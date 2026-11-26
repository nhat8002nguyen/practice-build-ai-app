import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.graph import (
    FALLBACK_ANSWER,
    HITL_PLACEHOLDER,
    MAX_ASSISTANT_STEPS,
    format_order_status,
)
from app.agents.runner import get_checkpointer
from app.rag.generate import REFUSAL_TEXT

FIXTURE = Path(__file__).parents[2] / "evals" / "fixtures" / "sample_policy.md"
REFUND_QUOTE = "Customers may request a full refund within 14 days of purchase."
AGENT_PROMPT_START = "You are a support agent"


def tool(name: str, **args) -> str:
    return json.dumps({"action": "tool", "tool": name, "args": args})


def final(answer: str) -> str:
    return json.dumps({"action": "final", "answer": answer})


@pytest.fixture
def script(llm):
    """Scripts the agent model node. Calls from the RAG answer step get a cited reply."""

    def install(*steps: str) -> None:
        queue = list(steps)

        def respond(system: str, messages) -> str:
            if system.startswith(AGENT_PROMPT_START):
                return queue.pop(0) if queue else final("done")
            chunk_id = system.split("[chunk_id=", 1)[1].split("]", 1)[0]
            return json.dumps(
                {
                    "answer": "Refunds are available within 14 days of purchase.",
                    "citations": [{"chunk_id": chunk_id, "quote": REFUND_QUOTE}],
                }
            )

        llm.responder = respond

    return install


def new_session(client: TestClient, headers) -> str:
    return client.post("/chat/sessions", headers=headers).json()["id"]


def ask_agent(client: TestClient, headers, session_id: str, content: str):
    return client.post(
        f"/chat/sessions/{session_id}/messages",
        headers=headers,
        json={"content": content, "mode": "agent"},
    )


def resolve(client: TestClient, headers, ticket_id: str, decision: str, note=None):
    return client.post(
        f"/tickets/{ticket_id}/resolve",
        headers=headers,
        json={"decision": decision, "note": note},
    )


def stored_messages(db_path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            "SELECT role, content FROM messages ORDER BY created_at, rowid"
        ).fetchall()


def paused_run_state(db_path: Path) -> dict:
    with sqlite3.connect(db_path) as connection:
        (thread_id,) = connection.execute("SELECT thread_id FROM tickets").fetchone()
    checkpoint = get_checkpointer().get_tuple({"configurable": {"thread_id": thread_id}})
    return checkpoint.checkpoint["channel_values"]


def escalate_missing_order(script, monkeypatch) -> None:
    monkeypatch.setenv("ORDER_STUB_MODE", "miss")
    script(
        tool("lookup_order", order_id="ORD-404"),
        tool("create_ticket", reason="Order ORD-404 not found", priority="high"),
        final("I could not find that order, a human will follow up."),
    )


def test_agent_escalates_when_order_missing(client, register_user, script, monkeypatch, llm):
    escalate_missing_order(script, monkeypatch)
    headers = register_user()
    session_id = new_session(client, headers)

    response = ask_agent(client, headers, session_id, "Where is order ORD-404?")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_human"
    assert body["answer"] == HITL_PLACEHOLDER
    assert body["ticket_id"]
    assert '"found": false' in llm.calls[1][1][-1]["content"]

    tickets = client.get("/tickets", headers=headers).json()
    assert [t["id"] for t in tickets] == [body["ticket_id"]]
    assert tickets[0]["status"] == "open"
    assert tickets[0]["priority"] == "high"
    assert tickets[0]["session_id"] == session_id
    assert tickets[0]["subject"] == "Order ORD-404 not found"


def test_human_approval_resumes_the_paused_run(
    client, register_user, script, monkeypatch, db_path
):
    escalate_missing_order(script, monkeypatch)
    headers = register_user()
    session_id = new_session(client, headers)
    ticket_id = ask_agent(client, headers, session_id, "Where is order ORD-404?").json()[
        "ticket_id"
    ]

    assert paused_run_state(db_path)["decision"] is None

    response = resolve(client, headers, ticket_id, "approve", "Refund issued.")

    assert response.status_code == 200
    assert paused_run_state(db_path)["decision"] == "approve"
    assert response.json()["status"] == "approved"
    assert response.json()["resolution_note"] == "Refund issued."
    last_role, last_content = stored_messages(db_path)[-1]
    assert last_role == "assistant"
    assert last_content == (
        "A human agent reviewed your request and approved it. Refund issued."
    )
    assert client.get("/tickets?status=open", headers=headers).json() == []


def test_human_rejection_is_reported_to_the_customer(
    client, register_user, script, monkeypatch, db_path
):
    escalate_missing_order(script, monkeypatch)
    headers = register_user()
    session_id = new_session(client, headers)
    ticket_id = ask_agent(client, headers, session_id, "Where is order ORD-404?").json()[
        "ticket_id"
    ]

    response = resolve(client, headers, ticket_id, "reject")

    assert response.json()["status"] == "rejected"
    assert "could not approve" in stored_messages(db_path)[-1][1]


def test_resolve_fails_and_keeps_ticket_open_when_paused_run_is_lost(
    client, register_user, script, monkeypatch, db_path
):
    escalate_missing_order(script, monkeypatch)
    headers = register_user()
    session_id = new_session(client, headers)
    ticket_id = ask_agent(client, headers, session_id, "Where is order ORD-404?").json()[
        "ticket_id"
    ]
    messages_before = stored_messages(db_path)
    get_checkpointer.cache_clear()

    response = resolve(client, headers, ticket_id, "approve", "ok")

    assert response.status_code == 409
    assert "can no longer be resumed" in response.json()["detail"]
    ticket = client.get("/tickets", headers=headers).json()[0]
    assert ticket["status"] == "open"
    assert ticket["resolution_note"] is None
    assert stored_messages(db_path) == messages_before


def test_ticket_cannot_be_resolved_twice(client, register_user, script, monkeypatch):
    escalate_missing_order(script, monkeypatch)
    headers = register_user()
    session_id = new_session(client, headers)
    ticket_id = ask_agent(client, headers, session_id, "Where is order ORD-404?").json()[
        "ticket_id"
    ]
    resolve(client, headers, ticket_id, "approve")

    assert resolve(client, headers, ticket_id, "reject").status_code == 409


def test_existing_order_is_answered_without_a_ticket(
    client, register_user, script, monkeypatch
):
    monkeypatch.setenv("ORDER_STUB_MODE", "hit")
    script(
        tool("lookup_order", order_id="ORD-1"),
        final("Order ORD-1 has shipped."),
    )
    headers = register_user()

    body = ask_agent(client, headers, new_session(client, headers), "Order ORD-1?").json()

    assert body["status"] == "answered"
    assert body["ticket_id"] is None
    assert body["refused"] is False
    assert body["citations"] == []
    assert body["answer"] == format_order_status(
        {
            "found": True,
            "order_id": "ORD-1",
            "status": "shipped",
            "carrier": "DemoExpress",
            "eta_days": 3,
        }
    )
    assert client.get("/tickets", headers=headers).json() == []


def test_search_knowledge_returns_grounded_citations(client, register_user, script):
    script(
        tool("search_knowledge", query="Can I get a full refund within 14 days?"),
        final("Yes, refunds are available within 14 days."),
    )
    headers = register_user()
    client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample_policy.md", FIXTURE.read_bytes(), "text/markdown")},
    )

    body = ask_agent(
        client, headers, new_session(client, headers), "Can I get a full refund?"
    ).json()

    assert body["status"] == "answered"
    assert [c["quote"] for c in body["citations"]] == [REFUND_QUOTE]
    assert body["metrics"]["prompt_tokens"] == 360


def test_refused_search_clears_prior_citations(client, register_user, llm):
    agent_steps = [
        tool("search_knowledge", query="Can I get a full refund within 14 days?"),
        tool("search_knowledge", query="What is the refund window again?"),
        final("I still need an answer."),
    ]
    queue = list(agent_steps)
    rag_calls = 0

    def respond(system: str, messages) -> str:
        nonlocal rag_calls
        if system.startswith(AGENT_PROMPT_START):
            return queue.pop(0) if queue else final("done")
        rag_calls += 1
        if rag_calls == 1:
            chunk_id = system.split("[chunk_id=", 1)[1].split("]", 1)[0]
            return json.dumps(
                {
                    "answer": "Refunds are available within 14 days of purchase.",
                    "citations": [{"chunk_id": chunk_id, "quote": REFUND_QUOTE}],
                }
            )
        return json.dumps({"insufficient_evidence": True})

    llm.responder = respond
    headers = register_user()
    client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample_policy.md", FIXTURE.read_bytes(), "text/markdown")},
    )

    body = ask_agent(
        client, headers, new_session(client, headers), "Can I get a full refund?"
    ).json()

    assert body["status"] == "answered"
    assert body["refused"] is True
    assert body["answer"] == REFUSAL_TEXT
    assert body["citations"] == []
    assert rag_calls == 2


def test_tool_errors_are_fed_back_to_the_model(client, register_user, script, llm):
    script(
        tool("create_ticket", reason="help", priority="urgent"),
        tool("nope"),
        final(FALLBACK_ANSWER),
    )
    headers = register_user()

    body = ask_agent(client, headers, new_session(client, headers), "help").json()

    assert body["status"] == "answered"
    assert body["answer"] == FALLBACK_ANSWER
    assert "priority must be one of" in llm.calls[1][1][-1]["content"]
    assert "unknown tool 'nope'" in llm.calls[2][1][-1]["content"]
    assert client.get("/tickets", headers=headers).json() == []


def test_repeated_create_ticket_reuses_the_run_ticket(client, register_user, script):
    script(
        tool("create_ticket", reason="first", priority="low"),
        tool("create_ticket", reason="second", priority="low"),
        final("A human will follow up."),
    )
    headers = register_user()

    ask_agent(client, headers, new_session(client, headers), "help me")

    assert len(client.get("/tickets", headers=headers).json()) == 1


def test_malformed_model_output_falls_back(client, register_user, script):
    script("not json")
    headers = register_user()

    body = ask_agent(client, headers, new_session(client, headers), "hi").json()

    assert body["answer"] == FALLBACK_ANSWER
    assert body["status"] == "answered"
    assert body["refused"] is False


def test_ungrounded_policy_final_is_refused(client, register_user, script):
    script(final("Refunds are available for 90 days."))
    headers = register_user()

    body = ask_agent(
        client, headers, new_session(client, headers), "What is the refund window?"
    ).json()

    assert body["status"] == "answered"
    assert body["refused"] is True
    assert body["answer"] == REFUSAL_TEXT
    assert body["citations"] == []


def test_failed_lookup_does_not_unlock_ungrounded_final(client, register_user, script):
    script(
        tool("lookup_order"),
        final("Refunds are available for 90 days."),
    )
    headers = register_user()

    body = ask_agent(
        client, headers, new_session(client, headers), "What is the refund window?"
    ).json()

    assert body["status"] == "answered"
    assert body["refused"] is True
    assert body["answer"] == REFUSAL_TEXT
    assert body["citations"] == []


def test_successful_lookup_does_not_unlock_ungrounded_final(
    client, register_user, script, monkeypatch
):
    monkeypatch.setenv("ORDER_STUB_MODE", "hit")
    invented = "Refunds are available for 90 days."
    script(
        tool("lookup_order", order_id="ORD-1"),
        final(invented),
    )
    headers = register_user()

    body = ask_agent(
        client, headers, new_session(client, headers), "What is the refund window?"
    ).json()

    assert body["status"] == "answered"
    assert body["answer"] != invented
    assert body["answer"] == format_order_status(
        {
            "found": True,
            "order_id": "ORD-1",
            "status": "shipped",
            "carrier": "DemoExpress",
            "eta_days": 3,
        }
    )
    assert body["citations"] == []


def test_refused_search_does_not_mask_order_status(
    client, register_user, script, monkeypatch
):
    monkeypatch.setenv("ORDER_STUB_MODE", "hit")
    script(
        tool("search_knowledge", query="refund policy"),
        tool("lookup_order", order_id="ORD-1"),
        final("Refunds are available for 90 days."),
    )
    headers = register_user()

    body = ask_agent(
        client, headers, new_session(client, headers), "Where is order ORD-1?"
    ).json()

    assert body["status"] == "answered"
    assert body["refused"] is False
    assert body["answer"] == format_order_status(
        {
            "found": True,
            "order_id": "ORD-1",
            "status": "shipped",
            "carrier": "DemoExpress",
            "eta_days": 3,
        }
    )


def test_hitl_draft_does_not_surface_invented_policy(
    client, register_user, script, monkeypatch
):
    monkeypatch.setenv("ORDER_STUB_MODE", "miss")
    invented = "Refunds are available for 90 days."
    script(
        tool("lookup_order", order_id="ORD-404"),
        tool("create_ticket", reason="Order ORD-404 not found", priority="high"),
        final(invented),
    )
    headers = register_user()

    body = ask_agent(
        client, headers, new_session(client, headers), "Where is order ORD-404?"
    ).json()

    assert body["status"] == "awaiting_human"
    assert body["answer"] == HITL_PLACEHOLDER
    assert body["answer"] != invented
    assert body["refused"] is False


def test_missed_lookup_final_without_ticket_is_grounded(
    client, register_user, script, monkeypatch
):
    monkeypatch.setenv("ORDER_STUB_MODE", "miss")
    invented = "Refunds are available for 90 days."
    script(
        tool("lookup_order", order_id="ORD-404"),
        final(invented),
    )
    headers = register_user()

    body = ask_agent(
        client, headers, new_session(client, headers), "What is the refund window?"
    ).json()

    assert body["status"] == "answered"
    assert body["ticket_id"] is None
    assert body["refused"] is True
    assert body["answer"] == REFUSAL_TEXT
    assert body["citations"] == []


def test_agent_loop_is_bounded(client, register_user, script, llm):
    script(*[tool("lookup_order", order_id="ORD-1")] * 20)
    headers = register_user()

    body = ask_agent(client, headers, new_session(client, headers), "loop").json()

    assert body["answer"] == FALLBACK_ANSWER
    assert len(llm.calls) == MAX_ASSISTANT_STEPS


def test_agent_sees_earlier_turns_of_the_session(client, register_user, script, llm):
    script(
        tool("lookup_order", order_id="ORD-1"),
        final("First reply."),
        tool("lookup_order", order_id="ORD-1"),
        final("Second reply."),
    )
    headers = register_user()
    session_id = new_session(client, headers)

    ask_agent(client, headers, session_id, "one")
    ask_agent(client, headers, session_id, "two")

    roles = [m["role"] for m in llm.calls[2][1]]
    assert roles == ["user", "assistant", "user"]


def test_tickets_are_private_to_their_owner(client, register_user, script, monkeypatch):
    escalate_missing_order(script, monkeypatch)
    owner, other = register_user(), register_user()
    ticket_id = ask_agent(
        client, owner, new_session(client, owner), "Where is order ORD-404?"
    ).json()["ticket_id"]

    assert client.get("/tickets", headers=other).json() == []
    assert resolve(client, other, ticket_id, "approve").status_code == 404
    assert client.get("/tickets", headers=owner).json()[0]["status"] == "open"


def test_ticket_endpoints_validate_input_and_require_auth(client, register_user):
    headers = register_user()

    assert client.get("/tickets").status_code == 401
    assert (
        client.post("/tickets/00000000-0000-0000-0000-000000000000/resolve").status_code
        == 401
    )
    assert (
        client.post(
            "/tickets/00000000-0000-0000-0000-000000000000/resolve",
            headers=headers,
            json={"decision": "maybe"},
        ).status_code
        == 422
    )
    assert (
        resolve(client, headers, "00000000-0000-0000-0000-000000000000", "approve").status_code
        == 404
    )


def test_agent_mode_without_configured_llm_fails_cleanly(
    client, register_user, monkeypatch
):
    from app.api.deps_rag import get_llm
    from app.core.config import settings

    client.app.dependency_overrides.pop(get_llm)
    get_llm.cache_clear()
    monkeypatch.setattr(settings, "openai_api_key", "")
    headers = register_user()

    response = ask_agent(client, headers, new_session(client, headers), "hi")

    assert response.status_code == 502


def test_only_one_concurrent_resolver_claims_an_open_ticket(db_path):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api.tickets import _claim_ticket
    from app.core.db import Base
    from app.models.entities import Ticket, User
    from app.schemas.tickets import ResolveRequest

    async def scenario() -> list[bool]:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as setup:
            user = User(email="race@example.com", password_hash="x")
            setup.add(user)
            await setup.commit()
            ticket = Ticket(user_id=user.id, subject="s")
            setup.add(ticket)
            await setup.commit()
        async with factory() as first, factory() as second:
            # Both sessions read the ticket as open before either resolves it.
            await first.get(Ticket, ticket.id)
            await second.get(Ticket, ticket.id)
            outcomes = [
                await _claim_ticket(first, ticket.id, ResolveRequest(decision="approve")),
                await _claim_ticket(second, ticket.id, ResolveRequest(decision="reject")),
            ]
        await engine.dispose()
        return outcomes

    assert asyncio.run(scenario()) == [True, False]
