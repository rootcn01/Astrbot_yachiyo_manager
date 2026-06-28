"""Life OS 上下文构建 — 为 LLM 注入当前生活数据状态 + 主动建议"""
from datetime import datetime

from .file_ops import read_file, ensure_repo_path
from .dashboard import (
    extract_today_plan, extract_weekly_snapshot, extract_global_status,
    parse_weekly_log_table, compute_weekly_stats, extract_retest_date,
    extract_wfa, extract_overtime_stats,
)
from .expense import (
    parse_expense_table, compute_today_totals, compute_monthly_totals,
    parse_debt_from_claude_md, MONTHLY_BUDGET,
)


class LifeOSContext:
    """读取 Futureplan 数据仓库，构建注入 LLM 的上下文块。"""

    def __init__(self, config: dict):
        self.config = config
        self._last_build = 0.0
        self._cached_block = ""

    def build_context_block(self) -> str:
        """构建追加到 system_prompt 的 Life OS 上下文。

        包含：当前时间、本周快照、今日餐饮、本月预算、复测日期、
        可用工具列表、主动行为建议。
        """
        import time
        now = time.time()
        # 缓存 60 秒
        if self._cached_block and (now - self._last_build) < 60:
            return self._cached_block

        try:
            repo_path = ensure_repo_path(self.config)
        except FileNotFoundError:
            return ""

        dashboard_md = read_file(repo_path, "dashboard.md")
        finance_claude = read_file(repo_path, "finance/CLAUDE.md")
        expense_md = read_file(repo_path, "finance/expense-log.md")

        # 时间上下文
        now_dt = datetime.now()
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        time_str = now_dt.strftime(f"%Y年%m月%d日 {weekday_names[now_dt.weekday()]} %H:%M")
        hour = now_dt.hour
        weekday = now_dt.weekday()

        lines = [
            "",
            "[Life OS 上下文]",
            f"当前时间：{time_str}",
        ]

        # 本周统计（用于趋势感知）
        stats = {}
        ot_stats = {}
        log_rows = []
        if dashboard_md:
            log_rows = parse_weekly_log_table(dashboard_md)
            if log_rows:
                stats = compute_weekly_stats(log_rows)
                ot_stats = extract_overtime_stats(log_rows)
                lines.append(
                    f"本周快照：创作 {stats['creative']} | "
                    f"脱离 {stats['detachment']} | "
                    f"L1 {stats['l1']}"
                )
                if ot_stats["total_days"] > 0:
                    lines.append(
                        f"  加班 {ot_stats['overtime_days']}/{ot_stats['total_days']} 天 "
                        + ("⚠️ 加班较多" if ot_stats.get("ratio", 0) >= 0.6 else "")
                    )
                for field, trend in stats.get("trends", {}).items():
                    labels = {"energy": "精力", "mood": "情绪", "anxiety": "焦虑"}
                    lines.append(f"  {labels.get(field, field)}趋势：{trend}")

            retest = extract_retest_date(dashboard_md)
            if retest:
                lines.append(f"下次复测：{retest}")

            # WFA 本周焦点
            wfa = extract_wfa(dashboard_md)
            if wfa:
                lines.append("")
                lines.append(wfa)

        # 今日餐饮 + 本月预算
        today = {}
        month = {}
        if expense_md:
            entries = parse_expense_table(expense_md)
            today = compute_today_totals(entries)
            month = compute_monthly_totals(entries)

            if today.get("entry_count", 0) > 0:
                over = " ⚠️ 已超标" if today.get("over_budget") else ""
                lines.append(
                    f"今日餐饮累计：¥{today['today_dining']:.0f} / "
                    f"日均 ¥{today['daily_budget']}{over}"
                )

            if month.get("entry_count", 0) > 0:
                lines.append(
                    f"本月预算剩余：¥{month['month_remaining']:.0f} / "
                    f"¥{MONTHLY_BUDGET}（已用 {month['budget_pct']}%）"
                )

        # ── 主动行为建议（自然融入对话，不要逐字念）──
        suggestions = []

        # 时间感知
        if hour >= 20:
            suggestions.append("现在已是晚上 → 如果用户还没汇报今天状态，轻问一句")
        if hour >= 22:
            suggestions.append("深夜了 → 语气更温柔，提醒用户早点休息")
        if hour < 8:
            suggestions.append("清晨 → 如果用户醒了，语气轻柔，不建议催促任务")

        # L1 缺口
        if stats:
            l1_parts = stats.get("l1", "0/7").split("/")
            try:
                l1_done = int(l1_parts[0])
                if l1_done <= 1 and stats.get("total_days", 0) >= 3:
                    suggestions.append("L1本周严重缺口 → 找机会轻问一句护肤情况")
            except (ValueError, IndexError):
                pass

            # 创作连续性
            creative_parts = stats.get("creative", "0/7").split("/")
            try:
                creative_done = int(creative_parts[0])
                total = int(creative_parts[1])
                if creative_done <= 2 and total >= 5:
                    suggestions.append("创作完成率偏低 → 如果用户状态还行，可以鼓励一下微创作")
            except (ValueError, IndexError):
                pass

        # 预算预警
        if today.get("over_budget"):
            suggestions.append("今日餐饮已超标 → 晚上如果用户再提吃的，用腹黑语气提醒")
        if month.get("budget_pct", 0) >= 80:
            suggestions.append(f"本月预算已用{month['budget_pct']}% → 如果用户提消费，提醒节制")

        # 周末提醒
        if weekday in (4, 5):  # 周五/周六
            suggestions.append("快到周末 → 可以轻问一句周日是否有空做周复盘")

        # 加班周 → 降低期望
        if ot_stats and ot_stats.get("ratio", 0) >= 0.6 and ot_stats.get("total_days", 0) >= 4:
            suggestions.append("本周加班较多 → 语气多体谅，不要催促任何任务，周末优先恢复")

        if suggestions:
            lines.append("")
            lines.append("行为指引（自然融入对话，不要逐字念）：")
            for s in suggestions:
                lines.append(f"  · {s}")

        # ── 可用工具列表 ──
        lines.append("")
        lines.append("可用工具（用户每次发消息时 LLM 都能调用）：")
        lines.append("  · 用户说花了钱/买东西 → record_expense(amount, description, category)")
        lines.append("  · 用户说要做/记得/别忘了/灵感/设定 → record_note(content, note_type)")
        lines.append("  · 用户汇报精力/情绪/焦虑/状态 → record_checkin(energy, mood, anxiety, ...)")
        lines.append("  · 用户问计划/安排/本周/预算/趋势 → get_status()")
        lines.append("  · 用户问欠款/债务/还欠多少 → get_debt()")
        lines.append("  · 用户说XX分钟后提醒我 → set_reminder(delay_minutes, message)")
        lines.append("  · 用户说查看/取消提醒 → cancel_reminder(task_index)")

        block = "\n".join(lines)
        self._cached_block = block
        self._last_build = now
        return block
