"""CRG critical-flow analysis."""
from __future__ import annotations

from typing import Any


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
