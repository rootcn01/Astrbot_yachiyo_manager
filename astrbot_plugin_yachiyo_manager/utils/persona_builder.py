"""八千代 Persona 构建器 — 纯动态上下文层（v2.5 · W3 台词选区）

静态人格协议（身份/语言指纹/红线矩阵/防线/台词示范）自 W2 起住在
AstrBot 原生人格「月见八千代」（data_v4.db，由 Yachiyo_Project/persona/
编译分发，见 persona/out/native_persona_protocol.md）。本模块只负责
每轮变化的动态上下文：场景（对应红线矩阵行）、时段、用户关系、记忆转投、
台词分区选区（W3：按关系等级替换式注入，数据源 persona/out/tone_zones.json，
与 persona/ 原稿经编译同步，禁止手改插件内嵌副本）。

铁律：本模块不得包含静态人格设定或字数数字——数字唯一出处是
persona/10-voice.md 的红线矩阵（经原生协议注入）。
"""


class PersonaBuilder:
    def __init__(self, persona_enabled: bool, tone_zones: dict = None):
        self.persona_enabled = persona_enabled
        # None/缺文件 = 选区注入关闭，回退纯协议采样（W2.6 行为）
        self.tone_zones = tone_zones

    def assemble(self, *, user_state: dict = None, time_ctx: str = "",
                 ltm_ctx: str = "", is_group: bool = False) -> str:
        """组装动态上下文块（追加到 req.system_prompt，位于原生协议之后）"""
        parts = [self._build_scene(is_group)]
        if user_state:
            rel = user_state.get("relationship", "stranger")
            tone = self._build_tone_section(rel, is_group)
            if tone:
                parts.append(tone)
        if time_ctx:
            parts.append(f"[时间] {time_ctx}")
        if user_state:
            parts.append(self._build_user_section(user_state))
        if ltm_ctx:
            parts.append(f"[回忆涌现]\n{ltm_ctx}")
        parts.append("[约束] 永远以八千代身份回复，不跳出角色。")
        return "\n\n".join(parts)

    def _build_scene(self, is_group: bool) -> str:
        if is_group:
            return "[场景] 群聊——按红线矩阵「群聊」行执行。"
        return ("[场景] 私聊——按红线矩阵「私聊·日常」行执行；"
                "对方发长文、点名深谈或情绪低落时，切换「私聊·深谈」行。")

    def _build_tone_section(self, rel: str, is_group: bool) -> str:
        """台词分区选区（20 模块预埋规则）：
        stranger/acquaintance→营业区；familiar→+温柔；close/intimate→三区全开。
        替换式=按关系给一档，不累积全库。协议已静态采样的条目不重复注入；
        跨区字面重复句只保留首次出现。群聊场景每区上限 3 条（短回预算敏感）。
        """
        if not self.tone_zones:
            return ""
        tiers = self.tone_zones.get("tiers", {})
        zones = self.tone_zones.get("zones", {})
        zone_names = tiers.get(rel) or tiers.get("stranger") or ["营业"]
        # 协议静态已采样的条目（按 id 对照）：动态选区不重复注入
        native_quotes = set()
        for zname, ids in self.tone_zones.get("native_picks", {}).items():
            for it in zones.get(zname, []):
                if it.get("id") in ids:
                    native_quotes.add(it["quote"])
        lines, seen = [], set()
        for zname in zone_names:
            items = zones.get(zname, [])
            if is_group:
                items = items[:3]
            for it in items:
                q = it["quote"]
                if q in native_quotes or q in seen:
                    continue
                seen.add(q)
                lines.append(f"- 「{q}」（{it['ctx']}）")
        if not lines:
            return ""
        return "[台词示范·校准用，禁止逐字复读]\n" + "\n".join(lines)

    def _build_user_section(self, s: dict) -> str:
        rel = s.get("relationship", "stranger")
        mood = s.get("mood", "neutral")
        rel_cn = {"stranger": "陌生人", "acquaintance": "认识的人",
                  "familiar": "熟悉的神明大人", "close": "亲密的神明大人",
                  "intimate": "最重要的神明大人（彩叶位）"}.get(rel, "用户")
        mood_cn = {"neutral": "平静", "happy": "开心",
                   "slightly_worried": "略担心", "missing_you": "想念"}.get(mood, "平静")
        text = f"[关于神明] {rel_cn}。心情：{mood_cn}。"
        if s.get("nickname"):
            text += f"\n称呼TA：{s['nickname']}。"
        if s.get("pinned_facts"):
            text += f"\n关于TA：{'、'.join(s['pinned_facts'])}。"
        return text
