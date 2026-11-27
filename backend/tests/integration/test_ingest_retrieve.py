import asyncio
import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.store import QdrantStore

FIXTURE = Path(__file__).parents[2] / "evals" / "fixtures" / "sample_policy.md"


def register(client: TestClient) -> dict[str, str]:
    credentials = {"email": f"ops-{uuid.uuid4().hex}@example.com", "password": "secret123"}
    token = client.post("/auth/register", json=credentials).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def user_id_of(headers: dict[str, str]) -> uuid.UUID:
    token = headers["Authorization"].split()[1]
    return uuid.UUID(jwt.get_unverified_claims(token)["sub"])


def upload_policy(client: TestClient, headers, strategy: str | None = None):
    params = {"strategy": strategy} if strategy else {}
    return client.post(
        "/documents/upload",
        headers=headers,
        params=params,
        files={"file": ("sample_policy.md", FIXTURE.read_bytes(), "text/markdown")},
    )


def test_upload_requires_auth(client):
    response = client.post(
        "/documents/upload", files={"file": ("a.md", b"# A\ntext", "text/markdown")}
    )

    assert response.status_code == 401


def test_ingest_then_retrieve_refund_chunk_with_parent_child_default(
    client, store, embedder
):
    headers = register(client)

    response = upload_policy(client, headers)

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "parent_child"
    assert body["chunk_count"] > 0

    chunks = client.get(
        "/admin/chunks", headers=headers, params={"document_id": body["id"]}
    ).json()
    assert len(chunks) == body["chunk_count"]
    assert all(c["strategy"] == "parent_child" and c["parent_text"] for c in chunks)
    assert all(c["qdrant_point_id"] for c in chunks)

    user_id = user_id_of(headers)
    query = asyncio.run(embedder.embed_query("full refund within 14 days"))
    hits = asyncio.run(store.search(query, user_id, limit=3))

    assert hits[0].payload["section"] == "Refunds"
    assert "14 days" in hits[0].payload["parent_text"]
    assert hits[0].payload["document_id"] == body["id"]


@pytest.mark.parametrize("strategy", ["fixed", "heading"])
def test_upload_honours_strategy_override(client, strategy):
    headers = register(client)

    body = upload_policy(client, headers, strategy).json()
    chunks = client.get(
        "/admin/chunks", headers=headers, params={"document_id": body["id"]}
    ).json()

    assert body["strategy"] == strategy
    assert {c["strategy"] for c in chunks} == {strategy}


def test_unknown_strategy_is_rejected(client):
    headers = register(client)

    assert upload_policy(client, headers, "semantic").status_code == 422


def test_unsupported_file_type_is_rejected(client):
    headers = register(client)

    response = client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("data.exe", b"x", "application/octet-stream")},
    )

    assert response.status_code == 415


def test_empty_document_is_rejected(client):
    headers = register(client)

    response = client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("empty.md", b"  \n", "text/markdown")},
    )

    assert response.status_code == 422


def test_chunks_are_private_to_document_owner(client):
    owner = register(client)
    other = register(client)
    document_id = upload_policy(client, owner).json()["id"]

    response = client.get(
        "/admin/chunks", headers=other, params={"document_id": document_id}
    )

    assert response.status_code == 404


def test_search_is_scoped_to_owner(client, store, embedder):
    owner = register(client)
    other = register(client)
    upload_policy(client, owner)
    query = asyncio.run(embedder.embed_query("refund"))

    hits = asyncio.run(store.search(query, user_id_of(other)))

    assert hits == []


def test_crawl_rejects_private_address(client):
    headers = register(client)

    response = client.post(
        "/documents/crawl", headers=headers, json={"url": "http://127.0.0.1:6333/"}
    )

    assert response.status_code == 422
    assert "non-public" in response.json()["detail"]


def test_corrupt_pdf_is_rejected(client):
    headers = register(client)

    response = client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("bad.pdf", b"not a pdf", "application/pdf")},
    )

    assert response.status_code == 422


def document_statuses(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as connection:
        return [row[0] for row in connection.execute("SELECT status FROM documents")]


def chunk_row_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM chunk_records").fetchone()[0]


def point_count(store: QdrantStore) -> int:
    return asyncio.run(store._client.count("knowledge_chunks")).count


def test_document_is_ready_in_database_before_vectors_are_written(
    client, store, db_path, monkeypatch
):
    headers = register(client)
    original_upsert = store.upsert
    observed = []

    async def spying_upsert(points):
        observed.append((document_statuses(db_path), chunk_row_count(db_path)))
        await original_upsert(points)

    monkeypatch.setattr(store, "upsert", spying_upsert)

    response = upload_policy(client, headers)

    assert response.status_code == 200
    statuses, rows = observed[0]
    assert statuses == ["ready"]
    assert rows == response.json()["chunk_count"]


def test_failed_vector_upsert_cleans_up_rows_and_points(
    client, store, db_path, monkeypatch
):
    headers = register(client)
    original_upsert = store.upsert

    async def partial_upsert(points):
        await original_upsert(points[:1])
        raise ConnectionError("qdrant down")

    monkeypatch.setattr(store, "upsert", partial_upsert)

    response = upload_policy(client, headers)

    assert response.status_code == 503
    assert document_statuses(db_path) == ["failed"]
    assert chunk_row_count(db_path) == 0
    assert point_count(store) == 0


def test_cleanup_failure_keeps_rows_for_retry_and_marks_document_failed(
    client, store, db_path, monkeypatch
):
    headers = register(client)
    original_upsert = store.upsert

    async def partial_upsert(points):
        await original_upsert(points[:1])
        raise ConnectionError("qdrant down")

    async def failing_delete(point_ids):
        raise ConnectionError("qdrant still down")

    monkeypatch.setattr(store, "upsert", partial_upsert)
    monkeypatch.setattr(store, "delete", failing_delete)

    response = upload_policy(client, headers)

    assert response.status_code == 503
    assert document_statuses(db_path) == ["failed"]
    assert chunk_row_count(db_path) > 0


def test_status_commit_failure_never_writes_vectors(
    client, store, db_path, monkeypatch
):
    headers = register(client)
    commits = []
    original_commit = AsyncSession.commit

    async def commit_failing_on_ready_update(self):
        commits.append(1)
        if len(commits) == 2:
            raise ConnectionError("postgres down")
        await original_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", commit_failing_on_ready_update)

    response = upload_policy(client, headers)

    assert response.status_code == 503
    assert document_statuses(db_path) == ["failed"]
    assert chunk_row_count(db_path) == 0
    assert asyncio.run(store._client.collection_exists("knowledge_chunks")) is False
