# codex-review-gate

> A Claude Code plugin that forces an independent review by the `codex:codex-rescue` subagent before a plan is finalized or code is committed.
>
> 一个 Claude Code 插件：在技术方案定稿或代码提交前，强制由 `codex:codex-rescue` 子代理做一次独立审查。

[English](#english) · [中文](#中文)

---

## English

### Why this plugin

When Claude Code drafts a plan or makes a large code change, there is no built-in pause for a second opinion. By the time `ExitPlanMode` fires or `git commit` runs, any flaws have already been locked in. This plugin installs two hook-driven gates that block those actions until an independent Codex review has happened.

### How it works

| Gate | Hook event | Fires when | Blocks if | Auto-unblocked by |
|---|---|---|---|---|
| **Plan** | `PreToolUse(ExitPlanMode)` | every call | `sha256(plan)` is not in state | `Agent(subagent_type="codex:codex-rescue", ...)` completes — `PostToolUse(Agent)` promotes the pending hash |
| **Code** | `PreToolUse(Bash)` | `git commit` and staged diff ≥ threshold | `sha256(git diff --cached)` is not in state | same as above |

There is also a `Stop` hook that emits a soft reminder if a turn ends with a large unreviewed staged diff — Claude can kick off the review before the next `git commit` gets blocked.

All markers are **SHA fingerprints of the artifact being reviewed**. Any post-review edit invalidates the marker, so Claude cannot tweak content after review and sneak it past the gate.

### Install

Inside Claude Code:

```
/plugin marketplace add niqibiao/codex-review-gate
/plugin install codex-review-gate@codex-review-gate
```

That is all. Claude Code fetches the repo, registers the plugin, and loads its hooks. Confirm the four hook handlers are live with `/hooks`.

To update later: `/plugin marketplace update codex-review-gate`. To remove: `/plugin uninstall codex-review-gate@codex-review-gate`.

### Requirements

- Python 3.9+ on `PATH` as `python` (hook scripts, no third-party packages)
- `git` on `PATH`
- The `codex:codex-rescue` subagent available in the environment. This plugin only observes whether an `Agent` tool call with that `subagent_type` has completed; it does not invoke Codex itself.

### Configure (optional)

Create `$CLAUDE_PROJECT_DIR/.claude/codex-review.local.json`:

```json
{
  "code_line_threshold": 80,
  "code_file_threshold": 4,
  "ignore_patterns": ["docs/", "tests/", "test/", "*.md", "*.lock"],
  "review_ttl_seconds": 1800
}
```

All fields are optional and fall back to the defaults shown. Plan gate is not configurable — plans are always reviewed.

### Recommended project `.gitignore`

```gitignore
.claude/codex-review-state.json
.claude/codex-review.local.json
```

### When a gate fires

The block message tells Claude exactly what to do. In short:

1. Invoke `codex:codex-rescue` via the `Agent` tool, passing the plan text or staged diff as the review target.
2. Address the must-fix findings.
3. Retry the original tool call (`ExitPlanMode` or `git commit`).

Full reference is in `skills/codex-review-workflow/SKILL.md`, which auto-activates when the gate fires.

### Emergency bypass

For genuine hotfixes only:

```
/codex-review-gate:codex-review-bypass <reason>
```

Applies to the single currently-pending SHA and appends the justification to `bypass_log` in the state file.

### Layout

```
codex-review-gate/
├── .claude-plugin/plugin.json
├── hooks/
│   ├── hooks.json
│   └── scripts/
│       ├── _state.py           # shared helpers (state, settings, git)
│       ├── gate-plan.py        # PreToolUse(ExitPlanMode)
│       ├── gate-commit.py      # PreToolUse(Bash), filters to `git commit`
│       ├── mark-reviewed.py    # PostToolUse(Agent), promotes pending hash
│       └── stop-reminder.py    # Stop, soft reminder
├── skills/
│   ├── codex-review-workflow/SKILL.md  # auto-activated reference
│   └── codex-review-bypass/SKILL.md    # /codex-review-gate:codex-review-bypass
├── settings/codex-review.local.json.example
└── README.md
```

---

## 中文

### 为什么需要这个插件

Claude Code 在做方案设计或大幅改动代码时，并没有内置的二次审查环节。等 `ExitPlanMode` 被调用或 `git commit` 执行，问题已经落地。这个插件通过 hook 安装两道闸门，在这两个动作之前强制做一次独立的 Codex 审查。

### 工作机制

| 闸门 | Hook 事件 | 何时触发 | 何时拦截 | 如何自动放行 |
|---|---|---|---|---|
| **方案** | `PreToolUse(ExitPlanMode)` | 每次调用 | state 中没有 `sha256(plan)` | `Agent(subagent_type="codex:codex-rescue", ...)` 完成时，`PostToolUse(Agent)` 把 pending hash 提升为 reviewed |
| **代码** | `PreToolUse(Bash)` | `git commit` 且 staged diff ≥ 阈值 | state 中没有 `sha256(git diff --cached)` | 同上 |

另外有一个 `Stop` hook：回合结束时若存在未审查的大改动，会发一条软提示，让 Claude 趁早触发审查，避免下次 `git commit` 被拦截。

所有标记都是**被审查内容的 SHA 指纹**。审查后任何修改都会使标记失效 — Claude 不能在审查完成之后再偷偷改代码绕过闸门。

### 安装

在 Claude Code 中执行：

```
/plugin marketplace add niqibiao/codex-review-gate
/plugin install codex-review-gate@codex-review-gate
```

Claude Code 会自动拉取仓库、注册插件并加载 hook。用 `/hooks` 可确认 4 个 handler 已启用。

- 更新：`/plugin marketplace update codex-review-gate`
- 卸载：`/plugin uninstall codex-review-gate@codex-review-gate`

### 运行要求

- `PATH` 中有 Python 3.9+ 命名为 `python`（hook 脚本使用，不依赖任何第三方包）
- `PATH` 中有 `git`
- 环境里可用的 `codex:codex-rescue` 子代理。插件本身**不调用** Codex，它只在某个 `subagent_type="codex:codex-rescue"` 的 `Agent` 工具调用完成时记录 review 标记。

### 配置（可选）

在 `$CLAUDE_PROJECT_DIR/.claude/codex-review.local.json` 里写入：

```json
{
  "code_line_threshold": 80,
  "code_file_threshold": 4,
  "ignore_patterns": ["docs/", "tests/", "test/", "*.md", "*.lock"],
  "review_ttl_seconds": 1800
}
```

所有字段都可选，缺省值如上。方案闸门**不设阈值** —— 方案一经定稿，成本就已经高到值得审查。

### 建议加入项目 `.gitignore`

```gitignore
.claude/codex-review-state.json
.claude/codex-review.local.json
```

### 闸门拦截后怎么办

拦截消息本身会指导 Claude 下一步动作。简言之：

1. 通过 `Agent` 工具调用 `codex:codex-rescue` 子代理，把方案文本 / staged diff 作为审查对象传入
2. 处理 review 反馈中的必改项
3. 重试被拦截的工具调用（`ExitPlanMode` 或 `git commit`）

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
├── .claude-plugin/plugin.json
├── hooks/
│   ├── hooks.json
│   └── scripts/
│       ├── _state.py           # 共享：state / settings / git / SHA
│       ├── gate-plan.py        # PreToolUse(ExitPlanMode)
│       ├── gate-commit.py      # PreToolUse(Bash)，用 shlex 识别 `git commit` 子命令
│       ├── mark-reviewed.py    # PostToolUse(Agent)，推进 pending → reviewed
│       └── stop-reminder.py    # Stop，软提示
├── skills/
│   ├── codex-review-workflow/SKILL.md  # 自动激活，解释机制
│   └── codex-review-bypass/SKILL.md    # /codex-review-gate:codex-review-bypass
├── settings/codex-review.local.json.example
└── README.md
```

---

## License

MIT
