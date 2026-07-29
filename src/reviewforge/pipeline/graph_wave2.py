"""Deterministic, best-effort CRG wave-two analyses."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any


def snapshot(store: Any) -> dict[str, Any]:
    from code_review_graph.graph_diff import take_snapshot
    data = take_snapshot(store)
    edges = data.get("edges", {})
    if isinstance(edges, set):
        data["edges"] = {edge: True for edge in sorted(edges)}
    return data


def diff_snapshots(base: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    bn, sn = base.get("nodes", {}), source.get("nodes", {})
    be, se = base.get("edges", {}), source.get("edges", {})
    added = sorted(set(sn) - set(bn))
    removed = sorted(set(bn) - set(sn))
    changed = sorted(name for name in set(bn) & set(sn) if bn[name] != sn[name])
    added_edges = sorted(set(se) - set(be))
    removed_edges = sorted(set(be) - set(se))
    return {
        "added_nodes": added[:50],
        "removed_nodes": removed[:50],
        "changed_nodes": changed[:50],
        "added_edges": added_edges[:50],
        "removed_edges": removed_edges[:50],
        "truncated": any(
            len(values) > 50
            for values in (added, removed, changed, added_edges, removed_edges)
        ),
    }


def api_surface(base: dict[str, Any], source: dict[str, Any], changed_files: list[str]) -> dict[str, Any]:
    del changed_files
    result = diff_snapshots(base, source)
    base_nodes, source_nodes = base.get("nodes", {}), source.get("nodes", {})
    watched = (
        (set(base_nodes) - set(source_nodes))
        | {
            name
            for name in set(base_nodes) & set(source_nodes)
            if base_nodes[name] != source_nodes[name]
        }
    )
    candidates: list[dict[str, Any]] = []
    for edge in source.get("edges", {}):
        parts = edge.split(":", 1)
        if len(parts) != 2 or parts[1] != "CALLS":
            continue
        endpoints = parts[0].split("->", 1)
        if len(endpoints) != 2 or endpoints[1] not in watched:
            continue
        candidate = next((item for item in candidates if item["symbol"] == endpoints[1]), None)
        if candidate is None:
            candidate = {
                "symbol": endpoints[1],
                "reason": "removed or changed node with surviving incoming call edges",
                "caller_count": 0,
            }
            candidates.append(candidate)
        candidate["caller_count"] += 1
    candidates.sort(key=lambda item: (item["symbol"], item["reason"]))
    if len(candidates) > 50:
        result["truncated"] = True
    result["breaking_candidates"] = candidates[:50]
    return result

def _flow_kind(flow: dict[str, Any], store: Any | None = None) -> str:
    flow = dict(flow)
    entry_point = flow.get("entry_point") or flow.get("name")
    get_node = getattr(store, "get_node", None)
    if callable(get_node) and entry_point:
        node = get_node(str(entry_point))
        if node is not None:
            flow.setdefault("entry_file", getattr(node, "file_path", ""))
            flow.setdefault("is_test", getattr(node, "is_test", False))
            flow.setdefault("decorators", getattr(node, "extra", {}).get("decorators", ""))
    entry = str(entry_point or "").lower()
    files = [str(path).lower() for path in flow.get("files", [])]
    file_path = str(flow.get("entry_file") or flow.get("file") or (files[0] if files else "")).lower()
    extra = str(flow.get("decorators") or flow.get("framework") or "").lower()
    if flow.get("is_test") or "test" in file_path or entry.split(".")[-1].startswith("test_"):
        return "test"
    if any(token in extra for token in ("route", "app.", "fastapi", "flask", "django")):
        return "http handler"
    if any(token in entry or token in file_path for token in ("cli", "command", "main")):
        return "cli"
    if any(token in entry or token in file_path for token in ("job", "task", "worker", "schedule", "cron")):
        return "job"
    return "other"


def _path_matches(path: str, changed_files: set[str]) -> bool:
    return any(path == changed or path.endswith("/" + changed) for changed in changed_files)


def flows(store: Any, changed_files: list[str]) -> dict[str, Any]:
    from code_review_graph.flows import compute_criticality, get_affected_flows, trace_flows
    changed = set(changed_files)
    affected_result = get_affected_flows(store, changed_files)
    affected = (
        affected_result.get("affected_flows", [])
        if isinstance(affected_result, dict)
        else affected_result
    )
    if not affected:
        affected = [
            flow
            for flow in trace_flows(store)
            if any(_path_matches(str(path), changed) for path in flow.get("files", []))
        ]
    adjacency = store.load_flow_adjacency()
    rows = []
    for flow in affected:
        if not isinstance(flow, dict):
            continue
        try:
            score = compute_criticality(flow, adjacency)
        except Exception:
            score = flow.get("criticality", 0.0)
        rows.append({
            "entry_point": str(flow.get("entry_point") or flow.get("name") or ""),
            "kind": _flow_kind(flow, store),
            "criticality": float(score or 0.0),
            "path_summary": str(flow.get("path", "")),
        })
    rows.sort(key=lambda item: (-item["criticality"], item["entry_point"]))
    return {"status": "ok", "affected_count": len(rows), "top": rows[:15]}


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


def build_base_snapshot(ctx: Any, tool_version: str) -> dict[str, Any]:
    from ..git.ops import run_git
    from code_review_graph.graph import GraphStore
    import code_review_graph.incremental as inc
    from ..runlog import info

    del tool_version
    base = getattr(ctx.state, "base_commit", "")
    if not base:
        raise ValueError("base commit unavailable")
    root = Path(
        getattr(ctx.cfg, "crg_cache_dir", None)
        or ctx.cfg.review_artifact_root / "graph-cache"
    )
    path = root / _safe(getattr(ctx.cfg, "ado_repo_id", "default")) / "base-snapshots" / f"{base}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        info(f"CRG base snapshot reused: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    worktree = Path(tempfile.mkdtemp(prefix="crg-base-"))
    graph_data_dir = Path(tempfile.mkdtemp(prefix="crg-base-graph-"))
    cleanup_paths = getattr(ctx.state, "cleanup_paths", None)
    if isinstance(cleanup_paths, list):
        for temp_path in (worktree, graph_data_dir):
            if temp_path not in cleanup_paths:
                cleanup_paths.append(temp_path)
    try:
        run_git(ctx.state.repo_dir, "worktree", "add", "--detach", str(worktree), base)
        store = GraphStore(graph_data_dir / "base.db")
        inc.full_build(worktree, store)
        data = snapshot(store)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        info(f"CRG base snapshot built: {path}")
        return data
    finally:
        try:
            run_git(ctx.state.repo_dir, "worktree", "remove", "--force", str(worktree), check=False)
        except Exception:
            pass
        shutil.rmtree(worktree, ignore_errors=True)
        shutil.rmtree(graph_data_dir, ignore_errors=True)


def _safe(value: str) -> str:
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in value) or "default"
