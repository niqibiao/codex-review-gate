---
name: codex-review-workflow
description: Reference for the codex-review-gate plugin — read this when a PreToolUse or PostToolUse hook from "codex-review-gate" blocks or logs a message, when the user asks how the review gate works, or before invoking the codex:codex-rescue subagent to satisfy a gate.
---

# codex-review-gate workflow

This plugin enforces independent review by the `codex:codex-rescue` subagent at two points: finalizing a plan (`ExitPlanMode`, or a `Write` that persists a plan file) and committing code (`git commit`).

## How the gates work

### Spec gate — single trigger

Fires on `PreToolUse(Write)` when `tool_input.file_path` matches an entry in `spec_path_patterns` (default prefixes `docs/superpowers/specs/`, `docs/specs/`, `docs/design/`) **and** ends in `.md`. Independent of the plan gate — spec approval does NOT satisfy plan approval and vice versa.

1. PreToolUse(Write) hook inspects `tool_input.file_path`.
2. If the path does not match `spec_path_patterns` (resolved-path containment, case-insensitive on Windows) OR is not `.md`, control falls through to the plan-gate dispatch.
3. Otherwise the hook hashes `tool_input.content` and applies the same gate logic as the plan gate — block on SHA mismatch, auto-promote on `codex:codex-rescue` completion keyed by the marker `[review-target: spec:<sha>]`, retry the `Write`.

**Edit is intentionally not gated for specs**, same rationale as the plan gate: `PreToolUse(Edit)` exposes only `old_string`/`new_string`, not the post-edit file contents, so a faithful spec SHA cannot be reconstructed from the hook payload. Major spec revisions land via full `Write` (which IS gated); small `Edit` tweaks to an already-reviewed spec are tolerated. The next full `Write` re-fires the gate with a fresh SHA.

When a spec block fires:
1. Capture the spec text — for a `Write` block, that's simply `tool_input.content` of the attempted write (no need to re-read the file from disk).
2. Inline the text into the codex:codex-rescue prompt with the `[review-target: spec:<sha>]` marker copied verbatim at the start.
3. Address must-fix items, retry the `Write`. Identical content → gate passes. Edited content → fresh review.

### Plan gate — two triggers

The plan gate fires in two places. Both share the same review marker (`plan_reviewed_hash`) but each pending review is tracked independently by its `(kind, hash)` pair, so two plans that block back-to-back do not clobber each other.

**Trigger A — `ExitPlanMode`** (traditional plan-mode exit)

1. PreToolUse hook reads `tool_input.plan` and computes `sha256(plan)`.
2. If the SHA matches `plan_reviewed_hash`, the call is allowed.
3. Otherwise the hook appends a `{kind: "plan", hash: <sha>, trigger: "ExitPlanMode"}` entry to `state.pending` and blocks.
4. When `Agent(subagent_type="codex:codex-rescue", ...)` next completes, the PostToolUse hook reads the agent's prompt, finds the `[review-target: plan:<sha>]` marker, and promotes **only that specific pending entry** to `plan_reviewed_hash`. Any other pending entries are left alone.
5. Retry `ExitPlanMode`. If the plan text is unchanged, the gate passes.

**Trigger B — `Write` to a plan path** (skills like `superpowers:writing-plans` that save plans directly to disk)

1. PreToolUse(Write) hook inspects `tool_input.file_path`.
2. If the path does not match any entry in `plan_path_patterns` (default prefixes `docs/superpowers/plans/` and `docs/plans/`) OR is not a `.md` file, the call is allowed immediately. Path containment is tested via `Path.resolve()` + `relative_to()`, so `..` segments and symlinks that escape the configured prefix do NOT match, and on Windows the match is case-insensitive.
3. Otherwise the hook hashes `tool_input.content` and applies the same gate logic as Trigger A — block on SHA mismatch, auto-promote on `codex:codex-rescue` completion keyed by the marker, retry the `Write`.

**Why `Edit` is not gated.** The Edit tool's PreToolUse payload only contains `old_string`/`new_string`, not the post-edit file contents. Reconstructing the faithful plan SHA would require reading the current file + simulating the edit inside the hook — more surface area without much gain. The pragmatic trade-off: major plan changes happen via full `Write` (overwrite) which IS gated; small `Edit` tweaks to an already-reviewed plan are tolerated. The next full `Write` re-fires the gate with a fresh SHA.

### Code gate (fires on `git commit` when the staged diff is large)

1. PreToolUse on `Bash` inspects `tool_input.command` for `git commit`.
2. If the command does not contain `git commit`, the call is allowed immediately.
3. Otherwise the hook runs `git diff --cached` and counts lines/files, skipping paths that match `ignore_patterns` (default: docs/, tests/, *.md, *.lock).
4. If the change is below both thresholds (default: 80 lines AND 4 files), the commit is allowed.
5. Otherwise the hook checks `sha256(diff) == code_reviewed_sha`. Match → allowed; no match → a `{kind: "code", hash: <sha>, trigger: "git commit"}` entry is appended to `state.pending` and the commit is blocked.
6. When `Agent(subagent_type="codex:codex-rescue", ...)` next completes with a matching `[review-target: code:<sha>]` marker in its prompt, `hash` is promoted to `code_reviewed_sha`.
7. Retry `git commit`. Any file edit changes the diff SHA and requires a fresh review.

## How to satisfy a block

When a hook blocks with `[codex-review-gate] BLOCK:`, do exactly this, in order:

1. For a spec block — the spec text is `tool_input.content` from the attempted `Write`; no re-reading of a file is needed (the spec gate only fires on Write, not on ExitPlanMode).
2. For a plan block — inline the plan text you just drafted into the subagent prompt. For Trigger B (`Write`), the plan text is simply `tool_input.content` from the attempted write; no re-reading of a file is needed.
3. For a commit block — first run `git diff --cached` via Bash to capture the diff, then inline it into the subagent prompt.
4. **Include the `[review-target: <kind>:<sha>]` marker verbatim at the top of the prompt.** The block message shows the exact line to copy. Without the marker the PostToolUse hook will not promote the review, and you'll have to re-invoke the agent.
5. Invoke `codex:codex-rescue`:
   ```
   Agent(
     subagent_type="codex:codex-rescue",
     description="Pre-commit review" | "Plan review",
     prompt="[review-target: <kind>:<sha12>]\n" + <task-specific review instructions + artifact>
   )
   ```
6. Read the review output. Integrate must-fix items. Do NOT try to retry the blocked tool call until the review has returned.
7. Retry the original tool call (`ExitPlanMode`, `Write`, or `git commit`). The hook now sees the SHA matches the reviewed marker and allows it.

## State file layout

Location: `$CLAUDE_PROJECT_DIR/.claude/codex-review-state.json`

```json
{
  "spec_reviewed_hash": "<sha of last spec that passed review>",
  "plan_reviewed_hash": "<sha of last plan that passed review>",
  "code_reviewed_sha":  "<sha of last staged diff that passed review>",
  "pending": [
    {
      "kind":    "spec" | "plan" | "code",
      "hash":    "<sha awaiting review>",
      "trigger": "ExitPlanMode" | "Write to <path>" | "git commit",
      "ts":      "<ISO 8601>"
    }
  ],
  "last_pending_ts": "<ISO 8601>",
  "last_review_ts":  "<ISO 8601>",
  "bypass_log":      [{ "ts": "...", "gate": "plan|code|spec", "hash": "...", "reason": "..." }]
}
```

Entries in `pending` are deduplicated by `(kind, hash)` and removed individually when their matching review marker is seen. The state file is project-local; recommend adding both this file and `codex-review.local.json` to the project's `.gitignore`.

## Configuration

Optional file at `$CLAUDE_PROJECT_DIR/.claude/codex-review.local.json`:

```json
{
  "code_line_threshold": 80,
  "code_file_threshold": 4,
  "ignore_patterns": ["docs/", "tests/", "test/", "*.md", "*.lock"],
  "spec_path_patterns": ["docs/superpowers/specs/", "docs/specs/", "docs/design/"],
  "plan_path_patterns": ["docs/superpowers/plans/", "docs/plans/"],
  "review_ttl_seconds": 1800
}
```

Any missing field falls back to the default. The plan gate still has no content threshold — plans are always reviewed — but you CAN configure which file paths count as "a plan" via `plan_path_patterns`. Entries are directory prefixes; any `.md` file (at any depth) beneath the prefix counts. Prefixes starting with `/` or a Windows drive letter are treated as absolute paths; others are interpreted relative to the project root. To disable the Write-path trigger, set `plan_path_patterns` to `[]`.

## Design rationale

- **SHA-based markers** mean any post-review edit invalidates approval. Claude cannot tweak code after review and sneak it past the gate.
- **Keyed `pending` list + `[review-target:]` marker** means two pending reviews (e.g., a blocked plan and a blocked commit) can coexist. The PostToolUse hook promotes only the pending entry whose `(kind, hash)` matches the marker in the completed agent's prompt. If Claude omits the marker, nothing is promoted — the gate fails safe rather than approving the wrong artifact.
- **PostToolUse(Agent) auto-promotion** removes the need for Claude to remember to "mark as reviewed" — the gate closes automatically on subagent completion, provided the marker is present.
- **Plan gate has no threshold** because by the time a plan is worth finalizing, the cost of review is small compared to the cost of implementing the wrong plan.
- **Code gate has thresholds** so trivial fixes (typos, comment edits) are not blocked.
- **Review outcome is not inspected** — the gate trusts Claude to integrate findings. If major issues are left unfixed and code is edited to address them, the diff SHA changes and review re-fires anyway.

## Emergency bypass

For genuine hotfixes, use the `codex-review-bypass` skill (`/codex-review-gate:codex-review-bypass <reason>`). It writes a one-shot approval to the state file and appends the justification to `bypass_log`. If multiple entries are pending, the skill asks which one to bypass. Do not use bypass unless the user has explicitly asked.
