import httpx
from typing import Optional
from astrbot.api import logger


class NapCatClient:
    def __init__(self, api_url: str, api_token: str):
        self.api_url = api_url.rstrip("/")
        self.api_token = api_token
        self.client = httpx.AsyncClient(timeout=30.0)

    def _get_headers(self) -> dict:
        """获取请求头"""
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def send_group_ai_record(self, character: str, group_id: int, text: str) -> bool:
        """发送群组 AI 语音"""
        try:
            response = await self.client.post(
                f"{self.api_url}/send_group_ai_record",
                json={"character": character, "group_id": group_id, "text": text},
                headers=self._get_headers()
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"NapCat API 调用失败: {e}")
            return False

    async def send_private_msg(self, user_id: int, message: str) -> bool:
        """发送私聊消息（fallback 用）"""
        try:
            response = await self.client.post(
                f"{self.api_url}/send_private_msg",
                json={"user_id": user_id, "message": message},
                headers=self._get_headers()
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"NapCat 私聊发送失败: {e}")
            return False

    async def close(self):
        await self.client.aclose()
