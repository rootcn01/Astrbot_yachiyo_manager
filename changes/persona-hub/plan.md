# 八千代人格中枢收敛方案（A v2 · 定稿）

> 2026-09-19 用户拍板通过。对抗审查 REQUEST-CHANGES 十条 must-fix 已全部纳入本文。
> 执行分工：ZCode 执行 / Cursor 窗验收（AGENTS.md 补充5）。产品仓 = 本仓（Yachiyo_Project），流程按 ../dev-hub。

## 0. 背景与问题

2026-09-18 全栈调研结论（勿重查，见 LifeOS 记忆档 yachiyo-persona-upgrade-research-2026-09-18）：
- 人格文本分裂 7~8 处：①原生人格DB「月见八千代」(data_v4.db, 1601字, 04-18版) ②angel_heart config ai_self_identity（仅喂秘书分析器）③manager PersonaBuilder 截断块（[:800]，台词库几乎 0% 到达）④KB 3文档 ⑤proactive_chat 四段 prompt ⑥planner 两段常量 ⑦persona_builder.py:37/51/54 另有三处硬编码。
- 字数规则三版本打架（40字 / ≤3句 / ≤5句）。

## 1. 对抗审查的关键事实修正（承重，勿再犯）

1. **on_llm_request 优先级是降序**（star_handler.py:26，数值大先执行）。真实注入顺序：**manager(100) → angel_heart(50/0)**；最终 system_prompt = 原生人格协议 → manager 动态块 → angel_heart scene_prompt。angel_heart 源码里"priority=50 在决策注入之后"的注释本身就是错的。
2. **reply_strategy 私聊到不了主模型**：私聊链路 decision 恒为 None（front_desk.py:1400/1427-1436）；群聊也只以弱化 XML 追加进 contexts（:1456-1460）。策略是自由文本非枚举。
3. **reply_strategy_guide 只喂秘书**（llm_analyzer.py:218），KB 检索由主模型执行——RAG 使用说明必须放主模型可见处。
4. front_desk 群聊接管时**全量替换 req.contexts**（:1372）——livingmemory 注入存活待服务器实测（W2 前置验证）。

## 1.5 W1 服务器取证结果（2026-09-19 00:18–00:30，只读）

1. **system_prompt 实序（源码级确认）**：原生人格 `# Persona Instructions`（astr_main_agent.py:516）→ manager priority=100 追加（群聊非@时跳过；LifeOS 块仅 owner）→ angel_heart priority=50 替换 contexts/prompt、system_prompt 尾部追加 scene_prompt。与 §1.1 一致。日志级无法还原（INFO 级 + trace 全关），如需运行时对账须临时开 trace 或加 debug 钩子。
2. **⚠️ livingmemory 处于停用状态**：每次重启报 `Plugin astrbot_plugin_livingmemory is disabled`（最近 00:17:45），日志零注入行。机制上其 `user_message_before` 注入改 req.prompt、钩子默认优先级 0 后于 angel_heart，**应能存活**——但实际整层记忆现在是关的（config mtime 09-18 23:40，禁用是注册表级）。W4 前需用户拍板是否重启该插件。
3. **⚠️ KB 启动即坏**：`知识库 Yachiyo_Project 初始化失败: 无法找到 ID 为 text-embedding-v3 的 Embedding Provider`（kb_mgr:81）——KB 引用的 embedding id 与现存 provider（qwen3.7-text-embedding）不匹配，RAG 实际不可用。W2 更新 KB 文档前必须先修此项。
4. **angel_heart 钉版确认**：本地 0.9.0 市场安装（无 .git、mtime 06-27），上游已到 2.1.2；dashboard 只有手动 update 端点、crontab/systemd 无自动更新——钉版安全，但未来升级=大迁移（0.9→2.x），须整跑冒烟。
5. **dsh_task 冒烟通过**：hello.md 已产出、TASKLOG 全 DONE、sidecar 18234 在跑；已知瑕疵=容器重启后任务 ID 回卷（dsh 线自己处理）。当晚 9 次容器重启均为 dsh 开发迭代——W2 部署前与 dsh 线确认无进行中任务。
6. **部署端点确认**：KB 现代路由 `/api/v1/knowledge-bases/{kb_id}/documents`（POST 上传 / DELETE 文档；**无文档内容更新端点**，更新=delete+re-upload）；dashboard :6185；proactive 群聊破冰 prompt 全文已取回（占位符 {{current_time}}/{{unanswered_count}}，与 persona/out/proactive_pack.md 口径一致）。
7. **⚠️ angel_heart 同样处于停用**（09-19 追查）：禁用名单 `preferences.inactivated_plugins`（2026-07-18 16:29 批量操作）含 angel_heart + livingmemory；同批 self_learning/outputpro/spectrecore 为已卸载插件的僵尸条目。即 **07-18 起运行时没有秘书决策/上下文接管/scene_prompt，八千代在「原生协议+manager 截断块」裸管线上跑了两个月**。§1.1–1.3 与 §2 中关于 angel_heart 的结论是源码级真相，当前运行时未激活；其两个人格 config 字段现为惰性。**启用与否=用户拍板项**（影响：群回复时机行为变化、每条群消息多一次秘书 LLM 调用、上下文接管与 manager/livingmemory 注入的相互作用）。
8. **✅ 已处置（09-19 00:36）**：①KB embedding 引用修正 `text-embedding-v3 → qwen3.7-text-embedding`（kb.db UPDATE；**旧 key 实测未过期**，无需换 dsh key；用户点名的 tongyi-embedding-vision-plus-2026-03-06 该账号 404 不存在；账号在列向量模型=qwen3.7-text-embedding(+flash)，1024 维）②livingmemory 摘出禁用名单并重启生效：Provider 第 3 次重试就绪、衰减调度找回 **8 条 7 月前旧记忆**（记忆库存活）③重启前后备份：`backups/data_v4.20260919-003603.bak`、`backups/kb.20260919-003603.bak`（容器内路径）。angel_heart 保持停用待拍板。dsh 侧 0919-04 任务于重启前 DONE，零中断。
9. **W2.5 模型定案**：`qwen3.8-max`（09-19 用户改定，原 glm-5.2 提名作废；账号 models 列表确认存在，另有 qwen3.8-max-0902 日期版）。

## 2. 架构（原稿 + 编译分发）


```
persona/00-identity.md      核心身份（cut:core 进原生协议 / cut:boot 演出指令）
persona/10-voice.md         语言指纹 + 字数红线矩阵（唯一出处）
persona/20-tone-library.md  台词库 few-shot（原作行号溯源；情绪×亲密度分区）
persona/30-world.md         世界观 → KB 全文
persona/40-timeline.md      时间线羁绊（公开/绝密两层）→ KB 全文
persona/50-relations.md     关系分层态度（五级关系映射）
persona/60-scenarios.md     场景策略（群聊/私聊/深谈/主动/早晚push/任务/深夜/月读常识使用）
persona/70-guardrails.md    防线（身份/剧透/注入/情绪/格式/隐私）
        │ build_persona.py（唯一人格分发通道，27 项自检，exit 1 on fail）
        ▼ persona/out/
1. native_persona_protocol.md → 原生人格DB「月见八千代」：静态协议（1803字：身份+语言指纹+关系+常识使用+防线+台词采样+boot）
2. analyzer_identity.txt      → angel_heart ai_self_identity：「月读观测子系统」包装+身份摘要（不含演出指令）
3. strategy_guide.txt         → angel_heart reply_strategy_guide：策略枚举约束（顶流营业/温柔安慰/腹黑调戏/淡定简答/继续观察）
4. kb/*.md                    → KB 文档替换（30/40 全文）
5. proactive_pack.md          → proactive_chat 三段（PRIVATE_PROACTIVE/PRIVATE_HISTORY/GROUP_ICEBREAK）
6. planner_prompts.txt        → planner.py 两常量
7. manifest.json              → 版本/长度/sha256/自检记录
```

**分工铁律**：静态协议=原生人格（每链路必达）；动态上下文=manager 注入层（时段/关系/场景/台词运行时选择/LifeOS）；世界观=KB 按需检索；决策=angel_heart；主动=proactive_chat。**部署面（DB人格/angel_heart config/KB/proactive config）一律只由编译产物更新，禁止手改。**

## 3. 部署 runbook（W2 用，靶位×通道×角色）

| 靶位 | 通道 | 回滚 |
|---|---|---|
| 原生人格DB | WebUI 编辑 or dashboard API（W1 取证确认端点）；内容=out/native_persona_protocol.md | data_v4.db 部署前备份 |
| angel_heart 两字段 | ssh + python json 合并脚本（out/analyzer_identity.txt + strategy_guide.txt；先导出 config 快照） | 还原 config 快照 |
| KB 2 文档 | dashboard KB API **delete + 重新 upload**（无文档级更新端点）；前置修复 embedding provider 引用（text-embedding-v3 → qwen3.7-text-embedding，见 §1.5-3） | 旧文档导出留档 |
| proactive 三段 | 同 angel_heart 通道 | 同上 |
| manager 代码（截断修复+动态化+守卫） | build_zip.py → WebUI 上传 → 插件 reload | 旧 zip 留档（yachiyo_plugin_v2.3.zip） |
| 模型切换（W2.5 独立窗） | WebUI provider_settings.default_provider_id → 阿里百炼/glm-5.2（fallback 不动 deepseek 系）+ modalities 核对 | 切回 ds-v4-flash |

部署顺序：先快照全靶位 → manager 代码 → 原生人格 → angel_heart/KB/proactive → 冒烟。**dsh 冒烟期间不 restart 容器**；热生效性逐项验证（W1 取证），需 restart 的项目与 dsh 排期错开。

## 4. 冒烟清单（W2 收工门）

1. 口癖存在性：群里/私聊各触发一轮，回复含签名口癖之一、无动作描写、无 <inner_thought>
2. 红线矩阵：群聊回复 ≤40 字；私聊深谈（发长文）放开字数
3. 白名单三道回归：非白名单群不回、owner gate 工具不泄、persona_pool 切人格时 manager 跳过注入（新守卫）
4. 秘书健康：决策日志正常（观测子系统包装后 JSON 稳定）
5. KB：月读常识类提问能召回且转述为阅历口吻
6. 原生人格 DB 内容 = manifest sha256 对账
7. livingmemory 注入存活（前置验证结论复核）

## 5. 路线图与决策记录

- **W1（本窗，2026-09-19）**：persona/ 八模块 + build_persona.py v1（27/27 自检绿）+ 本方案档 + CLAUDE.md 刷新 + angel_heart 快照（_server_snapshot_2026-09-18/，不进 git）+ 服务器取证（system_prompt 实序 / livingmemory 存活 / angel_heart 钉 0.9.0 / dsh 冒烟态 / 部署面端点）。
- **W2 部署窗**：manager 硬编码清理（[:800]/:37/:51/:54→引用红线矩阵）+ PersonaBuilder 降级纯动态 + 非默认人格守卫 + 七靶位落盘 + 回滚包 + 冒烟。
- **W2.5 模型窗（独立，A 冒烟通过后）**：默认 provider → 阿里百炼/glm-5.2（复用 dsh 的百炼 key 口径；fallback 留 deepseek 系）；modalities 配置核对；QQ 通道金丝雀 → 微信。
- **W3 表达窗（B 降级版）**：台词库运行时选区（关系×场景，替换式非叠加）；策略枚举→群聊风格路由；私聊不依赖策略标签。
- **W4 记忆窗（C）**：set_pinned_fact/set_nickname 工具；livingmemory 写接口前置验证（不通则记 user_state）；三轨注入前缀声明。
- **D 声音轨（独立插空）**：参考音频 → MiMo 克隆验证 → 投递路径（原生 provider 音色字段 vs 薄插件）→ 按场景 TTS 策略。
- 快赢（可先行）：[:800] 修复随 W2；703030437/703030473 QQ 号核对；manager README 重写；reminder_tools.py 死代码清理。

**用户拍板记录**：①原生人格纳为第 7 靶位承静态协议（否决存根化）②W2.5 模型=**百炼 qwen3.8-max**（09-19 改定，glm-5.2 提名作废；复用 dsh 百炼 key 口径）③livingmemory「有用就启动」授权已执行（09-19 00:36 启用成功，8 条旧记忆找回）④台词库扩写政策未决（现库仅原作溯源条目，W3 前需拍板）⑤**新增待拍板：angel_heart 是否重新启用**（07-18 起停用，详见 §1.5-7）。

## 6. 风险登记

- angel_heart 市场插件：钉 0.9.0，升级前必须跑冒烟 §4（其 0.8.33 曾 config schema 迁移）。
- WebUI 手改部署面 → 与编译产物漂移：manifest sha256 对账 + 修后再编译（不手改）。
- 私聊策略路由缺失是 angel_heart 设计使然，非 bug；补丁方案进 backlog（改 front_desk 私聊链路取决策），W3 不做。
- proactive/proactive_history 的占位符（{{current_time}} 等）在 W2 合入时必须原样保留。
- **KeyError 'type'**：每次启动 provider.manager:283 报一次（全史 15 次，先于本次改动存在）——某个 provider 条目缺 type 字段，W2 顺手定位修复（备份在案，与人格线无耦合）。
- livingmemory 重启后 8 条旧记忆已找回，但其向量索引是旧模型产物；W2 若换 embedding 模型需触发其 index rebuild（其配置有 migration/rebuild 开关）。
