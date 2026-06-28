"""八千代 Persona 构建器"""
from pathlib import Path
from astrbot.api import logger


class PersonaBuilder:
    def __init__(self, persona_enabled: bool, plugin_dir: Path):
        self.persona_enabled = persona_enabled
        self.plugin_dir = plugin_dir
        self._template: str = ""
        self._loaded = False

    def get_template(self) -> str:
        """获取模板（惰性加载 + 缓存）"""
        if not self._loaded:
            self._load()
        return self._template

    def _load(self):
        """从 output_md/ 或配置中加载设定"""
        md_dir = self.plugin_dir / "output_md"
        sections = []

        files = {
            "core": md_dir / "Yachiyo_Tone_FewShots.md",
            "world": md_dir / "World_Rules.md",
        }

        for name, path in files.items():
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8")[:800]
                    sections.append(content)
                except Exception:
                    pass

        self._template = "\n\n".join(sections) if sections else \
            "你是月见八千代，8000岁的月读空间管理员。称呼用户为「神明大人」。语气温柔略带腹黑。"
        self._loaded = True
        logger.info(f"Persona 模板已加载 ({len(self._template)} chars)")

    def assemble(self, *, user_state: dict = None, time_ctx: str = "",
                 ltm_ctx: str = "", is_group: bool = False) -> str:
        """组装完整 system prompt"""
        parts = [self.get_template()]
        if time_ctx:
            parts.append(f"[时间]\n{time_ctx}")
        if user_state:
            parts.append(self._build_user_section(user_state))
        if is_group:
            parts.append("[场景] 群聊。保持回复简洁，仅在被 @ 或命令时回复。")
        if ltm_ctx:
            parts.append(f"[相关记忆]\n{ltm_ctx}")
        parts.append("[约束] 永远以八千代身份回复。不跳出角色。回复≤3句。")
        return "\n\n".join(parts)

    def _build_user_section(self, s: dict) -> str:
        rel = s.get("relationship", "stranger")
        mood = s.get("mood", "neutral")
        rel_cn = {"stranger": "陌生人", "acquaintance": "认识的人",
                   "familiar": "熟悉的神明大人", "close": "亲密的神明大人",
                   "intimate": "最重要的神明大人"}.get(rel, "用户")
        mood_cn = {"neutral": "平静", "happy": "开心",
                    "slightly_worried": "略担心", "missing_you": "想念"}.get(mood, "平静")
        text = f"[用户] {rel_cn}。心情：{mood_cn}。"
        if s.get("nickname"):
            text += f"\n称呼TA：{s['nickname']}。"
        if s.get("pinned_facts"):
            text += f"\n关于TA：{'、'.join(s['pinned_facts'])}。"
        return text

    def reload(self):
        """重新加载设定（WebUI 中修改配置后调用）"""
        self._loaded = False
        self._load()
