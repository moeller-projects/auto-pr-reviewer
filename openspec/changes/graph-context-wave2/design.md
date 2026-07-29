# Design

The installed `code-review-graph` package is version 2.3.7 with schema version 9.
`graph_diff.take_snapshot(store)` returns `node_count`, `edge_count`, a
`nodes` mapping keyed by qualified name, and an `edges` set of
`src->dst:kind` strings. Node payloads include kind, file, and community id.
ReviewForge normalizes the edge set to a deterministic JSON object before
caching. The snapshot does not include function signatures or a before/after
source body, so this change detects node/edge additions, removals, and changed
node metadata only; it does not claim signature-change detection.

`detect_entry_points`, `trace_flows`, `compute_criticality`, and
`get_affected_flows` provide flow data. Cached builds call the package's
normal `full_build`/`incremental_update` APIs without a flow-skipping option.
Absent flow tables or APIs degrade only the flows section. Entry points are
classified deterministically as `http handler`, `cli`, `job`, `test`, or
`other`, then sorted by descending criticality and entry-point name.

The source graph remains in the warm per-repository SQLite cache. An API base
snapshot is built from a detached git worktree and a separate temporary graph
database, then cached as
`graph-cache/<repo-slug>/base-snapshots/<base-sha>.json`; neither temporary
directory is created under the warm cache. Worktree and graph-data paths are
registered in `RepoState.cleanup_paths` and removed in the build `finally`
block. Snapshot arithmetic is deterministic and capped at 50 entries.

Architecture facts filter hubs and bridges against changed nodes only.
Community counts use changed nodes plus incoming `CALLS` callers. The
code-review-graph community implementation uses its networkx/file fallback
when igraph is unavailable; this repository does not add igraph.
