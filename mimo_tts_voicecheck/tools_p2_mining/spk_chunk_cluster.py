# Chunk-level speaker clustering: attribution + purity in one vote per clip.
# Chunks (1.6s, energy-gated) are near-single-speaker; a clip is Yachiyo iff >=80% of its
# chunks land in the anchor-claimed cluster with decent centroid cosine.
import json
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.cluster.vq import kmeans2

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")
CAND = BASE.parents[1] / "candidates"
K = {"p2": 5, "bd": 4}
CHUNK = 1.6
FRAC_Y = 0.80          # fraction of chunks that must vote yachiyo
CENT_COS = 0.70        # chunk-to-claimed-centroid floor for a valid vote
RMS_GATE = 0.02
MIN_DUR = 1.2


def clip_wav(p):
    with wave.open(str(p), "rb") as w:
        return (np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from resemblyzer import VoiceEncoder, preprocess_wav
    enc = VoiceEncoder("cpu", verbose=False)
    anchor = enc.embed_utterance(preprocess_wav(str(CAND / "alarmP2_yachiyo_solo_v1.wav")))

    for name, k in K.items():
        clips = sorted((BASE / f"{name}_all").glob("clip_*.wav"))
        scored = {round(c["start"], 1): c for c in json.load(open(BASE / f"{name}_scored.json", encoding="utf-8"))}
        asr = {}
        for line in open(BASE / f"{name}_asr_full.jsonl", encoding="utf-8"):
            d = json.loads(line)
            asr[round(d["start"], 1)] = d["text"]
        # 1) collect chunks
        per_clip, allc = {}, []
        for p in clips:
            x = clip_wav(p)
            n = int(CHUNK * 16000)
            if len(x) < n // 2:
                continue
            chs = []
            for off in range(0, len(x) - n + 1, n):
                seg = x[off:off + n]
                if float(np.sqrt(np.mean(seg ** 2))) < RMS_GATE:
                    continue
                chs.append(seg)
            if chs:
                per_clip[p.name] = chs
                allc.extend(chs)
        print(f"[{name}] {len(allc)} chunks from {len(per_clip)} clips")
        X = np.stack([enc.embed_utterance(c) for c in allc])
        best = None
        for seed in range(6):
            cent, lab = kmeans2(X, k, minit="++", seed=seed, iter=40)
            intra = np.mean([np.linalg.norm(X[i] - cent[lab[i]]) for i in range(len(X))])
            if best is None or intra < best[0]:
                best = (intra, cent, lab)
        intra, cent, lab = best
        anchor_cos = [float(c @ anchor) for c in cent]
        yc = int(np.argmax(anchor_cos))
        print(f"[{name}] intra={intra:.3f} cluster{yc} claimed cos={anchor_cos[yc]:.3f}; all={[round(a,3) for a in anchor_cos]}")
        sizes = {ci: int((lab == ci).sum()) for ci in range(k)}
        print(f"[{name}] cluster sizes {sizes}")
        # 2) per-clip vote
        idx = 0
        out = []
        for pname, chs in per_clip.items():
            st = float(Path(pname).stem.split("_")[1])
            votes = lab[idx: idx + len(chs)]
            idx += len(chs)
            frac = float(np.mean([v == yc for v in votes]))
            cent_coses = [float(ch_e @ cent[yc]) for ch_e, v in zip([e for e in X[idx - len(chs): idx]], votes) if v == yc]
            strong = float(np.mean([c >= CENT_COS for c in cent_coses])) if cent_coses else 0.0
            dur = scored.get(round(st, 1), {}).get("dur", 0)
            out.append({"clip": pname, "start": st, "dur": dur,
                        "frac_y": round(frac, 2), "strong": round(strong, 2),
                        "label": "y" if (frac >= FRAC_Y and strong >= 0.9 and dur >= MIN_DUR) else ("mixed" if frac >= 0.3 else "other"),
                        "text": asr.get(round(st, 1), "")})
        json.dump(out, open(BASE / f"{name}_final_labels.json", "w"), ensure_ascii=False, indent=1)
        ys = [r for r in out if r["label"] == "y"]
        print(f"[{name}] FINAL yachiyo solo: {len(ys)} clips, {sum(r['dur'] for r in ys):.0f}s")
        for r in sorted(ys, key=lambda r: r["start"]):
            print(f"   {r['start']:8.1f} {r['dur']:5.1f}s f={r['frac_y']} | {r['text'][:60]}")


if __name__ == "__main__":
    main()
