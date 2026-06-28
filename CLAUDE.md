# CLAUDE.md — 月见八千代 AstrBot 插件

> 版本：v2.3.0 | 最后更新：2026-06-28

## 项目定位

这是 Futureplan LifeOS 的移动端接入层。八千代通过微信提供自然语言记账/灵感/待办/汇报/查询。深度处理由 Claude Code 桌面端完成。

## 关键架构

- 工具注册：`@llm_tool`（AstrBot 全局，所有聊天流可用）
- 数据源：`/data/Futureplan/` markdown 文件
- git 同步：每次写后 fire-and-forget push
- 身份安全：`_is_owner()` gate

## v2.3.0 变更（2026-06-28）

- `checkin.py`：`format_checkin_line()` +overtime 参数
- `main.py`：`record_checkin()` +overtime 参数
- `dashboard.py`：表格解析兼容新旧格式（8/9列）+ `extract_wfa()` + `extract_overtime_stats()`
- `context.py`：上下文块 +加班统计 +WFA +加班周建议

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
