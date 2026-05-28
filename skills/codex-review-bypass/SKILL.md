---
name: codex-review-bypass
description: Emergency one-shot bypass of the codex-review-gate plugin for the current pending plan or staged diff. Use only when the user explicitly requests it for a time-critical hotfix; records the reason to an audit log in the state file.
argument-hint: <reason for bypass>
allowed-tools: Bash, Read, Write
---

# Bypass the codex-review-gate (emergency only)

You are resolving a user-initiated request to bypass the review gate for exactly one upcoming action. Bypassing defeats the gate's purpose — only proceed if the user has given an explicit reason appropriate to a time-critical hotfix.

## Preconditions

- `$ARGUMENTS` should contain the user's reason. If it is empty or a placeholder, STOP and ask the user to supply one. Do not make up a reason.
- Do not bypass preemptively. A bypass is meaningful only when there is a pending or imminent block.

## Steps

1. Read the current state file at `$CLAUDE_PROJECT_DIR/.claude/codex-review-state.json`. If it does not exist, create an empty `{}` in memory.

2. Determine the gate being bypassed. The state file has a `pending` list: `[{ "kind": "plan"|"spec"|"code", "hash": "<sha>", "trigger": "...", "ts": "..." }, ...]`.
   - Run `Bash("git diff --cached")` and capture the output.
     - If non-empty → this is a **code** gate bypass. Compute `sha256` of the diff; call that `target_hash` (kind = `code`). Ignore any stale `pending` entry whose hash does not match the current diff.
   - Else if `pending` contains exactly one `spec` entry → this is a **spec** gate bypass. Use its `hash` as `target_hash`.
   - Else if `pending` contains multiple spec entries → ask the user which one to bypass (show trigger + short SHA for each). Do not proceed without an explicit choice.
   - Else if `pending` contains exactly one `plan` entry → this is a **plan** gate bypass. Use its `hash` as `target_hash`.
   - Else if `pending` contains multiple plan entries → ask the user which one to bypass (show trigger + short SHA for each). Do not proceed without an explicit choice.
   - Else → tell the user there is nothing pending to bypass and stop.

3. Update the state file:
   - For code bypass: set `code_reviewed_sha = target_hash`.
   - For spec bypass: set `spec_reviewed_hash = target_hash`.
   - For plan bypass: set `plan_reviewed_hash = target_hash`.
   - Set `last_review_ts` to the current ISO 8601 UTC timestamp.
   - Remove the matching entry from `pending` (by `kind` + `hash`). Leave any other pending entries alone — bypass is scoped to one artifact.
   - Append to `bypass_log` (create the array if missing) an entry:
     ```json
     { "ts": "<iso>", "gate": "plan|code|spec", "hash": "<target_hash>", "reason": "<user reason from $ARGUMENTS>" }
     ```

4. Write the updated state back to the file (pretty-printed JSON, sorted keys).

5. Confirm to the user with a single line:
   > codex-review-gate: one-shot bypass recorded for <gate> gate (SHA <first-12-chars>). Reason logged.

## Safety rules

- Never bypass without an explicit user-supplied reason.
- Never modify anything other than the state file.
- Never bypass more than one artifact per invocation. If multiple entries are pending, ask the user which one to bypass.
- Never clear `bypass_log`. Entries are append-only.
- The bypass applies only to the single SHA you just recorded. Any further change re-arms the gate.

## Shell snippet you may use to read current timestamp portably

```bash
python -c "import datetime, sys; sys.stdout.write(datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'))"
```
