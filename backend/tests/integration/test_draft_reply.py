import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings

FIXTURE = Path(__file__).parents[2] / "evals" / "fixtures" / "sample_policy.md"
REFUND_QUOTE = "Customers may request a full refund within 14 days of purchase."


def register_owner(client: TestClient, email: str) -> dict[str, str]:
    credentials = {"email": email, "password": "secret123"}
    token = client.post("/auth/register", json=credentials).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_draft_reply_requires_n8n_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "n8n_draft_secret", "workflow-secret")

    response = client.post(
        "/drafts/reply",
        json={"subject": "Refund request", "body": "Can I get a refund?"},
    )

    assert response.status_code == 401


def test_draft_reply_uses_configured_owners_knowledge(client, llm, monkeypatch):
    owner_email = "draft-owner@example.com"
    monkeypatch.setattr(settings, "n8n_draft_secret", "workflow-secret")
    monkeypatch.setattr(settings, "draft_user_email", owner_email)
    owner_headers = register_owner(client, owner_email)
    upload = client.post(
        "/documents/upload",
        headers=owner_headers,
        files={"file": ("sample_policy.md", FIXTURE.read_bytes(), "text/markdown")},
    )
    assert upload.status_code == 200

    def draft_response(system: str, _) -> str:
        chunk_id = re.search(r"\[chunk_id=([^\]]+)\]", system).group(1)
        return json.dumps(
            {
                "answer": "You can request a full refund within 14 days of purchase.",
                "citations": [{"chunk_id": chunk_id, "quote": REFUND_QUOTE}],
            }
        )

    llm.responder = draft_response

    response = client.post(
        "/drafts/reply",
        headers={"X-N8N-Secret": "workflow-secret"},
        json={
            "subject": "Refund request",
            "body": "Can I get a full refund within 14 days?",
            "customer_email": "customer@example.com",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "draft": "You can request a full refund within 14 days of purchase.",
        "citations": [
            {
                "chunk_id": response.json()["citations"][0]["chunk_id"],
                "source": "sample_policy.md",
                "quote": REFUND_QUOTE,
            }
        ],
        "refused": False,
    }
