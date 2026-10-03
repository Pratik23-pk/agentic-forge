from pathlib import Path

import httpx

from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import (
    JobRequest,
    JobState,
    JobTask,
    TaskStatus,
    WorkerKind,
    WorkerResult,
)
from software_developer_agent.tools.media_assets import (
    MediaAssetPipeline,
    cleanup_media_cache,
    materialize_selected_media_assets,
)
from software_developer_agent.tools.policy import ToolPolicy
from software_developer_agent.tools.types import ToolResult


class FakeMediaSearch:
    def __init__(
        self,
        *,
        images: list[dict[str, str]] | None = None,
        videos: list[dict[str, str]] | None = None,
    ) -> None:
        self.images = images or []
        self.videos = videos or []

    def search_images(self, query: str) -> ToolResult:
        return ToolResult(
            "serper_image_search",
            "succeeded",
            query,
            metadata={
                "candidates": self.images,
                "urls": [item["source_url"] for item in self.images],
                "licensing_note": "Use only when permitted.",
            },
        )

    def search_videos(self, query: str) -> ToolResult:
        return ToolResult(
            "serper_video_search",
            "succeeded",
            query,
            metadata={
                "candidates": self.videos,
                "urls": [item["source_url"] for item in self.videos],
                "licensing_note": "Use only when permitted.",
            },
        )


def test_image_download_is_materialized_then_temporary_cache_is_removed(tmp_path: Path) -> None:
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"safe-image"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://cdn.example.com/xpulse.png"
        return httpx.Response(
            200,
            headers={"content-type": "image/png", "content-length": str(len(image_bytes))},
            content=image_bytes,
        )

    settings = Settings(
        app_env="test",
        enable_web_search=True,
        enable_media_downloads=True,
        media_cache_dir=tmp_path / "cache",
    )
    pipeline = MediaAssetPipeline(
        settings,
        ToolPolicy(allow_web_search=True),
        FakeMediaSearch(
            images=[
                {
                    "title": "Hero Xpulse 200",
                    "image_url": "https://cdn.example.com/xpulse.png",
                    "source_url": "https://example.com/xpulse",
                    "source": "Example",
                }
            ]
        ),
        transport=httpx.MockTransport(handler),
        public_url_validator=lambda _url: True,
    )

    result = pipeline.acquire(
        "Xpulse 200 official image",
        "image",
        "frontend-task",
        "Include and download an Xpulse 200 image for offline use.",
    )

    assert result.status == "succeeded"
    downloaded = result.metadata["assets"][0]["download"]
    assert Path(downloaded["cache_path"]).read_bytes() == image_bytes
    assert downloaded["web_path"].startswith("/assets/media/")

    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Add an image",
        task_id="frontend-task",
    )
    job = JobState(request=JobRequest(prompt="Add an image"), tasks=[task])
    job.worker_results = [
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="done",
            tool_calls=[result.to_record()],
        )
    ]
    project_root = tmp_path / "project"
    project_root.mkdir()

    selected = materialize_selected_media_assets(
        job,
        settings,
        project_root,
        {"frontend/src/App.tsx": f'<img src="{downloaded["web_path"]}" />'},
    )

    assert selected[0]["strategy"] == "download"
    assert (project_root / downloaded["project_path"]).read_bytes() == image_bytes
    cleanup_media_cache(job, settings)
    assert not settings.media_cache_dir.exists()
    assert (project_root / downloaded["project_path"]).is_file()


def test_video_search_exposes_safe_embed_without_downloading_streaming_page(
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env="test",
        enable_web_search=True,
        enable_media_downloads=True,
        media_cache_dir=tmp_path / "cache",
    )
    pipeline = MediaAssetPipeline(
        settings,
        ToolPolicy(allow_web_search=True),
        FakeMediaSearch(
            videos=[
                {
                    "title": "Gameplay",
                    "source_url": "https://www.youtube.com/watch?v=abcDEF12345",
                    "video_url": "",
                    "poster_url": "https://img.example.com/poster.jpg",
                    "source": "Publisher",
                }
            ]
        ),
        public_url_validator=lambda _url: True,
    )

    result = pipeline.acquire(
        "permitted gameplay video",
        "video",
        "frontend-task",
        "Embed one permitted gameplay video.",
    )

    asset = result.metadata["assets"][0]
    assert result.status == "succeeded"
    assert asset["embed_url"] == "https://www.youtube-nocookie.com/embed/abcDEF12345"
    assert asset["remote_url"] is None
    assert asset["download"] is None


def test_direct_video_can_be_downloaded_when_explicitly_requested(tmp_path: Path) -> None:
    video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"video"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "video/mp4"}, content=video_bytes)

    settings = Settings(
        app_env="test",
        enable_web_search=True,
        enable_media_downloads=True,
        media_cache_dir=tmp_path / "cache",
    )
    pipeline = MediaAssetPipeline(
        settings,
        ToolPolicy(allow_web_search=True),
        FakeMediaSearch(
            videos=[
                {
                    "title": "Permitted demo",
                    "source_url": "https://media.example.com/demo.mp4",
                    "video_url": "https://media.example.com/demo.mp4",
                    "poster_url": "",
                    "source": "Example",
                }
            ]
        ),
        transport=httpx.MockTransport(handler),
        public_url_validator=lambda _url: True,
    )

    result = pipeline.acquire(
        "permitted demo video",
        "video",
        "frontend-task",
        "Download and bundle the permitted demo video.",
    )

    downloaded = result.metadata["assets"][0]["download"]
    assert downloaded["mime_type"] == "video/mp4"
    assert Path(downloaded["cache_path"]).read_bytes() == video_bytes


def test_invalid_media_candidate_is_skipped_before_remote_url_is_exposed(tmp_path: Path) -> None:
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"valid"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("broken.jpg"):
            return httpx.Response(200, headers={"content-type": "text/html"}, text="blocked")
        return httpx.Response(200, headers={"content-type": "image/png"}, content=image_bytes)

    settings = Settings(
        app_env="test",
        enable_web_search=True,
        max_media_assets=1,
        media_cache_dir=tmp_path / "cache",
    )
    pipeline = MediaAssetPipeline(
        settings,
        ToolPolicy(allow_web_search=True),
        FakeMediaSearch(
            images=[
                {
                    "title": "Broken",
                    "image_url": "https://cdn.example.com/broken.jpg",
                    "source_url": "https://example.com/broken",
                    "source": "Example",
                },
                {
                    "title": "Valid",
                    "image_url": "https://cdn.example.com/valid.png",
                    "source_url": "https://example.com/valid",
                    "source": "Example",
                },
            ]
        ),
        transport=httpx.MockTransport(handler),
        public_url_validator=lambda _url: True,
    )

    result = pipeline.acquire(
        "motorcycle image",
        "image",
        "frontend-task",
        "Give me a motorcycle image.",
    )

    assert result.status == "succeeded"
    assert result.metadata["assets"][0]["title"] == "Valid"
    assert result.metadata["assets"][0]["download"] is not None
