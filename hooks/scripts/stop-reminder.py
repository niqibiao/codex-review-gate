#!/usr/bin/env python3
"""Stop hook: soft reminder when a session ends with unreviewed large staged changes."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _state import (  # noqa: E402
    load_settings,
    load_state,
    read_hook_input,
    sha256,
    significant_change_stats,
    staged_diff,
)


def main() -> int:
    read_hook_input()

    settings = load_settings()
    diff = staged_diff()
    if not diff.strip():
        return 0

    lines, files = significant_change_stats(settings)
    line_threshold = int(settings.get("code_line_threshold", 80))
    file_threshold = int(settings.get("code_file_threshold", 4))
    if lines < line_threshold and files < file_threshold:
        return 0

    state = load_state()
    if state.get("code_reviewed_sha") == sha256(diff):
        return 0

    print(
        "[codex-review-gate] reminder: staged changes "
        f"({lines} lines / {files} files) exceed the review threshold and have not "
        "been reviewed by codex:codex-rescue. The next git commit will be blocked "
        "until reviewed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
