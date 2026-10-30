import type {
  APIErrorBody,
  ComparisonDTO,
  MemoryDTO,
  MessagePageDTO,
  RunDTO,
  RunEvent,
  SessionDTO,
  SpeechStatusDTO,
  SpeechTranscriptionDTO,
  SourceDTO,
  SourceDimensionsDTO,
  SourcePreviewFilter,
  SourcePreviewDTO,
} from "./types";

export class APIError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "APIError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new APIError("无法连接本地 Agent 服务，请检查服务是否启动。", 0);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as APIErrorBody;
    throw new APIError(body.error?.message ?? `请求失败（${response.status}）`, response.status, body.error?.code);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; model_provider: string; model_name: string }>("/api/v1/health"),
  modelHealth: () => request<{ status: "available" | "model_missing" | "unavailable"; model_name: string; message: string }>("/api/v1/health/model"),
  speechStatus: () => request<SpeechStatusDTO>("/api/v1/speech/status"),
  transcribeSpeech: (audio: Blob, signal?: AbortSignal) => {
    const extension = audio.type.includes("ogg") ? ".ogg" : audio.type.includes("wav") ? ".wav" : audio.type.includes("mp4") ? ".m4a" : ".webm";
    const file = new File([audio], `recording${extension}`, { type: audio.type || "audio/webm" });
    const body = new FormData();
    body.append("file", file);
    return request<SpeechTranscriptionDTO>("/api/v1/speech/transcribe", { method: "POST", body, signal });
  },
  listSources: () => request<SourceDTO[]>("/api/v1/sources"),
  previewSource: (sourceId: string, offset = 0, limit = 100, search = "", filters: SourcePreviewFilter[] = []) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (search.trim()) params.set("search", search.trim());
    if (filters.length) params.set("filters", JSON.stringify(filters));
    return request<SourcePreviewDTO>(`/api/v1/sources/${encodeURIComponent(sourceId)}/preview?${params.toString()}`);
  },
  sourceDimensions: (sourceId: string) =>
    request<SourceDimensionsDTO>(`/api/v1/sources/${encodeURIComponent(sourceId)}/dimensions`),
  uploadSource: async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<SourceDTO>("/api/v1/sources/upload", { method: "POST", body });
  },
  listSessions: (sourceId?: string) =>
    request<SessionDTO[]>(sourceId ? `/api/v1/sessions?source_id=${encodeURIComponent(sourceId)}` : "/api/v1/sessions"),
  getSession: (sessionId: string) => request<SessionDTO>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`),
  listComparisons: () => request<ComparisonDTO[]>("/api/v1/comparisons?limit=30"),
  comparison: (comparisonId: string) => request<ComparisonDTO>(`/api/v1/comparisons/${encodeURIComponent(comparisonId)}`),
  startComparison: (payload: { comparisonId: string; question: string; sourceIds: string[]; parentSessionId?: string; sessionIds?: Record<string, string> }) =>
    request<ComparisonDTO>("/api/v1/comparisons", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comparison_id: payload.comparisonId, question: payload.question, source_ids: payload.sourceIds, parent_session_id: payload.parentSessionId ?? null, session_ids: payload.sessionIds ?? {}, use_decision_loop: true }),
    }),
  cancelComparison: (comparisonId: string) => request<ComparisonDTO>(`/api/v1/comparisons/${encodeURIComponent(comparisonId)}/cancel`, { method: "POST" }),
  createSession: (sourceId: string, title = "新会话") =>
    request<SessionDTO>("/api/v1/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_id: sourceId, title }),
    }),
  setSessionSources: (sessionId: string, sourceIds: string[]) =>
    request<SessionDTO>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/sources`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_ids: sourceIds }),
    }),
  renameSession: (sessionId: string, title: string) =>
    request<SessionDTO>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  deleteSession: (sessionId: string) =>
    request<{ deleted: boolean }>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
  messages: (sessionId: string) =>
    request<MessagePageDTO>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/messages?limit=200`),
  sessionRuns: (sessionId: string) =>
    request<RunDTO[]>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/runs?limit=10`),
  startRun: (sessionId: string, question: string, submissionId: string, sourceIds: string[] = []) =>
    request<RunDTO>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, submission_id: submissionId, source_ids: sourceIds, use_decision_loop: true }),
    }),
  run: (runId: string) => request<RunDTO>(`/api/v1/runs/${encodeURIComponent(runId)}`),
  cancelRun: (runId: string) =>
    request<{ run_id: string; status: string }>(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }),
  artifacts: (runId: string) => request<{ run_id: string; status: string; artifacts: Array<{ kind: string; label: string; data: unknown }> }>(`/api/v1/runs/${encodeURIComponent(runId)}/artifacts`),
  memories: (includeHistory = false) => request<MemoryDTO[]>(`/api/v1/memories?include_history=${includeHistory}`),
  saveMemory: (payload: { memory_type: string; memory_key: string; content: Record<string, unknown>; scope?: Record<string, unknown>; unit?: string; source: string; confirmed: boolean }) =>
    request<MemoryDTO>("/api/v1/memories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteMemory: (memoryId: string) => request<{ deleted: boolean }>(`/api/v1/memories/${encodeURIComponent(memoryId)}`, { method: "DELETE" }),
  subscribe: (runId: string, onEvent: (event: RunEvent, eventId: string) => void, onError?: () => void, onOpen?: () => void) => {
    const source = new EventSource(`/api/v1/runs/${encodeURIComponent(runId)}/events`);
    source.onopen = () => onOpen?.();
    source.onmessage = (message) => {
      try {
        onEvent(JSON.parse(message.data) as RunEvent, message.lastEventId);
      } catch {
        // Ignore a malformed event and let the stream deliver its next sequence.
      }
    };
    source.onerror = () => onError?.();
    return source;
  },
};
