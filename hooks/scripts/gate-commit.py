#!/usr/bin/env python3
"""PreToolUse(Bash) gate: block `git commit` on large staged diffs until codex:codex-rescue has reviewed the SHA."""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _state import (  # noqa: E402
    GitError,
    add_pending,
    load_settings,
    load_state,
    read_hook_input,
    save_state,
    sha256,
    significant_change_stats,
    staged_diff,
)

# Global git flags that consume the NEXT token as their value.
_GIT_FLAGS_WITH_VALUE = {
    "-c", "-C",
    "--git-dir", "--work-tree", "--namespace",
    "--config-env", "--exec-path",
    "--super-prefix", "--list-cmds",
}


def _is_git_commit(cmd: str) -> bool:
    """True iff cmd invokes `git commit` as a subcommand (not a filename)."""
    for segment in re.split(r"[;&|]{1,2}", cmd):
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            tokens = segment.split()
        try:
            i = tokens.index("git")
        except ValueError:
            continue
        i += 1
        while i < len(tokens):
            t = tokens[i]
            if t in _GIT_FLAGS_WITH_VALUE:
                i += 2
            elif t.startswith("-"):
                i += 1
            else:
                break
        if i < len(tokens) and tokens[i] == "commit":
            return True
    return False


def block(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def main() -> int:
    data = read_hook_input()
    if data.get("tool_name") != "Bash":
        return 0

    cmd = ((data.get("tool_input") or {}).get("command") or "")
    if not _is_git_commit(cmd):
        return 0

    settings = load_settings()
    try:
        diff = staged_diff()
        lines, files = significant_change_stats(settings)
    except GitError as e:
        return block(
            "[codex-review-gate] BLOCK: could not determine the staged diff\n"
            f"({e}). Refusing to allow `git commit` through an unknown\n"
            "state. Verify that `git` is on PATH and the working tree is\n"
            "readable, then retry. If this is a genuine hotfix, invoke\n"
            "/codex-review-gate:codex-review-bypass with a justification."
        )
    if not diff.strip():
        return 0

    line_threshold = int(settings.get("code_line_threshold", 80))
    file_threshold = int(settings.get("code_file_threshold", 4))
    if lines < line_threshold and files < file_threshold:
        return 0

    diff_sha = sha256(diff)
    state = load_state()
    if state.get("code_reviewed_sha") == diff_sha:
        return 0

    add_pending(state, "code", diff_sha, "git commit")
    save_state(state)

    sha12 = diff_sha[:12]
    msg = (
        "[codex-review-gate] BLOCK: staged diff exceeds threshold and has not been\n"
        f"reviewed by codex:codex-rescue.\n"
        f"  staged:    {lines} lines across {files} non-trivial files\n"
        f"  threshold: {line_threshold} lines or {file_threshold} files\n"
        f"  diff SHA:  {sha12}\n"
        "\n"
        "Action required before retrying git commit:\n"
        "  1. Capture the diff:\n"
        "       Bash(\"git diff --cached\")\n"
        "  2. Review it via the codex:codex-rescue subagent. The prompt MUST include\n"
        "     this review-target marker verbatim so the gate can tie the completed\n"
        "     review to this specific diff SHA:\n"
        "\n"
        f"       [review-target: code:{sha12}]\n"
        "\n"
        "     Example:\n"
        "       Agent(\n"
        "         subagent_type=\"codex:codex-rescue\",\n"
        "         description=\"Pre-commit code review\",\n"
        "         prompt=(\n"
        f"           \"[review-target: code:{sha12}]\\n\"\n"
        "           \"Review the following staged diff. Focus on: bugs, security \"\n"
        "           \"issues, error handling, edge cases, test coverage gaps, and \"\n"
        "           \"maintainability. Output: (1) must-fix issues, (2) suggested \"\n"
        "           \"improvements, (3) overall verdict.\\n\\n\"\n"
        "           \"<diff>\\n\" + DIFF + \"\\n</diff>\"\n"
        "         ),\n"
        "       )\n"
        "  3. Address must-fix issues, re-stage, then retry git commit.\n"
        "     Any file edit changes the diff SHA and triggers a fresh review.\n"
        "\n"
        "The review marker is recorded automatically when the codex:codex-rescue\n"
        "subagent tool call completes (PostToolUse hook) — provided the\n"
        "review-target marker is present in the agent prompt. If you omit the\n"
        "marker, promotion is skipped and you must re-invoke codex:codex-rescue.\n"
        "\n"
        "Emergency bypass (hotfix only): invoke the /codex-review-gate:codex-review-bypass\n"
        "skill with a justification."
    )
    return block(msg)


if __name__ == "__main__":
    sys.exit(main())
