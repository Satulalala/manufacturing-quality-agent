import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, ChevronLeft, ChevronRight, Database, FileSpreadsheet, LoaderCircle, Upload, X } from "lucide-react";
import { api } from "../../app/api";
import type { SourceDTO, SourcePreviewDTO, SourcePreviewFilter } from "../../app/types";

interface DataManagerProps {
  open: boolean;
  initialPreviewId?: string;
  sources: SourceDTO[];
  conversationSourceIds: string[];
  turnSourceIds: string[];
  onClose: () => void;
  onRefresh: () => Promise<SourceDTO[]>;
  onApply: (conversationSourceIds: string[], turnSourceIds: string[]) => Promise<void>;
}

export function DataManager({ open, initialPreviewId, sources, conversationSourceIds, turnSourceIds, onClose, onRefresh, onApply }: DataManagerProps) {
  const [preview, setPreview] = useState<SourcePreviewDTO | null>(null);
  const [previewId, setPreviewId] = useState(initialPreviewId ?? turnSourceIds[0] ?? conversationSourceIds[0] ?? sources[0]?.source_id ?? "");
  const [includedIds, setIncludedIds] = useState(conversationSourceIds);
  const [activeIds, setActiveIds] = useState(turnSourceIds);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(100);
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [filterDrafts, setFilterDrafts] = useState<Array<{ id: number; field: string; value: string; match: SourcePreviewFilter["match"] }>>([]);
  const [filters, setFilters] = useState<SourcePreviewFilter[]>([]);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const wasOpen = useRef(false);
  const filterIdRef = useRef(0);

  useEffect(() => {
    if (!open) {
      wasOpen.current = false;
      return;
    }
    if (wasOpen.current) return;
    wasOpen.current = true;
    setIncludedIds([...conversationSourceIds]);
    setActiveIds([...turnSourceIds]);
    setPreviewId(initialPreviewId ?? turnSourceIds[0] ?? conversationSourceIds[0] ?? sources[0]?.source_id ?? "");
    setPage(0);
    setPageSize(100);
    setSearchDraft("");
    setSearch("");
    setFilterDrafts([]);
    setFilters([]);
    setPreview(null);
    setPreviewError("");
    setError("");
    setNotice("");
  }, [open, initialPreviewId, conversationSourceIds, turnSourceIds, sources]);

  useEffect(() => {
    if (!open || !previewId) { setPreview(null); return; }
    let current = true;
    setLoadingPreview(true);
    setPreviewError("");
    void api.previewSource(previewId, page * pageSize, pageSize, search, filters)
      .then((result) => { if (current) setPreview(result); })
      .catch((reason: Error) => { if (current) { setPreview(null); setPreviewError(reason.message); } })
      .finally(() => { if (current) setLoadingPreview(false); });
    return () => { current = false; };
  }, [open, previewId, page, pageSize, search, filters]);

  if (!open) return null;

  const handleFiles = async (fileList?: FileList | null) => {
    const files = Array.from(fileList ?? []);
    if (!files.length) return;
    const invalidFile = files.find((file) => !file.name.toLowerCase().endsWith(".csv"));
    if (invalidFile) {
      setError(`${invalidFile.name} 不是 CSV 文件。`);
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    const addedIds: string[] = [];
    try {
      for (const file of files) {
        const source = await api.uploadSource(file);
        addedIds.push(source.source_id);
      }
      await onRefresh();
      const nextIncluded = [...new Set([...includedIds, ...addedIds])];
      if (nextIncluded.length > 8) {
        setError("文件已保存到数据列表，但一个会话最多使用 8 个文件。请先取消其他文件。");
        setPreviewId(addedIds[0] ?? previewId);
        setPage(0);
        setSearchDraft("");
        setSearch("");
        setFilterDrafts([]);
        setFilters([]);
        return;
      }
      setIncludedIds(nextIncluded);
      setActiveIds((current) => [...new Set([...current, ...addedIds])]);
      setPreviewId(addedIds[0] ?? previewId);
      setPage(0);
      setSearchDraft("");
      setSearch("");
      setFilterDrafts([]);
      setFilters([]);
      setNotice(`已添加 ${addedIds.length} 个文件；点击“完成”后用于当前对话。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "上传失败");
    } finally {
      setBusy(false);
    }
  };

  const toggleIncluded = (sourceId: string, included: boolean) => {
    if (included) {
      if (!includedIds.includes(sourceId) && includedIds.length >= 8) {
        setError("一个会话最多保留 8 个文件。");
        return;
      }
      setIncludedIds((current) => current.includes(sourceId) ? current : [...current, sourceId]);
      setActiveIds((current) => current.includes(sourceId) ? current : [...current, sourceId]);
    } else {
      setIncludedIds((current) => current.filter((item) => item !== sourceId));
      setActiveIds((current) => current.filter((item) => item !== sourceId));
    }
    setError("");
  };

  const selected = sources.find((source) => source.source_id === previewId);

  const selectPreview = (sourceId: string) => {
    setPreviewId(sourceId);
    setPage(0);
    setSearchDraft("");
    setSearch("");
    setFilterDrafts([]);
    setFilters([]);
  };

  const applyPreviewFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFilters(filterDrafts
      .filter((filter) => filter.field && filter.value.trim())
      .map((filter) => ({ field: filter.field, value: filter.value.trim(), match: filter.match })));
    setSearch(searchDraft.trim());
    setPage(0);
  };

  const clearPreviewFilters = () => {
    setSearchDraft("");
    setSearch("");
    setFilterDrafts((current) => current.map((filter) => ({ ...filter, value: "" })));
    setFilters([]);
    setPage(0);
  };

  const apply = async () => {
    setBusy(true);
    setError("");
    try {
      await onApply(includedIds, activeIds.filter((sourceId) => includedIds.includes(sourceId)));
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存文件选择失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <section className="data-manager" role="dialog" aria-modal="true" aria-labelledby="data-manager-title">
        <header className="modal-header">
          <div className="modal-title-wrap"><span className="modal-icon"><Database size={18} /></span><div><h2 id="data-manager-title">对话文件</h2><p>文件可留在对话中，也可只用于本轮</p></div></div>
          <div className="data-manager-actions">
            <button type="button" className="button button-primary button-small" disabled={busy} onClick={() => void apply()}>{busy ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />}完成</button>
            <button type="button" className="icon-button" aria-label="关闭数据管理" disabled={busy} onClick={onClose}><X size={18} /></button>
          </div>
        </header>
        <div className="data-manager-grid">
          <aside className="source-list-pane">
            <label className="upload-zone" htmlFor="csv-upload">
              {busy ? <LoaderCircle className="spin" size={20} /> : <Upload size={19} />}
              <strong>{busy ? "正在读取 CSV…" : "添加 CSV 文件"}</strong>
              <span>支持多选，单个文件最多 20 MB</span>
            </label>
            <input id="csv-upload" type="file" accept=".csv,text/csv" multiple hidden disabled={busy} onChange={(event) => { void handleFiles(event.target.files); event.currentTarget.value = ""; }} />
            <div className="source-list-heading">数据文件 <span>{sources.length}</span></div>
            <div className="source-list">
              {sources.map((source) => {
                const included = includedIds.includes(source.source_id);
                const active = activeIds.includes(source.source_id);
                return (
                  <div key={source.source_id} className={`source-management-row ${previewId === source.source_id ? "selected" : ""}`}>
                      <button type="button" className="source-option" onClick={() => selectPreview(source.source_id)}>
                      <span className="source-option-icon"><FileSpreadsheet size={17} /></span>
                      <span className="source-option-copy"><strong>{source.name}</strong><small>{source.record_count.toLocaleString()} 条 · {source.kind === "demo" ? "模拟数据" : "CSV"}</small></span>
                    </button>
                    <label className="source-use-toggle" title="保留在这个对话的文件列表中">
                      <input type="checkbox" checked={included} onChange={(event) => toggleIncluded(source.source_id, event.target.checked)} />
                      <span>对话</span>
                    </label>
                    <label className="source-use-toggle source-turn-toggle" title="本轮分析会读取这个文件">
                      <input type="checkbox" checked={active} disabled={!included} onChange={(event) => setActiveIds((current) => event.target.checked ? [...new Set([...current, source.source_id])] : current.filter((item) => item !== source.source_id))} />
                      <span>本轮</span>
                    </label>
                  </div>
                );
              })}
            </div>
            {error && <p className="inline-error" role="alert">{error}</p>}
            {notice && <p className="inline-success">{notice}</p>}
          </aside>
          <div className="preview-pane">
            <div className="preview-heading">
              <div><strong>{selected?.name ?? "选择数据文件"}</strong><span>{preview ? `${preview.total.toLocaleString()} 条记录` : "CSV 预览"}</span></div>
              <span className="data-selection-count">本轮 {activeIds.length} 个 · 对话 {includedIds.length} 个</span>
            </div>
            {selected?.kind === "demo" && <p className="demo-disclaimer">演示数据为程序生成的模拟记录，不代表真实生产结果。</p>}
            {preview && <form className="preview-filters" onSubmit={applyPreviewFilters}>
              <label className="preview-search-field">全文搜索<input type="search" value={searchDraft} maxLength={200} placeholder="搜索所有列" onChange={(event) => setSearchDraft(event.target.value)} /></label>
              <div className="preview-column-filters">
                {filterDrafts.map((filter) => <div className="preview-filter-row" key={filter.id}>
                  <label><span>字段</span><select value={filter.field} onChange={(event) => setFilterDrafts((current) => current.map((item) => item.id === filter.id ? { ...item, field: event.target.value } : item))}>{preview.columns.map((column) => <option value={column} key={column}>{column}</option>)}</select></label>
                  <label><span>匹配</span><select value={filter.match} onChange={(event) => setFilterDrafts((current) => current.map((item) => item.id === filter.id ? { ...item, match: event.target.value as SourcePreviewFilter["match"] } : item))}><option value="contains">包含</option><option value="equals">等于</option></select></label>
                  <label className="preview-filter-value"><span>值</span><input value={filter.value} maxLength={200} placeholder="输入筛选值" onChange={(event) => setFilterDrafts((current) => current.map((item) => item.id === filter.id ? { ...item, value: event.target.value } : item))} /></label>
                  <button type="button" className="preview-filter-remove" aria-label="移除筛选条件" onClick={() => setFilterDrafts((current) => current.filter((item) => item.id !== filter.id))}><X size={14} /></button>
                </div>)}
              </div>
              <div className="preview-filter-actions">
                <button type="button" className="preview-filter-add" disabled={filterDrafts.length >= 12 || preview.columns.length === 0} onClick={() => setFilterDrafts((current) => [...current, { id: ++filterIdRef.current, field: preview.columns[0] ?? "", value: "", match: "contains" }])}>添加筛选</button>
                <div><button type="button" className="preview-filter-clear" onClick={clearPreviewFilters}>清空</button><button type="submit" className="preview-filter-submit">应用筛选</button></div>
              </div>
            </form>}
            {loadingPreview ? <div className="preview-empty"><LoaderCircle className="spin" size={18} />正在读取数据…</div>
              : previewError ? <div className="preview-empty" role="alert">{previewError}</div>
              : preview ? (
              <div className="preview-table-wrap">
                <div className="preview-table-scroll">
                  <table className="preview-table">
                    <thead><tr>{preview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
                    <tbody>{preview.records.length ? preview.records.map((record, index) => <tr key={index}>{preview.columns.map((column) => <td key={column}>{String(record[column] ?? "") || "—"}</td>)}</tr>) : <tr><td className="preview-no-results" colSpan={Math.max(1, preview.columns.length)}>当前筛选条件下没有匹配记录</td></tr>}</tbody>
                  </table>
                </div>
                {preview.total > 0 && (
                  <div className="table-pagination">
                    <span className="table-pagination-count">显示 <strong>{page * pageSize + 1}–{Math.min((page + 1) * pageSize, preview.total)} 条</strong>，共 <strong>{preview.total.toLocaleString()} 条</strong></span>
                    <div className="table-pagination-controls">
                      <button type="button" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}><ChevronLeft size={16} aria-hidden="true" />上一页</button>
                      <span className="table-pagination-page" aria-live="polite">第 <strong>{page + 1}</strong> / {Math.ceil(preview.total / pageSize)} 页</span>
                      <button type="button" disabled={(page + 1) * pageSize >= preview.total} onClick={() => setPage((value) => value + 1)}>下一页<ChevronRight size={16} aria-hidden="true" /></button>
                      <label className="preview-page-size">每页<select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(0); }}><option value={30}>30</option><option value={50}>50</option><option value={100}>100</option><option value={200}>200</option></select>条</label>
                    </div>
                  </div>
                )}
              </div>
            ) : <div className="preview-empty">选择一个数据源以查看记录。</div>}
          </div>
        </div>
      </section>
    </div>
  );
}
