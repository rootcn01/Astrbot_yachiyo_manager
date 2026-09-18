#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Key 冒烟测试：用免费预置音色模型 mimo-v2.5-tts 合成一句话。
不消耗任何额度（TTS 限时免费），验证三件事：key 有效、端点可达、TTS 免费口径实战成立。
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
BASE_URL = os.environ.get("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1").rstrip("/")
KEY = os.environ.get("MIMO_API_KEY", "").strip() or (HERE / "api_key.txt").read_text(encoding="utf-8").strip()


def call(payload: dict) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": KEY,
            "Authorization": "Bearer " + KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:800]


def main() -> None:
    base_payload = {
        "model": "mimo-v2.5-tts",
        "messages": [
            {"role": "user", "content": "用平静自然的语气说话。"},
            {"role": "assistant", "content": "密钥验证成功，语音链路已经打通。"},
        ],
        "stream": False,
    }
    for voice in ("茉莉", None):
        payload = dict(base_payload)
        payload["audio"] = {"format": "wav", **({"voice": voice} if voice else {})}
        print(f"[i] 尝试 voice={voice or '(默认)'} ...")
        status, body = call(payload)
        if status != 200:
            print(f"[E] HTTP {status}: {body}")
            continue
        audio = ((body.get("choices") or [{}])[0].get("message") or {}).get("audio") or {}
        data = audio.get("data")
        if not data:
            print(f"[E] 200 但无 audio.data: {json.dumps(body, ensure_ascii=False)[:400]}")
            continue
        out = HERE / "outputs" / "smoke.wav"
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(base64.b64decode(data))
        usage = body.get("usage") or {}
        print(f"[OK] voice={voice or '(默认)'} -> {out} ({out.stat().st_size / 1024:.0f} KB)")
        print(f"[i] usage 原样返回: {json.dumps(usage, ensure_ascii=False)}")
        print("[DONE] key 有效 + 端点可达 + TTS 免费合成成功。拿播放器听一下 outputs/smoke.wav。")
        return
    sys.exit("[FAIL] 两种 voice 形态都没成功，把上面的报错带回来。")


if __name__ == "__main__":
    main()
