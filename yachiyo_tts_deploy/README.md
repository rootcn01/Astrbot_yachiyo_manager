# yachiyo-tts 双引擎部署 · 总 runbook（2026-09-20 v1 实施完成）

> 三件组件=bridge（本机）/ router（服务器）/ voicemode 插件（AstrBot）。接口契约见 [CONTRACT.md](CONTRACT.md)。
> 实施状态：**代码+部署+auto×5 态矩阵全绿；生产切换（MiMo 插件 base_url）留用户终审门**——见 §4。

## 1. 现役拓扑与进程（已部署在跑）

| 组件 | 位置 | 守护 | 验证 |
|---|---|---|---|
| yachiyo-tts-bridge | 本机 127.0.0.1:9881（代码 `bridge/bridge.py`，运行配置 `E:\DATA\YachiyoRuntime\bridge\config.json`） | 计划任务 `YachiyoBridge`（登录触发+60s 重试，`taskschd.msc` 可查） | `curl http://127.0.0.1:9881/health` |
| GPT-SoVITS api_v2 | bridge 子进程 127.0.0.1:9880，权重热载自 `E:\DATA\YachiyoRuntime\weights\` | bridge 监督（游戏判忙卸载/退出 45s 回载） | 同上（state=ready 即在） |
| frpc 隧道 | 本机 frp_0.61.1 → 服务器 frps:7400，映射 server 127.0.0.1:9881 | 计划任务 `YachiyoFrpc` | 服务器 `curl http://127.0.0.1:9881/health` |
| yachiyo-tts-router | 服务器 172.19.0.1:8800（`/opt/yachiyo-tts-router/`，配置 `/etc/yachiyo-tts-router/config.json`） | systemd `yachiyo-tts-router` | `curl http://172.19.0.1:8800/health` |
| voicemode 插件 | AstrBot `data/plugins/astrbot_plugin_voicemode/`（token 预置 `plugin_data/<同名>/config.json`） | astrbot 容器 | QQ 发 `/voicemode status` |

token 真值三处同源：`E:\DATA\YachiyoRuntime\bridge\config.json` ↔ `/etc/yachiyo-tts-router/config.json` ↔ AstrBot `plugin_data/astrbot_plugin_voicemode/config.json`（本机留档 `E:\DATA\YachiyoRuntime\bridge\token.local.txt`，均在 git 外）。

## 2. 已验证结论（2026-09-20 04:2x 实测）

- **全链路合成**：服务器→router→frp→本机 bridge→引擎→24k/16bit/mono WAV，200/1.4-2.7s。
- **延迟**：ready 态 p50≈1.9s / p95≈5.5s（n=5；目标 ≤5/≤8s，p95 达标余量大）。
- **auto×5 态矩阵**：ready✅ / busy✅（云回落 3.9s 实弹）/ loading✅（busy_reason=bridge_loading 实时）/ down✅（探测连失 2 次降级、云接管 9.8s、复线恢复）/ mode=cloud✅（直通 3.5s）。
- **local 明确报错**：502 `bridge_unavailable` 32ms，不上云。
- **安全面**：bridge 127.0.0.1+token+6RPM（429 实测）；9881 隧道口仅服务器回环（frps proxyBindAddr）；8800 仅 docker 网桥+UFW 172.19.0.0/16 窄域；frps 带 token。
- **异家族审查**（Cursor grok-4.6-xhigh 强席两轮）：一轮 FAIL（1H/14M/10L）→回修 22/22+3 自选；二审 **PASS_WITH_FIX**（F1-F22 确认落地，余 5M/8L 中 9 项当场清：热载超时 60s、云墙钟 120s、_resp_socket 回退链、500 固定文案、admin 先鉴权后读体、getresponse 分段超时、ExecStartPre grep -F、NVSMI 惯例位回退、插件 HTTPError close）。挂账不修：bridge 合成 30s vs router 8s 的锁占用差（静默回落不受影响，设计取舍）；owner_ids 待补微信 sender_id（见 §3）。
- **鉴权次序/闸门**（回修后实弹）：错 token+垃圾 body→401；raw>120 字（含可 strip 记号）→400；>512KB body→413；合成回归 200。

## 3. 已知非阻塞事项

- AstrBot 启动日志有一条 `provider.manager KeyError: 'type'`（deepseek-v4-pro provider 配置缺 type）——**预存问题与本部署无关**，默认模型 qwen3.8-max 正常。
- 计划任务为**登录触发**（注册 AtStartup/任意用户触发需管理员权限被拒）——机器重启后需用户登录一次才拉起 bridge/frpc；要开机即起（免登录）用 `bridge/install/install_nssm.ps1`（需管理员装 NSSM）。
- 本机 frpc 无独立守护崩溃重启（任务级 RestartInterval 60s 兜底）。
- 音频通道 AB 素材：`mimo_tts_voicecheck/outputs/ab_bridge_smoke_2026-09-20/BRIDGE_s{1,2,3}_default.wav`，与 `outputs/ab_finetune_2026-09-19/MIMO_V2_s{1,2,3}*.wav` 同文对拍。
- 待用户手做（安全 §4 尾巴）：Clash 加 `IP-CIDR,110.40.182.106/32,DIRECT`；确认本机电源「睡眠=从不」；把微信侧 sender id 补进 AstrBot `plugin_data/astrbot_plugin_voicemode/config.json` 的 `owner_ids`（当前仅 QQ 1010233339+AstrBot 管理员放行）。

## 4. 上线切换（用户终审门，一键两步）

前置：听一遍 §3 的 AB 三句（bridge vs MiMo V2），可接受才切。

```bash
# 服务器上：MiMo 插件 base_url 切到 router（备份先行）
sudo python3 - <<'EOF'
import json
p = "/www/dk_project/dk_app/astrbot/astrbot/data/plugin_data/astrbot_plugin_mimo_tts_clone/config.json"
raw = open(p, encoding="utf-8-sig").read()          # BOM 纪律：读 utf-8-sig
cfg = json.loads(raw)
cfg["base_url"] = "http://172.19.0.1:8800/v1"
open(p + ".bak_baseurl_20260920", "w", encoding="utf-8-sig").write(raw)
open(p, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))  # 写回普通 utf-8
EOF
sudo docker restart astrbot-astrbot-1
```

切完验收：QQ 发 `/voicemode status`（应显示 auto+bridge ready）→ 发 `/tts` 一条 → 服务器 `curl http://172.19.0.1:8800/health` 看 `today.bridge` 递增 → 微信/QQ 各发 3 条双平台矩阵。

## 5. 回滚（ anytime ）

- 一键：QQ `/voicemode cloud`（全量回云，不动配置）。
- 终极：base_url 改回 `https://api.xiaomimimo.com/v1`（用 §4 的 .bak_baseurl 备份）+ `sudo docker restart astrbot-astrbot-1`。
- 本机下线：计划任务禁用 `YachiyoBridge`+`YachiyoFrpc`；服务器 `sudo systemctl stop/disable yachiyo-tts-router`（或 `deploy_server.sh --rollback`）。

## 6. 测试矩阵剩余项（需用户参与）

- 三句 AB 盲听终审（素材就位）；微信+QQ 双平台×双引擎各 3 条（需切 base_url 后真实消息流）；游戏实测（r5apex 起时判忙卸载+退出 60s 回载——模拟已过，真机待验）；插件重装后 base_url 回归检查。

## 7. v2 清单（不阻塞，见 deploy-task-package §6）

BD 宽带语料重训 / prompt_map sad 升真哀腔档 / 12-26 感謝祭 YT 录档 / B1 桥接 W2 回收验收（本部署已自动触发其前置）。
