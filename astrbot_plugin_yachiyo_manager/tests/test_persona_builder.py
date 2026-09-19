"""W3 台词分区选区测试（persona_builder v2.5）
数据源=真实编译产物 persona/out/tone_zones.json（数据驱动，不 mock 台词）。
"""
import json
from pathlib import Path

import pytest

from astrbot_plugin_yachiyo_manager.utils.persona_builder import PersonaBuilder

ROOT = Path(__file__).parent.parent.parent
TZ_PATH = ROOT / "persona" / "out" / "tone_zones.json"

STATE = {"relationship": "stranger", "mood": "happy",
         "nickname": "", "pinned_facts": []}


def _builder(rel: str = "stranger", tone_zones: dict = None) -> tuple[PersonaBuilder, str]:
    tz = tone_zones if tone_zones is not None else json.loads(
        TZ_PATH.read_text(encoding="utf-8-sig"))
    b = PersonaBuilder(persona_enabled=True, tone_zones=tz)
    state = dict(STATE, relationship=rel)
    return b, b.assemble(user_state=state, time_ctx="测试时段", is_group=False)


def _tone_block(text: str) -> str:
    for part in text.split("\n\n"):
        if part.startswith("[台词示范"):
            return part
    return ""


def _quotes(block: str) -> list[str]:
    import re
    # 只抓行首台词「…」（语境列里的嵌套引号不算）
    return re.findall(r"^- 「([^」]+)」（", block, re.M)


class TestToneSection:
    def test_no_tone_zones_falls_back(self):
        b = PersonaBuilder(persona_enabled=True, tone_zones=None)
        text = b.assemble(user_state=dict(STATE), time_ctx="t")
        assert "[台词示范" not in text
        assert "[场景]" in text and "[约束]" in text  # 其余结构不受影响

    def test_stranger_gets_yingye_only(self):
        _, text = _builder("stranger")
        block = _tone_block(text)
        quotes = _quotes(block)
        yingye = {it["quote"] for it in json.loads(
            TZ_PATH.read_text(encoding="utf-8-sig"))["zones"]["营业"]}
        assert quotes and set(quotes) <= yingye

    def test_familiar_gets_yingye_plus_wenrou(self):
        tz = json.loads(TZ_PATH.read_text(encoding="utf-8-sig"))
        _, text = _builder("familiar")
        quotes = set(_quotes(_tone_block(text)))
        wenrou = {it["quote"] for it in tz["zones"]["温柔"]}
        assert quotes & wenrou  # 混入温柔区

    def test_intimate_all_zones_no_cross_zone_dup(self):
        _, text = _builder("intimate")
        quotes = _quotes(_tone_block(text))
        assert len(quotes) == len(set(quotes))  # 跨区字面重复句只保留一次
        tz = json.loads(TZ_PATH.read_text(encoding="utf-8-sig"))
        assert len(quotes) == (  # 全库 21 - 协议采样 2 - 跨区重复 1 = 18
            sum(len(v) for v in tz["zones"].values())
            - sum(len(v) for v in tz["native_picks"].values())
            - 1
        )

    def test_native_picks_excluded(self):
        tz = json.loads(TZ_PATH.read_text(encoding="utf-8-sig"))
        native = {it["quote"] for z, ids in tz["native_picks"].items()
                  for it in tz["zones"][z] if it["id"] in ids}
        _, text = _builder("intimate")
        assert native and not (set(_quotes(_tone_block(text))) & native)

    def test_group_caps_three_per_zone(self):
        b = PersonaBuilder(persona_enabled=True, tone_zones=json.loads(
            TZ_PATH.read_text(encoding="utf-8-sig")))
        text = b.assemble(user_state=dict(STATE, relationship="intimate"),
                          time_ctx="t", is_group=True)
        tz = json.loads(TZ_PATH.read_text(encoding="utf-8-sig"))
        quotes = _quotes(_tone_block(text))
        # 群聊每区上限 3：营业前3去协议采样(2)剩2 + 温柔3 + 腹黑3 = 8
        # （跨区重复句在本档不同时出现：温柔#5/腹黑#6 不在前3）
        assert len(quotes) == 8

    def test_assemble_block_order(self):
        _, text = _builder("familiar")
        i_scene = text.index("[场景]")
        i_tone = text.index("[台词示范")
        i_time = text.index("[时间]")
        i_user = text.index("[关于神明]")
        i_guard = text.index("[约束]")
        assert i_scene < i_tone < i_time < i_user < i_guard
