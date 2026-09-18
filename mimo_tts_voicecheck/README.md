# MiMo TTS 音色复刻 · 验证与接入方案（2026-09-18）

> 状态：**Phase 0 已裁决（2026-09-18 深夜）**——`jp3_style`（日语+贴耳风格指令）用户判定「挺像」；裸合成、中文跨语言均不像。
> 🆕 **相似度优化线（2026-09-19）**：链路全通但用户持续判「不像」→ 调研/诊断/方案见 [optimization-research-2026-09-19.md](optimization-research-2026-09-19.md)（H1 带宽坐实 5kHz + 官方闹钟 App 09-18 上线 + 本机 4060Ti 微调路线；分阶段决策门在内，**勿绕过该报告直接开工**）。
> 🆕 **人设符合前提（2026-09-19 用户拍板）**：语音说话方式优化方案见 [persona-fit-optimization-plan-2026-09-19.md](persona-fit-optimization-plan-2026-09-19.md)（导演 prompt v3 全文 ready，四条 v2 违人设项修正+主旨保真+长度分级；含 style_tags 念白坑修复后的重听要求）。

## ⭐ 冻结配方（Phase 1 照此，勿改语言）

| 项 | 值 |
|---|---|
| 参考音频 | `recutB_yachiyo_dense.wav`（**2026-09-19 盲测胜出版**：candidate_01 压缝版 14.9s，静音缝压至 ~0.28s；本地 `candidates/`，服务器 `voice_refs/1789757000000000000_yachiyo_dense.wav`，旧 01 原版保留未删） |
| 风格指令（default_context） | `用温和、轻柔、贴着耳朵说话的语气，语速稍慢，像闹钟语音那样。` |
| **输出语言** | **一律日语（用户规则 2026-09-18：八千代语音调用都用日语，不用中文）**。中文只做文字回复 |

Phase 1 的语言适配：bot 文字回复是中文、语音必须日语 → TTS 前需要一步「中文回复 → 日语朗读文本」。市场插件的「发送前 AI 语音导演」（`ai_style_director`，可配 prompt，输出 style_context + speech_text）正好兼任：导演 prompt 里写死「把回复译成自然的日语口语、套用冻结风格指令」。

## 0. 免费口径（已核，一手信源）

| 来源 | 更新日期 | 原文关键句 |
|---|---|---|
| 按量付费定价页 mimo.mi.com/docs/zh-CN/price/pay-as-you-go | 2026-08-06 | 「mimo-v2.5-tts、mimo-v2.5-tts-voiceclone、mimo-v2.5-tts-voicedesign **限时免费**」 |
| Token Plan 订阅文档 mimo.mi.com/docs/zh-CN/tokenplan | 2026-07-15 | 「TTS 系列模型限时免费，**不消耗套餐 Credit**」 |

- **结论：现在调 voiceclone = 0 元**，不扣 Token Plan Credits、不扣余额。控制台「账单明细」可查用量（0 费用记录）。
- 「限时」无截止日公告（2026-09-02 的 beta-extended 新闻是 UltraSpeed 模型，与 TTS 无关）→ 随时可能转收费，但验证和试用成本为零。
- 免费≠无限：voiceclone 限 **RPM 100 / TPM 10M**，单次输出上限 8K tokens（长文需分段）。
- **ASR 不免费**（mimo-v2.5-asr ¥0.5/小时）：以后若做"语音输入给八千代"，那条路是花钱的。

## 1. API 事实（与官方文档 / 过审插件源码三方一致）

- 端点：`POST https://api.xiaomimimo.com/v1/chat/completions`（OpenAI 兼容；鉴权 `api-key` 头或 `Authorization: Bearer` 均可）
- 模型：`mimo-v2.5-tts-voiceclone`
- 请求体：`messages=[{role:"user", content:风格指令(可省)}, {role:"assistant", content:要念的文本}]`，`audio={"format":"wav","voice":"data:audio/mpeg|wav;base64,..."}`
- 响应：`choices[0].message.audio.data` = base64 WAV；`finish_reason=content_filter` 表示内容过滤拦截
- 参考音频：mp3/wav，base64 后 ≤10MB；**每次请求随发，平台不存音色 ID** → 固定用同一段参考文件 = 音色跨调用一致，参考文件必须自己永久留档

**用哪把 Key（官方 API 接入 FAQ 已核）**：两种 key 相互独立、不可混用——
- **按量付费 key（`sk-` 开头）**：控制台 → API Keys 页申请，走标准端点 `api.xiaomimimo.com/v1`（全部官方示例与社区插件的默认路径）
- **Token Plan key（`tp-` 开头）**：Token Plan 页专属 key，走订阅专属 Base URL，**仅在套餐有效期内可用**（到期即失效）

→ **本项目用 `sk-` key**。TTS 两条路都免费、成本零差别，但 sk- 与你的 Token Plan 完全解耦：不碰 Coding 额度，套餐过期/换档不影响 bot 发声，端点零配置。若按量侧报 402（要求余额才能调免费模型），退路 = 换 tp- key + 把 `MIMO_BASE_URL`（脚本）/`base_url`（插件）改成 Token Plan 专属地址。

## 2. Phase 0：本机验证"像不像"（不碰 AstrBot，10 分钟）

**你提供两样**：
1. **MiMo API Key**：控制台 → **API Keys 页**创建的**按量付费 `sk-` key**（不是 Token Plan 页的 tp- key，理由见 §1 末尾）。给法二选一：设 `MIMO_API_KEY` 环境变量，或写进本目录 `api_key.txt`（已被 .gitignore 挡住，不会进 git）。
2. **参考音频**：八千代目标声线的干净人声片段。要求：单人、无 BGM 无噪音、**10–30 秒**、语气贴近日常说话（不要播音腔朗读，模型会连语气一起学走）、mp3/wav。命名 `reference.wav`/`reference.mp3` 放本目录。

**跑**：`python mimo_voice_check.py`（零依赖）→ `outputs/` 出三个 wav：
- `test1_bare`：裸合成，**和原声比相似度（主判据）**
- `test2_style`：带风格指令，判指令跟随
- `test3_persona`：八千代汇报语感

**不像怎么办（按序）**：
1. 换更长更干净的参考段（30s 干净人声 > 5s 嘈杂段）
2. 参考段换成像微信聊天的语气录/剪的一段
3. 降级路线：`mimo-v2.5-tts-voicedesign` 用文字描述造声线（无版权问题，但跨次一致性无保证）——改造脚本把 MODEL 换掉即可

## 3. Phase 1：接入 AstrBot（服务器，Phase 0 过了再动）

### 3.1 平台适配点（先确认，这是最大变数）

市场过审插件 **astrbot_plugin_mimo_tts_clone v0.7.2**（Justice-ocr，11★，8-21 仍在更）功能最全（Pages 音色管理/授权上传/多音色/情绪路由/试听诊断/供其他插件复用的 synthesize_text()），**但 `support_platforms` 只声明了 aiocqhttp（QQ/OneBot）**，它的语音投递链路（base64:// Record / NapCat shared_path）都是 QQ 侧的。八千代是微信端 → 先到服务器确认：

```bash
docker exec <astrbot容器> cat /AstrBot/data/cmd_config.json | grep -A3 platform   # 或直接看 WebUI
```

确认微信适配器是哪个（gewechat / wechatpadpro / 公众号 / 其它）+ 它能否发 Record 语音。**按结果三条路**：

| 路 | 条件 | 做法 |
|---|---|---|
| A | 适配器支持 Record 语音 | 装市场插件，改/放 `support_platforms` 限制试一把；不行就 fork 它只改投递层 |
| B | 适配器不支持 Record | 用插件的 `synthesize_text()` 复用接口，音频走 yachiyo-web(:18000) 出播放链接（顺手实现 P3 想法） |
| C | A/B 都别扭 | 自写薄插件（<200 行）：照抄其 `core/mimo_official_client.py` 的调用模式（本方案 §1 就是全部接口事实），挂 yachiyo_manager 旁边 |

### 3.2 路 A/C 共同的接入步骤

1. WebUI → 插件市场 → 搜 mimo → 安装
2. 配置：`api_key`（base_url 默认 `https://api.xiaomimimo.com/v1` 即可）、模型默认 voiceclone
3. Pages 上传**和 Phase 0 同一段**参考音频 → 试听诊断（和本机 test1 应当一致）
4. 先开**命令朗读**（手动触发），验收微信端收到语音；再考虑自动语音化（建议先低概率或仅 owner 私聊，微信对高频语音有风控）
5. AstrBot 版本要求 `>=4.16.0,<5`（过审插件声明；自写插件无此约束）

### 3.3 密钥纪律

- key 只进服务器上的 AstrBot 插件配置，不进 git、不进本仓、不写进回推文本（对齐 dsh 设计 §5 的 tavily key 纪律）
- 本机侧 `api_key.txt`、参考音频、`outputs/` 都被本目录 `.gitignore` 挡住

## 4. 风险与边界

- **限时免费可能结束**：转收费时账单明细可查，届时按单价再决定去留（届时可对比火山 ICL/CosyVoice）
- **声音版权**：只克隆有权使用的声线；插件免责声明同款要求。自用低风险，合成内容勿公开分发
- **长文**：单次 8K tokens 输出上限，长汇报要分段合成
- **资源**：TTS 插件是纯 API 调用，无本地模型，容器 avail 2.7G 完全无压力（dsh 那条线才是吃内存的）

## 5. Phase 1 部署实录（2026-09-18 深夜，已上线待验收）

> ⚠️ **工程链欠账**：本补丁在 LifeOS 会话内直接设计上线，未走 dev-hub 完整链（已记 friction-log）。语音链验收收口后，补丁包（设计说明+diff+重放脚本+回滚）交 dev-hub 补课；候选产出 = 向上游 AstrBot 提 PR（issue #6797）。

**路线落定**：市场插件 `astrbot_plugin_mimo_tts_clone` v0.7.2 + weixin_oc 适配器 6 行补丁。

| 项 | 落点 |
|---|---|
| 插件 | 服务器 `/AstrBot/data/plugins/astrbot_plugin_mimo_tts_clone`（v0.7.2，日志确认加载、`mimo_tts_speak` 工具注册） |
| 配置 | `plugin_data/astrbot_plugin_mimo_tts_clone/config.json`（持久层，覆盖 AstrBot schema 侧同名配置；内容=sk-key+冻结风格+日语导演 prompt+auto_tts 关） |
| 音色 | `voice_refs/1789746704193329400_yachiyo.mp3` + `voices.json`（name=八千代，global_default 已设，consent=true） |
| **weixin_oc 补丁 v2** | `send_by_session` Record→**原生语音条**：wav→(pysilk)→silk 24k→iLink 上传 media_type=4→item type=3 `voice_item{media,encode_type:6,sample_rate:24000,playtime}`；silk 不可用退 mp3(encode_type=7, ffmpeg)，再退 File 卡片。原/补丁件存 `data/patches_backup/`（容器 recreate 后重放：`sudo docker cp <patched> astrbot-astrbot-1:/AstrBot/astrbot/core/platform/sources/weixin_oc/weixin_oc_adapter.py && sudo docker restart astrbot-astrbot-1`）+ 容器内已 `pip install pysilk-mod`（也已追加进插件 requirements.txt） |
| 重启 | 单次 23:52，bot 恢复正常 |

**验收**（等用户）：微信私聊八千代发 `/tts おはようございます、八千代です。` → 应回文字+一个 `voice_xxx.wav` 文件（点开即播；微信 leg 的语音只能以文件气泡送达，QQ leg 是原生语音）。过了之后：开 `auto_tts_enabled`+概率、把 owner id 填 `admin_users`。

**遗留**：① 适配器补丁在容器可写层，镜像升级会丢（重放命令在上表）；② 服务器有个**旧账**报错（今日 11:44 起）：知识库 Yachiyo_Project 绑定的 `text-embedding-v3` provider 不存在（现有的是 qwen3.7-text-embedding），与本次无关，要修在 AstrBot 知识库设置里换 embedding；③ `mimo_tts`/`mimo_stt` 两个内置 provider 早已有人配好（tts_config 为空=未启用，不冲突）。

**「语音条」终局定论（2026-09-19 凌晨，证据闭环）**：iLink 服务端**当前对 bot 账号静默丢弃 VOICE item**——不是字段问题。证据链：①[Tencent/openclaw-weixin#209](https://github.com/Tencent/openclaw-weixin/issues/209)：同一套实现 2026-06 前气泡正常、之后静默失效（服务端收紧）；②[#215](https://github.com/Tencent/openclaw-weixin/issues/215)：两位开发者穷举 encode_type×采样率×playtime 单位×aes_key 形态全排列，全部 API success、全部不渲染（真实入站字段已实测：encode_type=4、16000Hz、16bit、playtime=ms——我们补丁已完全对齐仍无效）；③全生态无任何成功案例、三个语音 PR 全挂起、官方零回应。**终态**：适配器补丁 v3 = Record 默认降级**文件卡片**（微信里点开即播）；原生语音路径保留成休眠开关（容器内 `touch /AstrBot/data/weixin_voice_native_enabled` 即启用，等腾讯重开）。AstrBot 自带 TTS 入口与本链同汇于 Record 投递点，同样受限。可选后续：把「真实入站字段实测值」贴到 #215 当数据点、补丁包交 dev-hub（含向上游提 File-fallback 改进 PR 的素材）。

## 5b. QQ leg 闭环（2026-09-19 01:02，用户已验收「可以正常语音」）

- bot QQ=2725576624（月見ヤチヨ），凭据在 LifeOS `reference/secrets/qq-bot-credentials.md`
- NapCat 已补 HTTP server（onebot11 config httpServers:3000，无 token；重启导致过一次掉线扫码，已恢复）
- 全链一次通：QQ 私聊 `/tts` → AI 导演（日语+贴耳风格）→ MiMo 克隆合成 → NapCat 原生语音气泡
- owner 个人 QQ=1010233339（admin_users 候选）
- 微信=文件卡片（iLink 上限）、QQ=原生气泡，双通道定稿

## 6. 本目录清单

| 文件 | 作用 |
|---|---|
| `mimo_voice_check.py` | Phase 0 验证脚本（零依赖，stdlib only） |
| `spectral_check.py` | 参考音频带宽取证（numpy+ffmpeg；新素材验收必跑） |
| `api_key.txt`（你创建） | API Key，gitignored |
| `reference.wav|mp3`（你放入） | 参考音频，gitignored |
| `outputs/` | 合成产物，gitignored（含 `ab_2026-09-19/` 试听包） |
