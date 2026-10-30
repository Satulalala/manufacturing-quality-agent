export interface SourceDTO {
  source_id: string;
  name: string;
  kind: "demo" | "upload";
  record_count: number;
  data_version: string;
}

export interface SpeechStatusDTO {
  status: "ready" | "model_missing" | "dependency_missing";
  model_name: string;
  message: string;
}

export interface SpeechTranscriptionDTO {
  text: string;
  language: string;
  duration_seconds: number;
}

export interface SourcePreviewDTO {
  source_id: string;
  offset: number;
  limit: number;
  total: number;
  columns: string[];
  records: Record<string, unknown>[];
}

export interface SourcePreviewFilter {
  field: string;
  value: string;
  match: "contains" | "equals";
}

export interface SourceDimensionsDTO {
  source_id: string;
  production_lines: string[];
  vehicle_models: string[];
  workstations: string[];
}

export interface MemoryDTO {
  memory_id: string;
  memory_type: string;
  memory_key: string;
  content: Record<string, unknown>;
  scope: Record<string, unknown>;
  unit: string;
  source: string;
  confirmed_status: string;
  version: number;
  status: string;
  updated_at: string;
}

export interface SessionDTO {
  session_id: string;
  title: string;
  source_id: string;
  data_version: string;
  data_sources: Array<{ source_id: string; data_version: string }>;
  status: string;
  last_question: string;
  created_at: string;
  updated_at: string;
}

export interface MessageDTO {
  message_id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  run_id: string | null;
  report: QualityReport | null;
  data_sources?: Array<{ source_id: string; name: string; data_version: string; record_count: number }>;
}

export interface QualityTrendPoint {
  period: string;
  total: number;
  defect_count: number;
  defect_rate_percent: number;
}

export interface QualityParetoItem {
  defect_type: string;
  count: number;
  percent: number;
  cumulative_percent: number;
}

export interface QualityReportCharts {
  defect_trend?: {
    status?: string;
    period_unit?: "day" | "month";
    points?: QualityTrendPoint[];
  };
  defect_pareto?: {
    status?: string;
    total_defects?: number;
    items?: QualityParetoItem[];
  };
}

export interface QualityReport {
  status?: string;
  task?: string;
  task_label?: string;
  question?: string;
  summary?: string;
  explanation?: string;
  explanation_source?: string;
  explanation_citations?: Array<Record<string, unknown>>;
  charts?: QualityReportCharts;
  llm_status?: string;
  baseline?: Record<string, unknown>;
  top_factors?: Array<Record<string, unknown>>;
  tool_result?: Record<string, unknown>;
  filters?: Record<string, unknown>;
  data_scope?: {
    matched_count?: number;
    source_count?: number;
    actual_start_date?: string | null;
    actual_end_date?: string | null;
    datasets?: Array<{ source_id: string; name: string; data_version: string; record_count: number }>;
    source_record_count?: number;
  };
  data_sources?: Array<{ source_id: string; name: string; data_version: string; record_count: number }>;
  comparison_id?: string;
  comparison?: ComparisonDTO;
  evidence_refs?: Array<Record<string, unknown>>;
  trace?: Array<Record<string, unknown>>;
  elapsed_ms?: number;
  missing_inputs?: string[];
  [key: string]: unknown;
}

export interface MessagePageDTO {
  session_id: string;
  offset: number;
  limit: number;
  total: number;
  messages: MessageDTO[];
}

export interface RunDTO {
  run_id: string;
  session_id: string;
  source_id: string;
  source_ids: string[];
  submission_id: string;
  question: string;
  status: string;
  created_at: string;
  updated_at: string;
  report: QualityReport | null;
}

export interface ComparisonChildDTO {
  source_id: string;
  source_name: string;
  session_id: string;
  run_id: string;
  status: string;
  report: QualityReport | null;
}

export interface ComparisonDTO {
  comparison_id: string;
  question: string;
  source_ids: string[];
  parent_session_id?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  children: ComparisonChildDTO[];
}

export interface RunEvent {
  id?: string;
  type: string;
  run_id: string;
  status?: string;
  stage?: string;
  label?: string;
  elapsed_ms?: number | null;
  report?: QualityReport;
  [key: string]: unknown;
}

export interface APIErrorBody {
  error?: { code?: string; message?: string; details?: unknown };
}
