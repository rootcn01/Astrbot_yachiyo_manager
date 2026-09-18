"""Google Tasks + Calendar 集成 - httpx 直连 REST，OAuth token 文件 + 自动刷新

依赖：httpx（已在 requirements.txt）
token：data/plugin_data/yachiyo_manager/token.json
  - 本地跑 OAuth flow（InstalledAppFlow.run_local_server）生成后复制到服务器此路径
  - 含 refresh_token + client_id + client_secret + expiry，可自动刷新 access_token
  - .gitignore 必须覆盖此文件（含 refresh_token 等同账户密码）

方案：pipeline/2026-07-17-google-tasks-calendar-sync-plan.md §四 §五 §六
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from astrbot.api import logger

# OAuth token 文件路径（AstrBot 插件数据目录规范）
TOKEN_FILE = Path("data/plugin_data/yachiyo_manager/token.json")

# Google API endpoints
GTASKS_BASE = "https://tasks.googleapis.com/tasks/v1"
GCAL_BASE = "https://www.googleapis.com/calendar/v3"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleIntegration:
    """Google Tasks + Calendar REST 客户端。

    OAuth token 从文件加载，access_token 过期时用 refresh_token 自动刷新。
    所有方法 async，失败返回空/None/False 并 logger.warning（不抛异常，由调用方降级）。
    """

    def __init__(self, config: dict):
        self.config = config
        self.enabled = bool(config.get("google_tasks_enabled") or
                            config.get("google_calendar_enabled"))
        self._creds: Optional[dict] = None
        # 所有 Google 请求走代理（tasks/calendar/oauth2 国内均不可达，不只 oauth2）
        self._proxy = config.get("google_oauth_proxy", "")
        self._client = self._make_client()

    def _make_client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        kwargs = {"timeout": timeout}
        if self._proxy:
            kwargs["proxy"] = self._proxy
        return httpx.AsyncClient(**kwargs)

    async def initialize(self):
        """插件 initialize() 时调用。加载 token 文件。"""
        if not self.enabled:
            logger.info("Google 集成未启用（google_tasks_enabled/google_calendar_enabled 均未开）")
            return
        if not TOKEN_FILE.exists():
            logger.warning(
                f"Google token 未找到: {TOKEN_FILE}。"
                "需本地跑 OAuth flow 生成 token.json 后复制到服务器此路径"
            )
            self.enabled = False
            return
        try:
            self._creds = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            logger.info("Google 集成已加载 token")
        except Exception as e:
            logger.warning(f"Google token 加载失败: {e}")
            self.enabled = False

    # ── OAuth ──

    def _expiry_timestamp(self) -> float:
        """解析 token.json 的 expiry 字段为 timestamp（容错 ISO 字符串或数字）。"""
        expiry = self._creds.get("expiry") if self._creds else None
        if not expiry:
            return 0
        if isinstance(expiry, (int, float)):
            return float(expiry)
        try:
            dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return 0

    async def _ensure_token(self) -> bool:
        """确保 access_token 有效，过期则尝试刷新。
        刷新失败不阻塞——仍返回 True 尝试用现有 token（API 调用如 401 由 llm_tool 降级处理）。"""
        if not self._creds or not self._creds.get("access_token"):
            return False
        if time.time() < self._expiry_timestamp() - 60:
            return True
        # token 理论上过期了，尝试刷新但失败不阻塞
        refreshed = await self._refresh()
        return True if refreshed else bool(self._creds.get("access_token"))

    async def _ensure_client(self):
        """确保 httpx client 可用（terminate 后重建）。"""
        try:
            await self._client.get('https://www.googleapis.com/discovery/v1/apis', params={'fake': '1'})
        except Exception:
            pass  # 不关心结果，只检测连接
        if self._client.is_closed:
            self._client = self._make_client()
            logger.info('Google 集成 httpx client 已重建')

    async def _refresh(self) -> bool:
        """用 refresh_token 刷新 access_token，成功后回写 token.json。
        超时 10s（服务器在国内，oauth2.googleapis.com 大概率不通，不阻塞调用）。"""
        try:
            async with self._make_client(timeout=10.0) as _refresh_client:
                resp = await _refresh_client.post(OAUTH_TOKEN_URL, data={
                    "client_id": self._creds["client_id"],
                    "client_secret": self._creds["client_secret"],
                    "refresh_token": self._creds["refresh_token"],
                    "grant_type": "refresh_token",
                })
                data = resp.json()
                if "access_token" not in data:
                    logger.warning(f"Google token 刷新失败: {data.get('error_description', data)}")
                    return False
                self._creds["access_token"] = data["access_token"]
                expires_in = data.get("expires_in", 3600)
                self._creds["expiry"] = (datetime.now(timezone.utc) + __import__('datetime').timedelta(seconds=expires_in)).isoformat()
                try:
                    TOKEN_FILE.write_text(json.dumps(self._creds, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    logger.warning(f"token 回写失败（不影响本次调用）: {e}")
                return True
        except Exception as e:
            # 网络不通时 e 可能为空字符串，补充类型信息
            err_msg = str(e) or type(e).__name__
            logger.warning(f"Google token 刷新异常 [{err_msg}]")
            return False

    async def _headers(self) -> Optional[dict]:
        await self._ensure_client()
        if not await self._ensure_token():
            return None
        return {"Authorization": f"Bearer {self._creds['access_token']}"}

    # ── Tasks ──

    async def list_tasklists(self) -> list[dict]:
        """列出所有 task list（多 list 场景查 list_id 用）。"""
        headers = await self._headers()
        if not headers:
            return []
        try:
            resp = await self._client.get(f"{GTASKS_BASE}/users/@me/lists", headers=headers)
            if resp.status_code != 200:
                logger.warning(f"tasklists list 失败: {resp.status_code}")
                return []
            return resp.json().get("items", [])
        except Exception as e:
            logger.warning(f"tasklists list 异常: {e}")
            return []

    async def list_tasks(self, list_id: str = "@default", **params) -> list[dict]:
        """列出某 list 的 tasks。

        params: showCompleted / showDeleted / completedMin / completedMax /
                updatedMin / maxResults / pageToken
        """
        headers = await self._headers()
        if not headers:
            return []
        try:
            resp = await self._client.get(
                f"{GTASKS_BASE}/lists/{list_id}/tasks",
                params=params, headers=headers,
            )
            if resp.status_code != 200:
                logger.warning(f"tasks list 失败: {resp.status_code}")
                return []
            return resp.json().get("items", [])
        except Exception as e:
            logger.warning(f"tasks list 异常: {e}")
            return []

    async def insert_task(self, title: str, list_id: str = "@default",
                          due: Optional[str] = None, notes: Optional[str] = None) -> Optional[dict]:
        """创建 task。due 为 RFC3339 字符串（如 '2026-07-18T00:00:00Z'，Tasks 仅记录日期）。"""
        headers = await self._headers()
        if not headers:
            return None
        body = {"title": title}
        if due:
            body["due"] = due
        if notes:
            body["notes"] = notes
        try:
            resp = await self._client.post(
                f"{GTASKS_BASE}/lists/{list_id}/tasks",
                json=body, headers=headers,
            )
            if resp.status_code != 200:
                logger.warning(f"tasks insert 失败: {resp.status_code} {resp.text}")
                return None
            return resp.json()
        except Exception as e:
            logger.warning(f"tasks insert 异常: {e}")
            return None

    async def complete_task(self, task_id: str, list_id: str = "@default") -> bool:
        """标记 task 完成（PATCH status=completed）。"""
        headers = await self._headers()
        if not headers:
            return False
        try:
            resp = await self._client.patch(
                f"{GTASKS_BASE}/lists/{list_id}/tasks/{task_id}",
                json={"status": "completed"}, headers=headers,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"tasks complete 异常: {e}")
            return False

    # ── Calendar ──

    async def list_events(self, calendar_id: str = "primary", **params) -> list[dict]:
        """列出日历事件。

        params: timeMin / timeMax / syncToken / showDeleted / singleEvents /
                orderBy / maxResults / pageToken
        返回事件列表；syncToken 过期(410) 返回空列表（调用方应清空 gcal_sync_token 全量重拉）。
        """
        headers = await self._headers()
        if not headers:
            return []
        try:
            resp = await self._client.get(
                f"{GCAL_BASE}/calendars/{calendar_id}/events",
                params=params, headers=headers,
            )
            if resp.status_code == 410:
                logger.info("Calendar syncToken 过期(410)，调用方应清空 gcal_sync_token 全量重拉")
                return []
            if resp.status_code != 200:
                logger.warning(f"events list 失败: {resp.status_code}")
                return []
            return resp.json().get("items", [])
        except Exception as e:
            logger.warning(f"events list 异常: {e}")
            return []

    async def close(self):
        await self._client.aclose()
