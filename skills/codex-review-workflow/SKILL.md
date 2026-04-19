---
name: codex-review-workflow
description: Reference for the codex-review-gate plugin — read this when a PreToolUse or PostToolUse hook from "codex-review-gate" blocks or logs a message, when the user asks how the review gate works, or before invoking the codex:codex-rescue subagent to satisfy a gate.
---

# codex-review-gate workflow

This plugin enforces independent review by the `codex:codex-rescue` subagent at two points: finalizing a plan (`ExitPlanMode`) and committing code (`git commit`).

## How the gates work

### Plan gate (fires on every ExitPlanMode)

1. PreToolUse hook reads `tool_input.plan` and computes `sha256(plan)`.
2. If the SHA already appears in the state file's `plan_reviewed_hash`, the call is allowed.
3. Otherwise the state file is updated with `pending_review="plan"` + `pending_hash=<sha>`, and the tool call is blocked with instructions.
4. When `Agent(subagent_type="codex:codex-rescue", ...)` next completes, the PostToolUse hook promotes `pending_hash` → `plan_reviewed_hash` and clears pending.
5. Retry `ExitPlanMode`. If the plan text is unchanged, the gate passes.

### Code gate (fires on `git commit` when the staged diff is large)

1. PreToolUse on `Bash` inspects `tool_input.command` for `git commit`.
2. If the command does not contain `git commit`, the call is allowed immediately.
3. Otherwise the hook runs `git diff --cached` and counts lines/files, skipping paths that match `ignore_patterns` (default: docs/, tests/, *.md, *.lock).
4. If the change is below both thresholds (default: 80 lines AND 4 files), the commit is allowed.
5. Otherwise the hook checks `sha256(diff) == code_reviewed_sha`. Match → allowed; no match → blocked with instructions and pending state recorded.
6. When `Agent(subagent_type="codex:codex-rescue", ...)` next completes, `pending_hash` is promoted to `code_reviewed_sha`.
7. Retry `git commit`. Any file edit changes the diff SHA and requires a fresh review.

## How to satisfy a block

When a hook blocks with `[codex-review-gate] BLOCK:`, do exactly this, in order:

1. For plan block — inline the plan text you just drafted into the subagent prompt.
2. For commit block — first run `git diff --cached` via Bash to capture the diff, then inline it into the subagent prompt.
3. Invoke `codex:codex-rescue`:
   ```
   Agent(
     subagent_type="codex:codex-rescue",
     description="Pre-commit review" | "Plan review",
     prompt=<task-specific review instructions + artifact>
   )
   ```
4. Read the review output. Integrate must-fix items. Do NOT try to retry the blocked tool call until the review has returned.
5. Retry the original tool call (`ExitPlanMode` or `git commit`). The hook now sees the SHA matches the reviewed marker and allows it.

## State file layout

Location: `$CLAUDE_PROJECT_DIR/.claude/codex-review-state.json`

```json
{
  "plan_reviewed_hash":  "<sha of last plan that passed review>",
  "code_reviewed_sha":   "<sha of last staged diff that passed review>",
  "pending_review":      "plan" | "code" | null,
  "pending_hash":        "<sha awaiting review>" | null,
  "last_pending_ts":     "<ISO 8601>",
  "last_review_ts":      "<ISO 8601>",
  "bypass_log":          [{ "ts": "...", "gate": "plan|code", "hash": "...", "reason": "..." }]
}
```

The state file is project-local. Recommend adding both this file and `codex-review.local.json` to the project's `.gitignore`.

## Configuration

Optional file at `$CLAUDE_PROJECT_DIR/.claude/codex-review.local.json`:

```json
{
  "code_line_threshold": 80,
  "code_file_threshold": 4,
  "ignore_patterns": ["docs/", "tests/", "test/", "*.md", "*.lock"],
  "review_ttl_seconds": 1800
}
```

Any missing field falls back to the default. Plan gate is not configurable — plans are always reviewed.

## Design rationale

- **SHA-based markers** mean any post-review edit invalidates approval. Claude cannot tweak code after review and sneak it past the gate.
- **PostToolUse(Agent) auto-promotion** removes the need for Claude to remember to "mark as reviewed" — the gate closes automatically on subagent completion.
- **Plan gate has no threshold** because by the time a plan is worth finalizing, the cost of review is small compared to the cost of implementing the wrong plan.
- **Code gate has thresholds** so trivial fixes (typos, comment edits) are not blocked.
- **Review outcome is not inspected** — the gate trusts Claude to integrate findings. If major issues are left unfixed and code is edited to address them, the diff SHA changes and review re-fires anyway.

## Emergency bypass

For genuine hotfixes, use the `codex-review-bypass` skill (`/codex-review-gate:codex-review-bypass <reason>`). It writes a one-shot approval to the state file and appends the justification to `bypass_log`. Do not use bypass unless the user has explicitly asked.
