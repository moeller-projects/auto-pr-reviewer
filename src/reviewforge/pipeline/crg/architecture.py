"""CRG architecture analysis."""
from __future__ import annotations

from typing import Any


def architecture(store: Any, changed_files: list[str]) -> dict[str, Any]:
    from code_review_graph.analysis import find_bridge_nodes, find_hub_nodes
    changed = set(changed_files)

    def is_changed(item: dict[str, Any]) -> bool:
        path = str(item.get("file") or item.get("file_path") or "")
        return any(path.endswith(file) for file in changed)

    hubs = [item for item in find_hub_nodes(store, 50) if is_changed(item)]
    bridges = [item for item in find_bridge_nodes(store, 50) if is_changed(item)]
    communities = store.get_all_community_ids()
    changed_nodes = {
        node.qualified_name
        for node in store.get_all_nodes(exclude_files=True)
        if any(str(node.file_path).endswith(file) for file in changed)
    }
    related_nodes = set(changed_nodes)
    for edge in store.get_all_edges():
        if edge.target_qualified in changed_nodes and edge.kind == "CALLS":
            related_nodes.add(edge.source_qualified)
    community_ids = {communities.get(name) for name in related_nodes} - {None}
    labels = {str(value): "community-" + str(value) for value in sorted(community_ids)}
    return {
        "status": "ok",
        "hubs_touched": sorted(hubs, key=lambda item: item.get("qualified_name", "")),
        "bridges_touched": sorted(bridges, key=lambda item: item.get("qualified_name", "")),
        "communities_crossed": len(community_ids),
        "community_labels": labels,
    }
