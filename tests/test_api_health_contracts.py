"""Phase 0: characterize public app contracts that do not need Firebase."""

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_and_root_contracts():
    # Avoid real Firebase/seeder on import lifespan by patching seeder.
    with patch("app.main.DatabaseSeeder") as seeder_cls:
        seeder_cls.return_value.seed_all.return_value = True
        from app.main import app

        client = TestClient(app)
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        root = client.get("/")
        assert root.status_code == 200
        body = root.json()
        assert body["status"] == "success"
        assert body["docs"] == "/docs"
