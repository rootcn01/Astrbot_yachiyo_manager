from typing import Optional


class PlatformAdapter:
    """平台适配器：统一 QQ 和微信的接口差异"""

    def __init__(self, context):
        self.context = context

    def detect_platform(self, event) -> str:
        """检测消息平台"""
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
