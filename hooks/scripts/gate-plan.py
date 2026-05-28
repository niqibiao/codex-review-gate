#!/usr/bin/env python3
"""PreToolUse gate: block until the artifact (spec or plan) SHA has been
reviewed by codex:codex-rescue.

Fires on three tool triggers, dispatched inside extract():

* ``Write`` to a file whose path matches ``spec_path_patterns`` — kind="spec"
  (e.g. design docs persisted by ``superpowers:brainstorming``).
* ``Write`` to a file whose path matches ``plan_path_patterns`` — kind="plan"
  (e.g. implementation plans persisted by ``superpowers:writing-plans``).
* ``ExitPlanMode`` — kind="plan", the traditional plan-mode exit path.

``Edit`` is intentionally NOT gated for either kind. The Edit tool's hook
payload only supplies ``old_string``/``new_string``, not the post-edit file
contents, so computing a faithful artifact SHA from a PreToolUse hook is not
possible without re-reading the file and re-applying the edit. In practice,
major changes happen via full ``Write`` (overwrite); small ``Edit`` tweaks to
an already-reviewed artifact are tolerated. The next full ``Write`` triggers a
fresh review.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _state import (  # noqa: E402
    add_pending,
    load_settings,
    load_state,
    path_matches_any,
    read_hook_input,
    save_state,
    sha256,
)


BLOCK_TEMPLATE = (
    "[codex-review-gate] BLOCK: plan not yet reviewed by codex:codex-rescue.\n"
    "\n"
    "Trigger: {trigger}\n"
    "Current plan SHA: {sha12}\n"
    "\n"
    "Action required before retrying:\n"
    "  1. Invoke the codex:codex-rescue subagent to review the plan you just drafted.\n"
    "     The prompt MUST include this review-target marker verbatim so the gate\n"
    "     can tie the completed review to this specific plan SHA:\n"
    "\n"
    "       [review-target: plan:{sha12}]\n"
    "\n"
    "     Example:\n"
    "       Agent(\n"
    "         subagent_type=\"codex:codex-rescue\",\n"
    "         description=\"Plan review\",\n"
    "         prompt=(\n"
    "           \"[review-target: plan:{sha12}]\\n\"\n"
    "           \"Review the following technical plan. Focus on: hidden risks, missing \"\n"
    "           \"edge cases, rollback strategy, interface/contract consistency, and \"\n"
    "           \"whether the scope matches the user's actual need. Output: (1) must-fix \"\n"
    "           \"issues, (2) suggested improvements, (3) overall verdict (approve / revise).\\n\\n\"\n"
    "           \"<plan>\\n\" + PLAN_TEXT + \"\\n</plan>\"\n"
    "         ),\n"
    "       )\n"
    "  2. Integrate the review's must-fix items into the plan.\n"
    "  3. Retry the blocked tool call. If the plan text is identical to what was\n"
    "     reviewed, the gate passes. If you edited the plan, the SHA changes and\n"
    "     a fresh review is required (by design).\n"
    "\n"
    "The review marker is recorded automatically when the codex:codex-rescue subagent\n"
    "tool call completes (PostToolUse hook) — provided the review-target marker is\n"
    "present in the agent prompt. If you omit the marker, the promotion is skipped\n"
    "and you must re-invoke codex:codex-rescue with the marker.\n"
    "\n"
    "Emergency bypass (hotfix only): invoke the /codex-review-gate:codex-review-bypass\n"
    "skill with a justification."
)

BLOCK_TEMPLATE_SPEC = (
    "[codex-review-gate] BLOCK: spec not yet reviewed by codex:codex-rescue.\n"
    "\n"
    "Trigger: {trigger}\n"
    "Current spec SHA: {sha12}\n"
    "\n"
    "Action required before retrying:\n"
    "  1. Invoke the codex:codex-rescue subagent to review the design/spec you\n"
    "     just drafted. The prompt MUST include this review-target marker\n"
    "     verbatim, on its own line, so the gate can tie the completed review\n"
    "     to this specific spec SHA:\n"
    "\n"
    "       [review-target: spec:{sha12}]\n"
    "\n"
    "     Example:\n"
    "       Agent(\n"
    "         subagent_type=\"codex:codex-rescue\",\n"
    "         description=\"Spec review\",\n"
    "         prompt=(\n"
    "           \"[review-target: spec:{sha12}]\\n\"\n"
    "           \"Review the following design / spec document. Focus on: \"\n"
    "           \"(a) requirement completeness and clarity, \"\n"
    "           \"(b) scope — one cohesive change or several subsystems crammed together, \"\n"
    "           \"(c) internal consistency — do sections contradict each other, \"\n"
    "           \"(d) ambiguity — any requirement readable two ways, \"\n"
    "           \"(e) missing edge cases or implicit assumptions. \"\n"
    "           \"Output: must-fix issues, suggested improvements, verdict.\\n\\n\"\n"
    "           \"<spec>\\n\" + SPEC_TEXT + \"\\n</spec>\"\n"
    "         ),\n"
    "       )\n"
    "  2. Integrate must-fix items into the spec.\n"
    "  3. Retry the Write. Identical content → gate passes. Edited content →\n"
    "     fresh review (a new SHA is computed and re-blocks).\n"
    "\n"
    "Edit is intentionally NOT gated for specs (same trade-off as the plan\n"
    "gate: PreToolUse(Edit) exposes only old_string/new_string, not the\n"
    "post-edit file body, so a faithful spec SHA cannot be reconstructed\n"
    "from the hook payload). Major spec revisions land via full Write and\n"
    "are gated; small Edits to an already-reviewed spec are tolerated. The\n"
    "next full Write re-fires the gate with a fresh SHA.\n"
    "\n"
    "Emergency bypass (hotfix only): invoke the\n"
    "/codex-review-gate:codex-review-bypass skill with a justification."
)


def block(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def extract(data: dict):
    """Return ``(text, kind, trigger)`` for a tool call that should be gated,
    or ``(None, "", "")`` if the call falls outside both gates.

    Dispatch order on a ``Write``:
      1. spec_path_patterns  → kind="spec"
      2. plan_path_patterns  → kind="plan"
      3. otherwise           → allow (None)

    ExitPlanMode is always kind="plan".
    """
    tool = data.get("tool_name")
    tool_input = data.get("tool_input") or {}

    if tool == "ExitPlanMode":
        return (tool_input.get("plan") or ""), "plan", "ExitPlanMode"

    if tool == "Write":
        file_path = tool_input.get("file_path") or ""
        settings = load_settings()

        spec_patterns = settings.get("spec_path_patterns") or []
        if path_matches_any(file_path, spec_patterns):
            return (tool_input.get("content") or ""), "spec", f"Write to {file_path}"

        plan_patterns = settings.get("plan_path_patterns") or []
        if path_matches_any(file_path, plan_patterns):
            return (tool_input.get("content") or ""), "plan", f"Write to {file_path}"

        return None, "", ""

    return None, "", ""


def main() -> int:
    data = read_hook_input()
    plan_text, kind, trigger = extract(data)
    if plan_text is None:
        return 0
    if not plan_text.strip():
        return 0

    artifact_hash = sha256(plan_text)
    state = load_state()

    reviewed_field = "spec_reviewed_hash" if kind == "spec" else "plan_reviewed_hash"
    if state.get(reviewed_field) == artifact_hash:
        return 0

    add_pending(state, kind, artifact_hash, trigger)
    save_state(state)

    template = BLOCK_TEMPLATE_SPEC if kind == "spec" else BLOCK_TEMPLATE
    return block(template.format(sha12=artifact_hash[:12], trigger=trigger))


if __name__ == "__main__":
    sys.exit(main())
