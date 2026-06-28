"""支出计算 — 预算统计、今日/本月消费汇总"""
import re
import os
from datetime import datetime, timedelta


# 月度预算（来自 finance/CLAUDE.md）
MONTHLY_BUDGET = 4700
DAILY_DINING_BUDGET = 40


def parse_expense_table(content: str) -> list[dict]:
    """解析 expense-log.md 的表格行，返回支出条目列表。"""
    entries = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|") or "日期" in line or "---" in line:
            continue
        # 格式: | 6/27 | 35 | 支出 | 🍜餐饮 | 午餐 | |
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        try:
            entries.append({
                "date_str": parts[1],
                "amount": float(parts[2]),
                "category": parts[4].lstrip("🍜🏠💡🚇🛒🎮🔧💊💰💵✍️🎁"),
                "desc": parts[5],
            })
        except (ValueError, IndexError):
            continue
    return entries


def compute_today_totals(entries: list[dict]) -> dict:
    """从支出列表中计算今日统计。"""
    today = datetime.now().strftime("%m/%d")
    today_entries = [e for e in entries if e["date_str"] == today]

    total = sum(e["amount"] for e in today_entries)
    dining = sum(e["amount"] for e in today_entries
                 if "餐饮" in e.get("category", ""))

    over_budget = dining > DAILY_DINING_BUDGET
    budget_pct = int(dining / DAILY_DINING_BUDGET * 100) if DAILY_DINING_BUDGET else 0

    return {
        "today_total": total,
        "today_dining": dining,
        "daily_budget": DAILY_DINING_BUDGET,
        "over_budget": over_budget,
        "budget_pct": budget_pct,
        "entry_count": len(today_entries),
    }


def compute_monthly_totals(entries: list[dict]) -> dict:
    """计算本月支出总计。"""
    now = datetime.now()
    this_month = now.strftime("%m")
    this_year = now.strftime("%Y")

    month_entries = []
    for e in entries:
        try:
            # date_str 格式 "6/27" → 需要补全年份
            parts = e["date_str"].split("/")
            if len(parts) == 2:
                m, d = parts
                # 假设在当年（跨年边缘情况忽略，12月 dashboard 能看到）
                if int(m) == int(this_month):
                    month_entries.append(e)
        except (ValueError, IndexError):
            continue

    total = sum(e["amount"] for e in month_entries)
    remaining = MONTHLY_BUDGET - total
    pct = int(total / MONTHLY_BUDGET * 100)

    # 按分类汇总
    by_cat: dict[str, float] = {}
    for e in month_entries:
        cat = e.get("category", "其他")
        by_cat[cat] = by_cat.get(cat, 0) + e["amount"]

    return {
        "month_spent": total,
        "month_budget": MONTHLY_BUDGET,
        "month_remaining": remaining,
        "budget_pct": pct,
        "by_category": by_cat,
        "entry_count": len(month_entries),
    }


def parse_debt_from_claude_md(content: str) -> list[dict]:
    """从 finance/CLAUDE.md 解析债务表。"""
    debts = []
    in_table = False
    for line in content.split("\n"):
        line = line.strip()
        if "债务（按还款优先级）" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and "---" not in line and "债权人" not in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                try:
                    debts.append({
                        "creditor": parts[1],
                        "amount": parts[2],
                        "rate": parts[3],
                        "strategy": parts[4],
                    })
                except IndexError:
                    continue
        if in_table and line == "":
            break
    return debts
