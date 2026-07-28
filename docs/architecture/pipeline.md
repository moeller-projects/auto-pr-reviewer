# Pipeline

**Purpose:** document stage order and execution semantics. **Audience:** operators and contributors. **Mode:** explanation.

`run_stages()` invokes stages in order, captures timing and token usage, returns `StageResult` records, and stops after the first failed stage. A stage may return `skipped` through `should_run()`.

Pipelines declared in `pipeline/stages/__init__.py`:

- `DEFAULT_PIPELINE`: `FetchPrMetadataStage` -> `PrepareRepositoryStage` -> `EnrichWithCrgStage` -> `ExecuteReasoningEngineStage` -> `ValidateAnchorsStage` -> `PostToAdoStage`.
- `REVIEW_ONLY_PIPELINE`: the same sequence without posting.
- `POST_ONLY_PIPELINE`: `FetchPrMetadataStage` -> `PostToAdoStage`.
- `FAST_REVIEW_PIPELINE` and `FAST_REVIEW_REVIEW_ONLY_PIPELINE`: compatibility entry points mirroring the corresponding current lists.

`EnrichWithCrgStage` is always registered but self-skips unless `CRG_ENABLED` is set and the review mode is not `no_op`. `PrepareRepositoryStage` writes the diff, changed-file list, and commits before staging complete deterministic copies under the checkout's `.reviewforge-context/`; CRG refreshes the graph copy after its current artifact is written. It builds (or incrementally updates) a Tree-sitter knowledge graph, writes `crg-analysis.json`, and writes the additive `graph-context.json`. `GRAPH_API_DIFF`, `GRAPH_FLOWS`, and `GRAPH_ARCH` independently enable base snapshot diffing, critical-flow context, and hub/bridge architecture context. Each feature records an independent status and duration, degrades independently, and never fails the review.

The selected engine owns Pi-driven reasoning. The physical pipeline owns metadata, repository preparation, materialization, projection, and posting. `run_full`, `run_review_only`, and `run_post_only` create artifacts, run the relevant list, write `run-summary.json`, and return `RunOutcome`.

Review mode can skip inactive or draft PRs, or target branches outside `REVIEW_TARGET_BRANCHES`, unless `force_review` is enabled. `dry_run` and `--no-post` prevent posting while retaining generated artifacts.

Follow-up reviews include deterministic `previousFeedback` curated from bot-authored ADO threads. Dismissed entries are not re-raised unless changed code genuinely reintroduces the issue; fixed entries are reported only when reintroduced. Non-regression re-raises are filtered before posting and recorded in `discarded_findings`.
