# astrbot_plugin_yachiyo_manager

月见八千代管理插件 - 为 AstrBot 提供 FUSHI 定时提醒、多模态通知等专属功能。

## 功能特性

- **FUSHI 定时提醒** - 设置定时闹钟，支持普通提醒和紧急提醒两种模式
- **多模态通知** - QQ 群聊支持 TTS 语音 + 文字双重提醒，私聊/微信 fallback 到文字轰炸
- **语音模式切换** - 用户可独立开启/关闭语音模式
- **白名单控制** - 支持 QQ/微信平台的白名单管理，管理员可动态添加/移除
- **人格化消息** - 提醒内容符合月见八千代的角色语气（温柔但略带腹黑）
- **可视化配置** - 支持 AstrBot 管理面板直接配置各项参数

## 目录结构

```
astrbot_plugin_yachiyo_manager/
├── __init__.py                    # 命名空间包声明
├── main.py                        # Star 主类 + 命令 handlers
├── metadata.yaml                  # 插件元数据
├── _conf_schema.json              # 可视化配置 schema
└── utils/
    ├── reminder_manager.py        # 定时任务管理
    ├── platform_adapter.py        # 平台适配器（QQ/微信）
    ├── personality.py             # 人格化消息处理
    └── napcat_client.py           # NapCat API 客户端
```

## 命令列表

| 命令 | 描述 | 参数 |
|------|------|------|
| `yachiyo_fushi_reminder` | 设定 FUSHI 闹钟 | `delay_minutes` - 延迟分钟数<br>`message` - 提醒内容<br>`alert_type` - 提醒类型 (normal/urgent) |
| `yachiyo_voice_mode` | 切换语音模式 | `enable` - true/false |
| `yachiyo_whitelist_add` | 添加白名单（管理员） | `qq_id` - QQ 号 |
| `yachiyo_whitelist_remove` | 移除白名单（管理员） | `qq_id` - QQ 号 |
| `yachiyo_whitelist_status` | 查看白名单状态（管理员） | - |

## 安装方式

1. 将 `astrbot_plugin_yachiyo_manager` 目录复制到 AstrBot 的 `data/plugins/` 目录下
2. 在 AstrBot 管理面板中 Reload 插件
3. 在管理面板中配置插件参数（ NapCat API 地址、人格化 Prompt 等）

## 配置说明

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `default_alert_type` | select | normal | 默认提醒类型 |
| `voice_character` | str | yachiyo | TTS 语音角色名称 |
| `qq_whitelist_enabled` | boolean | true | QQ 白名单开关 |
| `wechat_whitelist_enabled` | boolean | false | 微信白名单开关 |
| `napcat_api_url` | str | http://localhost:3000 | NapCat HTTP API 地址 |
| `napcat_api_token` | str | - | NapCat API Token |
| `personality_prompt` | text | - | 人格化用 LLM Prompt |
| `normal_message_template` | str | 【FUSHI 闹钟】叮铃铃~ 神明大人，{message} | 普通提醒消息模板 |
| `urgent_enhancement_template` | str | 神明大人！{message}！快醒醒！ | Urgent 增强模板 |

## 使用示例

```
# 设置 5 分钟后提醒喝水（普通模式）
/yachiyo_fushi_reminder 5 该喝水了 normal

# 设置 10 分钟后提醒开会（紧急模式，QQ 群聊会发 TTS）
/yachiyo_fushi_reminder 10 该开会了 urgent

# 开启语音模式
/yachiyo_voice_mode true

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

1. **定时任务持久化** - AstrBot 重启后正在运行的定时任务会丢失，这是 asyncio.create_task 的固有限制
2. **LLM 人格化** - 当前版本使用模板进行人格化，LLM 接口预留待后续实现
3. **白名单默认开启** - QQ 平台白名单默认开启，需要管理员添加用户后才能使用

## 角色设定

月见八千代是 8000 岁的月读空间管理员，语气温柔但略带腹黑，会用「神明大人」称呼用户。

## License

MIT License
