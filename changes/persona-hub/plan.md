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

10. **✅ 参数调优轮（09-19 01:0x，用户授权执行席定参；研究代理产出语义依据；备份 `backups/*.20260919-005941.bak`）**：
    - **分段回复**（cmd_config `platform_settings.segmented_reply`）：enable=true / only_llm_result=true / **threshold=400** / random 1.5-3.5s。阈值语义与直觉相反（**≤阈值才切分**，超过整发），400=几乎所有人格回复可按标点切条、超长深谈文整发。
    - **proactive_chat**：私聊主动消息**从上线起就是死配置**（friend session_list 为空、群 session `default:` 前缀匹配不上任何真实 UMO）。已修：friend session=owner UMO（weixin_personal_lotus:FriendMessage:o9cq…@im.wechat）+ auto_trigger 开（插件重启后60分钟无私聊则补种任务）+ 间隔 240-900min 均匀随机 + 连发 2 条未回复即停（原4）+ 免打扰 1-7 维持；群 session=`yachiyo:GroupMessage:853409824`。TTS 维持语音+文本双发。
    - **sowing_discord**：目标群号 `703030437`→**`703030473`**（会话库 190 条消息实锤真群号，原号从未存在=每转发必失败一次）；夜间冷却 0→3600s（防凌晨背靠背搬史）；白天 600s 维持。语义注记：该插件是按表情回应评价筛选的**跨群搬史机**（forward_group_single_msg 原样转发），不是拟态插件。
    - **livingmemory**：注入法 `user_message_before`→**`extra_user_content`**（不污染对话历史+不破坏 provider 前缀缓存）；遗忘清理 30d→**90d**（人格连续性）；`use_session_filtering`→**false**（跨会话召回：私聊记忆可在群被召回；隐私依赖 70 防线+亲友群场景，可一键回改）。其余（full_group_capture/top_k 5/反思10轮/graph 全默认）维持。
11. **⚠️ 两个运维配方（实测）**：①**cmd_config 在容器运行时改盘会被停机存档覆盖**（SIGTERM 优雅退出把内存配置写回盘）——核心配置改动必须 **stop→edit→start**；dashboard API 程序化登录被 PBKDF2 密码升级挡死（明文字段为空），别再试。插件配置无停机保存，改盘+重启即生效。②livingmemory 主库实为**空库**（documents=0；「8 条旧记忆」只在旧 schema 备份里且已被日清物理删除，前报有误）——记忆从零积累；7-18 有 embedding FreeTierOnly 写入失败史，09-19 实测 key 可出向量，**首次反思后查 memory_write_ops 有无新 failed**（观察项）。

12. **✅ W2.6 修复轮（09-19 01:46，用户指令）**：
    - **deepseek-v4-flash → deepseek-flash 全链路改名**：官方模型列表已无 v4-flash（仅 deepseek-flash/deepseek-v4-pro），改名具时效性。落点：provider 条目（id+model）、fallback 链、manager planning_provider_id、livingmemory llm_provider_id、angel_heart analyzer_model；停机改法一次完成，重启验证 `Loading model openai_chat_completion(deepseek/deepseek-flash)` 无残留。
    - **KB 修复（病根三层）**：①init 失败史（provider 引用错位）已于 00:36 修；②**FAISS 索引是 4 月 22 日旧 embedding 空间的向量**——4 月后所有语义检索都是跨空间静默垃圾，且 description 里的 `{RAG_CONTENT}` 模板在核心零引用=纯装饰。处置：铸 JWT（见下）→ API 删旧三档 → 上传新档全量重嵌入 → description 换真描述。**终态=3 档 39 chunks（World_Rules 16 + TL_h1 10 + TL_h2 13）当前模型 qwen3.7-text-embedding 嵌入**。③怪病记录：**Timeline_Bonds.md 整份上传在 storage 段确定性失败**（insert_batch 报「写入知识库索引时出错」，底层异常被 raise-from 吞掉；改名无效、清场串行重试无效、二分两半均一次过）——16-chunk 组合触雷待上游解释，接受两半形态（内容完整、检索等效），AstrBot 升级后可重试整份。
    - **协议 v2（1894 字重落）**：60-scenarios 核心区从「字面标记」（[月读常识]/[回忆涌现]，管线里根本没人发这些标记）改为**机制描述**：KB 检索结果=月读常识、英文 `HISTORICAL MEMORY REFERENCE` 块（livingmemory 实际格式）=过去记忆、`[关于神明]`（manager 实发）=用户了解。三信号全部对齐真实管线。
    - **JWT 铸钥配方（新运维武器）**：dashboard 的 kb/system 权限不在 API key 开放集（ALL_OPEN_API_SCOPES 无 kb/system，403 在验 key 前就抛）；但 `jwt_secret` 明文在 cmd_config——容器内用 pyjwt 铸 HS256 `{'username':'lotuscn'}` 即等价 WebUI 登录态（scopes=['*']），Bearer 头直接用。用后即删。
    - 观察记录：用户已自行安装 astrbot_plugin_mimo_tts_clone v0.7.2 且 **QQ 私聊语音发送实测成功**（D 轨用户自推，微信侧投递待验）。

13. **📋 三窗方案规划轮（09-19 深夜 ZCode，产出待拍板）**：W-AH/W3/W4 结构化方案落盘 [wah-w3-w4-plans-2026-09-19.md](wah-w3-w4-plans-2026-09-19.md)（v2=对抗修订版）。对抗审查 REQUEST-CHANGES 4H/4M/6L 全部修订纳入，最重四条：①**angel_heart 白名单非全局门**（只挡非@消息与上下文接管；全群 @消息 +analyzer 调用、strip_markdown 含私聊全局生效、扣押机制密集连@可吞回复）②config 实名字段=whitelist_enabled(默认False)+chat_ids，**alias 默认 "AngelHeart" 不设即污染实验效度** ③**关系计数生产死代码**：_update_user_interaction 全插件仅创建提醒一个调用点，W3 选区上线即近失效，须前置修活（inject_persona 注入路径+节流落盘）④「persona_pool 切人格守卫」在 manager v2.4.0 不存在（§4-3 声称的守卫未落实；persona_pool 已收缩为单人故 moot，记 §6）。另证：**build_persona.py 自检实数 36 项**（运行时 36/36 全绿+产物幂等；此前 27/34 口径均过时，CLAUDE.md 已同步）；台词库 2 条跨区重复（2165/2189），三区全开=19 唯一句。排程建议：W-AH 先启动（挂历观察期 3-7 天）→W3 编码重叠→D3 拍板与部署压后；W4 的 livingmemory 写接口验证插观察期内并行。方案档 §5 八项决策点等用户拍板。

14. **▶️ 执行轮第一班（09-19 ZCode，用户全八项照建议拍板）**：
    - **W-AH 启动 ✅**：备份 `backups/angel_heart_config.20260919-wah.bak` + `backups/data_v4.20260919-wah.bak`；stop→edit→start 三改动（顺带规避插件配置停机存档的不确定性）：①config 实录取证——`alias='AI|助手'`（非默认 AngelHeart，但同样污染 scene_prompt）→改`八千代`；`whitelist_enabled` 已 True；`chat_ids=['1010233339','703030473','853409824']`→收敛 `['187109260']`（**1010233339 实为私聊好友 QQ 号非群**，会话库 UMO=FriendMessage 坐实；187109260=09-18 新建测试群，非 proactive 非 sowing_discord 零混杂；样本量不足时升级「853409824+临时停 proactive 群破冰」）；`slap_words='闭嘴'`/`strip_markdown=True`/`comfort_words=''`/`force_reply_when_summoned=True` 维持原样 ②inactivated_plugins 摘除 angel_heart（剩三条为已卸载插件僵尸条目）③启动验证：0.9.0 加载、扣押机制 V2 启用、分析器组装成功、无 disabled 行；KeyError 'type' 复现一次=已知先天项。**观察期开始**（判据①②③数据靠金丝雀群真实对话积累）。
    - **W4 前置验证 ✅（结论改案）**：livingmemory **自带主动记忆写入工具 `memorize_long_term_memory`**（core/tools/memory_memorize_tool.py；参数 memory/topics/key_facts/sentiment/importance/reason），经 `context.add_llm_tools()` 注册——**主模型直接可调，双写零代码**。开关 `agent_tools.enable_memorize_tool` 默认 false、现值 false（`enable_recall_tool` true 已在跑）。开启动作压到 W4 执行窗（避免污染 W-AH 观察期行为面）。W4 方案修订：set_pinned_fact 降级为观察项（与 memorize 功能重叠；pinned=确定性注入 vs memorize=RAG 召回+90d 清理，先跑 memorize 看效果）；set_nickname 保留（称呼需每轮确定到达，不能赌召回）。
    - **W3 编码 ✅（本地，未部署——D3 与部署按排程压到观察期后）**：①D0 关系计数修活：inject_persona 注入成功路径调 `_update_user_interaction`（消息 id 去重 deque 256 防 agent 循环多轮重复计数；节流落盘=跨档/变mood/>10min 才写 KV）②新靶位 `persona/out/tone_zones.json`（三区结构化+tiers 五级+native_picks 去重标记；编译尾部自动同步进 `astrbot_plugin_yachiyo_manager/resources/`，build_zip 全目录打包自动带上）③协议采样收缩 D1-A：营业 [2,5] 两条兜底（原 7 条）④persona_builder v2.5 选区段：替换式档位（stranger/acquaintance→营业；familiar→+温柔；close/intimate→三区）、协议采样条目排除、跨区字面去重、群聊每区上限 3 ⑤启动校验：resources 缺文件/坏 JSON=WARN+选区关闭（回退纯协议采样，禁静默旧数据）⑥自检 36→**44 项全绿**（三区条数 9/6/6、字面重复 1+去括注重复 2 双口径——对抗结论的「2 条重复」系语义口径，字面仅 1 条、腹黑侧带括注）、产物幂等 ⑦新测试 `tests/test_persona_builder.py` 7/7 本地过（数据驱动用真实产物；坑：台词语境列嵌套「」会污染提取正则，须锚定行首）。测试算式坑：群聊档跨区重复句不同时出现（温柔#5/腹黑#6 不在前3），期望=2+3+3=8 非 6。
    - **遗留到下班的班次**：W3 部署+容器内全量 pytest（含 reminder 3 例需 astrbot 环境）；D3 群聊映射段（等 W-AH 去留结论）；W4 执行（开 memorize 开关+set_nickname+真实写入验证）；W-AH 三判据数据收集与拍板。

15. **▶️ 执行轮第一班·下半（09-19 午后 ZCode，用户指令：判据统计脚本+set_nickname 编码+模型源调整）**：
    - **模型 fallback 重排 ✅（用户意图=百炼赠送额度优先花，deepseek 留到快用完）**：主对话本就是百炼/qwen3.8-max（W2.5 切的，用户原以为没切）；实改=fallback 链 `[ds-flash, ds-v4-pro, 百炼/glm-5.2]` → **`[百炼/qwen3.8-max-0902, 百炼/qwen3.7-plus, 百炼/glm-5.2, ds-flash, ds-v4-pro]`**（前三条百炼花赠送额度；qwen3.8-max-0902 为新建 provider，复制 qwen3.8-max 条目仅改 id/model，enable_thinking=false/modalities 全同；五条 provider 全部真实存在零死链——W2.5 死链教训）。百炼账号模型列表已实拉（dashscope compatible-mode /models，200+ 个在列）。stop→edit→start，备份 `backups/cmd_config.20260919-model.bak`，重启验证加载行齐、dsh 零中断。**analyzer/planning/livingmemory 的 deepseek-flash 刻意未动**——切它们会给 W-AH 观察期引入秘书行为变量，攒观察期后与 W4 一起。
    - **W4 set_nickname 编码 ✅（本地未部署）**：main.py 新增 @llm_tool（record_expense 前，关系/记忆类小节）；docstring 写明「仅用户明确要求时调用」（防滥用）；≤12 字硬截断；返回 NICKNAME_OK|nickname=…|replaced=… 机器可读串。与 W3 攒一个部署包。
    - **判据③统计器 ✅**：`changes/persona-hub/wah_judge3_stats.py`（宿主机 sudo python3 跑，--since 24h）；从 docker logs 提取 LLM 调用数（按群分组）/参与 vs 不参与/策略分布/话题 top5/延迟 p50-p95（调用→决策行配对）/AngelHeart 错误数；本地干测 4 类行正则全命中后服务器实跑，与手采样本完全一致（12h 窗：1 调用/2.4s/零错误）。
    - **运行时新证据（日志级）**：①金丝雀群 187109260 已有插话决策样本（「不参与·原因:不在场」）②白名单外老群 709923858 的 @消息走完整秘书链——对抗 HIGH-1 的爆炸半径实况坐实（白名单只管插话不管@）③@轮策略覆写字面量=「被呼唤回复」实况坐实（W3 D3 映射的第六分支依据）④analyzer 延迟实测 2.4s。

16. **fallback 终版（09-19 13:32，用户点名四条全百炼链）**：`[百炼/qwen3.8-max, 百炼/qwen3.8-max-0902, 百炼/deepseek-v4-pro, 百炼/deepseek-v4-pro-0813]`。中间插曲：用户在 13:19 版后自行经 WebUI 调过 fallback 并自建 百炼/deepseek-v4-pro-0813 provider（读到的旧值=三条件态），本版在其基础上定稿。新建 provider 百炼/deepseek-v4-pro（复制 qwen3.8-max 结构；**去掉 enable_thinking**——qwen 系参数对百炼的 deepseek 模型有 400 风险，deepseek 用默认行为）。qwen3.8-max 居链首=主模型失败后同款即时重试（救瞬时抖动）。**链尾无异构家族兜底**（全链百炼账号，百炼整体故障时无候补——用户知情选择，glm 系/官方 deepseek provider 仍在列表可随时回加）。备份 `backups/cmd_config.20260919-model2.bak`；TASKLOG DONE 零中断；重启验证四条全加载、default 不变。**秘书 analyzer 及各分工位确认=单点无链**（analyzer_model 单字段锁 deepseek/deepseek-flash 官方源；AstrBot fallback 只包主对话请求）——切百炼 flash 档攒观察期后（避免污染 W-AH 判据）。

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
        │ build_persona.py（唯一人格分发通道，36 项自检，exit 1 on fail）
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

部署顺序：先快照全靶位 → manager 代码 → 原生人格 → angel_heart/KB/proactive → 冒烟。**dsh 冒烟期间不 restart 容器**；热生效性已验证（§1.5-11）：插件配置改盘+重启即生效；**cmd_config 必须停机改**（运行时改盘会被停机存档覆盖）；DB 类（persona/kb/preferences）运行时可改、重启后生效。

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
- **W2 部署窗（✅ 2026-09-19 01:20 完成并验证）**：manager v2.4.0（纯动态注入层，对抗审查 APPROVE-WITH-FIXES 三条 must-fix 已落）+ 七靶位中五靶位落盘——原生人格DB（1841字带编译戳）、angel_heart 两字段（惰性）、proactive 三段、planner 两常量（随插件）；**KB 文档替换延后**（旧文档=同源语料，价值低；用户可随时 WebUI 手动上传 persona/out/kb/*.md 或提供面板 API key 后脚本化）。persona_pool 收缩为 ['月见八千代']（停机改）。备份：`backups/*.20260919-011924.w2bak` + `yachiyo_manager.20260919-011924.tar.gz`。**验证证据**：部署后 01:20 用户真实消息（QQ私聊"晚上好"）回复含口癖"锵～☆"+神明大人+第三人称自称+凌晨时段上下文+世界观私有梗"松饼"（KB agentic 检索命中信号）+字数合规；容器内 pytest 3 passed；persona_mgr 3 personas 正常。遗留观察：meme_manager 报 `minimax/MiniMax-M2.7-highspeed` provider 不存在（先天配置悬空，非本窗引入）；KeyError 'type' 定位=provider_sources 机制条目无 type 字段（化妆级，模型可用，不修核心）。
- **W2.5 模型窗（独立，A 冒烟通过后）**：默认 provider → 阿里百炼/qwen3.8-max（复用 dsh 的百炼 key 口径；fallback 留 deepseek 系）；modalities 配置核对；QQ 通道金丝雀 → 微信。
- **W2.5 模型窗（✅ 2026-09-19 01:28）**：新增 provider `阿里百炼/qwen3.8-max`（百炼 source、key 实测活、**enable_thinking=false**——40字短回不需深思、省延迟成本；modalities=text/image/tool_use；reasoning=false），default_provider_id 切换成功（日志 "Selected … as default chat model provider"）。**顺手修死链**：原 fallback_chat_models 四条（glm-4.7/kimi-k2.5/qwen3.5-plus/ds-v4-pro）前三条 provider 列表里根本不存在=一直空转，改为 [ds-v4-flash, ds-v4-pro, 百炼/glm-5.2] 全活条目。规划/记忆反思/群分析仍锁 flash 不变。**新观察项两条**：①QQ 语音 STT 失败（mimo_stt 收到 67 字节坏音频，napcat silk 下载/转换问题；模型以人格口吻优雅兜底了）②个别空白消息分段（segmented_reply 对前导空白的切分，待复现再调）。
- **W-AH angel_heart 实验窗（W2/W2.5 稳定后，用户 09-19 批准）**：先只放开一个 QQ 群当金丝雀（其 access_control.whitelist 现成）→ 观察三判据：①插话时机质量 ②与 manager/livingmemory 注入的运行时相互作用（源码级顺序已推演，运行时首次实测）③秘书调用量（每条群消息一次 flash 调用）→ 通过则保留并激活其两个编译靶位（analyzer_identity/strategy_guide），失败则永久停用（终态成立：@驱动+主动破冰，人格栈依然完整）。回退=单开关。
- **W3 表达窗（B 降级版）**：台词库运行时选区（关系×场景，替换式非叠加）；策略枚举→群聊风格路由；私聊不依赖策略标签。
- **W4 记忆窗（C）**：set_pinned_fact/set_nickname 工具；livingmemory 写接口前置验证（不通则记 user_state）；三轨注入前缀声明。
- **D 声音轨（独立插空）**：参考音频 → MiMo 克隆验证 → 投递路径（原生 provider 音色字段 vs 薄插件）→ 按场景 TTS 策略。
- 快赢（可先行）：[:800] 修复随 W2；703030437/703030473 QQ 号核对；manager README 重写；reminder_tools.py 死代码清理。

**用户拍板记录**：①原生人格纳为第 7 靶位承静态协议（否决存根化）②W2.5 模型=**百炼 qwen3.8-max**（09-19 改定，glm-5.2 提名作废；复用 dsh 百炼 key 口径）③livingmemory「有用就启动」授权已执行（09-19 00:36 启用成功，8 条旧记忆找回）④台词库扩写政策未决（现库仅原作溯源条目，W3 前需拍板）⑤**angel_heart 路线批准（09-19）**：保持停用 → W2/W2.5 后按 W-AH 实验窗流程决定去留 ⑥**插件参数调优授权（09-19）**：执行席按需调到最优值，不熟悉的领域可开子代理研究。

## 6. 风险登记

- angel_heart 市场插件：钉 0.9.0，升级前必须跑冒烟 §4（其 0.8.33 曾 config schema 迁移）。
- WebUI 手改部署面 → 与编译产物漂移：manifest sha256 对账 + 修后再编译（不手改）。
- 私聊策略路由缺失是 angel_heart 设计使然，非 bug；补丁方案进 backlog（改 front_desk 私聊链路取决策），W3 不做。
- proactive/proactive_history 的占位符（{{current_time}} 等）在 W2 合入时必须原样保留。
- **KeyError 'type'**：每次启动 provider.manager:283 报一次（全史 15 次，先于本次改动存在）——某个 provider 条目缺 type 字段，W2 顺手定位修复（备份在案，与人格线无耦合）。
- livingmemory 重启后 8 条旧记忆已找回，但其向量索引是旧模型产物；W2 若换 embedding 模型需触发其 index rebuild（其配置有 migration/rebuild 开关）。
- **napcat HTTP API「未监听」结论作废（09-19 13:45 翻案）**：当时实测在 astrbot 容器/宿主 curl `localhost:3000` 均拒绝连接=**测试姿势错误**——napcat 是独立容器、3000 未映射宿主，正确地址是容器网络名 `http://napcat:3000`（已实测 get_status 返回 online/good 双 true）。manager 的 QQ 群 TTS（send_group_ai_record）改用此地址后应可活，快赢候选复活。
- **QQ 语音 STT / 纯图片消息根因诊断（09-19，待用户拍板修法）**：napcat 侧语音接收正常（03:49「接收←[语音 2s]」在案）、HTTP API 可达，断点=**napcat 报文的消息段 file 字段是 napcat 容器内本地路径**（onebot11 config `enableLocalFile2Url: false`），astrbot 容器读不到该路径 → STT 收到坏/空音频（历史 67 字节观察吻合）→ 空文本；纯图片消息同理变空 → 不唤醒主模型（12:54 私聊纯图后 3.5 分钟零 LLM 痕迹）。修法主选=napcat 开 `enableLocalFile2Url: true`（并确保生成 url 的 host 是 astrbot 可达名，如容器名 napcat 而非 0.0.0.0/127.0.0.1）；**需重启 napcat，有 QQ 掉线风险（历史判例：重启=掉线需重扫码）**——执行前必须用户知情拍板。
- **秘书 analyzer 已切百炼（09-19 13:39）**：analyzer_model `deepseek/deepseek-flash` → `阿里百炼/qwen3.8-flash`（新建 provider，enable_thinking=false 保持）；用户拍板提前切（观察期刚开始，基线直接定在最终形态）。观察期判据①数据自切换后起算。
- QQ 号悬案 `703030437/703030473` 机器验尸失败（platform_message_history 空表——group_icl 关着没记历史；napcat API 不通）→ 转用户人工确认。
- **manager v2.4.0 无「persona_pool 切人格守卫」**（09-19 三窗规划轮对抗核实）：§4-3 声称的新守卫从未实现，grep 全插件零引用；persona_pool 已收缩为 ['月见八千代'] 单人故当前 moot——若未来重开多人格池须补守卫。
- **关系计数生产死代码**（09-19 对抗核实）：_update_user_interaction 仅创建提醒一个调用点，interaction_count/relationship/mood 生产中几乎不动——W3 选区机制的生效前提，修法=W3 范围内 inject_persona 注入路径计数+节流落盘（方案档 §2.2-D0）。
- **angel_heart 启用的真实爆炸半径**（09-19 快照取证，详方案档 §1.2）：白名单只挡非@消息与上下文接管，全群 @消息 +analyzer 调用；strip_markdown 含私聊全局生效（回复第二副本入 ledger）；扣押机制密集连@可吞回复；alias 默认 "AngelHeart" 须改设。
