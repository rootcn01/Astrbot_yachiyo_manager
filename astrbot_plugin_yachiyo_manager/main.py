import asyncio
import json
from pathlib import Path
from typing import Optional

from astrbot.api.star import Star, Context
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger

from .utils.reminder_manager import ReminderManager
from .utils.platform_adapter import PlatformAdapter
from .utils.personality import PersonalityEngine
from .utils.napcat_client import NapCatClient


class YachiyoManager(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}

        # 数据目录 - 使用相对路径
        self.data_dir = Path("data/plugin_data/yachiyo_manager")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 初始化各模块
        self.reminder_manager = ReminderManager()
        self.platform_adapter = PlatformAdapter(context)
        self.personality_engine = PersonalityEngine(context, self.config)
        self.napcat_client = NapCatClient(
            api_url=self.config.get("napcat_api_url", "http://localhost:3000"),
            api_token=self.config.get("napcat_api_token", "")
        )

        # 加载数据
        self.whitelist = self._load_json("whitelist.json", {"qq_whitelist": [], "wechat_whitelist": []})
        self.user_configs = self._load_json("user_configs.json", {})

    def _load_json(self, filename: str, default: dict) -> dict:
        """加载 JSON 数据文件"""
        path = self.data_dir / filename
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return default
        return default

    def _save_json(self, filename: str, data: dict):
        """保存 JSON 数据文件"""
        path = self.data_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ==================== 命令 Handlers ====================

    @filter.command("yachiyo_fushi_reminder")
    async def handle_fushi_reminder(self, event: AstrMessageEvent, delay_minutes: int = None, message: str = None, alert_type: str = None):
        """设定 FUSHI 闹钟"""
        platform = self.platform_adapter.detect_platform(event)
        user_id = self.platform_adapter.get_user_id(event)

        if not self._check_whitelist(platform, user_id):
            yield event.plain_result("该功能仅对白名单用户开放哦~")
            return

        if delay_minutes is None or not message:
            yield event.plain_result("参数不完整哦~ 请提供 delay_minutes 和 message\n例如：yachiyo_fushi_reminder 5 该喝水了 normal")
            return

        if alert_type is None:
            alert_type = self.config.get("default_alert_type", "normal")

        yield event.plain_result(f"收到啦~ FUSHI 会在 {delay_minutes} 分钟后叫你的哦♪")

        asyncio.create_task(
            self.reminder_manager.create_reminder(
                user_id=user_id,
                platform=platform,
                delay_seconds=delay_minutes * 60,
                message=message,
                alert_type=alert_type,
                config=self.config,
                send_func=self._send_reminder,
                event=event
            )
        )

    @filter.command("yachiyo_voice_mode")
    async def handle_voice_mode(self, event: AstrMessageEvent, enable: bool = None):
        """切换语音模式"""
        user_id = self.platform_adapter.get_user_id(event)
        if user_id not in self.user_configs:
            self.user_configs[user_id] = {
                "voice_mode": False,
                "voice_character": self.config.get("voice_character", "yachiyo")
            }

        if enable is None:
            current = self.user_configs[user_id].get("voice_mode", False)
            yield event.plain_result(f"当前语音模式：{'开启' if current else '关闭'}\n使用 yachiyo_voice_mode true/false 来切换")
            return

        self.user_configs[user_id]["voice_mode"] = enable
        self._save_json("user_configs.json", self.user_configs)
        yield event.plain_result("明白啦，八千代现在切换模式咯~" if enable else "好的，语音模式已关闭。")

    @filter.command("yachiyo_whitelist_add")
    async def handle_whitelist_add(self, event: AstrMessageEvent, qq_id: str = None):
        """添加白名单"""
        if not qq_id:
            yield event.plain_result("请提供要添加的 QQ ID\n例如：yachiyo_whitelist_add 123456")
            return

        qq_id_str = str(qq_id)
        if qq_id_str not in self.whitelist["qq_whitelist"]:
            self.whitelist["qq_whitelist"].append(qq_id_str)
            self._save_json("whitelist.json", self.whitelist)
            yield event.plain_result(f"已将 {qq_id_str} 加入白名单♪")
        else:
            yield event.plain_result("该账号已在白名单中哦~")

    @filter.command("yachiyo_whitelist_remove")
    async def handle_whitelist_remove(self, event: AstrMessageEvent, qq_id: str = None):
        """移除白名单"""
        if not qq_id:
            yield event.plain_result("请提供要移除的 QQ ID\n例如：yachiyo_whitelist_remove 123456")
            return

        qq_id_str = str(qq_id)
        if qq_id_str in self.whitelist["qq_whitelist"]:
            self.whitelist["qq_whitelist"].remove(qq_id_str)
            self._save_json("whitelist.json", self.whitelist)
            yield event.plain_result(f"已将 {qq_id_str} 从白名单移除")
        else:
            yield event.plain_result("该账号不在白名单中哦~")

    @filter.command("yachiyo_whitelist_status")
    async def handle_whitelist_status(self, event: AstrMessageEvent):
        """查看白名单状态"""
        qq_list = self.whitelist.get("qq_whitelist", [])
        display_list = [str(qq) for qq in qq_list]
        yield event.plain_result(f"QQ 白名单共有 {len(display_list)} 人：\n{', '.join(display_list) if display_list else '（空）'}")

    # ==================== 内部方法 ====================

    def _check_whitelist(self, platform: str, user_id: str) -> bool:
        """检查白名单"""
        if not user_id:
            return False
        if platform == "qq":
            if self.config.get("qq_whitelist_enabled", True):
                return user_id in [str(qq) for qq in self.whitelist.get("qq_whitelist", [])]
            return True
        elif platform == "wechat":
            if self.config.get("wechat_whitelist_enabled", False):
                return user_id in [str(qq) for qq in self.whitelist.get("wechat_whitelist", [])]
            return True
        return True

    async def _send_reminder(self, user_id: str, platform: str, message: str, alert_type: str, config: dict, event: AstrMessageEvent):
        """发送提醒"""
        umo = self.platform_adapter.get_unified_msg_origin(event)

        if alert_type == "normal":
            template = config.get("normal_message_template", "【FUSHI 闹钟】叮铃铃~ 神明大人，{message}")
            formatted_message = template.format(message=message)
            await self.platform_adapter.send_message(umo, formatted_message)

        elif alert_type == "urgent":
            if platform == "qq" and self.platform_adapter.is_group_message(event):
                personalized_text = await self.personality_engine.personalize(message)
                group_id = self.platform_adapter.get_group_id(event)
                tts_success = await self.napcat_client.send_group_ai_record(
                    character=config.get("voice_character", "yachiyo"),
                    group_id=group_id,
                    text=personalized_text
                )
                if not tts_success:
                    logger.warning("TTS 发送失败，fallback 到文字")
                    await self._send_urgent_text_bomb(umo, message, config)
                else:
                    await self._send_urgent_text_bomb(umo, message, config)
            else:
                await self._send_urgent_text_bomb(umo, message, config)

    async def _send_urgent_text_bomb(self, umo: str, message: str, config: dict):
        """发送 urgent 文字轰炸"""
        template = config.get("urgent_enhancement_template", "神明大人！{message}！快醒醒！")
        messages = [
            template.format(message=message),
            template.format(message=message) + "！",
            template.format(message=message) + "！！"
        ]
        for msg in messages:
            await self.platform_adapter.send_message(umo, msg)
            await asyncio.sleep(0.5)
