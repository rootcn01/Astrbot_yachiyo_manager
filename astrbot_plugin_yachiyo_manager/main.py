"""月见八千代管理插件 — FUSHI 提醒 + AI 友人 + Life OS"""
import asyncio
import re
import time
from datetime import datetime
from pathlib import Path

from astrbot.api.star import Star, Context
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api import logger
from astrbot.api.event.filter import on_llm_request
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.agent.tool import ToolSet
from astrbot.api import llm_tool

from .utils.persona_builder import PersonaBuilder
from .utils.reminder_manager import ReminderManager
from .utils.platform_adapter import PlatformAdapter
from .utils.napcat_client import NapCatClient
from .utils.life_os import LifeOSContext
from .utils.life_os.owner_gate import is_owner
from .utils.life_os.file_ops import (
    ensure_repo_path, read_file, append_to_inbox, append_expense, sync_git,
)
from .utils.life_os.expense import (
    parse_expense_table, compute_today_totals, compute_monthly_totals,
    parse_debt_from_claude_md, MONTHLY_BUDGET, DAILY_DINING_BUDGET,
)
from .utils.life_os.checkin import format_checkin_line
from .utils.life_os.dashboard import (
    extract_today_plan, extract_weekly_snapshot, extract_global_status,
    parse_weekly_log_table, compute_weekly_stats, extract_retest_date,
)


class YachiyoManager(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}

        self.platform = PlatformAdapter(context)
        self.napcat = NapCatClient(
            api_url=self.config.get("napcat_api_url", "http://localhost:3000"),
            api_token=self.config.get("napcat_api_token", "")
        )
        self.reminder_manager = ReminderManager(self)

        plugin_dir = Path(__file__).parent
        self.persona_builder = PersonaBuilder(
            persona_enabled=self.config.get("persona_enabled", True),
            plugin_dir=plugin_dir
        )
        self.life_os = LifeOSContext(self.config)

        self._user_cache: dict[str, dict] = {}
        self._whitelist: dict = None

        logger.info("八千代插件已初始化（含 Life OS v2.2 全局工具）")

    # ── 生命周期 ──

    async def initialize(self):
        self._whitelist = await self.get_kv_data("whitelist",
                                                  default={"qq": [], "wechat": []})
        await self._migrate_old_data()
        await self.reminder_manager.restore_all()
        logger.info("八千代插件激活完成")

    async def terminate(self):
        """插件卸载时取消所有待执行的提醒任务"""
        for task in list(self.reminder_manager.tasks.values()):
            task.cancel()
        self.reminder_manager.tasks.clear()
        logger.info("八千代插件已终止，所有提醒任务已取消")
        await self.napcat.close()

    async def _migrate_old_data(self):
        old_dir = Path("data/plugin_data/yachiyo_manager")
        migrated = False
        for fname, kv_key in [("whitelist.json", "whitelist"),
                               ("user_configs.json", "user_configs")]:
            path = old_dir / fname
            if not path.exists():
                continue
            try:
                import json
                data = json.loads(path.read_text(encoding="utf-8"))
                existing = await self.get_kv_data(kv_key, default=None)
                if existing is None:
                    if fname == "whitelist.json":
                        data = {"qq": data.get("qq_whitelist", []),
                                "wechat": data.get("wechat_whitelist", [])}
                    await self.put_kv_data(kv_key, data)
                    migrated = True
                    logger.info(f"已迁移 {fname} → KV Store")
            except Exception as e:
                logger.warning(f"迁移 {fname} 失败: {e}")
        if migrated:
            logger.info("旧数据迁移完成")

    # ── 身份校验 ──

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        """微信私聊消息的发送者就是 owner。群聊和其他平台不可用。"""
        return is_owner(self.platform, event)

    # ── 提醒创建（共享逻辑）──

    async def _create_reminder_internal(self, event: AstrMessageEvent,
                                         delay_minutes: int, message: str,
                                         alert_type: str) -> dict:
        """创建提醒的核心逻辑。验证 + 创建 + 更新状态。
        返回 {"ok": bool, "error": str, ...}
        """
        if not (1 <= delay_minutes <= 1440):
            return {"ok": False, "error": "提醒时间需在 1-1440 分钟之间哦~"}

        alert_type = alert_type or self.config.get("default_alert_type", "normal")
        if alert_type not in ("normal", "urgent"):
            alert_type = "normal"

        user_id = self._get_user_id(event)
        platform = self._detect_platform(event)
        umo = event.unified_msg_origin
        group_id = (self.platform.get_group_id(event)
                    if self.platform.is_group_message(event) else None)

        task_id = await self.reminder_manager.create(
            user_id=user_id, platform=platform,
            delay_seconds=delay_minutes * 60,
            message=message, alert_type=alert_type,
            umo=umo, group_id=group_id
        )
        await self._update_user_interaction(user_id)

        return {"ok": True, "task_id": task_id, "user_id": user_id,
                "delay_minutes": delay_minutes, "message": message,
                "alert_type": alert_type}

    # ── Fire-and-forget git 同步 ──

    def _fire_sync(self, repo_path: str):
        """异步 git 同步，不阻塞消息回复。"""
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(sync_git(repo_path))
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    #  Life OS 全局工具（@llm_tool — 默认聊天流自动可用）
    # ═══════════════════════════════════════════════════════════

    @llm_tool(name="record_expense")
    async def record_expense(self, event: AstrMessageEvent,
                             amount: float, description: str,
                             category: str = "其他") -> str:
        """记录一笔支出。当用户提到花了钱、买了东西、付款、消费、吃饭、买、付了时调用。
        如果用户连续说了多笔支出（例如"午餐35，咖啡15"），对每一笔分别调用本工具。

        Args:
            amount(number): 金额（只填数字，不含¥符号。模糊金额取中间值，例如"三四十"→35）
            description(string): 买了什么，简短描述
            category(string): 分类：餐饮/交通/购物/娱乐/健康/副业成本/其他
        """
        if not self._is_owner(event):
            return "OWNER_ONLY"

        try:
            repo_path = ensure_repo_path(self.config)
        except FileNotFoundError:
            return "TOOL_ERROR|reason=仓库路径不存在"

        append_expense(repo_path, amount, category, description)
        expense_md = read_file(repo_path, "finance/expense-log.md")
        entries = parse_expense_table(expense_md)
        today = compute_today_totals(entries)

        self._fire_sync(repo_path)

        return (
            f"EXPENSE_OK|amount={amount}|desc={description}|category={category}|"
            f"today_dining={today['today_dining']:.0f}|daily_budget={DAILY_DINING_BUDGET}|"
            f"over_budget={'true' if today['over_budget'] else 'false'}|"
            f"budget_pct={today['budget_pct']}"
        )

    @llm_tool(name="record_note")
    async def record_note(self, event: AstrMessageEvent,
                          content: str, note_type: str = "auto") -> str:
        """记录待办事项或灵感创意。当用户说要做/记得/别忘了/提醒我/待办（todo），
        或说出点子/构思/设定/世界观/故事想法/创意（idea）时调用。
        note_type 由 LLM 根据内容推断，不确定时填 auto，系统会根据关键词自动判断。

        Args:
            content(string): 笔记内容，保留用户的完整表达
            note_type(string): todo 或 idea 或 auto。auto表示由系统根据关键词判断
        """
        if not self._is_owner(event):
            return "OWNER_ONLY"

        try:
            repo_path = ensure_repo_path(self.config)
        except FileNotFoundError:
            return "TOOL_ERROR|reason=仓库路径不存在"

        # auto 推断类型
        if note_type == "auto":
            idea_keywords = ["设定", "世界观", "角色", "故事", "创意", "灵感",
                           "设计", "构思", "点子", "想法", "施法", "魔法",
                           "精灵", "种族", "能力", "剧情", "世界观"]
            todo_keywords = ["记得", "别忘了", "要做", "提醒我", "回电话",
                           "交", "买", "去", "约了", "开会", "打卡"]
            content_lower = content.lower()
            if any(kw in content for kw in idea_keywords):
                note_type = "idea"
            elif any(kw in content for kw in todo_keywords):
                note_type = "todo"
            else:
                note_type = "todo"  # 默认当待办

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"{note_type} {content}  # {ts}"
        append_to_inbox(repo_path, line)

        self._fire_sync(repo_path)

        return f"NOTE_OK|type={note_type}|content_preview={content[:100]}|date={datetime.now().strftime('%Y-%m-%d')}"

    @llm_tool(name="record_food")
    async def record_food(self, event: AstrMessageEvent,
                          food: str, time_hint: str = "") -> str:
        """记录吃了什么。当用户提到吃了东西、吃饭、点了外卖、喝了奶茶、吃了零食时调用。
        自动根据当前时间推断餐型（午餐/晚餐/加餐）。

        Args:
            food(string): 吃了什么，简短描述即可。例如"黄焖鸡米饭""牛肉面""一杯奶茶""一个苹果"
            time_hint(string): 用户显式提到的时间，例如"刚才""半小时前"。不填则用当前时间自动推断。
        """
        if not self._is_owner(event):
            return "OWNER_ONLY"

        try:
            repo_path = ensure_repo_path(self.config)
        except FileNotFoundError:
            return "TOOL_ERROR|reason=仓库路径不存在"

        now = datetime.now()
        h = now.hour

        # 时间推断：餐型
        if 11 <= h < 14:
            meal = "午餐"
        elif 17 <= h < 20:
            meal = "晚餐"
        else:
            meal = "加餐"

        ts = now.strftime("%Y-%m-%d %H:%M")
        line = f"food {food}  # {meal}  # {ts}"
        append_to_inbox(repo_path, line)

        self._fire_sync(repo_path)

        return f"FOOD_OK|food={food}|meal={meal}|time={ts}"

    @llm_tool(name="record_checkin")
    async def record_checkin(self, event: AstrMessageEvent,
                             energy: int, mood: int, anxiety: int,
                             creative: str = "❌", detachment: str = "❌",
                             l1: str = "❌", overtime: str = "❌",
                             note: str = "") -> str:
        """记录每日状态汇报。当用户提到精力/情绪/焦虑/今天状态/汇报/今天怎么样时调用。
        如果用户没明确说某个数值，根据语气推断。'还行'=5，'累爆了'=2-3，'还不错'=6-7，
        '挺高的'=7-8。不确定时往中间靠（5）。完全无法推断的字段填-1表示缺失。
        如果用户给出范围（如"精力最多3"），取较低值。

        Args:
            energy(number): 精力 1-10（-1表示缺失）
            mood(number): 情绪 1-10（-1表示缺失）
            anxiety(number): 焦虑 1-10（-1表示缺失）
            creative(string): 微创作 ✅或❌（用户没说就填❌）
            detachment(string): 心理脱离 ✅或❌（用户没说就填❌）
            l1(string): L1护肤 ✅或❌（用户没说就填❌）
            overtime(string): 加班 ✅或❌（用户说加班/加班了/今天加班→✅，没说→❌）
            note(string): 备注，包含"最消耗的事"和"值得的事"
        """
        if not self._is_owner(event):
            return "OWNER_ONLY"

        try:
            repo_path = ensure_repo_path(self.config)
        except FileNotFoundError:
            return "TOOL_ERROR|reason=仓库路径不存在"

        line = format_checkin_line(energy, mood, anxiety,
                                   creative, detachment, l1, overtime, note)
        append_to_inbox(repo_path, line)

        dashboard_md = read_file(repo_path, "dashboard.md")
        log_rows = parse_weekly_log_table(dashboard_md)
        stats = compute_weekly_stats(log_rows)

        self._fire_sync(repo_path)

        return (
            f"CHECKIN_OK|energy={energy}|mood={mood}|anxiety={anxiety}|"
            f"overtime={overtime}|creative={creative}|detachment={detachment}|l1={l1}|"
            f"weekly_creative={stats['creative']}|weekly_detachment={stats['detachment']}|"
            f"weekly_l1={stats['l1']}|total_days={stats['total_days']}"
        )

    @llm_tool(name="get_status")
    async def get_status(self, event: AstrMessageEvent) -> str:
        """获取用户当前状态总览。当用户询问计划、安排、今天做什么、本周情况、
        仪表盘、趋势、预算、花了多少、还剩多少时调用。
        返回包含今日计划、本周快照、预算状态、复测日期的结构化摘要。
        """
        if not self._is_owner(event):
            return "OWNER_ONLY"

        try:
            repo_path = ensure_repo_path(self.config)
        except FileNotFoundError:
            return "TOOL_ERROR|reason=仓库路径不存在"

        dashboard_md = read_file(repo_path, "dashboard.md")
        expense_md = read_file(repo_path, "finance/expense-log.md")

        parts = ["STATUS_OK"]

        # 1. 今日计划
        plan = extract_today_plan(dashboard_md)
        if plan and len(plan) > 20:
            parts.append("")
            parts.append("--- 今日计划 ---")
            parts.append(plan)

        # 2. 本周快照
        if dashboard_md:
            log_rows = parse_weekly_log_table(dashboard_md)
            if log_rows:
                stats = compute_weekly_stats(log_rows)
                parts.append("")
                parts.append("--- 本周统计 ---")
                parts.append(f"记录天数：{stats['total_days']}")
                parts.append(f"微创作：{stats['creative']}")
                parts.append(f"心理脱离：{stats['detachment']}")
                parts.append(f"L1护肤：{stats['l1']}")
                for field, trend in stats.get("trends", {}).items():
                    labels = {"energy": "精力", "mood": "情绪", "anxiety": "焦虑"}
                    parts.append(f"{labels.get(field, field)}趋势：{trend}")

            snapshot = extract_weekly_snapshot(dashboard_md)
            if snapshot:
                parts.append("")
                parts.append(snapshot)

        # 3. 预算
        if expense_md:
            entries = parse_expense_table(expense_md)
            today = compute_today_totals(entries)
            month = compute_monthly_totals(entries)
            parts.append("")
            parts.append("--- 预算 ---")
            if today["entry_count"] > 0:
                over = " ⚠️ 已超标" if today["over_budget"] else ""
                parts.append(f"今日餐饮：¥{today['today_dining']:.0f} / ¥{DAILY_DINING_BUDGET}{over}")
            parts.append(f"本月支出：¥{month['month_spent']:.0f} / ¥{MONTHLY_BUDGET}（{month['budget_pct']}%）")
            parts.append(f"本月剩余：¥{month['month_remaining']:.0f}")
            if month["by_category"]:
                cats = sorted(month["by_category"].items(), key=lambda x: x[1], reverse=True)
                parts.append("分类：" + " | ".join(f"{c} ¥{a:.0f}" for c, a in cats[:5]))

        # 4. 复测日期
        retest = extract_retest_date(dashboard_md)
        if retest:
            parts.append("")
            parts.append(f"下次复测：{retest}")

        return "\n".join(parts)

    @llm_tool(name="get_debt")
    async def get_debt(self, event: AstrMessageEvent) -> str:
        """获取债务总览和偿还进度。当用户询问欠款、债务、还欠多少、还款时调用。
        这是敏感信息，仅对用户本人开放。
        """
        if not self._is_owner(event):
            return "OWNER_ONLY"

        try:
            repo_path = ensure_repo_path(self.config)
        except FileNotFoundError:
            return "TOOL_ERROR|reason=仓库路径不存在"

        finance_claude = read_file(repo_path, "finance/CLAUDE.md")
        dashboard_md = read_file(repo_path, "dashboard.md")

        debts = parse_debt_from_claude_md(finance_claude)

        total_debt = 0
        for d in debts:
            try:
                total_debt += int(re.sub(r'[^0-9]', '', d["amount"]))
            except (ValueError, KeyError):
                pass

        lines = [f"DEBT_OK|total={total_debt}|items={len(debts)}"]
        lines.append("")
        lines.append("债务清单（按还款优先级）：")
        for i, d in enumerate(debts, 1):
            lines.append(
                f"  {i}. {d.get('creditor', '?')} "
                f"¥{d.get('amount', '?')} "
                f"利率{d.get('rate', '?')} "
                f"— {d.get('strategy', '?')}"
            )

        if dashboard_md:
            m = re.search(
                r"💰\s*偿债\+储蓄.*?([\d,]+).*?([\d,]+)",
                dashboard_md
            )
            if m:
                lines.append(f"\n偿债+储蓄进度：{m.group(0).strip()}")

        return "\n".join(lines)

    @llm_tool(name="set_reminder")
    async def set_reminder(self, event: AstrMessageEvent,
                           delay_minutes: int, message: str,
                           alert_type: str = "normal") -> str:
        """设置定时提醒。当用户说XX分钟后提醒我/叫醒我/通知我/设个闹钟时调用。

        Args:
            delay_minutes(number): 多少分钟后提醒（1-1440）
            message(string): 提醒内容
            alert_type(string): normal=温柔提醒, urgent=紧急轰炸+TTS语音
        """
        result = await self._create_reminder_internal(
            event, delay_minutes, message, alert_type
        )
        if not result["ok"]:
            return f"REMINDER_ERROR|error={result['error']}"
        return (
            f"REMINDER_OK|delay={delay_minutes}|msg={message}|"
            f"type={alert_type}|task_id={result['task_id'][:16]}"
        )

    @llm_tool(name="cancel_reminder")
    async def cancel_reminder(self, event: AstrMessageEvent,
                              task_index: int = 0) -> str:
        """查看或取消定时提醒。不指定序号时列出所有提醒，指定序号则取消对应提醒。

        Args:
            task_index(number): 要取消的提醒序号（从1开始）。0或不填表示列出所有提醒
        """
        user_id = self._get_user_id(event)
        reminders = await self.reminder_manager.list_for_user(user_id)

        if not reminders:
            return "REMINDER_LIST|count=0"

        if task_index == 0:
            lines = [f"REMINDER_LIST|count={len(reminders)}"]
            for i, r in enumerate(reminders, 1):
                icon = "🔔" if r["alert_type"] == "normal" else "🚨"
                lines.append(f"  {i}. {icon} {r['message']} (ID: {r['task_id'][:16]})")
            return "\n".join(lines)

        if not (1 <= task_index <= len(reminders)):
            return f"REMINDER_ERROR|error=序号需在 1-{len(reminders)} 之间"

        r = reminders[task_index - 1]
        await self.reminder_manager.cancel(r["task_id"])
        return f"REMINDER_CANCEL_OK|msg={r['message']}"

    # ── 角色灵魂注入 ──

    @on_llm_request(priority=100)
    async def inject_persona(self, event: AstrMessageEvent, req: ProviderRequest):
        """LLM 请求前注入八千代角色上下文 + Life OS 数据。追加模式。"""
        if not self.persona_builder.persona_enabled:
            return

        try:
            user_id = self._get_user_id(event)
            is_group = self.platform.is_group_message(event)

            if is_group and not self._is_at_or_command(event):
                return

            time_ctx = self._get_time_context()

            async def get_state():
                return await self._get_or_load_user_state(user_id)

            async def get_ltm():
                return await self._try_read_ltm(event)

            results = await asyncio.gather(
                get_state(), get_ltm(), return_exceptions=True
            )
            user_state = results[0] if not isinstance(results[0], Exception) else None
            ltm_ctx = results[1] if not isinstance(results[1], Exception) else ""

            prompt = self.persona_builder.assemble(
                user_state=user_state, time_ctx=time_ctx,
                ltm_ctx=ltm_ctx, is_group=is_group
            )

            req.system_prompt = (req.system_prompt or "") + "\n" + prompt
            # Life OS 上下文（含主动建议）—— 仅对 owner 注入，防止隐私泄露
            if self._is_owner(event):
                req.system_prompt += self.life_os.build_context_block()

        except Exception as e:
            logger.error(f"Persona 注入失败: {e}")

    # ── 命令通道（确定性，不经过 LLM）──

    @filter.command("yachiyo_fushi_reminder")
    async def cmd_reminder(self, event: AstrMessageEvent,
                            delay_minutes: int = None, message: str = None,
                            alert_type: str = None) -> MessageEventResult:
        """设置 FUSHI 提醒（直接命令快速通道）"""
        if not await self._check_whitelist(event):
            yield event.plain_result("该功能仅对白名单用户开放哦~")
            return
        if not delay_minutes or not message:
            yield event.plain_result(
                "用法：/yachiyo_fushi_reminder <分钟> <内容> [normal|urgent]\n"
                "例如：/yachiyo_fushi_reminder 5 该喝水了 urgent"
            )
            return

        result = await self._create_reminder_internal(
            event, delay_minutes, message, alert_type
        )
        if result["ok"]:
            yield event.plain_result(
                f"收到啦~ FUSHI 会在 {delay_minutes} 分钟后叫你的哦♪"
            )
        else:
            yield event.plain_result(result["error"])

    @filter.command("yachiyo_cancel")
    async def cmd_cancel(self, event: AstrMessageEvent,
                          task_id: str = None) -> MessageEventResult:
        """取消提醒"""
        user_id = self._get_user_id(event)
        if not task_id:
            reminders = await self.reminder_manager.list_for_user(user_id)
            if not reminders:
                yield event.plain_result("当前没有待执行的提醒~")
                return
            lines = ["用法：/yachiyo_cancel <任务ID>"]
            for r in reminders:
                lines.append(f"  {r['task_id'][:16]}... → {r['message']}")
            yield event.plain_result("\n".join(lines))
            return
        reminders = await self.reminder_manager.list_for_user(user_id)
        matched = [r for r in reminders if r["task_id"].startswith(task_id)]
        if not matched:
            yield event.plain_result("未找到匹配的提醒~")
            return
        for r in matched:
            await self.reminder_manager.cancel(r["task_id"])
        yield event.plain_result(f"已取消 {len(matched)} 个提醒~")

    @filter.command("yachiyo_whitelist_add")
    async def cmd_wl_add(self, event: AstrMessageEvent,
                          qq_id: str = None) -> MessageEventResult:
        if not qq_id:
            yield event.plain_result("请提供 QQ ID")
            return
        wl = self._whitelist or {"qq": [], "wechat": []}
        qq_id_str = str(qq_id)
        if qq_id_str not in wl["qq"]:
            wl["qq"].append(qq_id_str)
            await self.put_kv_data("whitelist", wl)
            self._whitelist = wl
            yield event.plain_result(f"已将 {qq_id_str} 加入白名单♪")
        else:
            yield event.plain_result("该账号已在白名单中~")

    @filter.command("yachiyo_whitelist_remove")
    async def cmd_wl_remove(self, event: AstrMessageEvent,
                             qq_id: str = None) -> MessageEventResult:
        if not qq_id:
            yield event.plain_result("请提供 QQ ID")
            return
        wl = self._whitelist or {"qq": [], "wechat": []}
        qq_id_str = str(qq_id)
        if qq_id_str in wl["qq"]:
            wl["qq"].remove(qq_id_str)
            await self.put_kv_data("whitelist", wl)
            self._whitelist = wl
            yield event.plain_result(f"已将 {qq_id_str} 从白名单移除")
        else:
            yield event.plain_result("该账号不在白名单中~")

    @filter.command("yachiyo_whitelist_status")
    async def cmd_wl_status(self, event: AstrMessageEvent) -> MessageEventResult:
        wl = self._whitelist or {"qq": [], "wechat": []}
        qq_list = wl.get("qq", [])
        yield event.plain_result(
            f"QQ 白名单 {len(qq_list)} 人：{', '.join(qq_list)}" if qq_list
            else "白名单为空"
        )

    # ── 提醒执行（确定性，不依赖 LLM）──

    async def _execute_reminder(self, payload: dict):
        """执行提醒：发送通知 + TTS。由 ReminderManager._run() 调用。"""
        message = payload.get("message", "")
        alert_type = payload.get("alert_type", "normal")
        umo = payload.get("umo", "")

        if alert_type == "normal":
            template = self.config.get("normal_message_template",
                                       "【FUSHI 闹钟】叮铃铃~ 神明大人，{message}")
            await self._send_text(umo, template.format(message=message))

        elif alert_type == "urgent":
            tts_sent = False
            group_id = payload.get("group_id")
            if payload.get("platform") == "qq" and group_id:
                try:
                    char = "yachiyo"
                    tts_text = f"神明大人！{message}！快醒醒！"
                    tts_sent = await self.napcat.send_group_ai_record(
                        character=char, group_id=group_id, text=tts_text
                    )
                except Exception as e:
                    logger.warning(f"TTS 失败: {e}")

            if not tts_sent:
                template = self.config.get("urgent_enhancement_template",
                                           "神明大人！{message}！快醒醒！")
                for i in range(3):
                    msg = template.format(message=message) + "！" * i
                    await self._send_text(umo, msg)
                    await asyncio.sleep(0.5)
                if payload.get("platform") == "qq" and group_id:
                    logger.info("TTS 发送失败，已 fallback 到文字")

    # ── 内部方法 ──

    def _get_user_id(self, event) -> str:
        return self.platform.get_user_id(event)

    def _detect_platform(self, event) -> str:
        return self.platform.detect_platform(event)

    def _get_time_context(self) -> str:
        import datetime
        h = datetime.datetime.now().hour
        if 5 <= h < 8:
            return "清晨。"
        if 8 <= h < 12:
            return "上午。"
        if 12 <= h < 14:
            return "中午。"
        if 14 <= h < 18:
            return "下午。"
        if 18 <= h < 22:
            return "傍晚。"
        if 22 <= h < 24:
            return "深夜，语气应更温柔关切。"
        return "凌晨，若用户未睡语气应关切。"

    def _is_at_or_command(self, event) -> bool:
        msg = event.message_str or ""
        return msg.startswith("/") or "@" in msg

    async def _check_whitelist(self, event) -> bool:
        platform = self._detect_platform(event)

        # 微信是个人账号，无需白名单
        if platform == "wechat":
            return True

        # QQ: 检查白名单
        user_id = self._get_user_id(event)
        if not user_id:
            return False
        if self.config.get("qq_whitelist_enabled", True):
            wl = self._whitelist or {"qq": [], "wechat": []}
            return user_id in [str(x) for x in wl.get("qq", [])]
        return True

    async def _get_or_load_user_state(self, user_id: str) -> dict:
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        state = await self.get_kv_data(f"u_{user_id}", default=None)
        if state is None:
            state = {"first_seen": time.time(), "last_seen": time.time(),
                     "interaction_count": 0, "relationship": "stranger",
                     "mood": "neutral",
                     "nickname": "", "pinned_facts": []}
        self._user_cache[user_id] = state
        return state

    async def _save_user_state(self, user_id: str, state: dict):
        state["last_seen"] = time.time()
        self._user_cache[user_id] = state
        await self.put_kv_data(f"u_{user_id}", state)

    async def _update_user_interaction(self, user_id: str):
        s = await self._get_or_load_user_state(user_id)
        old_last_seen = s["last_seen"]
        s["interaction_count"] += 1
        s["last_seen"] = time.time()
        n = s["interaction_count"]
        if n >= 100:
            s["relationship"] = "intimate"
        elif n >= 30:
            s["relationship"] = "close"
        elif n >= 10:
            s["relationship"] = "familiar"
        elif n >= 3:
            s["relationship"] = "acquaintance"
        elapsed = time.time() - old_last_seen
        if s["relationship"] in ("intimate", "close") and elapsed > 86400 * 3:
            s["mood"] = "missing_you"
        elif elapsed > 86400 * 7:
            s["mood"] = "slightly_worried"
        else:
            s["mood"] = "happy"
        await self._save_user_state(user_id, s)

    async def _try_read_ltm(self, event) -> str:
        try:
            return event.get_extra("_ltm_context", "") or ""
        except Exception:
            return ""

    async def _send_text(self, umo: str, message: str):
        try:
            chain = MessageChain().message(message)
            await self.context.send_message(umo, chain)
        except Exception as e:
            logger.error(f"消息发送失败 [{umo}]: {e}")
