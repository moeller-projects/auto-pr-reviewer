"""Deterministic, best-effort CRG wave-two analyses."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any


def snapshot(store: Any) -> dict[str, Any]:
    from code_review_graph.graph_diff import take_snapshot
    return take_snapshot(store)


def diff_snapshots(base: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    bn, sn = base.get("nodes", {}), source.get("nodes", {})
    be, se = base.get("edges", {}), source.get("edges", {})
    added = sorted(set(sn) - set(bn))
    removed = sorted(set(bn) - set(sn))
    return {
        "added_nodes": added[:50], "removed_nodes": removed[:50],
        "added_edges": sorted(set(se) - set(be))[:50],
        "removed_edges": sorted(set(be) - set(se))[:50],
        "truncated": any(len(x) > 50 for x in (set(sn)-set(bn), set(bn)-set(sn), set(se)-set(be), set(be)-set(se))),
    }


def api_surface(base: dict[str, Any], source: dict[str, Any], changed_files: list[str]) -> dict[str, Any]:
    result = diff_snapshots(base, source)
    source_nodes = source.get("nodes", {})
    removed = set(result["removed_nodes"])
    callers: dict[str, int] = {n: 0 for n in removed}
    for edge in source.get("edges", {}):
        parts = edge.split(":", 1)[0].split("->", 1)
        if len(parts) == 2 and parts[1] in callers:
            callers[parts[1]] += 1
    candidates = []
    for name in sorted(removed):
        if callers.get(name, 0):
            candidates.append({"symbol": name, "reason": "removed node with incoming call edges", "caller_count": callers[name]})
    base_nodes = base.get("nodes", {})
    for name in sorted(removed):
        node = base_nodes.get(name, {})
        if node.get("file", "") and not str(node.get("file", "")).startswith("test") and not name.rsplit(".", 1)[-1].startswith("_"):
            candidates.append({"symbol": name, "reason": "removed public-looking symbol", "caller_count": callers.get(name, 0)})
    result["breaking_candidates"] = sorted({json.dumps(x, sort_keys=True): x for x in candidates}.values(), key=lambda x: x["symbol"])[:50]
    return result


def flows(store: Any, changed_files: list[str]) -> dict[str, Any]:
    from code_review_graph.flows import compute_criticality, detect_entry_points, get_affected_flows, trace_flows
    entries = detect_entry_points(store)
    try:
        affected = get_affected_flows(store, changed_files)
    except Exception:
        affected = []
    rows = []
    for flow in affected:
        try:
            score = compute_criticality(flow, {})
        except Exception:
            score = flow.get("criticality", 0.0) if isinstance(flow, dict) else 0.0
        name = flow.get("entry_point") or flow.get("name") or ""
        rows.append({"entry_point": str(name), "kind": "other", "criticality": float(score), "path_summary": str(flow.get("path", ""))})
    if not rows:
        for entry in entries:
            try:
                flow = trace_flows(store, entry)
                score = compute_criticality(flow, {})
            except Exception:
                continue
            files = {str(getattr(entry, "file_path", ""))}
            if files & set(changed_files):
                rows.append({"entry_point": str(getattr(entry, "qualified_name", "")), "kind": "other", "criticality": float(score), "path_summary": str(flow)})
    rows.sort(key=lambda x: (-x["criticality"], x["entry_point"]))
    return {"status": "ok", "affected_count": len(rows), "top": rows[:15]}


def architecture(store: Any, changed_files: list[str]) -> dict[str, Any]:
    from code_review_graph.analysis import find_bridge_nodes, find_hub_nodes
    hubs = [x for x in find_hub_nodes(store, 50) if any(str(x.get("file", "")).endswith(str(f)) for f in changed_files)]
    bridges = [x for x in find_bridge_nodes(store, 50) if any(str(x.get("file", "")).endswith(str(f)) for f in changed_files)]
    communities = store.get_all_community_ids()
    changed_nodes = {
        n.qualified_name for n in store.get_all_nodes(exclude_files=True)
        if any(str(getattr(n, "file_path", "")).endswith(str(f)) for f in changed_files)
    }
    crossed: set[tuple[Any, Any]] = set()
    for edge in store.get_all_edges():
        if edge.source_qualified in changed_nodes or edge.target_qualified in changed_nodes:
            left, right = communities.get(edge.source_qualified), communities.get(edge.target_qualified)
            if left is not None and right is not None and left != right:
                crossed.add((left, right))
    changed_ids = {communities.get(x.get("qualified_name")) for x in hubs + bridges} - {None}
    labels = {str(x): "community-" + str(x) for x in sorted(changed_ids)}
    return {"status": "ok", "hubs_touched": sorted(hubs, key=lambda x: x.get("qualified_name", "")), "bridges_touched": sorted(bridges, key=lambda x: x.get("qualified_name", "")), "communities_crossed": len(crossed), "community_labels": labels}


def build_base_snapshot(ctx: Any, tool_version: str) -> dict[str, Any]:
    from ...git.ops import run_git
    from code_review_graph.graph import GraphStore
    import code_review_graph.incremental as inc
    base = getattr(ctx.state, "base_commit", "")
    if not base:
        raise ValueError("base commit unavailable")
    root = Path(getattr(ctx.cfg, "crg_cache_dir", None) or ctx.cfg.review_artifact_root / "crg-cache")
    path = root / _safe(getattr(ctx.cfg, "ado_repo_id", "default")) / f"crg-{tool_version}" / "base-snapshots" / f"{base}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    worktree = Path(tempfile.mkdtemp(prefix="crg-base-", dir=str(path.parent)))
    db = worktree / "base.db"
    try:
        run_git(ctx.state.repo_dir, "worktree", "add", "--detach", str(worktree), base)
        store = GraphStore(db)
        inc.full_build(worktree, store)
        data = snapshot(store)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        return data
    finally:
        try:
            run_git(ctx.state.repo_dir, "worktree", "remove", "--force", str(worktree), check=False)
        except Exception:
            pass
        shutil.rmtree(worktree, ignore_errors=True)


def _safe(value: str) -> str:
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in value) or "default"
