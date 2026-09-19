#!/usr/bin/env python3
"""W-AH 判据③统计器 — angel_heart 秘书调用量/决策分布/延迟/错误（只读）。

在宿主机跑：sudo python3 wah_judge3_stats.py [--since 24h]
依据容器日志行格式（2026-09-19 实测样本）：
  [HH:MM:SS.mmm] ... [roles.secretary:258]: AngelHeart[umo]: 秘书开始调用LLM进行分析...
  [HH:MM:SS.mmm] ... [roles.front_desk:559]: AngelHeart[umo]: 决策为'参与'。策略: 被呼唤回复
  [HH:MM:SS.mmm] ... [roles.front_desk:503]: AngelHeart[umo]: 决策为'不参与'。原因: 不在场
  [HH:MM:SS.mmm] ... [core.angel_heart_context:492]: AngelHeart[umo]: 分析完成，已更新缓存。决策: 回复 | 策略: X | 话题: Y
时间戳无日期：跨天窗口统计时按行序推进（日界处 HH 回卷按 +24h 折算，仅供延迟配对用）。
"""
import re
import subprocess
import sys
from collections import Counter

ANSI = re.compile(r"\x1b\[[0-9;]*m")
TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]")
RE_CALL = re.compile(r"AngelHeart\[(.+?)\]: 秘书开始调用LLM进行分析")
RE_DECIDE_PART = re.compile(r"AngelHeart\[(.+?)\]: 决策为'参与'。策略: (.+?)\s*$")
RE_DECIDE_SKIP = re.compile(r"AngelHeart\[(.+?)\]: 决策为'不参与'")
RE_DONE = re.compile(r"AngelHeart\[(.+?)\]: 分析完成，已更新缓存。决策: (.+?) \| 策略: (.+?) \| 话题: (.*?)(?: \| 目标.*)?\s*$")


def to_sec(h, m, s, ms, base):
    t = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    if base is not None and t < base - 3600:  # 日界回卷
        t += 86400
    return t


def main():
    since = "24h"
    if "--since" in sys.argv:
        since = sys.argv[sys.argv.index("--since") + 1]
    p = subprocess.run(["docker", "logs", "astrbot-astrbot-1", "--since", since],
                       capture_output=True, text=True)
    lines = (p.stdout + p.stderr).splitlines()

    calls, latencies = [], []          # (umo, t) / (umo, 秒)
    decide_part, decide_skip = Counter(), Counter()
    strategies, topics = Counter(), Counter()
    errors = []
    base = None
    pending = {}                       # umo -> 最近一次 LLM 调用时间

    for raw in lines:
        line = ANSI.sub("", raw)
        m = TS.match(line)
        if not m:
            continue
        t = to_sec(*m.groups(), base)
        base = t if base is None else base

        if "ERROR" in line or "Traceback" in line:
            if "AngelHeart" in line or "angel_heart" in line:
                errors.append(line.strip()[:160])
            continue
        if (c := RE_CALL.search(line)):
            pending[c.group(1)] = t
            calls.append(c.group(1))
        elif (d := RE_DECIDE_PART.search(line)):
            umo = d.group(1)
            decide_part[umo] += 1
            if umo in pending:
                latencies.append(t - pending.pop(umo))
        elif (d := RE_DECIDE_SKIP.search(line)):
            decide_skip[d.group(1)] += 1
        elif (a := RE_DONE.search(line)):
            strategies[a.group(3)] += 1
            if a.group(4).strip():
                topics[a.group(4).strip()[:30]] += 1

    lat = sorted(latencies)
    pct = lambda q: lat[min(len(lat) - 1, int(len(lat) * q))] if lat else 0
    print(f"== W-AH 判据③统计（since {since}）==")
    print(f"LLM 分析调用总数: {len(calls)}")
    per_umo = Counter(calls)
    for umo, n in per_umo.most_common():
        print(f"  {umo}: 调用 {n} | 参与决策 {decide_part.get(umo, 0)} | 不参与 {decide_skip.get(umo, 0)}")
    print(f"策略分布: {dict(strategies) or '{}'}")
    if topics:
        print("话题 top5:", topics.most_common(5))
    print(f"分析延迟(n={len(lat)}): 平均 {sum(lat)/len(lat):.1f}s | p50 {pct(0.5):.1f}s | p95 {pct(0.95):.1f}s" if lat else "分析延迟: 无样本")
    print(f"AngelHeart 相关错误: {len(errors)}")
    for e in errors[:5]:
        print(f"  {e}")


if __name__ == "__main__":
    main()
