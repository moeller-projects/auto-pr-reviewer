"""Stage: answer unanswered human replies on bot comment threads.

Detects bot-marked threads whose last comment is human-authored, drafts a
reply per thread with the configured model runner (reusing the Pi session so
the model retains its review context), validates the output, and appends each
reply to its existing thread. Under ``dry_run`` the replies are printed and
recorded but never posted.
"""
from __future__ import annotations

import json
from typing import Any

from ...ado.client import AdoClient
from ...ado.posting import find_awaiting_replies
from ...artifacts.builder import write_json
from ...exceptions import ReviewForgeError
from ...runlog import info as _log
from ..schemas import CommentReplies, load_and_validate
from ..stage import Stage, StageContext


def _build_client(cfg: Any) -> AdoClient:
    return AdoClient(
        cfg.ado_org,
        cfg.ado_project,
        cfg.ado_repo_id,
        token=cfg.ado_token,
        retry_attempts=cfg.ado_retry_attempts,
        retry_base_delay=cfg.ado_retry_base_delay,
        retry_cap_delay=cfg.ado_retry_cap_delay,
        retry_budget_secs=cfg.ado_retry_budget_secs,
    )


def _thread_payload(thread: dict[str, Any]) -> dict[str, Any]:
    ctx = thread.get("threadContext") or {}
    return {
        "thread_id": thread.get("id"),
        "file": ctx.get("filePath"),
        "line": (ctx.get("rightFileStart") or {}).get("line"),
        "status": thread.get("status") or "",
        "comments": [
            {
                "author": (c.get("author") or {}).get("displayName")
                if isinstance(c.get("author"), dict)
                else str(c.get("author") or ""),
                "content": c.get("content") or "",
            }
            for c in thread.get("comments") or []
        ],
    }


class ReplyToCommentsStage(Stage):
    """Generate and post replies to unanswered human comments on bot threads."""

    name = "reply_to_comments"

    def should_run(self, ctx: StageContext) -> bool:
        return bool(ctx.cfg.reply_comments)

    def run(self, ctx: StageContext) -> dict[str, Any]:
        cfg = ctx.cfg
        client = _build_client(cfg)
        pending = find_awaiting_replies(client.get_threads(cfg.pr_id))
        if not pending:
            write_json(ctx.artifacts.comment_replies, {"replies": []})
            return {"awaiting": 0, "replied": 0}

        _log(f"{len(pending)} bot thread(s) awaiting a reply")
        payload = json.dumps(
            [_thread_payload(t) for t in pending], ensure_ascii=False, indent=2
        )
        raw_path = ctx.artifacts.raw_dir / "comment-replies.json"
        ctx.pi.run_json(cfg.comment_reply_prompt_path, payload, raw_path, "comment reply")
        result = load_and_validate(raw_path, CommentReplies)
        known_ids = {t.get("id") for t in pending}
        replies: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for item in result.replies:
            body = item.reply.strip()
            if item.thread_id not in known_ids or not body or item.thread_id in seen_ids:
                continue
            seen_ids.add(item.thread_id)
            replies.append({"thread_id": item.thread_id, "reply": body, "posted": False})
        dropped = len(result.replies) - len(replies)
        if dropped:
            _log(f"dropped {dropped} invalid reply/replies (unknown thread or empty body)")

        posted = 0
        failed = 0
        try:
            if cfg.dry_run:
                _log("DRY_RUN=1; printing replies (not posting)")
                if ctx.extras.get("explicit_reply_command"):
                    print(json.dumps({"replies": replies}, ensure_ascii=False, indent=2))
            else:
                for entry in replies:
                    try:
                        client.add_comment(cfg.pr_id, entry["thread_id"], entry["reply"])
                    except ReviewForgeError as exc:
                        failed += 1
                        entry["error"] = str(exc)
                        _log(f"reply to thread {entry['thread_id']} failed: {exc}")
                    else:
                        entry["posted"] = True
                        posted += 1
                _log(f"posted {posted} reply/replies on PR #{cfg.pr_id}")
        finally:
            write_json(ctx.artifacts.comment_replies, {"replies": replies})
        if failed:
            _log(f"{failed} reply/replies failed after ADO retries")
        return {"awaiting": len(pending), "replied": posted}


__all__ = ["ReplyToCommentsStage"]
