"""提醒功能测试"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestReminderManager:
    @pytest.mark.asyncio
    async def test_create_and_cancel(self):
        plugin = MagicMock()
        plugin.get_kv_data = AsyncMock(return_value={})
        plugin.put_kv_data = AsyncMock()
        from astrbot_plugin_yachiyo_manager.utils.reminder_manager import ReminderManager
        mgr = ReminderManager(plugin)
        tid = await mgr.create(
            user_id="u1", platform="qq", delay_seconds=3600,
            message="测试", alert_type="normal", umo="test:1:2"
        )
        assert tid
        assert await mgr.cancel(tid)
        assert not await mgr.cancel("nonexistent")

    @pytest.mark.asyncio
    async def test_list_for_user(self):
        plugin = MagicMock()
        plugin.get_kv_data = AsyncMock(return_value={
            "a": {"user_id": "u1", "message": "m1"},
            "b": {"user_id": "u2", "message": "m2"},
            "c": {"user_id": "u1", "message": "m3"},
        })
        plugin.put_kv_data = AsyncMock()
        from astrbot_plugin_yachiyo_manager.utils.reminder_manager import ReminderManager
        mgr = ReminderManager(plugin)
        result = await mgr.list_for_user("u1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_restore_all(self):
        """重启恢复：有效提醒恢复，过期提醒清理"""
        now = time.time()
        future_time = now + 7200
        past_time = now - 3600

        stored = {
            "valid_1": {
                "task_id": "valid_1", "user_id": "u1",
                "trigger_at": future_time, "message": "valid",
                "alert_type": "normal", "umo": "test:1:2"
            },
            "expired_1": {
                "task_id": "expired_1", "user_id": "u2",
                "trigger_at": past_time, "message": "expired",
                "alert_type": "normal", "umo": "test:2:3"
            },
        }

        plugin = MagicMock()
        plugin.get_kv_data = AsyncMock(return_value=stored)
        plugin.put_kv_data = AsyncMock()
        plugin._execute_reminder = AsyncMock()

        from astrbot_plugin_yachiyo_manager.utils.reminder_manager import ReminderManager
        mgr = ReminderManager(plugin)
        await mgr.restore_all()

        # 有效提醒被恢复为 asyncio task
        assert "valid_1" in mgr.tasks
        # 过期提醒不被恢复
        assert "expired_1" not in mgr.tasks

        # 验证过期提醒从 KV Store 中移除
        saved = plugin.put_kv_data.call_args[0][1]
        assert "valid_1" in saved
        assert "expired_1" not in saved
