from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ProjectSpec:
    """Normalized, serializable description of the requested software project."""

    capability_id: str
    application_type: str
    frontend_framework: str | None = None
    backend_framework: str | None = None
    primary_languages: list[str] = field(default_factory=list)
    runtime_versions: dict[str, str] = field(default_factory=dict)
    package_managers: dict[str, str] = field(default_factory=dict)
    ports: dict[str, int] = field(default_factory=dict)
    adapter_ids: list[str] = field(default_factory=list)
    requested_features: list[str] = field(default_factory=list)
    excluded_features: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    explicitly_selected: bool = False
    confidence: float = 1.0
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProjectSpec:
        return cls(
            capability_id=str(payload.get("capability_id", "react-fastapi")),
            application_type=str(payload.get("application_type", "web_application")),
            frontend_framework=_optional_string(payload.get("frontend_framework")),
            backend_framework=_optional_string(payload.get("backend_framework")),
            primary_languages=[str(item) for item in payload.get("primary_languages", [])],
            runtime_versions={
                str(key): str(value)
                for key, value in dict(payload.get("runtime_versions", {})).items()
            },
            package_managers={
                str(key): str(value)
                for key, value in dict(payload.get("package_managers", {})).items()
            },
            ports={str(key): int(value) for key, value in dict(payload.get("ports", {})).items()},
            adapter_ids=[str(item) for item in payload.get("adapter_ids", [])],
            requested_features=[str(item) for item in payload.get("requested_features", [])],
            excluded_features=[str(item) for item in payload.get("excluded_features", [])],
            acceptance_criteria=[str(item) for item in payload.get("acceptance_criteria", [])],
            explicitly_selected=bool(payload.get("explicitly_selected", False)),
            confidence=float(payload.get("confidence", 1.0)),
            schema_version=int(payload.get("schema_version", 1)),
        )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
