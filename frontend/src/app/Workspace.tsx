import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Activity, BarChart3, Brain, Check, ChevronDown, CircleHelp, Database, Download, FileSpreadsheet, FileText, GitCompareArrows,
  LoaderCircle, Menu, MessageSquarePlus, Mic, MicOff, Pencil, Search, Send, Settings2, Trash2, Paperclip,
  Square, X,
} from "lucide-react";
import { api } from "./api";
import { AssistantTurn } from "./AssistantTurn";
import { DataManager } from "../features/data/DataManager";
import { ComparisonResult } from "../features/comparison/ComparisonResult";
import { MemoryManager } from "../features/memory/MemoryManager";
import type { ComparisonDTO, MessageDTO, QualityReport, RunDTO, RunEvent, SessionDTO, SourceDTO } from "./types";
import { qualityDimensionLabel, qualityValueLabel } from "./qualityLabels";

const EXAMPLE_QUESTIONS = [
  "最近不良率有什么变化，哪些工位风险最高？",
  "分析夜班和白班的不良率差异，并说明证据。",
  "检查 A 产线最近的过程能力，缺少参数时告诉我需要什么。",
];

const ResultChart = lazy(() => import("./ResultChart").then((module) => ({ default: module.ResultChart })));
const TrendChart = lazy(() => import("./ResultChart").then((module) => ({ default: module.TrendChart })));
const ParetoChart = lazy(() => import("./ResultChart").then((module) => ({ default: module.ParetoChart })));

const SIDEBAR_MIN_WIDTH = 240;
const SIDEBAR_MAX_WIDTH = 460;

function clampSidebarWidth(width: number) {
  const maxWidth = typeof window === "undefined"
    ? SIDEBAR_MAX_WIDTH
    : Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, window.innerWidth - 64));
  return Math.round(Math.max(SIDEBAR_MIN_WIDTH, Math.min(maxWidth, width)));
}

function shortQuestion(question: string, length = 42) {
  const compact = question.replace(/\s+/g, " ").trim();
  return compact.length > length ? `${compact.slice(0, length)}…` : compact;
}

function isDataIndependentQuestion(question: string) {
  const lower = question.toLowerCase();
  const dataTerms = /质量|不良|缺陷|产线|生产线|工位|批次|班次|车型|供应商|工艺|数据|记录|筛选|结果|扭矩|压力|温度|csv|pareto|cpk|spc|趋势/;
  const directTerms = /模型|显存|ollama|qwen|agent|智能体|程序|软件|页面|界面|功能|按钮|会话|图表|布局|上下文|记忆|思考强度|测试|速度|什么是|是什么意思|有什么区别|怎么使用|如何使用|你是谁|你好|为什么/;
  return directTerms.test(lower) && !dataTerms.test(lower);
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(date);
}

function reportValue(report: QualityReport | null | undefined, key: string) {
  const value = report?.baseline?.[key];
  if (typeof value === "number") return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function downloadFile(name: string, contents: string, mime: string) {
  const url = URL.createObjectURL(new Blob([contents], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function csvCell(value: unknown) {
  const text = typeof value === "string" ? value : value == null ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}

function ResultPanel({ report: initialReport, selectedMessage, dataVersion, onClose }: { report?: QualityReport | null; selectedMessage?: MessageDTO; dataVersion?: string; onClose: () => void }) {
  const [restoredReport, setRestoredReport] = useState<QualityReport | null>(null);
  const [restoringCharts, setRestoringCharts] = useState(false);
  const [chartsUnavailable, setChartsUnavailable] = useState(false);

  useEffect(() => {
    let current = true;
    setRestoredReport(null);
    setChartsUnavailable(false);
    if (
      initialReport?.task !== "quality_analysis"
      || initialReport.status !== "success"
      || initialReport.charts
    ) {
      setRestoringCharts(false);
      return () => { current = false; };
    }
    const runId = selectedMessage?.run_id ?? initialReport.run_id;
    if (typeof runId !== "string" || !runId) {
      setRestoringCharts(false);
      setChartsUnavailable(true);
      return () => { current = false; };
    }
    setRestoringCharts(true);
    void api.run(runId).then((run) => {
      if (!current) return;
      if (run.report?.charts) setRestoredReport(run.report);
      else setChartsUnavailable(true);
    }).catch(() => {
      if (current) setChartsUnavailable(true);
    }).finally(() => {
      if (current) setRestoringCharts(false);
    });
    return () => { current = false; };
  }, [initialReport, selectedMessage?.run_id]);

  const report = restoredReport ?? initialReport;
  const factors = Array.isArray(report?.top_factors) ? report.top_factors : [];
  const total = reportValue(report, "total_count");
  const defects = reportValue(report, "defect_count");
  const defectRate = reportValue(report, "defect_rate_percent") ?? ((total && defects != null) ? defects / total * 100 : null);
  const trend = report?.charts?.defect_trend;
  const trendPoints = trend?.points ?? [];
  const pareto = report?.charts?.defect_pareto;
  const paretoItems = pareto?.items ?? [];

  const panel = (
    <aside
      className="results-panel results-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="result-dialog-title"
    >
      <header className="results-header">
        <div><div className="results-eyebrow"><BarChart3 size={15} />结果工作区</div><h2 id="result-dialog-title">本轮分析结果</h2></div>
        <button type="button" className="icon-button" aria-label="关闭本轮结果" onClick={onClose} autoFocus><X size={18} /></button>
      </header>
      <div className="results-scroll">
        {selectedMessage?.content && <div className="result-question"><span>问题</span><p>{selectedMessage.content}</p></div>}
        {report ? (
          <>
            <div className="result-export">
              <button type="button" onClick={() => {
                const baseline = report.baseline ?? {};
                const factorsMarkdown = factors.length ? `\n| 因素 | 值 | 样本数 | 缺陷数 | 不良率 | 证据 |\n|---|---|---:|---:|---:|---|\n${factors.map((factor) => `| ${factor.dimension ?? ""} | ${factor.value ?? ""} | ${factor.sample_count ?? ""} | ${factor.defect_count ?? ""} | ${formatPercent(factor.defect_rate_percent ?? factor.defect_rate)} | ${String(factor.evidence ?? "").replaceAll("|", "\\|")} |`).join("\n")}` : "";
                const body = `# 制造质量分析\n\n**问题：** ${selectedMessage?.content ?? report.question ?? ""}\n\n**状态：** ${report.status ?? "unknown"}\n\n**数据版本：** ${dataVersion ?? "未知"}\n\n## 结论\n\n${report.explanation ?? report.summary ?? "暂无文字说明"}\n\n## 统计范围\n\n\`\`\`json\n${JSON.stringify(report.filters ?? {}, null, 2)}\n\`\`\`\n\n## 统计结果\n\n- 分析记录：${String(baseline.total_count ?? "—")}\n- 缺陷数量：${String(baseline.defect_count ?? "—")}\n- 总体不良率：${String(baseline.defect_rate_percent ?? "—")}%\n${factorsMarkdown}\n\n---\n导出时间：${new Date().toLocaleString("zh-CN")}\n`;
                downloadFile("制造质量分析.md", body, "text/markdown;charset=utf-8");
              }}><FileText size={14} />导出 Markdown</button>
              <button type="button" disabled={!factors.length} onClick={() => {
                if (!factors.length) return;
                const columns = [...new Set(factors.flatMap((factor) => Object.keys(factor)))];
                const csv = [columns.map(csvCell).join(","), ...factors.map((factor) => columns.map((column) => csvCell(factor[column])).join(","))].join("\r\n");
                downloadFile("质量分析因素.csv", `\ufeff${csv}`, "text/csv;charset=utf-8");
              }}><FileSpreadsheet size={14} />导出因素 CSV</button>
              <span><Download size={12} />版本 {dataVersion?.slice(0, 10) ?? "—"}</span>
            </div>
            <div className="result-metrics">
              <Metric label="分析记录" value={total == null ? "—" : total.toLocaleString()} />
              <Metric label="缺陷数量" value={defects == null ? "—" : defects.toLocaleString()} />
              <Metric label="总体不良率" value={defectRate == null ? "—" : `${defectRate.toFixed(2)}%`} />
            </div>
            {trend && (
              <section className="result-section">
                <div className="section-heading"><h3>不良率趋势（Trend）</h3><span>{trend.period_unit === "month" ? "按月汇总" : "按日汇总"}</span></div>
                {trendPoints.length > 0 ? (
                  <Suspense fallback={<div className="quality-chart-placeholder">正在载入趋势图…</div>}><TrendChart points={trendPoints} /></Suspense>
                ) : <div className="quality-chart-empty">当前筛选条件下没有可绘制的趋势数据。</div>}
              </section>
            )}
            {pareto && (
              <section className="result-section">
                <div className="section-heading"><h3>缺陷 Pareto 分析（Pareto Analysis）</h3><span>{(pareto.total_defects ?? 0).toLocaleString()} 条缺陷</span></div>
                {paretoItems.length > 0 ? (
                  <Suspense fallback={<div className="quality-chart-placeholder">正在载入 Pareto 图…</div>}><ParetoChart items={paretoItems} /></Suspense>
                ) : <div className="quality-chart-empty">当前筛选条件下没有缺陷记录，暂不生成 Pareto 图。</div>}
              </section>
            )}
            {report.task === "quality_analysis" && report.status === "success" && !report.charts && (
              <div className="quality-chart-legacy-note">
                {restoringCharts
                  ? "正在按原数据版本补算趋势图和 Pareto 图…"
                  : chartsUnavailable
                    ? "原数据版本已不可用，无法安全补算趋势图和 Pareto 图。恢复对应版本数据后即可查看。"
                    : "正在准备历史图表…"}
              </div>
            )}
            {factors.length > 0 && (
              <section className="result-section">
                <div className="section-heading"><h3>候选风险因素</h3><span>按优先级排列</span></div>
                <Suspense fallback={<div className="factor-chart chart-loading">正在载入图表…</div>}><ResultChart factors={factors} /></Suspense>
                <div className="factor-list">
                  {factors.slice(0, 8).map((factor, index) => (
                    <div className="factor-row" key={`${factor.dimension}-${factor.value}-${index}`}>
                      <span className="factor-rank">{String(index + 1).padStart(2, "0")}</span>
                      <span className="factor-name"><strong>{qualityDimensionLabel(factor.dimension)}</strong><small className={factor.dimension === "batch_id" ? "factor-value-batch" : undefined} title={String(factor.value ?? "")}>{qualityValueLabel(factor.dimension, factor.value)}</small></span>
                      <span className="factor-rate">{formatPercent(factor.defect_rate_percent ?? factor.defect_rate)}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
            {report.tool_result && Object.keys(report.tool_result).length > 0 && (
              <details className="result-details"><summary>工具结果</summary><pre>{JSON.stringify(report.tool_result, null, 2)}</pre></details>
            )}
            {Array.isArray(report.evidence_refs) && report.evidence_refs.length > 0 && (
              <section className="result-section evidence-section">
                <div className="section-heading"><h3>证据来源</h3><span>{report.evidence_refs.length} 项</span></div>
                {report.evidence_refs.slice(0, 8).map((evidence, index) => <div className="evidence-card" key={String(evidence.evidence_id ?? index)}><strong>{String(evidence.title ?? evidence.kind ?? `证据 ${index + 1}`)}</strong><p>{String(evidence.summary ?? evidence.description ?? evidence.text ?? "本轮分析引用的结构化数据证据")}</p></div>)}
              </section>
            )}
            <p className="result-source-note">{report.explanation_source === "model" ? "文字解释由模型生成，并根据本轮统计证据校验。" : report.explanation_source === "fallback" ? "模型解释不可用，当前展示证据支持的规则说明。" : "结果来自本轮结构化统计。"}</p>
          </>
        ) : <div className="result-placeholder"><Activity size={20} /><strong>等待本轮统计</strong><p>分析过程中，统计结果会先出现在这里。</p></div>}
      </div>
    </aside>
  );

  return (
    <div className="modal-backdrop result-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      {panel}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function formatPercent(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  return `${(numeric <= 1 ? numeric * 100 : numeric).toFixed(2)}%`;
}

export function Workspace() {
  const [sources, setSources] = useState<SourceDTO[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState("demo");
  const [conversationSourceIds, setConversationSourceIds] = useState<string[]>([]);
  const [turnSourceIds, setTurnSourceIds] = useState<string[]>([]);
  const [analysisMode, setAnalysisMode] = useState<"merge" | "compare">("merge");
  const [sessions, setSessions] = useState<SessionDTO[]>([]);
  const [comparisonHistory, setComparisonHistory] = useState<ComparisonDTO[]>([]);
  const [currentComparison, setCurrentComparison] = useState<ComparisonDTO | null>(null);
  const [comparisonParentSessionId, setComparisonParentSessionId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [messages, setMessages] = useState<MessageDTO[]>([]);
  const [health, setHealth] = useState<{ model_name: string } | null>(null);
  const [modelHealth, setModelHealth] = useState<{ status: string; model_name: string; message: string } | null>(null);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [input, setInput] = useState("");
  const [activeRun, setActiveRun] = useState<RunDTO | null>(null);
  const [runEvents, setRunEvents] = useState<Record<string, RunEvent[]>>({});
  const [previewReport, setPreviewReport] = useState<QualityReport | null>(null);
  const [resultMessage, setResultMessage] = useState<MessageDTO | undefined>();
  const [resultDialogMessage, setResultDialogMessage] = useState<MessageDTO | undefined>();
  const [dataOpen, setDataOpen] = useState(false);
  const [dataPreviewId, setDataPreviewId] = useState<string>();
  const openDataManager = (sourceId?: string) => {
    setDataPreviewId(sourceId);
    setDataOpen(true);
  };
  const closeDataManager = () => {
    setDataOpen(false);
    setDataPreviewId(undefined);
  };
  const [attachmentsOpen, setAttachmentsOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 980);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    if (typeof window === "undefined") return 272;
    try {
      const savedWidth = Number(window.localStorage.getItem("quality-workbench:sidebar-width"));
      return Number.isFinite(savedWidth) && savedWidth > 0 ? clampSidebarWidth(savedWidth) : 272;
    } catch {
      return 272;
    }
  });
  const [sidebarResizing, setSidebarResizing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [apiReady, setApiReady] = useState<boolean | null>(null);
  const [speechStatus, setSpeechStatus] = useState<{ status: string; message: string } | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const recordingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recordingStartedAtRef = useRef(0);
  const discardRecordingRef = useRef(false);
  const speechAbortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachmentPopoverRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<EventSource | null>(null);
  const comparisonStreamsRef = useRef<EventSource[]>([]);
  const seenEventIdsRef = useRef<Record<string, Set<string>>>({});
  const sessionRef = useRef<string | null>(null);
  const subscribeRunRef = useRef<(run: RunDTO) => void>(() => undefined);
  const watchComparisonRef = useRef<(comparison: ComparisonDTO) => void>(() => undefined);
  const comparisonRef = useRef<ComparisonDTO | null>(null);
  const sidebarWidthRef = useRef(sidebarWidth);
  const pendingSubmissionRef = useRef<{ question: string; submissionId: string } | null>(null);
  const pendingComparisonRef = useRef<{ question: string; sourceIds: string[]; parentSessionId: string; comparisonId: string } | null>(null);
  const maxSidebarWidth = typeof window === "undefined"
    ? SIDEBAR_MAX_WIDTH
    : Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, window.innerWidth - 64));
  const resizeSidebar = (nextWidth: number) => {
    const width = clampSidebarWidth(nextWidth);
    sidebarWidthRef.current = width;
    setSidebarWidth(width);
  };
  const saveSidebarWidth = () => {
    try {
      window.localStorage.setItem("quality-workbench:sidebar-width", String(sidebarWidthRef.current));
    } catch {
      // Keep resizing available when browser storage is disabled.
    }
  };
  const closeSidebarOnCompactViewport = () => {
    if (window.innerWidth <= 980) setSidebarOpen(false);
  };
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);

  const loadSources = useCallback(async () => {
    const rows = await api.listSources();
    setSources(rows);
    return rows;
  }, []);

  const loadSessions = useCallback(async () => {
    const rows = await api.listSessions();
    setSessions(rows);
    return rows;
  }, []);

  const loadComparisons = useCallback(async () => {
    const rows = await api.listComparisons();
    setComparisonHistory(rows);
    return rows;
  }, []);

  const loadMessages = useCallback(async (id: string) => {
    const page = await api.messages(id);
    setMessages(page.messages);
    return page.messages;
  }, []);

  useEffect(() => {
    let mounted = true;
    void api.speechStatus().then((status) => { if (mounted) setSpeechStatus(status); }).catch(() => { if (mounted) setSpeechStatus(null); });
    void Promise.all([api.health(), loadSources(), api.listComparisons()]).then(async ([status, sourceRows, compareRows]) => {
      if (!mounted) return;
      setHealth(status);
      setApiReady(true);
      setComparisonHistory(compareRows);
      void api.modelHealth().then(setModelHealth).catch(() => setModelHealth(null));
      const savedComparisonId = window.localStorage.getItem("quality-workbench:comparison");
      const restoredComparison = compareRows.find((item) => item.comparison_id === savedComparisonId);
      if (restoredComparison) {
        setCurrentComparison(restoredComparison.status === "running" || !restoredComparison.parent_session_id ? restoredComparison : null);
        comparisonRef.current = restoredComparison;
        if (restoredComparison.parent_session_id) {
          setComparisonParentSessionId(restoredComparison.parent_session_id);
          setSessionId(restoredComparison.parent_session_id);
        }
        if (restoredComparison.status === "running") watchComparisonRef.current(restoredComparison);
      }
      const defaultSource = restoredComparison
        ? sourceRows.find((item) => item.source_id === restoredComparison.source_ids[0])
        : sourceRows.find((item) => item.source_id === "demo") ?? sourceRows[0];
      if (!defaultSource) return;
      setSelectedSourceId(defaultSource.source_id);
      const rows = await loadSessions();
      const currentVersionSession = rows.find((session) => session.source_id === defaultSource.source_id && session.data_version === defaultSource.data_version);
      if (mounted && restoredComparison?.parent_session_id) {
        const parent = rows.find((session) => session.session_id === restoredComparison.parent_session_id);
        const ids = parent?.data_sources.map((item) => item.source_id) ?? [];
        if (parent) setSelectedSourceId(parent.source_id);
        setConversationSourceIds(ids);
        setTurnSourceIds(restoredComparison.source_ids.filter((id) => ids.includes(id)));
      }
      if (mounted && !restoredComparison) {
        setSessionId(currentVersionSession?.session_id ?? null);
        const ids = currentVersionSession?.data_sources.map((item) => item.source_id) ?? [defaultSource.source_id];
        setConversationSourceIds(ids);
        setTurnSourceIds(ids);
        if (!currentVersionSession && rows.length > 0) {
          setNotice("最近会话仍保留在左侧；新建分析可直接使用当前数据文件。");
        }
      }
    }).catch((reason: Error) => {
      if (mounted) { setApiReady(false); setError(reason.message); }
    });
    return () => { mounted = false; };
  }, [loadSources, loadSessions]);

  useEffect(() => { sessionRef.current = sessionId; }, [sessionId]);

  useEffect(() => {
    if (!isRecording) return;
    const timer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - recordingStartedAtRef.current) / 1000);
      setRecordingSeconds(Math.min(60, elapsed));
    }, 250);
    return () => window.clearInterval(timer);
  }, [isRecording]);

  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setActiveRun(null);
      setPreviewReport(null);
      return;
    }
    let mounted = true;
    setMessages([]);
    const selected = sessions.find((item) => item.session_id === sessionId);
    const sessionIds = selected?.data_sources.map((item) => item.source_id) ?? [];
    setConversationSourceIds(sessionIds);
    setTurnSourceIds(sessionIds);
    void Promise.all([loadMessages(sessionId), api.sessionRuns(sessionId)]).then(([loadedMessages, recentRuns]) => {
      if (!mounted) return;
      const lastDataTurn = [...loadedMessages].reverse().find((message) => message.role === "assistant" && message.report?.task !== "direct_answer" && (message.data_sources?.length ?? message.report?.data_sources?.length ?? 0) > 0);
      const lastSourceIds = lastDataTurn?.data_sources?.map((item) => item.source_id)
        ?? lastDataTurn?.report?.data_sources?.map((item) => item.source_id)
        ?? sessionIds;
      setTurnSourceIds(lastSourceIds.filter((id) => sessionIds.includes(id)));
      const running = recentRuns.find((run) => ["queued", "running", "cancelling"].includes(run.status));
      if (running) subscribeRunRef.current(running);
      else {
        const interrupted = recentRuns.find((run) => run.status === "interrupted");
        if (interrupted) setNotice("服务上次重启时这轮分析尚未完成；可重新发送问题继续分析。");
      }
    }).catch((reason: Error) => { if (mounted) setError(reason.message); });
    return () => { mounted = false; };
  }, [sessionId, loadMessages]);

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus();
  }, [searchOpen]);

  useEffect(() => {
    if (!attachmentsOpen) return;
    const closeWhenOutside = (event: PointerEvent) => {
      if (!attachmentPopoverRef.current?.contains(event.target as Node)) setAttachmentsOpen(false);
    };
    document.addEventListener("pointerdown", closeWhenOutside);
    return () => document.removeEventListener("pointerdown", closeWhenOutside);
  }, [attachmentsOpen]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "n") {
        event.preventDefault();
        startNewSession();
      }
      if (event.key === "Escape") {
        setSearchOpen(false);
        setAttachmentsOpen(false);
        setDataOpen(false);
        setDataPreviewId(undefined);
        setMemoryOpen(false);
        setSidebarOpen(false);
        setResultDialogMessage(undefined);
        setResultMessage(undefined);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => () => {
    streamRef.current?.close();
    comparisonStreamsRef.current.forEach((stream) => stream.close());
    if (recordingTimeoutRef.current) clearTimeout(recordingTimeoutRef.current);
    speechAbortRef.current?.abort();
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = null;
      try { recorder.stop(); } catch { /* Recorder may already have stopped. */ }
    }
    recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  useEffect(() => {
    const container = chatScrollRef.current;
    if (!container || !shouldAutoScrollRef.current) return;
    requestAnimationFrame(() => container.scrollTo({ top: container.scrollHeight, behavior: "smooth" }));
  }, [messages, activeRun, runEvents]);

  const startNewSession = () => {
    streamRef.current?.close();
    comparisonStreamsRef.current.forEach((stream) => stream.close());
    comparisonStreamsRef.current = [];
    comparisonRef.current = null;
    pendingComparisonRef.current = null;
    setComparisonParentSessionId(null);
    window.localStorage.removeItem("quality-workbench:comparison");
    setCurrentComparison(null);
    setAttachmentsOpen(false);
    pendingSubmissionRef.current = null;
    shouldAutoScrollRef.current = true;
    setSessionId(null);
    const fallbackIds = sources.some((source) => source.source_id === selectedSourceId) ? [selectedSourceId] : [];
    setConversationSourceIds(fallbackIds);
    setTurnSourceIds(fallbackIds);
    setAnalysisMode("merge");
    setMessages([]);
    setActiveRun(null);
    setRunEvents({});
    setResultMessage(undefined);
    setPreviewReport(null);
    setError("");
    setNotice("");
    closeSidebarOnCompactViewport();
    textareaRef.current?.focus();
  };

  const subscribeToRun = useCallback((run: RunDTO) => {
    streamRef.current?.close();
    setActiveRun(run);
    setPreviewReport(null);
    const seen = seenEventIdsRef.current[run.run_id] ?? new Set<string>();
    seenEventIdsRef.current[run.run_id] = seen;
    const stream = api.subscribe(run.run_id, (event, eventId) => {
      if (eventId && seen.has(eventId)) return;
      if (eventId) seen.add(eventId);
      if (event.report && (event.type === "statistics.ready" || event.type === "message.completed" || event.type.startsWith("run."))) {
        setPreviewReport(event.report);
      }
      setRunEvents((current) => ({ ...current, [run.run_id]: [...(current[run.run_id] ?? []), event].slice(-160) }));
      if (["run.completed", "run.failed", "run.cancelled", "run.interrupted"].includes(event.type)) {
        stream.close();
        streamRef.current = null;
        setActiveRun(null);
        if (event.report) setPreviewReport(event.report);
        if (sessionRef.current === run.session_id) {
          void loadMessages(run.session_id);
          void loadSessions();
        }
        if (event.type === "run.failed") setError(String(event.report?.summary ?? "本轮分析未完成，请重试。"));
        if (event.type === "run.cancelled") setNotice("本轮分析已停止。");
        if (event.type === "run.interrupted") setNotice("服务重启导致本轮分析中断，可重新提问继续分析。");
      }
    },
    () => setNotice("实时连接暂时中断，浏览器正在自动重连…"),
    () => setNotice((current) => current === "实时连接暂时中断，浏览器正在自动重连…" ? "" : current));
    streamRef.current = stream;
  }, [loadMessages, loadSessions]);
  subscribeRunRef.current = subscribeToRun;

  const watchComparison = useCallback((comparison: ComparisonDTO) => {
    comparisonStreamsRef.current.forEach((stream) => stream.close());
    comparisonStreamsRef.current = [];
    const activeChildren = comparison.children.filter((child) => ["queued", "running", "cancelling"].includes(child.status));
    for (const child of activeChildren) {
      const seen = seenEventIdsRef.current[child.run_id] ?? new Set<string>();
      seenEventIdsRef.current[child.run_id] = seen;
      const stream = api.subscribe(child.run_id, (event, eventId) => {
        if (eventId && seen.has(eventId)) return;
        if (eventId) seen.add(eventId);
        setRunEvents((current) => ({ ...current, [child.run_id]: [...(current[child.run_id] ?? []), event].slice(-160) }));
        if (event.type === "statistics.ready" && event.report) {
          setCurrentComparison((current) => current?.comparison_id === comparison.comparison_id ? {
            ...current,
            children: current.children.map((item) => item.run_id === child.run_id ? { ...item, report: event.report ?? item.report } : item),
          } : current);
        }
        if (["run.completed", "run.failed", "run.cancelled", "run.interrupted"].includes(event.type)) {
          void api.comparison(comparison.comparison_id).then((updated) => {
            if (comparisonRef.current?.comparison_id !== comparison.comparison_id) return;
            comparisonRef.current = updated;
            setCurrentComparison(updated);
            void loadComparisons();
            if (!updated.children.some((item) => ["queued", "running", "cancelling"].includes(item.status))) {
              comparisonStreamsRef.current.forEach((active) => active.close());
              comparisonStreamsRef.current = [];
              if (updated.parent_session_id && sessionRef.current === updated.parent_session_id) {
                void loadMessages(updated.parent_session_id).then(() => {
                  setCurrentComparison((current) => current?.comparison_id === updated.comparison_id ? null : current);
                  setComparisonParentSessionId((current) => current === updated.parent_session_id ? null : current);
                  window.localStorage.removeItem("quality-workbench:comparison");
                  void loadSessions();
                });
              } else if (!updated.parent_session_id) {
                window.localStorage.removeItem("quality-workbench:comparison");
              }
            }
          }).catch((reason: Error) => setError(reason.message));
        }
      },
      () => setNotice("比较任务的实时连接暂时中断，浏览器正在自动重连…"),
      () => setNotice((current) => current === "比较任务的实时连接暂时中断，浏览器正在自动重连…" ? "" : current));
      comparisonStreamsRef.current.push(stream);
    }
  }, [loadComparisons, loadMessages, loadSessions]);
  watchComparisonRef.current = watchComparison;

  const ensureSession = async (question: string) => {
    if (sessionId) return sessionId;
    const anchorId = conversationSourceIds[0] ?? turnSourceIds[0] ?? selectedSourceId;
    const anchor = sources.find((source) => source.source_id === anchorId) ?? sources[0];
    if (!anchor) throw new Error("请先添加一个数据文件，再开始新会话。");
    const created = await api.createSession(anchor.source_id, shortQuestion(question, 60));
    const updated = await api.setSessionSources(created.session_id, conversationSourceIds);
    setSelectedSourceId(anchor.source_id);
    setSessionId(created.session_id);
    setSessions((current) => [updated, ...current.filter((item) => item.session_id !== updated.session_id)]);
    return created.session_id;
  };

  const applyDataSelection = async (conversationIds: string[], activeIds: string[]) => {
    if (sessions.find((item) => item.session_id === sessionId)?.status === "waiting_input") {
      throw new Error("请先完成当前任务的参数补充，再修改会话文件。");
    }
    const nextConversationIds = [...new Set(conversationIds)].slice(0, 8);
    const nextTurnIds = [...new Set(activeIds)].filter((id) => nextConversationIds.includes(id));
    if (sessionId) {
      const updated = await api.setSessionSources(sessionId, nextConversationIds);
      setSessions((current) => current.map((item) => item.session_id === updated.session_id ? updated : item));
    }
    setConversationSourceIds(nextConversationIds);
    setTurnSourceIds(nextTurnIds);
    const primary = nextTurnIds[0] ?? nextConversationIds[0];
    if (primary) setSelectedSourceId(primary);
  };

  const uploadFiles = async (fileList?: FileList | File[]) => {
    const files = Array.from(fileList ?? []);
    if (!files.length || uploadingFiles) return;
    if (activeRun || currentComparison?.status === "running") {
      setError("当前分析完成后才能修改本轮文件。");
      return;
    }
    const invalidFile = files.find((file) => !file.name.toLowerCase().endsWith(".csv"));
    if (invalidFile) {
      setError(`${invalidFile.name} 不是 CSV 文件。`);
      return;
    }
    if (sessions.find((item) => item.session_id === sessionId)?.status === "waiting_input") {
      setError("请先完成当前任务的参数补充，再添加或移除会话文件。");
      return;
    }
    if (conversationSourceIds.length + files.length > 8) {
      setError("一个对话最多保留 8 个文件，请先移除不需要的文件。");
      return;
    }
    setUploadingFiles(true);
    setError("");
    setNotice("");
    const uploaded: SourceDTO[] = [];
    try {
      for (const file of files) {
        uploaded.push(await api.uploadSource(file));
      }
      await loadSources();
      const ids = [...new Set([...conversationSourceIds, ...uploaded.map((source) => source.source_id)])];
      const selected = [...new Set([...turnSourceIds, ...uploaded.map((source) => source.source_id)])];
      if (ids.length > 8) throw new Error("一个对话最多保留 8 个不同文件。");
      if (sessionId) {
        const updated = await api.setSessionSources(sessionId, ids);
        setSessions((current) => current.map((item) => item.session_id === updated.session_id ? updated : item));
      }
      setConversationSourceIds(ids);
      setTurnSourceIds(selected);
      if (uploaded[0]) setSelectedSourceId(uploaded[0].source_id);
      setNotice(`已添加 ${uploaded.length} 个文件，已选为本轮附件。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "上传文件失败");
    } finally {
      setUploadingFiles(false);
    }
  };

  const startComparison = async (question: string, sourceIds: string[], sessionIds: Record<string, string> = {}, requestedParentId: string | null = sessionId) => {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    streamRef.current?.close();
    comparisonStreamsRef.current.forEach((stream) => stream.close());
    comparisonStreamsRef.current = [];
    try {
      const parentSessionId = requestedParentId ?? await ensureSession(question);
      if (!pendingComparisonRef.current || pendingComparisonRef.current.question !== question || pendingComparisonRef.current.parentSessionId !== parentSessionId || JSON.stringify(pendingComparisonRef.current.sourceIds) !== JSON.stringify(sourceIds)) {
        pendingComparisonRef.current = { question, sourceIds: [...sourceIds], parentSessionId, comparisonId: crypto.randomUUID() };
      }
      const comparison = await api.startComparison({ comparisonId: pendingComparisonRef.current.comparisonId, question, sourceIds, parentSessionId, sessionIds });
      pendingComparisonRef.current = null;
      comparisonRef.current = comparison;
      setCurrentComparison(comparison.status === "running" ? comparison : null);
      setComparisonParentSessionId(parentSessionId);
      if (comparison.status === "running") window.localStorage.setItem("quality-workbench:comparison", comparison.comparison_id);
      else window.localStorage.removeItem("quality-workbench:comparison");
      setSessionId(parentSessionId);
      setResultMessage(undefined);
      setPreviewReport(null);
      setInput("");
      closeSidebarOnCompactViewport();
      await Promise.all([loadMessages(parentSessionId), loadSessions(), loadComparisons()]);
      if (comparison.status === "running") watchComparisonRef.current(comparison);
      else setComparisonParentSessionId(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建比较失败");
    } finally {
      setBusy(false);
    }
  };

  const releaseRecordingResources = () => {
    if (recordingTimeoutRef.current) clearTimeout(recordingTimeoutRef.current);
    recordingTimeoutRef.current = null;
    recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
    recordingStreamRef.current = null;
    recorderRef.current = null;
  };

  const stopVoiceRecording = (discard = false) => {
    discardRecordingRef.current = discard;
    if (recordingTimeoutRef.current) clearTimeout(recordingTimeoutRef.current);
    recordingTimeoutRef.current = null;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    else {
      releaseRecordingResources();
      setIsRecording(false);
    }
  };

  const insertTranscription = (text: string) => {
    const textarea = textareaRef.current;
    const current = textarea?.value ?? input;
    const start = textarea?.selectionStart ?? current.length;
    const end = textarea?.selectionEnd ?? start;
    const left = current.slice(0, start);
    const right = current.slice(end);
    const inserted = `${left && !/\s$/.test(left) ? " " : ""}${text}${right && !/^\s/.test(right) ? " " : ""}`;
    const next = `${left}${inserted}${right}`;
    const cursor = start + inserted.length;
    setInput(next);
    requestAnimationFrame(() => {
      const field = textareaRef.current;
      if (!field) return;
      field.focus();
      field.setSelectionRange(cursor, cursor);
      field.style.height = "auto";
      field.style.height = `${Math.min(field.scrollHeight, 160)}px`;
    });
  };

  const startVoiceRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("当前浏览器不支持录音，请使用桌面版 Edge 或 Chrome，并通过 localhost 打开工作台。");
      return;
    }
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      recordingStreamRef.current = stream;
      recordingChunksRef.current = [];
      discardRecordingRef.current = false;
      const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => { if (event.data.size > 0) recordingChunksRef.current.push(event.data); };
      recorder.onerror = () => {
        setError("录音设备出现问题，请检查麦克风后重试。");
        stopVoiceRecording(true);
      };
      recorder.onstop = async () => {
        if (recordingTimeoutRef.current) clearTimeout(recordingTimeoutRef.current);
        recordingTimeoutRef.current = null;
        recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
        recordingStreamRef.current = null;
        recorderRef.current = null;
        setIsRecording(false);
        if (discardRecordingRef.current) { discardRecordingRef.current = false; recordingChunksRef.current = []; return; }
        const recordingDurationMs = recordingStartedAtRef.current ? Date.now() - recordingStartedAtRef.current : 0;
        recordingStartedAtRef.current = 0;
        if (recordingDurationMs < 500) {
          recordingChunksRef.current = [];
          setNotice("录音时间太短，请至少说 1 秒后再结束。");
          return;
        }
        const audio = new Blob(recordingChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        recordingChunksRef.current = [];
        if (!audio.size) { setNotice("没有录到语音，请重试。"); return; }
        const controller = new AbortController();
        speechAbortRef.current = controller;
        setIsTranscribing(true);
        setNotice("正在本机识别语音，完成后会填入输入框供你核对…");
        try {
          const result = await api.transcribeSpeech(audio, controller.signal);
          insertTranscription(result.text);
          setNotice(`语音已转为草稿（${result.duration_seconds.toFixed(1)} 秒），请核对内容后再发送。`);
        } catch (reason) {
          if (controller.signal.aborted) setNotice("语音识别已取消。");
          else setError(reason instanceof Error ? reason.message : "语音识别失败，请重试。");
        } finally {
          if (speechAbortRef.current === controller) speechAbortRef.current = null;
          setIsTranscribing(false);
        }
      };
      // Emit one finalized container on stop. Timesliced WebM fragments can be
      // malformed when concatenated by some browser/audio-device combinations.
      recorder.start();
      recordingStartedAtRef.current = Date.now();
      setRecordingSeconds(0);
      setIsRecording(true);
      setNotice("正在录音；结束后会转写到输入框，不会自动发送。");
      recordingTimeoutRef.current = setTimeout(() => {
        if (recorder.state !== "inactive") {
          setNotice("已达到 60 秒上限，正在识别语音…");
          recorder.stop();
        }
      }, 60_000);
    } catch (reason) {
      releaseRecordingResources();
      const name = reason instanceof Error ? reason.name : "";
      setError(name === "NotAllowedError" || name === "PermissionDeniedError"
        ? "麦克风权限未开启。请在浏览器地址栏的站点设置中允许使用麦克风。"
        : name === "NotFoundError"
          ? "没有找到可用麦克风，请连接或启用麦克风后重试。"
          : reason instanceof Error ? reason.message : "无法启动录音，请重试。");
    }
  };

  const submitQuestion = async (rawQuestion = input) => {
    const question = rawQuestion.trim();
    if (!question || busy || activeRun || currentComparison?.status === "running") return;
    if (question === "/new") { startNewSession(); return; }
    if (question === "/data") { openDataManager(); setInput(""); return; }
    const activeSession = sessions.find((session) => session.session_id === sessionId);
    const dataIndependent = isDataIndependentQuestion(question);
    const staleRefs = (activeSession?.data_sources ?? []).filter((ref) => !dataIndependent && turnSourceIds.includes(ref.source_id)).filter((ref) => {
      const source = sources.find((item) => item.source_id === ref.source_id);
      return !source || source.data_version !== ref.data_version;
    });
    if (staleRefs.length) {
      setError("本轮选择的一个或多个文件版本已不可用。历史结果仍可查看；请从本轮移除失效文件或新建会话。");
      setInput(question);
      return;
    }
    const asksToCompare = /比较|对比|差异|相比|哪个.{0,6}(更高|更低|更好|更差)/.test(question);
    const useComparison = turnSourceIds.length >= 2 && !dataIndependent && (analysisMode === "compare" || asksToCompare);
    if (useComparison) {
      const sessionIds = currentComparison?.parent_session_id === sessionId
        ? Object.fromEntries(currentComparison.children.map((child) => [child.source_id, child.session_id]))
        : {};
      await startComparison(question, turnSourceIds, sessionIds, sessionId);
      return;
    }
    if (currentComparison) {
      setCurrentComparison(null);
      setComparisonParentSessionId(null);
      window.localStorage.removeItem("quality-workbench:comparison");
    }
    setInput("");
    setAttachmentsOpen(false);
    shouldAutoScrollRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      let activeSessionId = sessionId;
      if (!activeSessionId) {
        activeSessionId = await ensureSession(question);
      }
      if (!pendingSubmissionRef.current || pendingSubmissionRef.current.question !== question) {
        pendingSubmissionRef.current = { question, submissionId: crypto.randomUUID() };
      }
      const selectedSourceIds = dataIndependent ? [] : turnSourceIds;
      const run = await api.startRun(activeSessionId, question, pendingSubmissionRef.current.submissionId, selectedSourceIds);
      pendingSubmissionRef.current = null;
      setMessages((current) => [
        ...current,
        { message_id: `pending-user-${run.run_id}`, session_id: activeSessionId!, role: "user", content: question, created_at: new Date().toISOString(), run_id: run.run_id, report: null, data_sources: selectedSourceIds.map((id) => { const source = sources.find((item) => item.source_id === id); return source ? { source_id: source.source_id, name: source.name, data_version: source.data_version, record_count: source.record_count } : null; }).filter((item): item is NonNullable<typeof item> => item !== null) },
      ]);
      subscribeToRun(run);
      closeSidebarOnCompactViewport();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交失败");
      setInput(question);
    } finally {
      setBusy(false);
    }
  };

  const stopRun = async () => {
    if (!activeRun) return;
    try {
      await api.cancelRun(activeRun.run_id);
      setNotice("正在等待当前分析阶段安全结束…");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "停止请求失败");
    }
  };

  const selectSession = (id: string) => {
    streamRef.current?.close();
    comparisonStreamsRef.current.forEach((stream) => stream.close());
    comparisonStreamsRef.current = [];
    comparisonRef.current = null;
    pendingComparisonRef.current = null;
    window.localStorage.removeItem("quality-workbench:comparison");
    setCurrentComparison(null);
    setComparisonParentSessionId(null);
    pendingSubmissionRef.current = null;
    shouldAutoScrollRef.current = true;
    setActiveRun(null);
    setSessionId(id);
    const selected = sessions.find((item) => item.session_id === id);
    setSelectedSourceId(selected?.source_id ?? selectedSourceId);
    setConversationSourceIds(selected?.data_sources.map((item) => item.source_id) ?? []);
    setTurnSourceIds(selected?.data_sources.map((item) => item.source_id) ?? []);
    setAnalysisMode("merge");
    setPreviewReport(null);
    closeSidebarOnCompactViewport();
    setError("");
    setNotice("");
    const activeComparison = comparisonHistory.find((item) => item.parent_session_id === id && item.status === "running");
    if (activeComparison) {
      comparisonRef.current = activeComparison;
      setCurrentComparison(activeComparison);
      setComparisonParentSessionId(id);
      setTurnSourceIds(activeComparison.source_ids.filter((sourceId) => (selected?.data_sources ?? []).some((item) => item.source_id === sourceId)));
      window.localStorage.setItem("quality-workbench:comparison", activeComparison.comparison_id);
      watchComparisonRef.current(activeComparison);
    }
  };

  const saveSessionTitle = async () => {
    if (!editingSessionId) return;
    const title = editingSessionTitle.trim();
    if (!title) return;
    try {
      const updated = await api.renameSession(editingSessionId, title);
      setSessions((current) => current.map((session) => session.session_id === updated.session_id ? updated : session));
      setEditingSessionId(null);
      setEditingSessionTitle("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重命名会话失败");
    }
  };

  const deleteSession = async (session: SessionDTO) => {
    const title = session.title || "新会话";
    const confirmed = window.confirm(
      `确定删除“${title}”吗？会删除会话消息和普通分析记录。已完成的多文件比较结果会保留，但会解除与本会话的关联。此操作不可撤销。`,
    );
    if (!confirmed) return;

    const wasSelected = sessionId === session.session_id;
    const selectedComparisonId = currentComparison?.comparison_id;
    try {
      await api.deleteSession(session.session_id);
      const [remainingSessions] = await Promise.all([
        loadSessions(),
        loadComparisons(),
      ]);
      if (wasSelected) {
        streamRef.current?.close();
        comparisonStreamsRef.current.forEach((stream) => stream.close());
        comparisonStreamsRef.current = [];
        comparisonRef.current = null;
        window.localStorage.removeItem("quality-workbench:comparison");
        pendingSubmissionRef.current = null;
        pendingComparisonRef.current = null;
        setCurrentComparison(null);
        setComparisonParentSessionId(null);
        setSessionId(remainingSessions[0]?.session_id ?? null);
        const nextSession = remainingSessions[0];
        const nextSourceIds = nextSession?.data_sources.map((item) => item.source_id) ?? [];
        setConversationSourceIds(nextSourceIds);
        setTurnSourceIds(nextSourceIds);
        setMessages([]);
        setActiveRun(null);
        setRunEvents({});
        setResultMessage(undefined);
        setPreviewReport(null);
      }
      if (selectedComparisonId) {
        const comparison = await api.comparison(selectedComparisonId);
        comparisonRef.current = comparison;
        setCurrentComparison(comparison);
      }
      setError("");
      setNotice("会话已删除");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除会话失败");
    }
  };

  const selectComparison = async (comparisonId: string) => {
    streamRef.current?.close();
    comparisonStreamsRef.current.forEach((stream) => stream.close());
    comparisonStreamsRef.current = [];
    setMessages([]);
    setActiveRun(null);
    setResultMessage(undefined);
    setPreviewReport(null);
    closeSidebarOnCompactViewport();
    setError("");
    try {
      const comparison = await api.comparison(comparisonId);
      comparisonRef.current = comparison;
      const active = comparison.status === "running";
      setCurrentComparison(active || !comparison.parent_session_id ? comparison : null);
      setComparisonParentSessionId(comparison.parent_session_id ?? null);
      if (active) window.localStorage.setItem("quality-workbench:comparison", comparisonId);
      else window.localStorage.removeItem("quality-workbench:comparison");
      if (comparison.parent_session_id) setSessionId(comparison.parent_session_id);
      else setSessionId(null);
      if (comparison.source_ids[0]) {
        if (!comparison.parent_session_id) setSelectedSourceId(comparison.source_ids[0]);
        await loadSessions();
      }
      if (comparison.parent_session_id) {
        const parent = await api.getSession(comparison.parent_session_id);
        const ids = parent.data_sources.map((item) => item.source_id);
        setSelectedSourceId(parent.source_id);
        setConversationSourceIds(ids);
        setTurnSourceIds(comparison.source_ids.filter((id) => ids.includes(id)));
        await loadMessages(parent.session_id);
      } else {
        setConversationSourceIds(comparison.source_ids);
        setTurnSourceIds(comparison.source_ids);
      }
      if (active) watchComparisonRef.current(comparison);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取比较记录失败");
    }
  };

  const stopComparison = async () => {
    if (!currentComparison) return;
    try {
      const updated = await api.cancelComparison(currentComparison.comparison_id);
      comparisonRef.current = updated;
      setCurrentComparison(updated);
      setNotice("已向各数据源发送停止请求；正在运行的模型会在当前阶段结束后停止。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "停止比较失败");
    }
  };

  const displayedMessages = useMemo(() => messages, [messages]);
  const comparisonIsPendingInSession = Boolean(currentComparison && comparisonParentSessionId === sessionId);
  const questions: MessageDTO[] = currentComparison && !comparisonIsPendingInSession
    ? [{ message_id: `comparison-question-${currentComparison.comparison_id}`, session_id: "", role: "user", content: currentComparison.question, created_at: currentComparison.created_at, run_id: null, report: null }]
    : displayedMessages.filter((message) => message.role === "user");
  const currentSource = sources.find((source) => source.source_id === selectedSourceId);
  const selectedSession = sessions.find((session) => session.session_id === sessionId);
  const sourceSelectionLocked = Boolean(activeRun || currentComparison?.status === "running" || selectedSession?.status === "waiting_input");
  const selectedSessionIsStale = Boolean(selectedSession?.data_sources.some((ref) => {
    const source = sources.find((item) => item.source_id === ref.source_id);
    return !source || source.data_version !== ref.data_version;
  }));
  const latestAssistant = [...displayedMessages].reverse().find((message) => message.role === "assistant" && message.report);
  const activeReport = resultMessage?.report ?? previewReport ?? latestAssistant?.report;
  const openResultDialog = (message: MessageDTO) => {
    setResultMessage(message);
    setPreviewReport(null);
    setResultDialogMessage(message);
  };
  const questionSearchResults = searchOpen
    ? sessions.filter((session) => `${session.title} ${session.last_question}`.toLowerCase().includes(query.toLowerCase()))
    : sessions;

  return (
    <div className={`workbench ${sidebarOpen ? "sidebar-expanded" : "sidebar-collapsed"} ${sidebarResizing ? "sidebar-resizing" : ""}`} style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}>
      <div className={`sidebar-scrim ${sidebarOpen ? "visible" : ""}`} onClick={() => setSidebarOpen(false)} />
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""} ${sidebarResizing ? "sidebar-resizing" : ""}`}>
        <div className="brand-row"><div className="brand-mark"><BarChart3 size={17} /></div><span>质析</span><span className="brand-caption">AGENT</span><button type="button" className="mobile-close icon-button" aria-label="收起侧栏" title="收起侧栏" onClick={() => setSidebarOpen(false)}><X size={17} /></button></div>
        <button type="button" className="new-chat-button" onClick={startNewSession}><MessageSquarePlus size={17} /><span>新建分析</span><span className="shortcut-hint">Ctrl N</span></button>
        <button type="button" className={`sidebar-search ${searchOpen ? "active" : ""}`} onClick={() => setSearchOpen((open) => !open)}><Search size={16} /><span>搜索会话</span><kbd>Ctrl K</kbd></button>
        {searchOpen && <div className="search-input-wrap"><Search size={15} /><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题或问题" /><button type="button" aria-label="关闭搜索" onClick={() => { setSearchOpen(false); setQuery(""); }}><X size={14} /></button></div>}

        <div className="sidebar-section-label"><span>工作区</span><button type="button" title="管理数据源" onClick={() => openDataManager()}><Settings2 size={14} /></button></div>
        <button type="button" className="source-context" onClick={() => openDataManager()}>
          <span className="source-context-icon"><Database size={15} /></span>
          <span><strong>{currentSource?.name ?? "选择数据源"}</strong><small>{currentSource ? `${currentSource.record_count.toLocaleString()} 条记录` : "点击选择数据源"}</small></span>
          <ChevronDown size={14} />
        </button>
        {currentSource?.kind === "demo" && <div className="demo-tag"><span />演示数据 · 模拟记录</div>}

        <div className="sidebar-section-label history-label"><span>{searchOpen ? "搜索结果" : "最近会话"}</span><span className="section-count">{questionSearchResults.length}</span></div>
        <div className="session-list">
          {questionSearchResults.map((session) => (
            <div key={session.session_id} className={`session-row ${session.session_id === sessionId ? "selected" : ""}`}>
              {editingSessionId === session.session_id ? (
                <form className="session-rename-form" onSubmit={(event) => { event.preventDefault(); void saveSessionTitle(); }}>
                  <input autoFocus aria-label="会话标题" value={editingSessionTitle} maxLength={80} onChange={(event) => setEditingSessionTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") { setEditingSessionId(null); setEditingSessionTitle(""); } }} />
                  <button type="submit" className="session-row-action" aria-label="保存标题" disabled={!editingSessionTitle.trim()}><Check size={14} /></button>
                  <button type="button" className="session-row-action" aria-label="取消重命名" onClick={() => { setEditingSessionId(null); setEditingSessionTitle(""); }}><X size={14} /></button>
                </form>
              ) : <>
                <button type="button" className="session-item" onClick={() => selectSession(session.session_id)}>
                  <MessageSquarePlus size={15} /><span><strong>{session.title || "新会话"}</strong><small>{session.data_version !== currentSource?.data_version && <span className="session-stale-badge">旧版</span>}{session.last_question ? shortQuestion(session.last_question, 34) : formatTime(session.updated_at)}</small></span>
                </button>
                <button type="button" className="session-row-action rename-session" aria-label={`重命名 ${session.title || "新会话"}`} title="重命名会话" onClick={() => { setEditingSessionId(session.session_id); setEditingSessionTitle(session.title || "新会话"); }}><Pencil size={13} /></button>
                <button type="button" className="session-row-action delete-session" aria-label={`删除 ${session.title || "新会话"}`} title="删除会话" onClick={() => void deleteSession(session)}><Trash2 size={13} /></button>
              </>}
            </div>
          ))}
          {questionSearchResults.length === 0 && <p className="sidebar-empty">没有匹配的会话</p>}
        </div>

        {comparisonHistory.length > 0 && <>
          <div className="sidebar-section-label comparison-history-label"><span>多文件比较</span><span className="section-count">{comparisonHistory.length}</span></div>
          <div className="comparison-history-list">
            {comparisonHistory.slice(0, 8).map((comparison) => <button key={comparison.comparison_id} type="button" className={`comparison-history-item ${currentComparison?.comparison_id === comparison.comparison_id ? "selected" : ""}`} onClick={() => void selectComparison(comparison.comparison_id)}><GitCompareArrows size={14} /><span><strong>{shortQuestion(comparison.question, 34)}</strong><small>{comparison.children.length} 个数据源 · {comparison.status === "running" ? "分析中" : formatTime(comparison.updated_at)}</small></span></button>)}
          </div>
        </>}

        {questions.length > 0 && (
          <div className="question-index">
            <div className="sidebar-section-label"><span>本会话提问</span><span className="section-count">{questions.length}</span></div>
            <div className="question-list">
              {questions.map((message, index) => (
                <button key={message.message_id} type="button" className="question-index-item" title={message.content} onClick={() => { document.getElementById(message.message_id)?.scrollIntoView({ behavior: "smooth", block: "center" }); closeSidebarOnCompactViewport(); }}>
                  <span className="question-index-number">{String(index + 1).padStart(2, "0")}</span><span>{shortQuestion(message.content, 36)}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="sidebar-footer">
          <button type="button" className="footer-link" onClick={() => setMemoryOpen(true)}><Brain size={15} /><span>长期记忆</span></button>
          <button type="button" className="footer-link" onClick={() => openDataManager()}><Database size={15} /><span>数据与记录</span></button>
          <div className="service-state"><span className={`service-indicator ${apiReady ? "online" : apiReady === false ? "offline" : ""}`} /><span>{apiReady ? "本地服务已连接" : apiReady === false ? "服务未连接" : "正在连接"}</span><CircleHelp size={14} /></div>
        </div>
        <div
          className="sidebar-resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="调整左侧栏宽度"
          aria-valuemin={SIDEBAR_MIN_WIDTH}
          aria-valuemax={maxSidebarWidth}
          aria-valuenow={sidebarWidth}
          tabIndex={0}
          onPointerDown={(event) => {
            if (event.pointerType === "mouse" && event.button !== 0) return;
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            setSidebarResizing(true);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) resizeSidebar(event.clientX);
          }}
          onPointerUp={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
            setSidebarResizing(false);
            saveSidebarWidth();
          }}
          onPointerCancel={() => {
            setSidebarResizing(false);
            saveSidebarWidth();
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
              event.preventDefault();
              resizeSidebar(sidebarWidth + (event.key === "ArrowRight" ? 16 : -16));
              saveSidebarWidth();
            } else if (event.key === "Home" || event.key === "End") {
              event.preventDefault();
              resizeSidebar(event.key === "Home" ? SIDEBAR_MIN_WIDTH : maxSidebarWidth);
              saveSidebarWidth();
            }
          }}
        />
      </aside>

      <main className="main-column">
        <header className="topbar">
          <button type="button" className="mobile-menu icon-button" aria-label={sidebarOpen ? "收起会话侧栏" : "打开会话侧栏"} aria-expanded={sidebarOpen} title={sidebarOpen ? "收起侧栏" : "打开侧栏"} onClick={() => setSidebarOpen((open) => !open)}><Menu size={19} /></button>
          <div className="breadcrumb"><span>质量分析</span><span className="crumb-slash">/</span><strong>{selectedSession?.title ?? (currentComparison ? "多文件比较" : "新建分析")}</strong></div>
          <div className="topbar-right">
            <span className="model-pill" title={modelHealth?.message ?? "正在检查本地 Ollama"}><span className={`model-dot ${modelHealth?.status === "available" ? "model-ready" : modelHealth?.status === "unavailable" ? "model-down" : "model-wait"}`} />Ollama <span className="model-name">{health?.model_name ?? "本地模型"}</span></span>
          </div>
        </header>

        <div className="chat-scroll" id="chat-scroll" ref={chatScrollRef} onScroll={(event) => { const element = event.currentTarget; shouldAutoScrollRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 120; }}>
          <div className={`conversation ${displayedMessages.length === 0 && !activeRun && !currentComparison ? "conversation-empty" : ""}`}>
            {displayedMessages.length === 0 && !activeRun && !currentComparison ? (
              <div className="welcome-state">
                <div className="welcome-symbol"><BarChart3 size={25} /></div>
                <p className="welcome-kicker">MANUFACTURING QUALITY AGENT</p>
                <h1>从一个问题开始分析</h1>
                <p className="welcome-copy">可在输入框添加一个或多个数据文件，再直接提问或比较不同文件。</p>
                <div className="example-grid">
                  {EXAMPLE_QUESTIONS.map((example, index) => <button type="button" key={example} className="example-card" onClick={() => { setInput(example); textareaRef.current?.focus(); }}><span>{index === 0 ? "趋势与风险" : index === 1 ? "班次对比" : "工艺能力"}</span><strong>{example}</strong><ArrowUpRightIcon /></button>)}
                </div>
                <div className="welcome-footnote"><span className="demo-indicator" />{currentSource?.kind === "demo" ? "当前使用模拟演示数据" : `${currentSource?.record_count.toLocaleString() ?? 0} 条记录已就绪`}</div>
              </div>
            ) : (
                <div className="message-list">
                {displayedMessages.map((message) => message.role === "user" ? (
                  <article className="user-turn" id={message.message_id} key={message.message_id}>
                    <div className="user-bubble">{message.content}</div><span className="user-time">{formatTime(message.created_at)}</span>
                    {message.data_sources && message.data_sources.length > 0 && <div className="user-data-sources">{message.data_sources.map((source) => <button type="button" className="user-data-source" key={source.source_id} title={`查看 ${source.name} 中的数据`} aria-label={`查看数据：${source.name}`} onClick={() => openDataManager(source.source_id)}><FileSpreadsheet size={11} />{source.name}</button>)}</div>}
                  </article>
                ) : <div key={message.message_id}>
                  <AssistantTurn message={message} events={message.run_id ? runEvents[message.run_id] : []} onOpenResults={openResultDialog} onSubmitFollowup={(question) => void submitQuestion(question)} onRetry={(question) => void submitQuestion(question)} />
                  {message.report?.task === "multi_file_comparison" && message.report.comparison && <ComparisonResult comparison={message.report.comparison} events={runEvents} onCancel={() => undefined} onOpenResult={(item) => openResultDialog({ ...item, content: message.content })} />}
                </div>)}
                {activeRun && !displayedMessages.some((message) => message.run_id === activeRun.run_id && message.role === "assistant") && (
                  <AssistantTurn
                    message={{ message_id: `active-${activeRun.run_id}`, session_id: activeRun.session_id, role: "assistant", content: activeRun.report?.explanation ?? "", created_at: activeRun.created_at, run_id: activeRun.run_id, report: activeRun.report }}
                    running
                    events={runEvents[activeRun.run_id] ?? []}
                    onOpenResults={(item) => openResultDialog(item)}
                  />
                )}
                {currentComparison && (comparisonParentSessionId !== sessionId) && <>
                  <article className="user-turn" id={`comparison-question-${currentComparison.comparison_id}`}>
                    <div className="user-bubble">{currentComparison.question}</div><span className="user-time">{formatTime(currentComparison.created_at)}</span>
                  </article>
                  <ComparisonResult comparison={currentComparison} events={runEvents} onCancel={() => void stopComparison()} onOpenResult={(item) => openResultDialog({ ...item, content: currentComparison.question })} />
                </>}
                {currentComparison && comparisonParentSessionId === sessionId && <ComparisonResult comparison={currentComparison} events={runEvents} onCancel={() => void stopComparison()} onOpenResult={(item) => openResultDialog({ ...item, content: currentComparison.question })} />}
                <div className="conversation-bottom" />
              </div>
            )}
          </div>
        </div>

        {(error || notice || selectedSessionIsStale) && <div className={`notice-bar ${error || selectedSessionIsStale ? "notice-error" : "notice-info"}`} role={error || selectedSessionIsStale ? "alert" : "status"}>
          <span>{selectedSessionIsStale ? "此历史会话使用的旧数据版本已不可用，消息仍保留供查看。新建会话后即可使用当前数据继续。" : error || notice}</span>
          {selectedSessionIsStale && <button type="button" className="notice-action" onClick={startNewSession}>新建会话</button>}
          {!selectedSessionIsStale && <button type="button" aria-label="关闭提示" onClick={() => { setError(""); setNotice(""); }}><X size={14} /></button>}
        </div>}

        <div className={`composer-area ${dropActive ? "drop-active" : ""}`}
          onDragOver={(event) => { if (event.dataTransfer.types.includes("Files")) { event.preventDefault(); setDropActive(true); } }}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropActive(false); }}
          onDrop={(event) => { if (event.dataTransfer.files.length) { event.preventDefault(); setDropActive(false); void uploadFiles(event.dataTransfer.files); } }}>
          {input.startsWith("/") && !["/new", "/data"].includes(input.trim().toLowerCase()) && (
            <div className="slash-command-menu" role="menu" aria-label="快捷操作">
              <button type="button" role="menuitem" onMouseDown={(event) => event.preventDefault()} onClick={() => { setInput(""); startNewSession(); }}><kbd>/new</kbd><span>新建分析</span></button>
              <button type="button" role="menuitem" onMouseDown={(event) => event.preventDefault()} onClick={() => { setInput(""); openDataManager(); }}><kbd>/data</kbd><span>管理对话文件</span></button>
            </div>
          )}
          <input ref={fileInputRef} type="file" accept=".csv,text/csv" multiple hidden disabled={uploadingFiles || sourceSelectionLocked} onChange={(event) => { void uploadFiles(event.target.files ?? undefined); event.currentTarget.value = ""; }} />
          <form className="composer" onSubmit={(event) => { event.preventDefault(); void submitQuestion(); }}>
            <textarea
              ref={textareaRef}
              value={input}
              rows={1}
              placeholder={activeRun ? "本轮分析完成后继续提问…" : currentComparison?.status === "running" ? "等待各文件完成本轮分析…" : "描述一个质量问题，或追问上一轮的结果…"}
              disabled={Boolean(activeRun) || currentComparison?.status === "running" || busy || !apiReady}
              onChange={(event) => { setInput(event.target.value); event.target.style.height = "auto"; event.target.style.height = `${Math.min(event.target.scrollHeight, 160)}px`; }}
              onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submitQuestion(); } }}
              aria-label="输入分析问题"
            />
            <div className="composer-toolbar">
              <div className="composer-context">
                <div className="attachment-popover-anchor" ref={attachmentPopoverRef}>
                  <button type="button" className="composer-file-count attachment-toggle" aria-expanded={attachmentsOpen} aria-controls="composer-attachment-popover" onClick={() => setAttachmentsOpen((open) => !open)} title="展开本轮文件和分析方式">
                    <Database size={14} />本轮 {turnSourceIds.length} 个文件{turnSourceIds.length > 1 && <span className="composer-file-mode">· {analysisMode === "merge" ? "合并分析" : "逐文件比较"}</span>}<ChevronDown size={13} className={attachmentsOpen ? "attachment-chevron-open" : ""} />
                  </button>
                  {attachmentsOpen && <section className="attachment-popover" id="composer-attachment-popover" aria-label="本轮文件和分析方式">
                    <header className="attachment-popover-header">
                      <div><strong>本轮文件</strong><span>{turnSourceIds.length} 个 · 质量分析将读取这些文件</span></div>
                      <button type="button" className="attachment-popover-close" aria-label="关闭文件面板" onClick={() => setAttachmentsOpen(false)}><X size={15} /></button>
                    </header>
                    {turnSourceIds.length > 0 ? <ul className="attachment-popover-list">
                      {turnSourceIds.map((id) => {
                        const source = sources.find((item) => item.source_id === id);
                        return <li className="attachment-popover-item" key={id}>
                          <FileSpreadsheet size={15} />
                          <span className="attachment-popover-copy"><button type="button" className="attachment-source-link" title={`查看 ${source?.name ?? id} 中的数据`} disabled={!source} onClick={() => openDataManager(id)}>{source?.name ?? id}</button><small>{source ? `${source.record_count.toLocaleString()} 条记录` : "文件版本不可用"}</small></span>
                          <button type="button" aria-label={`从本轮移除 ${source?.name ?? id}`} title="从本轮移除" disabled={sourceSelectionLocked} onClick={() => setTurnSourceIds((current) => current.filter((item) => item !== id))}><X size={14} /></button>
                        </li>;
                      })}
                    </ul> : <div className="attachment-popover-empty">当前没有选择数据文件，可直接提问，或添加 CSV 文件。</div>}
                    {turnSourceIds.length > 1 && <div className="attachment-popover-modes">
                      <span>多文件分析方式</span>
                      <div>
                        <button type="button" className={`composer-mode-button ${analysisMode === "merge" ? "active" : ""}`} aria-pressed={analysisMode === "merge"} title="把所选文件的记录合并为一个总体进行筛选和统计。适合同字段、同口径文件；结果不会分别给出每个文件的指标。" data-tooltip="把所选文件的记录合并为一个总体进行筛选和统计。适合同字段、同口径文件；结果不会分别给出每个文件的指标。" disabled={sourceSelectionLocked} onClick={() => setAnalysisMode("merge")}><Database size={13} />合并分析</button>
                        <button type="button" className={`composer-mode-button ${analysisMode === "compare" ? "active" : ""}`} aria-pressed={analysisMode === "compare"} title="在每个文件中独立执行同一个问题，再并列展示结果。适合比较不同年份、产线或批次；各文件统计保持独立。" data-tooltip="在每个文件中独立执行同一个问题，再并列展示结果。适合比较不同年份、产线或批次；各文件统计保持独立。" disabled={sourceSelectionLocked} onClick={() => setAnalysisMode("compare")}><GitCompareArrows size={13} />逐文件比较</button>
                      </div>
                    </div>}
                    <footer className="attachment-popover-footer">
                      <button type="button" className="attachment-add" disabled={uploadingFiles || sourceSelectionLocked} onClick={() => fileInputRef.current?.click()}>{uploadingFiles ? <Activity className="spin" size={14} /> : <Paperclip size={14} />}{uploadingFiles ? "正在添加" : "添加文件"}</button>
                      <button type="button" className="attachment-manage" disabled={sourceSelectionLocked} onClick={() => { setAttachmentsOpen(false); openDataManager(); }}><Database size={14} />管理对话文件</button>
                      <span>对话保留的文件可在管理中切换</span>
                    </footer>
                  </section>}
                </div>
                <span className="composer-hint"><kbd>Enter</kbd> 发送 <span>·</span> <kbd>Shift Enter</kbd> 换行</span>
              </div>
              <div className="composer-actions">
              {activeRun ? (
                <button type="button" className="send-button stop-button" onClick={() => void stopRun()} title="在当前阶段完成后停止"><Square size={13} fill="currentColor" /><span>停止</span></button>
              ) : currentComparison?.status === "running" ? (
                <button type="button" className="send-button stop-button" onClick={() => void stopComparison()} title="向所有数据源发送停止请求"><Square size={13} fill="currentColor" /><span>停止比较</span></button>
              ) : (
                <>
                  <button
                    type="button"
                    className={`voice-button ${isRecording ? "is-recording" : isTranscribing ? "is-transcribing" : ""}`}
                    aria-label={isRecording ? "结束录音并识别" : isTranscribing ? "取消语音识别" : "语音输入"}
                    title={isRecording ? "结束录音并填入草稿" : isTranscribing ? "取消本次识别" : speechStatus?.status === "dependency_missing" ? speechStatus.message : speechStatus?.status === "model_missing" ? `${speechStatus.message} 点击后开始录音。` : "录音只发送到本机服务；停止后会填入可编辑草稿，不会自动发送。"}
                    disabled={!isRecording && !isTranscribing && (apiReady !== true || speechStatus?.status === "dependency_missing" || busy || uploadingFiles || typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined")}
                    onClick={() => {
                      if (isRecording) stopVoiceRecording();
                      else if (isTranscribing) speechAbortRef.current?.abort();
                      else void startVoiceRecording();
                    }}
                  >
                    {isRecording ? <><MicOff size={15} /><span>停止 · {String(Math.floor(recordingSeconds / 60)).padStart(2, "0")}:{String(recordingSeconds % 60).padStart(2, "0")}</span></> : isTranscribing ? <><LoaderCircle size={15} /><span>取消识别</span></> : <><Mic size={15} /><span>语音输入</span></>}
                  </button>
                  <button type="submit" className="send-button" disabled={!input.trim() || busy || !apiReady || isRecording || isTranscribing} title="发送问题"><Send size={16} /><span>发送</span></button>
                </>
              )}
              </div>
            </div>
          </form>
          <p className="composer-disclaimer">模型解释可能出错。关键结论请结合本轮统计、筛选范围和证据复核。</p>
        </div>
      </main>

      {resultDialogMessage && <ResultPanel report={resultDialogMessage.report ?? activeReport} selectedMessage={resultDialogMessage} dataVersion={String(resultDialogMessage.report?.data_version ?? selectedSession?.data_version ?? currentSource?.data_version ?? "")} onClose={() => { setResultDialogMessage(undefined); setResultMessage(undefined); }} />}
      {dataOpen && <DataManager open={dataOpen} initialPreviewId={dataPreviewId} sources={sources} conversationSourceIds={conversationSourceIds} turnSourceIds={turnSourceIds} onClose={closeDataManager} onRefresh={loadSources} onApply={applyDataSelection} />}
      {memoryOpen && <MemoryManager open={memoryOpen} source={currentSource} onClose={() => setMemoryOpen(false)} />}
    </div>
  );
}

function ArrowUpRightIcon() {
  return <span className="example-arrow" aria-hidden="true">↗</span>;
}
