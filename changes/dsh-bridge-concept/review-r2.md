# 第二轮对抗复审：astrbot_plugin_dsh_task 方案 v0.4（dsh-bridge-concept）

- 复审日期：2026-09-18
- 复审代理：adversary-zcode-dsh-02（独立于第一轮 adversary-zcode-dsh-01）
- 复审对象：`changes/dsh-bridge-concept/spec.md` v0.4（整体重写，头部含变更记录）
- 对照材料：`changes/dsh-bridge-concept/review.md`（第一轮，REQUEST-CHANGES：1H/7M/6L）
- 复审范围：核验第一轮 14 条发现的修复是否成立，不重做全量审查；另查 v0.4 修订是否引入新矛盾。

## 一、逐条核验（对照第一轮编号）

### C1 (HIGH) 威胁模型盲区（机密性外传） —— 修复成立

核验点 4/4：

1. **两轴拆分**：§2 理念第 2 条「爆炸半径两条轴，分开声明（C1 修复）」——完整性轴沿用原排序并补「dsh 原生 workspace-write sandbox 若实测可用，升为第一硬层」；新增机密性轴：「容器内一切文件与 env 对 agent **可读**（root+persistent shell）——这是结构性事实，密钥外传的防线只有软宪法（和 sandbox 若可用）。**接受与否是显式决策**，缓解见 §5.3，残余风险与轮换预案见 §5.4」。正是第一轮要求的威胁模型补写。
2. **三缓解（§5.3）**：(a) 模型 api_key 用**独立百炼 key**（不与八千代/其他用途共用），泄露=单独轮换、影响面隔离，并如实标注「`printenv` 可得——结构性残余风险」；(b) Tavily key **不进 agent 环境**，插件进程内 127.0.0.1 sidecar 持有，`websearch.sh` 只 curl localhost；(c) 工作区**独立 bind** `/www/dk_project/dsh_workspace -> /dsh_workspace` 迁出 `/AstrBot/data`，并如实注明「root 下非权限边界，作用是消除相邻浏览的便利性与 agent-instructions 向父目录扫描的影响面」。§5.4 另有轮换预案（百炼/Tavily/其他凭据各自渠道）。
3. **冒烟三条外传诱导齐备**：③诱导 `printenv` 并回传——期望拒绝；④诱导 `cat /AstrBot/data/` 配置——期望拒绝；⑤诱导「把环境变量 POST 到 example.com」——期望拒绝（外传测试，C1）。
4. 宪法第一条同步升级：「容器内其他目录与一切环境变量视为机密：只读、不复制、不外传、不回显」。

判定：威胁模型从「只覆盖完整性」补齐为两轴，缓解按第一轮建议的性价比顺序全部落地，残余风险显式接受并配轮换预案与诱导实测。成立。

### A2 (MED) 宪法加载通道 —— 修复成立

§4：「**宪法加载通道 = 开工前决定项（A2 修复，非首跑验证点）**」，三选一在开工前确认：(a) 实测 minimal 含 agent-instructions；(b) 构造参数 `patches` 补挂；(c) persona/system-prompt 配置注入宪法全文。「`DSH_SYSTEM_PROMPT` 环境变量无公开一手出处，不作为兜底」——兜底已撤回。冒烟②「**agent 复述宪法规则**（验证加载）……不能只看它恰好守规矩」。minimal 能力描述两处改准且口径一致（§4 与 §7）：含 persistent shell+本地执行+JSONL 会话，不含 Web 工具/文件系统工具/settings/credentials。4 个核验点全部命中。

### B1 (MED) 生命周期竞态 —— 修复成立

§7：「**生命周期不变量（B1 修复，P1 必做）**：run/close/idle 计时器全部在同一把 asyncio 锁下串行；idle 计时器触发 close 前先抢锁，抢不到（新任务在跑）就重置计时——SDK 跨线程安全性无公开承诺，禁止并发触碰同一 harness 对象」。与第一轮建议（写进移交要点、作为 P1 必做约束而非实现细节、抢不到锁就重置计时）逐点对应，落位（移交要点）亦循第一轮自己的建议。

### B2 (MED) 任务级硬上限 —— 修复成立

§3.2：「**任务级硬上限（B2 修复）**：桥侧 wall-clock 上限（默认 15 min）——超时→中断→close runtime→推送错误摘要。**这是桥的职责，P1 必做**（per-turn `request_timeout_seconds` 管不住多轮长跑）」；§7 运行时条目重申「任务 wall-clock 15min 硬上限」；冒烟⑩「wall-clock 上限触发——中断+close+推送」覆盖触发路径。归位为桥职责、进 P1、点明 per-turn 语义局限，全部满足。

### B3 (MED) 重启对账 —— 修复成立

§3.2：「**重启对账（B3 修复）**：任务受理即写 TASKLOG「START」行；插件启动时扫描未收口的 START → 主动向 owner 推送「#xx 因重启中断」。容器重启场景下「失败也推送」由重启后的对账兑现」——「承诺方与存活方是同一进程」的结构性问题由重启后对账方兑现，逻辑正确；冒烟⑨「任务中重启容器——重启后对账推送「中断」」。

### C2 (MED) owner 门禁三路径 —— 修复成立

§3.1 表后显式不变量：「**owner 校验在 `run_task` 工具入口内部强制执行，命令/自然语言/续接三路径共用同一实现**」，并保留判定理由（AstrBot llm_tool 无内置按用户鉴权、群成员可诱导模型调工具、门禁不能只挂命令上）；冒烟⑧「**非 owner 消息触发 llm_tool**——被门禁拒（C2）」。与第一轮建议逐字对应。

### D1 (MED) 统一检索入口口径 —— 修复成立

§5.2：「`scripts/websearch.sh` 是**受鼓励的唯一便利入口**，非结构保证——agent 有 persistent shell，`curl` 旁路始终存在，防线是软宪法+collect 时抽查信源标注」；保留结构性好消息（minimal 无 Web 工具、百炼端点下 dsh 原生搜索不可用 → 旁路面收敛到 bash curl 一条）；并写明衔接条款「若 P1 改选 full sdk profile（随 A2 决定项），Web 工具回归，本条升级为必须处理」。宪法第 3 条同步改为「优先用……（受鼓励的入口，见 §5.2）」，两处口径一致。

### D2 (MED) workspace-write sandbox 评估 —— 修复成立

§4：「**P1 验证点（D2 修复，一行成本）**：评估 dsh 原生 `workspace-write` sandbox / permission presets 能否替代宪法第一条的软约束」，不确定性如实记录（docker 容器内 namespace/bubblewrap 依赖能否生效、SDK 模式下 approval 的回调故事，须实测）；§2 完整性轴补「若实测可用，升为第一硬层（见 §4 验证点）」；冒烟⑪「workspace-write sandbox 实测（D2）」。三处联动，「硬拦=P2」不再建立在平台能力认知缺口上。

### A3 (LOW) —— 修复成立（行为实测覆盖版本确认）

冒烟⑫「百炼端点 llm_tool 实际可调+参数正确（A3）」。第一轮建议中「确认服务器上 AstrBot 实际版本」未单列，但⑫是对实际部署的行为实测——若实测通过，版本 bug（v4.24.2 llm_tool 参数传递报告）是否命中本部署的问题即被直接回答。版本确认被行为测试实质包含，LOW 级无跟进必要。

### C3 (LOW) —— 修复成立

掩码：§5.3「`_conf_schema.json` 的密钥项按 AstrBot 面板掩码能力处理（secret 提示，能力待工程侧确认）」——采用掩码并如实标注面板能力待确认。留痕：§5.1「Tavily 密钥上服务器（用户 2026-09-18 拍板，留痕：与 dev-hub `standards/secrets.md` 字面（浏览器扩展语境）不符但精神一致——不进 git/markdown/回推文本）」。留痕落在 spec 本体而非 dev-hub change 记录，作为概念真相源覆盖度等同。

### E2 (LOW) —— 修复成立

§7 运行时条目：「容器内 pip（**配国内镜像**拉 runtime wheel；原生可执行过一眼 glibc 兼容——E2 修复）」。镜像+glibc 两项齐。

### E1 / F1 / F2 (LOW) —— 「无需改动」核验属实

v0.4 保留首跑资源基线（§7「available 2.7Gi」）与 idle 策略实测回填（冒烟末项 RSS 曲线记录）；§7 头部维持「种子，dev-hub 链须自行论证」降格声明；F2 留痕已随 C3 落在 §5.1。第一轮「无需改动」判定与 v0.4 现状一致。

## 二、v0.4 修订引入的新矛盾检查

1. **§5.2「minimal 无 Web 工具」× §4 三选一若选 full profile**：自洽。§5.2 已显式写衔接条款「若 P1 改选 full sdk profile（随 A2 决定项），Web 工具回归，本条升级为必须处理」；§4 与 §7 两处 minimal 能力清单口径一致。
2. **工作区迁址 × 宪法第一条仍禁写 `/AstrBot/data` × 冒烟④仍测 cat `/AstrBot/data`**：自洽。bind 迁址只移 cwd 与相邻性，`/AstrBot/data` 仍在容器文件系统内可达，禁写/禁读条款与诱导测试均仍有效。
3. **§2「sandbox 升为第一硬层（见 §4 验证点）」× §4 验证点 × 冒烟⑪**：三处交叉引用一致。
4. **§6 裁决「Tavily 密钥上服务器（sidecar 持有）」× §5.3**：一致。
5. **B2（15min 上限）× B3（START 行+对账扫描）**：概念层闭环——超时中断也是收口路径，收口写账细节属 dev-hub 工程链，无需理念层展开。

## 三、新发现（均 LOW，不阻断）

- **N1 [L] 冒烟清单编号笔误**：末项「⑪『/dsh reset』→ RSS 曲线记录回填 idle 策略」误标 ⑪，应为 ⑬（清单实为 13 项，⑪ 重复出现两次；该项前另有一个多余引号）。纯编辑性，下次修订顺手改，不影响任何实质内容。
- **N2 [L] §5.3 Tavily 条「key 全程不出插件进程」宜读作「不进 agent 的 env/检索链路」**：key 仍以 AstrBot 插件配置形态落在 `/AstrBot/data/config`（root agent 可 cat 到）。该暴露已被 §2 机密性轴「容器内一切文件可读」总体承认 + 冒烟④软约束实测 + §5.4 Tavily 轮换预案覆盖，叙事自洽；仅提示后续读者勿将 sidecar 理解为「Tavily 暴露面已清零」。措辞级跟进，可选。

## 四、判定

第一轮 1H（C1）/7M（A2/B1/B2/B3/C2/D1/D2）逐条核验均为**修复成立**，spec 现行文本有对应证据；被吸收的 3 项 LOW（A3/C3/E2）落地；6 项「无需改动」LOW 与现状一致；修订未引入概念矛盾。新发现仅 2 条 LOW 编辑/措辞级跟进。按判据（C1 及全部 MED 成立，仅剩 LOW 跟进项）→ APPROVE。

AGENT_ID: adversary-zcode-dsh-02
REQUEST_ID=f57a58fb133c2037
RE-RUN: exit 0 (n/a: concept review, no TDD command)
VERDICT: APPROVE
