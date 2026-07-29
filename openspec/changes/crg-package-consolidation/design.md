## Context

CRG currently spans `pipeline/stages/enrich_with_crg.py`, `pipeline/graph_wave2.py`, and CRG-specific formatting in `reasoning/single_pi.py`. The feature has one stage, several analysis projections, and one prompt boundary, so a feature package is the smallest coherent ownership boundary.

## Design

### Module mapping

| New module | Moved contents |
| --- | --- |
| `pipeline/crg/__init__.py` | `EnrichWithCrgStage` export only |
| `pipeline/crg/stage.py` | `EnrichWithCrgStage`, `_crg_version`, `_crg_db_path`, cache/orchestration helpers |
| `pipeline/crg/analysis.py` | `_build_document`, `_write_artifact`, `_write_graph_context`, `_write_failure_document`, and their private shaping helpers |
| `pipeline/crg/snapshots.py` | `snapshot`, `diff_snapshots`, `api_surface`, `build_base_snapshot`, `_safe` |
| `pipeline/crg/flows.py` | `flows`, `_flow_kind`, `_path_matches` |
| `pipeline/crg/architecture.py` | `architecture` |
| `pipeline/crg/prompt.py` | CRG and wave-two prompt-section assembly; generic `render_section` and `_byte_cap_with_pointer` remain in `single_pi.py` |

The package exports only `EnrichWithCrgStage`. No public-surface reference to the old modules was found in `docs/reference/public-api.md` or package exports, so no compatibility alias modules are retained.

### Base-snapshot cache key

`build_base_snapshot` writes to:

`<cache-root>/<repo>/base-snapshots/crg-<tool_version>/<sha>.json`

The tool version is part of the path because snapshots are derived from the installed CRG graph schema and algorithms. The old unversioned files are cache entries, not artifacts or data contracts; no migration is added. A version bump simply builds once cold in its new directory, then reuses that versioned snapshot.

### Compatibility

The relocation preserves `CRG_ENABLED`, `CRG_CACHE_DIR`, `GRAPH_API_DIFF`, `GRAPH_FLOWS`, `GRAPH_ARCH`, `crg-analysis.json`, `graph-context.json`, `.reviewforge-context`, `ARTIFACT_NAMES`, and the `enrich_with_crg` stage name. Prompt output and artifact JSON remain byte-identical for unchanged inputs.
