"""仪表盘解析 — 从 dashboard.md 提取结构化数据"""
import re
from datetime import datetime


def extract_section(content: str, heading: str) -> str:
    """提取 markdown 中某个 ## 标题下的完整内容。

    从 heading 那一行开始，到下一个同级或更高级标题为止。
    """
    escaped = re.escape(heading)
    # 匹配 "## heading" 或 "## heading（...）" 等形式
    pattern = rf"^##\s+{escaped}.*$"
    lines = content.split("\n")
    start = None
    for i, line in enumerate(lines):
        if re.match(pattern, line.strip()):
            start = i
            break
    if start is None:
        return ""
    # 收集到下一个 ## 或 # 标题
    result = [lines[start]]
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if re.match(r"^##?\s", stripped):
            break
        result.append(lines[j])
    return "\n".join(result)


def parse_weekly_log_table(content: str) -> list[dict]:
    """解析「本周日志」表格，返回日期→数据的映射列表。

    兼容两种格式：
    - 旧版（8列）：日期 | 精力 | 情绪 | 焦虑 | 创作 | 脱离 | L1 | 备注
    - 新版（9列）：日期 | 精力 | 情绪 | 焦虑 | 加班 | 创作 | 脱离 | L1 | 备注
    """
    rows = []
    in_log = False
    for line in content.split("\n"):
        stripped = line.strip()
        if "本周日志" in stripped:
            in_log = True
            continue
        if in_log and stripped.startswith("|") and "---" not in stripped and "日期" not in stripped:
            parts = [p.strip() for p in stripped.split("|")]
            n = len(parts)
            if n >= 9:
                # 新版 9列：日期 | 精力 | 情绪 | 焦虑 | 加班 | 创作 | 脱离 | L1 | 备注
                try:
                    rows.append({
                        "date": parts[1],
                        "energy": _parse_int(parts[2]),
                        "mood": _parse_int(parts[3]),
                        "anxiety": _parse_int(parts[4]),
                        "overtime": parts[5],
                        "creative": parts[6],
                        "detachment": parts[7],
                        "l1": parts[8],
                        "note": parts[9] if n > 9 else "",
                    })
                except (ValueError, IndexError):
                    continue
            elif n >= 7:
                # 旧版 8列：日期 | 精力 | 情绪 | 焦虑 | 创作 | 脱离 | L1 | 备注
                try:
                    rows.append({
                        "date": parts[1],
                        "energy": _parse_int(parts[2]),
                        "mood": _parse_int(parts[3]),
                        "anxiety": _parse_int(parts[4]),
                        "overtime": "",  # 旧格式无加班列
                        "creative": parts[5],
                        "detachment": parts[6],
                        "l1": parts[7],
                        "note": parts[8] if n > 8 else "",
                    })
                except (ValueError, IndexError):
                    continue
        if in_log and stripped == "" and rows:
            break  # 表格后空行 = 结束
    return rows


def compute_weekly_stats(rows: list[dict]) -> dict:
    """从本周日志行计算累计统计。"""
    total_days = len(rows)
    creative_days = sum(1 for r in rows if "✅" in r.get("creative", ""))
    detachment_days = sum(1 for r in rows if "✅" in r.get("detachment", ""))
    l1_days = sum(1 for r in rows if "✅" in r.get("l1", ""))

    # 趋势：比较前半周和后半周
    trends = {}
    if total_days >= 3:
        mid = total_days // 2
        for field in ["energy", "mood", "anxiety"]:
            first = [r[field] for r in rows[:mid] if isinstance(r.get(field), (int, float))]
            second = [r[field] for r in rows[mid:] if isinstance(r.get(field), (int, float))]
            if first and second:
                avg1 = sum(first) / len(first)
                avg2 = sum(second) / len(second)
                diff = avg2 - avg1
                if abs(diff) < 0.5:
                    trends[field] = "→ 持平"
                elif diff > 0:
                    trends[field] = f"↗️ 上升 (+{diff:.1f})"
                else:
                    trends[field] = f"↘️ 下降 ({diff:.1f})"

    return {
        "total_days": total_days,
        "creative": f"{creative_days}/{total_days}",
        "detachment": f"{detachment_days}/{total_days}",
        "l1": f"{l1_days}/{total_days}",
        "trends": trends,
    }


def extract_today_plan(content: str) -> str:
    """提取「明日计划」区块（其实是今日计划——Claude 昨晚生成的）。"""
    section = extract_section(content, "📅 明日计划")
    if not section:
        return "（暂无今日计划——Claude 还没生成今天的~）"
    return section


def extract_weekly_snapshot(content: str) -> str:
    """提取「本周快照」区块。"""
    return extract_section(content, "📊 本周快照")


def extract_global_status(content: str) -> str:
    """提取「全局状态」区块。"""
    return extract_section(content, "🗺️ 全局状态")


def extract_retest_date(content: str) -> str:
    """提取下次复测日期。"""
    m = re.search(r"下次复测[：:]\s*\*?\*?(\d{4}-\d{2}-\d{2})", content)
    if not m:
        return ""
    retest_str = m.group(1)
    try:
        retest_date = datetime.strptime(retest_str, "%Y-%m-%d")
        days_left = (retest_date - datetime.now()).days
        if days_left < 0:
            return f"{retest_str}（已逾期 {abs(days_left)} 天）"
        return f"{retest_str}（{days_left} 天后）"
    except ValueError:
        return retest_str


def extract_wfa(content: str) -> str:
    """提取「本周焦点分配（WFA）」区块。"""
    section = extract_section(content, "🎯 本周焦点分配")
    if not section:
        section = extract_section(content, "🎯 本周焦点")
    return section


def extract_overtime_stats(rows: list[dict]) -> dict:
    """从本周日志行计算加班统计。"""
    total = len(rows)
    if total == 0:
        return {"overtime_days": 0, "total_days": 0, "ratio": 0}
    ot = sum(1 for r in rows if "✅" in r.get("overtime", ""))
    return {
        "overtime_days": ot,
        "total_days": total,
        "ratio": ot / total if total > 0 else 0,
    }


def _parse_int(s: str) -> int | None:
    try:
        return int(s)
    except (ValueError, TypeError):
        return None
