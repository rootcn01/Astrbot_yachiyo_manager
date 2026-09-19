# yachiyo-tts 三件组件接口契约 v1（2026-09-20）

> 本文件=三组件并行实现的接口单一真相源。执行窗不得改写；实现与契约冲突时以契约为准并写回执"推翻点"。
> 依据：`mimo_tts_voicecheck/deploy-task-package-2026-09-20.md` + `fine-tune-deploy-handoff-2026-09-19.md` §2 方案 v2。
> 上游实证：插件 `astrbot_plugin_mimo_tts_clone` v0.7.2 的 `core/mimo_official_client.py`（本地参考副本 `_tmp/deploy_ref/`，gitignored）。

## 0. 拓扑

```
AstrBot 插件(容器, base_url→http://172.19.0.1:8800/v1, openai SDK)
  → yachiyo-tts-router (服务器宿主机 systemd, 172.19.0.1:8800)
      ├─ TTS 形状 & mode 允许 & bridge ready → 127.0.0.1:9881 (frp 隧道, proxyBindAddr=127.0.0.1)
      │     → yachiyo-tts-bridge (Windows 本机, 127.0.0.1:9881)
      │           → GPT-SoVITS api_v2 子进程 (127.0.0.1:9880)
      └─ 其余一切（ASR/非TTS/bridge不可用）→ https://api.xiaomimimo.com 原样透传（含鉴权头）
```

frps 复用 `fit-frps.service`（bindPort 7400，`proxyBindAddr=127.0.0.1`，token 存在于 /opt/fitness-relay/frps.toml——**禁改 frps 配置**）。frpc 在 Windows 侧新增 proxy `yachiyo-bridge`，remotePort **9881**（部署时核实服务器该端口空闲）。

## 1. 上游 API 形状（实证，openai SDK chat.completions）

请求（插件→router）：`POST {base_url}/chat/completions`
```json
{
  "model": "mimo-v2.5-tts-voiceclone",
  "messages": [
    {"role": "user", "content": "<style_context，可多条可缺省>"},
    {"role": "assistant", "content": "<speech_text 正文，最后一条 assistant>"}
  ],
  "audio": {"format": "wav", "voice": "<data:audio/wav;base64,.... ~954KB 参考音频>"}
}
```
- **TTS 判据**：JSON body 有顶层 `audio` 对象。无 `audio`（如 ASR 的 input_audio 在 messages 里）→ 永远透传云。
- 鉴权头：`Authorization: Bearer sk-...` 透传。
- 插件侧 `max_retries=0`、timeout 可配（默认见 _conf_schema.json，按 120s 假设有余量）。

响应（云或 bridge 都必须长这样，openai SDK 兼容）：
```json
{
  "id": "chatcmpl-...", "object": "chat.completion", "created": 1758..., "model": "mimo-v2.5-tts-voiceclone",
  "choices": [{"index": 0, "finish_reason": "stop",
    "message": {"role": "assistant", "content": null,
      "audio": {"data": "<base64 RIFF/WAVE, 24kHz/16bit/mono>", "transcript": "", "expires_at": 0}}}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```
插件只消费 `choices[0].message.audio.data`（base64 解码后校验 `RIFF....WAVE` 头）。`transcript`/`expires_at`/`usage` 填空值防 openai SDK pydantic 必填校验。

## 2. yachiyo-tts-bridge（Windows，Python 3.12 系统 Python，**stdlib-only 零第三方依赖**）

bind `127.0.0.1:9881`，HTTP/1.1，ThreadingHTTPServer。

### 2.1 端点
- `POST /v1/chat/completions` — 契约：头 `X-Bridge-Token` 匹配，否则 401。处理顺序：401→429(限速 6RPM 滑窗，超→429)→400(speech_text>120 字符，code=`text_too_long`)→503(state!=ready，code=`bridge_busy`，附 `Retry-After: 60`)→合成 200。错误体统一 `{"error":{"message":"...","code":"...","type":"bridge_error"}}`。
  - 解析：`style_context` = 所有 user 消息 content 拼接；`speech_text` = 最后一条 assistant 消息 content。`audio.voice` 可能已被 router 剥（有则忽略，不使用——推理参考走 prompt_map）。
  - strip：speech_text 去 ♪♫♬♩♭♮ 与 markdown 记号（`*_~>#`[]()|`\、代码围栏、URL）后压缩空白；strip 后为空 → 400 code=`empty_text`。
  - 合成串行（threading.Lock；占坑排队超 1 个请求时后来者直接 503 `bridge_busy`——防 router 8s 超时内堆积）。
- `GET /health` — 永远 200：`{"state":"ready|busy|loading|down","game_detected":bool,"vram_used_mib":int,"engine_pid":int|null,"last_synth_at":"ISO8601|null","ts":"ISO8601"}`。
- `GET /control/shutdown`（token 门控）— 本体优雅退出（卸引擎+停服务），供运维。

### 2.2 style→prompt 映射
读 `E:/DATA/YachiyoRuntime/prompt_map.json`（四档 happy/tender/default/sad；sad 波形即 tender 暂代）。style_context 关键词命中（config 关键词表，ja/zh/en 混编；小写化匹配）：**先判 sad 关键词→tender 档**，再 happy，再 tender，miss 永落 default。档位→(prompts_dir+wav, text) 喂引擎 ref_audio_path/prompt_text。

### 2.3 引擎监督（api_v2 子进程）
- 引擎根：`F:/AIPart/GPT-SoVITS/GPT-SoVITS-v2pro-20250604/`，`runtime/python.exe` + `api_v2.py`（CLI 参数以 api_v2.py argparse 实读为准：端口 9880、`-a gpt_yachiyo_v1.ckpt -c sovits_yachiyo_v1.pth`；cwd=引擎根）。
- 权重：`E:/DATA/YachiyoRuntime/weights/`。子进程 stdout/stderr → 按大小轮转日志（`logs/api_v2_*.log`，单文件 10MB×5）。
- 引擎就绪探测：轮询 api_v2 的健康/tts 探针（实读 api_v2.py 路由），就绪前 state=loading。
- **判忙**：进程名单（config `game_processes`，默认 `["r5apex.exe"]`，tasklist /fi 探测，5s 周期）出现 → busy；触发卸载：调 api_v2 `/control?command=exit`（等退出，强杀兜底），**busy 期间抑制监督重启**。显存副判据：`nvidia-smi --query-gpu=memory.used` < 2500 MiB 用于确认卸载完成（busy 态下 engine_pid 应为 null）。
- **回载**：进程消失后 debounce 45s（config 可调 30-60s）→ 重启引擎 → loading → ready。
- `/tts` 调用：text=speech_text, text_lang="ja", ref_audio_path, prompt_text, prompt_lang="ja"（参数名以 api_v2.py 实读为准，含 text_split_method 用不切或按引擎默认——长文本已被 120 字符闸挡住）。返回 wav → `wave` 模块解析 → 单声道 16bit → `audioop.ratecv` 重采样 **24000 Hz** → 重新封装 RIFF/WAVE → base64。

### 2.4 心跳与守护
- 每 60s 写 `E:/DATA/YachiyoRuntime/heartbeat.json`：`{"ts":...,"last_synth_at":...,"mode":"<state>","engine_pid":...}`（watchdog 判据 C 只认 last_synth_at）。
- config：`config.json`（真实配置在 YachiyoRuntime/bridge/，git 只放 config.example.json；token 部署时注入）。含 `test_hooks.force_state`（none|busy|loading，默认 none——测试矩阵模拟用，README 标注生产禁用）。
- 守护：NSSM 服务脚本 + 计划任务脚本二选一（install/ 下都给）。

## 3. yachiyo-tts-router（Ubuntu 24.04 服务器，Python 3.12，**stdlib-only**）

bind `172.19.0.1:8800`（docker 网桥地址，astrbot 容器可达）。systemd `yachiyo-tts-router.service`（Simple，Restart=always，After=network-online + docker.service）。

### 3.1 请求路由（POST /v1/chat/completions）
1. body JSON 解析失败 → 透传云（原样 bytes）。
2. **非 TTS 形状**（无顶层 audio 对象）→ 透传云。
3. TTS 形状：
   - mode=cloud → 透传云。
   - mode=auto：bridge_state==ready → 走桥（**剥 `audio.voice` 键**再加 `X-Bridge-Token`，connect 超时 2s / 总超时 8s）；bridge 非 200 / 超时 / bridge_state!=ready → 透传云（**原始完整 body**，含 voice）。
   - mode=local：走桥；桥失败 → `502 {"error":{"message":"yachiyo local bridge unavailable","code":"bridge_unavailable","type":"router_error"}}`（**明确报错不上云**）。
4. 其余一切路径（/v1/models 等）→ 透传云。
5. 透传=Authorization 等全部头+body 原样转发 `https://api.xiaomimimo.com`，响应原样回（状态码/头/体），**静默**（无播报字段）。
6. 每请求一行日志：`ts mode engine=bridge|cloud status=xx ms=nnn bytes=n reason=probe|forward|fallback`。

### 3.2 桥探测与模式
- 后台线程每 30s `GET http://127.0.0.1:9881/health`（connect 2s）；**连续 2 次失败 → bridge_state=down**；成功 → 取 body.state（ready/busy/loading）。down 期间不路由（省 8s 等待）。
- mode 存内存+落盘 `state.json`（重启保持）；计数器按日期键控落盘 `counters.json`，只留今日+昨日。
- `GET /health`（无鉴权，172.19.0.1 绑定即防护）：`{"mode":...,"bridge_state":...,"today":{"bridge":n,"cloud":n},"busy_reason":"...|null","last_fallback":"ISO|null","ts":...}`——voicemode status 数据源。
- `POST /admin/mode`（头 X-Bridge-Token）：`{"mode":"auto|local|cloud"}` → 200 `{"ok":true,"mode":...}`；非法值 400。

### 3.3 config
`/etc/yachiyo-tts-router/config.json`（git 放 config.example.json）：bridge_url、frp 端口、cloud_base=https://api.xiaomimimo.com、token、探测参数、bind。**token 与 bridge 同值，部署时注入。**

## 4. voicemode tiny 插件（AstrBot，不碰现有任何插件）

- 目录名 `astrbot_plugin_voicemode`；命令 `/voicemode auto|local|cloud|status`；无参数=`status`。
- 门控：`event.get_sender_id()`（或等价）在 config `owner_ids`（默认 `["1010233339"]`）或 event.role==admin 才响应；否则静默忽略（不回错误防刷屏）。
- 实现：aiohttp（astrbot 容器自带）调 router `POST /admin/mode` / `GET /health`；router 地址+token 进 `_conf_schema.json`（默认 `http://172.19.0.1:8800`）。
- status 输出（一条消息）：模式 / bridge 态 / 两引擎今日计数 / 判忙原因 / 回退模式回显。中文文案。
- AstrBot API 参考：`_tmp/deploy_ref/main.py`（MiMo 插件 main.py 副本，只读参考——import 形态 `from astrbot.api.event import ... filter`、`@register`、`@filter.command`、event 用法照抄该文件用法，**不复制其业务代码**）。
- `metadata.yaml`（name/version/author=ZCode-deploy）、`requirements.txt`（空）、README。

## 5. 共同纪律

- 所有 JSON 读 `utf-8`（服务器插件配置例外——那是运维改配置时 `utf-8-sig` 读），写 `utf-8` 无 BOM；Windows 路径用正斜杠。
- 日志不带 token/sk-key。
- 错误路径全部有兜底（引擎崩→bridge 报 down→router 回落云；router 崩→systemd 拉起，astrbot 直连云超时期间重试=SDK 层无重试，插件报 TTS 失败=可接受降级）。
- 测试：unittest（stdlib），不依赖 GPU/网络的部分全覆盖（映射/strip/限速/形状解析/重采样头/路由决策表/计数落盘），mock 引擎与上游。
