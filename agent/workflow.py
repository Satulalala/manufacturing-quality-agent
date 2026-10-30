"""Ollama-understood quality Agent with deterministic analysis tools."""

from __future__ import annotations

import json
import inspect
import os
import time
from pathlib import Path
from typing import Callable, Iterable, Mapping
from uuid import uuid4

from agent.llm_parser import llm_timeout_seconds
from agent.tracing import configure_tracing, langsmith_context


Record = Mapping[str, object]


class AgentRunCancelled(Exception):
    """Raised between Agent stages when a local run is asked to stop."""


def parse_question(question: str) -> dict[str, object]:
    """Compatibility API; all natural-language parsing is performed by Ollama."""

    from agent.llm_parser import parse_with_llm

    return parse_with_llm(question)


def _recommendation(dimension: str) -> str:
    recommendations = {
        "workstation": "优先检查该工位的设备参数、工装状态和最近换型记录。",
        "shift": "对比该班次的交接班记录、人员配置和作业参数。",
        "supplier_id": "核查该供应商批次、来料检验记录和近期变更。",
        "batch_id": "追溯该批次的原料、工艺参数和维修记录。",
    }
    return recommendations.get(dimension, "结合现场记录进行人工确认。")


class QualityAgent:
    """Coordinate deterministic quality tools and produce an evidence report."""

    def __init__(
        self,
        records: Iterable[Record],
        llm_provider: str | None = None,
        log_dir: str | Path | None = None,
        *,
        model_fn=None,
        csv_path: str | Path | None = None,
        progress_fn=None,
        partial_report_fn=None,
        parse_fn: Callable | None = None,
        decision_fn: Callable | None = None,
        use_decision_loop: bool = True,
        source_id: str | None = None,
        data_version: str | None = None,
        session_store_path: str | Path | None = None,
        checkpoint_path: str | Path | None = None,
        result_store_path: str | Path | None = None,
        memory_store_path: str | Path | None = None,
        memory_owner_id: str = "local",
        event_log_path: str | Path | None = None,
    ):
        self.records = [dict(record) for record in records]
        from data.source_manager import records_content_hash

        self.data_version = str(data_version or records_content_hash(self.records))
        self.source_id = str(source_id or self.data_version)
        self.session_store_path = Path(session_store_path) if session_store_path else None
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else None
        self.result_store_path = Path(result_store_path) if result_store_path else None
        self.memory_store_path = Path(memory_store_path) if memory_store_path else None
        self.memory_owner_id = str(memory_owner_id or "local")
        self.event_log_path = Path(event_log_path) if event_log_path else None
        self.provider = llm_provider or "ollama"
        if self.provider != "ollama":
            raise ValueError(f"仅支持 Ollama 问题解析，当前配置为：{self.provider}")
        self.csv_path = str(csv_path) if csv_path is not None else None
        self.model_fn = model_fn
        self.progress_fn = progress_fn
        self.partial_report_fn = partial_report_fn
        self.decision_fn = decision_fn
        # use_decision_loop remains an accepted compatibility argument; data
        # analysis now always uses the bounded decision loop.
        self.llm_status = "disabled"
        self.trace_fn, self.tracing_status = configure_tracing()
        if model_fn is not None:
            self.llm_status = "injected"
        else:
            from agent.model_adapter import create_langchain_model_fn

            self.model_fn, self.llm_status = create_langchain_model_fn(self.provider)
        from agent.llm_parser import make_parse_fn

        self.parse_fn = parse_fn or make_parse_fn(self.provider)
        self.log_dir = Path(log_dir) if log_dir else None

    def _invoke_controlled_loop(
        self,
        question: str,
        parsed_query: dict[str, object] | None = None,
        run_id: str | None = None,
        *,
        session_id: str | None = None,
        recent_messages: list[dict[str, object]] | None = None,
        previous_reports: list[dict[str, object]] | None = None,
        pending_task: dict[str, object] | None = None,
        confirmed_preferences: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        from agent.decision import (
            build_quality_tool_registry,
            decide_with_ollama,
            required_tool_for_task,
            run_decision_loop,
        )
        from agent.graph import parse_node, report_node
        from agent.result_store import ResultStore, evidence_staleness
        from agent.state import initial_state
        from tools.quality_tools import filter_records

        if confirmed_preferences is None:
            confirmed_preferences = self._confirmed_preferences()
        state = initial_state(
            self.records,
            question,
            llm_provider=self.provider,
            csv_path=self.csv_path,
            model_fn=self.model_fn,
            llm_status=self.llm_status,
            tracing_status=self.tracing_status,
            progress_fn=self.progress_fn,
            partial_report_fn=self.partial_report_fn,
            parsed_query=parsed_query,
            confirmed_preferences=confirmed_preferences,
        )

        def bounded_parse(text: str) -> dict[str, object]:
            try:
                parameters = inspect.signature(self.parse_fn).parameters.values()
                accepts_timeout = any(
                    parameter.name == "timeout"
                    or parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                )
            except (TypeError, ValueError):
                accepts_timeout = False
            if not accepts_timeout:
                return self.parse_fn(text)
            return self.parse_fn(text, timeout=llm_timeout_seconds())

        with langsmith_context(self.tracing_status == "enabled"):
            state.update(parse_node(state, bounded_parse, self._apply_confirmed_specification))
            if state.get("missing_inputs"):
                state.update(report_node(state, trace_fn=self.trace_fn))
                return state

            task = str(state.get("task", "quality_analysis"))
            registry = build_quality_tool_registry(task, has_csv_path=bool(self.csv_path))

            def on_observation(observation: dict[str, object]) -> None:
                result = observation.get("result") or {}
                if (
                    observation.get("tool") == "quality_summary"
                    and observation.get("status") == "success"
                    and callable(self.partial_report_fn)
                    and isinstance(result, dict)
                ):
                    self.partial_report_fn(
                        {
                            "filters": state.get("filters", {}),
                            "baseline": result.get("baseline", {}),
                            "top_factors": result.get("top_factors", []),
                        }
                    )

            prior_evidence: list[dict[str, object]] = []
            stale_evidence: list[dict[str, object]] = []
            for old_report in (previous_reports or [])[-12:]:
                refs = old_report.get("evidence_refs", [])
                if not isinstance(refs, list):
                    continue
                for reference in refs:
                    if not isinstance(reference, dict):
                        continue
                    stale_reason = evidence_staleness(
                        reference,
                        data_version=self.data_version,
                        filters=state.get("filters", {}),
                    )
                    if stale_reason is None:
                        prior_evidence.append(reference)
                    else:
                        stale_evidence.append({
                            "evidence_id": reference.get("evidence_id"),
                            "tool": reference.get("tool"),
                            "summary": reference.get("summary", ""),
                            "reason": stale_reason,
                        })
            prior_evidence = prior_evidence[-12:]
            loop_result = run_decision_loop(
                question,
                registry,
                {
                    "records": self.records,
                    "filters": state.get("filters", {}),
                    "data_version": self.data_version,
                    "csv_path": self.csv_path,
                    "task": task,
                    "task_args": state.get("task_args", {}),
                    "pending_task": pending_task,
                    "recent_messages": recent_messages or [],
                    "prior_evidence": prior_evidence,
                    "stale_evidence_count": len(stale_evidence),
                    "confirmed_preferences": confirmed_preferences,
                },
                decide_fn=self.decision_fn or decide_with_ollama,
                total_budget_seconds=100.0,
                required_tools=required_tool_for_task(task),
                run_id=run_id,
                observation_fn=on_observation,
            )

        observations = loop_result.get("observations", [])
        evidence_refs = []
        result_store = ResultStore(self.result_store_path)
        for observation in observations:
            if isinstance(observation, dict):
                reference = result_store.save_observation(
                    observation,
                    session_id=session_id,
                    run_id=str(loop_result.get("run_id", run_id or "")),
                    filters=state.get("filters", {}),
                    data_version=self.data_version,
                )
                if reference is not None:
                    evidence_refs.append(reference)
        successful = [item for item in observations if item.get("status") == "success"]
        evidence_results = [
            item.get("result", {}) for item in successful if isinstance(item.get("result"), dict)
        ]
        for item in loop_result.get("events", []):
            state["trace"].append(
                {"tool": "agent_decision", "detail": f"{item.get('action')}:{item.get('tool') or ''}"}
            )
        for item in observations:
            state["trace"].append(
                {"tool": str(item.get("tool", "tool")), "detail": str(item.get("status", "unknown"))}
            )

        final_filters = dict(state.get("filters", {}))
        for result in reversed(evidence_results):
            if isinstance(result.get("filters"), dict):
                final_filters.update(result["filters"])
                break
        filtered = filter_records(self.records, **final_filters)
        baseline_result = next(
            (result["baseline"] for result in reversed(evidence_results) if isinstance(result.get("baseline"), dict)),
            None,
        )
        candidates = next(
            (result["top_factors"] for result in reversed(evidence_results) if isinstance(result.get("top_factors"), list)),
            [],
        )
        knowledge = next(
            (
                result for item, result in zip(successful, evidence_results)
                if item.get("tool") == "search_knowledge"
            ),
            {"status": "no_results", "results": [], "metadata": {}},
        )
        latest_result = evidence_results[-1] if evidence_results else {
            "status": "error",
            "evidence": loop_result.get("message") or loop_result.get("stop_reason"),
        }
        state.update(
            {
                "filters": final_filters,
                "filtered_records": filtered,
                "baseline": baseline_result or {
                    "total_count": 0,
                    "defect_count": 0,
                    "defect_rate": 0.0,
                    "defect_rate_percent": 0.0,
                },
                "candidates": candidates,
                "tool_result": latest_result,
                "knowledge": knowledge,
                "preserve_partial_evidence": True,
                "decision_loop": {
                    "run_id": loop_result.get("run_id"),
                    "status": loop_result.get("status"),
                    "stop_reason": loop_result.get("stop_reason"),
                    "decision_count": loop_result.get("decision_count", 0),
                    "tool_call_count": loop_result.get("tool_call_count", 0),
                    "tool_execution_count": loop_result.get("tool_execution_count", 0),
                    "cache_hit_count": loop_result.get("cache_hit_count", 0),
                    "retry_count": loop_result.get("retry_count", 0),
                    "context_budget": loop_result.get("context_budget", {}),
                    "events": loop_result.get("events", []),
                },
                "evidence_refs": evidence_refs,
                "stale_evidence_refs": stale_evidence,
            }
        )
        if loop_result.get("status") == "needs_input":
            state["missing_inputs"] = ["question_clarification"]
            state["clarification"] = str(loop_result.get("message") or "请补充完成分析所需的信息。")
            state["parse_error"] = "decision_needs_input"
        # The decision loop and explanation share the configured model timeout;
        # report_node still validates every numeric claim against tool evidence.
        progress = state.get("progress_fn")
        report_started = time.perf_counter()
        if callable(progress):
            progress("quality_agent_report", "start", None)
        state.update(report_node(state, trace_fn=self.trace_fn))
        if callable(progress):
            progress("quality_agent_report", "complete", round((time.perf_counter() - report_started) * 1000, 2))
        report = state["report"]
        report["decision_loop"] = state["decision_loop"]
        report["run_id"] = loop_result.get("run_id")
        report["evidence_refs"] = evidence_refs
        report["stale_evidence_refs"] = stale_evidence
        if loop_result.get("status") not in {"success", "needs_input", "no_data"}:
            report["status"] = "error"
            report["summary"] = (
                "决策循环未完成："
                + str(loop_result.get("message") or loop_result.get("stop_reason"))
                + (f" 已保留 {len(evidence_results)} 项工具观察。" if evidence_results else " 未产生可用工具证据。")
            )
        return state

    def _finish_report(
        self,
        report: dict[str, object],
        trace: list[dict[str, object]],
        top_n: int,
        started: float,
    ) -> dict[str, object]:
        if report["status"] == "success":
            report["top_factors"] = report["top_factors"][:top_n]
        report["trace"] = trace
        elapsed_ms = (time.perf_counter() - started) * 1000
        report["elapsed_ms"] = round(elapsed_ms, 2)

        if self.log_dir is not None:
            try:
                from agent.run_logger import log_run

                log_run(report, trace, self.provider, elapsed_ms, log_dir=self.log_dir)
            except Exception:
                pass
        return report

    def _session_store(self):
        from agent.session_store import SessionStore

        return SessionStore(self.session_store_path, self.checkpoint_path)

    def _confirmed_preferences(self) -> list[dict[str, object]]:
        from agent.memory_store import MemoryStore

        return MemoryStore(self.memory_store_path).confirmed_preferences(self.memory_owner_id)

    def _apply_confirmed_specification(self, parsed: dict[str, object]) -> dict[str, object]:
        from copy import deepcopy
        from math import isfinite

        query = deepcopy(parsed)
        if query.get("task") != "cpk":
            return query

        scope = self._cpk_specification_scope(query)
        memory_store = self._memory_store()
        existing_id = query.get("spec_memory_id")
        if existing_id:
            stored = memory_store.get_active(str(existing_id), owner_id=self.memory_owner_id)
            if stored is None or scope is None or stored.get("scope") != scope:
                query["usl"] = None
                query["lsl"] = None
                query["unit"] = ""
                query.pop("spec_memory_id", None)
                query.pop("spec_source", None)
            else:
                return query

        if scope is None or (query.get("usl") is not None and query.get("lsl") is not None and query.get("unit")):
            return query
        matches = memory_store.find_confirmed(
            owner_id=self.memory_owner_id,
            memory_type="specification",
            memory_key="cpk_specification",
            scope=scope,
        )
        if len(matches) > 1:
            query["clarification_needed"] = True
            query["clarification"] = "当前范围匹配到多条已确认规格，请先在长期记忆中整理冲突规格。"
            return query
        if not matches:
            return query

        memory = matches[0]
        content = memory.get("content")
        if not isinstance(content, dict):
            return query
        try:
            lsl, usl = float(content["lsl"]), float(content["usl"])
        except (KeyError, TypeError, ValueError):
            return query
        unit = str(content.get("unit", "")).strip()
        if not (isfinite(lsl) and isfinite(usl) and usl > lsl and unit):
            return query
        for key, value in (("lsl", lsl), ("usl", usl), ("unit", unit)):
            supplied = query.get(key)
            if supplied not in (None, ""):
                if key in {"lsl", "usl"}:
                    try:
                        if float(supplied) != value:
                            return query
                    except (TypeError, ValueError):
                        return query
                elif str(supplied).strip() != value:
                    return query
            query[key] = value
        query["spec_memory_id"] = memory["memory_id"]
        query["spec_source"] = "confirmed_memory"
        query["unit_confirmed"] = True
        return query

    def _cpk_specification_scope(self, query: dict[str, object]) -> dict[str, object] | None:
        lines = query.get("production_line")
        workstations = query.get("workstation")
        vehicle_model = str(query.get("vehicle_model") or "").strip()
        field = str(query.get("field") or "").strip()
        if (
            not isinstance(lines, list) or len(lines) != 1
            or not isinstance(workstations, list) or len(workstations) != 1
            or not vehicle_model or field not in {"torque", "pressure", "temperature"}
        ):
            return None
        return {
            "source_id": self.source_id,
            "data_version": self.data_version,
            "production_line": lines[0],
            "vehicle_model": vehicle_model,
            "workstation": workstations[0],
            "field": field,
        }

    def _memory_store(self):
        from agent.memory_store import MemoryStore

        return MemoryStore(self.memory_store_path)

    def get_evidence(self, evidence_id: str, *, session_id: str) -> dict[str, object] | None:
        from agent.result_store import ResultStore

        return ResultStore(self.result_store_path).get(evidence_id, session_id=session_id)

    def create_session(self, title: str = "新会话") -> dict[str, object]:
        return self._session_store().create_session(self.source_id, self.data_version, title)

    def get_session_state(self, session_id: str) -> dict[str, object]:
        return self._session_store().get_state(session_id)

    def _session_report(
        self,
        question: str,
        summary: str,
        *,
        status: str = "needs_input",
        missing: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "status": status,
            "question": question,
            "filters": {},
            "baseline": {
                "total_count": 0,
                "defect_count": 0,
                "defect_rate": 0.0,
                "defect_rate_percent": 0.0,
            },
            "top_factors": [],
            "summary": summary,
            "missing_inputs": missing or [],
            "trace": [],
            "elapsed_ms": 0.0,
        }

    def _direct_answer(self, question: str, previous: dict[str, object] | None = None) -> str:
        from agent.direct_answer import answer_direct_question

        state = previous or {}
        messages = [
            {"role": str(item.get("role", "")), "content": str(item.get("content", ""))[:1200]}
            for item in (state.get("messages", [])[-12:] if isinstance(state.get("messages"), list) else [])
            if isinstance(item, dict) and item.get("role") in {"user", "assistant"}
        ]
        reports = []
        for item in (state.get("reports", [])[-5:] if isinstance(state.get("reports"), list) else []):
            if not isinstance(item, dict):
                continue
            reports.append({
                key: item.get(key)
                for key in ("question", "summary", "explanation", "filters", "baseline", "task_label")
                if item.get(key) is not None
            })

        memories = []
        try:
            memories = [
                {
                    key: item.get(key)
                    for key in ("memory_type", "memory_key", "content", "scope", "unit", "source")
                    if item.get(key) is not None
                }
                for item in self._memory_store().list_memories(self.memory_owner_id)
                if item.get("confirmed_status") == "confirmed"
            ][-12:]
        except Exception:
            memories = []

        model = os.environ.get("QUALITY_LLM_MODEL", "qwen3:4b-q4_K_M")
        return answer_direct_question(
            question,
            recent_messages=messages,
            recent_reports=reports,
            memories=memories,
            model_context={
                "model": model,
                "thinking": "disabled; Ollama think=false and reasoning=false",
            },
        )

    def _direct_answer_report(
        self,
        question: str,
        previous: dict[str, object] | None = None,
        *,
        started: float,
        top_n: int,
    ) -> dict[str, object]:
        try:
            answer = self._direct_answer(question, previous)
            report = self._session_report(question, answer, status="success")
            report.update({
                "task": "direct_answer",
                "task_label": "直接回答",
                "summary": answer,
                "explanation": answer,
                "explanation_source": "model",
                "llm_status": self.llm_status,
            })
        except Exception as error:
            report = self._session_report(
                question,
                f"本地模型暂时无法直接回答（{type(error).__name__}）。请稍后重试。",
                status="error",
            )
            report.update({"task": "direct_answer", "task_label": "直接回答", "llm_status": self.llm_status})
        return self._finish_report(report, [], top_n, started)

    @staticmethod
    def _stored_report(question: str, report: dict[str, object], source_id: str, data_version: str):
        compact = {
            "question": question,
            "status": report.get("status"),
            "task": report.get("task"),
            "task_label": report.get("task_label"),
            "filters": report.get("filters", {}),
            "data_scope": report.get("data_scope"),
            "baseline": report.get("baseline", {}),
            "top_factors": report.get("top_factors", []),
            "summary": report.get("summary", ""),
            "explanation": report.get("explanation", ""),
            "explanation_citations": report.get("explanation_citations", []),
            "explanation_source": report.get("explanation_source", "deterministic"),
            "llm_status": report.get("llm_status", "disabled"),
            "response_style": report.get("response_style", "standard"),
            "source_id": source_id,
            "data_version": data_version,
            "run_id": report.get("run_id"),
            "task_id": report.get("task_id"),
            "decision_loop": report.get("decision_loop", {}),
            "evidence_refs": report.get("evidence_refs", []),
            "stale_evidence_refs": report.get("stale_evidence_refs", []),
        }
        return json.loads(json.dumps(compact, ensure_ascii=False, default=str))

    def _answer_in_session(
        self,
        question: str,
        top_n: int,
        started: float,
        session_id: str,
        submission_id: str | None = None,
    ) -> dict[str, object]:
        store = self._session_store()
        try:
            session = store.get_session(session_id)
        except ValueError:
            session = None
        if session is None:
            return self._session_report(
                question,
                "找不到该会话。请新建会话后重试。",
                missing=["session_id"],
            )
        if session["source_id"] != self.source_id or session["data_version"] != self.data_version:
            return self._session_report(
                question,
                "当前数据源内容与会话绑定版本不一致。请重新上传原数据，或新建会话。",
                missing=["matching_data_source"],
            )

        try:
            previous = store.get_state(session_id)
        except Exception:
            return self._session_report(
                question,
                "会话检查点无法读取；原会话未被覆盖。请重新选择会话或联系维护者检查本地数据库。",
                status="error",
            )
        if previous.get("schema_version") != 1:
            return self._session_report(
                question,
                "会话状态版本不兼容，暂未继续执行。",
                status="error",
                missing=["session_migration"],
            )
        if previous.get("source_id") != self.source_id or previous.get("data_version") != self.data_version:
            return self._session_report(
                question,
                "会话检查点绑定的数据版本与当前数据不一致，已停止分析。",
                missing=["matching_data_source"],
            )

        submission_reclaimed = False
        if submission_id:
            try:
                submission = store.claim_submission(session_id, submission_id)
            except ValueError:
                return self._session_report(question, "提交 ID 格式无效。", status="error")
            if not submission.get("claimed"):
                if submission.get("status") == "completed" and submission.get("report_json"):
                    return dict(submission.get("report") or {})
                return self._session_report(
                    question,
                    "这条提交正在处理中，已阻止重复执行。请稍后查看会话记录。",
                )
            submission_reclaimed = bool(submission.get("reclaimed"))

        pending_task = previous.get("pending_task")
        task_id = (
            str(pending_task.get("task_id"))
            if isinstance(pending_task, dict) and pending_task.get("task_id")
            else str(uuid4())
        )
        recovery_event = (
            "submission_recovered" if submission_reclaimed
            else "pending_task_resumed" if isinstance(pending_task, dict)
            else "session_resumed" if previous.get("messages")
            else "session_started"
        )
        run_id = submission_id or str(uuid4())

        def finish_submission(report: dict[str, object]) -> dict[str, object]:
            report["session_id"] = session_id
            report["source_id"] = self.source_id
            report["data_version"] = self.data_version
            report["run_id"] = run_id
            report["task_id"] = task_id
            try:
                from agent.run_logger import DEFAULT_EVENT_LOG, log_execution_event

                log_execution_event(
                    report,
                    session_id=session_id,
                    task_id=task_id,
                    data_version=self.data_version,
                    recovery_event=recovery_event,
                    event_log=self.event_log_path or DEFAULT_EVENT_LOG,
                )
            except Exception:
                pass
            return report

        def save_pending_response(
            report: dict[str, object],
            *,
            pending_task: dict[str, object] | None,
            active_query: dict[str, object] | None = None,
            status: str = "waiting_input",
            clear_pending: bool = False,
        ) -> dict[str, object]:
            report = self._finish_report(report, [], top_n, started)
            report = finish_submission(report)
            update: dict[str, object] = {
                "messages": [{"role": "assistant", "content": str(report.get("explanation") or report.get("summary", ""))}],
                "reports": [self._stored_report(question, report, self.source_id, self.data_version)],
                "status": status,
            }
            if pending_task is not None:
                update["pending_task"] = pending_task
            elif clear_pending:
                update["clear_pending_task"] = True
            if active_query is not None:
                update["active_query"] = active_query
                filter_keys = {
                    "start_date", "end_date", "production_line", "vehicle_model",
                    "workstation", "shift", "supplier_id", "batch_id", "defect_type",
                }
                update["active_filters"] = {
                    key: active_query[key] for key in filter_keys if key in active_query
                }
            store.update_state(session_id, **update)
            store.update_session(session_id, last_question=question, status=status)
            if submission_id:
                store.complete_submission(session_id, submission_id, report)
            return report

        store.update_state(session_id, messages=[{"role": "user", "content": question}], status="running")
        store.update_session(
            session_id,
            title=question if session.get("title") == "新会话" else None,
            last_question=question,
            status="running",
        )

        from agent.direct_answer import is_direct_question

        if is_direct_question(question) and not isinstance(pending_task, dict):
            report = self._direct_answer_report(question, previous, started=started, top_n=top_n)
            return save_pending_response(
                report,
                pending_task=pending_task if isinstance(pending_task, dict) else None,
                active_query=previous.get("active_query") if isinstance(previous.get("active_query"), dict) else None,
                status=(
                    "waiting_input" if isinstance(pending_task, dict)
                    else "failed" if report.get("status") == "error"
                    else "completed"
                ),
            )

        parsed_query = None
        pending_to_clear = False
        if isinstance(pending_task, dict):
            from agent.conversation import is_cancel_pending_request, pending_task_response

            if is_cancel_pending_request(question):
                recovery_event = "pending_task_cancelled"
                report = self._session_report(
                    question,
                    "已取消待补充任务；未运行 Cpk。可以继续提出新的调查问题。",
                    status="success",
                )
                return save_pending_response(
                    report,
                    pending_task=None,
                    status="completed",
                    clear_pending=True,
                )

            resolution = pending_task_response(question, pending_task)
            if resolution is not None:
                parsed_query = resolution["parsed_query"]
                if not resolution["complete"]:
                    report = self._session_report(
                        question,
                        str(resolution["message"]),
                        missing=list(resolution["pending_task"].get("missing_inputs", [])),
                    )
                    return save_pending_response(
                        report,
                        pending_task=resolution["pending_task"],
                        active_query=parsed_query,
                        status="waiting_input",
                    )
                pending_to_clear = True
            else:
                # A new task or changed scope invalidates the old pending work.
                pending_to_clear = True
                recovery_event = "pending_task_cancelled_then_new_task"

        if pending_to_clear and parsed_query is None:
            task_id = str(uuid4())

        prior_query = previous.get("active_query") or None
        if pending_to_clear and isinstance(prior_query, dict) and prior_query.get("task") == "cpk":
            prior_query = {
                **prior_query,
                "usl": None,
                "lsl": None,
                "unit": "",
            }
        if parsed_query is None and prior_query:
            from agent.conversation import explicit_filter_patch, is_condition_only_followup, merge_followup_query

            patch = explicit_filter_patch(question, prior_query)
            if is_condition_only_followup(question, patch):
                parsed_query = merge_followup_query(prior_query, question)
            else:
                try:
                    from agent.graph import _question_with_data_date_context

                    parsed = self.parse_fn(_question_with_data_date_context(question, self.records))
                    parsed_query = merge_followup_query(prior_query, question, parsed)
                except Exception as error:
                    parsed_query = merge_followup_query(prior_query, question)
                    parsed_query["clarification_needed"] = True
                    parsed_query["clarification"] = (
                        "无法可靠解析这次追问；已保留上一轮筛选条件，请明确要更换的条件或任务。"
                    )

        try:
            recent_messages = previous.get("messages", [])
            if not isinstance(recent_messages, list):
                recent_messages = []
            run_state = self._invoke_controlled_loop(
                question,
                parsed_query=parsed_query,
                run_id=run_id,
                session_id=session_id,
                recent_messages=[*recent_messages, {"role": "user", "content": question}],
                previous_reports=previous.get("reports", []),
                pending_task=(
                    pending_task
                    if isinstance(pending_task, dict) and not pending_to_clear
                    else None
                ),
            )
        except Exception as error:
            if isinstance(error, AgentRunCancelled):
                cancelled = self._session_report(
                    question,
                    "本轮分析已停止。未完成的统计不作为分析结果。",
                    status="cancelled",
                )
                cancelled = self._finish_report(cancelled, [], top_n, started)
                cancelled = finish_submission(cancelled)
                store.update_state(
                    session_id,
                    messages=[{"role": "assistant", "content": str(cancelled["summary"])}],
                    reports=[self._stored_report(question, cancelled, self.source_id, self.data_version)],
                    status="cancelled",
                )
                store.update_session(session_id, last_question=question, status="cancelled")
                if submission_id:
                    store.complete_submission(session_id, submission_id, cancelled)
                return cancelled
            failed = self._session_report(
                question,
                f"本轮执行异常（{type(error).__name__}），失败结果未标记为成功。",
                status="error",
            )
            failed["task"] = parsed_query.get("task") if isinstance(parsed_query, dict) else None
            failed = self._finish_report(failed, [], top_n, started)
            failed = finish_submission(failed)
            store.update_state(
                session_id,
                messages=[{"role": "assistant", "content": str(failed["summary"])}],
                reports=[self._stored_report(question, failed, self.source_id, self.data_version)],
                status="failed",
            )
            store.update_session(session_id, last_question=question, status="failed")
            if submission_id:
                store.complete_submission(session_id, submission_id, failed)
            return failed
        report = self._finish_report(
            run_state["report"],
            run_state.get("trace", []),
            top_n,
            started,
        )
        parsed_result = run_state.get("parsed_query")
        parse_ok = isinstance(parsed_result, dict) and not run_state.get("parse_error")
        pending_to_save = None
        if (
            report.get("status") == "needs_input"
            and isinstance(parsed_result, dict)
            and parsed_result.get("task") == "cpk"
        ):
            pending_to_save = {
                "task": "cpk",
                "task_id": task_id,
                "question": question,
                "parsed_query": parsed_result,
                "missing_inputs": report.get("missing_inputs", []),
                "unit_confirmed": bool(parsed_result.get("unit")),
                "source_id": self.source_id,
                "data_version": self.data_version,
            }
        report = finish_submission(report)
        checkpoint_update: dict[str, object] = {
            "messages": [{"role": "assistant", "content": str(report.get("explanation") or report.get("summary", ""))}],
            "reports": [self._stored_report(question, report, self.source_id, self.data_version)],
            "status": {
                "success": "completed",
                "no_data": "completed",
                "needs_input": "waiting_input",
                "error": "failed",
                "success": "completed",
            }.get(str(report.get("status")), "failed"),
        }
        if parse_ok:
            checkpoint_update["active_filters"] = run_state.get("filters", {})
            checkpoint_update["active_query"] = parsed_result
        if pending_to_save is not None:
            checkpoint_update["pending_task"] = pending_to_save
        elif pending_to_clear:
            checkpoint_update["clear_pending_task"] = True
        store.update_state(session_id, **checkpoint_update)
        store.update_session(
            session_id,
            last_question=question,
            status=str(checkpoint_update["status"]),
        )
        if submission_id:
            store.complete_submission(session_id, submission_id, report)
        return report

    def answer(
        self,
        question: str,
        top_n: int = 3,
        *,
        session_id: str | None = None,
        submission_id: str | None = None,
    ) -> dict[str, object]:
        started = time.perf_counter()
        if session_id:
            return self._answer_in_session(question, top_n, started, session_id, submission_id)
        from agent.direct_answer import is_direct_question

        if is_direct_question(question):
            return self._direct_answer_report(question, started=started, top_n=top_n)
        run_id = submission_id or str(uuid4())
        run_state = self._invoke_controlled_loop(question, run_id=run_id)
        report = self._finish_report(run_state["report"], run_state.get("trace", []), top_n, started)
        task_id = str(uuid4())
        report.update({
            "run_id": run_id,
            "task_id": task_id,
            "source_id": self.source_id,
            "data_version": self.data_version,
        })
        try:
            from agent.run_logger import DEFAULT_EVENT_LOG, log_execution_event

            log_execution_event(
                report,
                session_id=None,
                task_id=task_id,
                data_version=self.data_version,
                recovery_event="direct_run",
                event_log=self.event_log_path or DEFAULT_EVENT_LOG,
            )
        except Exception:
            pass
        return report

    def run(
        self,
        question: str,
        top_n: int = 3,
        *,
        session_id: str | None = None,
        submission_id: str | None = None,
    ) -> dict[str, object]:
        """Public task-routing API; ``answer`` remains a backwards-compatible alias."""

        return self.answer(question, top_n=top_n, session_id=session_id, submission_id=submission_id)


def render_text_report(report: Mapping[str, object]) -> str:
    """Render a report for the command line and README screenshots."""

    lines = [f"状态：{report['status']}", f"结论：{report['summary']}"]
    task_label = report.get("task_label")
    if task_label:
        lines.append(f"任务：{task_label}")
    baseline = report["baseline"]
    lines.append(
        f"数据：{baseline['total_count']} 条，缺陷 {baseline['defect_count']} 条，"
        f"不良率 {float(baseline['defect_rate_percent']):.2f}%"
    )
    factors = report["top_factors"]
    if factors:
        lines.append("候选因素：")
        for index, factor in enumerate(factors, start=1):
            lines.append(
                f"{index}. {factor['dimension']}={factor['value']}，"
                f"不良率 {float(factor['defect_rate_percent']):.2f}%，"
                f"样本 {factor['sample_count']}；{factor['recommendation']}"
            )
            lines.append(f"   证据：{factor['evidence']}")
    tool_result = report.get("tool_result") or {}
    result_evidence = tool_result.get("evidence")
    if result_evidence and str(result_evidence) not in str(report.get("summary", "")):
        lines.append(f"工具结果：{result_evidence}")
    if "row_count" in tool_result:
        lines.append(f"只读查询返回 {tool_result['row_count']} 条记录。")
    if report.get("missing_inputs"):
        lines.append("需补充：" + "、".join(str(item) for item in report["missing_inputs"]))
    if report.get("explanation"):
        lines.append(f"解释：{report['explanation']}")
        source_labels = {"model": "模型", "fallback": "模型回退", "deterministic": "确定性说明"}
        source = source_labels.get(str(report.get("explanation_source")), report.get("explanation_source"))
        if source:
            lines.append(f"解释方式：{source}")
        citations = report.get("explanation_citations", [])
        if citations:
            lines.append("解释证据：" + "、".join(str(item) for item in citations))
    for limitation in report.get("limitations", []):
        lines.append(f"提示：{limitation}")
    if report.get("knowledge_refs"):
        lines.append("知识库引用：")
        for item in report["knowledge_refs"]:
            lines.append(f"- {item['doc']}（{item['section']}）")
    elif report.get("knowledge_summary"):
        lines.append(f"知识库：{report['knowledge_summary']}")
    if report.get("trace"):
        lines.append("调用链：" + " → ".join(step["tool"] for step in report["trace"]))
    return "\n".join(lines)
