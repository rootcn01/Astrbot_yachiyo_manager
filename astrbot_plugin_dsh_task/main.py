"""astrbot_plugin_dsh_task — DSH 任务执行器（P1 样板）

方案：Yachiyo_Project/dsh-plugin-design-2026-09-18.md（v0.4，对抗审查 APPROVE）
桥只做三件事：收任务（owner-only）→ 驱动 deepseek-harness-sdk → 异步回推。
生命周期不变量（方案 §7）：run / close / idle 计时全部串行在同一把 asyncio 锁下。
"""

import asyncio
import json
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote
from urllib.request import Request, urlopen

from astrbot.api import logger, llm_tool
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult, filter
from astrbot.api.star import Context, Star

PLUGIN_DIR = Path(__file__).parent
ASSETS_DIR = PLUGIN_DIR / "workspace_assets"
TASKLOG_NAME = "TASKLOG.md"


class DshTaskPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self._ws = None                      # 工作区 Path（initialize 时定）
        self._harness = None                 # DeepSeekHarness 单例
        self._lock = asyncio.Lock()          # run/close/idle 唯一串行点
        self._idle_task = None
        self._current = None                 # {"id","umo","t0"}
        self._sessions = {}                  # umo -> {"session_id","turns","updated"}
        self._sidecar = None
        self._seq = 0

    # ── 生命周期 ──

    async def initialize(self):
        self._ws = Path(self.config.get("workspace_path", "/AstrBot/data/dsh_workspace"))
        self._init_workspace()
        self._seed_seq()
        await self._load_sessions()
        self._reconcile_tasklog()
        if self.config.get("tavily_api_key"):
            try:
                await self._start_sidecar()
            except Exception as e:
                logger.warning(f"[dsh_task] sidecar 启动失败（websearch 将不可用）：{e}")
        miss = self._missing_config()
        if miss:
            logger.warning(f"[dsh_task] 配置缺 {miss}，插件只挂载、不受理任务")
        logger.info("[dsh_task] DSH 任务执行器已初始化")

    async def terminate(self):
        self._cancel_idle()
        async with self._lock:
            await self._kill_runtime()
        if self._sidecar:
            try:
                self._sidecar.close()
                await self._sidecar.wait_closed()
            except Exception:
                pass

    # ── 工作区脚手架 ──

    def _init_workspace(self):
        self._ws.mkdir(parents=True, exist_ok=True)
        for rel in ("AGENTS.md", TASKLOG_NAME, ".gitignore",
                    "reference/source-policy.md",
                    "scripts/preflight.py", "scripts/collect.sh", "scripts/websearch.sh"):
            src, dst = ASSETS_DIR / rel, self._ws / rel
            if src.exists() and not dst.exists():   # 不覆盖：宪法可被用户手改
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                if dst.suffix == ".sh":
                    dst.chmod(0o755)
        (self._ws / "tasks").mkdir(exist_ok=True)
        (self._ws / "scratch").mkdir(exist_ok=True)
        if not (self._ws / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=self._ws, check=False)
            subprocess.run(["git", "config", "user.email", "dsh-agent@local"], cwd=self._ws, check=False)
            subprocess.run(["git", "config", "user.name", "dsh-agent"], cwd=self._ws, check=False)

    # ── 会话与台账 ──

    async def _load_sessions(self):
        try:
            self._sessions = await self.get_kv_data("sessions", default={}) or {}
        except Exception:
            self._sessions = {}

    async def _save_sessions(self):
        try:
            await self.put_kv_data("sessions", self._sessions)
        except Exception as e:
            logger.warning(f"[dsh_task] 会话持久化失败：{e}")

    async def _tasklog(self, line: str):
        def _w():
            with open(self._ws / TASKLOG_NAME, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {line}\n")
        try:
            await asyncio.to_thread(_w)
        except Exception as e:
            logger.warning(f"[dsh_task] 台账写入失败：{e}")

    def _reconcile_tasklog(self):
        """启动对账（方案 B3）：未收口的 START 主动推中断通知。"""
        p = self._ws / TASKLOG_NAME
        if not p.exists():
            return
        starts, closed = {}, set()
        for ln in p.read_text(encoding="utf-8").splitlines():
            parts = [x.strip() for x in ln.split("|")]
            if len(parts) >= 3 and parts[1] == "START":
                starts[parts[2]] = (parts[3] if len(parts) > 3 else "", parts[0])
            elif len(parts) >= 3 and parts[1] in ("DONE", "FAIL"):
                closed.add(parts[2])
        for tid, (umo, ts) in starts.items():
            if tid not in closed:
                asyncio.create_task(self._interrupt_push(tid, umo, ts))

    async def _interrupt_push(self, tid: str, umo: str, ts: str):
        await asyncio.sleep(15)   # 等平台适配器就绪，避免启动即推被吞
        await self._send(umo, f"⚠️ #{tid} 因插件/容器重启中断（受理于 {ts}）。需要的话请重发任务。")
        await self._tasklog(f"FAIL | {tid} | interrupted-by-restart")

    # ── Tavily sidecar（密钥不进 agent 环境，方案 §5.3）──

    async def _start_sidecar(self):
        port = int(self.config.get("sidecar_port", 18234))
        self._sidecar = await asyncio.start_server(self._handle_search, "127.0.0.1", port)
        logger.info(f"[dsh_task] Tavily sidecar 127.0.0.1:{port}")

    async def _handle_search(self, reader, writer):
        try:
            line = (await reader.readline()).decode("utf-8", "ignore")
            m = re.search(r"GET\s+/search\?(\S+)", line)
            params = parse_qs(m.group(1)) if m else {}
            q = params.get("q", [""])[0]
            n = min(int(params.get("max", ["5"])[0]), 10)
            payload = json.dumps(await asyncio.to_thread(self._tavily_search, q, n),
                                 ensure_ascii=False).encode("utf-8")
        except Exception as e:
            payload = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
        try:
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\n"
                         b"Content-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
            await writer.drain()
        finally:
            writer.close()

    def _tavily_search(self, q: str, n: int) -> dict:
        req = Request("https://api.tavily.com/search",
                      data=json.dumps({"query": q, "max_results": n}).encode(),
                      headers={"Content-Type": "application/json",
                               "Authorization": f"Bearer {self.config['tavily_api_key']}"},
                      method="POST")
        with urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return {"results": [{"title": x.get("title"), "url": x.get("url"),
                             "date": x.get("published_date"),
                             "content": (x.get("content") or "")[:800]}
                            for x in data.get("results", [])]}

    # ── 门禁与配置 ──

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        """与八千代同语义：微信私聊发送者 = owner；群聊与其他平台不可用。"""
        sid = (getattr(event, "session_id", "") or "").lower()
        return "wechat" in sid and getattr(event, "group_id", None) is None

    def _missing_config(self):
        return [k for k in ("base_url", "api_key", "model") if not self.config.get(k)]

    # ── 入口（门禁不变量：三路径同一实现，方案 §3.1）──

    @llm_tool(name="run_task")
    async def run_task(self, event: AstrMessageEvent,
                       task: str, mode: str = "new") -> str:
        """在服务器上执行深度任务（DeepSeek Harness agent），跑完异步回推结果。
        仅当用户明确要求在服务器上执行任务/跑 agent/深度查证并整理时调用；日常聊天问答不要调用。

        Args:
            task(string): 任务全文，尽量保留用户原话与细节
            mode(string): new=新会话（默认）；continue=沿用该用户最近会话继续（保留文件与 shell 状态）
        """
        if not self._is_owner(event):
            return "OWNER_ONLY：该工具仅 owner（微信私聊）可用。"
        return await self._accept(event, task, mode)

    @filter.command("dsh")
    async def cmd_dsh(self, event: AstrMessageEvent) -> MessageEventResult:
        """DSH 深度任务：/dsh <任务>（开头加「继续」沿用会话）｜/dsh status｜/dsh reset"""
        if not self._is_owner(event):
            yield event.plain_result("OWNER_ONLY：仅 owner（微信私聊）可用。")
            return
        text = re.sub(r"^\s*/?dsh\s*", "", (event.message_str or "").strip(),
                      flags=re.I).strip()
        if not text:
            yield event.plain_result("用法：/dsh <任务>（开头加「继续」沿用会话）｜/dsh status｜/dsh reset")
            return
        low = text.lower()
        if low in ("status", "状态"):
            yield event.plain_result(self._status())
            return
        if low in ("reset", "重置"):
            closed = await self._reset()
            yield event.plain_result("runtime 已关闭。" if closed else "当前没有运行中的 runtime。")
            return
        mode = "continue" if text.startswith("继续") else "new"
        yield event.plain_result(await self._accept(event, text, mode))

    # ── 受理与执行 ──

    async def _accept(self, event: AstrMessageEvent, task: str, mode: str) -> str:
        miss = self._missing_config()
        if miss:
            return f"配置缺 {miss}，请先在管理面板填好再用。"
        task = (task or "").strip()
        if not task:
            return "任务内容为空。"
        if len(task) > 2000:
            return "任务文本超 2000 字，请拆分。"
        if self._current:
            mins = int((time.time() - self._current["t0"]) / 60)
            return f"已有任务 #{self._current['id']} 在跑（{mins} 分钟），等它完成或 /dsh reset。"
        umo = event.unified_msg_origin
        tid = self._next_id()
        sess = await self._session_for(umo, mode)
        self._current = {"id": tid, "umo": umo, "t0": time.time()}
        await self._tasklog(f"START | {tid} | {umo} | {sess['session_id'][:8]} | {task.splitlines()[0][:60]}")
        asyncio.create_task(self._worker(tid, umo, task, sess))
        tag = "沿用会话" if mode == "continue" else "新会话"
        return f"收到任务 #{tid}（{tag}）· 跑完回推，期间可正常聊天。"

    async def _session_for(self, umo: str, mode: str) -> dict:
        s = self._sessions.get(umo)
        if mode == "continue" and s:
            s["turns"] = int(s.get("turns", 1)) + 1
            s["updated"] = datetime.now().isoformat(timespec="seconds")
        else:
            s = {"session_id": uuid.uuid4().hex[:12], "turns": 1,
                 "updated": datetime.now().isoformat(timespec="seconds")}
            self._sessions[umo] = s
        await self._save_sessions()
        return s

    def _next_id(self) -> str:
        self._seq += 1
        return f"{datetime.now().strftime('%m%d')}-{self._seq:02d}"

    def _seed_seq(self):
        """从台账恢复当日序号——插件热重载后内存计数归零会撞号（0919-01 复发案例）。"""
        today = datetime.now().strftime("%m%d")
        mx = 0
        p = self._ws / TASKLOG_NAME
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                m = re.search(rf"\| {today}-(\d{{2}}) \|", ln)
                if m:
                    mx = max(mx, int(m.group(1)))
        self._seq = mx

    async def _rotate_session(self, umo: str) -> dict:
        s = {"session_id": uuid.uuid4().hex[:12], "turns": 1,
             "updated": datetime.now().isoformat(timespec="seconds")}
        self._sessions[umo] = s
        await self._save_sessions()
        return s

    async def _worker(self, tid: str, umo: str, task: str, sess: dict):
        wall = int(self.config.get("task_wallclock_minutes", 15)) * 60
        t0 = time.time()
        degraded = False
        try:
            async with self._lock:
                self._cancel_idle()
                try:
                    h = await self._ensure_harness()
                    try:
                        result = await asyncio.wait_for(
                            asyncio.to_thread(h.run, task, session_id=sess["session_id"]),
                            timeout=wall)
                    except Exception as e:
                        if "already exists" not in str(e):
                            raise
                        # rc1 实测：持久化 session id 只能在同一 runtime 实例内复用，
                        # 跨实例（idle 关闭/插件重载后）run() 报 already exists。
                        # 同 harness 换新 id 重跑一次（diag 验证此路径可用），续接降级为新会话。
                        sess = await self._rotate_session(umo)
                        degraded = True
                        result = await asyncio.wait_for(
                            asyncio.to_thread(h.run, task, session_id=sess["session_id"]),
                            timeout=wall)
                    final = (getattr(result, "final_response", None) or "").strip()
                except asyncio.TimeoutError:
                    await self._kill_runtime()
                    await self._send(umo, f"⏱ #{tid} 超过 {wall // 60} 分钟硬上限，已中断并关闭 runtime。"
                                          "建议把任务拆小后重发。")
                    await self._tasklog(f"FAIL | {tid} | wallclock-timeout")
                    return
                except Exception as e:
                    await self._kill_runtime()
                    await self._send(umo, f"❌ #{tid} 执行失败：{type(e).__name__}: {str(e)[:300]}\n"
                                          "可 /dsh reset 后重试。")
                    await self._tasklog(f"FAIL | {tid} | {type(e).__name__}: {str(e)[:120]}")
                    return
            finish = getattr(result, "finish_reason", None)
            if finish == "error" or not final:
                err = ""
                for ev in reversed(getattr(result, "events", None) or []):
                    s = str(ev)
                    if "'kind': 'error'" in s:
                        err = s[:300]
                        break
                async with self._lock:
                    await self._kill_runtime()
                await self._send(umo, f"❌ #{tid} agent 轮次失败（finish={finish or 'none'}）：{err or '无输出'}")
                await self._tasklog(f"FAIL | {tid} | agent-error: {finish} | {err[:100]}")
                return
            note = "\n（注：原会话跨重启不可续接，已自动开新会话重跑本任务）" if degraded else ""
            await self._send(umo, self._format_result(tid, time.time() - t0, final) + note)
            await self._tasklog(f"DONE | {tid} | {int(time.time() - t0)}s | out:{len(final)}ch" + (" | session-rotated" if degraded else ""))
        finally:
            self._current = None
            self._arm_idle()

    async def _ensure_harness(self):
        if self._harness is None:
            try:
                from deepseek_harness import DeepSeekHarness   # PyPI 项目名是 deepseek-harness-sdk，导入名是 deepseek_harness
            except ImportError:
                from deepseek_harness_sdk import DeepSeekHarness   # 兜底：包名改名时再试项目名
            home = PLUGIN_DIR / "data" / "plugin_data" / "dsh_task" / "dsh_home"
            home.mkdir(parents=True, exist_ok=True)
            # 容器内无 bwrap 且 userns 被 docker seccomp 拦 → confined bash 无后端可用。
            # 官方通道：DSH_PERMISSION_MODE 进程级覆写沙箱模式（danger-full-access → 审批自动 never），
            # 会话创建时钉入（对已存在会话无效；本插件默认每任务新会话，无此问题）。SDK env 是合并语义。
            # 边界回到 v0.4 威胁模型：容器隔离 + owner + 单飞 + wall-clock + 宪法（软）。
            # P2：容器装 bubblewrap + seccomp=unconfined 后切回 workspace-write（ADR-007）。
            preset = self.config.get("permission_preset", "danger-full-access")
            kwargs = dict(
                cwd=str(self._ws),
                dsh_home=str(home),
                env={"DSH_PERMISSION_MODE": preset},
                base_url=self.config["base_url"],
                api_key=self.config["api_key"],
                model=self.config["model"],
                max_tokens=int(self.config.get("max_tokens", 131072)),   # SDK 默认 256k，百炼上限 131072，不压会 400
                request_timeout_seconds=int(self.config.get("request_timeout_seconds", 600)),
                initialize_timeout_seconds=60,
            )
            if self.config.get("provider"):
                kwargs["provider"] = self.config["provider"]
            self._harness = await asyncio.to_thread(DeepSeekHarness, **kwargs)
        return self._harness

    async def _kill_runtime(self):
        h, self._harness = self._harness, None
        if h is not None:
            try:
                await asyncio.to_thread(h.close)
            except Exception as e:
                logger.warning(f"[dsh_task] close runtime: {e}")

    def _arm_idle(self):
        self._cancel_idle()
        mins = int(self.config.get("idle_close_minutes", 10))
        if mins > 0 and self._harness is not None:
            self._idle_task = asyncio.create_task(self._idle_close(mins * 60))

    def _cancel_idle(self):
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    async def _idle_close(self, delay: float):
        try:
            await asyncio.sleep(delay)
            async with self._lock:               # 抢不到=有新任务，本计时作废（worker 收工会重挂）
                if self._current is None and self._harness is not None:
                    logger.info("[dsh_task] idle 达时，关闭 runtime 释放内存")
                    await self._kill_runtime()
        except asyncio.CancelledError:
            pass

    async def _reset(self) -> bool:
        self._cancel_idle()
        async with self._lock:
            if self._harness is None:
                return False
            await self._kill_runtime()
            return True

    # ── 输出 ──

    def _format_result(self, tid: str, secs: float, final: str) -> str:
        limit = int(self.config.get("max_result_chars", 3000))
        body = final if len(final) <= limit else \
            final[:limit] + f"\n…（已截断，原始 {len(final)} 字，全文见工作区产物）"
        return f"✅ #{tid} 完成 · {int(secs)}s\n{body}"

    def _status(self) -> str:
        cur = f"#{self._current['id']}（{int((time.time() - self._current['t0']) / 60)} 分钟）" \
            if self._current else "无"
        return (f"runtime：{'运行中' if self._harness else '未启动'}\n"
                f"当前任务：{cur}\n"
                f"会话数：{len(self._sessions)}\n"
                f"工作区：{self._ws}")

    async def _send(self, umo: str, message: str):
        try:
            chain = MessageChain().message(message)
            await self.context.send_message(umo, chain)
        except Exception as e:
            logger.error(f"[dsh_task] 回推失败 [{umo}]: {e}")
