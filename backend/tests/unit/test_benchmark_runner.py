from pathlib import Path

from software_developer_agent.benchmarks.runner import (
    _content_digest,
    _expected_path_present,
    _load_cases,
    run_benchmark,
)


def test_offline_benchmark_is_repeatable_and_meets_threshold() -> None:
    report = run_benchmark(execute=False, repeat=2)
    assert report.passed is True
    assert report.repeatable is True
    assert report.average_score >= 12.0
    assert len(report.cases) == len(_load_cases())
    assert all(case.score >= 12.0 for case in report.cases)


def test_benchmark_accepts_supported_backend_manifest_alternative() -> None:
    files = {"backend/requirements.txt": Path("backend/requirements.txt")}

    assert _expected_path_present("backend/pyproject.toml", files)


def test_content_digest_ignores_volatile_validation_report(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (tmp_path / "README.md").write_text("# Stable\n", encoding="utf-8")
    risk_report = artifacts / "risk-report.json"
    risk_report.write_text('{"duration_seconds": 1.2}\n', encoding="utf-8")
    first = _content_digest(tmp_path)

    risk_report.write_text('{"duration_seconds": 9.8}\n', encoding="utf-8")

    assert _content_digest(tmp_path) == first
