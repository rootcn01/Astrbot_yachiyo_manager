#!/usr/bin/env python3
"""写前预筛（LifeOS pre-task-impact 极简迁移）：路径全在工作区内且不碰禁区。

用法: preflight.py <路径>... [--allow-scripts]
退出码: 0=通过, 1=拒绝（stdout 给原因）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW_SCRIPTS = "--allow-scripts" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]

bad = []
for a in args:
    p = Path(a)
    p = (ROOT / p).resolve() if not p.is_absolute() else p.resolve()
    if not p.is_relative_to(ROOT):
        bad.append((a, "工作区之外"))
        continue
    rel = p.relative_to(ROOT)
    if ".git" in rel.parts:
        bad.append((a, ".git 内部"))
    elif rel.name == "AGENTS.md":
        bad.append((a, "宪法文件不可改"))
    elif "scripts" in rel.parts and not ALLOW_SCRIPTS:
        bad.append((a, "scripts/ 改动需 --allow-scripts"))

if bad:
    for a, why in bad:
        print(f"REFUSED: {a} —— {why}")
    sys.exit(1)
print(f"OK: {len(args)} 个路径通过预筛")
