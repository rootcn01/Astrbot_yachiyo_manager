import re
import json
import logging

class IntentRecognizer:
    """LLM 意图识别器 - 识别定时提醒意图"""

    INTENT_PROMPT = """你是月见八千代的助手，负责判断用户消息是否包含定时提醒意图。

判断规则：
- 如果用户想设置一个将来某个时间的提醒，则为提醒意图
- 关键词包括：提醒、叫醒、提醒我、提醒一下、待会、过后、一会儿、x分钟后、x分钟后等

用户消息：{message}

请以JSON格式返回分析结果：
{{"intent": "reminder", "delay_minutes": 数字, "message": "提醒内容"}}

如果不包含定时提醒意图：
{{"intent": "none"}}

只返回JSON，不要其他内容。"""

    def __init__(self, context, config: dict):
        self.context = context
        self.config = config
        self.logger = logging.getLogger(__name__)

    async def recognize(self, message: str) -> dict:
        """
        识别消息意图
        返回: {"intent": "reminder", "delay_minutes": int, "message": str} 或 {"intent": "none"}
        """
        try:
            prompt = self.INTENT_PROMPT.format(message=message)

            # 获取 provider
            provider = self.context.get_using_provider()
            if not provider:
                self.logger.warning("No LLM provider available")
                return {"intent": "none"}

            # 调用 LLM
            resp = await provider.text_chat(
                prompt,
                session_id="yachiyo_intent_recognition"
            )

            text = resp.completion_text.strip() if resp.completion_text else ""

            # 解析 JSON
            result = self._extract_json(text)

            if result:
                # 验证数据
                if result.get("intent") == "reminder":
                    delay = result.get("delay_minutes")
                    msg = result.get("message")
                    if delay and msg and isinstance(delay, (int, float)) and delay > 0:
                        return {
                            "intent": "reminder",
                            "delay_minutes": int(delay),
                            "message": msg.strip()
                        }

            return {"intent": "none"}

        except Exception as e:
            self.logger.error(f"意图识别失败: {e}")
            return {"intent": "none"}

    def _extract_json(self, text: str) -> dict:
        """从 LLM 响应中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从文本中提取 JSON 对象
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    async def cleanup(self):
        """清理会话"""
        try:
            conv_manager = getattr(self.context, "conversation_manager", None)
            if conv_manager:
                await conv_manager.close_session("yachiyo_intent_recognition")
        except Exception:
            pass
