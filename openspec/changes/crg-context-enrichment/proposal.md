## Why

The model spends part of its reasoning budget on ad-hoc file reading and grep
exploration to understand which functions were changed, which callers are
affected, and whether tests cover the changed code. This exploration is
non-deterministic, unbounded, and invisible to operators.

## What Changes

- A new `EnrichWithCrgStage` is inserted between `PrepareRepositoryStage` and
  `ExecuteReasoningEngineStage` in every pipeline variant that runs a reasoning
  engine (`DEFAULT_PIPELINE`, `REVIEW_ONLY_PIPELINE`, `FAST_REVIEW_PIPELINE`,
  `FAST_REVIEW_REVIEW_ONLY_PIPELINE`).
- The stage uses `code-review-graph` (Tree-sitter, SQLite) to build a knowledge
  graph from the already-checked-out working tree and runs change-impact
  analysis: changed functions, blast radius, affected flows, test gaps, and risk
  scores.
- The analysis is stored in `ctx.extras["crg_analysis"]` and injected into the
  single-pi prompt prefix by `_build_single_pi_prefix` in
  `reasoning/single_pi.py`.
- The analysis is also persisted as `crg-analysis.json` in the run artifact
  directory (new entry in `ARTIFACT_NAMES`).
- A new boolean config field `crg_enabled` (env `CRG_ENABLED`, default `false`)
  controls whether the stage runs. The stage is always registered in the
  pipeline; it skips itself when disabled or when `code-review-graph` is absent.
- `code-review-graph>=2.3.7` is listed under the new `crg` optional-dependency
  group in `pyproject.toml`.
- Any CRG failure is caught, a warning is logged, and the pipeline continues
  exactly as before. The stage never raises.

## Capabilities

### New Capabilities

- `crg-context-enrichment`: Deterministic Tree-sitter static analysis of the PR
  working tree, producing change-impact data (changed functions, blast radius,
  affected flows, test gaps, risk scores) that is injected into the model prompt
  and saved as `crg-analysis.json`.

### Modified Capabilities

- `single-pi-reasoning`: The prompt prefix now includes CRG analysis when
  `crg_analysis` is present in `ctx.extras`. The diff and all other context are
  unchanged.

## Impact

- `src/reviewforge/artifacts/manager.py`: `ARTIFACT_NAMES` and `Artifacts` gain
  `crg-analysis.json` / `crg_analysis`.
- `src/reviewforge/config.py`: `crg_enabled` config field + `CRG_ENABLED` env
  var (both constructors).
- `src/reviewforge/pipeline/stages/enrich_with_crg.py`: new stage.
- `src/reviewforge/pipeline/stages/__init__.py`: import + pipeline insertion.
- `src/reviewforge/reasoning/single_pi.py`: `_build_single_pi_prefix` injects
  CRG analysis; `_format_crg_context` helper added.
- `pyproject.toml`: `[crg]` optional-dependency group.
- `docs/reference/environment-variables.md`: `CRG_ENABLED` documented.
- `tests/test_stages.py`: `EnrichWithCrgStage` unit tests added.
