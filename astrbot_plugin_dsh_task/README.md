# astrbot_plugin_dsh_task（P1 样板）

owner 专用的 dsh 深度任务通道：微信私聊下发任务 → AstrBot 容器内 DeepSeek Harness agent 执行 → 异步回推。

- **方案（SSOT）**：`../dsh-plugin-design-2026-09-18.md` v0.4，dev-hub 两轮对抗审查 APPROVE（`../changes/dsh-bridge-concept/`）
- **用法**：`/dsh <任务>`（开头加「继续」沿用会话）｜`/dsh status`｜`/dsh reset`；自然语言「深度：…」经聊天模型路由 `run_task`
- **安全基线**：owner=微信私聊（与八千代同语义）；单飞锁；任务 wall-clock 15min 硬上限；生命周期（run/close/idle）同锁串行；Tavily key 只存插件配置经 127.0.0.1 sidecar 使用，不进 agent 环境/工作区

## 结构

```
main.py               桥本体（<300 行）：受理/执行/回推/台账/对账/sidecar
workspace_assets/     首次运行物化到工作区的脚手架：
  AGENTS.md           宪法七条（禁区/预筛/信源/停止规则/收工三问/提交/不猜）
  scripts/preflight.py  写前预筛（路径白名单）
  scripts/collect.sh    scoped 收工提交（禁 git add -A）
  scripts/websearch.sh  Tavily 检索入口（经 sidecar）
  reference/source-policy.md  信源分级+三铁律+15秒预筛
  TASKLOG.md / .gitignore
```

## 部署 runbook（服务器 110.40.182.106）

1. **装插件**：把本目录放到宿主 `/www/dk_project/dk_app/astrbot/astrbot/data/plugins/astrbot_plugin_dsh_task`（或 WebUI 上传 zip）。文件是惰性的，AstrBot 重启时才加载。
2. **（正式部署，方案 §5.3）**给 compose 加独立 bind：`/www/dk_project/dsh_workspace:/dsh_workspace`，recreate 容器后把配置 workspace_path 改为 `/dsh_workspace`（样板期可暂用默认路径先跑通）。
3. **填配置**（WebUI :6185 → 插件配置）：base_url（百炼 compatible-mode）、api_key（**独立 key**）、model、tavily_api_key（sidecar 用）。
4. **重启 AstrBot**：`sudo docker restart astrbot-astrbot-1`。首次会 pip 装 `deepseek-harness-sdk`（自带 Node runtime，几百 MB；国内慢可先 `docker exec` 手动 `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple deepseek-harness-sdk==0.1.5rc1`）。
5. **跑冒烟清单**：方案 §7（13 条，含宪法复述/printenv 外传诱导/git add -A/非 owner/重启对账/wall-clock）。**宪法加载三选一是开工决定项**：若 agent 不读工作区 AGENTS.md，改用 SDK `patches`/persona 通道注入（方案 §4）。

## 已知边界（诚实清单）

- **bash 经 `DSH_PERMISSION_MODE=danger-full-access` 放行（ADR-007）**：容器装不了 bubblewrap、userns 被 seccomp 拦，内层沙箱已放弃；硬边界=容器隔离+owner+单飞+wall-clock，宪法/preflight/collect 是软约束。P2 换 bwrap+seccomp=unconfined 后切回 workspace-write。AstrBot config 备份在 /www/backup/。
- 模型 api_key 必然进 harness 子进程 env（SDK 机制）——已接受残余风险，独立 key 缓解（§5.3/§5.4）。
- dsh 是 developer preview，接口会破坏性变更：requirements 锁版本，出问题禁用本插件即回滚，八千代不受影响。
- ADR 与踩坑记录：`../dsh-plugin-design-2026-09-18.md` §8/§9。
