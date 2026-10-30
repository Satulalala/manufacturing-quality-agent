import { useEffect, useState } from "react";
import { GitCompareArrows, X } from "lucide-react";
import type { SourceDTO } from "../../app/types";

interface ComparisonDialogProps {
  open: boolean;
  sources: SourceDTO[];
  selectedSourceId: string;
  onClose: () => void;
  onStart: (question: string, sourceIds: string[]) => void;
}

export function ComparisonDialog({ open, sources, selectedSourceId, onClose, onStart }: ComparisonDialogProps) {
  const [selected, setSelected] = useState<string[]>([]);
  const [question, setQuestion] = useState("");

  useEffect(() => {
    if (!open) return;
    const other = sources.find((source) => source.source_id !== selectedSourceId);
    setSelected([selectedSourceId, ...(other ? [other.source_id] : [])].filter(Boolean));
    setQuestion("");
  }, [open, selectedSourceId, sources]);

  if (!open) return null;

  const toggle = (sourceId: string) => {
    setSelected((current) => current.includes(sourceId) ? current.filter((id) => id !== sourceId) : current.length < 8 ? [...current, sourceId] : current);
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="comparison-dialog" role="dialog" aria-modal="true" aria-labelledby="compare-title">
        <header className="modal-header">
          <div className="modal-title-wrap"><span className="modal-icon"><GitCompareArrows size={18} /></span><div><h2 id="compare-title">多文件比较</h2><p>每个文件分别分析，历史上下文彼此独立</p></div></div>
          <button type="button" className="icon-button" aria-label="关闭比较窗口" onClick={onClose}><X size={18} /></button>
        </header>
        <div className="comparison-dialog-body">
          <label className="compare-question-label"><span>本轮问题</span><textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} maxLength={4000} placeholder="例如：比较最近一个月各产线的不良率与主要风险因素" /></label>
          <div className="compare-source-heading"><strong>选择数据源</strong><span>{selected.length} / 8</span></div>
          <div className="compare-source-list">
            {sources.map((source) => (
              <label key={source.source_id} className={`compare-source-row ${selected.includes(source.source_id) ? "checked" : ""}`}>
                <input type="checkbox" checked={selected.includes(source.source_id)} onChange={() => toggle(source.source_id)} />
                <span className="compare-checkmark" />
                <span className="compare-source-info"><strong>{source.name}</strong><small>{source.record_count.toLocaleString()} 条 · {source.kind === "demo" ? "模拟数据" : "CSV"}</small></span>
              </label>
            ))}
          </div>
          <p className="compare-disclaimer">比较会为每个数据源创建独立会话。统计与解释不会合并不同文件的数据。</p>
          <div className="compare-dialog-actions"><button type="button" className="button button-quiet" onClick={onClose}>取消</button><button type="button" className="button button-primary" disabled={selected.length < 2 || !question.trim()} onClick={() => onStart(question.trim(), selected)}><GitCompareArrows size={15} />分别分析并比较</button></div>
        </div>
      </section>
    </div>
  );
}
