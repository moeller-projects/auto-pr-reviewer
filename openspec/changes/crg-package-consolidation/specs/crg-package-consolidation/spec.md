## ADDED Requirements

### Requirement: CRG implementation is feature-packaged

The implementation MUST keep CRG stage orchestration, analysis projections, snapshot helpers, flow helpers, architecture helpers, and CRG prompt assembly under `reviewforge.pipeline.crg`, while generic single-Pi section rendering and byte-cap helpers remain in `single_pi.py`.

#### Scenario: Package exports the registered stage

- **WHEN** a caller imports `EnrichWithCrgStage` from `reviewforge.pipeline.crg` and from `reviewforge.pipeline.stages`
- **THEN** both imports MUST resolve to the same class object.

#### Scenario: Relocation preserves prompt bytes

- **WHEN** CRG is disabled and the single-Pi prefix is built with the same context
- **THEN** the instruction MUST remain byte-identical to the pre-consolidation output.

### Requirement: Base snapshots are version-qualified

`build_base_snapshot` MUST cache each base snapshot under `<cache-root>/<repo>/base-snapshots/crg-<tool_version>/<sha>.json` and MUST NOT migrate older unversioned cache files.

#### Scenario: Different tool versions build distinct snapshots

- **WHEN** the same base commit is requested with two different CRG tool versions
- **THEN** two distinct cache files MUST be created and both requests MUST perform cold builds.

#### Scenario: Same tool version reuses its snapshot

- **WHEN** the same base commit is requested twice with the same CRG tool version
- **THEN** the second request MUST reuse the versioned cache file without another build.
