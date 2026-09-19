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

1. **数据集挖掘**（最长前置，工具全在位）：P2 全量八千代行（`tools_p2_mining/` 四脚本管线：切分→F0+声纹评分(recutB/新V2做锚)→逐条 ASR 归人）+ BD 评论轨八千代份额（31min 三人谈，同管线跑）。目标 10 分钟级干净 solo 语料。**归人标志**：神々のみんな/良きかな/物語を見届ける=她；かぐや自称第三人称=かぐや；かけあい段会骗过包络评分需 ASR 复核。
2. **训练**：本机 GPT-SoVITS v2ProPlus 整合包（4060Ti 8G：SoVITS bs1/GPT bs2，不跑 DPO；2-3h）或云新人券（趋动云 ¥168，0.5-2 卡时）。训练集另挑 3 条 prompt 片段（happy/tender/default）。
3. **dev-hub 任务包**：按 §2 方案 v2 出 spec（router/bridge/voicemode 插件三件+测试矩阵+回滚）。
4. **watchdog runbook v4 修订**（判据 C）——与数据挖掘并行可做。
5. 验收：三句 AB（bridge vs MiMo V2）用户盲听终审；延迟 p50≤5s/p95≤8s；回落≤15s 无感。

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

—— 2026-09-19 ZCode 窗交接。方案对抗全记录在当窗对话；本文件为唯一执行依据。
