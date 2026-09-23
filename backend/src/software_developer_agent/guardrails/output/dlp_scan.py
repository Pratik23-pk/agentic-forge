import re
from dataclasses import dataclass

from software_developer_agent.models.job_state import GuardrailFinding, GuardrailReport

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
US_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PAYMENT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
PUBLIC_ASSET_URL_PATTERN = re.compile(
    r"https?://(?:images\.unsplash\.com|images\.pexels\.com|"
    r"images\.pixabay\.com|cdn\.pixabay\.com)/[^\s\"'<>]+",
    re.IGNORECASE,
)
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
ZERO_UUID_PATTERN = re.compile(r"\b0{8}-0{4}-0{4}-0{4}-0{12}\b")
RESERVED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "example.test",
    "example.local",
    "test.com",
    "test.local",
    "localhost",
}
CODE_DECORATOR_DOMAINS = {
    "app.delete",
    "app.get",
    "app.patch",
    "app.post",
    "app.put",
    "router.delete",
    "router.get",
    "router.patch",
    "router.post",
    "router.put",
}


@dataclass(frozen=True, slots=True)
class VerifiedMatch:
    value: str
    confidence: float
    reason: str


def scan_dlp(text: str) -> GuardrailReport:
    findings: list[GuardrailFinding] = []
    blocked_email_matches, suppressed_email_matches = _classify_emails(text)
    if blocked_email_matches:
        findings.append(_blocking_finding("email", blocked_email_matches))
    if suppressed_email_matches:
        findings.append(_suppressed_finding("email", suppressed_email_matches))

    ssn_matches = _verified_ssns(text)
    if ssn_matches:
        findings.append(_blocking_finding("us_ssn", ssn_matches))

    blocked_payment_card_matches, suppressed_payment_card_matches = _classify_payment_cards(text)
    if blocked_payment_card_matches:
        findings.append(_blocking_finding("payment_card", blocked_payment_card_matches))
    if suppressed_payment_card_matches:
        findings.append(_suppressed_finding("payment_card", suppressed_payment_card_matches))

    if not findings:
        findings.append(
            GuardrailFinding(
                name="dlp_scan",
                passed=True,
                severity="info",
                message="No PII-like patterns detected.",
            )
        )

    return GuardrailReport(
        name="dlp_scan", passed=all(item.passed for item in findings), findings=findings
    )


def _classify_emails(text: str) -> tuple[list[VerifiedMatch], list[VerifiedMatch]]:
    blocked: list[VerifiedMatch] = []
    suppressed: list[VerifiedMatch] = []
    for match in EMAIL_PATTERN.finditer(text):
        value = match.group(0)
        if match.start() > 0 and text[match.start() - 1] == "\\":
            suppressed.append(
                VerifiedMatch(
                    value=value,
                    confidence=0.12,
                    reason="JSON-escaped code token, likely not an email address",
                )
            )
            continue
        domain = value.rsplit("@", maxsplit=1)[-1].lower()
        if _is_demo_email(value, domain):
            suppressed.append(
                VerifiedMatch(
                    value=value,
                    confidence=0.15,
                    reason="reserved, local, or demo email placeholder",
                )
            )
            continue
        blocked.append(
            VerifiedMatch(
                value=value,
                confidence=0.92,
                reason="email address uses a non-reserved domain",
            )
        )
    return _unique_matches(blocked), _unique_matches(suppressed)


def _verified_emails(text: str) -> list[VerifiedMatch]:
    blocked, _ = _classify_emails(text)
    return blocked


def _verified_ssns(text: str) -> list[VerifiedMatch]:
    matches: list[VerifiedMatch] = []
    for value in US_SSN_PATTERN.findall(text):
        area, group, serial = value.split("-")
        if area in {"000", "666"} or area.startswith("9"):
            continue
        if group == "00" or serial == "0000":
            continue
        matches.append(
            VerifiedMatch(
                value=value,
                confidence=0.95,
                reason="valid-looking US SSN structure",
            )
        )
    return _unique_matches(matches)


def _classify_payment_cards(text: str) -> tuple[list[VerifiedMatch], list[VerifiedMatch]]:
    blocked: list[VerifiedMatch] = []
    suppressed: list[VerifiedMatch] = []
    uuid_spans = [match.span() for match in UUID_PATTERN.finditer(text)]
    uuid_spans.extend(match.span() for match in ZERO_UUID_PATTERN.finditer(text))
    public_asset_spans = [match.span() for match in PUBLIC_ASSET_URL_PATTERN.finditer(text)]
    for match in PAYMENT_CARD_PATTERN.finditer(text):
        raw_value = match.group(0)
        if _span_inside_any(match.span(), uuid_spans):
            suppressed.append(
                VerifiedMatch(
                    value=raw_value,
                    confidence=0.08,
                    reason="numeric candidate is inside a UUID-like identifier",
                )
            )
            continue
        if _span_inside_any(match.span(), public_asset_spans):
            suppressed.append(
                VerifiedMatch(
                    value=raw_value,
                    confidence=0.04,
                    reason="numeric candidate is part of a public image asset URL",
                )
            )
            continue
        digits = re.sub(r"\D", "", raw_value)
        if len(digits) < 13 or len(digits) > 19:
            continue
        if len(set(digits)) <= 1:
            suppressed.append(
                VerifiedMatch(
                    value=raw_value,
                    confidence=0.05,
                    reason="repeated digits are test data, not a valid payment card",
                )
            )
            continue
        if not _passes_luhn(digits):
            suppressed.append(
                VerifiedMatch(
                    value=raw_value,
                    confidence=0.18,
                    reason="number does not pass Luhn payment-card verification",
                )
            )
            continue
        blocked.append(
            VerifiedMatch(
                value=raw_value,
                confidence=0.94,
                reason="number length and Luhn checksum match a payment card",
            )
        )
    return _unique_matches(blocked), _unique_matches(suppressed)


def _verified_payment_cards(text: str) -> list[VerifiedMatch]:
    blocked, _ = _classify_payment_cards(text)
    return blocked


def _passes_luhn(digits: str) -> bool:
    total = 0
    reverse_digits = [int(digit) for digit in reversed(digits)]
    for index, digit in enumerate(reverse_digits):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _span_inside_any(span: tuple[int, int], containers: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(
        container_start <= start and end <= container_end
        for container_start, container_end in containers
    )


def _blocking_finding(name: str, matches: list[VerifiedMatch]) -> GuardrailFinding:
    return GuardrailFinding(
        name=f"dlp_{name}",
        passed=False,
        severity="critical" if name in {"payment_card", "us_ssn"} else "high",
        message=f"Verified sensitive {name} data detected in output.",
        metadata={
            "blocking": True,
            "classification": "verified_sensitive_data",
            "count": len(matches),
            "confidence": max(match.confidence for match in matches),
            "reasons": sorted({match.reason for match in matches}),
        },
    )


def _suppressed_finding(name: str, matches: list[VerifiedMatch]) -> GuardrailFinding:
    return GuardrailFinding(
        name=f"dlp_{name}_false_positive",
        passed=True,
        severity="info",
        message=f"Suppressed non-blocking {name} false positive candidate.",
        metadata={
            "blocking": False,
            "classification": "suppressed_false_positive",
            "count": len(matches),
            "confidence": max(match.confidence for match in matches),
            "samples": [match.value for match in matches[:5]],
            "reasons": sorted({match.reason for match in matches}),
        },
    )


def _is_demo_email(value: str, domain: str) -> bool:
    local_part = value.rsplit("@", maxsplit=1)[0]
    configuration_placeholder = local_part == local_part.upper() and any(
        marker in local_part for marker in ("YOUR_PASSWORD", "PASSWORD_PLACEHOLDER", "REPLACE_ME")
    )
    return (
        domain in RESERVED_EMAIL_DOMAINS
        or domain in CODE_DECORATOR_DOMAINS
        or domain.endswith((".test", ".example", ".invalid", ".local"))
        or configuration_placeholder
    )


def _unique_matches(matches: list[VerifiedMatch]) -> list[VerifiedMatch]:
    seen: set[str] = set()
    unique: list[VerifiedMatch] = []
    for match in matches:
        if match.value in seen:
            continue
        seen.add(match.value)
        unique.append(match)
    return unique
