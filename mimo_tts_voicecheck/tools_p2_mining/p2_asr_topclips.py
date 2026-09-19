# Per-clip ASR of top-40 Yachiyo-scored clips for line-level speaker attribution.
import json, subprocess, sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\lotus\AppData\Local\Temp")
from asr_mimo import transcribe

SRC = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl\BV1eUem6yE3x_P2_全语音展示.m4s")
SCORED = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl\p2_scored.json")
OUTD = SCORED.parent

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    clips = json.load(open(SCORED, encoding="utf-8"))
    clips.sort(key=lambda c: -c["sim"])
    for c in clips[:40]:
        seg = OUTD / f"clip_{c['start']:.1f}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SRC),
                        "-ss", str(c["start"]), "-t", str(round(c["dur"], 2)),
                        "-ac", "1", "-ar", "16000", str(seg)], check=True)
        try:
            text = transcribe(str(seg)).replace("\n", " ")[:150]
        except Exception as e:
            text = f"[ERR {e!r}]"
        print(f"{c['start']:8.1f}-{c['end']:8.1f} {c['dur']:5.1f}s sim={c['sim']:.3f} | {text}")
