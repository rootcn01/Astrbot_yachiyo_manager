#!/usr/bin/env python3
"""yachiyo-tts-bridge — CONTRACT §2 实现。Windows 本机 GPT-SoVITS api_v2 监督桥。
Python 3.12 stdlib-only；OpenAI chat.completions 形状 → api_v2 /tts → wav 24kHz/16bit/mono → base64。
api_v2.py 实证引用（F:/AIPart/GPT-SoVITS/GPT-SoVITS-v2pro-20250604/api_v2.py）:
  - CLI: -c/--tts_config(默认 tts_infer.yaml):134  -a/--bind_addr(默认127.0.0.1):135
    -p/--port(默认9880):136 ——【推翻点】无 -a/-c 权重 CLI 参数(CONTRACT §2.3 假设不成立)，
    权重经 HTTP 热载: GET /set_gpt_weights?weights_path=:545-554、/set_sovits_weights:557-565
  - POST /tts JSON 字段(TTS_Request): text/text_lang/ref_audio_path/prompt_text/prompt_lang/
    text_split_method(默认"cut5")/media_type("wav")/streaming_mode(bool) :154-178, :511-514；
    非流式 wav 返回原始 wav bytes Response :440-443
  - GET /control?command=exit → SIGTERM 退出 :448-452, :300-302；【实证】无独立 /health 路由，
    GET /control 无参 → 400 "command is required" :449-451 = HTTP 存活/就绪探针
  - 引擎 wav 打包 mono/16bit :282-291（采样率从 wav 头读取，常见 32000）
"""
import argparse, base64, hmac, io, json, logging, os, re, shutil, subprocess, sys
import threading, time, urllib.error, urllib.parse, urllib.request, uuid, wave, warnings
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

warnings.filterwarnings("ignore", category=DeprecationWarning)  # audioop 3.12 弃用告警
import audioop  # noqa: E402  (Python 3.12 仍在 stdlib；3.13 起移除)

log = logging.getLogger("bridge")
DEFAULT_MODEL, DEFAULT_CONFIG_PATH = "mimo-v2.5-tts-voiceclone", "E:/DATA/YachiyoRuntime/bridge/config.json"

DEFAULTS = {
    "bind": "127.0.0.1", "port": 9881, "token": "CHANGE_ME",
    "prompt_map_path": "E:/DATA/YachiyoRuntime/prompt_map.json",
    "runtime_dir": "E:/DATA/YachiyoRuntime",
    "engine": {  # api_v2 CLI 无权重参数(:134-136)，权重走 /set_*_weights(:545-565)
        "python_exe": "F:/AIPart/GPT-SoVITS/GPT-SoVITS-v2pro-20250604/runtime/python.exe",
        "api_v2_path": "F:/AIPart/GPT-SoVITS/GPT-SoVITS-v2pro-20250604/api_v2.py",
        "cwd": "F:/AIPart/GPT-SoVITS/GPT-SoVITS-v2pro-20250604", "host": "127.0.0.1", "port": 9880,
        "gpt_weights": "E:/DATA/YachiyoRuntime/weights/gpt_yachiyo_v1.ckpt",
        "sovits_weights": "E:/DATA/YachiyoRuntime/weights/sovits_yachiyo_v1.pth",
        "startup_timeout_s": 300, "request_timeout_s": 30, "crash_restart_delay_s": 10},
    "game_processes": ["r5apex.exe"], "game_poll_s": 5.0, "vram_poll_s": 10.0,
    "vram_threshold_mib": 2500, "reload_debounce_s": 45, "rate_limit_rpm": 6, "max_text_len": 120,
    "unload_confirm_poll_s": 2.0, "unload_confirm_timeout_s": 30.0,
    "heartbeat_path": "E:/DATA/YachiyoRuntime/heartbeat.json", "heartbeat_interval_s": 60,
    "keywords": {
        "sad": ["悲しい", "辛い", "つらい", "寂しい", "泣", "伤心", "难过", "哭", "sad", "lonely", "cry"],
        "happy": ["楽しい", "嬉しい", "わくわく", "たのし", "高兴", "开心", "快乐", "happy", "glad", "yay", "great"],
        "tender": ["大丈夫", "頑張", "がんば", "安心", "抱きしめ", "温柔", "安慰", "加油", "tender", "gentle", "comfort", "care"]},
    "test_hooks": {"force_state": "none"},
    "log_dir": "E:/DATA/YachiyoRuntime/bridge/logs", "log_max_bytes": 10 * 1024 * 1024, "log_backups": 5,
}


def deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
def load_config(path):
    return deep_merge(DEFAULTS, load_json(path))
def utc_iso(ts=None):
    return datetime.fromtimestamp(ts if ts is not None else time.time(),
                                  tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
# ---------------------------------------------------------------- 文本清洗
NOTE_RE = re.compile("[♪♫♬♩♭♮]")
FENCE_RE = re.compile("```.*?```", re.S)
URL_RE = re.compile(r"(?:https?://|www\.)\S+")
MD_CHARS_RE = re.compile(r"[*_~>`\[\]()|\\#]")
WS_RE = re.compile(r"\s+")


def strip_speech(text):
    """去 ♪♫♬♩♭♮、代码围栏、URL、markdown 记号，压缩空白（CONTRACT §2.1）。"""
    t = MD_CHARS_RE.sub(" ", NOTE_RE.sub("", URL_RE.sub(" ", FENCE_RE.sub(" ", text or ""))))
    return WS_RE.sub(" ", t).strip()


_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


def detect_text_lang(text):
    """text_lang 探测（v1.1）：含假名→ja（日语铁证）；纯汉字无假名→zh（中文文本，
    避免日语音读中文——生产首例：神明大人被读成しんめいだいじん）；其余保持 ja 默认
    （用户长期规则：语音一律日语，导演正常时 speech_text 已译日）。"""
    t = text or ""
    if _KANA_RE.search(t):
        return "ja"
    if _HAN_RE.search(t):
        return "zh"
    return "ja"
# ---------------------------------------------------------------- 限速（滑窗 RPM）
class RateLimiter:
    def __init__(self, rpm):
        self.rpm = max(1, int(rpm))
        self.window = deque()
        self.lock = threading.Lock()
    def allow(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            while self.window and now - self.window[0] >= 60.0:
                self.window.popleft()  # 滑出 60s 窗口
            if len(self.window) >= self.rpm:
                return False
            self.window.append(now)
            return True
# ---------------------------------------------------------------- style → prompt 四档映射
class StyleMapper:
    """CONTRACT §2.2：sad 关键词→tender 档优先判，再 happy、tender，miss 落 default。"""
    def __init__(self, prompt_map, keywords, runtime_dir=None):
        self.prompt_map, self.keywords = prompt_map or {}, keywords or {}
        paths = self.prompt_map.get("_paths", {})
        self.runtime_dir = paths.get("runtime_dir") or runtime_dir or "E:/DATA/YachiyoRuntime"
        self.prompts_dir = paths.get("prompts_dir", "prompts")
    def classify(self, style_context):
        ctx = (style_context or "").lower()
        for tier in ("sad", "happy", "tender"):  # sad 先判（命中即用 tender 素材）
            for kw in self.keywords.get(tier, []):
                if kw.lower() in ctx:
                    return "tender" if tier == "sad" else tier
        return "default"
    def resolve(self, tier):
        entry = self.prompt_map.get(tier) or self.prompt_map["default"]
        return "{}/{}/{}".format(self.runtime_dir, self.prompts_dir,
                                 entry["wav"]), entry.get("text", "")
# ---------------------------------------------------------------- 引擎 stdout 轮转日志（10MB×5）
class RotatingLog:
    def __init__(self, path, max_bytes, backups):
        self.path, self.max_bytes, self.backups = path, max_bytes, backups
        self.lock = threading.Lock()
    def write(self, text):
        with self.lock:
            with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                f.write(text)
            if os.path.getsize(self.path) > self.max_bytes:
                self._rotate()
    def _rotate(self):
        for i in range(self.backups - 1, 0, -1):
            src, dst = "{}.{}".format(self.path, i), "{}.{}".format(self.path, i + 1)
            if os.path.exists(src):
                if os.path.exists(dst):
                    os.remove(dst)
                os.replace(src, dst)
        if os.path.exists(self.path + ".1"):
            os.remove(self.path + ".1")
        os.replace(self.path, self.path + ".1")
# ---------------------------------------------------------------- 可注入系统探针
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NVIDIA_SMI_ABS = "C:/Windows/System32/nvidia-smi.exe"
def nvidia_smi_cmd():
    """绝对路径优先（PATH 劫持/缺失免疫），NVSMI 惯例位与 shutil.which 回退。"""
    for cand in (_NVIDIA_SMI_ABS,
                 "C:/Program Files/NVIDIA Corporation/NVSMI/nvidia-smi.exe"):
        if os.path.exists(cand):
            return cand
    return shutil.which("nvidia-smi") or "nvidia-smi"
def tasklist_running(process_name, _runner=subprocess.run):
    """tasklist /fi 探测进程是否存在（Windows）。"""
    try:
        cp = _runner(["tasklist", "/fi", "IMAGENAME eq {}".format(process_name)],
                     capture_output=True, text=True, encoding="utf-8", errors="replace",
                     timeout=15, creationflags=_NO_WINDOW)
        return process_name.lower() in (cp.stdout or "").lower()
    except Exception:
        return False
def nvidia_smi_vram_mib(_runner=subprocess.run):
    """nvidia-smi 显存占用 MiB；失败返回 None。"""
    try:
        cp = _runner([nvidia_smi_cmd(), "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                     capture_output=True, text=True, encoding="utf-8", errors="replace",
                     timeout=15, creationflags=_NO_WINDOW)
        return int((cp.stdout or "").strip().splitlines()[0])
    except Exception:
        return None
def taskkill_tree(pid, _runner=subprocess.run):
    """Windows 强杀兜底：taskkill /T 连进程树一起杀。"""
    try:
        cp = _runner(["taskkill", "/T", "/F", "/PID", str(pid)],
                     capture_output=True, timeout=15, creationflags=_NO_WINDOW)
        return cp.returncode == 0
    except Exception:
        return False
def default_transport(method, url, params=None, json_body=None, timeout=30):
    """引擎 HTTP transport（可整体注入替换——测试用）。返回 (status|None, body_bytes)。"""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        finally:
            e.close()  # HTTPError 也持有连接，须关防 fd 泄漏
    except Exception:
        return None, b""
# ---------------------------------------------------------------- 引擎监督状态机
class EngineSupervisor:
    """down →(spawn)→ loading →(探针+热载权重)→ ready →(游戏进程)→ busy(卸载,抑重启)
       →(进程消失+debounce)→ loading → ready；ready 崩溃 → down → 延时重启。"""
    def __init__(self, cfg, transport=None, spawner=None, tasklist=tasklist_running,
                 vram_probe=nvidia_smi_vram_mib, clock=time.time,
                 synth_lock=None, taskkiller=taskkill_tree):
        self.cfg, self.ecfg = cfg, cfg["engine"]
        self.base_url = "http://{}:{}".format(self.ecfg["host"], self.ecfg["port"])
        self.transport = transport or default_transport
        self.spawner = spawner or self._default_spawner
        self.tasklist, self.vram_probe, self.clock = tasklist, vram_probe, clock
        # 与请求路径合成共用同一把 synth 锁（F6）：unload/spawn 等在飞合成结束，
        # 请求路径持锁期间不再取任何监督锁，单向顺序无死锁
        self.synth_lock = synth_lock or threading.Lock()
        self.taskkiller = taskkiller
        self.state, self.proc, self.engine_pid = "down", None, None
        self.game_detected, self.vram_used_mib, self._shutting_down = False, -1, False
        self._spawned_at = self._restart_at = self._last_game_poll = self._last_vram_poll = 0.0
        self._absence_since, self._weights_loaded, self._log, self._monitor_thread = \
            None, False, None, None
    # -- 子进程启动: -a=bind_addr -p=port（实证 api_v2.py:135-136; 无权重 CLI 参数 :134）--
    def _default_spawner(self):
        cmd = [self.ecfg["python_exe"], self.ecfg["api_v2_path"],
               "-a", self.ecfg["host"], "-p", str(self.ecfg["port"])]
        log.info("engine spawn: %s (cwd=%s)", " ".join(cmd), self.ecfg["cwd"])
        return subprocess.Popen(
            cmd, cwd=self.ecfg["cwd"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    def _start_log(self, proc):
        os.makedirs(self.cfg["log_dir"], exist_ok=True)
        self._log = RotatingLog(os.path.join(self.cfg["log_dir"], "api_v2.log"),
                                self.cfg["log_max_bytes"], self.cfg["log_backups"])
        def pump():
            try:
                for line in proc.stdout:
                    self._log.write(line)
            except Exception:
                pass
        threading.Thread(target=pump, daemon=True).start()
    def start(self):
        self.spawn()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    def spawn(self):
        with self.synth_lock:  # F6: 与请求路径合成互斥
            self._weights_loaded, self._spawned_at = False, self.clock()
            self.proc = self.spawner()
            self.engine_pid = getattr(self.proc, "pid", None)
            if getattr(self.proc, "stdout", None) is not None:
                self._start_log(self.proc)
            self._set_state("loading")
    def _set_state(self, state):
        if state != self.state:
            log.info("state: %s -> %s", self.state, state)
            self.state = state
    # -- 就绪探测: GET /control 无参应答 400 "command is required" (api_v2.py:449-451) --
    def _probe_and_promote(self):
        if any(self.tasklist(p) for p in self.cfg["game_processes"]):
            # F7: 热载前先查游戏名单——命中则不热载，直接走卸载分支
            log.info("game process present during loading; skip weight load, unload")
            self.game_detected, self._absence_since = True, None  # 复审 L：同步置位防误开 debounce
            self._set_state("busy")
            self._unload()
            return
        status, body = self.transport("GET", self.base_url + "/control", timeout=10)
        if status == 400 and b"command is required" in body and self._load_weights():
            self._set_state("ready")
    def _load_weights(self):
        if self._weights_loaded:
            return True
        for path_key, route in (("gpt_weights", "/set_gpt_weights"),      # api_v2.py:545-554
                                ("sovits_weights", "/set_sovits_weights")):  # api_v2.py:557-565
            # 复审 M：冷加载 ckpt/pth 可超 15s，timeout 回 60s（防卡 loading 到 300s 启动超时）
            status, body = self.transport("GET", self.base_url + route,
                                          params={"weights_path": self.ecfg[path_key]}, timeout=60)
            if status != 200 or b"success" not in body:
                log.error("weights load failed %s: %s %s", route, status, body[:200])
                return False
        self._weights_loaded = True
        return True
    # -- 卸载: GET /control?command=exit (api_v2.py:448-452) + 等退出/强杀兜底 --
    def _unload(self):
        with self.synth_lock:  # F6: 等在飞合成结束（调用方须已先置 busy 挡新请求）
            if self.proc is not None and self.proc.poll() is None:
                self.transport("GET", self.base_url + "/control",
                               params={"command": "exit"}, timeout=10)
                self._wait_exit(20)
            if self.proc is not None and self.proc.poll() is None:
                try:
                    self.proc.kill()
                    self._wait_exit(5)
                except Exception:
                    pass
            if self.proc is not None and self.proc.poll() is None:
                # F15: Windows kill 失效兜底——taskkill 连进程树强杀
                if not self.taskkiller(self.proc.pid):
                    log.warning("taskkill fallback failed for pid %s", self.proc.pid)
                self._wait_exit(5)
            try:  # F15: 释放子进程 stdout PIPE 句柄
                if getattr(self.proc, "stdout", None) is not None:
                    self.proc.stdout.close()
            except Exception:
                pass
            self.proc = None
        # 复审 L：显存确认轮询放锁外（busy 已置位挡新请求，监督线程不必持锁干等 30s）
        self._confirm_vram_released()  # F8: 显存回落确认后才算卸载完成
        self.engine_pid = None
    def _confirm_vram_released(self):
        """等子进程退出后轮询 nvidia-smi（默认 2s 间隔至多 30s）直到 vram<阈值。"""
        deadline = time.monotonic() + self.cfg["unload_confirm_timeout_s"]
        while True:
            vram = self.vram_probe()
            if vram is None:
                return  # 探针不可用，无从确认，视为完成
            self.vram_used_mib = vram
            if vram < self.cfg["vram_threshold_mib"]:
                return
            if time.monotonic() >= deadline:
                log.warning("vram %d MiB still >= %d MiB after %.0fs confirm window",
                            vram, self.cfg["vram_threshold_mib"],
                            self.cfg["unload_confirm_timeout_s"])
                return
            time.sleep(self.cfg["unload_confirm_poll_s"])
    def _wait_exit(self, timeout_s):
        deadline = time.monotonic() + timeout_s  # 真实墙钟等待，不吃注入 clock
        while self.proc is not None and self.proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
    # -- 单次监督节拍（测试可直接驱动） --
    def tick(self):
        now = self.clock()
        if self._shutting_down:
            return
        if now - self._last_game_poll >= self.cfg["game_poll_s"]:
            self._last_game_poll = now
            self.game_detected = any(self.tasklist(p) for p in self.cfg["game_processes"])
        if now - self._last_vram_poll >= self.cfg["vram_poll_s"]:
            self._last_vram_poll, vram = now, self.vram_probe()
            if vram is not None:
                self.vram_used_mib = vram
        # 崩溃检测（busy 抑制重启）
        if (self.proc is not None and self.proc.poll() is not None
                and self.state in ("ready", "loading")):
            log.warning("engine exited unexpectedly (rc=%s)", self.proc.poll())
            self.proc, self.engine_pid = None, None
            self._set_state("down")
            self._restart_at = now + self.ecfg["crash_restart_delay_s"]
        if self.game_detected:
            self._absence_since = None
            if self.state != "busy":
                log.info("game process detected -> busy, unloading engine")
                self._set_state("busy")  # 先置 busy 挡新请求，再等锁上在飞合成退出（F6）
                self._unload()
                if self.vram_used_mib >= self.cfg["vram_threshold_mib"]:
                    log.warning("vram still %d MiB after unload", self.vram_used_mib)
        elif self.state == "busy":
            if self._absence_since is None:
                self._absence_since = now
            elif now - self._absence_since >= self.cfg["reload_debounce_s"]:  # CONTRACT §2.3 回载
                log.info("game gone %.0fs -> reload engine", now - self._absence_since)
                self._absence_since = None
                self.spawn()
        elif self.state == "down":
            if self._restart_at and now >= self._restart_at:
                self._restart_at = 0.0
                self.spawn()
        elif self.state == "loading":
            if self.proc is not None and self.proc.poll() is None:
                self._probe_and_promote()
                if self.state == "loading" and now - self._spawned_at > self.ecfg["startup_timeout_s"]:
                    log.error("engine startup timeout; killing")
                    self._unload()
                    self._set_state("down")
                    self._restart_at = now + self.ecfg["crash_restart_delay_s"]
    def _monitor_loop(self):
        while not self._shutting_down:
            try:
                self.tick()
            except Exception:
                log.exception("supervisor tick failed")
            time.sleep(1.0)
    def stop(self):
        self._shutting_down = True
        self._unload()
        self._set_state("down")
# ---------------------------------------------------------------- 音频后处理
def postprocess_wav(wav_bytes, target_rate=24000):
    """wave 解析 → 16bit mono → audioop.ratecv 重采样 → RIFF 重封（CONTRACT §2.3）。"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        nch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        frames = w.readframes(w.getnframes())
    if nch == 2:
        frames = audioop.tomono(frames, width, 0.5, 0.5)
        nch = 1
    if width != 2:
        frames = audioop.lin2lin(frames, width, 2)
    if rate != target_rate:
        frames, _ = audioop.ratecv(frames, 2, 1, rate, target_rate, None)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(target_rate)
        w.writeframes(frames)
    return buf.getvalue()
# ---------------------------------------------------------------- 请求解析 / 响应形状
MAX_BODY_BYTES = 512 * 1024  # F4: /v1/chat/completions Content-Length 上限
def parse_chat_request(body):
    """style_context=所有 user content 拼接; speech_text=最后一条 assistant content（§2.1）。"""
    messages = body.get("messages") or []
    def pick(role):
        return [str(m.get("content") or "") for m in messages
                if isinstance(m, dict) and m.get("role") == role]
    users, assistants = pick("user"), pick("assistant")
    return " ".join(users), (assistants[-1] if assistants else None)
def build_chat_response(audio_b64, model=None):
    return {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion",
            "created": int(time.time()), "model": model or DEFAULT_MODEL,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": None,
                                     "audio": {"data": audio_b64, "transcript": "",
                                               "expires_at": 0}}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
# ---------------------------------------------------------------- 应用主体
class BridgeApp:
    def __init__(self, cfg, supervisor=None):
        self.cfg = cfg
        self.limiter = RateLimiter(cfg["rate_limit_rpm"])
        self.mapper = StyleMapper(load_json(cfg["prompt_map_path"]), cfg["keywords"],
                                  cfg.get("runtime_dir"))
        self.synth_lock = threading.Lock()
        self.supervisor = supervisor or EngineSupervisor(cfg, synth_lock=self.synth_lock)
        self.last_synth_at = None
        self.stop_requested = False
        self.http_server = None
    def token_ok(self, token_header):
        """常数时间 token 比较（F12）；空配置 token 恒拒。"""
        want = str(self.cfg.get("token") or "").encode("utf-8")
        got = str(token_header or "").encode("utf-8")
        return bool(want) and hmac.compare_digest(got, want)
    def force_state(self):
        v = str((self.cfg.get("test_hooks") or {}).get("force_state") or "none").lower()
        return v if v in ("busy", "loading") else None
    def effective_state(self):
        return self.force_state() or self.supervisor.state
    def start(self):
        self.supervisor.start()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._hb_thread.start()
        self.write_heartbeat()
    # -- 心跳（CONTRACT §2.4）--
    def write_heartbeat(self):
        hb = {"ts": utc_iso(), "last_synth_at": self.last_synth_at,
              "mode": self.effective_state(), "engine_pid": self.supervisor.engine_pid}
        tmp = self.cfg["heartbeat_path"] + ".tmp"
        os.makedirs(os.path.dirname(self.cfg["heartbeat_path"]), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(hb, f, ensure_ascii=False)
        os.replace(tmp, self.cfg["heartbeat_path"])
    def _heartbeat_loop(self):
        while not self.stop_requested:
            time.sleep(self.cfg["heartbeat_interval_s"])
            if self.stop_requested:
                return
            try:
                self.write_heartbeat()
            except Exception:
                log.exception("heartbeat write failed")
    # -- POST /v1/chat/completions 主流程；返回 (status, headers, body_bytes) --
    def handle_chat(self, token_header, body_bytes):
        try:
            if not self.token_ok(token_header):  # F4: 401 优先于 body 解析等一切
                return self._err(401, "bad or missing X-Bridge-Token", "unauthorized")
            try:
                body = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                return self._err(400, "request body is not valid JSON", "invalid_json")
            if not self.limiter.allow():
                return self._err(429, "rate limit exceeded (6 RPM)", "rate_limited",
                                 {"Retry-After": "60"})
            style_context, speech_text = parse_chat_request(body)
            if speech_text is None:
                return self._err(400, "no assistant message found", "invalid_request")
            if len(speech_text) > self.cfg["max_text_len"]:  # F16: raw 闸在 strip 之前
                return self._err(400, "speech_text exceeds 120 chars", "text_too_long")
            stripped = strip_speech(speech_text)
            if not stripped:
                return self._err(400, "speech_text empty after strip", "empty_text")
            if self.effective_state() != "ready":
                return self._err(503, "bridge state is " + self.effective_state(),
                                 "bridge_busy", {"Retry-After": "60"})
            if not self.synth_lock.acquire(blocking=False):  # 队列>1 直接 503（§2.1）
                return self._err(503, "synthesis queue full", "bridge_busy",
                                 {"Retry-After": "60"})
            try:
                audio_b64 = self._synthesize(stripped, style_context, body.get("model"))
            finally:
                self.synth_lock.release()
            return 200, {"Content-Type": "application/json"}, json.dumps(
                build_chat_response(audio_b64, body.get("model")), ensure_ascii=False).encode("utf-8")
        except Exception:
            log.exception("handle_chat failed")
            return self._err(500, "internal error", "internal_error")  # F13: 细节只进日志
    def _synthesize(self, speech_text, style_context, model=None):
        tier = self.mapper.classify(style_context)
        wav_path, prompt_text = self.mapper.resolve(tier)
        log.info("synth tier=%s len=%d", tier, len(speech_text))
        payload = {  # POST /tts JSON（TTS_Request 字段, api_v2.py:154-178, :511-514）
            "text": speech_text, "text_lang": detect_text_lang(speech_text),
            "ref_audio_path": wav_path, "prompt_text": prompt_text, "prompt_lang": "ja",  # 参考音频恒日语
            "text_split_method": "cut5",  # 引擎默认切法 api_v2.py:164
            "media_type": "wav", "streaming_mode": False}
        status, data = self.supervisor.transport(
            "POST", self.supervisor.base_url + "/tts", json_body=payload,
            timeout=self.cfg["engine"]["request_timeout_s"])
        if status != 200 or not data:
            raise RuntimeError("engine /tts failed: status={} bytes={}".format(status, len(data or b"")))
        out = postprocess_wav(data, 24000)
        self.last_synth_at = utc_iso()
        return base64.b64encode(out).decode("ascii")
    @staticmethod
    def _err(status, message, code, extra_headers=None):
        payload = {"error": {"message": message, "code": code, "type": "bridge_error"}}
        headers = dict({"Content-Type": "application/json"}, **(extra_headers or {}))
        return status, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8")
    def health(self):
        return {"state": self.effective_state(), "game_detected": bool(self.supervisor.game_detected),
                "vram_used_mib": int(self.supervisor.vram_used_mib), "engine_pid": self.supervisor.engine_pid,
                "last_synth_at": self.last_synth_at, "ts": utc_iso()}
    def request_shutdown(self):
        self.stop_requested = True
        log.info("shutdown requested")
        threading.Thread(target=self._shutdown_server, daemon=True).start()
    def _shutdown_server(self):
        time.sleep(0.3)  # 让 /control/shutdown 响应先落地
        if self.http_server is not None:
            self.http_server.shutdown()
        else:
            self.supervisor.stop()
# ---------------------------------------------------------------- HTTP 层
class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app = None  # 由 serve() 注入
    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)
    def _send(self, status, headers, body):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def _json(self, obj, status=200, headers=None):
        h = dict({"Content-Type": "application/json"}, **(headers or {}))
        self._send(status, h, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    def _err_json(self, status, message, code):
        self._json({"error": {"message": message, "code": code, "type": "bridge_error"}}, status)
    def do_GET(self):
        app, path = self.app, urllib.parse.urlparse(self.path).path
        if path == "/health":
            self._json(app.health())
        elif path == "/control/shutdown":
            if not app.token_ok(self.headers.get("X-Bridge-Token")):
                self._err_json(401, "bad or missing X-Bridge-Token", "unauthorized")
                return
            app.request_shutdown()
            self._json({"ok": True, "stopping": True})
        else:
            self._err_json(404, "not found", "not_found")
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/v1/chat/completions":
            self._err_json(404, "not found", "not_found")
            return
        token = self.headers.get("X-Bridge-Token")
        if not self.app.token_ok(token):  # F4: 401 优先于读取 body
            self.close_connection = True  # body 未读，连接不可复用
            self._err_json(401, "bad or missing X-Bridge-Token", "unauthorized")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            self._err_json(400, "bad request", "invalid_request")
            return
        if length > MAX_BODY_BYTES:  # F4: 读取 body 前判体积上限
            self.close_connection = True
            self._err_json(413, "request body too large", "body_too_large")
            return
        try:
            body = self.rfile.read(length) if length > 0 else b""
        except Exception:
            self._err_json(400, "bad request", "invalid_request")
            return
        status, headers, payload = self.app.handle_chat(token, body)
        self._send(status, headers, payload)
class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True  # F10: 重启窗口内 TIME_WAIT 不阻断 rebind
def serve(cfg):
    app = BridgeApp(cfg)
    handler = type("BoundBridgeHandler", (BridgeHandler,), {"app": app})
    app.http_server = BridgeServer((cfg["bind"], cfg["port"]), handler)
    app.start()
    log.info("bridge listening on %s:%d", cfg["bind"], cfg["port"])
    try:
        app.http_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_requested = True
        app.supervisor.stop()
        app.http_server.server_close()
def main():
    ap = argparse.ArgumentParser(description="yachiyo-tts-bridge")
    ap.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = load_config(args.config)
    if not cfg.get("token") or cfg["token"] == "CHANGE_ME":
        log.error("config token is unset (CHANGE_ME); fill %s before running", args.config)
        sys.exit(2)
    serve(cfg)
if __name__ == "__main__":
    main()
