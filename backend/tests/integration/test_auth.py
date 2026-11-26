import asyncio
import os
import uuid
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import Base, get_db
from app.main import app


def test_register_and_login(tmp_path):
    database_url = os.environ.get(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}",
    )
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    asyncio.run(prepare_database())
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        credentials = {
            "email": f"ops-{uuid.uuid4().hex}@example.com",
            "password": "secret123",
        }
        register_response = client.post("/auth/register", json=credentials)
        login_response = client.post("/auth/login", json=credentials)

        assert register_response.status_code == 200
        assert register_response.json()["token_type"] == "bearer"
        assert login_response.status_code == 200
        assert "access_token" in login_response.json()
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
