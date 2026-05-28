#!/usr/bin/env python3
"""PostToolUse(Agent) hook: promote the pending entry referenced by the
``[review-target: <kind>:<sha>]`` marker in the completing codex:codex-rescue
agent's prompt. No marker → no promotion (fails safe).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _state import (  # noqa: E402
    load_state,
    now_iso,
    read_hook_input,
    remove_pending,
    resolve_pending_from_prompt,
    save_state,
)


def main() -> int:
    data = read_hook_input()
    if data.get("tool_name") != "Agent":
        return 0

    ti = data.get("tool_input") or {}
    if ti.get("subagent_type") != "codex:codex-rescue":
        return 0

    state = load_state()
    if not (state.get("pending") or []):
        return 0

    match = resolve_pending_from_prompt(state, ti.get("prompt") or "")
    if match is None:
        print(
            "[codex-review-gate] codex:codex-rescue completed but no "
            "[review-target: plan|code|spec:<sha>] marker matched a pending review. "
            "No review marker recorded. Re-invoke the agent with the marker "
            "shown in the block message."
        )
        return 0

    kind, full_hash = match
    if kind == "plan":
        state["plan_reviewed_hash"] = full_hash
    elif kind == "code":
        state["code_reviewed_sha"] = full_hash
    elif kind == "spec":
        state["spec_reviewed_hash"] = full_hash
    else:
        return 0

    remove_pending(state, kind, full_hash)
    state["last_review_ts"] = now_iso()
    save_state(state)

    print(
        f"[codex-review-gate] recorded {kind} review marker ({full_hash[:12]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
