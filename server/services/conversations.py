"""Adapters from existing LangGraph session storage to stable chat messages."""

from __future__ import annotations

from uuid import UUID, uuid5

from agent.session_store import SessionStore
from server.services.sources import DataSource


class ConversationService:
    def __init__(self, session_store: SessionStore | None = None) -> None:
        self.store = session_store or SessionStore()

    def list_sessions(self, source_id: str | None = None) -> list[dict[str, object]]:
        return self.store.list_sessions(source_id=source_id, limit=200)

    def create_session(self, source: DataSource, title: str = "新会话") -> dict[str, object]:
        return self.store.create_session(source.source_id, source.data_version, title)

    def set_sources(self, session_id: str, sources: list[DataSource]) -> dict[str, object] | None:
        refs = [
            {"source_id": source.source_id, "data_version": source.data_version}
            for source in sources
        ]
        return self.store.set_session_sources(session_id, refs)

    def get_session(self, session_id: str) -> dict[str, object] | None:
        return self.store.get_session(session_id)

    def rename_session(self, session_id: str, title: str) -> dict[str, object] | None:
        return self.store.update_session(session_id, title=title)

    def delete_session(self, session_id: str) -> bool:
        return self.store.delete_session(session_id)

    def messages(self, session_id: str) -> list[dict[str, object]]:
        session = self.store.get_session(session_id)
        if session is None:
            raise KeyError("会话不存在")
        state = self.store.get_state(session_id)
        stored_messages = state.get("messages", [])
        reports = state.get("reports", [])
        if not isinstance(stored_messages, list):
            stored_messages = []
        if not isinstance(reports, list):
            reports = []

        hydrated_reports: list[dict[str, object]] = []
        report_times: list[dict[str, str]] = []
        for compact in reports:
            if not isinstance(compact, dict):
                hydrated_reports.append({})
                continue
            full = None
            times: dict[str, str] = {}
            run_id = compact.get("run_id")
            if run_id:
                try:
                    submission = self.store.get_submission(session_id, str(run_id))
                except ValueError:
                    submission = None
                if isinstance(submission, dict) and isinstance(submission.get("report"), dict):
                    full = submission["report"]
                    times = {
                        "user": str(submission.get("created_at", "")),
                        "assistant": str(submission.get("updated_at", "")),
                    }
            hydrated_reports.append(full or compact)
            report_times.append(times)

        result: list[dict[str, object]] = []
        assistant_index = 0
        user_index = 0
        namespace = UUID(str(session_id))
        for index, item in enumerate(stored_messages):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", ""))
            if role not in {"user", "assistant"}:
                continue
            content = str(item.get("content", ""))
            message_id = str(uuid5(namespace, f"message:{index}:{role}"))
            report = None
            run_id = None
            data_sources: list[dict[str, object]] = []
            created_at = str(session.get("updated_at", ""))
            if role == "assistant":
                if assistant_index < len(hydrated_reports):
                    candidate = hydrated_reports[assistant_index]
                    report = candidate if isinstance(candidate, dict) else None
                    run_id = str(report.get("run_id")) if report and report.get("run_id") else None
                    created_at = report_times[assistant_index].get("assistant") or created_at
                    if report:
                        content = str(report.get("explanation") or report.get("summary") or content)
                assistant_index += 1
            else:
                if user_index < len(report_times):
                    created_at = report_times[user_index].get("user") or created_at
                if user_index < len(hydrated_reports):
                    source_refs = hydrated_reports[user_index].get("data_sources")
                    if isinstance(source_refs, list):
                        data_sources = [item for item in source_refs if isinstance(item, dict)]
                user_index += 1
            result.append(
                {
                    "message_id": message_id,
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "created_at": created_at,
                    "run_id": run_id,
                    "report": report,
                    "data_sources": data_sources,
                }
            )
        return result
