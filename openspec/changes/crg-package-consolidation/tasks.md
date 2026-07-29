## 1. Relocation

- [x] 1.1 Create `pipeline.crg` and split stage, analysis, snapshot, flow, architecture, and prompt modules.
- [x] 1.2 Update stage registration and single-Pi imports; remove obsolete modules without shims.
- [x] 1.3 Preserve the CRG package export boundary and shipped contracts.

## 2. Cache correction

- [x] 2.1 Include `crg-<tool_version>` in the base-snapshot cache path.
- [x] 2.2 Leave old unversioned cache entries unmigrated.

## 3. Documentation and tests
- [x] 3.1 Add import-boundary and version-key regression coverage.
- [x] 3.2 Update architecture, API, changelog, and verification-report layout notes.
- [x] 3.3 Run focused CRG tests and the full pytest suite.
- [x] 3.4 Validate this OpenSpec change.
