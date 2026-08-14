from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient


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

    def cancel_question(self, access_token: str, message_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/chat/messages/{message_id}/cancel", json_payload=payload, access_token=access_token).data

    def reassign_question(self, access_token: str, message_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch(f"/api/v1/chat/messages/{message_id}/assignee", json_payload=payload, access_token=access_token).data

    def get_proposal_activities(self, access_token: str, proposal_id: int, **filters) -> Any:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = f"/api/v1/proposals/{proposal_id}/activities" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data
