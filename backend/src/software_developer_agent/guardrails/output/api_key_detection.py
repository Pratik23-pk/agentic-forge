import re

from software_developer_agent.models.job_state import GuardrailFinding, GuardrailReport

KEY_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
}
GENERIC_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?P<name>api[_-]?key|secret|token)\s*=\s*['\"](?P<value>[^'\"]{12,})['\"]"
)
PLACEHOLDER_MARKERS = {
    "change-me",
    "changeme",
    "dummy",
    "example",
    "placeholder",
    "replace-me",
    "replace_this",
    "test-value",
    "your-",
    "your_",
}


def scan_api_keys(text: str) -> GuardrailReport:
    findings: list[GuardrailFinding] = []
    for name, pattern in KEY_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            findings.append(
                GuardrailFinding(
                    name=f"api_key_{name}",
                    passed=False,
                    severity="critical",
                    message=f"Potential {name} secret detected in output.",
                    metadata={
                        "blocking": True,
                        "classification": "verified_secret_pattern",
                        "count": len(matches),
                    },
                )
            )

    blocked_assignments = []
    suppressed_assignments = []
    for match in GENERIC_ASSIGNMENT_PATTERN.finditer(text):
        value = match.group("value").strip().lower()
        if any(marker in value for marker in PLACEHOLDER_MARKERS) or set(value) <= {"x", "-", "_"}:
            suppressed_assignments.append(match.group(0))
        else:
            blocked_assignments.append(match.group(0))
    if blocked_assignments:
        findings.append(
            GuardrailFinding(
                name="api_key_generic_assignment",
                passed=False,
                severity="critical",
                message="Potential generic secret assignment detected in output.",
                metadata={
                    "blocking": True,
                    "classification": "verified_secret_pattern",
                    "count": len(blocked_assignments),
                },
            )
        )
    if suppressed_assignments:
        findings.append(
            GuardrailFinding(
                name="api_key_placeholder_false_positive",
                passed=True,
                severity="info",
                message="Suppressed non-secret configuration placeholder.",
                metadata={
                    "blocking": False,
                    "classification": "suppressed_false_positive",
                    "count": len(suppressed_assignments),
                },
            )
        )

    if not findings:
        findings.append(
            GuardrailFinding(
                name="api_key_detection",
                passed=True,
                severity="info",
                message="No API key patterns detected.",
            )
        )

    return GuardrailReport(
        name="api_key_detection",
        passed=all(item.passed for item in findings),
        findings=findings,
    )
