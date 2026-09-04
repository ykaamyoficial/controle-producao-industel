from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient


class _ProgressFile:
    def __init__(self, handle, total: int, progress_callback: Callable[[int, int], None] | None = None, cancel_checker: Callable[[], bool] | None = None):
        self._handle = handle
        self._total = max(0, int(total))
        self._progress_callback = progress_callback
        self._cancel_checker = cancel_checker
        self._sent = 0

    def read(self, size: int = -1) -> bytes:
        if self._cancel_checker is not None and self._cancel_checker():
            raise RuntimeError("upload_cancelled")
        chunk = self._handle.read(size)
        if chunk:
            self._sent += len(chunk)
            if self._progress_callback is not None:
                self._progress_callback(self._sent, self._total)
        return chunk


class ChatApiClient:
    def __init__(self, client: DesktopApiClient):
        self.client = client

    def list_conversations(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/chat/conversations" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def list_messages(self, access_token: str, conversation_id: int, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = f"/api/v1/chat/conversations/{conversation_id}/messages" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def list_shared_content(self, access_token: str, conversation_id: int, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = f"/api/v1/chat/conversations/{conversation_id}/shared-content" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def post_message(self, access_token: str, conversation_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/chat/conversations/{conversation_id}/messages", json_payload=payload, access_token=access_token).data

    def answer_question(self, access_token: str, message_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/chat/messages/{message_id}/answer", json_payload=payload, access_token=access_token).data

    def get_proposal_timeline(self, access_token: str, proposal_id: int, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = f"/api/v1/chat/proposals/{proposal_id}/timeline" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def mark_read(self, access_token: str, conversation_id: int, payload: dict[str, Any]) -> None:
        self.client.post(f"/api/v1/chat/conversations/{conversation_id}/read", json_payload=payload, access_token=access_token)

    def unread_summary(self, access_token: str) -> dict[str, Any]:
        return self.client.get("/api/v1/chat/unread-summary", access_token=access_token).data

    def list_mentionable_users(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/chat/mentionable-users" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def list_notifications(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/chat/notifications" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def mark_all_notifications_read(self, access_token: str) -> None:
        self.client.post("/api/v1/chat/notifications/mark-all-read", access_token=access_token)

    def mark_notification_read(self, access_token: str, notification_id: int) -> None:
        self.client.post(f"/api/v1/chat/notifications/{notification_id}/read", access_token=access_token)

    def mark_question_viewed(self, access_token: str, message_id: int) -> dict[str, Any]:
        return self.client.post(f"/api/v1/chat/messages/{message_id}/viewed", access_token=access_token).data

    def upload_attachment(
        self,
        access_token: str,
        message_id: int,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
        client_attachment_id: str | None = None,
    ) -> dict[str, Any]:
        mime = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return self.client.request(
            "POST",
            f"/api/v1/chat/messages/{message_id}/attachments",
            files={"file": (filename, content, mime)},
            data={"client_attachment_id": client_attachment_id} if client_attachment_id else None,
            access_token=access_token,
            retries=0,
        ).data

    def upload_attachment_path(
        self,
        access_token: str,
        message_id: int,
        path: str | Path,
        *,
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_checker: Callable[[], bool] | None = None,
        client_attachment_id: str | None = None,
    ) -> dict[str, Any]:
        file_path = Path(path)
        mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        with file_path.open("rb") as handle:
            wrapped = _ProgressFile(handle, file_path.stat().st_size, progress_callback, cancel_checker)
            return self.client.request(
                "POST",
                f"/api/v1/chat/messages/{message_id}/attachments",
                files={"file": (file_path.name, wrapped, mime)},
                data={"client_attachment_id": client_attachment_id} if client_attachment_id else None,
                access_token=access_token,
                retries=0,
            ).data

    def get_attachment(self, access_token: str, attachment_id: int) -> dict[str, Any]:
        return self.client.get(f"/api/v1/chat/attachments/{attachment_id}", access_token=access_token).data

    def download_attachment(self, access_token: str, attachment_id: int) -> bytes | None:
        return self.client.get_bytes(f"/api/v1/chat/attachments/{attachment_id}/content", access_token=access_token, accept="*/*")

    def download_attachment_to_file(
        self,
        access_token: str,
        attachment_id: int,
        destination,
        *,
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> bool:
        return self.client.download_to_file(
            f"/api/v1/chat/attachments/{attachment_id}/content",
            destination,
            access_token=access_token,
            accept="*/*",
            progress_callback=progress_callback,
            cancel_checker=cancel_checker,
        )

    def delete_attachment(self, access_token: str, attachment_id: int, reason: str) -> dict[str, Any]:
        return self.client.delete(
            f"/api/v1/chat/attachments/{attachment_id}",
            json_payload={"reason": reason},
            access_token=access_token,
        ).data

    def cancel_question(self, access_token: str, message_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/chat/messages/{message_id}/cancel", json_payload=payload, access_token=access_token).data

    def reassign_question(self, access_token: str, message_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch(f"/api/v1/chat/messages/{message_id}/assignee", json_payload=payload, access_token=access_token).data

    def get_proposal_activities(self, access_token: str, proposal_id: int, **filters) -> Any:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = f"/api/v1/proposals/{proposal_id}/activities" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data
