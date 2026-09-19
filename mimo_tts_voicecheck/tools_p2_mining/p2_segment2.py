# Segment alarm-P2 (v2: consistent sample units everywhere).
import json
import sys
import wave

import numpy as np

SRC = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl\BV1eUem6yE3x_P2_全语音展示.wav"
OUT = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl\p2_segments.json"
SR = 16000
FRAME = int(0.030 * SR)
GAP_MERGE = int(0.45 * SR)
MIN_CLIP = int(1.0 * SR)
MAX_CLIP = int(14.0 * SR)


def load(path):
    with wave.open(path, "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
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


def f0_median(x):
    fl, hop, res = int(0.04 * SR), int(0.02 * SR), []
    for off in range(0, len(x) - fl, hop):
        seg = x[off:off + fl]
        if float(np.mean(seg ** 2)) < 5e-4:
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, "full")[fl - 1:]
        lo, hi = int(SR / 450), int(SR / 120)
        band = ac[lo:hi] / (ac[0] + 1e-9)
        k = int(np.argmax(band))
        if band[k] > 0.45:
            res.append(SR / (lo + k))
    return round(float(np.median(res))) if len(res) >= 5 else None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    x = load(SRC)
    runs = merge_runs(speech_mask(x))
    clips = []
    for s, e in runs:
        pieces = split_long(x, s, e) if e - s > MAX_CLIP else [(s, e)]
        for a, b in pieces:
            if b - a < MIN_CLIP:
                continue
            clips.append({"start": round(a / SR, 2), "end": round(b / SR, 2),
                          "dur": round((b - a) / SR, 2), "f0": f0_median(x[a:b])})
    json.dump(clips, open(OUT, "w"), ensure_ascii=False, indent=1)
    tot = sum(c["dur"] for c in clips)
    print(f"total clips: {len(clips)}, speech secs: {tot:.0f}")
    f0s = sorted(c["f0"] for c in clips if c["f0"])
    print("F0 sorted sample:", [round(v) for v in f0s[:: max(1, len(f0s) // 25)]])
    for i, c in enumerate(clips):
        print(f"{i:3d} {c['start']:8.1f}-{c['end']:8.1f} {c['dur']:5.1f}s f0={c['f0']}")


if __name__ == "__main__":
    main()
