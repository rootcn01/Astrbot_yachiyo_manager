#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MiMo voiceclone 音色验证脚本（零第三方依赖，不用装包）。

跑法:
  1) 参考音频: 放一个 reference.wav / reference.mp3 到本目录 (或把路径作为第一个参数)
  2) API Key: 设环境变量 MIMO_API_KEY, 或写入同目录 api_key.txt (单行纯 key)
  3) python mimo_voice_check.py [参考音频路径] [--cn]
     (默认日语组——八千代语音一律日语(用户规则); --cn 才用中文组)

产出: outputs/ 下三个 wav。判据:
  test1_bare    裸合成, 和原声比"像不像" —— 主判据
  test2_style   带风格指令, 判指令是否生效
  test3_persona 八千代人设句, 判日常汇报语感
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1").rstrip("/")
MODEL = "mimo-v2.5-tts-voiceclone"
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "outputs"

TESTS_CN = [
    (
        "test1_bare",
        "",
        "今天天气不错，我们把上次说好的事情再对一遍吧。",
    ),
    (
        "test2_style",
        "用平静温和、略带笑意的语气说话，语速放慢，吐字放松。",
        "记账完成啦。今天这一笔已经写进账本，还顺手归好了类，不用你再检查第二遍。",
    ),
    (
        "test3_persona",
        "你是八千代，说话轻快亲切，带一点自然的少女感，像在微信里跟主人汇报今天的进展。",
        "今天的日报整理好了，三件事都办完了。晚上想吃什么我也顺手想了两个备选，等你回来定。",
    ),
]

# 日语组：参考音频是日语，同语言克隆才能听出真实相似度（中文输出=跨语言，音色必然打折）
TESTS_JP = [
    (
        "jp1_bare",
        "",
        "おはようございます。今日も一日、よろしくお願いします。",
    ),
    (
        "jp2_bare",
        "",
        "えっ、本当ですか？それ、私に任せてくれたんですか？",
    ),
    (
        "jp3_style",
        "用温和、轻柔、贴着耳朵说话的语气，语速稍慢，像闹钟语音那样。",
        "もうすぐ着きますから、少しだけ待っていてくださいね。",
    ),
]

MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg"}


def load_key() -> str:
    env = os.environ.get("MIMO_API_KEY", "").strip()
    if env:
        return env
    key_file = HERE / "api_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    sys.exit("[E] 缺 API Key: 设 MIMO_API_KEY 或把 key 写进本目录 api_key.txt")


def find_reference(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if not p.exists():
            sys.exit(f"[E] 找不到参考音频: {arg}")
        return p
    for ext in ("wav", "mp3"):
        p = HERE / f"reference.{ext}"
        if p.exists():
            return p
    sys.exit("[E] 缺参考音频: 放一个 reference.wav / reference.mp3 到本目录, 或把路径作为参数传入")


def wav_duration(path: Path) -> str:
    try:
        with wave.open(str(path), "rb") as w:
            return f"{w.getnframes() / w.getframerate():.1f}s"
    except Exception:
        return "?"


def synthesize(key: str, voice_data_url: str, text: str, style: str) -> bytes:
    messages = []
    if style:
        messages.append({"role": "user", "content": style})
    messages.append({"role": "assistant", "content": text})
    payload = {
        "model": MODEL,
        "messages": messages,
        "audio": {"format": "wav", "voice": voice_data_url},
        "stream": False,
    }
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": key,
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        sys.exit(f"[E] HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"[E] 连不上 {BASE_URL}: {e.reason}")
    elapsed = time.time() - t0

    choices = body.get("choices") or []
    if not choices:
        sys.exit(f"[E] 响应无 choices: {json.dumps(body, ensure_ascii=False)[:500]}")
    if choices[0].get("finish_reason") == "content_filter":
        sys.exit("[E] 被内容过滤拦截 (finish_reason=content_filter), 换句文本再试")
    audio = (choices[0].get("message") or {}).get("audio") or {}
    data = audio.get("data")
    if not data:
        sys.exit(f"[E] 响应无 audio.data: {json.dumps(body, ensure_ascii=False)[:500]}")
    print(f"    合成耗时 {elapsed:.1f}s")
    return base64.b64decode(data)


def main() -> None:
    cn_mode = "--cn" in sys.argv[1:]
    pos_args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ref = find_reference(pos_args[0] if pos_args else None)
    tests = TESTS_CN if cn_mode else TESTS_JP
    key = load_key()
    mime = MIME.get(ref.suffix.lower())
    if not mime:
        sys.exit(f"[E] 参考音频只支持 mp3/wav, 收到: {ref.suffix}")
    b64 = base64.b64encode(ref.read_bytes()).decode("ascii")
    if len(b64) > 10 * 1024 * 1024:
        sys.exit("[E] 参考音频 base64 后超过 10MB 上限, 裁短一点")

    print(f"[i] endpoint = {BASE_URL}/chat/completions")
    print(f"[i] model    = {MODEL}")
    print(f"[i] 参考音频 = {ref.name} ({ref.stat().st_size / 1024:.0f} KB, base64 {len(b64) / 1024:.0f} KB)")
    tag = "_".join(ref.stem.split("_")[:2]) if ref.stem.startswith("candidate_") else "ref"
    OUT_DIR.mkdir(exist_ok=True)

    for name, style, text in tests:
        print(f"\n== {name} ==")
        if style:
            print(f"    风格指令: {style}")
        print(f"    文本: {text}")
        raw = synthesize(key, f"data:{mime};base64,{b64}", text, style)
        out = OUT_DIR / f"{tag}_{name}.wav"
        out.write_bytes(raw)
        print(f"    -> {out} ({len(raw) / 1024:.0f} KB, 时长 {wav_duration(out)})")

    print(f"\n[DONE] 三个 wav 已生成在 outputs/（前缀 {tag}_）。先听 {tag}_jp1_bare 和原声比相似度。")


if __name__ == "__main__":
    main()
