from io import BytesIO
from pathlib import Path

import pytest
from starlette.datastructures import Headers, UploadFile

from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobRequest, JobState
from software_developer_agent.tools.media_assets import materialize_selected_media_assets
from software_developer_agent.tools.user_media import UserMediaStore, cleanup_user_media


@pytest.mark.asyncio
async def test_uploaded_image_is_bound_materialized_and_cleaned(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        upload_cache_dir=tmp_path / "uploads",
        media_cache_dir=tmp_path / "media",
    )
    store = UserMediaStore(settings)
    body = b"\x89PNG\r\n\x1a\n" + b"user-image"
    upload = UploadFile(
        BytesIO(body),
        filename="Rider Photo.png",
        headers=Headers({"content-type": "image/png"}),
    )

    pending = await store.save_pending(upload)
    assets = store.bind_to_job("job-123", [pending["asset_id"]])
    job = JobState(
        job_id="job-123",
        request=JobRequest(
            prompt="Use my rider photo",
            metadata={"uploaded_assets": assets},
        ),
    )
    web_path = assets[0]["download"]["web_path"]
    project = tmp_path / "project"
    project.mkdir()

    selected = materialize_selected_media_assets(
        job,
        settings,
        project,
        {"frontend/src/App.tsx": f'<img src="{web_path}" alt="Rider" />'},
    )

    assert selected[0]["rights_status"] == "user-provided"
    assert (project / assets[0]["download"]["project_path"]).read_bytes() == body
    cleanup_user_media(job, settings)
    assert not settings.upload_cache_dir.exists()


@pytest.mark.asyncio
async def test_upload_rejects_mismatched_media_signature(tmp_path: Path) -> None:
    settings = Settings(app_env="test", upload_cache_dir=tmp_path / "uploads")
    upload = UploadFile(
        BytesIO(b"not-an-image"),
        filename="fake.png",
        headers=Headers({"content-type": "image/png"}),
    )

    with pytest.raises(ValueError, match="do not match"):
        await UserMediaStore(settings).save_pending(upload)
