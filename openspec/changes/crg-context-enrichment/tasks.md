## 1. Stage and Pipeline

- [x] 1.1 Add `EnrichWithCrgStage` between `PrepareRepositoryStage` and `ExecuteReasoningEngineStage` in all four engine pipelines
- [x] 1.2 Gate on `CRG_ENABLED` and `no_op` review mode; never raise on CRG failure
- [x] 1.3 Persist graph DB at `<cache-root>/<repo_id>/crg-<tool_version>/crg.db`; cold `full_build` once, warm `incremental_update` with explicit changed files
- [x] 1.4 Write `crg-analysis.json` (canonical status/tool_version/build document) on success and failure

## 2. Configuration and Packaging

- [x] 2.1 Add `crg_enabled`, `crg_cache_dir`, `crg_context_max_bytes` config fields with `CRG_ENABLED`/`CRG_CACHE_DIR`/`CRG_CONTEXT_MAX_BYTES` env resolution in both constructors
- [x] 2.2 Pin `code-review-graph==2.3.7` in the `crg` extra and lock it in `uv.lock`
- [x] 2.3 Install the `crg` extra in the container image and mount the dedicated `reviewforge-crg-cache` volume with `CRG_CACHE_DIR`

## 3. Prompt Integration

- [x] 3.1 Inject the deterministic graph-context section into the single-pi prefix on `ok`/`degraded` only, with caps, deterministic ordering, and the byte cap
- [x] 3.2 Document the section in `prompts/fast-review-system.md` without touching the output contract

## 4. Verification

- [x] 4.1 Add stage tests: gates, failure paths, cold/warm selection, version-bump rebuild, cache survival, artifact contract, determinism
- [x] 4.2 Add prompt-injection tests: byte-identity, caps, ordering, byte cap, chunk-1-only placement
- [x] 4.3 Add config and container-run construction tests for the new env vars and volume
- [x] 4.4 Update docs (pipeline, artifacts, environment variables, ai, operations) and CHANGELOG
