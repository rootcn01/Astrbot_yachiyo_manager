# astrbot_plugin_yachiyo_manager

月见八千代管理插件 —— LifeOS 的移动端接入层。八千代通过微信/QQ 提供自然语言记账、汇报、待办、提醒、查询；深度处理由 Claude Code 桌面端完成。

## 架构（v2.4 起）

```
静态人格协议 → AstrBot 原生人格「月见八千代」（data_v4.db，由 Yachiyo_Project/persona/ 编译分发）
动态上下文   → 本插件 inject_persona（on_llm_request priority=100，追加式）
               [场景](对应红线矩阵行) + [时间] + [关于神明](关系/心情/昵称/置顶事实)
               + [回忆涌现](LTM 转投) + [约束]；owner 追加 [Life OS 上下文]
世界观资料   → 知识库「Yachiyo_Project」（agentic 检索）
工具层       → 10 个 @llm_tool（全局注册，默认聊天流可调用）
```

人格唯一编辑点 = 仓库根 `persona/` 八模块；`build_persona.py` 编译产出到 `persona/out/`；**本插件不再持有静态人格文本**（persona_builder 只做动态块）。

## LLM 工具（@llm_tool，全局，共 10 个）

| 工具 | 作用 | 权限 |
|---|---|---|
| `record_expense` | 记账 → LifeOS `finance/expense-log.md`，返回今日餐饮预算 | owner |
| `record_note` | 待办→Google Tasks（失败降级 inbox）；灵感/知识→inbox.md | owner |
| `record_food` | 记饮食，按时间推断餐型 → inbox | owner |
| `record_checkin` | 每日状态汇报（精力/情绪/焦虑 1-10，BARS 锚点评分） | owner |
| `get_status` | 今日计划+周统计+预算+复测日期总览 | owner |
| `get_debt` | 债务清单（finance/CLAUDE.md 解析） | owner |
| `set_reminder` / `cancel_reminder` | FUSHI 定时提醒（1-1440 分钟） | 白名单 |
| `list_tasks` / `complete_task` | 查看某日待办+日历 / 模糊匹配完成任务 | owner |

## 命令（确定性通道，不经 LLM）

| 命令 | 描述 |
|------|------|
| `yachiyo_fushi_reminder <分钟> <内容> [normal\|urgent]` | FUSHI 闹钟（白名单） |
| `yachiyo_cancel [task_id]` | 取消/列出提醒 |
| `yachiyo_whitelist_add / _remove / _status` | QQ 白名单管理 |
| `yachiyo_test_plan / _cron` | owner 手动触发早晚 push 链路（调试） |

## 目录结构

```
astrbot_plugin_yachiyo_manager/
├── main.py                        # Star 主类：10 llm_tool + 7 命令 + inject_persona
├── metadata.yaml / _conf_schema.json / requirements.txt
├── utils/
│   ├── persona_builder.py         # 纯动态上下文块（场景/时间/关系/记忆/约束）
│   ├── reminder_manager.py        # asyncio 调度 + KV 持久化 + 重启恢复
│   ├── platform_adapter.py        # QQ/微信平台判定
│   ├── napcat_client.py           # NapCat HTTP 客户端（QQ TTS；需 napcat 开 HTTP）
│   ├── proactive_scheduler.py     # 早晚 cron push（chronotype 映射）
│   ├── google_integration.py      # Google Tasks/Calendar REST + OAuth 刷新
│   └── life_os/                   # LifeOS 数据层：dashboard 解析/支出/汇报/规划/git 同步
└── tests/test_reminder.py         # ReminderManager 单测
```

## 配置要点

| 配置项 | 说明 |
|---|---|
| `futureplan_repo_path` | LifeOS 仓库路径（默认 /AstrBot/data/Futureplan），写后 git 自动同步 |
| `chronotype` | night_heavy → 早晚 push 13:00/23:00；normal → 08:00/22:00 |
| `planning_provider_id` | 早晚规划用的 LLM provider |
| `google_tasks_enabled / google_calendar_enabled` | Google 集成开关（OAuth token 在 data/plugin_data/yachiyo_manager/token.json） |
| `napcat_api_url` | NapCat HTTP（napcat 未开 HTTP 时 QQ TTS 静默降级） |

## 安装 / 更新

1. `python build_zip.py`（仓库根 astrbot_plugin_yachiyo_manager/ 下）生成 zip，或直接 scp 目录覆盖 `data/plugins/astrbot_plugin_yachiyo_manager/`
2. 重启 AstrBot 或 WebUI reload 插件
3. 配置项在 WebUI 插件配置页

## 注意事项

- **注入顺序**：on_llm_request priority 为降序（数值大先执行），本插件(100)先于 angel_heart(50/0)；最终 system_prompt = 原生协议 → 本插件动态块 → scene_prompt
- **隐私**：LifeOS 上下文仅 owner 私聊注入；群聊非 @ 消息不注入人格块
- **白名单**：微信个人号直接放行；QQ 走白名单（`yachiyo_whitelist_add`）
- 提醒持久化在 KV Store，重启自动恢复

## License

MIT License
