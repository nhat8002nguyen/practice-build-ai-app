import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, validate_production_settings
from app.main import create_app


def test_production_rejects_default_jwt_secret():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_production_settings(Settings(app_env="production"))


def test_production_accepts_custom_jwt_secret():
    validate_production_settings(Settings(app_env="production", jwt_secret="x" * 32))


def test_development_allows_default_jwt_secret():
    validate_production_settings(Settings(app_env="development"))


def test_docs_are_hidden_in_production(monkeypatch):
    monkeypatch.setattr("app.main.settings", Settings(app_env="production"))

    client = TestClient(create_app())

    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
