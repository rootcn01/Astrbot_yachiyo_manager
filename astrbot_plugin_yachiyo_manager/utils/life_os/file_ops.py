"""文件操作 — 读写 Futureplan 数据仓库的 markdown 文件 + 异步 git 同步"""
import asyncio
import os
from datetime import datetime
from pathlib import Path


def ensure_repo_path(config: dict) -> str:
    """从插件配置中获取 Futureplan 仓库路径。"""
    path = config.get("futureplan_repo_path", "/data/Futureplan")
    if not os.path.isdir(path):
        raise FileNotFoundError(f"Futureplan 仓库路径不存在: {path}")
    return path


def read_file(repo_path: str, relative_path: str) -> str:
    """读取仓库中的文件，返回全部文本。文件不存在则返回空字符串。"""
    full = os.path.join(repo_path, relative_path)
    if not os.path.isfile(full):
        return ""
    with open(full, "r", encoding="utf-8") as f:
        return f.read()


def append_to_file(repo_path: str, relative_path: str, line: str):
    """向文件末尾追加一行。"""
    full = os.path.join(repo_path, relative_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def append_to_section(repo_path: str, relative_path: str,
                      section_marker: str, line: str):
    """在指定 markdown 区块后追加一行。

    找到 `section_marker` 所在行，在下一行插入 `line`。
    如果找不到标记，则追加到文件末尾。
    """
    full = os.path.join(repo_path, relative_path)
    if not os.path.isfile(full):
        append_to_file(repo_path, relative_path, line)
        return

    with open(full, "r", encoding="utf-8") as f:
        content = f.read()

    if section_marker in content:
        idx = content.index(section_marker) + len(section_marker)
        # 跳到下一行开头
        next_nl = content.index("\n", idx)
        insert_pos = next_nl + 1
        content = content[:insert_pos] + line + "\n" + content[insert_pos:]
    else:
        content = content.rstrip("\n") + "\n" + line + "\n"

    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def append_to_inbox(repo_path: str, line: str):
    """向 inbox.md 的「待处理」区块追加一条记录。"""
    append_to_section(repo_path, "inbox.md", "## 待处理", line)


def append_expense(repo_path: str, amount: float, category: str, desc: str):
    """向 expense-log.md 追加一条支出记录（表格行格式）。"""
    today = datetime.now().strftime("%m/%d")
    emoji_cat = _category_emoji(category)
    row = f"| {today} | {amount:.0f} | 支出 | {emoji_cat}{category} | {desc} | |"
    append_to_file(repo_path, "finance/expense-log.md", row)


def _category_emoji(cat: str) -> str:
    mapping = {
        "餐饮": "🍜", "交通": "🚇", "购物": "🛒",
        "娱乐": "🎮", "健康": "💊", "副业成本": "🔧",
        "其他": "🎁",
    }
    return mapping.get(cat, "")


# ═══════════════════════════════════════════════════════════
#  Git 异步同步
# ═══════════════════════════════════════════════════════════

async def _run_git(*args, cwd: str) -> int:
    """执行 git 命令，返回退出码。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return await proc.wait()
    except Exception:
        return 1  # git 不存在或网络不可达


async def sync_git(repo_path: str):
    """异步执行 git pull → add → commit → push。

    失败不抛异常——文件已经写入磁盘，下次操作重试即可。
    """
    # 1. pull
    await _run_git("git", "pull", "--no-edit", "origin", "master", cwd=repo_path)

    # 2. add
    await _run_git("git", "add", "-A", cwd=repo_path)

    # 3. 有变更才提交
    rc = await _run_git("git", "diff", "--cached", "--quiet", cwd=repo_path)
    if rc != 0:
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        await _run_git("git", "commit", "-m",
                       f"phone: auto-sync {ts}", cwd=repo_path)
        await _run_git("git", "push", "origin", "master", cwd=repo_path)
