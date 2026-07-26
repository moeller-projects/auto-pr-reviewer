## ADDED Requirements

### Requirement: CRG enrichment stage runs in every engine pipeline
ReviewForge MUST register `EnrichWithCrgStage` between `PrepareRepositoryStage` and `ExecuteReasoningEngineStage` in `DEFAULT_PIPELINE`, `REVIEW_ONLY_PIPELINE`, `FAST_REVIEW_PIPELINE`, and `FAST_REVIEW_REVIEW_ONLY_PIPELINE`.

#### Scenario: Stage ordering
- **WHEN** any engine pipeline executes
- **THEN** the CRG stage MUST run after the repository is prepared and before the reasoning engine executes

### Requirement: The stage is opt-in and no-op aware
The stage MUST run only when `crg_enabled` is true (`CRG_ENABLED`) and the review mode is not `no_op`. With the flag off, pipeline behavior MUST be byte-identical to the pre-integration behavior.

#### Scenario: Flag disabled
- **WHEN** `CRG_ENABLED` is unset
- **THEN** the stage MUST skip and MUST NOT write `crg-analysis.json` or modify any prompt

#### Scenario: No-op review mode
- **WHEN** the review mode is `no_op`
- **THEN** the stage MUST skip even when `CRG_ENABLED` is set

### Requirement: Graph persistence across runs
The graph database MUST be stored at `<cache-root>/<repo_id>/crg-<tool_version>/crg.db`, where the cache root defaults to `<review_artifact_root>/crg-cache` and is overridable via `CRG_CACHE_DIR`. The path MUST NOT contain the run id, PR id, or a timestamp, and MUST survive deletion of the repo checkout and the per-run artifact directory.

#### Scenario: Cold then warm
- **WHEN** two consecutive runs target the same repository and CRG version
- **THEN** the first run MUST perform a full build and the second MUST perform an incremental update without calling full build again

#### Scenario: Version bump
- **WHEN** the CRG tool version changes
- **THEN** exactly one cold full rebuild MUST occur before warm updates resume

### Requirement: Cold/warm selection is decided before the store opens
The stage MUST decide between full and incremental build by testing database existence before constructing the graph store, because opening the store creates the file eagerly.

#### Scenario: First run with eager store creation
- **WHEN** no database file exists and the store creates it on open
- **THEN** the stage MUST still select the full build for that run

### Requirement: Warm updates use the pipeline changed-file list
`incremental_update` MUST be called with the PR's changed files from pipeline state, not with a git-base guess.

#### Scenario: Shallow detached checkout
- **WHEN** the checkout lacks a resolvable `HEAD~1` base
- **THEN** the incremental update MUST still re-parse exactly the PR's changed files and their dependents

### Requirement: Graceful degradation with failed-status artifact
Any CRG failure (missing package, build error, analysis error) MUST log a warning, write `crg-analysis.json` with `status: "failed"` and an `error` field, and allow the pipeline to continue. The stage MUST NOT raise `ReviewForgeError` or any other exception.

#### Scenario: Build failure
- **WHEN** the graph build raises
- **THEN** the stage result MUST be `ok`, the artifact MUST record `status: "failed"`, and subsequent stages MUST run normally

### Requirement: Canonical analysis document
`crg-analysis.json` MUST contain `status`, `tool_version`, `build` (`mode`, `duration_ms`), `summary`, `risk_score`, `changed_functions`, `affected_flows`, `test_gaps`, `impacted_files`, and `review_priorities`. Identical inputs MUST produce identical documents modulo `build.duration_ms`. The package's function-truncation flag MUST surface as `status: "degraded"`.

#### Scenario: Truncated analysis
- **WHEN** the CRG analysis reports `functions_truncated`
- **THEN** the document status MUST be `degraded`

#### Scenario: Determinism
- **WHEN** the stage runs twice with identical inputs
- **THEN** the artifacts MUST be identical except for `build.duration_ms`

### Requirement: Python-side invocation only
CRG MUST be invoked in-process from Python. The integration MUST NOT add an MCP server, daemon, new model tools, or new runtime dependencies beyond the pinned `code-review-graph` package, and MUST NOT change the `ModelRunner` contract or Pi's read-only tool sandbox.

#### Scenario: Dependency audit
- **WHEN** the integration lands
- **THEN** `code-review-graph` MUST be pinned exactly in `pyproject.toml` and `uv.lock`, and no MCP imports MUST exist in `reviewforge` code
