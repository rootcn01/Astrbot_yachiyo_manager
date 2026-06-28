# astrbot_plugin_yachiyo_manager

月见八千代管理插件 - 为 AstrBot 提供 FUSHI 定时提醒、多模态通知等专属功能。

## 功能特性

- **FUSHI 定时提醒** - 设置定时闹钟，支持普通提醒和紧急提醒两种模式
- **多模态通知** - QQ 群聊支持 TTS 语音 + 文字双重提醒，私聊/微信 fallback 到文字轰炸
- **白名单控制** - 支持 QQ/微信平台的白名单管理，管理员可动态添加/移除
- **人格化消息** - 提醒内容符合月见八千代的角色语气（温柔但略带腹黑）
- **可视化配置** - 支持 AstrBot 管理面板直接配置各项参数

## 目录结构

```
astrbot_plugin_yachiyo_manager/
├── __init__.py                    # 命名空间包声明
├── main.py                        # Star 主类 + 命令/LLM handlers
├── metadata.yaml                  # 插件元数据
├── _conf_schema.json              # 可视化配置 schema
├── requirements.txt               # 依赖声明
├── core/
│   └── persona_builder.py         # 角色 persona 构建（惰性加载 output_md/ 设定）
├── tools/
│   └── reminder_tools.py          # LLM 工具注册（set/cancel/list 提醒）
├── output_md/                     # 角色设定文件（Yachiyo_Tone_FewShots.md 等）
├── utils/
│   ├── reminder_manager.py        # asyncio 调度 + KV Store 持久化 + 重启恢复
│   ├── platform_adapter.py        # 平台适配器（QQ/微信）
│   └── napcat_client.py           # NapCat API 客户端
└── tests/
    └── test_reminder.py           # 单元测试
```

## 命令列表

| 命令 | 描述 | 参数 |
|------|------|------|
| `yachiyo_fushi_reminder` | 设定 FUSHI 闹钟 | `delay_minutes` - 延迟分钟数<br>`message` - 提醒内容<br>`alert_type` - 提醒类型 (normal/urgent) |
| `yachiyo_cancel` | 取消提醒 | `task_id` - 任务ID（不填则列出全部） |
| `yachiyo` | 自然语言对话入口 | `message` - 消息内容（如"5分钟后提醒我喝水"） |
| `yachiyo_whitelist_add` | 添加白名单 | `qq_id` - QQ 号 |
| `yachiyo_whitelist_remove` | 移除白名单 | `qq_id` - QQ 号 |
| `yachiyo_whitelist_status` | 查看白名单状态 | - |

## 安装方式

1. 将 `astrbot_plugin_yachiyo_manager` 目录复制到 AstrBot 的 `data/plugins/` 目录下
2. 在 AstrBot 管理面板中 Reload 插件
3. 在管理面板中配置插件参数（ NapCat API 地址、人格化 Prompt 等）

## 快速上手

1. **添加白名单** — 在QQ私聊中发送：`/yachiyo_whitelist_add <你的QQ号>`
2. **测试提醒** — 发送：`/yachiyo_fushi_reminder 1 喝水测试`
3. **AI对话** — 发送：`/yachiyo 半小时后提醒我吃药`（需配置LLM）

## 常见场景

| 场景 | 命令 |
|------|------|
| 定时喝水 | `/yachiyo_fushi_reminder 30 该喝水了` |
| 紧急会议提醒 | `/yachiyo_fushi_reminder 10 会议开始了 urgent` |
| 午休叫醒 | `/yachiyo_fushi_reminder 30 午休结束 urgent` |
| 自然语言 | `/yachiyo 20分钟后提醒我站起来活动` |
| 查看提醒 | `/yachiyo_cancel`（不带参数=列出） |
| 取消提醒 | `/yachiyo_cancel <任务ID前8位>` |

## 配置说明

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `default_alert_type` | 下拉 | normal | 默认提醒类型。normal=温柔文字，urgent=紧急TTS+文字 |
| `normal_message_template` | 文本 | 【FUSHI 闹钟】... | 普通提醒模板，`{message}` 为内容占位符 |
| `urgent_enhancement_template` | 文本 | 神明大人！... | 紧急提醒模板（TTS失败时使用） |
| `napcat_api_url` | 文本 | http://localhost:3000 | NapCat HTTP 地址，云服务器需改为实际IP |
| `napcat_api_token` | 文本 | (空) | NapCat 令牌，一般留空 |
| `persona_enabled` | 开关 | true | 是否让AI以八千代身份回复 |
| `qq_whitelist_enabled` | 开关 | true | 是否仅白名单QQ号可用 |

## 使用示例

```
# 设置 5 分钟后提醒喝水（普通模式）
/yachiyo_fushi_reminder 5 该喝水了 normal

# 设置 10 分钟后提醒开会（紧急模式，QQ 群聊会发 TTS）
/yachiyo_fushi_reminder 10 该开会了 urgent

# 添加白名单（管理员）
/yachiyo_whitelist_add 123456

# 移除白名单（管理员）
/yachiyo_whitelist_remove 123456
```

## 平台差异

| 平台 | Normal 提醒 | Urgent 提醒 |
|------|-------------|-------------|
| QQ 群聊 | 文字模板 | TTS 语音 + 文字轰炸 |
| QQ 私聊 | 文字模板 | 文字轰炸 |
| 微信 | 文字模板 | 文字轰炸 |

## 依赖

- AstrBot >= 4.0.0
- httpx (用于 NapCat API 调用)
- NapCat 扩展（仅 QQ 群聊 TTS 功能需要）

## 注意事项

1. **定时任务持久化** - 提醒数据存储在 KV Store 中，AstrBot 重启后自动恢复未过期的提醒
2. **角色人格注入** - 通过 @on_llm_request 追加模式注入八千代角色上下文，与 AngelHeart 等插件共存
3. **白名单默认开启** - QQ 平台白名单默认开启，需管理员添加用户后才能使用
4. **LLM 工具调用** - 通过 `/yachiyo <消息>` 可用自然语言设置/取消/查看提醒，LLM 自动调用对应的 Function Tool

## 问题排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 命令无响应 | 未加入白名单 | 管理员用 `/yachiyo_whitelist_add` 添加 |
| LLM对话无回复 | 未配置LLM或provider不可用 | 换用命令通道 `/yachiyo_fushi_reminder` |
| TTS语音没发 | 非QQ群聊 / NapCat未配置 | TTS仅QQ群聊支持，检查 napcat_api_url |
| 重启后提醒丢失 | KV Store异常 | 查看AstrBot日志 |
| 角色人格没生效 | persona_enabled 关闭 | WebUI中检查开关 |

## 角色设定

月见八千代是 8000 岁的月读空间管理员，语气温柔但略带腹黑，会用「神明大人」称呼用户。

## License

MIT License
