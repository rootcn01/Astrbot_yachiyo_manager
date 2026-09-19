# Broadcast tracks mining: segment all 5 tracks -> cut clips -> batch ASR -> ECAPA attribution.
# Output: _tmp/bili_dl/bc_asr_full.jsonl + bc_all/ clips + bc_ecapa.json
import json
import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")
TRACKS = ["BV1nZjz6REQK_main", "BV1nZjz6REQK_P2", "BV1nZjz6REQK_P3", "BV1nZjz6REQK_P4", "BV1nZjz6REQK_P5"]
OUTD = BASE / "bc_all"
SR = 16000
FRAME = int(0.030 * SR)
GAP_MERGE = int(0.45 * SR)
MIN_CLIP = int(1.0 * SR)
MAX_CLIP = int(14.0 * SR)
WORKERS = 4
RETRIES = 3

sys.path.insert(0, r"C:\Users\lotus\AppData\Local\Temp")
from asr_mimo import transcribe


def load(path):
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1, (path, w.getframerate(), w.getnchannels())
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def speech_mask(x):
    n = len(x) // FRAME
    rms = np.sqrt(np.mean(x[:n * FRAME].reshape(n, FRAME) ** 2, axis=1))
    thr = max(np.percentile(rms, 70) * 0.28, 0.012)
    return rms > thr


def merge_runs(mask):
    runs, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append([start * FRAME, i * FRAME])
            start = None
    if start is not None:
        runs.append([start * FRAME, len(mask) * FRAME])
    merged = []
    for s, e in runs:
        if merged and s - merged[-1][1] < GAP_MERGE:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged if e - s >= MIN_CLIP]


def split_long(x, s, e):
    out, seg_start = [], s
    guard = 0
    while e - seg_start >= MAX_CLIP + SR and guard < 50:
        guard += 1
        window = int(0.2 * SR)
        best_t, best_e = seg_start + int(6 * SR), 1e9
        for t in range(seg_start + int(6 * SR), e - int(3 * SR), window):
            en = float(np.mean(x[t:t + window] ** 2))
            if en < best_e:
                best_e, best_t = en, t
        out.append((seg_start, best_t))
        seg_start = best_t + int(0.15 * SR)
    out.append((seg_start, e))
    return out


def segment_all():
    OUTD.mkdir(exist_ok=True)
    all_segs = []
    for tr in TRACKS:
        x = load(BASE / f"{tr}.wav")
        clips = []
        for s, e in merge_runs(speech_mask(x)):
            pieces = split_long(x, s, e) if e - s > MAX_CLIP else [(s, e)]
            for a, b in pieces:
                if b - a < MIN_CLIP:
                    continue
                clips.append({"track": tr, "start": round(a / SR, 2), "end": round(b / SR, 2),
                              "dur": round((b - a) / SR, 2)})
        for c in clips:
            p = OUTD / f"{c['track']}_c{c['start']:.1f}.wav"
            if not p.exists():
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(c["start"]), "-i", str(BASE / f"{tr}.wav"),
                                "-t", str(c["dur"]), "-ac", "1", "-ar", "16000", str(p)], check=True)
        all_segs.extend(clips)
        print(f"[seg] {tr}: {len(clips)} clips, {sum(c['dur'] for c in clips):.0f}s")
    json.dump(all_segs, open(BASE / "bc_segments.json", "w"), ensure_ascii=False, indent=1)
    print(f"[seg] total {len(all_segs)} clips, {sum(c['dur'] for c in all_segs):.0f}s")


def asr_one(c):
    seg = OUTD / f"{c['track']}_c{c['start']:.1f}.wav"
    for attempt in range(RETRIES):
        try:
            t = transcribe(str(seg)).replace("\n", " ").strip()
            if t.startswith("[ERR") or t.startswith("{"):
                raise RuntimeError(t[:80])
            return {**c, "text": t}
        except Exception as e:
            if attempt == RETRIES - 1:
                return {**c, "text": f"[ERR {e!r}]"}
            time.sleep(8 * (attempt + 1))


def asr_all():
    segs = json.load(open(BASE / "bc_segments.json", encoding="utf-8"))
    out_path = BASE / "bc_asr_full.jsonl"
    done = set()
    if out_path.exists():
        keep = []
        for line in open(out_path, encoding="utf-8"):
            r = json.loads(line)
            if r["text"].startswith("[ERR"):
                continue
            done.add((r["track"], round(r["start"], 1)))
            keep.append(line)
        open(out_path, "w", encoding="utf-8").writelines(keep)
    todo = [c for c in segs if (c["track"], round(c["start"], 1)) not in done]
    print(f"[asr] {len(segs)} total, {len(done)} cached, {len(todo)} to go")
    with ThreadPoolExecutor(WORKERS) as ex, open(out_path, "a", encoding="utf-8") as f:
        for i, r in enumerate(ex.map(asr_one, todo), 1):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            mark = "!" if r["text"].startswith("[ERR") else " "
            print(f"[{i:3d}/{len(todo)}]{mark} {r['track'][-2:]} {r['start']:7.1f} {r['dur']:4.1f}s | {r['text'][:70]}")


def ecapa_all():
    import torch
    import torchaudio
    from speechbrain.inference.speaker import EncoderClassifier

    def load16k_tensor(p):
        with wave.open(str(p), "rb") as w:
            sr, ch = w.getframerate(), w.getnchannels()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
            if ch == 2:
                x = x.reshape(-1, 2).mean(axis=1)
        t = torch.from_numpy(x).unsqueeze(0)
        if sr != 16000:
            t = torchaudio.functional.resample(t, sr, 16000)
        return t

    m = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                       savedir=str(Path(__file__).resolve().parents[1] / "_tmp/ecapa"),
                                       run_opts={"device": "cpu"})

    def emb(p):
        with torch.no_grad():
            e = m.encode_batch(load16k_tensor(p)).squeeze().numpy()
        return e / np.linalg.norm(e)

    anchor = emb(BASE.parents[1] / "candidates/alarmP2_yachiyo_solo_v1.wav")
    segs = json.load(open(BASE / "bc_segments.json", encoding="utf-8"))
    raw = [json.loads(l) for l in open(BASE / "bc_asr_full.jsonl", encoding="utf-8")]
    rows = []
    for r in raw:
        if isinstance(r, dict):
            rows.append(r)
    if len(rows) != len(segs):  # legacy string rows: rebuild by order against segments
        rows = [{**c, "text": r if isinstance(r, str) else r["text"]} for r, c in zip(raw, segs)]
        json.dump(rows, open(BASE / "bc_asr_full.jsonl", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in rows:
        r["sy"] = round(float(emb(OUTD / f"{r['track']}_c{r['start']:.1f}.wav") @ anchor), 3)
    json.dump(rows, open(BASE / "bc_ecapa.json", "w"), ensure_ascii=False, indent=1)
    ys = [r for r in rows if r["sy"] >= 0.45]
    print(f"[ecapa] {len(ys)}/{len(rows)} clips sy>=0.45, {sum(r['dur'] for r in ys):.0f}s")
    for r in sorted(rows, key=lambda r: -r["sy"])[:15]:
        print(f"   {r['track'][-2:]} {r['start']:7.1f} {r['dur']:4.1f}s sy={r['sy']} | {r['text'][:60]}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("all", "seg"):
        segment_all()
    if step in ("all", "asr"):
        asr_all()
    if step in ("all", "ecapa"):
        ecapa_all()
