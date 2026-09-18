#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站无登录音频拉取（DASH 直下配方，见 memory bili-no-login-video-extract-recipe）。
用法: python bili_fetch.py BV1xxxx [输出目录]
输出: <dir>/<BV>_audio.m4s + <BV>.json(元数据)；curl 拦截页重试一次即过的坑已内置。
"""
import json, subprocess, sys, time
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
REFERER = "https://www.bilibili.com/"


def curl_json(url: str, retries: int = 2):
    for i in range(retries):
        raw = subprocess.run(["curl", "-s", "-A", UA, "-H", "Referer: " + REFERER, url],
                              capture_output=True).stdout
        try:
            return json.loads(raw)
        except Exception:
            time.sleep(1.5)  # 拦截 HTML 页：原样重试即 200
    raise RuntimeError(f"non-JSON from {url}: {raw[:120]!r}")


def main():
    bvid = sys.argv[1].strip()
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("bili_dl")
    out_dir.mkdir(parents=True, exist_ok=True)
    view = curl_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    assert view.get("code") == 0, view
    data = view["data"]
    cid = data["cid"]
    meta = {"bvid": bvid, "title": data["title"], "owner": data["owner"]["name"],
            "pubdate": time.strftime("%Y-%m-%d", time.localtime(data["pubdate"])),
            "duration": data["duration"], "cid": cid, "desc": data.get("desc", "")[:300]}
    (out_dir / f"{bvid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[meta] {meta['title']} | UP:{meta['owner']} | {meta['pubdate']} | {meta['duration']}s")

    play = curl_json(f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=64&fnval=16")
    assert play.get("code") == 0, play
    dash = play["data"]["dash"]
    auds = sorted(dash.get("audio") or [], key=lambda a: -a.get("bandwidth", 0))
    assert auds, "no audio stream"
    best = auds[0]
    print(f"[audio] id={best['id']} bw={best.get('bandwidth', 0) // 1000}kbps codecs={best.get('codecs')}")
    out = out_dir / f"{bvid}_audio.m4s"
    subprocess.run(["curl", "-s", "-A", UA, "-H", "Referer: " + REFERER, "-o", str(out), best["baseUrl"]],
                   check=True)
    print(f"[done] {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
