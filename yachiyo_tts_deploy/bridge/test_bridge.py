#!/usr/bin/env python3
"""test_bridge.py — unittest，零 GPU 零网络：引擎/系统探针全部注入 mock。"""
import base64, http.client, io, json, math, os, struct, sys, tempfile, threading, unittest, wave
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bridge  # noqa: E402
def make_wav(rate, seconds=0.2, freq=440.0, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            frames += struct.pack("<h", int(3000 * math.sin(2 * math.pi * freq * i / rate))) * channels
        w.writeframes(bytes(frames))
    return buf.getvalue()
PROMPT_MAP = {
    "happy": {"wav": "prompt_happy.wav", "text": "楽しそうだね"},
    "tender": {"wav": "prompt_tender.wav", "text": "いつも頑張ってるんだね"},
    "default": {"wav": "prompt_default.wav", "text": "夜景が大好き"},
    "sad": {"wav": "prompt_tender.wav", "text": "いつも頑張ってるんだね"},
    "_paths": {"runtime_dir": "R:/rt", "prompts_dir": "prompts"},
}
class FakeProc:
    def __init__(self, pid=4321):
        self.pid, self.stdout, self.exited, self.killed = pid, None, False, False
    def poll(self):
        return 1 if self.exited else None
    def kill(self):
        self.killed, self.exited = True, True
    def wait(self, timeout=None):
        return 1
class ScriptedTransport:
    """mock 引擎 HTTP：按路由脚本应答并记录调用序。alive=False 模拟引擎 HTTP 不通。"""
    def __init__(self, tts_wav=b"", alive=True):
        self.calls, self.tts_wav, self.alive, self.proc = [], tts_wav or make_wav(32000), alive, None
    def __call__(self, method, url, params=None, json_body=None, timeout=30):
        self.calls.append({"method": method, "url": url, "params": params,
                           "json_body": json_body})
        path = url.rsplit("/", 1)[-1]
        if (params or {}).get("command") == "exit":
            if self.proc is not None:
                self.proc.exited = True
            return 200, b""
        if path == "control":
            return (400, b'{"message":"command is required"}') if self.alive else (None, b"")  # :449-451
        if "set_gpt_weights" in url or "set_sovits_weights" in url:
            return 200, b'{"message":"success"}'
        return (200, self.tts_wav) if path == "tts" else (404, b"{}")
def make_cfg(tmp, **over):
    cfg = bridge.deep_merge(bridge.DEFAULTS, {
        "token": "t0k", "heartbeat_path": os.path.join(tmp, "hb.json"),
        "prompt_map_path": os.path.join(tmp, "prompt_map.json"),
        "log_dir": os.path.join(tmp, "logs"), "rate_limit_rpm": 6, "max_text_len": 120,
        "reload_debounce_s": 45, "game_poll_s": 5.0, "vram_poll_s": 10.0})
    cfg.update(over)
    with open(cfg["prompt_map_path"], "w", encoding="utf-8") as f:
        json.dump(PROMPT_MAP, f)
    return cfg
def chat_body(speech, style="天気だね", model="mimo-v2.5-tts-voiceclone"):
    return json.dumps({"model": model,
        "messages": [{"role": "user", "content": "前段"},
                     {"role": "user", "content": style},
                     {"role": "assistant", "content": "以前の返事"},
                     {"role": "assistant", "content": speech}],
        "audio": {"format": "wav", "voice": "data:audio/wav;base64,AAAA"}}).encode("utf-8")
class TestStrip(unittest.TestCase):
    def test_notes_and_markdown(self):
        self.assertEqual(bridge.strip_speech("♪こんにちは♫ *強調* 世界"), "こんにちは 強調 世界")
    def test_url_fence_and_ws(self):
        t = "見て https://example.com/a?b=1 ```code()``` >引用 _斜体_"
        self.assertEqual(bridge.strip_speech(t), "見て 引用 斜体")
    def test_heading_hash(self):  # F5: markdown 标题 # 也在剥除记号内
        self.assertEqual(bridge.strip_speech("# 見出し ## 本文 #単発"), "見出し 本文 単発")
    def test_empty(self):
        self.assertEqual(bridge.strip_speech("♪♫ `*`"), "")
class TestMapping(unittest.TestCase):
    def setUp(self):
        self.m = bridge.StyleMapper(PROMPT_MAP, bridge.DEFAULTS["keywords"])
    def test_tiers(self):
        cases = [("悲しい夜だった", "tender"), ("I am so sad", "tender"),  # sad→tender 优先判
                 ("嬉しいな、 HAPPY!", "happy"), ("大丈夫、頑張って", "tender"),
                 ("今日は天気だね", "default"), ("", "default")]  # miss → default
        for ctx, tier in cases:
            self.assertEqual(self.m.classify(ctx), tier)
    def test_sad_beats_happy(self):
        self.assertEqual(self.m.classify("sad but happy vibes"), "tender")
    def test_resolve_paths(self):
        wav, text = self.m.resolve("happy")
        self.assertEqual(wav, "R:/rt/prompts/prompt_happy.wav")
        self.assertEqual(text, "楽しそうだね")
class TestLimiter(unittest.TestCase):
    def test_sliding_window(self):
        lim = bridge.RateLimiter(6)
        t = 1000.0
        self.assertTrue(all(lim.allow(t) for _ in range(6)))
        self.assertFalse(lim.allow(t + 1))
        self.assertTrue(lim.allow(t + 61))  # 窗口滑出后恢复
class TestParsing(unittest.TestCase):
    def test_parse(self):
        style, speech = bridge.parse_chat_request(json.loads(chat_body("本文")))
        self.assertEqual(style, "前段 天気だね")
        self.assertEqual(speech, "本文")
    def test_no_assistant(self):
        style, speech = bridge.parse_chat_request({"messages": [{"role": "user", "content": "x"}]})
        self.assertIsNone(speech)
class TestPostprocess(unittest.TestCase):
    def test_32k_to_24k(self):
        out = bridge.postprocess_wav(make_wav(32000), 24000)
        with wave.open(io.BytesIO(out)) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 24000))
        self.assertTrue(out.startswith(b"RIFF"))
    def test_stereo_22050(self):
        out = bridge.postprocess_wav(make_wav(22050, channels=2), 24000)
        with wave.open(io.BytesIO(out)) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 24000))
class TestApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(self.tmp.name)
        self.transport = ScriptedTransport()
        self.game_on, self.now, self.spawn_count = [False], [1000.0], 0
        self.sup = bridge.EngineSupervisor(
            self.cfg, transport=self.transport, spawner=self._spawn,
            tasklist=lambda p: self.game_on[0], vram_probe=lambda: 800,
            clock=lambda: self.now[0])
        self.app = bridge.BridgeApp(self.cfg, supervisor=self.sup)
        self.proc = self._spawn()
        self.sup.proc, self.sup.engine_pid, self.sup.state = self.proc, self.proc.pid, "ready"
    def _spawn(self):
        self.spawn_count += 1
        p = FakeProc(pid=1000 + self.spawn_count)
        self.transport.proc = p
        return p
    def tearDown(self):
        self.tmp.cleanup()
    def test_success_shape(self):
        status, headers, body = self.app.handle_chat("t0k", chat_body("やっちょだよ♪"))
        self.assertEqual(status, 200)
        resp = json.loads(body)
        self.assertTrue(resp["id"].startswith("chatcmpl-"))
        self.assertEqual(resp["object"], "chat.completion")
        self.assertEqual(resp["model"], "mimo-v2.5-tts-voiceclone")
        msg = resp["choices"][0]["message"]
        self.assertIsNone(msg["content"])
        self.assertEqual(msg["audio"]["transcript"], "")
        self.assertEqual(msg["audio"]["expires_at"], 0)
        self.assertEqual(resp["usage"], {"prompt_tokens": 0, "completion_tokens": 0,
                                         "total_tokens": 0})
        raw = base64.b64decode(msg["audio"]["data"])
        self.assertTrue(raw.startswith(b"RIFF"))
        with wave.open(io.BytesIO(raw)) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 24000))
        self.assertEqual(resp["choices"][0]["finish_reason"], "stop")
        tts = [c for c in self.transport.calls if c["url"].endswith("/tts")][0]  # api_v2.py:154-178
        req = tts["json_body"]
        self.assertEqual((req["text"], req["text_lang"], req["prompt_lang"],
                          req["text_split_method"], req["media_type"], req["streaming_mode"]),
                         ("やっちょだよ", "ja", "ja", "cut5", "wav", False))
        self.assertEqual(req["ref_audio_path"], "R:/rt/prompts/prompt_default.wav")
        self.assertEqual(req["prompt_text"], "夜景が大好き")
    def test_auth_and_gates(self):
        self.assertEqual(self.app.handle_chat("bad", chat_body("x"))[0], 401)
        # F4: 401 优先于一切——坏 token + 非 JSON body 仍 401（而非 invalid_json）
        st, _, body = self.app.handle_chat("bad", b"definitely not json")
        self.assertEqual((st, json.loads(body)["error"]["code"]), (401, "unauthorized"))
        st, _, body = self.app.handle_chat("t0k", chat_body("あ" * 121))
        self.assertEqual(st, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "text_too_long")
        # F16: raw 闸在 strip 之前——raw 122 字符（strip 后仅 61）也判 text_too_long
        st, _, body = self.app.handle_chat("t0k", chat_body("*あ" * 61))
        self.assertEqual(json.loads(body)["error"]["code"], "text_too_long")
        st, _, body = self.app.handle_chat("t0k", chat_body("♪`*`"))
        self.assertEqual(json.loads(body)["error"]["code"], "empty_text")
        st, _, body = self.app.handle_chat("t0k", b"not json")
        self.assertEqual((st, json.loads(body)["error"]["code"]), (400, "invalid_json"))
        st, _, body = self.app.handle_chat(
            "t0k", json.dumps({"messages": [{"role": "user", "content": "u"}]}).encode())
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_request")
    def test_rate_limit(self):
        for _ in range(6):
            self.assertEqual(self.app.handle_chat("t0k", chat_body("おはよう"))[0], 200)
        st, headers, _ = self.app.handle_chat("t0k", chat_body("おはよう"))  # 第 7 次
        self.assertEqual((st, headers.get("Retry-After")), (429, "60"))
    def test_busy_and_queue(self):
        self.sup.state = "busy"
        st, headers, _ = self.app.handle_chat("t0k", chat_body("おはよう"))
        self.assertEqual((st, headers.get("Retry-After")), (503, "60"))
        self.sup.state = "ready"
        self.cfg["test_hooks"]["force_state"] = "loading"
        self.assertEqual(self.app.handle_chat("t0k", chat_body("おはよう"))[0], 503)
        self.cfg["test_hooks"]["force_state"] = "none"
        held = self.app.synth_lock.acquire()
        try:
            st, _, body = self.app.handle_chat("t0k", chat_body("おはよう"))
            self.assertEqual(json.loads(body)["error"]["code"], "bridge_busy")
        finally:
            self.app.synth_lock.release()
    def test_heartbeat_and_health(self):
        self.app.write_heartbeat()
        with open(self.cfg["heartbeat_path"], encoding="utf-8") as f:
            hb = json.load(f)
        self.assertEqual(sorted(hb), ["engine_pid", "last_synth_at", "mode", "ts"])
        self.assertEqual(hb["mode"], "ready")
        self.assertIsNone(hb["last_synth_at"])
        h = self.app.health()  # /health 形状（§2.1）
        self.assertEqual(sorted(h), ["engine_pid", "game_detected", "last_synth_at",
                                     "state", "ts", "vram_used_mib"])
        self.assertEqual(h["state"], "ready")
        self.app.handle_chat("t0k", chat_body("おはよう"))
        self.app.write_heartbeat()
        with open(self.cfg["heartbeat_path"], encoding="utf-8") as f:
            self.assertIsNotNone(json.load(f)["last_synth_at"])
class TestHttpGates(unittest.TestCase):
    """do_POST HTTP 层门控（F4）：401 先于读 body；Content-Length 超限 413（真实 socket）。"""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(self.tmp.name)
        self.app = bridge.BridgeApp(self.cfg)
        handler = type("H", (bridge.BridgeHandler,), {"app": self.app})
        self.srv = bridge.BridgeServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)  # LIFO: 先 shutdown 再 server_close
        self.addCleanup(self.tmp.cleanup)
    def _post_declared_length(self, token, length):
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        try:
            conn.request("POST", "/v1/chat/completions",
                         headers={"X-Bridge-Token": token, "Content-Length": str(length)})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()
    def test_401_precedes_body_too_large(self):
        st, body = self._post_declared_length("wrong", bridge.MAX_BODY_BYTES + 1)
        self.assertEqual((st, json.loads(body)["error"]["code"]), (401, "unauthorized"))
    def test_413_body_too_large(self):
        st, body = self._post_declared_length("t0k", bridge.MAX_BODY_BYTES + 1)
        self.assertEqual((st, json.loads(body)["error"]["code"]), (413, "body_too_large"))
class TestSupervisor(unittest.TestCase):
    """状态机: loading→ready→busy(卸载)→debounce→loading→ready；崩溃→down→重启。"""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(self.tmp.name)
        self.transport = ScriptedTransport()
        self.game_on, self.now, self.spawn_count = [False], [1000.0], 0
        self.sup = bridge.EngineSupervisor(
            self.cfg, transport=self.transport, spawner=self._spawn,
            tasklist=lambda p: self.game_on[0], vram_probe=lambda: 1200,
            clock=lambda: self.now[0])
    def _spawn(self):
        self.spawn_count += 1
        p = FakeProc(pid=2000 + self.spawn_count)
        self.transport.proc = p
        return p
    def _tick(self, advance=1.0):
        self.now[0] += advance
        self.sup.tick()
    def tearDown(self):
        self.tmp.cleanup()
    def test_full_cycle(self):
        self.sup.spawn()
        self.assertEqual(self.sup.state, "loading")
        self._tick()
        self.assertEqual(self.sup.state, "ready")
        urls = [c["url"] for c in self.transport.calls]
        self.assertTrue(any("set_gpt_weights" in u for u in urls))
        self.assertTrue(any("set_sovits_weights" in u for u in urls))
        self.assertEqual(self.sup.engine_pid, 2001)
        # 游戏出现 → busy + 卸载调用序: /control?command=exit
        self.game_on[0] = True
        self._tick(5.0)
        self.assertEqual(self.sup.state, "busy")
        self.assertIsNone(self.sup.engine_pid)
        exits = [c for c in self.transport.calls if (c["params"] or {}).get("command") == "exit"]
        self.assertEqual((len(exits), self.sup.proc), (1, None))
        self._tick(30.0)  # busy 期间抑重启
        self.assertEqual((self.sup.state, self.spawn_count), ("busy", 1))
        # 游戏消失 → debounce 45s 回载（game_detected 按 5s 周期刷新，需两个轮询拍）
        self.game_on[0] = False
        self._tick(1.0)   # 检测仍是旧值 True，absence 未起算
        self.assertEqual(self.sup.state, "busy")
        self._tick(5.0)   # 轮询拍: absence_since 起算
        self.assertEqual(self.sup.state, "busy")
        self._tick(50.0)  # 50s >= debounce 45s → 回载
        self.assertEqual((self.sup.state, self.spawn_count), ("loading", 2))
        self._tick(1.0)
        self.assertEqual(self.sup.state, "ready")
    def test_crash_restart(self):
        self.sup.spawn()
        self._tick()
        self.assertEqual(self.sup.state, "ready")
        self.transport.proc.exited = True
        self._tick()
        self.assertEqual(self.sup.state, "down")
        self._tick(10.0)
        self.assertEqual((self.sup.state, self.spawn_count), ("loading", 2))
    def test_startup_timeout(self):
        self.cfg["engine"]["startup_timeout_s"] = 5
        dead, procs = ScriptedTransport(alive=False), []  # 探针永不通
        def spawn():
            p = FakeProc(pid=777)
            procs.append(p)
            dead.proc = p
            return p
        self.sup.spawner, self.sup.transport = spawn, dead
        self.sup.spawn()
        for _ in range(7):
            self._tick(1.0)
        self.assertEqual(self.sup.state, "down")
        self.assertTrue(procs[0].exited)
    def test_unload_taskkill_fallback(self):
        # F15: exit/kill 都打不死 → taskkill /T /F 兜底；墙钟用 mock 走快表
        killed = []
        stubborn = FakeProc(pid=3221)
        stubborn.kill = lambda: setattr(stubborn, "killed", True)  # kill 无效不退出
        def fake_taskkill(pid):
            killed.append(pid)
            stubborn.exited = True
            return True
        self.sup.taskkiller = fake_taskkill
        self.sup.proc, self.sup.engine_pid, self.sup.state = stubborn, stubborn.pid, "ready"
        clock = {"t": 0.0}
        def fake_monotonic():
            clock["t"] += 1.0
            return clock["t"]
        with mock.patch.object(bridge.time, "monotonic", side_effect=fake_monotonic), \
             mock.patch.object(bridge.time, "sleep", lambda *_: None):
            self.sup._unload()
        self.assertEqual(killed, [3221])
        self.assertIsNone(self.sup.proc)
        self.assertIsNone(self.sup.engine_pid)
if __name__ == "__main__":
    unittest.main()
