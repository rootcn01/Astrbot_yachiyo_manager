# Unsupervised speaker clustering (k-means on resemblyzer embeddings), then claim the
# Yachiyo cluster via the verified solo anchor. Text markers cross-checked at the end.
import json
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.cluster.vq import kmeans2

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")
CAND = BASE.parents[1] / "candidates"
K = {"p2": 4, "bd": 3}          # BD = exactly 3 CVs; P2 may include extra voices
MIN_DUR = 1.0
CLAIM_COS = 0.80                # centroid-to-anchor cosine to claim cluster
MEMBER_COS = 0.70               # member-to-cluster-centroid membership floor
CHUNK = 1.6
YACHIYO_TEXT = ["良きかな", "良きかな", "神々のみんな", "物語を見届け", "ですわ", "のですよ", "やっちゃん", "やちよ", "八千代", "八尾", "かしらね"]


def load_wav(p):
    with wave.open(str(p), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return x


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from resemblyzer import VoiceEncoder, preprocess_wav
    enc = VoiceEncoder("cpu", verbose=False)
    anchor = enc.embed_utterance(preprocess_wav(str(CAND / "alarmP2_yachiyo_solo_v1.wav")))

    for name, k in K.items():
        clips = sorted((BASE / f"{name}_all").glob("clip_*.wav"))
        scored = {round(c["start"], 1): c for c in json.load(open(BASE / f"{name}_scored.json", encoding="utf-8"))}
        rows = []
        for p in clips:
            st = float(p.stem.split("_")[1])
            sc = scored.get(round(st, 1), {})
            if sc.get("dur", 0) < MIN_DUR:
                continue
            e = enc.embed_utterance(preprocess_wav(str(p)))
            rows.append({"clip": p.name, "start": st, "dur": sc.get("dur", 0), "emb": e})
        X = np.stack([r["emb"] for r in rows])
        best = None
        for seed in range(8):
            cent, lab = kmeans2(X, k, minit="++", seed=seed, iter=50)
            intra = np.mean([np.linalg.norm(X[i] - cent[lab[i]]) for i in range(len(X))])
            if best is None or intra < best[0]:
                best = (intra, cent, lab)
        intra, cent, lab = best
        yc = int(np.argmax([float(c @ anchor) for c in cent]))
        claim = float(cent[yc] @ anchor)
        print(f"== {name}: {len(rows)} clips, k={k}, intra={intra:.3f}, cluster{yc} claimed (cos={claim:.3f})")
        for ci in range(k):
            n = int((lab == ci).sum())
            secs = sum(r["dur"] for i, r in enumerate(rows) if lab[i] == ci)
            print(f"   cluster{ci}: n={n} {secs:.0f}s anchorcos={float(cent[ci] @ anchor):.3f}")

        members = []
        for i, r in enumerate(rows):
            if lab[i] != yc:
                continue
            mcos = float(r["emb"] @ cent[yc])
            r2 = {k2: v for k2, v in r.items() if k2 != "emb"}
            r2.update({"mcos": round(mcos, 3), "member": mcos >= MEMBER_COS})
            members.append(r2)
        # text marker cross-check
        asr = {}
        f_asr = BASE / f"{name}_asr_full.jsonl"
        if f_asr.exists():
            for line in open(f_asr, encoding="utf-8"):
                d = json.loads(line)
                asr[round(d["start"], 1)] = d["text"]
        hits = sum(1 for r in members if any(m in asr.get(round(r["start"], 1), "") for m in YACHIYO_TEXT))
        print(f"   yachiyo-cluster members: {sum(1 for r in members if r['member'])}/{len(members)}, "
              f"{sum(r['dur'] for r in members if r['member']):.0f}s; text-marker hits {hits}")
        json.dump(members, open(BASE / f"{name}_ycluster.json", "w"), ensure_ascii=False, indent=1)
        top = sorted(members, key=lambda r: -r["mcos"])[:30]
        for r in top:
            t = asr.get(round(r["start"], 1), "")
            print(f"   {r['start']:8.1f} {r['dur']:5.1f}s m={r['mcos']:.3f} | {t[:60]}")


if __name__ == "__main__":
    main()
