# Agentic Forge Regression Campaign

This directory is campaign-only control state. It is outside the packaged backend and frontend
applications and must not be copied into a production deployment.

The campaign contains three diversified cases in each of four categories: browser games,
commerce, video, and realtime collaboration. The controller persists state after every case,
skips completed cases on restart, retains cumulative paid cost across resets, and reserves the
configured maximum per-run cost before starting another paid case.

From the project root:

```bash
backend/.venv/bin/python benchmark-results/campaign-control/run_campaign.py --preflight
backend/.venv/bin/python benchmark-results/campaign-control/run_campaign.py --live --budget-cap-usd 12
backend/.venv/bin/python benchmark-results/campaign-control/run_campaign.py --status
```

Pass `--case CASE_ID` one or more times to run only selected cases during focused diagnosis.

`--reset-live` marks all cases pending for a clean certification round while preserving cumulative
campaign spend. `--reset-failed` marks only failed selected cases pending. Product defects discovered
by this campaign belong in the production source with focused regression tests; campaign lifecycle
behavior remains confined to this directory.
