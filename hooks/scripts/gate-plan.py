#!/usr/bin/env python3
"""PreToolUse(ExitPlanMode) gate: block until plan SHA has been reviewed by codex:codex-rescue."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _state import load_state, save_state, sha256, read_hook_input, now_iso  # noqa: E402


BLOCK_TEMPLATE = (
    "[codex-review-gate] BLOCK: plan not yet reviewed by codex:codex-rescue.\n"
    "\n"
    "Action required before retrying ExitPlanMode:\n"
    "  1. Invoke the codex:codex-rescue subagent to review the plan you just drafted.\n"
    "     Example:\n"
    "       Agent(\n"
    "         subagent_type=\"codex:codex-rescue\",\n"
    "         description=\"Plan review\",\n"
    "         prompt=(\n"
    "           \"Review the following technical plan. Focus on: hidden risks, missing \"\n"
    "           \"edge cases, rollback strategy, interface/contract consistency, and \"\n"
    "           \"whether the scope matches the user's actual need. Output: (1) must-fix \"\n"
    "           \"issues, (2) suggested improvements, (3) overall verdict (approve / revise).\\n\\n\"\n"
    "           \"<plan>\\n\" + PLAN_TEXT + \"\\n</plan>\"\n"
    "         ),\n"
    "       )\n"
    "  2. Integrate the review's must-fix items into the plan.\n"
    "  3. Retry ExitPlanMode. If the plan text is identical to what was reviewed, the\n"
    "     gate passes. If you edited the plan, the SHA changes and a fresh review is\n"
    "     required (by design).\n"
    "\n"
    "Current plan SHA: {sha12}\n"
    "The review marker is recorded automatically when the codex:codex-rescue subagent\n"
    "tool call completes (PostToolUse hook). No manual step is needed.\n"
    "\n"
    "Emergency bypass (hotfix only): invoke the /codex-review-gate:codex-review-bypass\n"
    "skill with a justification."
)


def block(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def main() -> int:
    data = read_hook_input()
    if data.get("tool_name") != "ExitPlanMode":
        return 0

    plan_text = ((data.get("tool_input") or {}).get("plan") or "")
    if not plan_text.strip():
        return 0

    plan_hash = sha256(plan_text)
    state = load_state()

    if state.get("plan_reviewed_hash") == plan_hash:
        return 0

    state["pending_review"] = "plan"
    state["pending_hash"] = plan_hash
    state["last_pending_ts"] = now_iso()
    save_state(state)

    return block(BLOCK_TEMPLATE.format(sha12=plan_hash[:12]))


if __name__ == "__main__":
    sys.exit(main())
