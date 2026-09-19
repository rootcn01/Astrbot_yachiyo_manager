# Wideband speech mining: honpen-head narration (八千代 wideband) + 星見雅 game lines (same-CV wideband).
# Both: silence-segment -> whisper JA -> ECAPA filter -> 16k clips for mixing into A_wide.
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck")
SRC = [
    # (tag, audio path, is_target_character)  target=True -> ECAPA sy>=0.40; same-CV -> sy>=0.22 (diagnostic floor)
    ("honpen", BASE / "separated/htdemucs/yt_honpen_head_5m42s/vocals.wav", True),
    ("hoshi", BASE / "_tmp/bili_dl/BV17rC5YWEBa_audio.m4s", False),
]
OUTW = BASE / "_tmp/wide_all"
SR = 16000
FRAME = int(0.030 * SR)
GAP = int(0.45 * SR)
MINC, MAXC = int(1.5 * SR), int(12.0 * SR)


def load16k(p):
    tmp = OUTW / "tmp16k.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-ac", "1", "-ar", "16000", str(tmp)], check=True)
    w = wave.open(str(tmp))
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def segs(x):
    n = len(x) // FRAME
    rms = np.sqrt(np.mean(x[:n * FRAME].reshape(n, FRAME) ** 2, axis=1))
    thr = max(np.percentile(rms, 70) * 0.28, 0.012)
    mask = rms > thr
    runs, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append([start * FRAME, i * FRAME]); start = None
    if start is not None:
        runs.append([start * FRAME, n * FRAME])
    merged = []
    for s, e in runs:
        if merged and s - merged[-1][1] < GAP:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    out = []
    for s, e in merged:
        if e - s > MAXC:
            for k in range(s, e - MINC, int(8 * SR)):
                out.append((k, min(k + int(8 * SR), e)))
        elif e - s >= MINC:
            out.append((s, e))
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUTW.mkdir(exist_ok=True)
    import torch, torchaudio
    from speechbrain.inference.speaker import EncoderClassifier
    m = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                       savedir=str(BASE / "_tmp/ecapa"), run_opts={"device": "cpu"})

    def emb(p):
        w = wave.open(str(p))
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        t = torch.from_numpy(x).unsqueeze(0)
        with torch.no_grad():
            e = m.encode_batch(t).squeeze().numpy()
        return e / np.linalg.norm(e)

    anchor = emb(BASE / "candidates/alarmP2_yachiyo_solo_v1.wav")
    from faster_whisper import WhisperModel
    wm = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    rows = []
    for tag, path, is_target in SRC:
        x = load16k(path)
        kept = 0
        for i, (s, e) in enumerate(segs(x)):
            name = f"{tag}_{s/ SR:.1f}".replace(".", "_") + ".wav"
            p = OUTW / name
            ww = wave.open(str(p), "wb"); ww.setnchannels(1); ww.setsampwidth(2); ww.setframerate(SR)
            ww.writeframes((x[s:e] * 32768).astype(np.int16).tobytes()); ww.close()
            sy = float(emb(p) @ anchor)
            thr = 0.40 if is_target else 0.22
            print(f"  [{tag}] {name} sy={sy:.2f}", flush=True)
            sgs, _ = wm.transcribe(str(p), language="ja", beam_size=5)
            tx = "".join(g.text for g in sgs).strip().replace(" ", "")
            if len(tx) < 6:
                p.unlink(); continue
            rows.append({"wav": name, "dur": round((e - s) / SR, 2), "sy": round(sy, 3), "src": tag, "text": tx})
            kept += 1
        print(f"[{tag}] kept {kept} clips")
    json.dump(rows, open(OUTW / "wide_manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for tag in ("honpen", "hoshi"):
        sub = [r for r in rows if r["src"] == tag]
        print(f"== {tag}: {len(sub)} clips {sum(r['dur'] for r in sub):.0f}s")
        for r in sub[:12]:
            print(f"   {r['wav']:22s} {r['dur']:4.1f}s sy={r['sy']:.2f} | {r['text'][:44]}")


if __name__ == "__main__":
    main()
