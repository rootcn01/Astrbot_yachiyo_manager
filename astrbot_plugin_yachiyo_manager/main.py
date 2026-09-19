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
from astrbot.api import llm_tool

from .utils.google_integration import GoogleIntegration
from .utils.persona_builder import PersonaBuilder
from .utils.reminder_manager import ReminderManager
from .utils.platform_adapter import PlatformAdapter
from .utils.napcat_client import NapCatClient
from .utils.life_os import LifeOSContext
from .utils.life_os.planner import generate_plan
from .utils.proactive_scheduler import ProactiveScheduler
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

        self.persona_builder = PersonaBuilder(
            persona_enabled=self.config.get("persona_enabled", True)
        )
        self.life_os = LifeOSContext(self.config)
        self.proactive_scheduler = ProactiveScheduler(self)
        self.google = GoogleIntegration(self.config)
        self._last_owner_umo = None

        self._user_cache: dict[str, dict] = {}
        self._whitelist: dict = None
        # D0：interaction 计数按消息 id 去重（agent 循环一轮可能多次 on_llm_request）
        from collections import deque
        self._counted_msgs: deque = deque(maxlen=256)

        logger.info("八千代插件已初始化（含 Life OS v2.2 全局工具）")

    # ── 生命周期 ──

    async def initialize(self):
        self._whitelist = await self.get_kv_data("whitelist",
                                                  default={"qq": [], "wechat": []})
        await self._migrate_old_data()
        await self.reminder_manager.restore_all()
        await self.proactive_scheduler.start()
        await self.google.initialize()
        self._load_tone_zones()
        logger.info("八千代插件激活完成")

    def _load_tone_zones(self):
        """W3：加载台词分区选区数据（编译产物，随插件包分发）。
        缺文件/坏 JSON = 选区关闭回退纯协议采样，禁静默用旧数据。"""
        import json as _json
        try:
            path = Path(__file__).parent / "resources" / "tone_zones.json"
            data = _json.loads(path.read_text(encoding="utf-8-sig"))
            self.persona_builder.tone_zones = data
            zones = data.get("zones", {})
            logger.info(
                f"台词库选区数据加载 v{data.get('version')} "
                f"（营业{len(zones.get('营业', []))}/温柔{len(zones.get('温柔', []))}/"
                f"腹黑{len(zones.get('腹黑', []))}）")
        except FileNotFoundError:
            logger.warning("tone_zones.json 缺失：台词选区注入关闭（纯协议采样）")
        except Exception as e:
            logger.warning(f"tone_zones.json 加载失败（选区关闭）：{e}")

    async def terminate(self):
        """插件卸载时取消所有待执行的提醒任务"""
        for task in list(self.reminder_manager.tasks.values()):
            task.cancel()
        self.reminder_manager.tasks.clear()
        self.proactive_scheduler.cancel_all()
        logger.info("八千代插件已终止，所有提醒任务已取消")
        await self.google.close()
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

    # ── 关系/记忆类（W4）──

    @llm_tool(name="set_nickname")
    async def set_nickname(self, event: AstrMessageEvent,
                           nickname: str = "") -> str:
        """当用户明确要求记住对TA的称呼时调用（如「以后叫我XX」「记住，叫我XX就好」）。
        只在用户明确提出时调用；从对话自行推断的称呼不要写入。
        更新后下一轮对话你就会以这个称呼叫TA。

        Args:
        nickname(string): 用户要求的称呼，≤12字，原样保留用户的用词
        """
        nickname = (nickname or "").strip()[:12]
        if not nickname:
            return "NICKNAME_EMPTY|未记录"
        user_id = self._get_user_id(event)
        state = await self._get_or_load_user_state(user_id)
        old = state.get("nickname", "")
        state["nickname"] = nickname
        await self._save_user_state(user_id, state)
        replaced = f"|replaced={old}" if old else ""
        return f"NICKNAME_OK|nickname={nickname}{replaced}"

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
            knowledge_keywords = ["kb", "知识", "学到", "了解一下", "查一下"]
            idea_keywords = ["设定", "世界观", "角色", "故事", "创意", "灵感",
                           "设计", "构思", "点子", "想法", "施法", "魔法",
                           "精灵", "种族", "能力", "剧情", "世界观"]
            todo_keywords = ["记得", "别忘了", "要做", "提醒我", "回电话",
                           "交", "买", "去", "约了", "开会", "打卡"]
            content_lower = content.lower()
            if any(kw in content for kw in knowledge_keywords):
                note_type = "kb"
            elif any(kw in content for kw in idea_keywords):
                note_type = "idea"
            elif any(kw in content for kw in todo_keywords):
                note_type = "todo"
            else:
                note_type = "todo"  # 默认当待办

        # todo -> Google Tasks（含降级），其他类型（idea/kb/food）写 inbox
        if note_type == "todo" and self.google.enabled:
            result = await self._create_gtask_with_fallback(content, repo_path)
            if result["ok"]:
                return (f"TASK_OK|title={content[:100]}|list={result.get('list', '@default')}"
                        f"|task_id={result.get('task_id', '')[:12]}")
            return (f"TASK_FALLBACK|title={content[:100]}|reason={result['reason']}"
                    f"|stored=inbox（八千代恢复后迁移）")

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

        数值 1-10。参考锚点（详见 LifeOS shared/rating-anchors.md）：
        - 精力：3=只想躺着做什么都费力，5=正常但不想额外做事，7=还能做额外事
        - 情绪：3=闷闷不乐提不起劲，5=正常无特别，7=还不错愿意交流
        - 焦虑：3=轻度偶尔烦，5=担忧反复但不影响做事，7=需转移注意力，8=影响效率应休息

        用户自然语言→数值映射：
        - 累爆了/完全没电→1-3，有点累→4-5，正常/还行→5-6，还不错→6-7，精力充沛→8-10
        - 很低落/崩了→1-3，不太好→3-4，还行/正常→5，还行有点开心→6-7，很开心→8-10
        - 不焦虑/很放松→1-2，有点焦虑→3-4，焦虑但还能做事→5-6，停不下来/影响做事→7-8，灾难化/身体反应→9-10

        不确定时往中间靠（5）。用户给出范围取较低值。完全无法推断填-1。

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

        # 1. 今日计划（Google Tasks due today + Calendar 活动；未启用则回退 dashboard）
        if self.google.enabled:
            from datetime import date as _date, timedelta
            target = _date.today()
            day_start = f"{target.isoformat()}T00:00:00+08:00"
            day_end = f"{(target + timedelta(days=1)).isoformat()}T00:00:00+08:00"
            tasklists = await self.google.list_tasklists()
            all_tasks = []
            for tl in tasklists:
                tl_tasks = await self.google.list_tasks(list_id=tl["id"], showCompleted=False)
                for t in tl_tasks:
                    all_tasks.append((tl.get("title", ""), t))
            all_tasks.sort(key=lambda x: x[1].get("due") or "9999")
            parts.append("")
            parts.append(f"--- 待办（{len(all_tasks)}）---")
            for list_name, t in all_tasks:
                due = t.get("due", "")
                due_str = due[:10] if due else "无日期"
                parts.append(f"  • [{list_name}] {t.get('title', '?')} (due:{due_str})")
            if self.config.get("google_calendar_enabled"):
                cal_id = self.config.get("google_calendar_id", "primary")
                events = await self.google.list_events(
                    calendar_id=cal_id, timeMin=day_start, timeMax=day_end,
                    singleEvents=True, orderBy="startTime", maxResults=20)
                parts.append(f"--- 今日活动（{len(events)}）---")
                for e in events:
                    st = (e.get("start", {}).get("dateTime") or e.get("start", {}).get("date") or "")
                    parts.append(f"  • {st[11:16] if len(st) >= 16 else ''} {e.get('summary', '?')}")
        else:
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

    # ── Google Tasks / Calendar ──

    async def _create_gtask_with_fallback(self, content: str, repo_path: str) -> dict:
        """创建 Google Task，失败重试 3 次（指数退避），仍失败降级写 inbox。

        降级策略见 pipeline/2026-07-17-google-tasks-calendar-sync-plan.md §6.6。
        """
        list_id = self.config.get("default_task_list", "@default")
        for attempt in range(3):
            result = await self.google.insert_task(content, list_id=list_id)
            if result:
                return {"ok": True, "list": list_id, "task_id": result.get("id", "")}
            await asyncio.sleep(2 ** attempt)  # 1s / 2s / 4s
        # 3 次失败 -> 降级写 inbox（保留 todo 格式 + 待迁移标记）
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            append_to_inbox(repo_path, f"todo {content}  # {ts}  # Google失败待迁移")
            self._fire_sync(repo_path)
        except Exception as e:
            logger.error(f"Google Task 降级写 inbox 也失败: {e}")
        return {"ok": False, "reason": "Google API 3次重试失败，已暂存 inbox"}

    @llm_tool(name="list_tasks")
    async def list_tasks(self, event: AstrMessageEvent, date: str = "") -> str:
        """查看待办和活动。当用户问今天有什么事/今日任务/今天安排/待办/活动时调用。

        Args:
            date(string): 日期 YYYY-MM-DD，空=今天
        """
        if not self._is_owner(event):
            return "OWNER_ONLY"
        if not self.google.enabled:
            return "TASKS_DISABLED|reason=Google 集成未启用"

        from datetime import date as _date, timedelta
        try:
            target = datetime.strptime(date, "%Y-%m-%d").date() if date else _date.today()
        except ValueError:
            return "TASKS_ERROR|reason=日期格式应为 YYYY-MM-DD"

        day_start = f"{target.isoformat()}T00:00:00+08:00"
        day_end = f"{(target + timedelta(days=1)).isoformat()}T00:00:00+08:00"
        parts = [f"TASKS_OK|date={target.isoformat()}"]

        # 待办（Tasks due 当天，未完成）
        tasklists = await self.google.list_tasklists()
        all_tasks = []
        for tl in tasklists:
            tl_tasks = await self.google.list_tasks(list_id=tl["id"], showCompleted=False)
            for t in tl_tasks:
                all_tasks.append((tl.get("title", ""), t))
        all_tasks.sort(key=lambda x: x[1].get("due") or "9999")
        parts.append(f"--- 待办（{len(all_tasks)}）---")
        for list_name, t in all_tasks:
            due = t.get("due", "")
            due_str = due[:10] if due else "无日期"
            parts.append(f"  • [{list_name}] {t.get('title', '?')} (due:{due_str})")

        # 活动（Calendar 当天）
        if self.config.get("google_calendar_enabled"):
            cal_id = self.config.get("google_calendar_id", "primary")
            events = await self.google.list_events(
                calendar_id=cal_id, timeMin=day_start, timeMax=day_end,
                singleEvents=True, orderBy="startTime", maxResults=20,
            )
            parts.append(f"--- 活动（{len(events)}）---")
            for e in events:
                start = e.get("start", {})
                st = start.get("dateTime") or start.get("date") or ""
                hhmm = st[11:16] if len(st) >= 16 else ""
                parts.append(f"  • {hhmm} {e.get('summary', '?')}")

        return "\n".join(parts)

    @llm_tool(name="complete_task")
    async def complete_task(self, event: AstrMessageEvent, task_title: str = "") -> str:
        """完成一个待办。当用户说做完了/完成了X/搞定X时调用。

        Args:
            task_title(string): 完成的任务标题关键词（模糊匹配）
        """
        if not self._is_owner(event):
            return "OWNER_ONLY"
        if not self.google.enabled:
            return "TASKS_DISABLED"
        if not task_title:
            return "TASKS_ERROR|reason=请提供完成的任务标题"

        # 拉所有 list 找匹配任务（complete 需要 list_id）
        tasklists = await self.google.list_tasklists()
        matched = []  # [(list_id, task)]
        for tl in tasklists:
            tl_tasks = await self.google.list_tasks(list_id=tl["id"], showCompleted=False)
            for t in tl_tasks:
                if task_title in (t.get("title") or ""):
                    matched.append((tl["id"], t))
        if not matched:
            return f"TASK_NOT_FOUND|query={task_title}"
        if len(matched) > 1:
            lines = [f"TASK_AMBIGUOUS|count={len(matched)}|请更精确指定"]
            for i, (lid, t) in enumerate(matched, 1):
                lines.append(f"  {i}. {t.get('title', '?')} (id={t.get('id', '')[:8]})")
            return "\n".join(lines)

        list_id, task = matched[0]
        ok = await self.google.complete_task(task["id"], list_id=list_id)
        return f"TASK_DONE|ok={ok}|title={task.get('title', '')}"

    # ── 角色灵魂注入 ──

    @on_llm_request(priority=100)
    async def inject_persona(self, event: AstrMessageEvent, *args, **kwargs):
        """LLM 请求前注入八千代角色上下文 + Life OS 数据。
        v4.26.5 on_llm_request 传参变化（req 位置漂移），用 isinstance 从 args/kwargs 找 ProviderRequest。"""
        if not self.persona_builder.persona_enabled:
            return

        # v4.26.5 适配：从 args/kwargs 找 ProviderRequest（req 位置可能漂移到 plugin）
        from astrbot.api.provider import ProviderRequest
        req = None
        for a in args:
            if isinstance(a, ProviderRequest):
                req = a
                break
        if req is None:
            req = kwargs.get("req")
        if req is None:
            logger.warning(f"inject_persona: 未找到 ProviderRequest，args 类型={[type(a).__name__ for a in args]}, kwargs keys={list(kwargs.keys())}")
            return  # 没找到 ProviderRequest，跳过（不报错，工具列表不注入）

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
            # D0：注入成功 = 一次真实人格互动，修活关系计数（按消息 id 去重）
            msg_id = getattr(getattr(event, "message_obj", None), "id", "")
            if msg_id and msg_id not in self._counted_msgs:
                self._counted_msgs.append(msg_id)
                await self._update_user_interaction(user_id)
            # Life OS 上下文（含主动建议）—— 仅对 owner 注入，防止隐私泄露
            if self._is_owner(event):
                req.system_prompt += self.life_os.build_context_block()
                # F8: 存 owner umo（变了才写，避免每请求写 KV）
                umo = event.unified_msg_origin
                if umo and umo != self._last_owner_umo:
                    await self.put_kv_data("owner_umo", umo)
                    self._last_owner_umo = umo

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

    # ── 主动 push 执行 ──

    async def _execute_proactive_push(self, push_type: str):
        """主动 push 执行：pull 最新 -> 生成规划 -> push。由 ProactiveScheduler 调用。"""
        try:
            repo_path = ensure_repo_path(self.config)
        except FileNotFoundError:
            logger.warning("主动 push：仓库路径不存在")
            return
        await sync_git(repo_path)  # 定时 pull，解决数据滞后
        owner_umo = await self.get_kv_data("owner_umo", default="")
        if not owner_umo:
            logger.warning("主动 push：owner_umo 未获取（需 owner 先交互一次）")
            return
        planning_provider_id = self.config.get("planning_provider_id", "")
        plan = await generate_plan(self, repo_path, owner_umo, push_type, planning_provider_id)
        if not plan:  # F6: None 守卫，不发 "None"
            return
        await self._send_text(owner_umo, plan)

    @filter.command("yachiyo_test_plan")
    async def cmd_test_plan(self, event: AstrMessageEvent,
                            push_type: str = "morning") -> MessageEventResult:
        """手动触发主动 push 测试。push_type: morning（早规划）/ evening（晚复盘）"""
        if not self._is_owner(event):
            yield event.plain_result("OWNER_ONLY")
            return
        try:
            repo_path = ensure_repo_path(self.config)
        except FileNotFoundError:
            yield event.plain_result("仓库路径不存在")
            return
        planning_provider_id = self.config.get("planning_provider_id", "")
        plan = await generate_plan(self, repo_path, event.unified_msg_origin,
                                   push_type, planning_provider_id)
        if not plan:
            yield event.plain_result(
                "生成失败：检查 planning_provider_id 是否配置 + LLM 调用日志"
            )
            return
        yield event.plain_result(plan)

    @filter.command("yachiyo_test_cron")
    async def cmd_test_cron(self, event: AstrMessageEvent,
                            *args, **kwargs) -> MessageEventResult:
        """手动触发完整 cron push 链路（sync_git+owner_umo+_send_text），验证主动 push 不等 cron。"""
        push_type = kwargs.get("push_type") or (args[0] if args else "morning")
        if not self._is_owner(event):
            yield event.plain_result("OWNER_ONLY")
            return
        owner_umo = await self.get_kv_data("owner_umo", default="")
        if not owner_umo:
            yield event.plain_result("owner_umo 未存：先和八千代普通对话一句（非命令），再试")
            return
        yield event.plain_result(f"触发 {push_type} 完整 cron 链路（sync_git+规划+push）...")
        await self._execute_proactive_push(push_type)
        yield event.plain_result("已触发。看微信是否收到 push + 查日志。")

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
        old_rel, old_mood = s["relationship"], s["mood"]
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
        # 节流落盘：关系跨档 / 心情变化 / 距上次落盘 >10min 才写 KV（防每消息写放大）
        now = time.time()
        if (s["relationship"] != old_rel or s["mood"] != old_mood
                or now - s.get("last_persist", 0) > 600):
            s["last_persist"] = now
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
