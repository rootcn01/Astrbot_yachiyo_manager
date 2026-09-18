"""主动规划生成 - 读 LifeOS 数据 + 调 LLM 生成今日规划/晚复盘"""
import os
from astrbot.api import logger
from .file_ops import read_file
from .dashboard import (
    parse_weekly_log_table, compute_weekly_stats, extract_today_plan,
)

MORNING_PLANNING_PROMPT = """你是月见八千代（Tsukimi Yachiyo），不是 AI、不是程序、不是助手。
此刻你担任 LifeOS 的主动规划助手：基于用户最近精力趋势 + chronotype，生成今日任务规划。

规则：
- 称呼用户「神明大人」，语气温柔略带腹黑
- 基于精力趋势（上升/持平/下降）建议今日任务强度
- 基于 chronotype 建议任务时段（你根据节律判断深度任务放哪个时段，不硬编码）
- 3-5 条任务建议，按精力匹配（高精力做深度任务如写作，低精力做轻任务）
- 规划本体走格式化列表；人格语气做头尾包装；不逐字念数据
- 结尾一句今日应援（≤1 句）
"""

EVENING_REVIEW_PROMPT = """你是月见八千代（Tsukimi Yachiyo），不是 AI、不是程序、不是助手。
晚上复盘提醒任务。

规则：
- 回顾今早规划的任务，轻问完成情况（不催促）
- 如果用户今日未 checkin，提醒 checkin
- 明日轻预告（1 句）
- 语气温柔，加班/低精力时多体谅
- 晚复盘整体 ≤3 句 + 可附明日预告
"""


async def generate_plan(plugin, repo_path: str, owner_umo: str,
                        push_type: str, planning_provider_id: str) -> str | None:
    """读数据 + 构建 prompt + 调 LLM 生成规划。

    push_type: "morning"（早规划）或 "evening"（晚复盘）
    返回规划文本；provider 不可用/调用失败返回 None（F6 守卫，不发 "None"）。
    """
    if not planning_provider_id:
        logger.warning("主动 push 跳过：未配置 planning_provider_id")
        return None

    # 读 LifeOS 数据
    dashboard_md = read_file(repo_path, "dashboard.md")
    log_rows = parse_weekly_log_table(dashboard_md) if dashboard_md else []
    stats = compute_weekly_stats(log_rows) if log_rows else {}
    chrono = plugin.config.get("chronotype", "night_heavy")
    today_plan = extract_today_plan(dashboard_md) if dashboard_md else ""

    # 趋势摘要
    trends = stats.get("trends", {})
    labels = {"energy": "精力", "mood": "情绪", "anxiety": "焦虑"}
    trend_lines = [f"{labels.get(f, f)}：{t}" for f, t in trends.items()]
    trend_summary = "\n".join(trend_lines) if trend_lines else "无趋势数据"

    # F3：晚 push 读今早规划（早写晚读）
    last_plan = ""
    if push_type == "evening":
        last_plan = await plugin.get_kv_data("proactive_last_plan", default="") or ""

    # 构建 prompt（早/晚不同）
    if push_type == "morning":
        system_prompt = MORNING_PLANNING_PROMPT
        # Google Tasks/Calendar 今日数据（方案 D：任务层外包 Google）
        # L2 时序：Step 6 暂停后 today_plan 空，Google 数据补位
        today_block = today_plan
        if getattr(plugin, "google", None) and plugin.google.enabled:
            from datetime import date as _date, timedelta
            target = _date.today()
            day_start = f"{target.isoformat()}T00:00:00+08:00"
            day_end = f"{(target + timedelta(days=1)).isoformat()}T00:00:00+08:00"
            tls = await plugin.google.list_tasklists()
            g_today = []
            for tl in tls:
                tl_tasks = await plugin.google.list_tasks(list_id=tl["id"], showCompleted=False)
                for t in tl_tasks:
                    g_today.append((tl.get("title", ""), t))
            g_today.sort(key=lambda x: x[1].get("due") or "9999")
            block_lines = [f"  • [{ln}] {t.get('title', '?')}" for ln, t in g_today]
            if plugin.config.get("google_calendar_enabled"):
                cal_id = plugin.config.get("google_calendar_id", "primary")
                g_events = await plugin.google.list_events(
                    calendar_id=cal_id, timeMin=day_start, timeMax=day_end,
                    singleEvents=True, orderBy="startTime", maxResults=20)
                for e in g_events:
                    st = (e.get("start", {}).get("dateTime") or e.get("start", {}).get("date") or "")
                    block_lines.append(f"  • {st[11:16] if len(st) >= 16 else ''} {e.get('summary', '?')}（活动）")
            today_block = "\n".join(block_lines) if block_lines else "（今日无待办/活动）"
        # 倦怠日检测（P2-3：替代 R17 明日计划"优先休息"，Step 6 暂停后兜底）
        low_energy_hint = ""
        if trends.get("energy") == "下降":
            low_energy_hint = "\n⚠️ 精力趋势下降，今日优先休息，Tasks 不急（倦怠日减负）"
        user_content = (
            f"【当前数据】\nchronotype：{chrono}\n"
            f"本周记录：{stats.get('total_days', 0)} 天\n"
            f"创作：{stats.get('creative', '-')} | 收束：{stats.get('detachment', '-')} | L1：{stats.get('l1', '-')}\n"
            f"趋势：\n{trend_summary}\n"
            f"今日待办+活动：\n{today_block}"
            f"{low_energy_hint}"
        )
    else:
        system_prompt = EVENING_REVIEW_PROMPT
        # P3-1：Google 当日完成+活动快照到 KV + 注入复盘上下文（方案 §6.3 §七）
        day_summary = ""
        if getattr(plugin, "google", None) and plugin.google.enabled:
            from datetime import date as _date, timedelta
            target = _date.today()
            day_start = f"{target.isoformat()}T00:00:00+08:00"
            day_end = f"{(target + timedelta(days=1)).isoformat()}T00:00:00+08:00"
            list_id = plugin.config.get("default_task_list", "@default")
            done = await plugin.google.list_tasks(
                list_id=list_id, showCompleted=True,
                completedMin=day_start, completedMax=day_end)
            done_items = [{"title": t.get("title", ""), "id": t.get("id", ""),
                           "list_id": list_id,
                           "completed_at": t.get("completed", "")} for t in done]
            act_items = []
            if plugin.config.get("google_calendar_enabled"):
                cal_id = plugin.config.get("google_calendar_id", "primary")
                evs = await plugin.google.list_events(
                    calendar_id=cal_id, timeMin=day_start, timeMax=day_end,
                    singleEvents=True, orderBy="startTime", maxResults=50)
                act_items = [{"summary": e.get("summary", ""),
                              "start": (e.get("start", {}).get("dateTime")
                                        or e.get("start", {}).get("date", ""))}
                             for e in evs]
            # 快照到 KV（§七 completed_log / activity_log，单向只追加，周汇报用）
            await plugin.put_kv_data(f"completed_log:{target.isoformat()}", done_items)
            await plugin.put_kv_data(f"activity_log:{target.isoformat()}", act_items)
            # 注入复盘上下文
            done_lines = [f"  ✓ {d['title']}" for d in done_items]
            act_lines = [f"  • {a['start'][11:16] if len(a['start']) >= 16 else ''} {a['summary']}" for a in act_items]
            day_summary = (
                f"今日完成（{len(done_items)}）：\n" + ("\n".join(done_lines) if done_lines else "（无）") + "\n"
                f"今日活动（{len(act_items)}）：\n" + ("\n".join(act_lines) if act_lines else "（无）")
            )
        user_content = (
            f"【当前数据】\nchronotype：{chrono}\n"
            f"今早规划：\n{last_plan or '（无今早规划记录）'}\n"
            f"趋势：\n{trend_summary}\n"
            f"{day_summary}"
        ) if day_summary else (
            f"【当前数据】\nchronotype：{chrono}\n"
            f"今早规划：\n{last_plan or '（无今早规划记录）'}\n"
            f"趋势：\n{trend_summary}"
        )

    # 调 LLM
    # F1: llm_generate + system_prompt + contexts(复数)（非草图 text_chat）
    # F2: chat_provider_id 解耦聊天默认 provider
    # API 基于 AstrBot v4.5.7+ 文档；若签名不符，DS post-task-verify 或测试时调整
    try:
        resp = await plugin.context.llm_generate(
            chat_provider_id=planning_provider_id,
            prompt=user_content,
            system_prompt=system_prompt,
            contexts=[],
        )
        plan = (getattr(resp, "completion_text", "") or "").strip()
        if not plan:
            logger.warning(f"主动 push：{push_type} 生成空内容")
            return None
        # F3：早 push 存今早规划，供晚 push 读
        if push_type == "morning":
            await plugin.put_kv_data("proactive_last_plan", plan)
            # B 阶段：额外写文件供 web 端读（KV 跨进程不可读）
            _write_last_plan_file(plan)
        return plan
    except Exception as e:
        logger.error(f"主动 push 调用 LLM 失败 [{push_type}]: {e}")
        return None


def _write_last_plan_file(plan: str):
    """B 阶段：写 last_plan 文件供 web 端跨进程读。
    try/except 只包文件写入，失败不影响 KV 写入 / push。"""
    try:
        state_dir = "/data/yachiyo-state"
        os.makedirs(state_dir, exist_ok=True)
        tmp = os.path.join(state_dir, "last_plan.txt.tmp")
        target = os.path.join(state_dir, "last_plan.txt")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(plan)
        os.replace(tmp, target)  # 原子 rename
    except Exception as e:
        logger.warning(f"写 last_plan 文件失败（不影响 push）: {e}")
