"""Deterministic acceptable-use gate for inbound build requests.

This guardrail runs before the planner, the design director, and every model
client, so a prohibited request is rejected without spending budget, worker
attempts, or artifact storage. It uses pattern matching only: no network call,
no model call, and no dependency beyond the standard library.

Each category separates two kinds of evidence:

* ``hard_patterns`` block unconditionally. They describe requests that have no
  legitimate build interpretation.
* ``soft_patterns`` block by default, and are released only when the prompt
  also carries an explicit legitimate context (``exemptions``). An
  ``escalators`` match cancels any exemption, so defensive vocabulary cannot be
  used to smuggle an offensive request through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from software_developer_agent.models.job_state import GuardrailFinding, GuardrailReport

GUARDRAIL_NAME = "acceptable_use"
MAX_RECORDED_EVIDENCE = 5
ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\ufeff]")
WHITESPACE = re.compile(r"\s+")


class ProhibitedRequestError(ValueError):
    """Raised when inbound text is rejected by the acceptable-use guardrail."""

    def __init__(self, report: GuardrailReport, source: str = "prompt") -> None:
        self.report = report
        self.source = source
        self.categories = [
            str(finding.metadata.get("category", "unknown"))
            for finding in report.findings
            if not finding.passed
        ]
        super().__init__(prohibited_use_reason(report) or "Request rejected by acceptable use.")


@dataclass(frozen=True, slots=True)
class ProhibitedCategory:
    """One acceptable-use category and the evidence that decides it."""

    category_id: str
    policy_id: str
    label: str
    hard_patterns: tuple[re.Pattern[str], ...] = ()
    soft_patterns: tuple[re.Pattern[str], ...] = ()
    exemptions: tuple[re.Pattern[str], ...] = ()
    escalators: tuple[re.Pattern[str], ...] = ()
    redact_evidence: bool = False


def _patterns(*expressions: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(expression, re.IGNORECASE) for expression in expressions)


CHILD_SAFETY = ProhibitedCategory(
    category_id="child_safety",
    policy_id="AUP-001",
    label="child sexual abuse material",
    redact_evidence=True,
    hard_patterns=_patterns(
        r"\bcsam\b",
        r"\bchild\s*(?:p[o0]rn\w*|sexual\s+abuse|sex\s+abuse)\b",
        r"\b(?:child|children|minors?|underage|under[-\s]?age|pre[-\s]?teens?)\s+"
        r"(?:nude|naked|nudity|sexual|sexuali[sz]ed|erotic|p[o0]rn\w*)\b",
        r"\b(?:nude|naked|sexual|erotic|p[o0]rn\w*)\s+"
        r"(?:child|children|minors?|toddlers?|kids)\b",
        r"\b(?:lolicon|loli|shotacon|jailbait)\b",
        r"\bcp\s+(?:site|website|content|images?|videos?)\b",
    ),
)

MALICIOUS_SOFTWARE = ProhibitedCategory(
    category_id="malicious_software",
    policy_id="AUP-002",
    label="malicious software",
    soft_patterns=_patterns(
        r"\bmal(?:ware|icious\s+software)\b",
        r"\bransom\s?ware\b",
        r"\bspyware\b",
        r"\bstalkerware\b",
        r"\bkey[\s-]?logger\w*\b",
        r"\bbotnets?\b",
        r"\brootkits?\b",
        r"\btrojans?\b",
        r"\bcomputer\s+worm\b",
        # "virus" alone is ambiguous (epidemiology, antivirus tooling, game themes),
        # so it only counts with malicious framing around it.
        r"\b(?:computer|pc|windows|macro|boot[\s-]?sector|polymorphic|file)\s+virus(?:es)?\b",
        r"\b(?:write|build|create|make|code|generate|develop|program|design)\s+"
        r"(?:a\s+|an\s+|the\s+|me\s+)?(?:\w+\s+){0,2}virus(?:es)?\b",
        r"\bvirus(?:es)?\s+(?:payloads?|builders?|generators?|source\s+code)\b",
        r"\bvirus(?:es)?\s+(?:that\s+)?(?:spreads?|infects?|replicates?|deletes?|encrypts?)\b",
        r"\bcryptojack\w*\b",
        r"\bcrypto[\s-]?miner\b",
        r"\b(?:credential|password|info(?:rmation)?|data|cookie)\s+stealer\b",
        r"\bstealer\s+logs?\b",
        r"\bexploit\s+kit\b",
        r"\bzero[\s-]?day\s+exploit\b",
        r"\bremote\s+access\s+(?:trojan|tool)\b",
        r"\bbackdoors?\b",
        r"\bddos\b",
        r"\bdenial[\s-]of[\s-]service\b",
        r"\bcrypter\b",
        r"\b(?:payload\s+)?droppers?\b",
        r"\bwiper\s+malware\b",
    ),
    exemptions=_patterns(
        r"\banti[\s-]?virus\b",
        r"\bantivirus\b",
        r"\b(?:edr|xdr|siem|soc|ids|ips)\b",
        r"\b(?:detect\w*|analysis|analy[sz]\w*|scanner|scanning|research\w*|forensics?|triage|"
        r"sandbox\w*|quarantine|remediation|mitigat\w*|prevent\w*|protect\w*|defen\w*|"
        r"blue\s+team|incident\s+response|threat\s+intel\w*|signature\s+database)\b",
        r"\b(?:awareness|training|education\w*|course|curriculum|documentation|blog|news|"
        r"explain\w*|glossary|encyclopedia|tutorial)\b",
        r"\b(?:epidemiolog\w*|outbreak|pandemic|endemic|vaccin\w*|immuni[sz]\w*|infection\s+rates?|"
        r"public\s+health|hospitals?|clinics?|patients?|influenza|covid|viral\s+load|"
        r"contact\s+tracing)\b",
        r"\bflu\b",
        r"\b(?:comparison|review|pricing|directory|marketplace)\s+(?:site|website|page|app)\b",
        r"\b(?:disaster|backup)\s+(?:and\s+)?recovery\b",
    ),
    escalators=_patterns(
        r"\b(?:fully\s+)?undetectable\b",
        r"\bfud\b",
        r"\bevade\s+(?:detection|antivirus|av|edr)\b",
        r"\bbypass\s+(?:antivirus|av|edr|defender|windows\s+defender)\b",
        r"\bavoid\s+(?:being\s+)?detect\w*\b",
        r"\bwithout\s+being\s+detected\b",
        r"\bencrypt\s+(?:the\s+)?(?:victim|target|user)s?'?s?\s+files\b",
        r"\bransom\s+(?:note|payment|demand)\b",
        r"\bexfiltrat\w*\b",
        r"\bsteal\s+(?:credentials|passwords|cookies|wallets?|session|browser\s+data)\b",
        r"\b(?:command\s+and\s+control|c2)\s+(?:server|panel|infrastructure)\b",
        r"\bself[\s-]?replicat\w*\b",
        r"\bspread\s+(?:to|across)\s+(?:other\s+)?(?:machines|computers|devices|networks)\b",
        r"\binfect\s+(?:a|the|other|target|victim)\w*\b",
    ),
)

SEXUAL_CONTENT = ProhibitedCategory(
    category_id="sexual_content",
    policy_id="AUP-003",
    label="sexual content platform",
    hard_patterns=_patterns(
        r"\bp[o0]rn(?:o|ography|hub)?\s*"
        r"(?:site|website|platform|app|tube|hub|clone|aggregator|streaming|gallery)\b",
        r"\b(?:site|website|platform|app|clone)\s+(?:for|of)\s+p[o0]rn\w*\b",
        r"\b(?:onlyfans|pornhub|xvideos|xhamster|redtube|brazzers|chaturbate)\s*"
        r"(?:clone|copy|style|like|alternative|competitor|replica)\b",
        r"\bhentai\b",
        r"\bcam[\s-]?girls?\b",
        r"\bsex\s?cams?\b",
        r"\bwebcam\s+sex\b",
        r"\bxxx\s+(?:site|website|videos?|content|tube)\b",
        r"\b(?:nudify|undress(?:ing)?\s+app|deep\s?fake\s+p[o0]rn|revenge\s+p[o0]rn)\b",
    ),
    soft_patterns=_patterns(
        r"\bp[o0]rn\w*\b",
        r"\badult\s+(?:content|videos?|entertainment|streaming|material|images?)\b",
        r"\bnsfw\s+(?:content|site|website|images?|gallery|videos?)\b",
        r"\berotica?\b",
        r"\bsexting\b",
        r"\bescort\s+(?:service|booking|directory|listing)\b",
    ),
    exemptions=_patterns(
        r"\bsexual\s+(?:health|wellness|education)\b",
        r"\bsex\s+education\b",
        r"\breproductive\s+health\b",
        r"\badult\s+(?:education|learning|literacy|training|course|school|student)\w*\b",
        r"\b(?:filter\w*|moderat\w*|blocklist|block\s+list|detect\w*|classifier|safe\s?search|"
        r"takedown|report\w*)\b",
        r"\bparental\s+controls?\b",
        r"\bage\s+(?:verification|gate|gating)\b",
    ),
)

FRAUD_DECEPTION = ProhibitedCategory(
    category_id="fraud_deception",
    policy_id="AUP-004",
    label="fraud or deception tooling",
    soft_patterns=_patterns(
        r"\bphishing\s+(?:site|website|page|kit|email|campaign|link|kit)\b",
        r"\bfake\s+(?:bank|banking|login|paypal|stripe)\s+(?:page|site|portal|screen|form)\b",
        r"\b(?:credit\s+card|card)\s+skimm\w*\b",
        r"\bcarding\s+(?:site|shop|forum|store)\b",
        r"\bponzi\b",
        r"\bpyramid\s+scheme\b",
        r"\bmoney\s+laundering\b",
        r"\bfake\s+(?:ids?|passports?|driver'?s?\s+licen[cs]es?|diplomas?|degrees?|"
        r"certificates?|vaccination\s+cards?|invoices?|receipts?|reviews?|testimonials?)\b",
        r"\bcounterfeit\b",
        r"\bforged?\s+(?:documents?|signatures?|records?)\b",
        r"\bscam\s+(?:site|website|page|bot|email)\b",
        r"\botp\s+bypass\b",
        r"\bessay\s+mill\b",
        r"\b(?:exam|test)\s+cheat\w*\b",
        r"\bcheat\s+on\s+(?:exams?|tests?)\b",
        r"\bplagiarism\s+(?:generator|rewriter|spinner)\b",
    ),
    exemptions=_patterns(
        r"\banti[\s-]?(?:phishing|fraud|money[\s-]?laundering|counterfeit)\b",
        r"\b(?:aml|kyc|compliance)\b",
        r"\b(?:detect\w*|prevent\w*|simulat\w*|awareness|training|education\w*|report\w*|"
        r"verif\w*|validation|integrity|proctor\w*|moderat\w*|takedown|investigat\w*|"
        r"forensics?|audit\w*)\b",
    ),
)

HARASSMENT_SURVEILLANCE = ProhibitedCategory(
    category_id="harassment_surveillance",
    policy_id="AUP-005",
    label="harassment or non-consensual surveillance",
    soft_patterns=_patterns(
        r"\bdox(?:x)?(?:ing|ed)?\b",
        r"\bstalk(?:ing|er)?\b",
        r"\bspy(?:ing)?\s+on\b",
        # Personal relationships only: workforce and fleet tracking are legitimate, and
        # non-consensual monitoring is caught by the explicit "without consent" pattern.
        r"\btrack\s+(?:my|his|her|their|someone'?s?)\s+"
        r"(?:girlfriend|boyfriend|wife|husband|partner|spouse|ex|neighbou?r)\b",
        r"\bwithout\s+(?:their|his|her|the\s+user'?s?|the\s+person'?s?)\s+"
        r"(?:knowledge|consent|permission|awareness)\b",
        r"\bread\s+(?:someone|their|his|her)'?s?\s+(?:messages|texts|whatsapp|emails?|dms?)\b",
        r"\bintercept\s+(?:messages|sms|calls|traffic|emails?)\b",
        r"\bhidden\s+(?:camera|recorder|microphone|tracker)\s+app\b",
        r"\bswatting\b",
        r"\bharassment\s+bot\b",
        r"\bmass[\s-]?report(?:ing)?\s+bot\b",
        r"\bdeep\s?fake\s+nudes?\b",
    ),
    exemptions=_patterns(
        r"\banti[\s-]?stalk\w*\b",
        r"\b(?:consent\w*|opt[\s-]?in|safeguard\w*|victim\s+support|helpline|"
        r"detect\w*|prevent\w*|moderat\w*|report\w*|takedown|awareness|training|education\w*)\b",
    ),
)

UNAUTHORIZED_ACCESS = ProhibitedCategory(
    category_id="unauthorized_access",
    policy_id="AUP-006",
    label="unauthorized system access",
    soft_patterns=_patterns(
        r"\bhack\s+(?:into|someone|somebody|a|an|the)\b",
        r"\bhacking\s+tool\b",
        r"\bcrack\s+(?:passwords?|wifi|wpa|licen[cs]es?|software)\b",
        r"\bcredential\s+stuffing\b",
        r"\baccount\s+takeover\b",
        r"\bsession\s+hijack\w*\b",
        r"\bsim[\s-]?swap\w*\b",
        r"\bsql\s+injection\b",
        r"\bbrute[\s-]?force\s+(?:login|attack|passwords?)\b",
        r"\bbypass\s+(?:authentication|auth|login|2fa|mfa|otp|paywall|licen[cs]ing|licen[cs]e)\b",
        r"\bkeygen\b",
        r"\blicen[cs]e\s+crack\w*\b",
        r"\bpiracy\s+(?:site|website)\b",
        r"\btorrent\s+site\s+for\s+(?:movies|pirated|cracked)\b",
    ),
    exemptions=_patterns(
        r"\b(?:pen(?:etration)?[\s-]?test\w*|pentest\w*|bug\s+bounty|ctf|capture\s+the\s+flag|"
        r"red\s+team|authori[sz]\w*|owasp|secure\s+coding|hardening|lab|sandbox\w*)\b",
        r"\bvulnerability\s+(?:scanner|management|assessment|disclosure)\b",
        r"\b(?:detect\w*|prevent\w*|mitigat\w*|defen\w*|protect\w*|monitor\w*|audit\w*|"
        r"rate[\s-]?limit\w*|training|education\w*|awareness|simulat\w*|research\w*)\b",
    ),
)

WEAPONS_ILLEGAL_GOODS = ProhibitedCategory(
    category_id="weapons_illegal_goods",
    policy_id="AUP-007",
    label="weapons or illegal goods",
    soft_patterns=_patterns(
        r"\bbomb[\s-]?making\b",
        r"\bpipe\s+bombs?\b",
        r"\bimprovised\s+explosive\b",
        r"\b(?:nerve|chemical|biological)\s+(?:agents?|weapons?)\b",
        r"\bbio[\s-]?weapons?\b",
        r"\b(?:ghost\s+guns?|untraceable\s+firearms?|3d[\s-]?printed\s+(?:guns?|firearms?)|"
        r"auto\s+sear)\b",
        r"\bsilencer\s+(?:build|design|plans?|blueprint)\b",
        r"\bsynthesi[sz]e?\s+(?:meth\w*|fentanyl|explosives?|ricin|sarin|nerve\s+agent)\b",
        r"\b(?:meth|fentanyl|cocaine|heroin)\s+(?:lab|synthesis|production|recipe)\b",
        r"\b(?:darknet|dark\s+web)\s+market(?:place)?\b",
        r"\bdrug\s+marketplace\b",
        r"\bsuicide\s+method\w*\b",
    ),
    exemptions=_patterns(
        r"\b(?:detect\w*|screening|disposal|defus\w*|safety|training|education\w*|awareness|"
        r"museum|history|historical|prevent\w*|helpline|crisis\s+support|"
        r"research\s+paper|documentation|compliance|regulat\w*)\b",
    ),
)

PROHIBITED_CATEGORIES: tuple[ProhibitedCategory, ...] = (
    CHILD_SAFETY,
    MALICIOUS_SOFTWARE,
    SEXUAL_CONTENT,
    FRAUD_DECEPTION,
    HARASSMENT_SURVEILLANCE,
    UNAUTHORIZED_ACCESS,
    WEAPONS_ILLEGAL_GOODS,
)


def prompt_fingerprint(text: str) -> str:
    """Stable audit identifier that does not persist the rejected text itself."""

    return sha256(_normalize(text).encode("utf-8")).hexdigest()[:16]


def check_acceptable_use(prompt: str) -> GuardrailReport:
    """Reject prohibited build requests deterministically, before any model call."""

    normalized = _normalize(prompt)
    findings = [
        finding
        for category in PROHIBITED_CATEGORIES
        if (finding := _evaluate(category, normalized)) is not None
    ]
    if not findings:
        findings.append(
            GuardrailFinding(
                name=GUARDRAIL_NAME,
                passed=True,
                severity="info",
                message="No prohibited-use patterns detected.",
            )
        )
    return GuardrailReport(
        name=GUARDRAIL_NAME,
        passed=all(finding.passed for finding in findings),
        findings=findings,
    )


def prohibited_use_findings(report: GuardrailReport) -> list[GuardrailFinding]:
    if report.name != GUARDRAIL_NAME:
        return []
    return [finding for finding in report.findings if not finding.passed]


def prohibited_use_reason(report: GuardrailReport) -> str | None:
    """Compose the operator-facing rejection message for a blocked report."""

    findings = prohibited_use_findings(report)
    if not findings:
        return None
    labels = sorted({str(finding.metadata.get("label", "prohibited use")) for finding in findings})
    policies = sorted({str(finding.metadata.get("policy_id", "AUP")) for finding in findings})
    return (
        f"This request was rejected by the acceptable-use guardrail ({', '.join(labels)}; "
        f"policy {', '.join(policies)}). No planning, model calls, worker attempts, or "
        "generated files were produced, and no budget was consumed. Revise the request or "
        "contact the operator if you believe this is a mistake."
    )


def _evaluate(category: ProhibitedCategory, normalized: str) -> GuardrailFinding | None:
    hard_hits = _matches(category.hard_patterns, normalized)
    soft_hits = _matches(category.soft_patterns, normalized)
    if not hard_hits and not soft_hits:
        return None

    escalated = _matches(category.escalators, normalized)
    exempted = _matches(category.exemptions, normalized)
    if hard_hits or escalated or not exempted:
        return _blocking_finding(
            category,
            evidence=[*hard_hits, *soft_hits],
            escalators=escalated,
            unconditional=bool(hard_hits),
        )
    return _exempted_finding(category, evidence=soft_hits, exemptions=exempted)


def _blocking_finding(
    category: ProhibitedCategory,
    *,
    evidence: list[str],
    escalators: list[str],
    unconditional: bool,
) -> GuardrailFinding:
    return GuardrailFinding(
        name=f"{GUARDRAIL_NAME}_{category.category_id}",
        passed=False,
        severity="critical",
        message=(
            f"Request rejected under the acceptable-use policy: {category.label}."
        ),
        metadata={
            "blocking": True,
            "classification": "prohibited_use",
            "category": category.category_id,
            "policy_id": category.policy_id,
            "label": category.label,
            "unconditional": unconditional,
            "escalated": bool(escalators),
            "match_count": len(evidence),
            "matched_terms": (
                ["[redacted]"]
                if category.redact_evidence
                else _unique(evidence)[:MAX_RECORDED_EVIDENCE]
            ),
            "escalating_terms": _unique(escalators)[:MAX_RECORDED_EVIDENCE],
        },
    )


def _exempted_finding(
    category: ProhibitedCategory,
    *,
    evidence: list[str],
    exemptions: list[str],
) -> GuardrailFinding:
    return GuardrailFinding(
        name=f"{GUARDRAIL_NAME}_{category.category_id}_exempted",
        passed=True,
        severity="info",
        message=(
            f"Allowed a {category.label} keyword in an explicit legitimate context."
        ),
        metadata={
            "blocking": False,
            "classification": "suppressed_false_positive",
            "category": category.category_id,
            "policy_id": category.policy_id,
            "label": category.label,
            "matched_terms": _unique(evidence)[:MAX_RECORDED_EVIDENCE],
            "exempting_terms": _unique(exemptions)[:MAX_RECORDED_EVIDENCE],
        },
    )


def _matches(patterns: tuple[re.Pattern[str], ...], normalized: str) -> list[str]:
    return [match.group(0).strip() for pattern in patterns for match in pattern.finditer(normalized)]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _normalize(prompt: str) -> str:
    collapsed = ZERO_WIDTH.sub("", prompt)
    collapsed = collapsed.replace("’", "'").replace("‘", "'")
    collapsed = collapsed.replace("“", '"').replace("”", '"')
    return WHITESPACE.sub(" ", collapsed).lower()
