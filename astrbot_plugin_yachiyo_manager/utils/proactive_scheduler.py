"""主动 push 周期调度 - cron 模式，复用 KV Store 持久化 + 重启重算"""
import asyncio
from datetime import datetime, timedelta
from astrbot.api import logger

# chronotype -> push 时机映射（漂移改 chrono 字段，时机自动跟）
CHRONO_PUSH_TIMES = {
    "night_heavy": {"morning": "13:00", "evening": "23:00"},  # 当前：3-4睡中午醒
    "normal":      {"morning": "08:00", "evening": "22:00"},  # 目标：8醒12睡
}


class ProactiveScheduler:
    """周期 cron 调度：早晚 push。

    与 ReminderManager（延迟一次性）不同，本类做周期 cron。
    复用 KV Store 持久化模式（proactive_jobs），重启时 start() 按 push_time 重算下次。
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self.tasks: dict[str, asyncio.Task] = {}

    async def start(self):
        """initialize() 时调用。

        F4: 检查总开关 proactive_push_enabled。
        F7: 按 push_time 重算下次发生（_seconds_until 算到下个时点），不 sleep 存量 remaining。
        """
        self.cancel_all()  # 防热重载重复调度
        if not self.plugin.config.get("proactive_push_enabled", True):
            logger.info("主动 push 已关闭（proactive_push_enabled=false）")
            return
        chrono = self.plugin.config.get("chronotype", "night_heavy")
        times = CHRONO_PUSH_TIMES.get(chrono, CHRONO_PUSH_TIMES["night_heavy"])
        await self.plugin.put_kv_data("proactive_jobs", times)  # 记录当前配置
        for name, push_time in times.items():
            self._schedule_next(name, push_time)
        logger.info(f"主动 push 已启动（chronotype={chrono}）：{times}")

    def _schedule_next(self, name: str, push_time: str):
        """F9: 用 asyncio.create_task（非 _fire_sync 的 get_event_loop）。"""
        task = asyncio.create_task(self._run_job(name, push_time))
        self.tasks[name] = task

    async def _run_job(self, name: str, push_time: str):
        """F5: 计算到下次 push_time 的秒数（今日过滚明天），sleep，触发，周期重调度。"""
        delay = self._seconds_until(push_time)
        logger.info(f"主动 push [{name}] 将在 {delay/3600:.1f}h 后触发（{push_time}）")
        await asyncio.sleep(delay)
        try:
            await self.plugin._execute_proactive_push(name)
        except Exception as e:
            logger.error(f"主动 push 失败 [{name}]: {e}")
        # 周期重新调度
        self._schedule_next(name, push_time)

    def _seconds_until(self, push_time: str) -> float:
        """F5: 到下次 push_time 的秒数。今日时机已过则滚到明天（防 0/负延迟紧循环）。"""
        now = datetime.now()
        hh, mm = push_time.split(":")
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    def cancel_all(self):
        """terminate() 或热重载时取消所有任务。"""
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()
