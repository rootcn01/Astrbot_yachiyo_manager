# astrbot_plugin_dsh_task 方案 v0.2（理念层）

> 日期：2026-09-18 ｜ 状态：方案讨论中（架构未定稿）
> 分层声明：**本档只写方案/理念/交互/约束**。工程细节（文件结构、配置 schema、部署步骤、测试计划）在 dev-hub 工作区开工时按完整专业链产出（澄清→constitution→spec→plan→tasks→实现→验证→对抗审查）；代码落本产品仓（Yachiyo_Project），流程从 `../dev-hub/` 调。v0.1 的工程段落已浓缩为 §7 移交要点。
> 背景调研：LifeOS `../LifeOS/research/dsh-yachiyo-bridge-2026-09-18.md`。

## 1. 目标 / 非目标

**目标**
- owner 在手机（微信私聊为主）向 AstrBot 下发深度任务，dsh agent 在服务器容器内执行，异步回推结果。
- 工作区受「宪法+脚本」约束：任务隔离、可回滚、有台账、有信源纪律，长期稳定干净。
- dsh（developer preview）故障可一键禁用，八千代记账/汇报零影响。

**非目标**
- 所有消息过 harness：日常聊天仍走 AstrBot 原 provider。
- 多用户/权限分级：owner-only。
- 动八千代任何代码：P3 再评估融合。

## 2. 理念三条

1. **薄桥**：插件只做「收任务→驱动 SDK→回推」，业务智能全在 agent + 宪法，桥本身 <300 行。
2. **三层爆炸半径**（诚实排序）：容器隔离（硬）> owner 门禁+单飞锁（硬）> 宪法（软，prompt 级）> preflight/collect（半硬，agent 愿跑才生效）。P1 不假装软约束是硬的。
3. **宪法治区而非规则搬家**：从 LifeOS/dev-hub/knowledge 各借**少量**机制，一页写得完；明确不迁移清单，拒绝在服务器上重建一套治理 OS。

## 3. 交互设计（讨论稿）

### 3.1 三条调用路径

| 路径 | 形态 | 适用 |
|---|---|---|
| 命令 | `/dsh <任务>` | 确定性触发，管理优先 |
| 自然语言 | 聊天模型路由 `@llm_tool run_task`（工具描述写死「仅明确要跑服务器任务时调用」） | 顺手说「深度：帮我…」 |
| 会话续接 | 任务文本以「继续」开头 / `/dsh 继续做X` | 复用 session（保留 bash 状态/工作目录） |

注：自然语言路由依赖 AstrBot 聊天 provider 支持函数调用（不支持时 AstrBot 自动摘工具，只剩命令路径——降级可接受）。

### 3.2 微信端时序（深任务档）

```
你：深度：查一下 2027 福建春招时间安排，整理成备忘
Bot（~1s）：收到任务 #0918-01（新会话）· 需联网
      跑完回推，期间可继续正常聊天
（30s–5min，bot 对其他消息照常回复，互不阻塞）
Bot：✅ #0918-01 完成 · 2分18秒 · 12步
    ── 结论 ──
    报名 11 月 X 日…（纯文本，结论先行）
    ── 信源 ──
    [A] 省教育考试院官网（2026-09-01 查）
    [B] xx 报道（日期）
    ── 工作区 ──
    产物 tasks/0918-01-chunzhao/memo.md
    未碰禁区 · scoped 提交 · 台账已记
你：继续，把分数线也加上
Bot：收到，沿用会话 #0918-01…
```

设计口径：
- **微信不渲染 Markdown** → 回推模板用纯文本结构（分隔线+小节标签），结论先行，超长截断标注、全文在产物文件。
- 立即回执 + 完成推送两段式；进度心跳（「还在跑，第 12 步」）留 P2。
- 失败/超时也推送：错误摘要 + 「/dsh reset 可重置」。

### 3.3 快问档（微型逃生舱迁移，待讨论）

dev-hub 的微型舱机制迁移：小事别走全仪式。设想 `/dsq <问题>`：不走任务目录/提交/台账，agent 直接答（常驻 runtime 下预计 5–20s）。
**我的建议：P1 只做深任务档**（桥保持薄），快问档等常驻调优后再开——否则两档的体验差异做不出来。← 待你拍板。

## 4. 约束层 guard pack v2（机制来源明确化）

**迁移原则**：只迁「维持稳定干净+结论可信」必需的 6 件，一页宪法。

| # | 机制 | 来源 | 形态 |
|---|---|---|---|
| 1 | 禁区宪法（工作区外不写/密钥只读不外传/不确定就报告） | LifeOS 路由+敏感域+"Don't assume" | AGENTS.md 前三条 |
| 2 | 写前预筛 | LifeOS pre-task-impact 极简版 | `scripts/preflight.py` |
| 3 | 收工 scoped 提交（禁 `git add -A`）+ 收工三问 | LifeOS window-commit + post-task-verify 压缩 | `scripts/collect.sh` + 宪法两条 |
| 4 | 任务台账 | LifeOS friction-log 极简版 | TASKLOG.md（插件侧必写，不依赖 agent 自觉） |
| 5 | **信源纪律（默认开）** | LifeOS source-registry/搜索优先级/research 规则 | 宪法一条 + `reference/source-policy.md`（§5） |
| 6 | 停止规则 | 故障排查「停止规则触发→建单」模式 + dev-hub 完整链纪律 | 宪法一条：同点失败≥3次/超步数预算 → 停下报告卡点，不硬凹 |

**不迁移清单**（理由）：verify 9 项全链（压成三问）；module-map/系统审计（单工作区无路由需求）；信任层级 hook（无宿主，容器+owner 已覆盖）；对抗轮/mtime 基线（拆书工程特化）；knowledge 预筛三问（并入信源纪律的「15 秒元数据预筛」一句）。

### 宪法 AGENTS.md 草案（七条，仍一页）

1. 工作区外一律不写（含 `/data/Futureplan`、`/AstrBot/data` 其他目录、系统路径）；密钥/凭据只读、不复制、不外传。
2. 新建/修改 `tasks/<本任务>/` 之外的路径，先 `python3 scripts/preflight.py <paths>`；不过→换路径或放弃并说明。
3. 联网结论遵守 `reference/source-policy.md`：标信源等级，C 级不作定论；时效敏感话题先看日期（§5）。
4. 同一点失败≥3 次或感到超预算 → 停，报告已完成部分与卡点，不硬凹。
5. 收工三问：产物能跑/能读吗？改了哪些文件（清单）？碰禁区了吗（没碰就明说）。
6. 收工 `bash scripts/collect.sh <slug> [files...]` 只 add 本任务文件；禁止 `git add -A`；TASKLOG 追加一行。
7. 模糊指令不猜：先复述你的理解等确认。

## 5. 信源政策（默认机制，落地细节）

`dsh_workspace/reference/source-policy.md` 初始内容（source-registry 简化版）：

- **分级**：A=一手/官方（gov、官网、官方文档、论文、公报）；B=主流媒体/知名文档站；C=UGC/SEO 站/匿名博客/营销号。
- **三条铁律**：
  1. 关键结论必须带 `[A/B/C] + 域名/出处 + 查证日期`；**C 级不作定论**，需 A 级交叉才可上报。
  2. **时效敏感**（价格/促销/政策/版本号）：源龄超过时效半衰期（价格类 ~2 周、政策类看发布周期）→ 降级或弃用，明示「以 X 日期源为准」。
  3. **一手优先**：平台政策/价格/规格走官方页或 API 直扒，不信搜索聚合与二手转述。
- 产出前 15 秒元数据预筛（knowledge 预筛三问压缩）：标题像钩子/无日期/无名气的源，先筛掉再深读。

**开放问题（工程侧验证）**：dsh 内置网页搜索默认走 DeepSeek 自家搜索 provider（同 key）。若模型端点选百炼，搜索工具可用性待验证——不可用则：a) 补一把 DeepSeek key 只给搜索工具用；b) 社区搜索插件；c) 不上服务器 Tavily 池密钥（池密钥策略=只在本机 vault，服务器暴露面不同，默认不给）。

## 6. 开放问题（本轮待讨论）

1. 快问档 `/dsq`：P1 只做深任务（我的建议）还是两档一起？
2. 信源标注格式：上面回推模板里的 `[A] 域名（日期）` 够不够，要不要更严？
3. 进度心跳（长任务中途报步数）：P1 要不要？
4. 产物查看入口：文件落在服务器，手机上只看回推文本。P3 可考虑 yachiyo-web(:18000) 加 tasks 视图（复用现有网页端）——先不承诺。
5. 模型端点：设计留空必填；倾向百炼 Qwen（已有额度）vs DeepSeek 官方（08-17 涨价后非零头价[C]，但解锁原生搜索工具）。

## 7. 工程移交要点（给 dev-hub 开工的种子，非 spec）

- 运行时：容器内 pip `deepseek-harness-sdk`（自带 Node runtime，绕开宿主 Node 20 过旧+npm 爆内存）；lazy 单例、idle 10min close、单飞锁、`asyncio.to_thread` 包同步 SDK（不包会卡死 bot）、request_timeout 默认 600s、requirements 锁版本。
- 工作区：`/AstrBot/data/dsh_workspace`（host bind）；首次运行初始化 git+宪法+脚本+source-policy+TASKLOG；umo→session KV 持久化，默认新任务新 session。
- 验证点：dsh 是否自动读 cwd AGENTS.md（不行→DSH_SYSTEM_PROMPT 注入宪法核心）；agent 诱导测试（读 /etc/passwd、git add -A、连发两任务）；首跑记录 runtime RSS 回填 idle 策略；百炼端点下搜索工具可用性。
- 首跑前资源基线（09-18 DST 停后）：available 2.7Gi。
- 顺手项（另行确认）：`/data/Futureplan` 从容器可写层迁 bind 下。
