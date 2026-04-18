from typing import Optional

class PlatformAdapter:
    """平台适配器：统一 QQ 和微信的接口差异"""

    def __init__(self, context):
        self.context = context

    def detect_platform(self, event) -> str:
        """检测消息平台"""
        # 根据 event 的字段判断平台
        # QQ: event.message_str 包含 CQ 码等特征
        # 微信: 可能有 wechat 字段
        session_id = getattr(event, "session_id", "") or ""
        if "wechat" in session_id.lower():
            return "wechat"
        return "qq"

    def get_user_id(self, event) -> str:
        """获取用户 ID"""
        sender = getattr(event, "sender_info", {}) or {}
        return str(sender.get("user_id", ""))

    def get_group_id(self, event) -> Optional[int]:
        """获取群 ID（如果是群消息）"""
        return getattr(event, "group_id", None)

    def is_group_message(self, event) -> bool:
        """是否群消息"""
        return getattr(event, "group_id", None) is not None

    def get_unified_msg_origin(self, event) -> str:
        """获取统一消息源 ID"""
        return getattr(event, "session_id", "")

    async def send_message(self, umo: str, message: str):
        """发送消息"""
        from astrbot.api.event import MessageChain
        chain = MessageChain().message(message)
        await self.context.send_message(umo, chain)
