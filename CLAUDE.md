# CLAUDE.md — 月见八千代人格中枢仓

> 版本：v3.0（人格中枢纪元） | 最后更新：2026-09-19
> 定稿方案与路线图：[changes/persona-hub/plan.md](changes/persona-hub/plan.md) ← 动手前必读

## 项目定位

两层：
1. **八千代人格中枢**——`persona/` 八模块是人格唯一原稿，`build_persona.py` 是唯一分发通道，编译产物进 `persona/out/` 部署到 AstrBot 各靶位。
2. **LifeOS 移动端接入层**——`astrbot_plugin_yachiyo_manager` 插件（记账/汇报/提醒/任务工具），深度处理由 Claude Code 桌面端完成。

## 铁律（人格线）

- 改人格 = 只改 `persona/*.md` → 跑 `python build_persona.py`（36 项自检必须全绿）→ 产物经部署 runbook 落服务器。
- **禁止手改部署面**：原生人格DB / angel_heart config / KB 文档 / proactive config。发现漂移 → 以 `persona/out/manifest.json` 的 sha256 对账 → 重新编译覆盖。
- 字数红线只有一个出处：`10-voice.md` 的红线矩阵。任何代码/配置不得另立数字。
- angel_heart 钉 0.9.0（快照在 `_server_snapshot_2026-09-18/`，不进 git）；升级前必须跑 plan.md §4 冒烟。
- 台词库只收原作溯源条目（扩写政策未决，见 plan.md §5）。

## 目录速览

```
persona/            人格八模块原稿（唯一编辑点）
  out/              编译产物（进 git，部署审计用）
build_persona.py    编译器（persona → 七靶位）
astrbot_plugin_yachiyo_manager/  管理插件（工具层+动态注入层）
astrbot_plugin_dsh_task/         dsh 任务桥插件（独立线，见 changes/dsh-bridge-concept/）
changes/            方案档（persona-hub / dsh-bridge-concept）
source_docs/        原作语料（小说/设定集/公式书）
output_md/          人格产物旧版（v2.3 时代；已被 persona/ 取代，留档）
_server_snapshot_*/ angel_heart 服务器快照（不进 git）
```

## 关键架构事实（对抗审查钉死，勿再错）

- AstrBot `on_llm_request` 优先级**降序**：manager(100) 先于 angel_heart(50/0)。最终 system_prompt = 原生人格协议 → manager 动态块 → angel_heart scene_prompt。
- angel_heart 的 `ai_self_identity`/`reply_strategy_guide` 只喂秘书分析器，主对话模型看不到。
- 秘书的 reply_strategy 私聊到不了主模型（decision 恒 None）；策略枚举见 `persona/out/strategy_guide.txt`。
- 分工：静态协议=原生人格 / 动态上下文=manager / 世界观=KB / 决策=angel_heart / 主动=proactive_chat。
- **运行时开关现状（2026-09-19 W2.6 后）**：主对话=阿里百炼/qwen3.8-max（enable_thinking=false）；fallback=deepseek/deepseek-flash → deepseek-v4-pro → 百炼/glm-5.2；livingmemory 启用（跨会话召回，主库从零积累中）；**angel_heart 停用中**（W-AH 实验窗再启，见 plan.md §5）；KB 已全量重嵌入（3 档 39 chunks，Timeline 两半形态=接受的终态）；proactive_chat 已修活；分段回复开（threshold 400）；用户已自装 mimo_tts_clone v0.7.2（QQ 私聊语音已通）。

## 与外部的关系

- **dev-hub**（../dev-hub）：功能开发走其专业链（spec→plan→tasks→实现→验证→对抗审查→标准回写）；微型改动逃生舱同其定义。
- **LifeOS**（../LifeOS）：本仓不 import 人生规则；manager 的 LifeOS 数据块只在 owner 私聊注入。
- **服务器**：110.40.182.106，容器 astrbot-astrbot-1；dsh 冒烟期等计划任务在跑时**不 restart 容器**，用插件 reload。

## 四条工程原则（沿用 v2.3）

1. **Think Before Coding**——不假设；多种解读摆出来；有更简单的做法就说。
2. **Simplicity First**——最小实现；不做投机性抽象。
3. **Surgical Changes**——只动该动的；不"顺手改"无关代码。
4. **Goal-Driven Execution**——先定可验证成功标准；改人格=自检全绿+冒烟清单，改代码=测试先行。
