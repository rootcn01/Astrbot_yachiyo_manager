"""汇报解析 — checkin 数据验证和格式化"""
from datetime import datetime


def format_checkin_line(energy: int, mood: int, anxiety: int,
                        creative: str, detachment: str, l1: str,
                        overtime: str = "❌", note: str = "") -> str:
    """格式化 checkin 条目，写入 inbox.md。"""
    today = datetime.now().strftime("%Y-%m-%d")
    parts = [f"精力{energy}", f"情绪{mood}", f"焦虑{anxiety}",
             f"加班{overtime}", f"创作{creative}", f"脱离{detachment}", f"L1{l1}"]
    line = "checkin " + " ".join(parts)
    if note:
        line += f"。{note}"
    line += f"  # {today}"
    return line


def validate_checkin_fields(energy: int, mood: int, anxiety: int) -> dict:
    """验证 checkin 字段，返回警告列表。"""
    warnings = []
    fields = {"精力": energy, "情绪": mood, "焦虑": anxiety}
    for name, val in fields.items():
        if val == -1:
            continue  # 用户没提供，LLM 标记缺失
        if not (1 <= val <= 10):
            warnings.append(f"{name}={val} 超出 1-10 范围")
    return {"warnings": warnings, "has_data": any(v != -1 for v in fields.values())}
