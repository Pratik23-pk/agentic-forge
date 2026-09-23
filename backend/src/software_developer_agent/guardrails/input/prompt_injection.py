import re

from software_developer_agent.models.job_state import GuardrailFinding, GuardrailReport

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bignore (all )?(previous|prior) instructions\b"),
    re.compile(r"(?i)\breveal\b.*\b(system|developer) prompt\b"),
    re.compile(r"(?i)\bexfiltrate\b.*\b(secret|token|api key|credential)\b"),
    re.compile(r"(?i)\b(show|print|reveal|leak)\b.*\b(secret|token|api key|credential)\b"),
    re.compile(r"(?i)\byou are now\b.*\b(system|developer|admin)\b"),
)


def check_prompt_injection(prompt: str) -> GuardrailReport:
    findings: list[GuardrailFinding] = []
    for pattern in INJECTION_PATTERNS:
        if pattern.search(prompt):
            findings.append(
                GuardrailFinding(
                    name="prompt_injection",
                    passed=False,
                    severity="critical",
                    message="Prompt contains a high-risk instruction override or secret request.",
                    metadata={"pattern": pattern.pattern},
                )
            )

    if not findings:
        findings.append(
            GuardrailFinding(
                name="prompt_injection",
                passed=True,
                severity="info",
                message="No prompt-injection patterns detected.",
            )
        )

    return GuardrailReport(
        name="prompt_injection",
        passed=all(finding.passed for finding in findings),
        findings=findings,
    )
