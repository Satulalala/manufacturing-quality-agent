"""Small allowlisted tool registry with programmatic argument validation."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Callable


class ToolValidationError(ValueError):
    """Raised before a tool runs when a model action is outside its contract."""


def _json_safe(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, object]
    handler: Callable[[dict[str, object], dict[str, object]], dict[str, object]]


def _check_value(value: object, schema: dict[str, object], path: str) -> None:
    expected = schema.get("type")
    if expected == "string":
        if not isinstance(value, str):
            raise ToolValidationError(f"{path} must be a string")
        if len(value) > int(schema.get("maxLength", 1000)):
            raise ToolValidationError(f"{path} is too long")
        if "enum" in schema and value not in schema["enum"]:
            raise ToolValidationError(f"{path} is not an allowed value")
    elif expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ToolValidationError(f"{path} must be a finite number")
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolValidationError(f"{path} is below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolValidationError(f"{path} exceeds the maximum")
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolValidationError(f"{path} must be an integer")
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolValidationError(f"{path} is below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolValidationError(f"{path} exceeds the maximum")
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise ToolValidationError(f"{path} must be a boolean")
    elif expected == "array":
        if not isinstance(value, list):
            raise ToolValidationError(f"{path} must be an array")
        if len(value) > int(schema.get("maxItems", 100)):
            raise ToolValidationError(f"{path} has too many items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _check_value(item, item_schema, f"{path}[{index}]")
    elif expected == "object":
        if not isinstance(value, dict):
            raise ToolValidationError(f"{path} must be an object")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ToolValidationError(f"{path} has an invalid schema")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ToolValidationError(f"{path}.{key} is required")
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise ToolValidationError(f"{path} has unknown fields: {', '.join(sorted(extras))}")
        for key, item in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                _check_value(item, child_schema, f"{path}.{key}")
    else:
        raise ToolValidationError(f"{path} uses an unsupported schema type")


class ToolRegistry:
    """Register fixed functions; model output can select names, never code."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, object],
        handler: Callable[[dict[str, object], dict[str, object]], dict[str, object]],
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError("tool name is invalid")
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        if parameters.get("type") != "object":
            raise ValueError("tool parameters must use an object schema")
        if not callable(handler):
            raise ValueError("tool handler must be callable")
        self._tools[name] = ToolDefinition(name, description, parameters, handler)

    def descriptions(self) -> list[dict[str, object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]

    def validate(self, name: object, arguments: object) -> tuple[ToolDefinition, dict[str, object]]:
        if not isinstance(name, str) or name not in self._tools:
            raise ToolValidationError("tool name is not allowlisted")
        if not isinstance(arguments, dict):
            raise ToolValidationError("tool arguments must be an object")
        tool = self._tools[name]
        _check_value(arguments, tool.parameters, "arguments")
        # Ensure the validated payload has deterministic, JSON-compatible values.
        normalized = json.loads(json.dumps(arguments, ensure_ascii=False, allow_nan=False))
        return tool, normalized

    @staticmethod
    def validate_scope_arguments(arguments: dict[str, object], context: dict[str, object]) -> None:
        """Validate an optional model echo without allowing it to alter runtime filters."""

        supplied = arguments.get("user_filters")
        if supplied is None:
            return
        if not isinstance(supplied, list) or not all(isinstance(item, str) for item in supplied):
            raise ToolValidationError("user_filters must be an array of strings")
        filters = context.get("filters", {})
        if not isinstance(filters, dict):
            raise ToolValidationError("locked filters are invalid")
        expected: list[str] = []
        for key, value in filters.items():
            if value is None or value == "" or value == []:
                continue
            values = value if isinstance(value, list) else [value]
            expected.extend(f"{key}={item}" for item in values)
        if sorted(set(supplied)) != sorted(set(expected)):
            raise ToolValidationError("user_filters do not match the program-locked scope")

    def execute(
        self,
        name: object,
        arguments: object,
        context: dict[str, object],
    ) -> dict[str, object]:
        tool, normalized = self.validate(name, arguments)
        self.validate_scope_arguments(normalized, context)
        result = tool.handler(normalized, context)
        if not isinstance(result, dict):
            raise TypeError(f"tool {tool.name} returned a non-object result")
        serialized = json.dumps(_json_safe(result), ensure_ascii=False, allow_nan=False, default=str)
        if len(serialized.encode("utf-8")) > 64_000:
            raise ValueError(f"tool {tool.name} returned more than 64 KB; return compact evidence")
        return json.loads(serialized)
