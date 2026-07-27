# Design

The installed `code-review-graph` package is version 2.3.7 with schema version 9. `graph_diff.take_snapshot(store)` returns node and edge counts plus `nodes` keyed by qualified name (`kind`, `file`, `community_id`) and `edges` keyed by `src->dst:kind`; it does not include function signatures, so this change does not claim signature detection.

The package exposes `detect_entry_points`, `trace_flows`, `compute_criticality`, `get_affected_flows`, `find_hub_nodes`, and `find_bridge_nodes`. Persisted flows are available through `get_flows`; the wave-two implementation also supports recomputation. Community IDs are read from the store. `communities.py` has an igraph-optional networkx/file fallback; missing optional community support degrades the architecture feature and does not add igraph.

A base graph is built in a disposable git worktree and temporary database, then its immutable snapshot is cached by base SHA under `base-snapshots`. Each feature has an isolated exception boundary and duration detail. Snapshot arithmetic is deterministic and capped.
