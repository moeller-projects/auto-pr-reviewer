"""Stage: enrich context with a Tree-sitter code-review graph (CRG).

Runs between :class:`PrepareRepositoryStage` and
:class:`ExecuteReasoningEngineStage`. Uses the optional ``code-review-graph``
PyPI package to build a lightweight SQLite knowledge graph from the
checked-out working tree, then analyses which functions were changed, their
blast radius, affected flows, test gaps, and risk scores.

The result is stored in ``ctx.extras["crg_analysis"]`` so that
:func:`~reviewforge.reasoning.single_pi._build_single_pi_prefix` can
forward it as structured context to the model. It is also written as
``crg-analysis.json`` in the run artifact directory.

The graph DB is stored at
``<cache-root>/<repo_id>/crg-<tool_version>/crg.db`` and **persisted
across runs**. The cache root defaults to
``<review_artifact_root>/crg-cache`` (inside the artifact volume) and can
be redirected with ``CRG_CACHE_DIR`` (e.g. a dedicated cache volume). The
tool version is part of the path, so a CRG upgrade triggers exactly one
cold rebuild instead of reusing an incompatible graph.

On the first run for a repository (no DB file yet) a full build is
performed (~10 s per 500 files). On subsequent runs an incremental update
(<2 s, SHA-256-based) re-parses only the PR's changed files and their
dependents; the changed-file list comes from the pipeline, not from a git
base guess, so shallow checkouts cannot silently degrade the warm path.
The stage falls back to a full build if ``incremental_update`` is absent
or raises.

This stage MUST NOT raise on any CRG failure. Any error degrades
gracefully to today's behavior: a warning is logged, ``crg-analysis.json``
is written with ``status: "failed"``, and the pipeline continues.
"""
from __future__ import annotations

import json
import re
import time
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from ...runlog import info as _log, warning as log_warning
from ..stage import Stage, StageContext

_CRG_DISTRIBUTION = "code-review-graph"


class EnrichWithCrgStage(Stage):
    """Build a Tree-sitter knowledge graph and analyse the PR diff."""

    name = "enrich_with_crg"

    def should_run(self, ctx: StageContext) -> bool:
        if not ctx.cfg.crg_enabled:
            return False
        if getattr(ctx.extras.get("review_state"), "mode", None) == "no_op":
            return False
        if ctx.state is None or not getattr(ctx.state, "repo_dir", None):
            return False
        return True

    def run(self, ctx: StageContext) -> dict[str, Any]:  # noqa: PLR0912 - graceful-degrade
        repo_dir: Path = ctx.state.repo_dir
        changed_files: list[str] = list(getattr(ctx.state, "files", []))
        range_spec: str = getattr(ctx.state, "range_spec", "")

        try:
            from code_review_graph.graph import GraphStore
            import code_review_graph.incremental as _crg_inc
            from code_review_graph.changes import analyze_changes, parse_git_diff_ranges
        except ImportError:
            log_warning(
                "CRG enrichment skipped: 'code-review-graph' package is not installed. "
                "Install it with: pip install code-review-graph"
            )
            _write_failure_document(ctx, tool_version=None, error="package unavailable")
            return {"crg_status": "package_unavailable"}

        tool_version = "unknown"
        build_mode = "full"
        build_duration_ms = 0
        node_count = 0
        try:
            tool_version = _crg_version()
            db_path = _crg_db_path(ctx, tool_version)
            # Decide cold vs warm BEFORE constructing GraphStore: opening the
            # SQLite database creates the file eagerly, so an existence check
            # afterwards would always report "warm" and the cold full build
            # would never run.
            db_existed = db_path.exists()
            store = GraphStore(db_path)
            incremental_update = getattr(_crg_inc, "incremental_update", None)
            started = time.monotonic()
            if db_existed and incremental_update is not None:
                try:
                    # Pass the PR's changed files explicitly. The package
                    # default diffs against HEAD~1, which is unreliable in
                    # our shallow, detached checkouts and silently re-parses
                    # the wrong file set.
                    build_result = incremental_update(repo_dir, store, changed_files=changed_files)
                    build_mode = "incremental"
                except Exception as exc:  # noqa: BLE001
                    log_warning(
                        f"CRG incremental update failed ({type(exc).__name__}: {exc}); "
                        "falling back to full build"
                    )
                    build_result = _crg_inc.full_build(repo_dir, store)
                    build_mode = "full"
            else:
                build_result = _crg_inc.full_build(repo_dir, store)
                build_mode = "full"
            build_duration_ms = int((time.monotonic() - started) * 1000)
            node_count = (
                build_result.get("nodes", build_result.get("total_nodes", 0))
                if isinstance(build_result, dict)
                else 0
            )
            _log(f"CRG graph {build_mode} build: {node_count} nodes from {repo_dir}")
        except Exception as exc:  # noqa: BLE001
            log_warning(f"CRG graph build failed ({type(exc).__name__}: {exc}); skipping enrichment")
            _write_failure_document(ctx, tool_version=tool_version, error=str(exc))
            return {"crg_status": "build_failed", "crg_error": str(exc)}

        try:
            # Parse line ranges from the diff so CRG can pinpoint changed nodes
            # precisely. Pass the range_spec (e.g. "abc..def") as the git base.
            # Absolute paths are required by analyze_changes for correct lookup.
            root_str = str(repo_dir)
            if range_spec:
                raw_ranges = parse_git_diff_ranges(root_str, range_spec)
                # Remap relative keys to absolute paths for GraphStore lookups.
                changed_ranges: dict[str, list[tuple[int, int]]] | None = {
                    str(repo_dir / key): ranges
                    for key, ranges in raw_ranges.items()
                }
            else:
                changed_ranges = None

            abs_changed_files = [
                str(repo_dir / f) if not Path(f).is_absolute() else f
                for f in changed_files
            ]
            analysis = analyze_changes(
                store,
                abs_changed_files,
                changed_ranges=changed_ranges,
                repo_root=root_str,
            )
            if not isinstance(analysis, dict):
                raise ValueError("CRG analysis returned a non-object payload")
        except Exception as exc:  # noqa: BLE001
            log_warning(f"CRG analysis failed ({type(exc).__name__}: {exc}); skipping enrichment")
            _write_failure_document(ctx, tool_version=tool_version, error=str(exc))
            return {"crg_status": "analysis_failed", "crg_error": str(exc)}

        status = "degraded" if analysis.get("functions_truncated") else "ok"
        document = _build_document(
            analysis,
            status=status,
            tool_version=tool_version,
            build={"mode": build_mode, "duration_ms": build_duration_ms},
            repo_root=str(repo_dir),
        )
        # Wave-two analyses are deliberately isolated: a missing optional API
        # or a malformed graph can only degrade its own context section.
        graph_context = dict(document)
        details: dict[str, Any] = {}
        if getattr(ctx.cfg, "graph_api_diff", False):
            started = time.monotonic()
            try:
                from ..graph_wave2 import api_surface, build_base_snapshot, snapshot
                base_snapshot = build_base_snapshot(ctx, tool_version)
                graph_context["api_surface"] = {"status": "ok", "base_commit": getattr(ctx.state, "base_commit", ""), **api_surface(base_snapshot, snapshot(store), changed_files)}
            except Exception as exc:  # noqa: BLE001
                log_warning(f"CRG API-surface analysis degraded ({type(exc).__name__}: {exc})")
                graph_context["api_surface"] = {"status": "degraded", "base_commit": getattr(ctx.state, "base_commit", ""), "error": str(exc)}
            details["graph_api_diff_ms"] = int((time.monotonic() - started) * 1000)
        if getattr(ctx.cfg, "graph_flows", False):
            started = time.monotonic()
            try:
                from ..graph_wave2 import flows
                graph_context["flows"] = flows(store, changed_files)
            except Exception as exc:  # noqa: BLE001
                log_warning(f"CRG flow analysis degraded ({type(exc).__name__}: {exc})")
                graph_context["flows"] = {"status": "degraded", "affected_count": 0, "top": [], "error": str(exc)}
            details["graph_flows_ms"] = int((time.monotonic() - started) * 1000)
        if getattr(ctx.cfg, "graph_arch", False):
            started = time.monotonic()
            try:
                from ..graph_wave2 import architecture
                graph_context["architecture"] = architecture(store, changed_files)
            except Exception as exc:  # noqa: BLE001
                log_warning(f"CRG architecture analysis degraded ({type(exc).__name__}: {exc})")
                graph_context["architecture"] = {"status": "degraded", "hubs_touched": [], "bridges_touched": [], "communities_crossed": 0, "community_labels": {}, "error": str(exc)}
            details["graph_arch_ms"] = int((time.monotonic() - started) * 1000)
        try:
            _write_artifact(ctx, document)
        except Exception as exc:  # noqa: BLE001
            log_warning(f"CRG artifact write failed ({type(exc).__name__}: {exc}); continuing without artifact")
        try:
            _write_graph_context(ctx, graph_context)
        except Exception as exc:  # noqa: BLE001
            log_warning(f"Graph-context artifact write failed ({type(exc).__name__}: {exc}); continuing without artifact")

        ctx.extras["crg_analysis"] = document
        ctx.extras["graph_context"] = graph_context
        _log(
            f"CRG enrichment complete: risk_score={document['risk_score']:.2f}, "
            f"changed_functions={len(document['changed_functions'])}, "
            f"test_gaps={len(document['test_gaps'])}"
        )
        return {
            "crg_status": status,
            "crg_build_mode": build_mode,
            "crg_nodes": node_count,
            "crg_risk_score": document["risk_score"],
            "crg_changed_functions": len(document["changed_functions"]),
            "crg_test_gaps": len(document["test_gaps"]),
            **details,
        }


def _crg_version() -> str:
    """Return the installed ``code-review-graph`` version (``unknown`` fallback)."""
    try:
        return importlib_metadata.version(_CRG_DISTRIBUTION)
    except importlib_metadata.PackageNotFoundError:
        return "unknown"


def _crg_db_path(ctx: StageContext, tool_version: str) -> Path:
    """Return the persistent per-repo SQLite path for the CRG graph.

    Stored at ``<cache-root>/<repo_id>/crg-<tool_version>/crg.db`` and
    shared across all runs for the same repository. The cache root is
    ``CRG_CACHE_DIR`` when configured, otherwise
    ``<review_artifact_root>/crg-cache`` — both live on persistent volumes,
    never under the per-run artifact dir or the disposable repo checkout.
    The tool version in the path guarantees a cold rebuild after a CRG
    upgrade. The directory is created eagerly so that ``GraphStore`` can
    open the file on first use.
    """
    repo_id = _safe_repo_id(ctx.cfg.ado_repo_id or "default")
    override = getattr(ctx.cfg, "crg_cache_dir", None)
    root = Path(override) if override else ctx.cfg.review_artifact_root / "crg-cache"
    cache_dir = root / repo_id / f"crg-{tool_version}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "crg.db"


def _safe_repo_id(repo_id: str) -> str:
    """Sanitise *repo_id* so it is safe to use as a directory name."""
    sanitised = re.sub(r"[^\w-]", "_", repo_id)
    return sanitised or "default"


def _strip_root(value: Any, repo_root: str) -> Any:
    """Strip the disposable absolute checkout prefix from analysis strings."""
    prefix = repo_root + "/"
    if isinstance(value, str):
        return value.removeprefix(prefix) if value.startswith(prefix) else value
    if isinstance(value, list):
        return [_strip_root(item, repo_root) for item in value]
    if isinstance(value, dict):
        return {key: _strip_root(item, repo_root) for key, item in value.items()}
    return value


def _entry_file(item: dict[str, Any]) -> str | None:
    """Return an entry's file; CRG node payloads use ``file_path``."""
    path = item.get("file_path") or item.get("file")
    return str(path) if path else None


def _impacted_files(analysis: dict[str, Any]) -> list[str]:
    """Return the sorted unique file set touched by the analysis."""
    files: set[str] = set()
    for key in ("changed_functions", "review_priorities", "test_gaps"):
        for item in analysis.get(key) or []:
            if isinstance(item, dict):
                path = _entry_file(item)
                if path:
                    files.add(path)
    return sorted(files)


def _base_document(tool_version: str | None) -> dict[str, Any]:
    return {
        "status": "failed",
        "tool_version": tool_version,
        "build": {"mode": "none", "duration_ms": 0},
        "summary": "",
        "risk_score": 0.0,
        "changed_functions": [],
        "affected_flows": [],
        "test_gaps": [],
        "impacted_files": [],
        "review_priorities": [],
    }


def _build_document(
    analysis: dict[str, Any],
    *,
    status: str,
    tool_version: str,
    build: dict[str, Any],
    repo_root: str,
) -> dict[str, Any]:
    """Compose the canonical ``crg-analysis.json`` document."""
    document = _base_document(tool_version)
    document.update(
        status=status,
        build=build,
        summary=analysis.get("summary", ""),
        risk_score=analysis.get("risk_score", 0.0),
        changed_functions=analysis.get("changed_functions", []),
        affected_flows=analysis.get("affected_flows", []),
        test_gaps=analysis.get("test_gaps", []),
        impacted_files=_impacted_files(analysis),
        review_priorities=analysis.get("review_priorities", []),
    )
    if analysis.get("functions_truncated"):
        document["functions_truncated"] = True
    return _strip_root(document, repo_root)


def _write_failure_document(ctx: StageContext, *, tool_version: str | None, error: str) -> None:
    """Best-effort ``status: "failed"`` artifact so operators can see the miss."""
    document = _base_document(tool_version)
    document["error"] = error
    try:
        _write_artifact(ctx, document)
    except Exception as exc:  # noqa: BLE001
        log_warning(f"CRG failure artifact write failed ({type(exc).__name__}: {exc})")
    try:
        _write_graph_context(ctx, document)
    except Exception as exc:  # noqa: BLE001
        log_warning(f"Graph-context failure artifact write failed ({type(exc).__name__}: {exc})")


def _write_artifact(ctx: StageContext, document: dict[str, Any]) -> None:
    """Serialise ``document`` to the ``crg-analysis.json`` artifact."""
    ctx.artifacts.crg_analysis.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )



def _write_graph_context(ctx: StageContext, document: dict[str, Any]) -> None:
    """Write the additive graph-context projection."""
    ctx.artifacts.graph_context.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
__all__ = ["EnrichWithCrgStage"]
