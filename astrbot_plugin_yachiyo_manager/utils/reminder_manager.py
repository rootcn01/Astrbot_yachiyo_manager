"""提醒管理器 — asyncio 调度 + KV Store 持久化 + 重启恢复"""
import asyncio
import time
from astrbot.api import logger


class ReminderManager:
    def __init__(self, plugin):
        self.plugin = plugin
        self.tasks: dict[str, asyncio.Task] = {}
        self._counter = 0

    async def create(self, *, user_id: str, platform: str, delay_seconds: int,
                     message: str, alert_type: str, umo: str,
                     group_id: int = None) -> str:
        """创建提醒。返回 task_id。"""
        self._counter += 1
        trigger_at = time.time() + delay_seconds
        task_id = f"{user_id}_{int(trigger_at)}_{self._counter}"

        payload = {
            "task_id": task_id,
            "user_id": user_id, "platform": platform,
            "message": message, "alert_type": alert_type,
            "umo": umo, "group_id": group_id,
            "trigger_at": trigger_at
        }

        await self._save_pending(task_id, payload)

        task = asyncio.create_task(self._run(task_id, delay_seconds))
        self.tasks[task_id] = task
        logger.info(f"提醒已创建: {task_id}, delay={delay_seconds}s")
        return task_id

    async def cancel(self, task_id: str) -> bool:
        """取消提醒"""
        task = self.tasks.pop(task_id, None)
        if task:
            task.cancel()
        pending = await self._load_pending()
        removed = pending.pop(task_id, None) is not None
        await self._save_all_pending(pending)
        if removed:
            logger.info(f"提醒已取消: {task_id}")
        return removed

    async def list_for_user(self, user_id: str) -> list[dict]:
        """列出用户的所有待执行提醒"""
        pending = await self._load_pending()
        return [v for v in pending.values() if v["user_id"] == user_id]

    async def restore_all(self):
        """重启后恢复所有未过期的提醒"""
        pending = await self._load_pending()
        now = time.time()
        restored = 0
        for task_id, data in list(pending.items()):
            remaining = data["trigger_at"] - now
            if remaining > 0:
                task = asyncio.create_task(self._run(task_id, remaining))
                self.tasks[task_id] = task
                restored += 1
            else:
                del pending[task_id]
        await self._save_all_pending(pending)
        logger.info(f"恢复了 {restored} 个提醒 ({len(pending)} 个过期已清理)")

    async def _run(self, task_id: str, delay: float):
        """执行提醒任务"""
        await asyncio.sleep(delay)
        pending = await self._load_pending()
        data = pending.pop(task_id, None)
        if data:
            await self._save_all_pending(pending)
            try:
                await self.plugin._execute_reminder(data)
            except Exception as e:
                logger.error(f"提醒执行失败 {task_id}: {e}")
        self.tasks.pop(task_id, None)

    async def _load_pending(self) -> dict:
        return await self.plugin.get_kv_data("pending_reminders", default={})

    async def _save_pending(self, task_id: str, data: dict):
        pending = await self._load_pending()
        pending[task_id] = data
        await self._save_all_pending(pending)

    async def _save_all_pending(self, data: dict):
        await self.plugin.put_kv_data("pending_reminders", data)
