# yachiyo-tts-bridge

Windows 本机 GPT-SoVITS TTS 桥（CONTRACT §2 实现）。stdlib-only，Python 3.12，零 pip 依赖。
对外暴露 OpenAI `chat/completions` 形状端点（`127.0.0.1:9881`），对内监督 GPT-SoVITS `api_v2.py` 子进程（`127.0.0.1:9880`），游戏运行时自动卸载显存、退出后自动回载。

## 布局

```
bridge.py               # 桥本体（单文件 stdlib-only）
test_bridge.py          # unittest（零 GPU 零网络，引擎全 mock）
config.example.json     # 配置样例（真实配置不放 git）
install/install_nssm.ps1    # 方案一: NSSM 服务
install/install_task.ps1    # 方案二: 计划任务
install/frpc.toml.example   # frp 隧道客户端配置样例
```

## 快速启动（手动）

```powershell
# 1) 生成真实配置并手填 token
Copy-Item config.example.json E:/DATA/YachiyoRuntime/bridge/config.json
notepad E:/DATA/YachiyoRuntime/bridge/config.json   # token 从 CHANGE_ME 改为部署值

# 2) 前台跑起来（NSSM/计划任务之前先这样验证）
python bridge.py --config E:/DATA/YachiyoRuntime/bridge/config.json

# 3) 验证（另一终端）
curl http://127.0.0.1:9881/health
```

token 仍是 `CHANGE_ME` 时 bridge 拒绝启动（退出码 2），防止裸奔上 frp 隧道。

## 安装（守护，二选一）

- **NSSM 服务（推荐）**：`powershell -ExecutionPolicy Bypass -File install/install_nssm.ps1`
  —— 崩溃 10s 自动重启、stdout 轮转日志、开机自启。
- **计划任务**：`powershell -ExecutionPolicy Bypass -File install/install_task.ps1`
  —— 开机自启 + 每小时兜底触发（进程死了最长 1h 拉起；要秒级守护用 NSSM）。

两个脚本都会在 config.json 不存在时从样例生成并停下提示手填 token，不会带占位值安装。

## frp 隧道

复制 `install/frpc.toml.example` 为 frpc 客户端的 `frpc.toml`，手填 `auth.token`，
确认包含 `[[proxies]] name="yachiyo-bridge" type="tcp" localPort=9881 remotePort=9881`。
服务器侧 frps（fit-frps, bindPort 7400, proxyBindAddr=127.0.0.1）已存在，勿改。

## 配置要点（config.example.json）

| 键 | 说明 |
|---|---|
| `token` | X-Bridge-Token，与 router 同值，部署时注入 |
| `engine.*` | 引擎 python/api_v2 路径、权重绝对路径、超时（合成请求 `request_timeout_s` 默认 30s） |
| `game_processes` | 判忙进程名单（默认 r5apex.exe），tasklist 5s 探测 |
| `vram_threshold_mib` | 卸载完成副判据（默认 2500） |
| `reload_debounce_s` | 游戏消失后回载 debounce（默认 45，可调 30-60） |
| `rate_limit_rpm` / `max_text_len` | 6 RPM 滑窗限速 / 120 字符闸 |
| `keywords` | style_context 四档映射关键词（ja/zh/en），sad 命中→tender 素材 |

**api_v2 启动方式注意**：实测 `api_v2.py` 的 CLI 只有 `-a`(bind_addr)/`-p`(port)/`-c`(tts_config yaml)，
**没有**权重 CLI 参数（api_v2.py:134-136）。桥以 `-a 127.0.0.1 -p 9880` 启动引擎，
就绪后通过 `GET /set_gpt_weights`、`GET /set_sovits_weights`（api_v2.py:545-565）热载 yachiyo 权重。

## 测试

```powershell
python -m unittest test_bridge     # 零 GPU 零网络，引擎走 mock transport
python -m py_compile bridge.py test_bridge.py
```

覆盖：strip、120 字符闸、四档映射+miss、限速滑窗、请求解析、响应形状、
32k→24k 重采样（输出头 24000/1ch/16bit）、心跳字段、busy 卸载调用序/回载 debounce/崩溃重启。

## 回滚

```powershell
# NSSM:  nssm stop YachiyoBridge; nssm remove YachiyoBridge confirm
# 计划任务: Unregister-ScheduledTask -TaskName YachiyoBridge -Confirm:$false
# 停引擎子进程随桥退出（/control/shutdown 或杀桥进程均可）
# frpc 删 yachiyo-bridge proxy 段即可断隧道；frps 侧无任何改动需要回滚
```

## 警示

- **`test_hooks.force_state` 仅测试用**（none|busy|loading）：非 none 时强制覆盖运行状态，
  用于 router/插件联调矩阵模拟 busy/loading。生产环境必须保持 `none`，
  否则真实状态被掩盖（该 busy 不卸载、该 ready 报 503），排障后请立即改回。
- 日志不落 token/sk-key；`YachiyoRuntime/` 下仅写 `heartbeat.json`、`bridge/` 运行目录与引擎 stdout 轮转日志。
