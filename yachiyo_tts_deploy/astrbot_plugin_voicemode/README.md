# astrbot_plugin_voicemode

语音模式切换 tiny 插件：通过 `/voicemode` 切换 yachiyo-tts-router 的路由模式并查询状态。

## 安装

1. 把整个 `astrbot_plugin_voicemode/` 目录拷入 AstrBot 的 `data/plugins/` 下；
2. 重启 astrbot（或在 WebUI 插件管理里重载）；
3. 在 WebUI 插件配置中把 `bridge_token` 从占位 `CHANGE_ME` 改为部署令牌（与 router/bridge 侧同值）。

零新增依赖：`requirements.txt` 为空；优先用容器自带的 aiohttp，缺失时自动退化为 asyncio + urllib 线程兜底，请求超时均为 5 秒。

## 命令

| 命令 | 作用 |
| --- | --- |
| `/voicemode` | 等同 `status`，查询当前状态 |
| `/voicemode status` | 当前模式 / bridge 状态 / 今日两引擎计数 / 判忙原因 / 最近一次回落时间 |
| `/voicemode auto` | 自动：本地 bridge 就绪走本地，不可用回落云端 |
| `/voicemode local` | 本地强制：仅走本地 bridge，不可用时报错不上云 |
| `/voicemode cloud` | 云端：语音全部走云端官方接口 |

权限门控：发送者 ID 在 `owner_ids`（默认 `1010233339`）或事件管理员字段为真才响应；其余人发送时静默忽略（不回复、不报错）。router 不可达时回复「router 不可达（语音仍走云端直连不受影响）」。

## 与 MiMo TTS 插件的关系

本插件只调用 yachiyo-tts-router 的 `GET /health` 与 `POST /admin/mode` 两个运维端点，用于查看状态和切换路由模式；**不读取、不写入、不修改 MiMo TTS 插件的任何文件与配置**，两者互不依赖、可共存。切换模式改变的是 router 对 TTS 请求的路由决策，MiMo 插件本身无感知。
