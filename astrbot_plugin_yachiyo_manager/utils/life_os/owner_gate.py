"""身份校验 — 确保 Life OS 工具只对 owner 生效"""


def is_owner(platform_adapter, event) -> bool:
    """微信私聊消息的发送者就是 owner。

    微信是个人账号，私聊消息只可能来自 owner。
    QQ 等其他平台的用户即使看到工具也无法使用。
    """
    platform = platform_adapter.detect_platform(event)
    if platform != "wechat":
        return False
    # 私聊消息（非群聊）
    return not platform_adapter.is_group_message(event)
