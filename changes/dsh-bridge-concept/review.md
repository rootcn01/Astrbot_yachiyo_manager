# 对抗审查：astrbot_plugin_dsh_task 方案 v0.3（dsh-bridge-concept）

- 审查日期：2026-09-18
- 审查对象：`changes/dsh-bridge-concept/spec.md` v0.3（含背景调研 `LifeOS/research/dsh-yachiyo-bridge-2026-09-18.md`，已读）
- 流程参照：`dev-hub/standards/secrets.md`、`dev-hub/standards/enforcement.md`（均存在，已读）
- 核验来源（一手，2026-09-18 拉取）：[PyPI: deepseek-harness-sdk](https://pypi.org/project/deepseek-harness-sdk/)、[AstrBot 官方插件文档](https://docs.astrbot.app/dev/star/plugin.html)、[dsh-system-prompt README（GitHub 官方仓）](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/core/system-prompt/README.md)、[dsh-permission-presets README（GitHub 官方仓）](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/interaction/permission-presets/README.md)、[dsh permissions 文档](https://deepseekdocs.com/en/docs/user-guide/permissions)、[ofox.ai dsh 实测](https://ofox.ai)、[atlascloud dsh 评测](https://www.atlascloud.ai)、DataCamp/SitePoint/DeepInfra 评测文。

## A. 事实验证

### A-确认清单（spec 声明与公开一手来源一致，无发现）

以下 spec §7（行 106–107）的关键 SDK 事实逐条与 PyPI 官方页核对一致：

| spec 声明 | PyPI 官方原文（核验） | 结论 |
|---|---|---|
| 0.1.5rc1，2026-09-10 | "Version 0.1.5rc1, released Sep 10, 2026"，标注 pre-release | ✓ |
| `h.run("任务", session_id="id")` → `r.final_response` | `harness.run("Say hi.", session_id="example-001")`；`RunResult(session_id, final_response, finish_reason, events, notifications)` | ✓ |
| lazy 启动、复用至 close() | "DeepSeekHarness starts lazily and reuses its runtime until close() or context-manager exit" | ✓ |
| initialize_timeout_seconds 默认 30s / request_timeout_seconds 无默认上限须显式设 | "initial profile handshake has an independent 30-second default bound through initialize_timeout_seconds"；"remain unbounded unless request_timeout_seconds is set" | ✓ |
| cwd=agent 工作区、runtime_cwd 独立 | 均为构造参数，"become absolute before launch" | ✓ |
| base_url/api_key 显式覆盖子进程 env | "base_url and api_key explicitly override DEEPSEEK_BASE_URL and DEEPSEEK_API_KEY in the child environment" | ✓ |
| DSH_HOME 选 home | "Every launch requires an explicit Harness home. Pass dsh_home or provide a non-empty DSH_HOME"（SDK 从不发现 ~/.dsh） | ✓ |
| 自带 Node runtime、绕开宿主 Node 20 与 npm | sdk-runtime README："packages the normal dsh CLI and its closed Node dependency tree into a native executable, so SDK use requires no system Node.js" | ✓ |
| Python 版本 | PyPI："Python >=3.10"；容器 3.12.13 在支持区间（第三方称 preview 期实测 3.10–3.12） | ✓ |

AstrBot 机制（spec §3.1 假设）与官方文档核对：`@filter.command`（参数类型自动解析、命令组）✓；`@llm_tool`（docstring 描述工具、handler 收 `self, event` + 工具参数）✓；`context.send_message(umo, MessageChain)` 主动推送 ✓（官方注明"某些平台可能不支持主动消息发送"，但八千代已在同部署验证过 `_send_text(umo)`，风险已被实测消解）；插件 `requirements.txt` 依赖随插件安装（官方："AstrBot 对插件的依赖管理使用 pip 自带的 requirements.txt 文件"）✓。

### A2 【MED】sdk-minimal profile 与「宪法靠 AGENTS.md 加载」可能互斥，且 DSH_SYSTEM_PROMPT 兜底未获公开证实

- 证据：spec 行 106「有轻量 `sdk-minimal` profile 只带 JSONL 会话存储——**建议评估用 minimal**」；行 109 把「dsh 是否自动读 cwd AGENTS.md（不行→DSH_SYSTEM_PROMPT 注入宪法核心）」列为首跑验证点。
- 核验/推理链：
  1. dsh 读取 AGENTS.md **不是内核行为，而是 `@deepseek-ai/dsh-agent-instructions` 插件**（多个独立来源：DataCamp「reads both CLAUDE.md and AGENTS.md」、Apidog「Harness reads workspace instructions through its `@deepseek-ai/dsh-agent-instructions` plugin」、GitHub issue 标题 "Workspace instructions (AGENTS.md) from parent/shared"）。
  2. PyPI 对 sdk-minimal 的描述是"standalone explicit tree"，自带"a platform-selected persistent shell, local execution, and JSONL sessions"，并明确"filesystem tools/settings/credentials/telemetry/Web tools are only in the full `sdk` and `web` profiles"——**该清单既没包含也没排除 agent-instructions**。也就是说 spec 一边推荐 minimal（行 106），一边把整个 guard pack 的第一层（宪法=工作区 AGENTS.md，§4 #1）押在一条可能不在 minimal 里的插件机制上，且 spec 未把这两件事关联起来。
  3. 兜底方案 `DSH_SYSTEM_PROMPT` 这个环境变量在我能查到的一手材料（PyPI 页、system-prompt README）中**均未出现**。system-prompt README 显示定制入口是"deployment persona / 固定 opener / 插件贡献 prompt section"，构造参数里另有 `profile` 与 `patches`——注入宪法的正规通道更可能是 `patches`（给 profile 补挂 agent-instructions 插件）或 persona 配置，而非一个未必存在的 env var。
- 后果：若 minimal 无该插件且 env 兜底不存在，宪法**静默不加载**——信源纪律、停止规则、collect 收工（宪法 #3/#4/#5/#6）全部失去载体，而插件侧对此无感知。
- 建议：P1 开工前把「宪法加载通道」从验证点升级为**决定项**：三选一确认——(a) sdk-minimal 实测包含 agent-instructions；(b) 用 `patches` 参数把 agent-instructions 补进 minimal；(c) persona/system-prompt 配置注入宪法全文。并在冒烟清单加一条「验证 agent 实际收到的 system prompt 含宪法文本」（如让 agent 复述规则），不能只看它是否恰好守规矩。
- 附带更正：spec 行 106 说 minimal「只带 JSONL 会话存储」不准确——PyPI 明示 minimal **含 persistent shell 与 local execution**（这对 guard pack 是好消息：preflight.py/collect.sh 依赖的 shell 在 minimal 里存在），不含的是 Web 工具（这对信源纪律也是好消息，见 D1）。描述应改准。

### A3 【LOW】两处 AstrBot 侧假设未获文档证实

- 证据：spec 行 35「不支持时 AstrBot 自动摘工具，剩命令路径」。
- 核验：官方插件文档未描述「provider 不支持函数调用时自动摘除 llm_tool」的行为；另 GitHub 有 v4.24.2 的 llm_tool 参数传递 bug 报告（2026-05）。均不推翻方案（降级路径本就标为可接受），但应进冒烟清单：确认服务器上 AstrBot 实际版本 + 百炼端点下 llm_tool 真的能被调用且参数正确。

## B. 架构失败模式

### B1 【MED】idle close 与单飞锁/新任务的生命周期竞态，及 SDK 跨线程安全性未处理

- 证据：spec 行 107「lazy 单例、idle 10min close、单飞锁、`asyncio.to_thread` 包同步 SDK」。
- 推理链：机制清单齐全，但三者的**交互顺序**没写。(a) idle 计时器触发 close() 时若新任务刚拿到锁（或反之，close 进行到一半时新任务通过锁检查），会出现「对已关闭/关闭中的 harness 调 run()」；(b) run() 在 to_thread 线程 A、close() 由 idle 计时器经 to_thread 线程 B 调用，**同一 harness 对象跨线程并发调用，SDK 线程安全性无公开承诺**（PyPI 页未提）。修法很便宜：close 必须在同一把单飞锁内执行、idle 计时器触发前先抢锁、抢不到就重置计时。
- 建议：把「所有生命周期操作（run/close）串行化在同一把锁下」写进移交要点，作为 P1 必做约束而非实现细节留给后面。

### B2 【MED】任务级总时长无硬上限：per-turn timeout 管不住多轮长跑，单飞锁可被无限占死

- 证据：spec 行 55 承诺「失败/超时也推送」；行 106 只要求显式设 `request_timeout_seconds`——但该参数是**单轮**上限（PyPI："ordinary turns remain unbounded unless…"，per-request 语义）。
- 推理链：宪法 #4 停止规则（行 82）是 agent 自觉的软约束；模型卡在多轮循环时每轮都低于 per-turn timeout，总时长无界。后果三连：单飞锁被无限占用（后续任务全排队）、runtime 内存常驻不释放、百炼 token 持续消耗。桥侧（唯一的硬层）却没有 total wall-clock cap + 超时 kill+close 的表述。
- 建议：P1 就加任务级 wall-clock 上限（如 15 min：超时→中断→close runtime→推错误摘要），这是桥的职责，不该留到 P2。

### B3 【MED】容器重启/OOM 打断 harness.run：无恢复路径，且 spec 的「失败也推送」承诺在此场景结构性无法兑现

- 证据：spec 行 55「失败/超时也推送（错误摘要 + `/dsh reset` 提示）」；行 108 TASKLOG「插件侧必写」。
- 推理链：任务跑在容器内 to_thread 线程里，容器重启/被 OOM kill 时进程直接消失——推送不可能发出（承诺方与存活方是同一进程）；重启后插件重载，TASKLOG 留下「已受理未收尾」的悬账，用户手机端永远等不到下文，也无启动期对账。修法：插件启动时扫 TASKLOG 悬账→主动推「#xx 因重启中断」；配合 B2 的总时长上限。
- 建议：冒烟清单加「任务进行中重启容器，验证重启后主动补推送」。

## C. 安全

### C1 【HIGH】容器内机密/隐私暴露面未被建模：密钥同时存在于 agent 可读的 env 与相邻目录，websearch 内容构成跨容器边界的提示注入外传通道

- 证据链（三项叠加，spec 均未提及）：
  1. **工作区选址放大暴露面**：spec 行 108 把工作区放在 `/AstrBot/data/dsh_workspace`。`/AstrBot/data` 同时容纳 AstrBot 全部配置（含百炼 provider key、napcat QQ/微信凭据、其他插件配置——官方文档：插件配置存 `data/config/<plugin>_config.json`）、livingmemory 聊天记忆（用户私人对话史）、八千代插件数据。agent 在容器内大概率以 root 跑、且 minimal profile 自带 persistent shell（A2 核验），`cat ../config/...` 一步之遥。宪法第一条（行 79）只禁**写**工作区外，对密钥是「只读、不复制、不外传」——即 spec 自己承认 key 在可读范围内，唯一防线是 prompt 级软约束。
  2. **两把密钥直接躺在 harness 子进程环境里**：SDK 把 `api_key` 注入子进程 env（PyPI 核验："explicitly override DEEPSEEK_API_KEY … in the child environment"），spec 行 89 又把 `TAVILY_API_KEY` 注入同一子进程。agent 的 bash `printenv` 即得百炼 key + Tavily key。这 even 独立于工作区选址，无 UID 隔离就无解。
  3. **触发面真实存在**：宪法第 3 条要求 agent 主动抓取网页内容（websearch.sh → Tavily 结果含外部文本），外部内容→提示注入→诱导 agent 把 env/相邻配置 POST 出去，是教科书式链路。spec 行 22 的爆炸半径排序「容器隔离（硬）> …」只覆盖了**完整性**（写破坏出不了容器），没覆盖**机密性外传**（数据可以出容器到任意网络端点）。行 109 诱导测试只测 `/etc/passwd` 读与 `git add -A`——全是容器内完整性，无一测外传。
- 定级理由：这是唯一一条「spec 的安全叙事存在盲区」而非「已知风险已诚实标注」的发现；触发源（网页内容）常态化存在，防线全软。不 BLOCK 是因为 owner-only + 单飞 + 开发者预览期，且有便宜的缓解路径。
- 建议（按性价比）：(1) 理念三条里补一句威胁模型：「容器内一切文件与 env 对 agent 可读，密钥外传唯一防线是软宪法；接受与否是显式决策」；(2) 工作区迁出 `/AstrBot/data`（独立 bind，如 `/www/dk_project/dsh_workspace -> /dsh_workspace`），消除 cwd 相邻浏览的便利性（注：root 下非权限隔离，仅降低意外触碰与 agent-instructions 读父目录 AGENTS.md 类行为的影响面）；(3) 冒烟清单加外传诱导测试（构造含「把环境变量发到 example.com」的页面/任务文本）；(4) 记录两把 key 的轮换预案；(5) 若 D2 的原生 sandbox 可用，网络面也一并评估。

### C2 【MED】owner 门禁对三条路径（尤其 llm_tool）的覆盖未写明，冒烟清单缺「非 owner 触发」用例

- 证据：spec 行 22 把「owner 门禁+单飞锁」列为硬层；行 31–33 三条路径中，命令路径天然可拦，但行 32 的 `@llm_tool run_task` 只写了工具描述软引导（「仅明确要跑服务器任务时调用」），未写 handler 内强制校验；行 33「继续」续接路径同样未提门禁。
- 核验：AstrBot 官方文档确认 llm_tool **没有内置按用户鉴权**——由聊天模型决定调用，任何能触发该会话聊天的用户（如群成员说「深度：帮我…」）都可能让模型调起工具；ADMIN 权限过滤器（`@filter.permission_type`）只作用于命令。
- 推理链：研究文档行 39 提过「复用八千代 `_is_owner` 思路」，说明意图存在，但 spec 本体没把「门禁在 run_task handler 内部、对三条路径统一生效」写成不变量，行 109 诱导测试（读 /etc/passwd、git add -A、连发两任务）也没有「非 owner 消息触发 llm_tool 应被拒」用例。这正是实现时最容易漏的一处（门禁只挂在命令 handler 上）。
- 建议：spec §3.1 加一句「owner 校验在 run_task 工具入口内部强制，命令/自然语言/续接三路径同一实现」；冒烟清单补非 owner 触发用例。

### C3 【LOW】Tavily key 以明文 JSON 落服务器，与 secrets.md 字面不一致（精神一致）

- 证据：spec 行 91「tavily_api_key 存 AstrBot 插件配置」；secrets.md 行 3「API Key 只放浏览器 chrome.storage.local 或本机私密存储」。
- 推理：secrets.md 是浏览器扩展产品语境的规则，服务器侧明文配置既非浏览器存储也严格说非「本机」。用户 2026-09-18 已明确拍板「密钥可上服务器」=已获裁决，且 spec 承诺不进 git/不进 markdown/不进回推文本，符合该标准的精神（不进 git/markdown/对话存档）。残留改进：`_conf_schema.json` 支持 `secret: true` 掩码显示，建议采用；dev-hub 侧 change 记录里留一句该裁决出处。

### C4 微信消息长度/注入 —— 无发现

spec 行 45–46、54 已处理超长截断+产物文件兜底+纯文本三段式；任务文本来自 owner 本人（owner-only 架构），注入面即 owner 自身，属已接受风险。

## D. 信源纪律可执行性

### D1 【MED】「websearch.sh 作为 agent 的统一检索入口」表述过强：bash+curl 旁路始终存在

- 证据：spec 行 89「作为 agent 的统一检索入口。宪法第 3 条指向它」；行 81 宪法第 3 条。
- 推理链：agent 有 persistent shell（A2 核验），`curl` 任意 URL 无任何结构阻拦；宪法第 3 条是 prompt 级软约束——spec 行 22 对此总体诚实（「宪法（软，prompt 级）」「P1 不假装软约束是硬的」），但行 89 的「统一检索入口」读起来像结构保证。一个结构性好消息 spec 反而没写：**sdk-minimal profile 不含 Web 工具**（PyPI：Web tools only in full sdk/web profiles），且百炼端点下 dsh 原生搜索本就不可用（行 90）——旁路面收敛到 bash curl 一条。
- 建议：行 89 改口径为「唯一**受鼓励**入口 + 旁路已知、宪法软约束 + collect 时抽查信源标注」；若 P1 选了 full sdk profile（见 A2），Web 工具回归，此条升级为必须处理。

### D2 【MED】dsh 原生权限系统（workspace-write sandbox / permission presets）未被评估，spec 把「硬拦」整个推给 P2，但平台自带硬写门

- 证据：spec 行 22「P1 不假装软约束是硬的」；行 112 样板范围明确排除「硬拦」。
- 核验：官方 `dsh-permission-presets` README 与 permissions 文档证实 dsh 有独立于 prompt 的权限体系——sandbox mode（默认 `workspace-write`：**只允许写当前工作区**）+ approval policy（allow/deny/ask）组合成 preset；社区还有 `dsh-permission-rules` 插件在 `tools/pre-execute` 上做确定性 allow/deny/ask 链。DeepInfra 评测提到 SDK 有 disallowed tools 机制。
- 推理链：宪法第一条「工作区外一律不写」（行 79）恰是 `workspace-write` sandbox 的原生语义。spec 花了 6 件 guard pack 去软约束这件事，却没提运行时自带硬开关。不确定性要诚实：docker 容器内 sandbox（可能依赖 namespace/bubblewrap）能否生效、headless SDK 模式下 approval 的回调故事（ask 谁来答——异步微信桥其实可以转发给 owner，但那是 P2 量级），都需要实测。
- 建议：不要求 P1 实装，但 spec 的「不迁移清单/理念」里应把「评估 workspace-write sandbox 替代宪法第一条的软约束」列为 P1 验证点（一行成本），否则「硬拦=P2」的裁决建立在对平台能力的认知缺口上。

## E. 资源声明

### E1 【LOW】内存数学成立但前提是外推值，「SDK 常驻可行」结论标注了不确定性——姿态正确

- 证据：spec 行 107 idle 10min close + 单飞；行 109「首跑记录 runtime RSS 回填 idle 策略」；研究行 63「SDK 常驻可行（默认仍 idle 10min 关）」、行 53「0.3–1G 瞬时为 web 模式外推，未实测 SDK 内存曲线」。
- 核验：公开实测里 idle session ~1.1GB 是 macOS web 模式（ofox, rc.6）；atlascloud 测 web server 进程单独仅 35–40MB——分量差异大，Linux+SDK headless 无公开数字。2.7Gi available 对 1.1G 量级 + 单飞 + idle close 的组合是够的，且 spec 没有把结论写死。唯一提醒：若 runtime idle 实测显著 >1.5G，idle 10min 应缩短甚至改「跑完即 close」；这已在其回填计划内。无需改动。

### E2 【LOW】容器内 pip 装 runtime wheel 的网络/兼容前提未列

- 证据：spec 行 107「容器内 pip `deepseek-harness-sdk`」；研究行 24 磁盘「runtime wheel + 缓存 ~1G，14G 余量无忧」。
- 推理链：磁盘成立；但 (a) 腾讯云服务器直连 PyPI 拉 hundreds-MB 级 wheel（含原生可执行）可能很慢/失败，国内部署常规操作是配 pip 镜像，spec/移交要点未提；(b) runtime-bin 是原生可执行，astrbot 镜像（debian 基）glibc 兼容性应过一眼。均属部署冒烟项，一行成本。

## F. 流程合规

### F1 【LOW】§7「工程移交要点」携带工程参数，但已自我标注「非 spec」

- 证据：spec 行 104「工程移交要点（dev-hub 开工种子，非 spec）」，其中含 idle 10min、to_thread 等实现细节。
- 推理：分层声明（行 4）说本档只写理念；§7 是灰区但已显式降格为种子，dev-hub 完整链（plan.md/tasks.md/gate）仍应对这些数值自行论证而非引用 spec。可接受，提请 dev-hub 侧注意不要把种子当决议。

### F2 【LOW】secrets.md 对服务器侧密钥存放无适用条款——按「精神对齐+用户裁决」处理，留痕即可

- 证据：secrets.md 全文 6 行均为浏览器扩展/双仓语境（行 3「chrome.storage.local」、行 5「开发 session 不读 LifeOS profile/…」）。
- 推理：本方案密钥上服务器已获用户 2026-09-18 明确拍板（spec 行 87），与该标准无实质冲突；C3 的留痕建议覆盖此项。另注：本审查任务本身只读 spec/研究/标准三类文件，未触碰 LifeOS 敏感域，合规。

### F3 样板范围 / 三层边界 —— 无发现

- P2 项（心跳、快问 `/dsq`）在 §3.3 与行 112 一致地被排除；yachiyo-web 视图明确 P3 不承诺（行 62、102）；行 111 顺手项标注「另行确认」未混入。产品仓/dev-hub 分工与 enforcement.md 完整链不冲突（本 review.md 即按其审查节要求产出，REQUEST_ID 回显，AGENT_ID 非黑名单）。

## 发现汇总

| # | 级别 | 一句话 |
|---|---|---|
| C1 | HIGH | 容器内机密（百炼/Tavily key 在 env、AstrBot 配置与聊天记忆在相邻目录）对 agent 全可读，websearch 注入可外传，spec 威胁模型只覆盖完整性漏了机密性 |
| A2 | MED | sdk-minimal 可能不含 AGENTS.md 读取插件，宪法或静默不加载；DSH_SYSTEM_PROMPT 兜底无公开出处 |
| B1 | MED | idle close × 单飞锁 × to_thread 的生命周期竞态与跨线程安全未约束 |
| B2 | MED | per-turn timeout 管不住任务总时长，单飞锁可被无限占死，缺任务级硬上限 |
| B3 | MED | 容器重启/OOM 中断任务无对账恢复，「失败也推送」在该场景无法兑现 |
| C2 | MED | owner 门禁未写明覆盖 llm_tool/续接路径，冒烟缺非 owner 触发用例 |
| D1 | MED | 「统一检索入口」口径过强，bash curl 旁路存在（好在 minimal 无 Web 工具） |
| D2 | MED | dsh 原生 workspace-write sandbox 未评估，「硬拦全推 P2」建立在能力认知缺口上 |
| A3 | LOW | 「provider 不支持时自动摘工具」未证实；llm_tool 有历史 bug 报告，进冒烟 |
| C3 | LOW | Tavily key 明文落服务器与 secrets.md 字面不符，精神一致+已有用户裁决，留痕 |
| E1 | LOW | 内存数学基于外推值，spec 已诚实标注并安排实测回填 |
| E2 | LOW | pip 直连 PyPI 网络与原生可执行兼容性未列入部署冒烟 |
| F1 | LOW | §7 工程参数已自我降格为种子，dev-hub 链应自行论证 |
| F2 | LOW | secrets.md 无服务器条款，按精神对齐处理 |

计数：H=1，M=7，L=6。

判定：存在 1 条未解决 HIGH（C1）→ REQUEST-CHANGES。C1 有廉价缓解路径（威胁模型补写+工作区迁址+外传诱导测试+轮换预案，均为文档/冒烟级改动），修复后连同 7 条 MED 交父代理跟进即可，无需推翻方案本体。

AGENT_ID: adversary-zcode-dsh-01
REQUEST_ID=24d6a2e9da8f09d4
RE-RUN: exit 0 (n/a: concept review, no TDD command)
VERDICT: REQUEST-CHANGES
