import json
import re
import sqlite3
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.rag.generate import REFUSAL_TEXT
from app.services.llm import LLMError

FIXTURE = Path(__file__).parents[2] / "evals" / "fixtures" / "sample_policy.md"
REFUND_QUOTE = "Customers may request a full refund within 14 days of purchase."
REFUND_QUESTION = "Can I get a full refund within 14 days?"


def register(client: TestClient) -> dict[str, str]:
    credentials = {"email": f"ops-{uuid.uuid4().hex}@example.com", "password": "secret123"}
    token = client.post("/auth/register", json=credentials).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def upload_policy(client: TestClient, headers) -> None:
    response = client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample_policy.md", FIXTURE.read_bytes(), "text/markdown")},
    )
    assert response.status_code == 200


def new_session(client: TestClient, headers) -> str:
    return client.post("/chat/sessions", headers=headers).json()["id"]


def ask(client: TestClient, headers, session_id: str, content: str, **extra):
    return client.post(
        f"/chat/sessions/{session_id}/messages",
        headers=headers,
        json={"content": content, **extra},
    )


def top_chunk_id(system: str) -> str:
    return re.search(r"\[chunk_id=([^\]]+)\]", system).group(1)


def cite_refund(system: str, messages) -> str:
    return json.dumps(
        {
            "answer": "Yes, refunds are available within 14 days of purchase.",
            "citations": [{"chunk_id": top_chunk_id(system), "quote": REFUND_QUOTE}],
        }
    )


def test_answer_is_cited_from_ingested_document(client, llm):
    llm.responder = cite_refund
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    response = ask(client, headers, session_id, REFUND_QUESTION)

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert "14 days" in body["answer"]
    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert citation["source"] == "sample_policy.md"
    assert citation["quote"] == REFUND_QUOTE
    assert citation["chunk_id"] in llm.calls[0][0]
    assert body["metrics"]["prompt_tokens"] == 120
    assert body["metrics"]["completion_tokens"] == 30
    assert body["metrics"]["latency_ms"] >= 0


def test_off_topic_question_is_refused_without_calling_the_model(client, llm):
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    response = ask(client, headers, session_id, "Who won the football world cup?")

    body = response.json()
    assert body["refused"] is True
    assert body["answer"] == REFUSAL_TEXT
    assert body["citations"] == []
    assert llm.calls == []


def test_empty_knowledge_base_is_refused(client, llm):
    headers = register(client)
    session_id = new_session(client, headers)

    body = ask(client, headers, session_id, REFUND_QUESTION).json()

    assert body["refused"] is True
    assert body["citations"] == []
    assert llm.calls == []


def test_model_insufficient_evidence_is_refused(client, llm):
    llm.responder = lambda *_: '{"insufficient_evidence": true}'
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    body = ask(client, headers, session_id, REFUND_QUESTION).json()

    assert body["refused"] is True
    assert body["answer"] == REFUSAL_TEXT
    assert len(llm.calls) == 1


def test_answer_with_fabricated_citation_is_refused(client, llm):
    llm.responder = lambda system, _: json.dumps(
        {
            "answer": "Refunds last 90 days.",
            "citations": [{"chunk_id": str(uuid.uuid4()), "quote": "Refunds last 90 days."}],
        }
    )
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    body = ask(client, headers, session_id, REFUND_QUESTION).json()

    assert body["refused"] is True
    assert body["citations"] == []


def test_citation_with_misquoted_text_is_dropped(client, llm):
    llm.responder = lambda system, _: json.dumps(
        {
            "answer": "Refunds last 90 days.",
            "citations": [
                {"chunk_id": top_chunk_id(system), "quote": "Refunds last 90 days."}
            ],
        }
    )
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    assert ask(client, headers, session_id, REFUND_QUESTION).json()["refused"] is True


def test_malformed_model_output_is_refused(client, llm):
    llm.responder = lambda *_: "not json at all"
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    assert ask(client, headers, session_id, REFUND_QUESTION).json()["refused"] is True


def test_llm_failure_returns_502_and_stores_no_messages(client, llm, db_path):
    def failing(*_):
        raise LLMError("down")

    llm.responder = failing
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    response = ask(client, headers, session_id, REFUND_QUESTION)

    assert response.status_code == 502
    assert sql(db_path, "SELECT COUNT(*) FROM messages") == [(0,)]


def test_follow_up_receives_previous_turns_as_history(client, llm):
    llm.responder = cite_refund
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    first = ask(client, headers, session_id, REFUND_QUESTION).json()
    ask(client, headers, session_id, "Do refunds really apply within 14 days?")

    _, messages = llm.calls[1]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == REFUND_QUESTION
    assert messages[1]["content"] == first["answer"]
    assert messages[2]["content"] == "Do refunds really apply within 14 days?"


def test_history_is_limited_to_recent_turns(client, llm, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "chat_history_turns", 1)
    llm.responder = cite_refund
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    for _ in range(3):
        ask(client, headers, session_id, REFUND_QUESTION)

    assert len(llm.calls[2][1]) == 3


def test_history_is_not_shared_between_sessions(client, llm):
    llm.responder = cite_refund
    headers = register(client)
    upload_policy(client, headers)
    ask(client, headers, new_session(client, headers), REFUND_QUESTION)

    ask(client, headers, new_session(client, headers), REFUND_QUESTION)

    assert len(llm.calls[1][1]) == 1


def test_chat_requires_auth(client):
    assert client.post("/chat/sessions").status_code == 401


def test_session_is_private_to_its_owner(client):
    owner = register(client)
    other = register(client)
    session_id = new_session(client, owner)

    assert ask(client, other, session_id, "hi").status_code == 404


def test_other_users_documents_are_never_retrieved(client, llm):
    upload_policy(client, register(client))
    headers = register(client)
    session_id = new_session(client, headers)

    body = ask(client, headers, session_id, REFUND_QUESTION).json()

    assert body["refused"] is True
    assert llm.calls == []


def test_unknown_mode_is_rejected(client):
    headers = register(client)
    session_id = new_session(client, headers)

    assert ask(client, headers, session_id, "hi", mode="other").status_code == 422


def sql(db_path: Path, statement: str) -> list[tuple]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(statement).fetchall()


def test_vectors_of_non_ready_documents_are_dropped(client, llm, db_path):
    llm.responder = cite_refund
    headers = register(client)
    upload_policy(client, headers)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE documents SET status = 'failed'")
    session_id = new_session(client, headers)

    body = ask(client, headers, session_id, REFUND_QUESTION).json()

    assert body["refused"] is True
    assert llm.calls == []


def test_vectors_without_chunk_rows_are_dropped(client, llm, db_path):
    llm.responder = cite_refund
    headers = register(client)
    upload_policy(client, headers)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM chunk_records")
    session_id = new_session(client, headers)

    body = ask(client, headers, session_id, REFUND_QUESTION).json()

    assert body["refused"] is True
    assert llm.calls == []


def test_refusal_does_not_need_a_configured_llm(client, monkeypatch):
    from app.api.deps_rag import get_llm
    from app.core.config import settings

    app_overrides = client.app.dependency_overrides
    app_overrides.pop(get_llm)
    get_llm.cache_clear()
    monkeypatch.setattr(settings, "openai_api_key", "")
    headers = register(client)
    session_id = new_session(client, headers)

    response = ask(client, headers, session_id, REFUND_QUESTION)

    assert response.status_code == 200
    assert response.json()["refused"] is True
    assert ask(client, headers, session_id, "hi", mode="agent").status_code == 502


def test_missing_llm_key_fails_cleanly_only_when_the_model_is_needed(client, monkeypatch):
    from app.api.deps_rag import get_llm
    from app.core.config import settings

    client.app.dependency_overrides.pop(get_llm)
    get_llm.cache_clear()
    monkeypatch.setattr(settings, "openai_api_key", "")
    headers = register(client)
    upload_policy(client, headers)
    session_id = new_session(client, headers)

    response = ask(client, headers, session_id, REFUND_QUESTION)

    assert response.status_code == 502
