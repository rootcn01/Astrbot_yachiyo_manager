# dev-hub 任务包 · 八千代语音混合双引擎部署 · v1 定版（2026-09-20）

> 执行依据=《fine-tune-deploy-handoff-2026-09-19.md》§2 方案 v2（已过对抗 PASS_WITH_FIX）+ 本包固化资产。设计决策勿重议，实现在此基础上做。
> 资产状态：**A 模型定版 v1**（用户判词三轮胜出）；宽带/哀腔/唱歌=已判负，进 §6 v2 清单不阻塞本包。

## 1. 固化资产（E:\DATA\YachiyoRuntime\）

| 路径 | 内容 |
|---|---|
| `weights/gpt_yachiyo_v1.ckpt` | GPT（yachiyo_A_char-e15） |
| `weights/sovits_yachiyo_v1.pth` | SoVITS（yachiyo_A_char_e8_s848） |
| `prompt_map.json` | happy/tender/default/sad(→tender 暂代) 四档 + 文本 + 路径 |
| `prompts/prompt_{default,happy,tender}.wav` | 推理参考（3.7-4.5s，≥3s 硬下限） |
| 心跳契约 | `heartbeat.json` 每 60s 写（last_synth_at/mode/ts）——watchdog runbook §7 判据 C 已预立 |

引擎环境：`F:\AIPart\GPT-SoVITS\GPT-SoVITS-v2pro-20250604\`（api_v2.py 由 bridge 以子进程监督；显存预算 4GB；卸载=`/control?command=exit` 杀子进程零 fork）。

## 2. 三件组件（实现范围）

1. **yachiyo-tts-bridge**（本机 Windows，127.0.0.1:9881）：监督 api_v2 子进程（127.0.0.1:9880）；加载定版双权重；style_context→prompt 三档关键词映射（miss 永落 default，**sad 落 tender**）；输出重采样 24k/16bit/mono 与 MiMo 同形；60s 心跳；游戏判忙（进程名单 r5apex.exe 起+显存<2.5GB 副）时忙拒+卸载、退出后 30-60s 回载期间报 loading；X-Bridge-Token+限速 6RPM；speech_text>120 字符直接 400 让 router 走 MiMo；strip ♪/markdown。
2. **yachiyo-tts-router**（服务器宿主机 systemd，bind 172.19.0.1:8800）：MiMo API 形状反代；bridge ready→转发（**转发前剥 `audio.voice` 参考字段**，省 ~954KB/次）；bridge 忙/挂/loading/mode=cloud→原样转发 api.xiaomimimo.com（鉴权头透传）；探测 30s/连失 2 次=down/connect 2s/总超时 8s；静默回落不播报。
3. **voicemode tiny 插件**（AstrBot 新插件，不碰现有 MiMo 插件）：`/voicemode auto|local|cloud|status`（owner=1010233339 门控）；status 显示模式/bridge 态/两引擎今日计数/判忙原因。**现有 MiMo 插件只改 config base_url→`http://172.19.0.1:8800/v1` 一行，零代码补丁。**

## 3. 上线前服务器核验（两项）

1. mimo_official_client 对 `http://` base_url 无强制 TLS；
2. astrbot 容器→172.19.0.1:8800 连通性。

## 4. 安全

bridge 绑 127.0.0.1+token+限速；router 绑 docker 网桥；frp remote port UFW+安全组双封；frpc-frps token；Clash 加 `IP-CIDR,110.40.182.106/32,DIRECT`；本机电源=睡眠从不。

## 5. 测试矩阵（验收=全绿）

auto×5 态（ready/busy/loading/down/mode=cloud）/ local 明确报错 / cloud 直通 / 游戏退出 60s 回载 / 插件重装后 base_url 回归 / 微信+QQ 双平台×双引擎各 3 条 / **三句 AB 盲听（bridge vs MiMo V2）用户终审** / 延迟 p50≤5s p95≤8s / 回落≤15s 无感 / 回滚：`/voicemode cloud` 一键，终极=base_url 改回+restart astrbot。

## 6. v2 优化清单（下版本，不阻塞本包）

- **BD 宽带说话语料**（用户决策中，通常版 SNCL-00122+外置蓝光光驱）→ 重训解锁电话音+哀腔素材+宽带 prompt 三合一；届时 prompt_map sad 升真哀腔档。
- 12-26 ツクヨミ感謝祭 YT 直播录档（yt-dlp 配方见 handoff §3.3）。
- B1 桥接 W2 回收（backlog 🟡）随本包部署自动触发验收。
- 唱歌线（so-vits-SVC）仅当用户点名才开。

## 7. 实现注意事项（血泪坑）

users.pth 打包机路径（若动引擎目录必改写）/ 训练或推理 prompt ≥3s / Windows 服务化用 NSSM 或计划任务（bridge 守护）/ 心跳只认 last_synth_at 不认进程存活 / api_v2 子进程 stdout 日志轮转。

## 8. 实施收口与终审判词（2026-09-20 晨，ZCode /dispatch 窗）

- **实施**：三件组件全量落地（`Yachiyo_Project/yachiyo_tts_deploy/`，契约+实现+23/23×2 单测；异家族审查 cursor grok 两轮 FAIL→PASS_WITH_FIX，余项当场清）。全链路实测 200/p50 1.9s/p95 5.5s，auto×5 态矩阵全绿，§3 双核验过。git：03871f1+02e4318（push 443 挂账）。
- **用户终审（AB 三句盲听）**：bridge **勉强可以**；**MiMo 质量判负（太烂）**——听感排序反转（此前口径 MiMo 通透占优）。
- **处置**：v1 不切 base_url、不上生产；本机侧停用（计划任务 Disable+引擎孤儿清+显存释放），服务器 router 保留。质量优化=v2 BD 宽带重训（§6 首项，handoff §3.2 已论证唯一解）。
- **v2 唤醒路径**：Enable 双计划任务 → 换 `E:\DATA\YachiyoRuntime\weights\` 新权重 → base_url 切换（runbook §4）。bridge 已胜 MiMo，差的只是质量绝对值。
