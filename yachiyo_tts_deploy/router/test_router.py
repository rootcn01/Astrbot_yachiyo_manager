#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yachiyo_router 单元测试（stdlib unittest，零外部网络）。

上游 bridge 与云均用本地线程 mock HTTP server；router 实例 bind 127.0.0.1:0。
覆盖 CONTRACT §3 决策表：auto×{ready,busy,loading,down}、local×{ready,桥挂,桥错}、cloud、
非TTS/坏JSON 透传、audio.voice 剥离、token 门控、计数与日期滚动、探测连失2次降down再恢复、
透传 Authorization 保留 + body 字节级一致。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import date
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from yachiyo_router import RouterApp  # noqa: E402

TEST_TOKEN = "test-bridge-token-123"
TTS_REPLY = {"id": "chatcmpl-mock", "object": "chat.completion", "created": 1758000000,
             "model": "mimo-v2.5-tts-voiceclone",
             "choices": [{"index": 0, "finish_reason": "stop",
                          "message": {"role": "assistant", "content": None,
                                      "audio": {"data": "UklGRj4AAABXQVZFZm10IBAAAAABAAEA",
                                                "transcript": "", "expires_at": 0}}}],
             "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


def tts_body_bytes(voice="data:audio/wav;base64,QUJDREVG"):
    payload = {"model": "mimo-v2.5-tts-voiceclone",
               "messages": [{"role": "user", "content": "style ctx"},
                            {"role": "assistant", "content": "テスト本文です"}],
               "audio": {"format": "wav", "voice": voice}}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class _MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        return self.rfile.read(n) if n > 0 else b""

    def _rec(self, body):
        owner = self.server.owner
        with owner.lock:
            owner.records.append({"method": self.command, "path": self.path,
                                  "headers": {k: v for k, v in self.headers.items()}, "body": body})

    def _reply(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        self._rec(b"")
        owner = self.server.owner
        with owner.lock:
            fail_next = owner.fail_health_next
            if self.path == "/health" and fail_next > 0:
                owner.fail_health_next = fail_next - 1
                fail_now = True
            else:
                fail_now = False
            state, health_status = owner.bridge_state, owner.health_status
        if self.path == "/health":
            if fail_now or health_status != 200:
                self._reply(500, b'{"error":"mock health fail"}')
                return
            self._reply(200, json.dumps({"state": state, "game_detected": False,
                                         "vram_used_mib": 0, "engine_pid": 1,
                                         "last_synth_at": None, "ts": "x"}).encode())
            return
        self._reply(200, json.dumps({"mock": "cloud", "path": self.path}).encode())

    def do_POST(self):
        body = self._read_body()
        self._rec(body)
        owner = self.server.owner
        with owner.lock:
            token, status, cbody = owner.token, owner.completions_status, owner.completions_body
            stall = owner.stall_body_seconds
        if self.path == "/v1/chat/completions":
            if token is not None and self.headers.get("X-Bridge-Token") != token:
                self._reply(401, b'{"error":{"message":"bad token","code":"unauthorized",'
                                 b'"type":"bridge_error"}}')
                return
            if stall and stall > 0:  # 先发响应头、滞住响应体（测透传读 deadline）
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cbody)))
                self.end_headers()
                time.sleep(stall)
                try:
                    if self.command != "HEAD":
                        self.wfile.write(cbody)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # 客户端已按 deadline 超时断开
                return
            self._reply(status, cbody)
            return
        self._reply(200, json.dumps({"mock": "cloud", "path": self.path}).encode())


class MockUpstream:
    def __init__(self, token=None):
        self.records = []
        self.lock = threading.Lock()
        self.token = token
        self.bridge_state = "ready"
        self.fail_health_next = 0
        self.health_status = 200
        self.completions_status = 200
        self.completions_body = json.dumps(TTS_REPLY).encode()
        self.stall_body_seconds = 0.0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        self.server.owner = self
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def completions(self):
        with self.lock:
            return [r for r in self.records if r["path"] == "/v1/chat/completions"]

    def set_state(self, state):
        with self.lock:
            self.bridge_state = state

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class RouterTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="yachiyo-router-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cloud = MockUpstream()
        self.addCleanup(self.cloud.stop)
        self.bridge = MockUpstream(token=TEST_TOKEN)
        self.addCleanup(self.bridge.stop)
        self._date_holder = {"today": date(2026, 9, 20)}
        self.app = None

    def start_app(self, **over):
        cfg = {"bind_host": "127.0.0.1", "bind_port": 0,
               "bridge_url": self.bridge.url, "cloud_base_url": self.cloud.url,
               "bridge_token": TEST_TOKEN,
               "probe_interval_s": 0.05, "probe_connect_timeout_s": 1.0,
               "probe_fail_threshold": 2,
               "bridge_connect_timeout_s": 1.0, "bridge_total_timeout_s": 3.0,
               "cloud_timeout_s": 5.0,
               "state_dir": str(self.tmp / "state"), "log_path": str(self.tmp / "router.log")}
        cfg.update(over)
        app = RouterApp(cfg, date_provider=lambda: self._date_holder["today"])
        app.start()
        self.addCleanup(app.stop)
        if self.app is None:
            self.app = app
        return app

    def wait_state(self, want, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.app.state.bridge_state == want:
                return
            time.sleep(0.02)
        self.fail("bridge_state != %s (actual %s)" % (want, self.app.state.bridge_state))

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.app.port, timeout=15)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k: v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def send_tts(self, body=None, auth="Bearer sk-test-123"):
        return self.request("POST", "/v1/chat/completions", body or tts_body_bytes(),
                            {"Authorization": auth, "Content-Type": "application/json"})

    def set_mode(self, mode, token=TEST_TOKEN):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Bridge-Token"] = token
        return self.request("POST", "/admin/mode", json.dumps({"mode": mode}).encode(), headers)

    def cloud_hits(self, path=None):
        with self.cloud.lock:
            return [r for r in self.cloud.records if path is None or r["path"] == path]

    def header_of(self, rec, name):
        for k, v in rec["headers"].items():
            if k.lower() == name.lower():
                return v
        return None

    # ---------- 决策表 ----------

    def test_auto_ready_routes_to_bridge(self):
        self.start_app()
        self.wait_state("ready")
        status, _, out = self.send_tts()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(out), TTS_REPLY)
        self.assertEqual(len(self.bridge.completions()), 1)
        self.assertEqual(self.cloud_hits("/v1/chat/completions"), [])
        snap = json.loads(self.request("GET", "/health")[2])
        self.assertEqual(snap["today"], {"bridge": 1, "cloud": 0})
        self.assertIsNone(snap["busy_reason"])

    def test_auto_ready_strips_voice_and_keeps_rest(self):
        self.start_app()
        self.wait_state("ready")
        self.send_tts()
        rec = self.bridge.completions()[0]
        sent = json.loads(rec["body"])
        self.assertNotIn("voice", sent["audio"])  # 剥离参考音频
        self.assertEqual(sent["audio"]["format"], "wav")
        self.assertEqual(sent["model"], "mimo-v2.5-tts-voiceclone")
        self.assertEqual(len(sent["messages"]), 2)
        self.assertEqual(self.header_of(rec, "X-Bridge-Token"), TEST_TOKEN)

    def test_auto_busy_falls_back_to_cloud_bytes_identical(self):
        self.start_app()
        self.wait_state("ready")
        self.bridge.set_state("busy")
        self.wait_state("busy")
        raw = tts_body_bytes()
        status, _, out = self.send_tts(body=raw)
        self.assertEqual(status, 200)
        self.assertEqual(self.bridge.completions(), [])  # busy 不走桥
        rec = self.cloud_hits("/v1/chat/completions")[0]
        self.assertEqual(rec["body"], raw)  # 原样完整 body（含 voice）
        self.assertEqual(self.header_of(rec, "Authorization"), "Bearer sk-test-123")
        snap = json.loads(self.request("GET", "/health")[2])
        self.assertEqual(snap["today"]["cloud"], 1)
        self.assertIsNotNone(snap["last_fallback"])

    def test_auto_loading_falls_back_to_cloud(self):
        self.start_app()
        self.wait_state("ready")
        self.bridge.set_state("loading")
        self.wait_state("loading")
        status, _, _ = self.send_tts()
        self.assertEqual(status, 200)
        self.assertEqual(self.bridge.completions(), [])
        self.assertEqual(len(self.cloud_hits("/v1/chat/completions")), 1)
        snap = json.loads(self.request("GET", "/health")[2])
        self.assertEqual(snap["busy_reason"], "bridge_loading")

    def test_auto_down_falls_back_without_touching_bridge(self):
        self.start_app()
        self.wait_state("ready")
        with self.bridge.lock:
            self.bridge.fail_health_next = 2
        self.wait_state("down")
        status, _, _ = self.send_tts()
        self.assertEqual(status, 200)
        self.assertEqual(self.bridge.completions(), [])
        self.assertEqual(len(self.cloud_hits("/v1/chat/completions")), 1)
        snap = json.loads(self.request("GET", "/health")[2])
        self.assertEqual(snap["bridge_state"], "down")
        self.assertEqual(snap["busy_reason"], "bridge_down")

    def test_auto_bridge_non200_falls_back_to_cloud(self):
        self.start_app()
        self.wait_state("ready")
        self.bridge.completions_status = 500
        raw = tts_body_bytes()
        status, _, _ = self.send_tts(body=raw)
        self.assertEqual(status, 200)
        self.assertEqual(len(self.bridge.completions()), 1)  # 试过桥
        self.assertEqual(self.cloud_hits("/v1/chat/completions")[0]["body"], raw)

    def test_local_ready_routes_to_bridge(self):
        self.start_app()
        self.wait_state("ready")
        self.assertEqual(self.set_mode("local")[0], 200)
        status, _, out = self.send_tts()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(out), TTS_REPLY)
        self.assertEqual(len(self.bridge.completions()), 1)
        self.assertEqual(self.cloud_hits("/v1/chat/completions"), [])

    def test_local_bridge_down_returns_502(self):
        self.start_app()
        self.wait_state("ready")
        self.set_mode("local")
        with self.bridge.lock:
            self.bridge.fail_health_next = 2
        self.wait_state("down")
        status, _, out = self.send_tts()
        self.assertEqual(status, 502)
        err = json.loads(out)["error"]
        self.assertEqual(err["code"], "bridge_unavailable")
        self.assertEqual(err["message"], "yachiyo local bridge unavailable")
        self.assertEqual(err["type"], "router_error")
        self.assertEqual(self.bridge.completions(), [])  # down 不等待不打扰
        self.assertEqual(self.cloud_hits("/v1/chat/completions"), [])  # local 绝不上云

    def test_local_bridge_non200_returns_502(self):
        self.start_app()
        self.wait_state("ready")
        self.set_mode("local")
        self.bridge.completions_status = 503
        status, _, out = self.send_tts()
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(out)["error"]["code"], "bridge_unavailable")
        self.assertEqual(self.cloud_hits("/v1/chat/completions"), [])

    def test_cloud_mode_always_forwards_to_cloud(self):
        self.start_app()
        self.wait_state("ready")
        self.set_mode("cloud")
        status, _, _ = self.send_tts()
        self.assertEqual(status, 200)
        self.assertEqual(self.bridge.completions(), [])
        self.assertEqual(len(self.cloud_hits("/v1/chat/completions")), 1)
        snap = json.loads(self.request("GET", "/health")[2])
        self.assertEqual(snap["today"]["cloud"], 1)
        self.assertIsNone(snap["last_fallback"])  # 主动 cloud 不算回退

    def test_non_tts_shape_passthrough(self):
        self.start_app()
        self.wait_state("ready")
        raw = json.dumps({"model": "mimo-v2.5-audio", "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]}]}).encode()
        status, _, _ = self.send_tts(body=raw)
        self.assertEqual(status, 200)
        self.assertEqual(self.bridge.completions(), [])
        rec = self.cloud_hits("/v1/chat/completions")[0]
        self.assertEqual(rec["body"], raw)
        self.assertEqual(self.header_of(rec, "Authorization"), "Bearer sk-test-123")
        snap = json.loads(self.request("GET", "/health")[2])
        self.assertEqual(snap["today"], {"bridge": 0, "cloud": 0})  # 非TTS 不进引擎计数

    def test_bad_json_passthrough_bytes_identical(self):
        self.start_app()
        self.wait_state("ready")
        raw = b'{"model": "broken", "messages": ['
        status, _, _ = self.send_tts(body=raw)
        self.assertEqual(status, 200)
        self.assertEqual(self.bridge.completions(), [])
        self.assertEqual(self.cloud_hits("/v1/chat/completions")[0]["body"], raw)

    def test_passthrough_strips_bridge_token_header(self):
        # F22: X-Bridge-Token 只发给 bridge，绝不透传给云
        self.start_app()
        self.wait_state("ready")
        raw = json.dumps({"model": "mimo-v2.5-audio", "messages": [
            {"role": "user", "content": "hi"}]}).encode()
        status, _, _ = self.request("POST", "/v1/chat/completions", raw,
                                    {"Authorization": "Bearer sk-1", "Content-Type": "application/json",
                                     "X-Bridge-Token": TEST_TOKEN})
        self.assertEqual(status, 200)
        rec = self.cloud_hits("/v1/chat/completions")[0]
        self.assertIsNone(self.header_of(rec, "X-Bridge-Token"))
        self.assertEqual(self.header_of(rec, "Authorization"), "Bearer sk-1")

    def test_cloud_deadline_interrupts_stalled_body(self):
        # F18: 整个透传墙钟 deadline 含读响应——头已到但体滞住时按 deadline 中断回 502
        self.start_app(cloud_timeout_s=0.4)
        self.wait_state("ready")
        self.set_mode("cloud")
        with self.cloud.lock:
            self.cloud.stall_body_seconds = 1.2
        t0 = time.monotonic()
        status, _, out = self.send_tts()
        elapsed = time.monotonic() - t0
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(out)["error"]["code"], "cloud_unreachable")
        self.assertLess(elapsed, 0.9)  # 远小于 1.2s 滞住——deadline 生效
        with self.cloud.lock:
            self.cloud.stall_body_seconds = 0.0

    def test_other_path_and_method_passthrough(self):
        self.start_app()
        self.wait_state("ready")
        status, _, out = self.request("GET", "/v1/models?limit=1",
                                      headers={"Authorization": "Bearer sk-models"})
        self.assertEqual(status, 200)
        rec = self.cloud_hits("/v1/models?limit=1")[0]
        self.assertEqual(rec["method"], "GET")
        self.assertEqual(self.header_of(rec, "Authorization"), "Bearer sk-models")
        self.assertEqual(json.loads(out)["path"], "/v1/models?limit=1")

    # ---------- admin / health / 状态 ----------

    def test_admin_mode_requires_token(self):
        self.start_app()
        self.wait_state("ready")
        self.assertEqual(self.set_mode("cloud", token=None)[0], 401)
        self.assertEqual(self.set_mode("cloud", token="wrong-token")[0], 401)
        self.assertEqual(self.app.state.mode_value(), "auto")  # 未被改动
        self.assertEqual(self.request("POST", "/admin/mode",
                                      json.dumps({"mode": "cloud"}).encode(),
                                      {"X-Bridge-Token": TEST_TOKEN})[0], 200)

    def test_admin_mode_invalid_value_400(self):
        self.start_app()
        self.wait_state("ready")
        status, _, out = self.request("POST", "/admin/mode", b'{"mode": "turbo"}',
                                      {"X-Bridge-Token": TEST_TOKEN})
        self.assertEqual(status, 400)
        self.assertEqual(self.app.state.mode_value(), "auto")

    def test_admin_mode_switch_persists_to_state_json(self):
        self.start_app()
        self.wait_state("ready")
        status, _, out = self.set_mode("local")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(out), {"ok": True, "mode": "local"})
        saved = json.loads((self.tmp / "state" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["mode"], "local")
        snap = json.loads(self.request("GET", "/health")[2])
        self.assertEqual(snap["mode"], "local")

    def test_mode_restored_from_state_json_on_restart(self):
        state_dir = self.tmp / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text('{"mode": "cloud"}', encoding="utf-8")
        app = self.start_app()
        self.assertEqual(app.state.mode_value(), "cloud")

    def test_health_endpoint_shape(self):
        self.start_app()
        self.wait_state("ready")
        status, _, out = self.request("GET", "/health")
        self.assertEqual(status, 200)
        snap = json.loads(out)
        self.assertEqual(set(snap), {"mode", "bridge_state", "today", "busy_reason",
                                     "last_fallback", "ts"})
        self.assertEqual(snap["mode"], "auto")
        self.assertEqual(snap["bridge_state"], "ready")
        self.assertEqual(snap["today"], {"bridge": 0, "cloud": 0})

    # ---------- 探测语义 ----------

    def test_probe_single_failure_keeps_ready(self):
        self.start_app()
        self.wait_state("ready")
        with self.bridge.lock:
            self.bridge.fail_health_next = 1
        time.sleep(0.4)  # 若干个探测周期：1 次失败后连续成功
        self.assertEqual(self.app.state.bridge_state, "ready")

    def test_probe_two_consecutive_failures_down_then_recover(self):
        self.start_app()
        self.wait_state("ready")
        with self.bridge.lock:
            self.bridge.fail_health_next = 2
        self.wait_state("down")
        self.wait_state("ready")  # 恢复成功即回 ready

    # ---------- 计数器 ----------

    def test_counters_date_rollover_and_pruning(self):
        state_dir = self.tmp / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "counters.json").write_text(
            json.dumps({"2020-01-01": {"bridge": 9, "cloud": 9}}), encoding="utf-8")
        self.start_app()
        self.wait_state("ready")
        self._date_holder["today"] = date(2026, 9, 19)
        self.send_tts()  # D1: bridge +1
        self.set_mode("cloud")
        self.send_tts()  # D1: cloud +1
        self._date_holder["today"] = date(2026, 9, 20)
        self.set_mode("auto")
        self.send_tts()  # D2: bridge +1
        snap = json.loads(self.request("GET", "/health")[2])
        self.assertEqual(snap["today"], {"bridge": 1, "cloud": 0})  # 只看今日
        saved = json.loads((state_dir / "counters.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["2026-09-19"], {"bridge": 1, "cloud": 1})  # 昨日保留
        self.assertEqual(saved["2026-09-20"], {"bridge": 1, "cloud": 0})
        self.assertNotIn("2020-01-01", saved)  # 旧键清除


if __name__ == "__main__":
    unittest.main(verbosity=2)
