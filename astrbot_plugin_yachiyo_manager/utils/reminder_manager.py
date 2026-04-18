import asyncio
from typing import Callable, Awaitable
import logging

class ReminderManager:
    """定时任务管理器"""

    def __init__(self):
        self.tasks: dict[str, asyncio.Task] = {}
        self.logger = logging.getLogger(__name__)

    async def create_reminder(
        self,
        user_id: str,
        platform: str,
        delay_seconds: int,
        message: str,
        alert_type: str,
        config: dict,
        send_func: Callable
    ):
        """创建定时提醒"""
        task_id = f"{user_id}_{platform}_{id(asyncio.current_task())}"

        async def reminder_task():
            try:
                await asyncio.sleep(delay_seconds)
                await send_func(user_id, platform, message, alert_type, config)
            except asyncio.CancelledError:
                self.logger.info(f"提醒任务已取消: {task_id}")
            except Exception as e:
                self.logger.error(f"提醒任务执行失败: {e}")
            finally:
                self.tasks.pop(task_id, None)

        task = asyncio.create_task(reminder_task())
        self.tasks[task_id] = task
        return task_id

    def cancel_reminder(self, task_id: str):
        """取消提醒"""
        task = self.tasks.get(task_id)
        if task:
            task.cancel()
            self.logger.info(f"已取消提醒: {task_id}")
