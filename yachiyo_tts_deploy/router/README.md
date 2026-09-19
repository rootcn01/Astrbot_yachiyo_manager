# yachiyo-tts-router

AstrBot TTS 分流路由器（CONTRACT §3 v1，2026-09-20）。Ubuntu 24.04 / Python 3.12 / **stdlib-only**，systemd 常驻，bind `172.19.0.1:8800`（docker 网桥，astrbot 容器可达）。

```
AstrBot 插件(openai SDK, base_url=http://172.19.0.1:8800/v1)
  → router(本件)
      ├─ TTS 形状 & mode 允许 & bridge ready → http://127.0.0.1:9881（frp 隧道 → Windows bridge → GPT-SoVITS）
      └─ 其余一切（非TTS/ASR/bridge 不可用/mode=cloud）→ https://api.xiaomimimo.com 原样透传
```

## 文件

| 文件 | 说明 |
|---|---|
| `yachiyo_router.py` | 路由器本体（单文件 stdlib） |
| `config.example.json` | 配置示例（`_note*` 字段为注释，程序忽略） |
| `test_router.py` | unittest，零外部网络（本地 mock 上游），`python -m unittest test_router` |
| `yachiyo-tts-router.service` | systemd 单元（`User=root`：绑 172.19.0.1 需该地址存在于宿主机 + 写 /var/lib、/var/log） |
| `deploy_server.sh` | 服务器部署脚本（幂等） |

## 部署

```bash
# 在本目录（router/）内，文件随仓库拷到服务器后：
sudo ./deploy_server.sh                 # 建目录、拷文件、生成 /etc 配置、enable --now、探活
sudo vi /etc/yachiyo-tts-router/config.json   # 注入 bridge_token（与 Windows 侧 bridge 同值，替换 CHANGE_ME）
sudo systemctl restart yachiyo-tts-router
curl http://172.19.0.1:8800/health      # 验活
```

注意：`172.19.0.1` 必须已存在于宿主机（astrbot 所在 docker 自定义网络拉起后才有）；service 单元的 `ExecStartPre` 会轮询等该地址出现（至多 60s），`StartLimitIntervalSec=0` 允许无限重试。探活失败时先 `ip addr show` 确认地址存在。

## 路由决策（POST /v1/chat/completions）

TTS 判据：JSON body 有**顶层 `audio` 对象**（ASR 的 input_audio 在 messages 里，不命中）。

| 条件 | 动作 | 日志 reason |
|---|---|---|
| body 非 JSON | 原样 bytes 透传云 | forward |
| 无顶层 audio（非 TTS） | 透传云 | forward |
| TTS + mode=cloud | 透传云 | forward |
| TTS + auto + bridge ready | 走桥：**剥 `audio.voice`**、加 `X-Bridge-Token`、connect 2s/总 8s | forward |
| TTS + auto + bridge busy/loading/down | 透传云（**原始完整 body**，含 voice） | probe |
| TTS + auto + 走桥非 200/超时 | 透传云（原始完整 body） | fallback |
| TTS + local + 桥可用 | 走桥 | forward |
| TTS + local + 桥失败（含 probe=down） | `502 {"error":{"message":"yachiyo local bridge unavailable","code":"bridge_unavailable","type":"router_error"}}`，**不上云** | fallback |
| 其余路径/方法（/v1/models 等） | 透传云 | forward |

透传 = 全头转发（Authorization 等全保留；剥 hop-by-hop：Connection/Transfer-Encoding/Keep-Alive/TE/Trailer/Upgrade/Proxy-*，另剥 Host/Content-Length/Expect/X-Bridge-Token——最后者防桥 token 外泄给云，由转发层重建/添加）+ body 原样 + 云响应原样回（状态/头/体，3xx 不跟随重定向）。透传整体墙钟超时 `cloud_timeout_s`（默认 60s，含读响应）。router 自有端点仅 `GET /health` 与 `POST /admin/mode`，其余一切（含对这两个端点的其他方法）都透传。

已知边界：客户端 chunked 请求体不支持（openai SDK 对 JSON body 恒发 Content-Length）；auto+ready 时桥挂会先耗最多 8s 再回落云。

## 探测语义

后台线程每 `probe_interval_s`(30s) `GET {bridge_url}/health`（connect 2s）：成功取 body.state（ready/busy/loading/down）；**连失 2 次判 down**（单次失败+成功即复位）；down 期间 auto 不试桥直接透传（省 8s 等待），local 直接 502。进程启动即先探一次，探测前状态 `unknown`（busy_reason=`probe_pending`，行为同非 ready）。

## 运维接口

- `GET /health`（无鉴权，绑定即防护）：`{"mode","bridge_state","today":{"bridge":n,"cloud":n},"busy_reason","last_fallback","ts"}` —— voicemode status 数据源。
- `POST /admin/mode`（头 `X-Bridge-Token`，与 bridge 同 token）：`{"mode":"auto|local|cloud"}` → `{"ok":true,"mode":...}`；错 token 401，非法值 400。

## 状态与计数

- `state_dir/state.json`：mode 落盘，重启保持（损坏/缺失回落 auto）。
- `state_dir/counters.json`：按日期键控（本地时区），只留今日+昨日；`today` 字段即当日引擎计数（**只计 TTS 形状请求**，非 TTS 透传不计）。
- 均原子写（tmp + rename），utf-8 无 BOM。

## 日志

`log_path`（默认 `/var/log/yachiyo-tts-router/router.log`），每请求一行，超 10MB 轮转 `.1`（留一份），同时回显 stderr 进 journald；**不含 token/sk-key**：

```
2026-09-20T12:00:00Z mode=auto engine=cloud status=200 ms=123 bytes=4567 reason=probe
```

`engine`=bridge|cloud；`reason`：forward=正常路由，probe=按探测态未走桥，fallback=试桥失败回落云。

## 回滚

```bash
sudo ./deploy_server.sh --rollback          # 停用服务 + 删单元/程序文件（保留 /etc 配置、状态、日志）
sudo ./deploy_server.sh --rollback --purge  # 连配置/状态/日志一起删
```

## 测试

```bash
python -m unittest test_router   # 21 个用例，零外部网络（bridge 与云均为本地线程 mock）
```
