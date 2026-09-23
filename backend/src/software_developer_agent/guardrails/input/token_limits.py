from software_developer_agent.models.job_state import GuardrailFinding, GuardrailReport


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def check_input_token_limit(prompt: str, max_tokens: int) -> GuardrailReport:
    estimated = estimate_tokens(prompt)
    passed = estimated <= max_tokens
    finding = GuardrailFinding(
        name="input_token_limit",
        passed=passed,
        severity="high" if not passed else "info",
        message=(
            f"Estimated input tokens {estimated} are within limit {max_tokens}."
            if passed
            else f"Estimated input tokens {estimated} exceed limit {max_tokens}."
        ),
        metadata={"estimated_tokens": estimated, "max_tokens": max_tokens},
    )
    return GuardrailReport(name="input_token_limit", passed=passed, findings=[finding])
