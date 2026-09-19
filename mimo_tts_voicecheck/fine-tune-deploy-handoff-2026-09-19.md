# 八千代语音 · 微调+混合部署 · 交接简报（2026-09-19 10:40）

> 给新 session 的完整上下文。**任务模式不变**：调研诊断先行；小改项目内；大改出任务包交 dev-hub；MiMo 保留兜底。运维真相源=LifeOS `reference/dst-dedicated-server.md` §11。

## 1. 现状一句话

MiMo 零样本链全通且已优化到头：V2 参考（闹钟 App 演示 9 句纯 solo）已上生产、导演 v3（人设符合前提）已上线、5 群白名单已开。**用户判词链：旧参考「不像」→ V2「还行」→ v2.1 混 register「炸了」= 零样本天花板已到。用户已拍板走微调线（GPT-SoVITS，本机 4060Ti）+ 混合双引擎部署。**

## 2. 部署方案 v2（已过对抗，PASS_WITH_FIX 修正全吸收）

**拓扑**（插件零补丁，只改 config 一行）：

```
AstrBot 插件（config base_url → http://172.19.0.1:8800/v1）
  → 服务器宿主机 yachiyo-tts-router（systemd，~200行：MiMo 形状反代）
      ├─ bridge 健康(ready) → frp 隧道 → 本机 yachiyo-tts-bridge(127.0.0.1:9881)
      │                            └─ 监督 GPT-SoVITS api_v2 子进程(127.0.0.1:9880)
      └─ 忙/挂/loading/mode=cloud → 原样转发 api.xiaomimimo.com（含鉴权头透传）
```

**关键设计点**（对抗修正后）：
1. **不做插件 main.py 补丁**（base_url 本就是持久配置）；**不装第二个 GPT-SoVITS 插件**（工具注册冲突）；新 tiny 插件只做 `/voicemode auto|local|cloud|status`（owner 门控）。
2. **显存按 4GB 预算**（v2ProPlus 实测口径，8G 卡与 Apex 不能共存）。判忙=游戏进程名单（初始 r5apex.exe，/voicemode game add 扩）+显存<2.5GB 副判据。卸载=bridge 调 `/control?command=exit` 杀 api_v2 子进程（显存全释放，官方无 unload 接口，零 fork）；游戏退出后监督重启回载（30-60s，期间报 loading 不路由）。
3. **风格映射**：MiMo 的 style_context 在 GPT-SoVITS 无通道 → bridge 解析关键词映射三档参考 prompt（happy/tender/default，从训练集挑 3-6s 片段+转写文本，外置 prompt_map.json，miss 永落 default 不拒请求）；输出重采样 24k/16bit/mono 与 MiMo 同形。
4. **回落参数**：探测 30s/连失 2 次=down/connect 2s/bridge 总超时 8s/loading/busy 不路由；router 转发 bridge 前剥 `audio.voice` 字段（省 ~954KB/次上行）。
5. **安全**：bridge 绑 127.0.0.1+X-Bridge-Token+限速 6RPM；router 绑 172.19.0.1（docker 网桥，公网不可达）；frp remote port UFW+安全组双封；frpc-frps 启用 token。
6. **看门狗协调**：bridge 每 60s 写心跳（last_synth_at），watchdog runbook 需 v4 修订增判据「last_synth_at<30min=BUSY」（只认合成时间不认进程存活）；**短期先文档化：挂看门狗当晚=cloud 语音**。
7. 静默回落（用户拍板）；`/voicemode status` 显示模式/bridge 态/两引擎今日计数/判忙原因。
8. 回滚：一键 `/voicemode cloud`；终极=base_url 改回 + restart astrbot。
9. 上线前服务器核验两项：mimo_official_client 对 http:// base_url 无强制 TLS；astrbot 容器到 172.19.0.1 连通性。
10. L 级护栏：speech_text>120 字符直接走 MiMo；strip ♪/markdown；Clash 加 `IP-CIDR,110.40.182.106/32,DIRECT`；本机睡眠=从不；完整测试矩阵见本简报对抗记录（auto×5 态/local 明错/cloud/游戏退出 60s 回载/插件重装 base_url 回归/双平台×双引擎）。

## 3. 下一 session 工作队列（按序）

1. ~~**数据集挖掘**~~ ✅ **2026-09-19 第二班完成+第三班增补**：主集 `finetune_dataset/` **106 片 / 289s 终稿**（p2 角色 50 / bd 谈话 48 / bc 正式 8）+ 3 prompt + `yachiyo.list`（faster-whisper 正日文）+ README。**翻案**：P2 整包=八千代语音包（ECAPA 定案，resemblyzer 无区分度弃用）；BD 三簇=三 CV 各一，早見=c2；MiMo ASR 只能 auto。扩量首选=买 BD 特装版。
   - **转写交叉校对毕**（whisper×MiMo 双 ASR+带角色提示词重转写三方裁决）：17 处修正（八千夜→八千代/縁も竹縄→宴もたけなわ/ヤチオ→八千代/犬同士 等，`corrections.json` 52 条含依据）、3 条存疑保留原版、2 条串音疑点终裁剔除（p2_049 问答同片/bd_028 语体突变搭腔）。
   - **同 CV 补充集** `finetune_dataset_natural/`（早見本人广播「Memories & Discoveries」2026-06-09 期自然语域）：2h 源→w900 干净锚（其余 6 窗实为歌曲/纯音乐被转写证伪）→ASR 文本筛剔歌/幻觉/嘉宾→ECAPA 逐片+块纯度→beam5 定稿，**134 片/561s 独立成包**。混训占比勿超 30-40%，推理 prompt 永用角色域。
   - **同 CV 可行性口径**（用户问「大差不差？」）：可行但要打折——ECAPA 实测同 CV 跨语域 0.33 ≈ 不同 CV 同域 0.30-0.44，语域拖动与身份同量级；建议 A/B 训练（角色 only vs 角色+补充）再定配比。
2. ~~**训练**~~ ✅ **2026-09-19 第四班完成（本机 4060Ti）**：整合包 v2pro（20250604，魔搭直链 8.19GB；**2026-09-19 已迁 `F:\AIPart\GPT-SoVITS\GPT-SoVITS-v2pro-20250604\`**（用户 AI 工具惯例位，E 盘减负 33G；users.pth 已改写、A 权重推理冒烟通过；安装包 .7z 已删可重下））；无头训练驱动 `tools_p2_mining/train_yachiyo.py`（复刻 webui 四步 prep+双训练，断点分步）。**A 模型**（纯角色 106 行）与 **B 模型**（+34% 同 CV 自然域 161 行，`finetune_dataset_ab/` 仅 list 入库、wav 可再生）各 ~25 分钟跑完。**AB 试听包**=`outputs/ab_finetune_2026-09-19/`（A/B×3句×3 prompt 档 + MiMo V2 同文基线，ASR 回环 3/3 过）**等用户判词定配方**。
   **本班四坑**：①整合包 `runtime/.../users.pth` 硬编码打包机路径（D:\BaiduNetdiskDownload\...）须改写成本机包路径否则 `No module named 'text'`；②数据集目录必须**平铺 wav**（脚本取 basename 拼 inp_wav_dir，子目录全静默丢）；③`gpu_numbers` 必须 "0"（"0-0"=同卡双 rank DDP 死锁）、训练前须预建 `logs_s2_v2ProPlus/` 目录（s2 存档 shutil.move 不建目录直接炸）；④**`pretrained_s1` 是顶层 yaml 键**（我误放 train 子字典→GPT 77.6M 随机初始化，症状=输出恒 0.7s 截断+top_3_acc 卡 0.015；修复后 0.89+）。另：推理 prompt 必须 ≥3s；inference_cli 只写流式最后一片，拼接要直调 get_tts_wav。
3. **dev-hub 任务包**：按 §2 方案 v2 出 spec（router/bridge/voicemode 插件三件+测试矩阵+回滚）。
4. **watchdog runbook v4 修订**（判据 C）——与训练并行可做。
5. 验收：三句 AB（bridge vs MiMo V2）用户盲听终审；延迟 p50≤5s/p95≤8s；回落≤15s 无感。

## 3.1 判词与带宽修复线（2026-09-19 第五班）

- **一轮判词（用户）**：A（纯角色 106 行）整体好于 B（+34% 同 CV 自然域）→ **配方=纯角色域**，B 归档为对照。痛点=A/B「沙沙电话感」、MiMo「通透但抽风+情绪乱」（微调线上位理由再+1）。
- **根因量化**：A/B 输出 10kHz=-77~-83dB=训练源窄带复现（P2 f99≈3.9k/BD≈3.6k/natural≈2.2k）；MiMo -44dB（引擎全频段+高频外推）。
- **修复=VoiceFixer 带宽扩展训练集**（`tools_p2_mining/enhance_bw.py`，mode0，106 片，10kHz 提升 ~88dB，转写不变）→ **A_enh 重训**（`yachiyo_A_enh`，同配方）。客观验收：AENH 输出 10kHz=-38dB**优于 MiMo**、12kHz -54.8dB 同样领先；ASR 回环 3/3。
- **二轮试听包**：`outputs/ab_finetune_2026-09-19/` 新增 `AENH_s{1,2,3}_*.wav`（prompt 同用增强版），**等用户判词「通透度是否追平/超过 MiMo、音色有无损伤」**。过 → A_enh 权重进部署包；VoiceFixer 也可作为 bridge 输出侧兜底工具（模型已缓存 `~/.cache/voicefixer`）。
- **二轮判词（用户，2026-09-19 傍晚）= 带宽扩展线关闭**：AENH「感觉并没有变好，通透感没有增强，语气语速可能也有些问题，性价比不大；并没有比 MiMo 强，个人感官和原版差距不大」。**结论：客观指标（10kHz -38dB）与听感脱节——VoiceFixer 生成的高频不是她的高频身份证，指标涨听感不涨还带副作用；A_enh 不进部署，A（原始窄带训练）保持为微调线现役交付物。**「明显超过 MiMo」的真解锁=无损宽源；MiMo 相对微调的优势项也收敛为「音质通透」单点（稳定性/情绪一致性已输给 A）。

## 3.2 BD 素材调研结论（2026-09-19 晚，Qoder 窗，报告=LifeOS research/bd-source-survey-2026-09-19.md，正文仅本地）

- **买就买通常版 SNCL-00122（¥6,800≈￥290，animate+代拍+EMS 到手约 ￥365-380），别碰特装（到手约 ￥837）**：通常版已含本篇 140 分+迎宾广播全 5 条，音轨规格与特装逐字相同；特装增量（三人同轨评论轨=训练污染源 / 142 分剪辑版八千代增量小 / 特典 CD 被 ¥2,444 数字专辑覆盖）不值 2.5 倍价。CDJapan/Neowing 不取扱→只能日本国内下单+代拍转运；官方 5/15 点名转卖溢价勿付。
- **官方三处口径均未标 codec**（LPCM 是推断，到手 ffprobe 定）；**f99 判据对带伴奏混音失效**（官方样片也才 9.6-11.9kHz）——判高频改看 **dB@12k/16k**。
- **¥0 因果验证（第六班，已完成=负结果）**：iTunes 官方免 DRM 30s 样片（八千代独唱 Remember/星降る海）→ demucs 分离（人声轨 dB@10k=-27~-30dB 全带宽保住）→ 筛 5 片 40s 干净歌唱人声（剔 2 条 whisper 幻觉「ご視聴」+英文乱转+乱码）混训 **A_song**（106 原始+5 歌唱=12% 宽带占比）→ **输出 10kHz 仍 -78.9dB 与 A 持平；宽带歌唱 prompt 也无效（-84.4dB）**。**结论：补充式宽带混入修不动电话音——窄带在训练分布中占绝对主导，vocoder 跟主导走；宽带要起效必须占大头（BD 旁白 10min+ 混入后可达 65%+，样片 40s 无法验证该情形）。** 文件=`outputs/ab_finetune_2026-09-19/ASONG_*`。
- **决策收敛（用户二选一）**：①买通常版（≈￥365-380 到手）+外置蓝光光驱（选型另开 product-research）→ 总投入 ~￥700-900 解锁宽带说话声重训（预期电话音消失）；②不买，A 现状（像+稳、音质电话档）直接进部署，MiMo 回落保持。
- **买盘前置硬卡点=本机 0 光驱**（三路交叉验证）→ 需外置蓝光 combo（DVD 光驱读不了 BD，选型走 product-research 另窗，比盘可能还贵）。到手提取链已收敛：MakeMKV v1.18.4 含 AACS v82；eac3to 可省；**取 5.1ch 中置声道比立体声下混再分离干净**；迎宾广播在碟1不同 title 按时长区分；区域码 PC 抓取不受限。
- 墙外 BDMV/种子/网盘侧调研窗明确不做（合规边界，不影响正版侧结论）。OST 35 轨零人声勿为素材买。

## 4. 遗留与挂账

- git：Yachiyo_Project `693b9d2` 因 GitHub 443 间歇未 push（本地安全），网络恢复补推；其余无欠账（LifeOS 到 dd3d200、Yachiyo 到 bd9da4f）。
- AB 试听包旧判词（`outputs/ab_2026-09-19/` B 组多段参考、H3 导演对）用户未给——**已被微调线决策超越，可弃**。
- 情绪路由双音色（v2.1 失败后的 BD 干净活泼源路线）→ **被 §2.3 prompt 映射取代**，不再单独做。
- backlog（LifeOS 已记）：B1 桥接 W2 回收 🟡、L2 情绪深谈冲突、L3 跨轮语音密度、L4b proactive 语音。
- 素材库：`_tmp/bili_dl/`（P2/广播×5/评论轨，gitignored）；candidates/：`alarmP2_yachiyo_solo_v1.wav`（**现役生产参考**）、`alarmP2_yachiyo_mixed_v21.wav`（失败实验，留档勿用）。

## 5. 本 session 已固化的教训（勿重踩）

1. 子代理按标题认片会翻车（『全修。』事件）——素材必 ASR 验身。
2. 频谱验收必测原始流（先转 16k=自砍 8k+）。
3. 音频切分脚本帧/采样单位必须全程统一（MIN_CLIP 坑）。
4. 单一参考混 register=毒药（v2.1 炸音，HF 气声被学走）；register 差异用 prompt 映射解决。
5. BOM 纪律：cmd_config/插件 config 读 utf-8-sig 写普通 utf-8。
6. heredoc 后禁接 `||`（本窗又踩一次）。

## 6. 第二班追加教训（2026-09-19 晚）

7. **resemblyzer 在本域无区分度**：不同 CV 的同域音频也能 0.9（锚身份都会被带偏）——说话人归人一律 ECAPA（早見跨语域基线 0.331，同簇 0.6+，区分度够）。
8. **MiMo ASR language 强制码（ja/jpn/ja-JP/Japanese/jp）全部 400**，只能 auto（中日英乱漂）——训练转写走 faster-whisper large-v3-turbo（language=ja，CPU int8 可跑，质量完美）。
9. **MiMo ASR 并发 4 就吃 429**（且空内容返回=音乐/噪声段，不是错误）；断点续跑缓存必须跳过 `[ERR` 行。
10. ECAPA 权重 Windows 取回：speechbrain fetch 硬编码 symlink 会 1314 失败——hf_hub_download 后手动拷 `_tmp/ecapa/`（label_encoder.txt→label_encoder.ckpt 改名）。
11. **块纯度校准数字**：1.6s 块对锚余弦 solo=0.51-0.78、他人/串音多 <0.35 → 规则 utterance≥0.40 + 最差块≥0.35。
12. torchaudio 2.11 load 要 torchcodec——直接 wave 模块读+torchaudio.functional.resample 绕开。

—— 2026-09-19 ZCode 窗交接。方案对抗全记录在当窗对话；本文件为唯一执行依据。

## 3.3 音源勘源·实测闭环（2026-09-20 凌晨，双 subagent 调研+主席逐项验尸）

**YT 官方源（活，配方已破解）**：`yt-dlp --js-runtimes node --remote-components ejs:github --extractor-args "youtube:player_client=web_embedded" -f 140`（默认 androidvr 必 403）。实测：本編冒頭 5m42s=**11.2kHz 宽带**（但混人说：八千代旁白 31-60s≈13s + かぐや/彩葉对白，demucs 后 ECAPA 被混响压到 0.1-0.2 无法自动分人，只能内容判读取旁白段）；Remember MV=10.5kHz 全曲；niconico 官方同母带 192k 略优；**舞台挨拶类=PA 录音源头窄带（4.2k）死路**。**2026-12-26 ツクヨミ感謝祭 YT 免费直播（八千代 CV 出演）=未来宽带说话声来源，值得届时录档**。
**B站同 CV 清单（全灭）**：星見雅 rip=**中配**（绝区零国服≠早見）；ふり〜すたいる 96min 谈话=语种对但**母带窄带**（129k 容器装烂源 -131dB@10k）；綾華 29min=主体中配+6kHz。教训：**B站码率≠带宽，验源必跑频谱**。
**HF/ModelScope 数据集（假货）**：ichayc/Frieren1.1=两段 79s×2+四份 Copia 重复，whisper 转写呈「私は、私は」合成伪影，ECAPA 对真人早見锚仅 0.16-0.23（真人自比 0.97）——AI 生成物，弃；mextre/frieren=6 个重复 mp3 垃圾包。**无任何真早見原始数据集**（只有 RVC/VITS 权重）。
**radiko**：M&D 电台正片唯一官方回听渠道（日本 IP+账号，AAC~60k 估 10-14k），非角色声，中低优先级。
**结论：宽带「说话声」免费路径穷尽——BD 通常版从「最优解」升格为「唯一解」**；网易云 VIP 的现实用途=无损全曲 Remember/星降る海（宽带「唱」，12% 样片实验已证混入无害无益，更高占比可试但唱歌语域风险已知）。
