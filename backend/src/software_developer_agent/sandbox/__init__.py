"""Isolated lifecycle management for generated application previews."""

from software_developer_agent.sandbox.preview_manager import (
    PreviewManager,
    PreviewRecord,
    get_preview_manager,
)

__all__ = ["PreviewManager", "PreviewRecord", "get_preview_manager"]
