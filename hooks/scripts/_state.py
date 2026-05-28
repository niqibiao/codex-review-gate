"""Shared helpers for codex-review-gate hook scripts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

DEFAULT_PLAN_PATH_PATTERNS = [
    "docs/superpowers/plans/",
    "docs/plans/",
]

DEFAULT_SPEC_PATH_PATTERNS = [
    "docs/superpowers/specs/",
    "docs/specs/",
    "docs/design/",
]

DEFAULT_SETTINGS = {
    "code_line_threshold": 80,
    "code_file_threshold": 4,
    "ignore_patterns": ["docs/", "tests/", "test/", "*.md", "*.lock"],
    "plan_path_patterns": list(DEFAULT_PLAN_PATH_PATTERNS),
    "spec_path_patterns": list(DEFAULT_SPEC_PATH_PATTERNS),
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
    # Drop legacy single-slot fields if they snuck in — we now use `pending` list.
    state.pop("pending_review", None)
    state.pop("pending_hash", None)
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GitError(RuntimeError):
    """Raised when a `git` invocation itself cannot be completed (not on PATH,
    timeout, OS-level failure). Non-zero exit codes with captured stdout are
    still returned normally — only subprocess-level failures raise, so the
    gate can distinguish 'no staged changes' (empty stdout) from 'we could
    not determine the staged diff' (raise).
    """


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
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError) as e:
        raise GitError(f"git {' '.join(args)}: {type(e).__name__}: {e}") from e
    return r.stdout or ""


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


def path_matches_any(path: str, patterns: list[str]) -> bool:
    """Return True if `path` falls under any configured directory prefix.

    Patterns are directory prefixes (with or without a trailing `/`). Relative
    patterns are interpreted relative to the project root; patterns that start
    with `/` or a Windows drive letter are treated as absolute-path prefixes.
    In both branches, containment is checked via ``Path.resolve()`` +
    ``relative_to()`` (so `..` segments, symlinks/junctions, and Windows
    case-folding all behave correctly — a path that lexically looks in-prefix
    but resolves outside does NOT match).

    Any markdown file (case-insensitive `.md`) at any depth under the prefix
    counts. Non-`.md` paths never match.
    """
    if not path:
        return False
    p_norm = path.replace("\\", "/")
    if not p_norm.lower().endswith(".md"):
        return False

    proj = project_dir().resolve()
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = project_dir() / candidate
        abs_in = candidate.resolve()
    except OSError:
        return False

    for raw_pat in patterns or []:
        pat_norm = raw_pat.replace("\\", "/").rstrip("/") + "/"
        anchored_abs = pat_norm.startswith("/") or (len(pat_norm) >= 2 and pat_norm[1] == ":")
        if anchored_abs:
            try:
                pat_abs = Path(raw_pat).resolve()
            except OSError:
                continue
        else:
            try:
                pat_abs = (proj / raw_pat.rstrip("/\\")).resolve()
            except OSError:
                continue
        try:
            abs_in.relative_to(pat_abs)
            return True
        except ValueError:
            continue
    return False


# Marker Claude must paste verbatim into the codex:codex-rescue prompt so the
# PostToolUse(Agent) hook knows which pending review this Agent call satisfies.
# Requires literal [...] brackets AND the marker be its own line (only
# whitespace around it) so substrings inside quoted diffs, fenced code blocks,
# or user-controlled plan text cannot spoof a promotion.
PENDING_MARKER_RE = re.compile(
    r"^[ \t]*\[[ \t]*review-target[ \t]*:[ \t]*(plan|code|spec)[ \t]*:[ \t]*([0-9a-f]{12,64})[ \t]*\][ \t\r]*$",
    re.IGNORECASE | re.MULTILINE,
)


def add_pending(state: dict, kind: str, hash_: str, trigger: str) -> None:
    """Append a pending review entry, deduplicating by (kind, hash).

    If an entry with the same (kind, hash) already exists, only its trigger
    and timestamp are refreshed. Concurrent blocks for different artifacts
    coexist; each is promoted independently when its marker is reviewed.
    """
    pending = state.get("pending") or []
    state["pending"] = pending
    ts = now_iso()
    for e in pending:
        if e.get("kind") == kind and e.get("hash") == hash_:
            e["trigger"] = trigger
            e["ts"] = ts
            state["last_pending_ts"] = ts
            return
    pending.append({"kind": kind, "hash": hash_, "trigger": trigger, "ts": ts})
    state["last_pending_ts"] = ts


def remove_pending(state: dict, kind: str, hash_: str) -> bool:
    pending = state.get("pending") or []
    filtered = [e for e in pending if not (e.get("kind") == kind and e.get("hash") == hash_)]
    if len(filtered) == len(pending):
        return False
    state["pending"] = filtered
    return True


def resolve_pending_from_prompt(state: dict, prompt: str):
    """Return ``(kind, full_hash)`` of the pending entry referenced by the
    ``[review-target: <kind>:<sha>]`` marker in ``prompt``, or ``None``.

    The marker kind must match an existing pending entry, and the marker hash
    prefix (12+ hex chars) must be a prefix of that entry's full hash.
    """
    if not prompt:
        return None
    m = PENDING_MARKER_RE.search(prompt)
    if not m:
        return None
    mk_kind = m.group(1).lower()
    mk_hash = m.group(2).lower()
    for e in state.get("pending") or []:
        if e.get("kind") != mk_kind:
            continue
        full = (e.get("hash") or "").lower()
        if full and full.startswith(mk_hash):
            return mk_kind, full
    return None
