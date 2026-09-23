from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from software_developer_agent.models.job_state import (
    GuardrailFinding,
    GuardrailReport,
    JobState,
    JobStatus,
    ReleaseStatus,
)


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    status: ReleaseStatus
    findings: list[dict[str, object]]

    @property
    def can_publish(self) -> bool:
        return self.status == ReleaseStatus.VERIFIED

    @property
    def requires_isolated_preview(self) -> bool:
        return self.status == ReleaseStatus.QUARANTINED


def latest_guardrail_reports(reports: Iterable[GuardrailReport]) -> list[GuardrailReport]:
    latest: dict[str, GuardrailReport] = {}
    for report in reversed(list(reports)):
        latest.setdefault(report.name, report)
    return list(latest.values())


def decide_release(
    job: JobState,
    *,
    validation_passed: bool,
    validation_reason: str | None = None,
) -> ReleaseDecision:
    findings = _guardrail_findings(job.guardrail_reports)
    if any(bool(item.get("blocking")) for item in findings):
        status = ReleaseStatus.QUARANTINED
    elif validation_passed:
        status = ReleaseStatus.VERIFIED
    else:
        status = ReleaseStatus.PROVISIONAL
        if validation_reason:
            findings.append(
                {
                    "source": "validation",
                    "name": "runtime_or_build_validation",
                    "severity": "warning",
                    "message": validation_reason,
                    "blocking": False,
                }
            )
    return ReleaseDecision(status=status, findings=findings)


def publication_allowed(job: JobState) -> bool:
    return job.status == JobStatus.SUCCEEDED and job.release_status == ReleaseStatus.VERIFIED


def _guardrail_findings(reports: Iterable[GuardrailReport]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for report in latest_guardrail_reports(reports):
        for finding in report.findings:
            if finding.passed:
                continue
            findings.append(_finding_record(report, finding))
    return findings


def _finding_record(
    report: GuardrailReport,
    finding: GuardrailFinding,
) -> dict[str, object]:
    metadata = dict(finding.metadata)
    return {
        "source": report.name,
        "name": finding.name,
        "severity": finding.severity,
        "message": finding.message,
        "blocking": bool(metadata.get("blocking", finding.severity == "critical")),
        "metadata": metadata,
    }
