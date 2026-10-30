import { useState } from "react";
import { Activity, BarChart3, Bot, Check, ChevronDown, ChevronRight, Copy, RotateCcw, Send, Sparkles } from "lucide-react";
import { Markdown } from "./Markdown";
import type { MessageDTO, QualityReport, RunEvent } from "./types";
import { qualityDimensionLabel, qualityValueLabel } from "./qualityLabels";

interface AssistantTurnProps {
  message: MessageDTO;
  running?: boolean;
  events?: RunEvent[];
  onOpenResults: (message: MessageDTO) => void;
  onSubmitFollowup?: (question: string) => void;
  onRetry?: (question: string) => void;
}

function sourceLabel(report?: QualityReport | null) {
  if (report?.task === "direct_answer") return "直接回答";
  if (report?.task === "multi_file_comparison") return "逐文件比较";
  if (report?.explanation_source === "model") return "模型分析";
  if (report?.explanation_source === "fallback") return "证据回退说明";
  return "分析结果";
}

type StageTimelineRow = {
  key: string;
  stage: string;
  label: string;
  status: "active" | "done";
  elapsedMs?: number;
};

function buildStageTimeline(events: RunEvent[]): StageTimelineRow[] {
  const rows: StageTimelineRow[] = [];
  let sequence = 0;

  for (const event of events) {
    if (event.type !== "stage.started" && event.type !== "stage.completed") continue;
    const stage = event.stage ?? event.label ?? "stage";
    const label = event.label ?? event.stage ?? "处理本轮内容";

    if (event.type === "stage.started") {
      rows.push({ key: `${stage}-${sequence++}`, stage, label, status: "active" });
      continue;
    }

    let activeIndex = -1;
    for (let index = rows.length - 1; index >= 0; index -= 1) {
      if (rows[index].stage === stage && rows[index].status === "active") {
        activeIndex = index;
        break;
      }
    }
    if (activeIndex >= 0) {
      rows[activeIndex] = { ...rows[activeIndex], status: "done", elapsedMs: event.elapsed_ms ?? undefined };
    } else {
      rows.push({ key: `${stage}-${sequence++}`, stage, label, status: "done", elapsedMs: event.elapsed_ms ?? undefined });
    }
  }

  return rows;
}

function formatElapsedTime(elapsedMs: number) {
  if (elapsedMs < 1) return "<1 毫秒";
  if (elapsedMs < 10) return `${elapsedMs.toFixed(1)} 毫秒`;
  if (elapsedMs < 1000) return `${Math.round(elapsedMs)} 毫秒`;
  return `${(elapsedMs / 1000).toFixed(1)} 秒`;
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function InlineResultSummary({ report }: { report?: QualityReport | null }) {
  if (!report || report.task === "direct_answer" || ["error", "cancelled", "needs_input"].includes(String(report.status))) return null;
  const baseline = report.baseline ?? {};
  const total = finiteNumber(baseline.total_count);
  const defects = finiteNumber(baseline.defect_count);
  const defectRate = finiteNumber(baseline.defect_rate_percent) ?? (total && defects != null ? defects / total * 100 : null);
  if (total == null && defects == null && defectRate == null) return null;

  const primaryFactor = report.top_factors?.[0];
  const factorRate = primaryFactor
    ? finiteNumber(primaryFactor.defect_rate_percent) ?? finiteNumber(primaryFactor.defect_rate)
    : null;
  const factorRateLabel = factorRate == null ? "" : `${(factorRate <= 1 ? factorRate * 100 : factorRate).toFixed(2)}%`;
  const filters = report.filters ?? {};
  const startDate = String(filters.start_date ?? "").trim();
  const endDate = String(filters.end_date ?? "").trim();
  const requestedDate = startDate && endDate
    ? `${startDate} 至 ${endDate}`
    : startDate
      ? `${startDate} 起`
      : endDate
        ? `截至 ${endDate}`
        : "全部日期";
  const conditions = Object.entries(filters)
    .filter(([key, value]) => !["start_date", "end_date"].includes(key) && value != null && value !== "" && (!Array.isArray(value) || value.length > 0))
    .map(([key, value]) => `${qualityDimensionLabel(key)}：${(Array.isArray(value) ? value : [value]).map((item) => qualityValueLabel(key, item)).join("、")}`);
  const dataScope = report.data_scope ?? {};
  const matchedCount = finiteNumber(dataScope.matched_count);
  const sourceCount = finiteNumber(dataScope.source_count);
  const actualStartDate = String(dataScope.actual_start_date ?? "");
  const actualEndDate = String(dataScope.actual_end_date ?? "");

  return (
    <section className="inline-result-summary" aria-label="本轮统计摘要">
      <div className="inline-result-heading"><BarChart3 size={15} /><strong>本轮数据摘要</strong></div>
      <div className="inline-result-metrics">
        <div><span>分析记录</span><strong>{total == null ? "—" : total.toLocaleString()}</strong></div>
        <div><span>缺陷数量</span><strong>{defects == null ? "—" : defects.toLocaleString()}</strong></div>
        <div><span>总体不良率</span><strong>{defectRate == null ? "—" : `${defectRate.toFixed(2)}%`}</strong></div>
      </div>
      {report.data_scope && <div className="inline-retrieval-scope">
        <strong>本次检索范围</strong>
        <span>筛选日期：{requestedDate}</span>
        {conditions.map((condition) => <span key={condition}>{condition}</span>)}
        {matchedCount != null && <span>命中记录：{matchedCount.toLocaleString()}{sourceCount == null ? "" : ` / ${sourceCount.toLocaleString()}`} 条</span>}
        {actualStartDate && actualEndDate
          ? <span>命中记录实际日期：{actualStartDate} 至 {actualEndDate}</span>
          : matchedCount === 0
            ? <span>此筛选范围内没有匹配记录</span>
            : null}
      </div>}
      {primaryFactor && <div className="inline-primary-factor"><span>首要候选因素</span><strong>{qualityDimensionLabel(primaryFactor.dimension)} = {qualityValueLabel(primaryFactor.dimension, primaryFactor.value) || "—"}</strong>{factorRateLabel && <b>{factorRateLabel}</b>}</div>}
    </section>
  );
}

export function AssistantTurn({ message, running = false, events = [], onOpenResults, onSubmitFollowup, onRetry }: AssistantTurnProps) {
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [lsl, setLsl] = useState("");
  const [usl, setUsl] = useState("");
  const [unit, setUnit] = useState("");
  const [field, setField] = useState("torque");
  const report = message.report;
  const stageEvents = events.filter((event) => event.type === "stage.started" || event.type === "stage.completed");
  const stageRows = buildStageTimeline(stageEvents);
  const currentStage = [...stageEvents].reverse().find((event) => event.type === "stage.started");
  const statusText = running
    ? currentStage?.label ?? "正在准备分析…"
    : report?.status === "needs_input"
      ? "需要补充参数"
      : report?.status === "cancelled"
        ? "本轮已停止"
        : report?.status === "error"
          ? "分析未完成"
          : sourceLabel(report);
  const content = message.content || (running ? "" : String(report?.summary ?? ""));

  return (
    <article className={`assistant-turn ${running ? "is-running" : ""}`} id={message.message_id}>
      <div className="assistant-avatar" aria-hidden="true"><Bot size={17} /></div>
      <div className="assistant-main">
        <div className="turn-heading">
          <strong>质量 Agent</strong>
          <span className="turn-separator">·</span>
          <span>{statusText}</span>
          {report?.elapsed_ms != null && !running && <span className="turn-duration" title="本轮总耗时；各阶段耗时仅统计对应阶段">{formatElapsedTime(report.elapsed_ms)}</span>}
        </div>
        <div className="assistant-content">
          {content ? <Markdown>{content}</Markdown> : running ? <div className="thinking-line"><span className="pulse-dot" />{statusText}</div> : null}
          {running && content && <div className="thinking-line"><span className="pulse-dot" />{statusText}</div>}
          {report?.status === "error" && report?.llm_status && <p className="muted-note">模型状态：{String(report.llm_status)}</p>}
        </div>
        {!running && report?.task !== "direct_answer" && <InlineResultSummary report={report} />}
        {!running && report?.status === "needs_input" && report?.task === "cpk" && onSubmitFollowup && (
          <form className="cpk-followup" onSubmit={(event) => {
            event.preventDefault();
            const lower = Number(lsl);
            const upper = Number(usl);
            if (!Number.isFinite(lower) || !Number.isFinite(upper) || upper <= lower || !unit.trim()) return;
            const fieldLabel = field === "torque" ? "扭矩" : field === "pressure" ? "压力" : "温度";
            onSubmitFollowup(`${fieldLabel}，下限 LSL=${lower}，上限 USL=${upper}，单位是 ${unit.trim()}，确认与数据一致`);
          }}>
            <div className="cpk-form-heading"><strong>补充 Cpk 规格</strong><span>单位需与数据列一致，系统不会自动换算。</span></div>
            <div className="cpk-fields">
              <label><span>参数</span><select value={field} onChange={(event) => setField(event.target.value)}><option value="torque">扭矩</option><option value="pressure">压力</option><option value="temperature">温度</option></select></label>
              <label><span>下限 LSL</span><input inputMode="decimal" value={lsl} onChange={(event) => setLsl(event.target.value)} placeholder="例如 40" required /></label>
              <label><span>上限 USL</span><input inputMode="decimal" value={usl} onChange={(event) => setUsl(event.target.value)} placeholder="例如 50" required /></label>
              <label><span>单位</span><input value={unit} onChange={(event) => setUnit(event.target.value)} placeholder="例如 N·m" required /></label>
            </div>
            <button type="submit" className="cpk-submit" disabled={!lsl || !usl || !unit.trim() || Number(usl) <= Number(lsl)}><Send size={13} />确认并继续</button>
          </form>
        )}
        {!running && content && <div className="turn-actions">
          {report && !["direct_answer", "multi_file_comparison"].includes(String(report.task)) && report.status !== "cancelled" && report.status !== "error" && <button type="button" className="text-action result-action" onClick={() => onOpenResults(message)}><BarChart3 size={15} />查看本轮结果</button>}
          {report?.status === "error" && report.question && onRetry && <button type="button" className="text-action retry-action" onClick={() => onRetry(String(report.question))}><RotateCcw size={14} />重试本轮</button>}
          {report?.explanation_source === "model" && <span className="source-proof"><Sparkles size={13} />引用基于本轮分析证据</span>}
          <button type="button" className="text-action copy-action" aria-label={copied ? "已复制" : "复制回答"} title={copied ? "已复制" : "复制回答"} onClick={() => { void navigator.clipboard.writeText(content).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1400); }).catch(() => undefined); }}>
            {copied ? <Check size={14} /> : <Copy size={14} />}{copied && <span>已复制</span>}
          </button>
        </div>}
        {report?.task !== "direct_answer" && stageEvents.length > 0 && (
          <div className="execution-block">
            <button className="execution-toggle" type="button" onClick={() => setTimelineOpen((open) => !open)} aria-expanded={timelineOpen}>
              <Activity size={15} />
              <span>{running ? "查看执行过程" : `${stageRows.filter((stage) => stage.status === "done").length} 个执行阶段`}</span>
              {timelineOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            </button>
            {timelineOpen && (
              <>
                <ol className="execution-timeline">
                  {stageRows.map((stage) => (
                    <li key={stage.key} className={stage.status === "active" ? "stage-active" : "stage-done"}>
                      <span className="timeline-mark">{stage.status === "done" ? "✓" : "·"}</span>
                      <span>{stage.label}</span>
                      {stage.status === "done" && stage.elapsedMs != null && <time>{formatElapsedTime(stage.elapsedMs)}</time>}
                    </li>
                  ))}
                </ol>
                <p className="execution-timing-note">阶段时间单独计量，总耗时还包含阶段间的处理开销。</p>
              </>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
