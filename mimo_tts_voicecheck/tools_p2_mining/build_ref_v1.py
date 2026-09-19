# Build new Yachiyo reference from content-verified solo lines cut from P2 m4s.
import subprocess, sys
from pathlib import Path

D = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")
SRC = D / "BV1eUem6yE3x_P2_全语音展示.m4s"
CAND = D.parents[1] / "candidates"

# (start, end, note) — solo-Yachiyo confirmed by content + high sim
LINES = [
    (151.6, 156.1, "elegant_gokigen"),
    (585.0, 587.1, "kami_wishes"),
    (589.7, 591.4, "wish_today"),
    (630.8, 633.1, "praise_effort"),
    (655.7, 658.0, "pancake_wistful"),
    (662.4, 664.8, "monogatari"),
    (671.6, 675.3, "giving_gift"),
    (1108.0, 1110.4, "night_view"),
    (171.2, 172.5, "ready_kana"),
]
GAP = 0.28

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = D / "refbuild"
    tmp.mkdir(exist_ok=True)
    parts, total = [], 0.0
    for i, (s, e, tag) in enumerate(LINES):
        p = tmp / f"l{i:02d}_{tag}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SRC), "-ss", str(s),
                        "-to", str(e), "-ac", "1", "-ar", "24000", str(p)], check=True)
        parts.append(p)
        total += e - s
        print(f"{tag}: {e-s:.1f}s")
    gap = tmp / "gap.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", str(GAP), str(gap)], check=True)
    lst = tmp / "list.txt"
    rows = []
    for i, p in enumerate(parts):
        rows.append(f"file '{p.as_posix()}'")
        if i < len(parts) - 1:
            rows.append(f"file '{gap.as_posix()}'")
    lst.write_text("\n".join(rows), encoding="utf-8")
    out = CAND / "alarmP2_yachiyo_solo_v1.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(out)], check=True)
    print(f"[done] {out}  speech={total:.1f}s + gaps -> file size {out.stat().st_size/1e6:.2f} MB")

if __name__ == "__main__":
    main()
