# Full-pass per-clip ASR with resume + concurrency (P2/BD mining line-level attribution).
# Usage: python asr_full.py <p2|bd>   (cuts clips then transcribes; resume-safe via jsonl)
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, r"C:\Users\lotus\AppData\Local\Temp")
from asr_mimo import transcribe

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")
SOURCES = {
    "p2": {"src": BASE / "BV1eUem6yE3x_P2_全语音展示.m4s",
           "scored": BASE / "p2_scored.json", "clips": BASE / "p2_all", "out": BASE / "p2_asr_full.jsonl"},
    "bd": {"src": BASE / "BV1Jhe16EELF_main.wav",
           "scored": BASE / "bd_scored.json", "clips": BASE / "bd_all", "out": BASE / "bd_asr_full.jsonl"},
}
WORKERS = 4
RETRIES = 3


def cut_all(cfg):
    cfg["clips"].mkdir(exist_ok=True)
    segs = json.load(open(cfg["scored"], encoding="utf-8"))
    for c in segs:
        p = cfg["clips"] / f"clip_{c['start']:.1f}.wav"
        if p.exists():
            continue
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(c["start"]), "-i", str(cfg["src"]),
                        "-t", str(round(c["dur"], 2)), "-ac", "1", "-ar", "16000", str(p)], check=True)
    print(f"[cut] {len(segs)} clips -> {cfg['clips']}")


def asr_one(cfg, c):
    seg = cfg["clips"] / f"clip_{c['start']:.1f}.wav"
    for attempt in range(RETRIES):
        try:
            text = transcribe(str(seg)).replace("\n", " ").strip()
            if text.startswith("[ERR") or text.startswith("{"):
                raise RuntimeError(text[:80])
            return text
        except Exception as e:
            if attempt == RETRIES - 1:
                return f"[ERR {e!r}]"
            time.sleep(8 * (attempt + 1))


def main(which):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = SOURCES[which]
    cut_all(cfg)
    done = {}
    if cfg["out"].exists():
        keep = []
        for line in open(cfg["out"], encoding="utf-8"):
            r = json.loads(line)
            if r["text"].startswith("[ERR"):
                continue  # 429/timeout rows are not real results: retry them
            done[round(r["start"], 1)] = r["text"]
            keep.append(line)
        open(cfg["out"], "w", encoding="utf-8").writelines(keep)
    segs = json.load(open(cfg["scored"], encoding="utf-8"))
    todo = [c for c in segs if round(c["start"], 1) not in done]
    print(f"[asr] {len(segs)} total, {len(done)} cached, {len(todo)} to go")

    def work(c):
        return {**c, "text": asr_one(cfg, c)}

    with ThreadPoolExecutor(WORKERS) as ex, open(cfg["out"], "a", encoding="utf-8") as f:
        for i, r in enumerate(ex.map(work, todo), 1):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            mark = "!" if r["text"].startswith("[ERR") else " "
            print(f"[{i:3d}/{len(todo)}]{mark} {r['start']:8.1f}-{r['end']:8.1f} {r['dur']:5.1f}s | {r['text'][:90]}")
    print(f"[done] -> {cfg['out']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "p2")
