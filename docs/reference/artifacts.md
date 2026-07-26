# Artifacts

**Purpose:** list stable per-run files. **Audience:** operators and integrations. **Mode:** reference.

Default location: `REVIEW_ARTIFACT_ROOT/pr-<PR_ID>/runs/<RUN_ID>/`, with the latest run recorded in `pr-<PR_ID>/latest.txt`.

Known artifact names from `ARTIFACT_NAMES` (best-effort outputs may be absent):

`metadata.json`, `diff.patch`, `changed-files.json`, `commits.txt`, `final-findings.json`, `posted-comments.json`, `run-summary.json`, `review-system.combined.md`, `work-items.json`, `threads.json`, `review-result.json`, `sarif-findings.json`, `run.log`, and `crg-analysis.json`.

`review-result.json` is the canonical engine output. `final-findings.json` is a write-once postable projection and the `reviewforge post --input` interchange shape. `run-summary.json` is the machine-readable record of stage records, timing, token totals, posting counts, skip reason, and exit code. `run.log` is the human-readable chronological record of the run.

`sarif-findings.json` is an additive SARIF 2.1.0 projection of `review-result.json` for dashboards and code-scanning tools. It is written on a best-effort basis and never fails the review or changes ADO posting.

`crg-analysis.json` is the deterministic code-review-graph output, present only when `CRG_ENABLED` is set. It records `status` (`ok`, `degraded`, or `failed`), `tool_version`, `build` (`mode`, `duration_ms`), `summary`, `risk_score`, `changed_functions`, `affected_flows`, `test_gaps`, `impacted_files`, and `review_priorities`. Failure runs still write the file with `status: "failed"` and an `error` field.
