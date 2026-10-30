import { useEffect, useState, type FormEvent } from "react";
import { Brain, Check, Clock3, LoaderCircle, Trash2, X } from "lucide-react";
import { api } from "../../app/api";
import type { MemoryDTO, SourceDTO, SourceDimensionsDTO } from "../../app/types";

interface MemoryManagerProps {
  open: boolean;
  source?: SourceDTO;
  onClose: () => void;
}

export function MemoryManager({ open, source, onClose }: MemoryManagerProps) {
  const [memories, setMemories] = useState<MemoryDTO[]>([]);
  const [dimensions, setDimensions] = useState<SourceDimensionsDTO | null>(null);
  const [includeHistory, setIncludeHistory] = useState(false);
  const [style, setStyle] = useState("standard");
  const [line, setLine] = useState("");
  const [model, setModel] = useState("");
  const [workstation, setWorkstation] = useState("");
  const [field, setField] = useState("torque");
  const [lsl, setLsl] = useState("");
  const [usl, setUsl] = useState("");
  const [unit, setUnit] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = async () => {
    const rows = await api.memories(includeHistory);
    setMemories(rows);
    const savedStyle = rows.find((item) => item.status === "active" && item.memory_type === "preference" && item.memory_key === "report_style");
    setStyle(String(savedStyle?.content.value ?? "standard"));
  };

  useEffect(() => {
    if (!open) return;
    setError("");
    void refresh().catch((reason: Error) => setError(reason.message));
  }, [open, includeHistory]);

  useEffect(() => {
    if (!open || !source) { setDimensions(null); return; }
    void api.sourceDimensions(source.source_id).then((value) => {
      setDimensions(value);
      setLine((current) => current || value.production_lines[0] || "");
      setModel((current) => current || value.vehicle_models[0] || "");
      setWorkstation((current) => current || value.workstations[0] || "");
    }).catch((reason: Error) => setError(reason.message));
  }, [open, source?.source_id]);

  if (!open) return null;

  const savePreference = async () => {
    setBusy(true); setError(""); setNotice("");
    try {
      await api.saveMemory({
        memory_type: "preference",
        memory_key: "report_style",
        content: { value: style },
        source: "用户在工作台的长期记忆管理中明确确认",
        confirmed: true,
      });
      await refresh();
      setNotice("表达偏好已确认保存，并会用于后续会话。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败"); }
    finally { setBusy(false); }
  };

  const saveSpecification = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!source || !dimensions) return;
    const lower = Number(lsl); const upper = Number(usl);
    if (!Number.isFinite(lower) || !Number.isFinite(upper) || upper <= lower || !unit.trim()) {
      setError("请填写有效的规格上下限和单位；USL 必须大于 LSL。");
      return;
    }
    setBusy(true); setError(""); setNotice("");
    try {
      await api.saveMemory({
        memory_type: "specification",
        memory_key: "cpk_specification",
        content: { field, lsl: lower, usl: upper, unit: unit.trim() },
        scope: {
          source_id: source.source_id,
          data_version: source.data_version,
          production_line: line,
          vehicle_model: model,
          workstation,
          field,
        },
        unit: unit.trim(),
        source: "用户在工作台长期记忆管理中确认；绑定当前数据版本与精确范围",
        confirmed: true,
      });
      setLsl(""); setUsl(""); setUnit("");
      await refresh();
      setNotice("Cpk 规格已绑定当前数据版本和选择范围。请确认单位与数据列一致。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败"); }
    finally { setBusy(false); }
  };

  const remove = async (memoryId: string) => {
    setError(""); setNotice("");
    try {
      await api.deleteMemory(memoryId);
      await refresh();
      setNotice("已从当前记忆中删除。历史版本仍可在“查看历史版本”中查看。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "删除失败"); }
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="memory-manager" role="dialog" aria-modal="true" aria-labelledby="memory-title">
        <header className="modal-header">
          <div className="modal-title-wrap"><span className="modal-icon"><Brain size={18} /></span><div><h2 id="memory-title">长期记忆</h2><p>只保存你明确确认的偏好与规格</p></div></div>
          <button type="button" className="icon-button" aria-label="关闭长期记忆" onClick={onClose}><X size={18} /></button>
        </header>
        <div className="memory-scroll">
          <section className="memory-section">
            <div className="section-heading"><div><h3>报告表达偏好</h3><p>跨会话生效；不会改变统计结果。</p></div><span className="confirmed-badge"><Check size={12} />需确认</span></div>
            <div className="memory-preference-row">
              <label className="memory-select"><span>模型回复风格</span><select value={style} onChange={(event) => setStyle(event.target.value)}><option value="standard">标准表达</option><option value="conclusion_first">结论优先</option></select></label>
              <button type="button" className="button button-primary button-small" disabled={busy} onClick={() => void savePreference()}>{busy ? <LoaderCircle className="spin" size={13} /> : "确认并保存"}</button>
            </div>
          </section>

          <section className="memory-section">
            <div className="section-heading"><div><h3>确认 Cpk 规格</h3><p>绑定数据版本、产线、车型、工位和工艺参数，不会自动换算单位。</p></div></div>
            {source && dimensions ? (
              <form className="specification-form" onSubmit={(event) => void saveSpecification(event)}>
                <div className="scope-source"><strong>{source.name}</strong><span>数据版本 {source.data_version.slice(0, 10)}</span></div>
                <div className="spec-fields">
                  <label><span>产线</span><select required value={line} onChange={(event) => setLine(event.target.value)}>{dimensions.production_lines.map((value) => <option key={value}>{value}</option>)}</select></label>
                  <label><span>车型</span><select required value={model} onChange={(event) => setModel(event.target.value)}>{dimensions.vehicle_models.map((value) => <option key={value}>{value}</option>)}</select></label>
                  <label><span>工位</span><select required value={workstation} onChange={(event) => setWorkstation(event.target.value)}>{dimensions.workstations.map((value) => <option key={value}>{value}</option>)}</select></label>
                  <label><span>参数</span><select value={field} onChange={(event) => setField(event.target.value)}><option value="torque">扭矩</option><option value="pressure">压力</option><option value="temperature">温度</option></select></label>
                  <label><span>下限 LSL</span><input inputMode="decimal" required value={lsl} onChange={(event) => setLsl(event.target.value)} placeholder="手册确认值" /></label>
                  <label><span>上限 USL</span><input inputMode="decimal" required value={usl} onChange={(event) => setUsl(event.target.value)} placeholder="手册确认值" /></label>
                  <label className="unit-field"><span>单位</span><input required value={unit} onChange={(event) => setUnit(event.target.value)} placeholder="如 N·m、MPa、℃" /></label>
                </div>
                <div className="memory-confirm-note"><Clock3 size={13} />保存表示你已核对规格文件及单位；系统只在此数据版本和范围内使用。</div>
                <button className="button button-primary button-small" type="submit" disabled={busy || !line || !model || !workstation}>{busy ? <LoaderCircle className="spin" size={13} /> : "确认并保存规格"}</button>
              </form>
            ) : <div className="memory-empty">当前数据源暂无可绑定的 Cpk 范围，请先选择含产线、车型与工位字段的数据。</div>}
          </section>

          <section className="memory-section memory-records">
            <div className="section-heading"><div><h3>已确认的记忆</h3><p>模型不会自动写入或修改这些内容。</p></div><label className="history-toggle"><input type="checkbox" checked={includeHistory} onChange={(event) => setIncludeHistory(event.target.checked)} />查看历史版本</label></div>
            {memories.length ? memories.map((item) => (
              <article className={`memory-card ${item.status !== "active" ? "memory-old" : ""}`} key={item.memory_id}>
                <div className="memory-card-top"><div><strong>{memoryLabel(item)}</strong><span>v{item.version} · {item.status === "active" ? "生效中" : item.status}</span></div>{item.status === "active" && <button type="button" className="memory-delete" aria-label={`删除${memoryLabel(item)}`} onClick={() => void remove(item.memory_id)}><Trash2 size={14} /></button>}</div>
                <p>{JSON.stringify(item.content)}</p>
                {Object.keys(item.scope).length > 0 && <small>适用范围：{JSON.stringify(item.scope)}</small>}
                <small>来源：{item.source}</small>
              </article>
            )) : <div className="memory-empty">还没有已确认的长期记忆。当前模型回复和分析记录不会自动保存为记忆。</div>}
          </section>
          {(error || notice) && <div className={`notice-bar ${error ? "notice-error" : "notice-info"}`} role={error ? "alert" : "status"}><span>{error || notice}</span></div>}
        </div>
      </section>
    </div>
  );
}

function memoryLabel(memory: MemoryDTO) {
  if (memory.memory_type === "preference" && memory.memory_key === "report_style") return "报告表达偏好";
  if (memory.memory_type === "specification") return `Cpk 规格 · ${String(memory.content.field ?? "工艺参数")}`;
  return memory.memory_key;
}
