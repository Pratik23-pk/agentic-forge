from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from software_developer_agent.api.routes import media as media_routes
from software_developer_agent.config.settings import Settings
from software_developer_agent.tools.user_media import UserMediaStore


def _client(monkeypatch, tmp_path: Path, *, with_openai: bool = False) -> TestClient:
    settings = Settings(
        app_env="test",
        openai_api_key="test-key" if with_openai else None,
        upload_cache_dir=tmp_path / "uploads",
    )
    store = UserMediaStore(settings)
    monkeypatch.setattr(media_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(media_routes, "get_user_media_store", lambda: store)
    app = FastAPI()
    app.include_router(media_routes.router, prefix="/api")
    return TestClient(app)


def test_upload_and_delete_media(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    body = b"\x89PNG\r\n\x1a\n" + b"prompt-image"

    response = client.post(
        "/api/media/uploads",
        files=[("files", ("reference.png", body, "image/png"))],
    )

    assert response.status_code == 201
    asset = response.json()["assets"][0]
    assert asset["kind"] == "image"
    assert "cache_path" not in asset
    deleted = client.delete(f"/api/media/uploads/{asset['asset_id']}")
    assert deleted.status_code == 204
    assert not (tmp_path / "uploads" / "pending" / asset["asset_id"]).exists()


def test_voice_transcription_returns_editable_text_and_cost(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path, with_openai=True)

    class FakeTranscriptions:
        @staticmethod
        def create(**_kwargs):
            return SimpleNamespace(text="Build a polished rider community website.")

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.audio = SimpleNamespace(transcriptions=FakeTranscriptions())

    monkeypatch.setattr(media_routes, "OpenAI", FakeOpenAI)

    response = client.post(
        "/api/media/transcriptions",
        data={"duration_seconds": "12"},
        files={"audio": ("prompt.webm", b"recording", "audio/webm")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcript"].startswith("Build a polished")
    assert payload["estimated_cost_usd"] > 0
