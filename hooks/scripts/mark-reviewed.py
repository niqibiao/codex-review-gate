#!/usr/bin/env python3
"""PostToolUse(Agent) hook: when a codex:codex-rescue subagent completes, promote the pending hash to the reviewed marker."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _state import load_state, now_iso, read_hook_input, save_state  # noqa: E402


def main() -> int:
    data = read_hook_input()
    if data.get("tool_name") != "Agent":
        return 0

    ti = data.get("tool_input") or {}
    if ti.get("subagent_type") != "codex:codex-rescue":
        return 0

    state = load_state()
    pending = state.get("pending_review")
    pending_hash = state.get("pending_hash")
    if not pending or not pending_hash:
        return 0

    if pending == "plan":
        state["plan_reviewed_hash"] = pending_hash
    elif pending == "code":
        state["code_reviewed_sha"] = pending_hash
    else:
        return 0

    state["pending_review"] = None
    state["pending_hash"] = None
    state["last_review_ts"] = now_iso()
    save_state(state)

    print(
        f"[codex-review-gate] recorded {pending} review marker ({pending_hash[:12]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
