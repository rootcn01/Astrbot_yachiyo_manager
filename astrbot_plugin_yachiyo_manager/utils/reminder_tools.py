"""八千代提醒工具 — @llm_tool 注册"""
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult


@filter.llm_tool(name="set_fushi_reminder")
async def set_fushi_reminder(self, event: AstrMessageEvent,
                              delay_minutes: int, message: str,
                              alert_type: str = "normal") -> MessageEventResult:
    """设置 FUSHI 定时提醒。到时间八千代会叫醒神明大人。
    Args:
        delay_minutes(number): 多少分钟后提醒(1-1440)
        message(string): 提醒内容
        alert_type(string): normal=温柔提醒, urgent=紧急轰炸+TTS语音
    """
    result = await self._create_reminder_internal(
        event, delay_minutes, message, alert_type
    )
    if not result["ok"]:
        yield event.plain_result(result["error"])
        return

    dm = result["delay_minutes"]
    msg = result["message"]
    if result["alert_type"] == "urgent":
        yield event.plain_result(
            f"知道啦！⏰ {dm}分钟后八千代会用紧急模式全力叫醒神明大人！"
        )
    else:
        yield event.plain_result(
            f"收到啦~ {dm}分钟后八千代会提醒神明大人「{msg}」的哦♪"
        )


@filter.llm_tool(name="cancel_fushi_reminder")
async def cancel_fushi_reminder(self, event: AstrMessageEvent,
                                 task_index: int = None) -> MessageEventResult:
    """取消 FUSHI 提醒。不指定序号时列出所有提醒，指定序号则取消对应提醒。
    Args:
        task_index(number): 要取消的提醒序号(从1开始)，不填则列出全部
    """
    user_id = self._get_user_id(event)
    reminders = await self.reminder_manager.list_for_user(user_id)

    if not reminders:
        yield event.plain_result("当前没有待执行的提醒哦~")
        return

    if task_index is None:
        lines = ["当前待执行的提醒："]
        for i, r in enumerate(reminders, 1):
            icon = "🔔" if r["alert_type"] == "normal" else "🚨"
            lines.append(f"  {i}. {icon} {r['message']}")
        lines.append("告诉我要取消第几个就好~")
        yield event.plain_result("\n".join(lines))
        return

    if not (1 <= task_index <= len(reminders)):
        yield event.plain_result(f"序号需在 1-{len(reminders)} 之间哦~")
        return

    r = reminders[task_index - 1]
    await self.reminder_manager.cancel(r["task_id"])
    yield event.plain_result(f"已取消提醒「{r['message']}」~")


@filter.llm_tool(name="list_fushi_reminders")
async def list_fushi_reminders(self, event: AstrMessageEvent) -> MessageEventResult:
    """查看当前所有 FUSHI 提醒"""
    user_id = self._get_user_id(event)
    reminders = await self.reminder_manager.list_for_user(user_id)
    if not reminders:
        yield event.plain_result("当前没有待执行的提醒~")
        return
    lines = [f"共 {len(reminders)} 个待执行提醒♪"]
    for r in reminders:
        icon = "🔔" if r["alert_type"] == "normal" else "🚨"
        lines.append(f"  {icon} {r['message']}")
    yield event.plain_result("\n".join(lines))
