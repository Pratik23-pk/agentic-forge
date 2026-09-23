# Security Guardrails

## Input

- Token limit estimation protects against oversized requests.
- Prompt-injection detection blocks direct instruction override attempts and secret-exfiltration requests.

## Output

- DLP scan blocks verified sensitive emails, SSNs, and Luhn-valid payment-card numbers.
- DLP scan records known false positives as non-blocking findings, including reserved/demo/local emails, JSON-escaped route decorators, UUID-like identifiers, repeated digit samples, and invalid Luhn payment-card candidates.
- API key detection blocks common secret shapes.
- Vulnerability scan flags risky code patterns such as `eval`, `exec`, shell execution, debug mode, and string-formatted SQL.
- Final scans include every staged text file, including hidden configuration files.
- Validation rejects destructive filesystem calls, child processes, socket access, unsafe npm scripts, executable setup files, URL/VCS dependencies, and non-allowlisted Python build backends.
- Certified capability packs replace LLM-selected core framework versions before dependency installation.
- High-severity production dependency findings and critical development dependency findings block publication; high development-only findings remain recorded advisories.
- LangGraph checkpoint deserialization uses strict msgpack mode and stores only JSON-compatible manifest state.

## False Positives

- Suppressed findings are marked with `classification=suppressed_false_positive` and `blocking=false`.
- Suppressed findings allow the workflow to continue.
- Suppressed findings remain visible in the Security/QA panel so developers can tune prompts, generated seeds, or scanner rules.

## Logging

Logs pass through a redaction filter that masks common key, token, password, and OpenAI key formats.

## Web Tooling

Serper and Playwright remain separately gated. Tool calls now flow through the MCP client/server boundary, where each tool is allowlisted by worker kind, timed, redacted, and recorded on worker results. Browser content is treated as untrusted input and obvious prompt-injection strings are stripped before entering worker context.

## Human Approval

Human checkpoints pause the workflow with a compact visual artifact and a single approval or change request. Requested changes are appended to the relevant worker instructions and rerun only that worker stage.

## MCP Boundary

The current MCP server exposes safe, deterministic development tools plus gated Serper and Playwright adapters. Do not add unrestricted shell, file-write, deployment, or credential-management tools until the MCP server runs with process isolation, scoped workspace permissions, and explicit per-tool approval policy.

## Default Secret Posture

The settings class defaults to `ENABLE_LLM_CALLS=false`. Runnable non-test project generation
fails clearly rather than publishing a generic fallback unless `ENABLE_LLM_CALLS=true` and
`OPENAI_API_KEY` is configured.

## Generated Code Execution

Artifact validation runs in a temporary staging project. Secret-like environment variables are
removed, outbound HTTP proxy variables are redirected during generated tests/builds, commands have
timeouts, and generated caches are deleted before publication.

These controls reduce risk but do not provide kernel-level isolation. Before accepting untrusted
public prompts, run validation in an ephemeral container or VM with a read-only host filesystem,
no credentials, constrained CPU/memory, and controlled egress.
