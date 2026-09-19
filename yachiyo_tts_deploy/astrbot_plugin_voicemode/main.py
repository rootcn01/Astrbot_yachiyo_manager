from __future__ import annotations

import asyncio
import inspect
import json
import urllib.error
import urllib.request
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:  # astrbot 容器自带 aiohttp；缺失时退 asyncio+urllib 线程兜底
    import aiohttp
except Exception:  # pragma: no cover
    aiohttp = None

# urllib 兜底不走环境代理：防容器 HTTP_PROXY 把带 token 的请求送代理
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_REQUEST_TIMEOUT_SECONDS = 5
_VALID_MODES = ("auto", "local", "cloud")
_MODE_NOTES = {
    "auto": "自动：本地 bridge 就绪时走本地，不可用时自动回落云端",
    "local": "本地强制：仅走本地 bridge，不可用时明确报错、不上云端",
    "cloud": "云端：语音全部走云端官方接口直连",
}
_BRIDGE_STATE_NOTES = {
    "ready": "就绪，本地合成可用",
    "busy": "忙碌，检测到游戏进程，本地合成已暂停",
    "loading": "加载中，引擎正在启动",
    "down": "离线，本地 bridge 不可达或已停止",
}
_DEFAULT_OWNER_IDS = ("1010233339",)


class RouterUnreachableError(RuntimeError):
    """router 连接失败或超时。"""


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


@register(
    "astrbot_plugin_voicemode",
    "lotus-zcode",
    "切换 yachiyo TTS 语音模式（auto/local/cloud）与状态查询",
    "1.0.0",
)
class VoiceModePlugin(Star):
    def __init__(self, context: Context, config: Any):
        super().__init__(context)
        self.context = context
        cfg = self._coerce_config(config)
        self.router_base_url = str(
            cfg.get("router_base_url") or "http://172.19.0.1:8800"
        ).strip().rstrip("/")
        self.bridge_token = str(cfg.get("bridge_token") or "").strip()
        raw_owners = cfg.get("owner_ids") or list(_DEFAULT_OWNER_IDS)
        self.owner_ids = {
            str(item).strip() for item in raw_owners if str(item).strip()
        }

    @staticmethod
    def _coerce_config(config: Any) -> dict:
        if isinstance(config, dict):
            return dict(config)
        items = getattr(config, "items", None)
        if callable(items):
            try:
                return dict(items())
            except Exception:
                return {}
        return {}

    # ---------- 权限门控 ----------

    def _authorized(self, event: AstrMessageEvent) -> bool:
        getter = getattr(event, "get_sender_id", None)
        sender_id = str(getter() or "").strip() if callable(getter) else ""
        if sender_id and sender_id in self.owner_ids:
            return True
        role = str(getattr(event, "role", "") or "").strip().lower()
        if role in ("admin", "owner", "administrator"):
            return True
        # AstrBot 4.x 的 is_admin 可能是属性也可能是方法：方法对象恒真，须先 callable 分派
        ia = getattr(event, "is_admin", None)
        is_admin = (ia() if callable(ia) else bool(ia)) or (
            getattr(event, "role", None) == "admin"
        )
        return bool(is_admin)

    @staticmethod
    async def _stop_event_quietly(event: AstrMessageEvent) -> None:
        """阻断事件继续传播（未授权命令防刷屏）。stop_event 兼容 async 与同步两种形态。"""
        try:
            stop = getattr(event, "stop_event", None)
            if callable(stop):
                result = stop()
                if inspect.isawaitable(result):
                    await result
        except Exception:
            logger.debug("[voicemode] stop_event failed", exc_info=True)

    @staticmethod
    def _parse_subcommand(message: str) -> str:
        text = str(message or "").strip()
        for prefix in ("/", "!", "！", ".", "。"):
            if text.startswith(prefix):
                text = text[1:].lstrip()
        if text[:9].lower() == "voicemode":
            text = text[9:]
        text = text.strip()
        return text.split()[0].lower() if text else ""

    # ---------- HTTP ----------

    async def _router_request(
        self, method: str, path: str, *, body: dict | None = None
    ) -> tuple[int, Any]:
        url = f"{self.router_base_url}{path}"
        headers: dict[str, str] = {}
        if self.bridge_token:
            headers["X-Bridge-Token"] = self.bridge_token
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if aiohttp is not None:
            return await self._request_aiohttp(method, url, headers, payload)
        return await asyncio.to_thread(
            self._request_urllib, method, url, headers, payload
        )

    @staticmethod
    async def _request_aiohttp(
        method: str, url: str, headers: dict[str, str], payload: bytes | None
    ) -> tuple[int, Any]:
        timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method, url, headers=headers, data=payload
                ) as resp:
                    text = await resp.text(encoding="utf-8", errors="replace")
                    status = resp.status
        except Exception as exc:
            raise RouterUnreachableError(
                str(exc) or type(exc).__name__
            ) from exc
        return status, _parse_json(text)

    @staticmethod
    def _request_urllib(
        method: str, url: str, headers: dict[str, str], payload: bytes | None
    ) -> tuple[int, Any]:
        req = urllib.request.Request(url, data=payload, method=method, headers=headers)
        try:
            with _NO_PROXY_OPENER.open(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
                return resp.status, _parse_json(
                    resp.read().decode("utf-8", errors="replace")
                )
        except urllib.error.HTTPError as exc:
            try:
                text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                text = ""
            return exc.code, _parse_json(text)
        except Exception as exc:
            raise RouterUnreachableError(
                str(exc) or type(exc).__name__
            ) from exc

    @staticmethod
    def _extract_error(status: int, data: Any) -> str:
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                return f"HTTP {status} {err['message']}"
            if data.get("message"):
                return f"HTTP {status} {data['message']}"
        return f"HTTP {status}"

    # ---------- 业务 ----------

    async def _switch_mode(self, mode: str) -> str:
        try:
            status, data = await self._router_request(
                "POST", "/admin/mode", body={"mode": mode}
            )
        except RouterUnreachableError:
            return "router 不可达（语音仍走云端直连不受影响）"
        if status == 200 and isinstance(data, dict) and data.get("ok"):
            logger.info("[voicemode] mode switched to %s", mode)
            return f"语音模式已切换为 {mode}（{_MODE_NOTES.get(mode, '')}）"
        return f"切换失败：{self._extract_error(status, data)}，当前模式不变"

    async def _build_status_text(self) -> str:
        try:
            status, data = await self._router_request("GET", "/health")
        except RouterUnreachableError:
            return "router 不可达（语音仍走云端直连不受影响）"
        if status != 200 or not isinstance(data, dict):
            return f"查询失败：{self._extract_error(status, data)}"
        mode = str(data.get("mode") or "unknown")
        bridge_state = str(data.get("bridge_state") or "unknown")
        today = data.get("today") if isinstance(data.get("today"), dict) else {}
        busy_reason = data.get("busy_reason") or None
        last_fallback = data.get("last_fallback") or None
        lines = [
            f"当前模式：{mode}（{_MODE_NOTES.get(mode, '未知模式')}）",
            f"bridge 状态：{bridge_state}（{_BRIDGE_STATE_NOTES.get(bridge_state, '未知状态')}）",
            f"今日合成：本地 {today.get('bridge', 0)} 条 · 云端 {today.get('cloud', 0)} 条",
            f"判忙原因：{busy_reason if busy_reason else '无'}",
            f"最近回落：{last_fallback if last_fallback else '无'}",
        ]
        return "\n".join(lines)

    @filter.command("voicemode")
    async def voicemode_command(self, event: AstrMessageEvent):
        if not self._authorized(event):
            # 非授权用户：静默忽略，不回错误防刷屏；阻断事件继续传播
            await self._stop_event_quietly(event)
            return
        sub = self._parse_subcommand(event.message_str)
        if sub in ("", "status"):
            yield event.plain_result(await self._build_status_text())
            return
        if sub not in _VALID_MODES:
            yield event.plain_result("用法：/voicemode [auto|local|cloud|status]")
            return
        yield event.plain_result(await self._switch_mode(sub))
