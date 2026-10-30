"""Small, validated condition patches for same-session follow-up questions."""

from __future__ import annotations

import calendar
import math
import re
from copy import deepcopy
from datetime import date


_CHINESE_MONTHS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}
_CHINESE_QUARTERS = {"一": 1, "二": 2, "三": 3, "四": 4}
_TASK_MARKERS = re.compile(
    r"\b(?:cpk|spc|sql)\b|质量分析|质量问题|不良率|缺陷率|能力指数|过程能力|控制图|异常检测|知识库|案例|只读查询|工位风险",
    re.IGNORECASE,
)
_DATE_REFERENCE = re.compile(
    r"\d{4}\s*年|(?:\d{1,2}|[一二三四五六七八九十]+)\s*月|上半年|下半年|半年度|上旬|中旬|下旬|"
    r"季度|第\s*[一二三四1-4]\s*季|\bQ[1-4]\b|全年|整年|年初|年末|"
    r"\bH[12]\b|年度|春季|夏季|秋季|冬季|日期|时间|月份|今年|去年|前年|本月|上月|下月|本周|上周|下周|最近|同期|截至|早于|之前|晚于|之后|"
    r"近\s*\d+\s*(?:天|日|周|星期|个月|月|季度|年)|过去\s*\d+",
    re.IGNORECASE,
)
_FILTER_MARKERS = {
    "production_line": r"产线|生产线|[A-Za-z]\s*线",
    "vehicle_model": r"车型|车款",
    "workstation": r"工位|工作站",
    "shift": r"班次|班组|班",
    "supplier_id": r"供应商|supplier",
    "batch_id": r"批次|batch",
    "defect_type": r"缺陷|故障",
}


def _month_number(value: str) -> int | None:
    if value.isdigit():
        month = int(value)
    else:
        month = _CHINESE_MONTHS.get(value)
    return month if month is not None and 1 <= month <= 12 else None


def _year_from_previous(previous: dict[str, object]) -> int | None:
    years = {
        int(value[:4])
        for key in ("start_date", "end_date")
        if (value := str(previous.get(key) or ""))
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    }
    return next(iter(years)) if len(years) == 1 else None


def _calendar_month_patch(text: str, previous: dict[str, object]) -> dict[str, object]:
    """Resolve complete calendar months without dropping named months or years."""
    number = r"(?:\d{1,2}|十一|十二|[一二三四五六七八九十]+)"
    # Day-level and relative bounds belong to the model parser, not a full-month patch.
    if re.search(r"\d{4}-\d{2}-\d{2}|月\s*(?:份\s*)?(?:\d+|[一二三四五六七八九十]+)\s*[日号]|上旬|中旬|下旬|月初|月末|月\s*(?:之前|之后|以前|以后|以来|起|前|后)", text):
        return {}
    connector = r"(?:以及|和|与|及|、|,|，|到|至|~|～|—|–|-)"
    expression = re.compile(
        rf"(?<![\d前近])(?:\d{{4}}\s*年\s*)?{number}\s*(?:月(?:份)?)?"
        rf"(?:\s*{connector}\s*(?:\d{{4}}\s*年\s*)?{number}\s*(?:月(?:份)?)?)*\s*月(?:份)?"
    )
    matches = list(expression.finditer(text))
    if not matches:
        return {}

    def unclear(message: str) -> dict[str, object]:
        return {"start_date": None, "end_date": None, "date_filter_requested": True,
                "date_scope": "unclear", "clarification_needed": True, "clarification": message,
                "scope_issue": "date_range"}

    if len(matches) != 1:
        return unclear("检测到多个独立日期条件，请明确本轮要合并分析的日期范围。")
    token = re.compile(rf"(?:(\d{{4}})\s*年\s*)?({number})\s*(?:月(?:份)?)?")
    parts = [(int(item.group(1)) if item.group(1) else None, _month_number(item.group(2)))
             for item in token.finditer(matches[0].group())]
    if any(month is None for _, month in parts):
        return unclear("月份必须在1月至12月之间，请更正日期条件。")
    explicit_years = [year for year, _ in parts if year is not None]
    all_years = {int(value) for value in re.findall(r"(?<!\d)(\d{4})\s*年", text)}
    if len(all_years) > 1 and not all_years.issubset(explicit_years):
        return unclear("检测到多个年份，请为每个日期条件明确年份，避免遗漏年度数据。")
    reference_year = _year_from_previous(previous)
    relative = re.search(r"今年|去年|前年", text)
    if relative:
        reference_year = date.today().year - {"今年": 0, "去年": 1, "前年": 2}[relative.group()]
    year = explicit_years[0] if explicit_years else reference_year
    if year is None:
        return unclear("无法唯一确定月份所属年份，请明确年份，例如“2026年7月和8月”。")
    is_range = len(parts) == 2 and bool(re.search(r"到|至|~|～|—|–|-", matches[0].group()))
    months = []
    for index, (explicit_year, month) in enumerate(parts):
        if explicit_year is not None:
            year = explicit_year
        elif index and is_range and month < months[-1][1]:
            year += 1
        months.append((year, month))
    if is_range and parts[0][0] is None and parts[1][0] is not None and months[0] > months[1]:
        months[0] = (months[1][0] - 1, months[0][1])
    if is_range and months[0] > months[-1]:
        return unclear("日期范围结束月份早于开始月份，请更正起止年份。")
    ordered = sorted(set(months))
    indices = [year * 12 + month for year, month in ordered]
    if not is_range and indices[-1] - indices[0] + 1 != len(indices):
        return unclear("本轮包含不连续月份，不能将中间月份一并纳入；请分别提问或提供一个连续日期范围。")
    first_year, first_month = ordered[0]
    last_year, last_month = ordered[-1]
    return {"start_date": f"{first_year:04d}-{first_month:02d}-01",
            "end_date": f"{last_year:04d}-{last_month:02d}-{calendar.monthrange(last_year, last_month)[1]:02d}",
            "date_filter_requested": True, "date_scope": "range"}


def _has_filter_value(value: object) -> bool:
    if isinstance(value, list):
        return any(_has_filter_value(item) for item in value)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _parsed_filter_is_explicit(key: str, value: object, question: str) -> bool:
    if not _has_filter_value(value):
        return False
    text = question.casefold()
    candidates = value if isinstance(value, list) else [value]
    if any(len(str(item).strip()) >= 2 and str(item).strip().casefold() in text for item in candidates):
        return True
    marker = _FILTER_MARKERS.get(key)
    return bool(marker and re.search(marker, question, re.IGNORECASE))


def explicit_filter_patch(question: str, previous: dict[str, object]) -> dict[str, object]:
    """Extract only unambiguous, user-stated filter changes."""

    patch: dict[str, object] = {}
    text = question.strip()
    # The year may precede a line name rather than the month ("2025年B产线7月").
    explicit_years = set(re.findall(r"(?<!\d)(\d{4})\s*年", text))
    if len(explicit_years) == 1:
        year = next(iter(explicit_years))
        previous = {**previous, "start_date": f"{year}-01-01", "end_date": f"{year}-12-31"}

    if re.search(r"(?:清除|取消|移除)\s*(?:所有|全部)?\s*(?:筛选|过滤|条件)|(?:恢复|切回)\s*全量数据", text):
        patch.update({
            "start_date": None,
            "end_date": None,
            "date_filter_requested": False,
            "date_scope": "all_data",
            "production_line": [],
            "vehicle_model": "",
            "workstation": [],
            "shift": [],
            "supplier_id": [],
            "batch_id": [],
            "defect_type": [],
        })
        return patch

    if re.search(r"(?:所有|全部|各|不限|不限定)\s*产线|(?:清除|取消|移除)\s*产线", text):
        patch["production_line"] = []
    else:
        line_clauses = list(re.finditer(
            r"((?:[A-Za-z]\s*(?:(?:和|与|、|,|，)\s*)?)*)\s*(?:生产线|产线|线)",
            text,
        ))
        lines = {line for clause in line_clauses for line in re.findall(r"[A-Za-z]", clause.group(1).upper())}
        if lines:
            patch["production_line"] = sorted(lines)
        elif re.search(r"(?:不限|不限定|清除|取消)\s*产线", text):
            patch["production_line"] = []

    if re.search(r"(?:不限|不限定|清除|取消)\s*(?:车型|车款)", text):
        patch["vehicle_model"] = ""
    else:
        model_match = re.search(
            r"(?:车型|车款)\s*(?:是|为|[:：=])?\s*([A-Za-z0-9][A-Za-z0-9_-]*)",
            text,
            re.IGNORECASE,
        )
        if model_match:
            patch["vehicle_model"] = model_match.group(1)

    workstation = re.search(
        r"(?:工位|工作站)\s*[：:=#]?\s*([A-Za-z]?[-_]?[A-Za-z0-9]+)|"
        r"([A-Za-z]?[-_]?[A-Za-z0-9]+)\s*(?:工位|工作站)",
        text,
        re.IGNORECASE,
    )
    if workstation:
        patch["workstation"] = [next(value for value in workstation.groups() if value).upper()]
    elif re.search(r"(?:不限|不限定|清除|取消)\s*(?:工位|工作站)", text):
        patch["workstation"] = []

    shifts = [value for value in ("夜班", "白班", "早班", "中班") if value in text]
    if shifts:
        patch["shift"] = shifts
    elif re.search(r"\b(?:day|night)\s*班?\b", text, re.IGNORECASE):
        shift = re.search(r"\b(day|night)\s*班?\b", text, re.IGNORECASE)
        patch["shift"] = [shift.group(1).capitalize()]
    elif re.search(r"(?:不限|不限定|清除|取消)\s*(?:班次|班组)", text):
        patch["shift"] = []

    for field, label in (("supplier_id", r"供应商"), ("batch_id", r"批次")):
        match = re.search(
            rf"{label}(?:编号|号码?|号|ID)?\s*(?:是|为|[:：=#])?\s*([A-Za-z0-9_-]+)",
            text,
            re.IGNORECASE,
        )
        if match:
            patch[field] = [match.group(1)]
        elif re.search(rf"(?:不限|不限定|清除|取消)\s*{label}", text):
            patch[field] = []

    if re.search(r"(?:不限|不限定|清除|取消)\s*(?:缺陷类型|缺陷)", text):
        patch["defect_type"] = []
    else:
        defect_match = re.search(
            r"(?:缺陷类型)\s*(?:是|为|[:：=])?\s*([\u4e00-\u9fffA-Za-z0-9_-]+)|"
            r"(?:只看|筛选|查看)\s*([\u4e00-\u9fffA-Za-z0-9_-]+)\s*缺陷",
            text,
        )
        if defect_match:
            patch["defect_type"] = [next(value for value in defect_match.groups() if value)]

    if re.search(r"(?:不限|不限定|清除|取消)\s*(?:日期|时间|日期范围|时间范围)|(?:所有|全部)\s*(?:日期|时间|月份)", text):
        patch["start_date"] = None
        patch["end_date"] = None
        patch["date_filter_requested"] = False
        patch["date_scope"] = "all_data"
    else:
        date_range = re.search(
            r"(\d{4}-\d{2}-\d{2})\s*(?:到|至|~|～|—|–)\s*(\d{4}-\d{2}-\d{2})",
            text,
        )
        iso_dates = re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", text)
        if len(iso_dates) > 1 and (len(iso_dates) != 2 or date_range is None):
            patch.update({"start_date": None, "end_date": None, "date_filter_requested": True,
                          "date_scope": "unclear", "clarification_needed": True,
                          "scope_issue": "date_range",
                          "clarification": "检测到多个独立日期或日期区间，请明确一个连续范围，避免漏选或纳入额外日期。"})
        elif date_range:
            patch["start_date"], patch["end_date"] = date_range.groups()
        else:
            single_date = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", text)
            if single_date:
                patch["start_date"] = patch["end_date"] = single_date.group(1)
            else:
                patch.update(_calendar_month_patch(text, previous))
                half_match = re.search(
                    r"(?:(\d{4})\s*年?\s*)?(上半年|下半年|上半年度|下半年度|前半年|后半年)",
                    text,
                )
                if half_match and not ("start_date" in patch or "end_date" in patch):
                    year_text, half = half_match.groups()
                    year = int(year_text) if year_text else _year_from_previous(previous)
                    if year is not None:
                        first_month, last_month = (1, 6) if half in {"上半年", "上半年度", "前半年"} else (7, 12)
                        patch["start_date"] = f"{year:04d}-{first_month:02d}-01"
                        patch["end_date"] = f"{year:04d}-{last_month:02d}-{calendar.monthrange(year, last_month)[1]:02d}"
                quarter_match = re.search(
                    r"(?:(\d{4})\s*年?\s*)?(?:第?\s*([一二三四1-4])\s*季度|Q([1-4]))",
                    text,
                    re.IGNORECASE,
                )
                if quarter_match and not ("start_date" in patch or "end_date" in patch):
                    year_text, quarter_text, arabic_quarter = quarter_match.groups()
                    quarter = int(arabic_quarter) if arabic_quarter else _CHINESE_QUARTERS.get(quarter_text, int(quarter_text) if quarter_text.isdigit() else None)
                    year = int(year_text) if year_text else _year_from_previous(previous)
                    if year is not None and quarter is not None:
                        first_month = (quarter - 1) * 3 + 1
                        last_month = first_month + 2
                        patch["start_date"] = f"{year:04d}-{first_month:02d}-01"
                        patch["end_date"] = f"{year:04d}-{last_month:02d}-{calendar.monthrange(year, last_month)[1]:02d}"
                year_match = re.search(r"(?:(\d{4})\s*年\s*)?(全年|整年|全年度)", text)
                if year_match and not ("start_date" in patch or "end_date" in patch):
                    year = int(year_match.group(1)) if year_match.group(1) else _year_from_previous(previous)
                    if year is not None:
                        patch["start_date"] = f"{year:04d}-01-01"
                        patch["end_date"] = f"{year:04d}-12-31"

        if ("start_date" in patch or "end_date" in patch) and patch.get("date_scope") != "unclear":
            patch["date_filter_requested"] = True
            patch["date_scope"] = "range"

    return patch


def validate_requested_scope(
    question: str, parsed: dict[str, object], reference: dict[str, object],
) -> dict[str, object]:
    """Make explicit calendar/line constraints authoritative over model guesses."""
    result = deepcopy(parsed)
    patch = explicit_filter_patch(question, reference)
    scope_keys = ("start_date", "end_date", "date_filter_requested", "date_scope", "production_line")
    result.update({key: patch[key] for key in scope_keys if key in patch})
    if patch.get("date_scope") == "range" and result.get("scope_issue") == "date_range":
        result.update({"clarification_needed": False, "clarification": ""})
        result.pop("scope_issue", None)
    if patch.get("clarification_needed"):
        result.update({"clarification_needed": True, "clarification": patch["clarification"],
                       "scope_issue": "date_range"})
    if (not any(key in patch for key in ("start_date", "end_date"))
            and re.search(r"上半年|下半年|季度|\bQ[1-4]\b|全年|整年", question, re.IGNORECASE)
            and not re.search(r"\d{4}\s*年|今年|去年|前年", question)
            and _year_from_previous(reference) is None):
        result.update({"start_date": None, "end_date": None, "date_filter_requested": True,
                       "date_scope": "unclear", "clarification_needed": True,
                       "scope_issue": "date_range",
                       "clarification": "数据包含多个年份，请明确本轮时间范围所属年份。"})
    return result


def is_condition_only_followup(question: str, patch: dict[str, object]) -> bool:
    """Use deterministic handling only when the user explicitly changed a filter."""

    if not patch or _TASK_MARKERS.search(question):
        return False
    has_date_patch = patch.get("date_scope") in {"range", "all_data"} or "start_date" in patch or "end_date" in patch
    return not (_DATE_REFERENCE.search(question) and not has_date_patch)


def merge_followup_query(
    previous: dict[str, object] | None,
    question: str,
    parsed: dict[str, object] | None = None,
) -> dict[str, object]:
    """Merge explicit changes, preserving prior conditions that were not mentioned."""

    if previous is None:
        if parsed is None:
            raise ValueError("首次会话需要完整解析结果")
        result = deepcopy(parsed)
        result["interpretation"] = question
        return result

    result = deepcopy(parsed if parsed is not None else previous)
    patch = explicit_filter_patch(question, previous)

    date_patch = patch.get("date_scope") in {"range", "all_data"} or "start_date" in patch or "end_date" in patch
    parsed_start = parsed.get("start_date") if parsed else None
    parsed_end = parsed.get("end_date") if parsed else None
    parsed_date_scope = parsed.get("date_scope") if parsed else None
    parsed_date_requested = bool(
        parsed
        and (
            parsed.get("date_filter_requested") is True
            or parsed_date_scope == "range"
            or _DATE_REFERENCE.search(question)
        )
    )
    parsed_has_dates = bool((parsed_start or parsed_end) and parsed_date_requested)
    parsed_date_unclear = bool(
        not parsed_has_dates
        and (
            (parsed is not None and (
                parsed_date_scope in {"range", "unclear"}
                or parsed_date_requested
            ))
            or _DATE_REFERENCE.search(question)
        )
    )

    if date_patch:
        pass
    elif parsed_has_dates:
        result["start_date"] = parsed_start
        result["end_date"] = parsed_end
    elif parsed_date_unclear:
        result["start_date"] = None
        result["end_date"] = None
        result["date_scope"] = "unclear"
        result["date_filter_requested"] = True
    else:
        for key in ("start_date", "end_date", "date_filter_requested", "date_scope"):
            if key in previous:
                result[key] = deepcopy(previous[key])

    for key in ("production_line", "vehicle_model", "workstation", "shift", "supplier_id", "batch_id", "defect_type"):
        if key in patch:
            continue
        if parsed is not None and _parsed_filter_is_explicit(key, parsed.get(key), question):
            continue
        if key in previous:
            result[key] = deepcopy(previous[key])
    result.update(patch)

    if parsed is None:
        for key, value in previous.items():
            result.setdefault(key, deepcopy(value))

    start_date = result.get("start_date")
    end_date = result.get("end_date")
    if start_date is not None:
        date.fromisoformat(str(start_date))
    if end_date is not None:
        date.fromisoformat(str(end_date))
    if start_date and end_date and str(start_date) > str(end_date):
        raise ValueError("日期范围结束日期早于开始日期")

    result["interpretation"] = question
    if result.get("date_scope") == "unclear":
        result["date_filter_requested"] = True
    else:
        result["date_filter_requested"] = bool(result.get("start_date") or result.get("end_date"))
        result["date_scope"] = "range" if result["date_filter_requested"] else "all_data"
    return result


def is_cancel_pending_request(question: str) -> bool:
    return bool(
        re.search(
            r"(?:取消|撤销|放弃|终止)(?:这个|当前|该)?(?:任务|计算|分析)|先不算|先取消",
            question,
        )
    )


def pending_task_response(
    question: str,
    pending_task: dict[str, object],
) -> dict[str, object] | None:
    """Apply only explicit Cpk specification/unit slots to a saved task."""

    if pending_task.get("task") != "cpk":
        return None
    text = question.strip()
    parsed_query = pending_task.get("parsed_query")
    if not isinstance(parsed_query, dict):
        return None
    updated_query = deepcopy(parsed_query)
    recognized = False

    for token, field in (("扭矩", "torque"), ("压力", "pressure"), ("温度", "temperature")):
        if token in text:
            updated_query["field"] = field
            recognized = True
            break

    for key, labels in (("lsl", r"下限|LSL|下规格限"), ("usl", r"上限|USL|上规格限")):
        match = re.search(rf"(?:{labels})\s*(?:为|是|[:：=])?\s*(-?\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            if math.isfinite(value):
                updated_query[key] = value
                recognized = True

    unit_match = re.search(
        r"(?:单位\s*(?:是|为|[:：=])\s*)([A-Za-z0-9°℃µμ·.*^/_-]+|[\u4e00-\u9fff]{1,8})",
        text,
        re.IGNORECASE,
    )
    if unit_match:
        updated_query["unit"] = unit_match.group(1).strip()[:32]
        recognized = True
    else:
        unit_match = re.search(
            r"(?<![A-Za-z])(?:N\s*[·⋅.]\s*m|N\s*m|kgf\s*[·.]?\s*cm|kPa|MPa|Pa|psi|bar|°\s*C|°\s*F|℃|摄氏度|华氏度)(?![A-Za-z])",
            text,
            re.IGNORECASE,
        )
        if unit_match:
            updated_query["unit"] = re.sub(r"\s+", "", unit_match.group(0))[:32]
            recognized = True

    confirmed = bool(re.search(r"确认|确定|与数据一致|适用当前|适用于当前|适用该范围", text))
    if confirmed:
        recognized = True
    if not recognized:
        return None

    unit_confirmed = bool(pending_task.get("unit_confirmed")) or confirmed
    missing = []
    if updated_query.get("field") not in {"torque", "pressure", "temperature"}:
        missing.append("field")
    lsl, usl = updated_query.get("lsl"), updated_query.get("usl")
    if lsl is None:
        missing.append("lsl")
    if usl is None:
        missing.append("usl")
    if lsl is not None and usl is not None and float(usl) <= float(lsl):
        missing.extend(("lsl", "usl"))
    if not updated_query.get("unit"):
        missing.append("unit")
    elif not unit_confirmed:
        missing.append("unit_confirmation")

    updated_pending = {
        **pending_task,
        "parsed_query": updated_query,
        "unit_confirmed": unit_confirmed,
        "missing_inputs": list(dict.fromkeys(missing)),
    }
    if missing:
        if "field" in missing:
            message = "请补充工艺参数（扭矩、压力或温度）。"
        elif "unit" in missing:
            message = "请补充规格单位，并确认它与当前数据列单位一致；系统不会自动换算单位。"
        elif "unit_confirmation" in missing:
            message = f"已记录规格范围，请确认 {updated_query['unit']} 与当前数据列单位一致，再继续计算。"
        elif "lsl" in missing or "usl" in missing:
            message = "请补齐上下限，并确保 USL 大于 LSL。"
        else:
            message = "USL 必须大于 LSL，请更正规格范围。"
        return {
            "complete": False,
            "parsed_query": updated_query,
            "pending_task": updated_pending,
            "message": message,
        }

    updated_query["clarification_needed"] = False
    updated_query["interpretation"] = str(pending_task.get("question") or question)
    return {
        "complete": True,
        "parsed_query": updated_query,
        "pending_task": updated_pending,
        "message": "规格和单位已确认，继续执行原 Cpk 任务。",
    }

