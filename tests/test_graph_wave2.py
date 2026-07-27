from reviewforge.pipeline.graph_wave2 import api_surface, diff_snapshots


def test_snapshot_diff_is_sorted_and_capped():
    base = {"nodes": {"b": {}, "a": {}}, "edges": {"a->b:CALLS": 1}}
    source = {"nodes": {"a": {}, "c": {}}, "edges": {"c->a:CALLS": 1}}
    result = diff_snapshots(base, source)
    assert result["added_nodes"] == ["c"]
    assert result["removed_nodes"] == ["b"]
    assert result["added_edges"] == ["c->a:CALLS"]
    assert result["removed_edges"] == ["a->b:CALLS"]


def test_api_surface_marks_public_removed_symbols():
    base = {"nodes": {"pkg.api": {"file": "pkg/api.py"}}, "edges": {}}
    source = {"nodes": {}, "edges": {}}
    result = api_surface(base, source, ["pkg/api.py"])
    assert result["breaking_candidates"][0]["symbol"] == "pkg.api"
