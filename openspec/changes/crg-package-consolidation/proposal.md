## Why

CRG implementation is split across a temporally named stage module, a pipeline-level wave-two module, and the single-Pi engine. This makes the feature harder to navigate and leaves base-snapshot cache versioning incomplete.

## What Changes

- Consolidate CRG orchestration, analysis projections, snapshots, flows, architecture, and prompt assembly under `reviewforge.pipeline.crg`.
- Keep generic single-Pi section rendering and UTF-8 byte-cap helpers in `single_pi.py`; move only CRG-specific assembly.
- Update internal imports and remove the obsolete scattered CRG modules without changing shipped contracts.
- Key base snapshots by CRG tool version so upgrades perform one cold build per version.
- Add relocation-boundary and cache-key regression coverage.

## Capabilities

### New Capabilities

- `crg-package-consolidation`: Internal CRG package layout and version-qualified base-snapshot caching.

### Modified Capabilities

None. This change preserves all operator-visible configuration, artifacts, markers, and stage names.

## Impact

- Python module paths under `reviewforge.pipeline.crg` are consolidated.
- Existing CRG tests and imports are updated to the new internal paths.
- Old base-snapshot cache files are intentionally not migrated; they are disposable cache entries.
