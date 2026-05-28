#!/usr/bin/env python3
"""Stop hook: soft reminder when a session ends with unfinished review work.

Covers two distinct conditions, either of which fires a reminder:

* ``state.pending`` is non-empty — at least one previously-blocked artifact
  has not yet been reviewed (any kind: spec, plan, or code).
* The current staged diff is above the code-gate threshold AND its SHA does
  not match ``code_reviewed_sha`` AND no matching code pending entry exists —
  i.e. the user has accumulated commit-worthy changes that have not yet hit
  the gate.

Both conditions are checked; one composite reminder is emitted to stderr.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _state import (  # noqa: E402
    GitError,
    load_settings,
    load_state,
    read_hook_input,
    sha256,
    significant_change_stats,
    staged_diff,
)


def _pending_summary(state: dict) -> str:
    pending = state.get("pending") or []
    if not pending:
        return ""
    counts = Counter(e.get("kind", "?") for e in pending)
    parts = [f"{n} {k}" for k, n in sorted(counts.items())]
    return f"{sum(counts.values())} pending review(s): " + ", ".join(parts)


def _unblocked_large_diff_summary(state: dict, settings: dict) -> str:
    try:
        diff = staged_diff()
    except GitError:
        return ""
    if not diff.strip():
        return ""
    try:
        lines, files = significant_change_stats(settings)
    except GitError:
        return ""
    line_threshold = int(settings.get("code_line_threshold", 80))
    file_threshold = int(settings.get("code_file_threshold", 4))
    if lines < line_threshold and files < file_threshold:
        return ""
    diff_sha = sha256(diff)
    if state.get("code_reviewed_sha") == diff_sha:
        return ""
    if any(
        e.get("kind") == "code" and e.get("hash") == diff_sha
        for e in (state.get("pending") or [])
    ):
        return ""  # already blocked and tracked; pending_summary covers it
    return (
        f"staged diff ({lines} lines / {files} files) exceeds threshold "
        "and has not yet been reviewed by codex:codex-rescue — the next "
        "git commit will be blocked"
    )


def main() -> int:
    read_hook_input()
    settings = load_settings()
    state = load_state()

    parts = []
    pending = _pending_summary(state)
    if pending:
        parts.append(pending)
    large = _unblocked_large_diff_summary(state, settings)
    if large:
        parts.append(large)

    if not parts:
        return 0

    print("[codex-review-gate] reminder: " + "; ".join(parts), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
