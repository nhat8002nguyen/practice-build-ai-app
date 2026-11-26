from app.core.config import settings


def auth_headers(client, email: str) -> dict[str, str]:
    token = client.post(
        "/auth/register", json={"email": email, "password": "secret123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def ask(client, headers, session_id: str):
    return client.post(
        f"/chat/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "Can I get a refund?"},
    )


def test_chat_messages_are_rate_limited_per_user(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_chat_burst", 2)
    monkeypatch.setattr(settings, "rate_limit_chat_per_minute", 1)
    alice = auth_headers(client, "alice@example.com")
    bob = auth_headers(client, "bob@example.com")
    alice_session = client.post("/chat/sessions", headers=alice).json()["id"]
    bob_session = client.post("/chat/sessions", headers=bob).json()["id"]

    assert ask(client, alice, alice_session).status_code == 200
    assert ask(client, alice, alice_session).status_code == 200
    limited = ask(client, alice, alice_session)

    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert ask(client, bob, bob_session).status_code == 200


def test_draft_replies_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "n8n_draft_secret", "workflow-secret")
    monkeypatch.setattr(settings, "draft_user_email", "draft-owner@example.com")
    monkeypatch.setattr(settings, "rate_limit_drafts_burst", 1)
    monkeypatch.setattr(settings, "rate_limit_drafts_per_minute", 1)
    auth_headers(client, "draft-owner@example.com")
    request = {"subject": "Refund request", "body": "Can I get a refund?"}
    secret = {"X-N8N-Secret": "workflow-secret"}

    assert client.post("/drafts/reply", json=request, headers=secret).status_code == 200
    assert client.post("/drafts/reply", json=request, headers=secret).status_code == 429


def test_unauthenticated_draft_calls_do_not_consume_tokens(client, monkeypatch):
    monkeypatch.setattr(settings, "n8n_draft_secret", "workflow-secret")
    monkeypatch.setattr(settings, "rate_limit_drafts_burst", 1)

    for _ in range(3):
        assert client.post(
            "/drafts/reply", json={"subject": "s", "body": "b"}
        ).status_code == 401
