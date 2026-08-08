"""Streamlit dashboard for the manufacturing-quality Agent."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent
_MPL_CACHE = _APP_ROOT / ".cache" / "matplotlib"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))
os.environ.setdefault("WINDIR", os.environ.get("SystemRoot", r"C:\Windows"))

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from agent.workflow import QualityAgent
from data.demo_data import generate_records, load_records, write_records
from tools.quality_tools import filter_records


DATA_PATH = _APP_ROOT / "data" / "demo_records.csv"
DEFAULT_QUESTION = "请分析 2026-01-01 到 2026-01-31 A产线的不良率异常"
REQUIRED_COLUMNS = {"timestamp", "production_line", "workstation", "shift", "supplier_id", "result"}
DIMENSION_LABELS = {
    "workstation": "工位",
    "shift": "班次",
    "supplier_id": "供应商",
    "batch_id": "批次",
}
LLM_PROVIDERS = {"mock": "模拟器（规则，无需配置）", "ollama": "本地 Ollama", "glm": "智谱 GLM"}
TRACE_ICONS = {
    "parse_question": "search",
    "filter_records": "filter_alt",
    "rank_candidate_causes": "leaderboard",
    "retrieve_quality_documents": "menu_book",
    "generate_report": "description",
}


def format_filters(filters: dict[str, object]) -> str:
    start = str(filters.get("start_date") or "不限")
    end = str(filters.get("end_date") or "不限")
    line = filters.get("production_line")
    if isinstance(line, list):
        line_text = "、".join(str(item) for item in line)
    else:
        line_text = str(line) if line else "不限"
    model = str(filters.get("vehicle_model") or "不限")
    return f"{start} ~ {end} · 产线 {line_text} · 车型 {model}"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


st.set_page_config(page_title="制造质量分析台", page_icon=None, layout="wide")
st.markdown(
    """
    <style>
    :root {
        --ink: #17201c;
        --muted: #5f6c65;
        --line: #d8ded9;
        --surface: #ffffff;
        --canvas: #f4f6f3;
        --accent: #176b52;
        --critical: #b63b35;
        --warning: #9a6718;
    }
    .stApp { background: var(--canvas); color: var(--ink); }
    .block-container { max-width: 1440px; padding-top: 1.5rem; padding-bottom: 2rem; }
    [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--line); }
    [data-testid="stSidebar"] * { color: var(--ink); }
    [data-testid="stSidebar"] h3 { margin-top: 0.25rem; font-size: 1.05rem !important; }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: var(--muted); }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        background: #f4f6f3; border: 1px dashed #aeb8b1; border-radius: 6px;
        padding: 0.25rem;
    }
    [data-testid="stSidebar"] [data-baseweb="textarea"] textarea {
        background: #ffffff; color: var(--ink); border: 1px solid var(--line); border-radius: 6px;
    }
    [data-testid="stSidebar"] [data-baseweb="textarea"] textarea:focus {
        border-color: var(--accent);
    }
    [data-testid="stSidebar"] [data-baseweb="select"] > div {
        border: 1px solid var(--line) !important; border-radius: 6px; background: #ffffff;
    }
    [data-testid="stSidebar"] [data-baseweb="popover"] { border: 1px solid var(--line); border-radius: 6px; }
    [data-testid="stSidebar"] [data-baseweb="popover"] * { color: var(--ink) !important; }
    [data-testid="stSidebar"] [data-baseweb="popover"] li:hover { background: #edf5f0; }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div > [data-testid="stVerticalBlockBorderWrapper"] {
        background: #f8faf9; border: 1px solid var(--line); border-radius: 6px; padding: 0.75rem 0.9rem;
    }
    [data-testid="stSidebar"] .stButton button {
        width: 100%; background: #176b52; color: #ffffff; border: 0;
        border-radius: 6px; font-weight: 700; min-height: 2.75rem;
    }
    [data-testid="stSidebar"] .stButton button:hover { background: #145a46; color: #ffffff; }
    [data-testid="stMetric"] {
        min-height: 116px; background: var(--surface); border: 1px solid var(--line);
        border-radius: 6px; padding: 0.85rem 1rem;
    }
    [data-testid="stMetricLabel"] { color: var(--muted); }
    [data-testid="stMetricValue"] { color: var(--ink); font-weight: 700; }
    [data-testid="stDataFrame"], [data-testid="stImage"] {
        background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 0.5rem;
    }
    h1, h2, h3 { color: var(--ink); letter-spacing: 0; }
    h1 { font-size: 1.75rem !important; }
    h2 { font-size: 1.15rem !important; margin-top: 1.25rem !important; }
    .analysis-summary {
        background: #edf5f0; border-left: 4px solid var(--accent); color: var(--ink);
        padding: 0.9rem 1rem; margin: 0.75rem 0 1rem; border-radius: 0 4px 4px 0;
    }
    .data-note { color: var(--muted); font-size: 0.84rem; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
    }
    @media (max-width: 768px) {
        .block-container { padding: 1rem 0.75rem; }
        h1 { font-size: 1.45rem !important; }
        [data-testid="stMetric"] { min-height: 96px; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def get_demo_records() -> list[dict[str, object]]:
    if DATA_PATH.exists():
        return load_records(DATA_PATH)
    records = generate_records()
    write_records(records, DATA_PATH)
    return records


def records_from_upload(uploaded_file) -> list[dict[str, object]]:
    frame = pd.read_csv(uploaded_file)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"CSV 缺少字段：{', '.join(sorted(missing))}")
    return frame.fillna("").to_dict(orient="records")


def build_trend(records: list[dict[str, object]], filters: dict[str, object]) -> pd.DataFrame:
    filtered = filter_records(records, **filters)
    frame = pd.DataFrame(filtered)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["timestamp"].astype(str).str[:10], errors="coerce")
    frame["is_defect"] = frame["result"].astype(str).str.upper().isin(["NG", "FAIL", "DEFECT", "NOK"])
    trend = frame.groupby("date", as_index=False).agg(total=("result", "size"), defects=("is_defect", "sum"))
    trend["defect_rate"] = trend["defects"] / trend["total"] * 100
    return trend


with st.sidebar:
    st.markdown("### :material/fact_check: 质量分析请求")
    st.caption("按步骤设置后点击运行")

    st.markdown("**① 数据源**")
    uploaded = st.file_uploader(
        "生产记录 CSV",
        type=["csv"],
        help="不选择时使用内置演示数据（2400 条）。",
    )
    question = st.text_area(
        "质量问题",
        value=st.session_state.get("quality_question", DEFAULT_QUESTION),
        height=116,
        placeholder="请分析 2026-01-01 到 2026-01-31 A产线的不良率异常",
    )
    st.markdown("**② 解析后端**")
    provider = st.selectbox(
        "LLM 解析后端",
        options=list(LLM_PROVIDERS),
        format_func=lambda key: LLM_PROVIDERS[key],
        index=0,
        help="问题解析的后端：模拟器无需配置；Ollama 需本地安装；GLM 需设置 GLM_API_KEY。",
    )
    st.markdown("**③ 运行分析**")
    run_analysis = st.button(
        "运行分析",
        type="primary",
        icon=":material/play_arrow:",
        disabled=not question.strip(),
        help="填写问题后点击运行",
    )
    st.caption(":material/lock: 本地只读分析，数据不出本机")

try:
    records = records_from_upload(uploaded) if uploaded else get_demo_records()
except Exception as error:
    st.error(f"无法读取数据：{error}")
    st.stop()

with st.sidebar:
    if uploaded:
        st.caption(f":material/check_circle: 已加载自定义数据 · {uploaded.name}")
    else:
        st.caption(f":material/database: 演示数据 · {len(records):,} 条")

if run_analysis or "quality_report" not in st.session_state or provider != st.session_state.get(
    "quality_provider", "mock"
):
    st.session_state.quality_question = question
    st.session_state.quality_provider = provider
    try:
        st.session_state.quality_report = QualityAgent(records, llm_provider=provider).answer(question)
    except ValueError as error:
        st.error(f"分析参数无效：{error}")
        st.stop()

report = st.session_state.quality_report
st.session_state.quality_filters = format_filters(report["filters"])
st.session_state.quality_run_at = datetime.now().strftime("%H:%M:%S")

with st.sidebar:
    st.divider()
    st.markdown("**最近结果**")
    if report["status"] == "success":
        st.caption(f":material/check_circle: 分析完成 · {st.session_state.quality_run_at}")
    elif report["status"] == "no_data":
        st.caption(f":material/warning: 无匹配数据 · {st.session_state.quality_run_at}")
    else:
        st.caption(f":material/error: 分析失败 · {st.session_state.quality_run_at}")
    st.markdown("**查询条件**")
    st.text(st.session_state.quality_filters)

st.title("制造质量分析台")
st.caption("Manufacturing Quality Root Cause Agent · 可追溯的质量异常分析")

if report["status"] != "success":
    st.warning(report["summary"])
    st.stop()

baseline = report["baseline"]
top_factors = report["top_factors"]
top_factor = top_factors[0] if top_factors else None

metric_columns = st.columns(4)
metric_columns[0].metric("分析记录", f"{baseline['total_count']:,}")
metric_columns[1].metric("缺陷数量", f"{baseline['defect_count']:,}")
metric_columns[2].metric("总体不良率", f"{float(baseline['defect_rate_percent']):.2f}%")
metric_columns[3].metric(
    f"最高风险 · {DIMENSION_LABELS.get(top_factor['dimension'], top_factor['dimension'])}" if top_factor else "最高风险",
    str(top_factor["value"]) if top_factor else "无",
)

st.markdown(f'<div class="analysis-summary">{report["summary"]}</div>', unsafe_allow_html=True)

st.caption(f":material/tune: 查询条件：{format_filters(report['filters'])}")

with st.container(border=True):
    st.markdown("**执行过程**")
    for step in report.get("trace", []):
        icon = TRACE_ICONS.get(step["tool"], "arrow_forward")
        st.markdown(f":material/{icon}: `{step['tool']}` — {step['detail']}")

trend_frame = build_trend(records, report["filters"])
left, right = st.columns([1.45, 1], gap="large")

with left:
    st.subheader("不良率趋势")
    if trend_frame.empty:
        st.info("当前筛选条件下没有趋势数据。")
    else:
        figure, axis = plt.subplots(figsize=(8.2, 3.45), dpi=120)
        axis.plot(
            trend_frame["date"],
            trend_frame["defect_rate"],
            color="#176b52",
            marker="o",
            markersize=4.5,
            linewidth=2.2,
        )
        axis.fill_between(trend_frame["date"], trend_frame["defect_rate"], color="#dcebe4", alpha=0.55)
        axis.set_ylabel("不良率 (%)")
        axis.set_xlabel("日期")
        axis.set_ylim(bottom=0)
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=8))
        axis.grid(axis="y", color="#d8ded9", linewidth=0.7)
        axis.spines[["top", "right"]].set_visible(False)
        axis.spines[["left", "bottom"]].set_color("#aeb8b1")
        figure.tight_layout()
        st.pyplot(figure, width="stretch")
        plt.close(figure)

with right:
    st.subheader("候选因素不良率")
    if not top_factors:
        st.info("没有满足最小样本量的候选因素。")
    else:
        factor_frame = pd.DataFrame(top_factors)
        factor_frame["label"] = factor_frame.apply(
            lambda row: f"{DIMENSION_LABELS.get(row['dimension'], row['dimension'])} · {row['value']}", axis=1
        )
        factor_frame = factor_frame.sort_values("defect_rate_percent", ascending=False)
        figure, axis = plt.subplots(figsize=(6.1, 3.45), dpi=120)
        bars = axis.barh(factor_frame["label"], factor_frame["defect_rate_percent"], color="#b63b35", height=0.58)
        axis.invert_yaxis()
        axis.set_xlabel("不良率 (%)")
        axis.grid(axis="x", color="#d8ded9", linewidth=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.spines["bottom"].set_color("#aeb8b1")
        axis.tick_params(axis="y", length=0)
        axis.bar_label(bars, fmt="%.2f%%", padding=4, color="#17201c", fontsize=9)
        figure.tight_layout()
        st.pyplot(figure, width="stretch")
        plt.close(figure)

st.subheader("证据与排查建议")
if top_factors:
    evidence_rows = [
        {
            "优先级": index,
            "维度": DIMENSION_LABELS.get(item["dimension"], item["dimension"]),
            "取值": item["value"],
            "不良率": f"{float(item['defect_rate_percent']):.2f}%",
            "样本量": item["sample_count"],
            "相对总体": f"{float(item['rate_difference']) * 100:+.2f} 个百分点",
            "排查建议": item["recommendation"],
        }
        for index, item in enumerate(top_factors, start=1)
    ]
    st.dataframe(pd.DataFrame(evidence_rows), hide_index=True, width="stretch")

st.subheader("知识库引用")
if report.get("knowledge_refs"):
    for reference in report["knowledge_refs"]:
        with st.container(border=True):
            st.markdown(f":material/menu_book: **{reference['doc']}** · **{reference['section']}**")
            st.markdown(reference["snippet"])
else:
    st.caption(f":material/menu_book: {report.get('knowledge_summary', '未检索到相关文档。')}")

with st.expander("数据证据与原始记录"):
    for item in top_factors:
        st.markdown(f"**{DIMENSION_LABELS.get(item['dimension'], item['dimension'])} · {item['value']}**")
        st.text(item["evidence"])
    st.dataframe(pd.DataFrame(filter_records(records, **report["filters"])).head(100), hide_index=True)

for limitation in report.get("limitations", []):
    st.markdown(f'<div class="data-note">{limitation}</div>', unsafe_allow_html=True)
