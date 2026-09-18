"""八千代 Persona 构建器 — 纯动态上下文层（v2.4）

静态人格协议（身份/语言指纹/红线矩阵/防线/台词示范）自 W2 起住在
AstrBot 原生人格「月见八千代」（data_v4.db，由 Yachiyo_Project/persona/
编译分发，见 persona/out/native_persona_protocol.md）。本模块只负责
每轮变化的动态上下文：场景（对应红线矩阵行）、时段、用户关系、记忆转投。

铁律：本模块不得包含静态人格设定或字数数字——数字唯一出处是
persona/10-voice.md 的红线矩阵（经原生协议注入）。
"""


class PersonaBuilder:
    def __init__(self, persona_enabled: bool):
        self.persona_enabled = persona_enabled

    def assemble(self, *, user_state: dict = None, time_ctx: str = "",
                 ltm_ctx: str = "", is_group: bool = False) -> str:
        """组装动态上下文块（追加到 req.system_prompt，位于原生协议之后）"""
        parts = [self._build_scene(is_group)]
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
