import { Activity, BarChart3, StopCircle } from "lucide-react";
import type { ComparisonDTO, MessageDTO, RunEvent } from "../../app/types";
import { qualityDimensionLabel, qualityValueLabel } from "../../app/qualityLabels";

interface ComparisonResultProps {
  comparison: ComparisonDTO;
  events: Record<string, RunEvent[]>;
  onOpenResult: (message: MessageDTO) => void;
  onCancel: () => void;
}

const statusLabel: Record<string, string> = {
  queued: "排队中", running: "分析中", cancelling: "正在停止", completed: "已完成",
  needs_input: "需要补充", failed: "分析失败", cancelled: "已停止", interrupted: "服务重启中断", not_started: "等待启动",
};

function metric(report: ComparisonDTO["children"][number]["report"], key: string) {
  const raw = report?.baseline?.[key];
  const number = Number(raw);
  return Number.isFinite(number) ? number : null;
}

export function ComparisonResult({ comparison, events, onOpenResult, onCancel }: ComparisonResultProps) {
  const running = comparison.children.some((child) => ["queued", "running", "cancelling"].includes(child.status));
  return (
    <article className="comparison-result" id="comparison-answer">
      <div className="comparison-agent-heading"><span className="assistant-avatar"><Activity size={16} /></span><div><strong>独立数据源分析</strong><span>· {comparison.children.length} 个数据源</span></div>{running && <span className="comparison-live"><i />运行中</span>}</div>
      <div className="comparison-intro">每个 Agent 在各自会话中分析同一个问题。下方结果按数据源并列展示。</div>
      <div className="comparison-table-wrap">
        <table className="comparison-table">
          <thead><tr><th>数据源</th><th>状态</th><th>分析记录</th><th>缺陷数</th><th>不良率</th><th>结果</th></tr></thead>
          <tbody>{comparison.children.map((child) => {
            const report = child.report;
            const eventsForRun = events[child.run_id] ?? [];
            const activeStage = [...eventsForRun].reverse().find((event) => event.type === "stage.started");
            const total = metric(report, "total_count");
            const defects = metric(report, "defect_count");
            const rate = metric(report, "defect_rate_percent");
            return <tr key={child.source_id}>
              <td><strong>{child.source_name}</strong><small>{child.source_id === "demo" ? "演示数据" : "独立会话"}</small></td>
              <td><span className={`comparison-status status-${child.status}`}><i />{activeStage?.label ?? statusLabel[child.status] ?? child.status}</span></td>
              <td>{total == null ? "—" : total.toLocaleString()}</td>
              <td>{defects == null ? "—" : defects.toLocaleString()}</td>
              <td className="comparison-rate">{rate == null ? "—" : `${rate.toFixed(2)}%`}</td>
              <td>{report ? <button type="button" className="text-action" onClick={() => onOpenResult({ message_id: `compare-${comparison.comparison_id}-${child.source_id}`, session_id: child.session_id, role: "assistant", content: String(report.explanation ?? report.summary ?? ""), created_at: comparison.updated_at, run_id: child.run_id, report })}><BarChart3 size={14} />详情</button> : <span className="comparison-wait">{child.status === "failed" ? "可重试" : "等待统计"}</span>}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      <div className="comparison-reports">
        {comparison.children.map((child) => <section className="comparison-report-card" key={child.source_id}>
          <div><strong>{child.source_name}</strong><span className={`comparison-status status-${child.status}`}><i />{statusLabel[child.status] ?? child.status}</span></div>
          {child.report?.explanation || child.report?.summary ? <p>{String(child.report.explanation ?? child.report.summary)}</p> : <p className="comparison-wait">{child.status === "running" || child.status === "queued" ? "" : "结果将在本源分析完成后显示。"}</p>}
          {Array.isArray(child.report?.top_factors) && child.report.top_factors.length > 0 && <small>首要候选：{qualityDimensionLabel(child.report.top_factors[0].dimension)} = {qualityValueLabel(child.report.top_factors[0].dimension, child.report.top_factors[0].value)}</small>}
        </section>)}
      </div>
      {running && <button type="button" className="comparison-cancel" onClick={onCancel}><StopCircle size={14} />停止所有数据源</button>}
      <p className="comparison-footnote">各数据源独立使用自己的历史筛选和分析会话；对比结果不推断跨文件因果关系。</p>
    </article>
  );
}
