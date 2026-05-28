# codex-review-gate

> **EN** · A Claude Code plugin that forces an independent review by the `codex:codex-rescue` subagent before a design/spec or plan is finalized, or code is committed.
>
> **CN** · 一个 Claude Code 插件：在设计稿/方案定稿或代码提交前，强制由 `codex:codex-rescue` 子代理做一次独立审查。

<p>
  <a href="#english"><strong>English</strong></a> ·
  <a href="#中文"><strong>中文</strong></a>
</p>

---

## English

### Why

When Claude Code drafts a design, drafts a plan, or makes a large code change, there is no built-in pause for a second opinion. By the time a spec/plan is written to disk, `ExitPlanMode` fires, or `git commit` runs, any flaws have already been locked in.

This plugin installs hook-driven gates that block those actions until an independent Codex review has happened, and records review approval as a **SHA of the reviewed artifact** — any post-review edit invalidates approval and requires a fresh review.

### How it works

| Gate | Hook event | Fires when | Blocks if | Auto-unblocked by |
|---|---|---|---|---|
| **Spec**           | `PreToolUse(Write)`       | `file_path` matches `spec_path_patterns` (default `docs/superpowers/specs/`, `docs/specs/`, `docs/design/`) and ends in `.md` | `sha256(content)` is not in state | `Agent(subagent_type="codex:codex-rescue", ...)` completes with `[review-target: spec:<sha>]` in prompt |
| **Plan (classic)** | `PreToolUse(ExitPlanMode)` | every call | `sha256(plan)` is not in state | `Agent(subagent_type="codex:codex-rescue", ...)` completes — `PostToolUse(Agent)` promotes the pending hash |
| **Plan (Write)**   | `PreToolUse(Write)`       | `file_path` matches `plan_path_patterns` (default `docs/superpowers/plans/`, `docs/plans/`) and ends in `.md` | `sha256(content)` is not in state | same as above |
| **Code**           | `PreToolUse(Bash)`        | `git commit` and staged diff ≥ threshold | `sha256(git diff --cached)` is not in state | same as above |

`Edit` is intentionally NOT gated — see `skills/codex-review-workflow/SKILL.md` for the rationale.

A `Stop` hook also emits a soft reminder when a turn ends with a large unreviewed staged diff — so Claude can kick off the review before the next `git commit` gets blocked.

### Requirements

- **Claude Code** with the `codex-plugin-cc` plugin installed — this is what provides the `codex:codex-rescue` subagent that the gate relies on. Without it, the gate will block but Claude has no reviewer to satisfy it.
- **Python 3.9+** on `PATH` as `python` (hook scripts; no third-party packages required).
- **git** on `PATH`.

### Install

Inside Claude Code:

```
/plugin marketplace add niqibiao/codex-review-gate
/plugin install codex-review-gate@codex-review-gate
```

Claude Code fetches the repo, registers the plugin, and loads its hooks. Confirm the five hook handlers are live with `/hooks`.

- **Update** → `/plugin marketplace update codex-review-gate`
- **Uninstall** → `/plugin uninstall codex-review-gate@codex-review-gate`

### Configure (optional)

Drop a file at `$CLAUDE_PROJECT_DIR/.claude/codex-review.local.json`:

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

All fields are optional and fall back to the defaults shown. The plan gate still has no content threshold — plans are always reviewed — but you can configure which file paths count as "a plan" via `plan_path_patterns` (directory prefixes; only `.md` files beneath a prefix are gated). Set it to `[]` to disable the Write-path trigger entirely. `spec_path_patterns` works the same way for design/spec markdown files written by skills like `superpowers:brainstorming`. Spec approval is tracked independently of plan approval.

Recommended additions to the host project's `.gitignore`:

```gitignore
.claude/codex-review-state.json
.claude/codex-review.local.json
```

### When a gate fires

The block message tells Claude exactly what to do. In short:

1. Invoke `codex:codex-rescue` via the `Agent` tool, passing the spec/plan text or staged diff as the review target. **Copy the `[review-target: <kind>:<sha>]` marker from the block message verbatim into the agent prompt** — without it the PostToolUse hook cannot promote the review and you will have to re-invoke.
2. Address the must-fix findings.
3. Retry the original tool call (`ExitPlanMode`, `Write`, or `git commit`).

Full reference lives in `skills/codex-review-workflow/SKILL.md`, which auto-activates when the gate fires.

### Emergency bypass

For genuine hotfixes only:

```
/codex-review-gate:codex-review-bypass <reason>
```

Applies to the single currently-pending SHA and appends the justification to `bypass_log` in the state file.

### Layout

```
codex-review-gate/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── hooks/
│   ├── hooks.json
│   └── scripts/
│       ├── _state.py           # shared helpers (state, settings, git, pending list)
│       ├── gate-plan.py        # PreToolUse(ExitPlanMode) + PreToolUse(Write-to-plan-path)
│       ├── gate-commit.py      # PreToolUse(Bash), filters to `git commit`
│       ├── mark-reviewed.py    # PostToolUse(Agent), promotes pending entry by [review-target:] marker
│       └── stop-reminder.py    # Stop, soft reminder
├── skills/
│   ├── codex-review-workflow/SKILL.md   # auto-activated reference
│   └── codex-review-bypass/SKILL.md     # /codex-review-gate:codex-review-bypass
├── settings/codex-review.local.json.example
└── README.md
```

---

## 中文

### 为什么需要它

Claude Code 在落地设计稿、做方案设计或大幅改动代码时，并没有内置的二次审查环节。等到 spec/plan 落到磁盘、`ExitPlanMode` 被调用或 `git commit` 执行，问题已经落地。

本插件通过 hook 安装多道闸门，在这些动作之前强制做一次独立的 Codex 审查，并把审查通过的标记记录为**被审查内容的 SHA 指纹** —— 审查后任何修改都会使标记失效，需要重新审查。

### 工作机制

| 闸门 | Hook 事件 | 触发时机 | 拦截条件 | 自动放行方式 |
|---|---|---|---|---|
| **方案（Spec）** | `PreToolUse(Write)` | `file_path` 命中 `spec_path_patterns`（默认 `docs/superpowers/specs/`、`docs/specs/`、`docs/design/`）且后缀为 `.md` | state 中没有 `sha256(content)` | `Agent(subagent_type="codex:codex-rescue", ...)` 完成且 prompt 包含 `[review-target: spec:<sha>]` |
| **方案（经典）** | `PreToolUse(ExitPlanMode)` | 每次调用 | state 中没有 `sha256(plan)` | `Agent(subagent_type="codex:codex-rescue", ...)` 完成且 prompt 里包含匹配的 `[review-target: plan:<sha>]` 标记，`PostToolUse(Agent)` 将对应 pending 条目提升为 reviewed |
| **方案（Write）** | `PreToolUse(Write)` | `file_path` 命中 `plan_path_patterns`（默认 `docs/superpowers/plans/`、`docs/plans/`）且后缀为 `.md` | state 中没有 `sha256(content)` | 同上 |
| **代码** | `PreToolUse(Bash)` | `git commit` 且 staged diff ≥ 阈值 | state 中没有 `sha256(git diff --cached)` | 同上（标记为 `[review-target: code:<sha>]`） |

`Edit` 刻意不做拦截 —— 原因见 `skills/codex-review-workflow/SKILL.md`。

另外有一个 `Stop` hook：回合结束时若存在未审查的大改动，会发一条软提示，让 Claude 趁早触发审查，避免下次 `git commit` 被拦截。

### 运行要求

- **Claude Code** 且已安装 `codex-plugin-cc` 插件 —— 它负责提供本闸门所依赖的 `codex:codex-rescue` 子代理。未安装时闸门会正常拦截，但 Claude 没有可调的审查者，无法满足闸门。
- `PATH` 中有 **Python 3.9+**，命名为 `python`（hook 脚本使用，无任何第三方依赖）。
- `PATH` 中有 **git**。

### 安装

在 Claude Code 中执行：

```
/plugin marketplace add niqibiao/codex-review-gate
/plugin install codex-review-gate@codex-review-gate
```

Claude Code 会自动拉取仓库、注册插件并加载 hook。使用 `/hooks` 可确认 5 个 handler 已启用。

- **更新** → `/plugin marketplace update codex-review-gate`
- **卸载** → `/plugin uninstall codex-review-gate@codex-review-gate`

### 配置（可选）

在 `$CLAUDE_PROJECT_DIR/.claude/codex-review.local.json` 里写入：

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

所有字段都可选，缺省值如上。方案闸门本身不设内容阈值 —— 方案一经定稿，成本高到值得审查 —— 但可以通过 `plan_path_patterns` 配置哪些路径算作"方案"（目录前缀，仅命中前缀下的 `.md` 文件）；以 `/` 或 Windows 盘符开头的前缀按绝对路径匹配，其余按项目根相对路径匹配。置为 `[]` 可关闭 Write 触发器。`spec_path_patterns` 工作方式相同，用于 `superpowers:brainstorming` 这类技能落到磁盘的 design/spec markdown 文件。spec 的审查标记与 plan 独立维护，互不影响。

推荐在宿主项目的 `.gitignore` 加入：

```gitignore
.claude/codex-review-state.json
.claude/codex-review.local.json
```

### 闸门拦截后如何处理

拦截消息本身会指导 Claude 下一步动作。简言之：

1. 通过 `Agent` 工具调用 `codex:codex-rescue` 子代理，把 spec/plan 文本或 staged diff 作为审查对象传入。**把拦截消息里的 `[review-target: <kind>:<sha>]` 标记原样粘进 prompt 开头** —— 没有这行，PostToolUse hook 无法把这次审查对应到正确的 pending 条目，只能重来。
2. 处理 review 反馈中的必改项。
3. 重试被拦截的工具调用（`ExitPlanMode`、`Write`、或 `git commit`）。

完整说明在 `skills/codex-review-workflow/SKILL.md`，闸门拦截时会自动激活。

### 紧急跳过

仅限真正的 hotfix：

```
/codex-review-gate:codex-review-bypass <跳过理由>
```

仅对当前待审的 SHA 放行一次，理由会追加到 state 文件的 `bypass_log`。

### 目录结构

```
codex-review-gate/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── hooks/
│   ├── hooks.json
│   └── scripts/
│       ├── _state.py           # 共享：state / settings / git / SHA / pending 列表
│       ├── gate-plan.py        # PreToolUse(ExitPlanMode) + PreToolUse(Write-to-plan-path)
│       ├── gate-commit.py      # PreToolUse(Bash)，用 shlex 识别 `git commit` 子命令
│       ├── mark-reviewed.py    # PostToolUse(Agent)，按 [review-target:] 标记推进 pending → reviewed
│       └── stop-reminder.py    # Stop，软提示
├── skills/
│   ├── codex-review-workflow/SKILL.md   # 自动激活，解释机制
│   └── codex-review-bypass/SKILL.md     # /codex-review-gate:codex-review-bypass
├── settings/codex-review.local.json.example
└── README.md
```

---

## License

MIT
