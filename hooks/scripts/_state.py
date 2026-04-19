"""Shared helpers for codex-review-gate hook scripts."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

DEFAULT_SETTINGS = {
    "code_line_threshold": 80,
    "code_file_threshold": 4,
    "ignore_patterns": ["docs/", "tests/", "test/", "*.md", "*.lock"],
    "review_ttl_seconds": 1800,
}


def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def state_path() -> Path:
    return project_dir() / ".claude" / "codex-review-state.json"


def settings_path() -> Path:
    return project_dir() / ".claude" / "codex-review.local.json"


def load_settings() -> dict:
    merged = dict(DEFAULT_SETTINGS)
    p = settings_path()
    if p.exists():
        try:
            merged.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return merged


def load_state() -> dict:
    p = state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git(args: list[str], timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=project_dir(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return r.stdout or ""
    except Exception:
        return ""


def staged_diff() -> str:
    return _git(["diff", "--cached"])


def staged_numstat() -> list[tuple[int, int, str]]:
    rows: list[tuple[int, int, str]] = []
    for line in _git(["diff", "--cached", "--numstat"]).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            added = int(parts[0]) if parts[0] != "-" else 0
            deleted = int(parts[1]) if parts[1] != "-" else 0
        except ValueError:
            continue
        rows.append((added, deleted, parts[2]))
    return rows


def is_trivial_path(path: str, patterns: list[str]) -> bool:
    p = path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    for pat in patterns:
        if pat.endswith("/"):
            prefix = pat.rstrip("/")
            if p == prefix or p.startswith(prefix + "/") or f"/{prefix}/" in f"/{p}/":
                return True
        elif fnmatch(p, pat) or fnmatch(name, pat):
            return True
    return False


def significant_change_stats(settings: dict) -> tuple[int, int]:
    patterns = settings.get("ignore_patterns", [])
    lines, files = 0, 0
    for added, deleted, path in staged_numstat():
        if is_trivial_path(path, patterns):
            continue
        lines += added + deleted
        files += 1
    return lines, files


def read_hook_input() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}
