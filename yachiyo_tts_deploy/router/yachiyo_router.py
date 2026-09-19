#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yachiyo-tts-router — AstrBot TTS 分流路由器（CONTRACT §3 v1, 2026-09-20）。

Ubuntu 24.04 / Python 3.12，stdlib-only。bind 172.19.0.1:8800（docker 网桥）。
POST /v1/chat/completions 决策：TTS 形状=JSON 顶层 audio 对象。
  非 JSON / 非 TTS / mode=cloud            → 原样透传云（全头+原始 bytes+响应原样回）
  mode=auto : bridge ready → 走桥（剥 audio.voice、加 X-Bridge-Token、connect 2s/总 8s）
              桥非200/超时/state!=ready → 原样完整 body 透传云（fallback）
  mode=local: 走桥；失败（含 probe=down）→ 502 bridge_unavailable，不上云
其余路径/方法永远透传。GET /health 公开状态；POST /admin/mode 切 mode（X-Bridge-Token 门控）。
"""
import argparse
import hmac
import http.client
import json
import os
import signal
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.0.0"
VALID_MODES = ("auto", "local", "cloud")
BRIDGE_STATES = ("ready", "busy", "loading", "down")
DEFAULT_CONFIG_PATH = "/etc/yachiyo-tts-router/config.json"
MAX_BODY_BYTES = 64 * 1024 * 1024
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailers", "transfer-encoding", "upgrade"}
REQ_SKIP = HOP_BY_HOP | {"host", "content-length", "expect", "x-bridge-token"}


def _now_iso():
    # F21: 统一 UTC 带显式 Z 后缀（日志/health/state 落盘一致）
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms(started):
    return int((time.monotonic() - started) * 1000)


class BridgeUnavailable(Exception):
    """桥连接/超时失败（connect 或总超时内未完成）。"""


class RouterConfig:
    def __init__(self, raw):
        if not isinstance(raw, dict):
            raise ValueError("config 根必须是 JSON 对象")
        self.bind_host = str(raw.get("bind_host") or "172.19.0.1")
        self.bind_port = int(raw.get("bind_port") or 8800)
        self.bridge_url = str(raw.get("bridge_url") or "http://127.0.0.1:9881").rstrip("/")
        self.cloud_base_url = str(raw.get("cloud_base_url") or "https://api.xiaomimimo.com").rstrip("/")
        self.bridge_token = str(raw.get("bridge_token") or "")
        self.probe_interval_s = float(raw.get("probe_interval_s") or 30)
        self.probe_connect_timeout_s = float(raw.get("probe_connect_timeout_s") or 2)
        self.probe_total_timeout_s = float(raw.get("probe_total_timeout_s") or 5)
        self.probe_fail_threshold = max(1, int(raw.get("probe_fail_threshold") or 2))
        self.bridge_connect_timeout_s = float(raw.get("bridge_connect_timeout_s") or 2)
        self.bridge_total_timeout_s = float(raw.get("bridge_total_timeout_s") or 8)
        self.cloud_timeout_s = float(raw.get("cloud_timeout_s") or 120)  # F18: 整个透传墙钟上限（含读响应；复审 M：对齐插件 120s 余量）
        self.state_dir = Path(str(raw.get("state_dir") or "/var/lib/yachiyo-tts-router"))
        self.log_path = Path(str(raw.get("log_path") or "/var/log/yachiyo-tts-router/router.log"))
        if not self.bridge_url or not self.cloud_base_url:
            raise ValueError("bridge_url / cloud_base_url 不能为空")


class RouterLog:
    """每请求一行结构化日志；文件超 10MB 轮转 .1（留一份）；同时回显 stderr（journald）。"""
    MAX_BYTES = 10 * 1024 * 1024

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._fh = None

    def write(self, line):
        with self._lock:
            try:
                if self._fh is None:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self._fh = open(self.path, "a", encoding="utf-8", newline="\n")
                if self._fh.tell() >= self.MAX_BYTES:
                    self._rotate()
                self._fh.write(line + "\n")
                self._fh.flush()
            except OSError:
                pass
        try:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        except Exception:
            pass

    def _rotate(self):
        try:
            self._fh.close()
        except OSError:
            pass
        target = self.path.with_name(self.path.name + ".1")
        try:
            if target.exists():
                target.unlink()
            os.replace(self.path, target)
        except OSError:
            pass
        self._fh = open(self.path, "a", encoding="utf-8", newline="\n")

    def close(self):
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None


def http_call(url, *, method, headers, body, connect_timeout, total_timeout):
    """单次 HTTP 请求，真墙钟 deadline：connect/发送/getresponse/read 每阶段前重算
    remaining，≤0 抛 BridgeUnavailable；socket 超时随 remaining 收紧（F17/F19）。"""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    deadline = time.monotonic() + total_timeout

    def _remaining(phase):
        left = deadline - time.monotonic()
        if left <= 0:
            raise BridgeUnavailable("total timeout before %s" % phase)
        return left

    try:
        sock = socket.create_connection((host, port), timeout=min(connect_timeout, _remaining("connect")))
    except BridgeUnavailable:
        raise
    except OSError as exc:
        raise BridgeUnavailable("connect failed: %s" % exc) from exc
    conn = None
    try:
        if parts.scheme == "https":
            sock.settimeout(_remaining("tls"))
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        conn = http.client.HTTPConnection(host, port, timeout=_remaining("request"))
        conn.sock = sock
        sock.settimeout(_remaining("request"))   # 发送 + 等响应头
        conn.request(method, target, body=body, headers=headers)
        sock.settimeout(_remaining("response"))  # 复审 L：等响应头前再收紧
        resp = conn.getresponse()
        sock.settimeout(_remaining("read"))      # 读响应体
        data = resp.read()
        return resp.status, resp.getheaders(), data
    except BridgeUnavailable:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise BridgeUnavailable("request failed: %s" % exc) from exc
    finally:
        if conn is not None:  # F19: 连接（含响应）必关，防 fd 泄漏
            try:
                conn.close()
            except Exception:
                pass
        try:
            sock.close()
        except OSError:
            pass


class AppState:
    """并发共享状态（锁护）：mode、bridge_state、探测连失计数、日期键控计数器。"""

    def __init__(self, cfg, date_provider=None):
        self.cfg = cfg
        self._lock = threading.RLock()
        self._date_fn = date_provider or date.today
        self.mode = "auto"
        self.bridge_state = "unknown"  # 首次探测前
        self._fail_streak = 0
        self.counters = {}
        self.last_fallback = None
        self.state_file = cfg.state_dir / "state.json"
        self.counters_file = cfg.state_dir / "counters.json"

    @staticmethod
    def _write_json(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)

    def load(self):
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("mode") in VALID_MODES:
                self.mode = data["mode"]
        except (OSError, ValueError):
            pass
        try:
            data = json.loads(self.counters_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, val in data.items():
                    if isinstance(val, dict):
                        self.counters[key] = {"bridge": int(val.get("bridge") or 0),
                                              "cloud": int(val.get("cloud") or 0)}
        except (OSError, ValueError, TypeError):
            pass

    def mode_value(self):
        with self._lock:
            return self.mode

    def routing_snapshot(self):
        with self._lock:
            return self.mode, self.bridge_state

    def set_mode(self, mode):
        with self._lock:
            self.mode = mode
            self._write_json(self.state_file, {"mode": mode, "saved_at": _now_iso()})

    def record_probe(self, ok, state=None):
        with self._lock:
            if ok and state in BRIDGE_STATES:
                self._fail_streak = 0
                self.bridge_state = state
            else:
                self._fail_streak += 1
                if self._fail_streak >= self.cfg.probe_fail_threshold:
                    self.bridge_state = "down"

    def record(self, engine):
        with self._lock:
            key = self._date_fn().isoformat()
            day = self.counters.setdefault(key, {"bridge": 0, "cloud": 0})
            day[engine] = day.get(engine, 0) + 1
            keep = {key, (self._date_fn() - timedelta(days=1)).isoformat()}
            self.counters = {k: v for k, v in self.counters.items() if k in keep}
            self._write_json(self.counters_file, self.counters)

    def note_fallback(self):
        with self._lock:
            self.last_fallback = _now_iso()

    def health_snapshot(self):
        with self._lock:
            today = dict(self.counters.get(self._date_fn().isoformat(), {}))
            today.setdefault("bridge", 0)
            today.setdefault("cloud", 0)
            state = self.bridge_state
            if state == "ready":
                busy = None
            elif state == "unknown":
                busy = "probe_pending"
            else:
                busy = "bridge_" + state
            return {"mode": self.mode, "bridge_state": state,
                    "today": {"bridge": int(today["bridge"]), "cloud": int(today["cloud"])},
                    "busy_reason": busy, "last_fallback": self.last_fallback, "ts": _now_iso()}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 3xx 原样透传客户端


def _resp_socket(resp):
    """取响应底层 socket（成功则可为每段读收紧超时）；取不到返回 None。
    复审 M：urllib3 形态 resp.fp.raw._sock 在 stdlib 下常取不到——多级回退。"""
    for cand in (lambda: resp.fp.raw._sock,
                 lambda: resp.fp._sock):
        try:
            return cand()
        except Exception:
            continue
    return None


def read_with_deadline(resp, deadline, chunk=65536):
    """墙钟 deadline 内分块读响应体（F18）：每块前重算剩余并收紧 socket 超时，
    ≤0 抛 TimeoutError——urllib 原生 timeout 只覆盖单次 open，不含整体读预算。"""
    sock = _resp_socket(resp)
    parts = []
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("cloud passthrough total timeout")
        if sock is not None:
            try:
                sock.settimeout(left)
            except OSError:
                pass
        piece = resp.read(chunk)
        if not piece:
            break
        parts.append(piece)
    return b"".join(parts)


class _RouterServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    server_version = "yachiyo-tts-router/" + VERSION
    protocol_version = "HTTP/1.1"
    timeout = 60

    def log_message(self, fmt, *args):
        pass  # 自有结构化日志，且默认 stderr 噪声会带请求行

    # ---- 分发 ----
    def _dispatch(self, method):
        try:
            path = urllib.parse.urlsplit(self.path).path
            if method == "GET" and path == "/health":
                self._send_json(200, self.server.app.state.health_snapshot())
            elif method == "POST" and path == "/admin/mode":
                self._handle_admin_mode()
            elif method == "POST" and path == "/v1/chat/completions":
                self._handle_chat()
            else:
                self._proxy(method)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as exc:  # 兜底：线程不崩
            try:
                # 复审 L：对外固定文案（不泄 str(exc)），细节只进日志
                self._send_json(500, {"error": {"message": "router internal error",
                                                "code": "internal", "type": "router_error"}})
            except Exception:
                self.close_connection = True
            try:
                self.server.app.log_event("error path=%s exception=%r" % (path, exc))
            except Exception:
                pass

    do_GET = lambda self: self._dispatch("GET")
    do_POST = lambda self: self._dispatch("POST")
    do_PUT = lambda self: self._dispatch("PUT")
    do_PATCH = lambda self: self._dispatch("PATCH")
    do_DELETE = lambda self: self._dispatch("DELETE")
    do_HEAD = lambda self: self._dispatch("HEAD")
    do_OPTIONS = lambda self: self._dispatch("OPTIONS")

    # ---- 工具 ----
    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return b""
        if n > MAX_BODY_BYTES:
            raise ValueError("body too large: %d" % n)
        return self.rfile.read(n)

    def _send(self, status, body, content_type="application/json"):
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _send_json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _send_raw(self, status, header_pairs, body):
        self.send_response(int(status))
        for key, val in header_pairs:
            if key.lower() in HOP_BY_HOP or key.lower() == "content-length":
                continue
            self.send_header(key, val)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _token_ok(self):
        cfg = self.server.app.cfg
        given = (self.headers.get("X-Bridge-Token") or "").encode("utf-8")
        want = cfg.bridge_token.encode("utf-8")
        return bool(cfg.bridge_token) and hmac.compare_digest(given, want)

    # ---- 端点 ----
    def _handle_admin_mode(self):
        app = self.server.app
        # 复审 L：先鉴权再读 body（与 bridge 同序，未授权不消费请求体）
        if not self._token_ok():
            app.log_event("admin mode_set denied (bad token)")
            self.close_connection = True
            self._send_json(401, {"error": {"message": "unauthorized", "code": "unauthorized",
                                            "type": "router_error"}})
            return
        body = self._read_body()
        try:
            payload = json.loads(body.decode("utf-8"))
            new_mode = payload["mode"]
        except Exception:
            self._send_json(400, {"error": {"message": "body must be JSON {\"mode\": \"auto|local|cloud\"}",
                                            "code": "invalid_body", "type": "router_error"}})
            return
        if new_mode not in VALID_MODES:
            self._send_json(400, {"error": {"message": "mode must be one of auto|local|cloud",
                                            "code": "invalid_mode", "type": "router_error"}})
            return
        app.state.set_mode(new_mode)
        app.log_event("admin mode_set=%s ok=true" % new_mode)
        self._send_json(200, {"ok": True, "mode": new_mode})

    def _handle_chat(self):
        app = self.server.app
        started = time.monotonic()
        body = self._read_body()
        mode, bridge_state = app.state.routing_snapshot()
        parsed = None
        try:
            obj = json.loads(body)
            if isinstance(obj, dict) and isinstance(obj.get("audio"), dict):
                parsed = obj  # TTS 形状 = 顶层 audio 对象
        except Exception:
            parsed = None

        if parsed is None:  # 坏 JSON / 非 TTS → 透传（不计 TTS 计数）
            self._proxy("POST", body=body, count_tts=False, reason="forward", mode=mode)
            return
        if mode == "cloud":
            self._proxy("POST", body=body, count_tts=True, reason="forward", mode=mode)
            return

        attempt = (bridge_state == "ready") if mode == "auto" else (bridge_state != "down")
        if not attempt:
            if mode == "local":
                self._reply_local_unavailable(app, started)
                return
            app.state.note_fallback()
            self._proxy("POST", body=body, count_tts=True, reason="probe", mode=mode)
            return

        ok, status, resp_headers, data = self._call_bridge(parsed)
        if ok and status == 200:
            app.state.record("bridge")
            self._send_raw(200, resp_headers, data)
            app.log_request(mode, "bridge", 200, _ms(started), len(data), "forward")
            return
        if mode == "local":
            self._reply_local_unavailable(app, started)
            return
        app.state.note_fallback()
        self._proxy("POST", body=body, count_tts=True, reason="fallback", mode=mode)

    def _reply_local_unavailable(self, app, started):
        payload = json.dumps({"error": {"message": "yachiyo local bridge unavailable",
                                        "code": "bridge_unavailable", "type": "router_error"}},
                             ensure_ascii=False).encode("utf-8")
        self._send(502, payload)
        app.log_request(app.state.mode_value(), "bridge", 502, _ms(started), len(payload), "fallback")

    def _call_bridge(self, parsed):
        app = self.server.app
        obj = dict(parsed)
        audio = dict(parsed.get("audio") or {})
        audio.pop("voice", None)  # 剥参考音频，走桥不带
        obj["audio"] = audio
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "X-Bridge-Token": app.cfg.bridge_token}
        try:
            status, resp_headers, data = http_call(
                app.cfg.bridge_url + "/v1/chat/completions", method="POST", headers=headers,
                body=payload, connect_timeout=app.cfg.bridge_connect_timeout_s,
                total_timeout=app.cfg.bridge_total_timeout_s)
            return True, status, resp_headers, data
        except BridgeUnavailable:
            return False, 0, [], b""

    # ---- 透传 ----
    def _proxy(self, method, body=None, count_tts=False, reason="forward", mode=None):
        app = self.server.app
        started = time.monotonic()
        if body is None:
            body = self._read_body()
        if mode is None:
            mode = app.state.mode_value()
        status, out, resp = 502, b"", None
        deadline = time.monotonic() + app.cfg.cloud_timeout_s  # F18: 整个透传墙钟 deadline
        try:
            headers = {k: v for k, v in self.headers.items() if k.lower() not in REQ_SKIP}
            req = urllib.request.Request(app.cfg.cloud_base_url + self.path,
                                         data=(body if body else None), headers=headers, method=method)
            try:
                resp = app.cloud_opener.open(req, timeout=max(0.001, deadline - time.monotonic()))
            except urllib.error.HTTPError as err:
                resp = err  # 非 2xx 也是"拿到云响应"，原样回
            out = read_with_deadline(resp, deadline)
            status = getattr(resp, "status", None) or getattr(resp, "code", 502)
            hdrs = getattr(resp, "headers", None) or getattr(resp, "hdrs", [])
            if count_tts:  # 先计数后回包（与 bridge 路径一致）：杜绝回包后日期翻转的错键竞态
                app.state.record("cloud")
            self._send_raw(status, hdrs.items(), out)
        except Exception as exc:
            status = 502
            out = json.dumps({"error": {"message": "cloud upstream unreachable: %s" % exc,
                                        "code": "cloud_unreachable", "type": "router_error"}},
                             ensure_ascii=False).encode("utf-8")
            try:
                self._send(502, out)
            except Exception:
                self.close_connection = True
        finally:
            if resp is not None:  # F19: 上游响应（含 HTTPError）必关，防 fd 泄漏
                try:
                    resp.close()
                except Exception:
                    pass
            app.log_request(mode, "cloud", status, _ms(started), len(out), reason)


class RouterApp:
    def __init__(self, raw_config, date_provider=None):
        self.cfg = RouterConfig(raw_config)
        self.log = RouterLog(self.cfg.log_path)
        self.state = AppState(self.cfg, date_provider)
        self.state.load()
        self.cloud_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._stop = threading.Event()
        self._stopped = False
        self._probe_thread = None
        self._server_thread = None
        self.server = _RouterServer((self.cfg.bind_host, self.cfg.bind_port), self)

    @property
    def port(self):
        return self.server.server_address[1]

    def start(self):
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self._probe_thread = threading.Thread(target=self._probe_loop, name="probe", daemon=True)
        self._probe_thread.start()
        self._server_thread = threading.Thread(target=self.server.serve_forever,
                                               kwargs={"poll_interval": 0.2}, name="http", daemon=True)
        self._server_thread.start()

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        if self._probe_thread is not None:
            self._probe_thread.join(timeout=3)
        self.server.shutdown()
        self.server.server_close()
        self.log.close()

    def run_forever(self):
        self.start()

        def _sig(signum, frame):
            self._stop.set()

        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)
        while not self._stop.is_set():
            self._stop.wait(1.0)
        self.stop()

    def _probe_loop(self):
        while not self._stop.is_set():
            self._probe_once()
            self._stop.wait(self.cfg.probe_interval_s)

    def _probe_once(self):
        cfg = self.cfg
        try:
            status, _, data = http_call(cfg.bridge_url + "/health", method="GET",
                                        headers={"Accept": "application/json"}, body=None,
                                        connect_timeout=cfg.probe_connect_timeout_s,
                                        total_timeout=cfg.probe_total_timeout_s)
            if status != 200:
                raise BridgeUnavailable("health status %d" % status)
            payload = json.loads(data.decode("utf-8"))
            state = payload.get("state") if isinstance(payload, dict) else None
            self.state.record_probe(True, state if isinstance(state, str) else None)
        except Exception:
            self.state.record_probe(False)

    def log_request(self, mode, engine, status, ms, nbytes, reason):
        self.log.write("%s mode=%s engine=%s status=%s ms=%d bytes=%d reason=%s"
                       % (_now_iso(), mode, engine, status, ms, nbytes, reason))

    def log_event(self, text):
        self.log.write("%s %s" % (_now_iso(), text))


def load_config_file(path):
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit("config 读取失败: %s (%s)" % (path, exc))
    except ValueError as exc:
        raise SystemExit("config JSON 解析失败: %s (%s)" % (path, exc))
    if not isinstance(raw, dict):
        raise SystemExit("config 根必须是 JSON 对象: %s" % path)
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description="yachiyo-tts-router (stdlib-only TTS router)")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="配置文件路径（JSON, utf-8）")
    args = parser.parse_args(argv)
    app = RouterApp(load_config_file(args.config))
    if app.cfg.bridge_token in ("", "CHANGE_ME"):
        app.log_event("WARNING bridge_token 未注入（空或 CHANGE_ME）：桥鉴权将失败、/admin/mode 将拒绝，"
                      "请在 config.json 填入与 Windows 侧 bridge 同值的 token")
    app.log_event("startup version=%s bind=%s:%d bridge_url=%s cloud=%s state_dir=%s"
                  % (VERSION, app.cfg.bind_host, app.cfg.bind_port, app.cfg.bridge_url,
                     app.cfg.cloud_base_url, app.cfg.state_dir))
    app.run_forever()


if __name__ == "__main__":
    main()
