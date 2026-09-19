# ECAPA-TDNN speaker verification: discrimination test + clustering + Yachiyo claiming.
# ECAPA cosine: same speaker (cross register) ~0.4-0.8, different speakers typically <0.25.
import json
import sys
import wave
from pathlib import Path

import numpy as np
import torch
import torchaudio
from scipy.cluster.vq import kmeans2
from speechbrain.inference.speaker import EncoderClassifier

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")
CAND = BASE.parents[1] / "candidates"
ECAPA = str(BASE.parents[1] / "_tmp/ecapa")
K = {"p2": 4, "bd": 3}


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


def emb(m, p):
    with torch.no_grad():
        e = m.encode_batch(load16k_tensor(p)).squeeze().numpy()
        return e / np.linalg.norm(e)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    m = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                       savedir=ECAPA, run_opts={"device": "cpu"})
    alarm = emb(m, CAND / "alarmP2_yachiyo_solo_v1.wav")
    kag = emb(m, CAND / "kaguya_anchor_p2.wav")
    radio = np.mean([emb(m, BASE / f"hayami_w{t}.wav") for t in [300, 900, 1800, 2700, 3600, 4500, 5400]], axis=0)
    radio /= np.linalg.norm(radio)
    print(f"[discrimination] alarm~radio (same-CV cross-register): {alarm @ radio:.3f}")
    print(f"[discrimination] alarm~kaguyaAnchor:                    {alarm @ kag:.3f}")
    print(f"[discrimination] radio~kaguyaAnchor:                    {radio @ kag:.3f}")
    for p in sorted(BASE.glob("BV1nZjz6REQK_*.wav")):
        e = emb(m, p)
        print(f"[broadcast] {p.name:32s} alarm={e @ alarm:+.3f} kag={e @ kag:+.3f} radio={e @ radio:+.3f}")

    for name, k in K.items():
        clips = sorted((BASE / f"{name}_all").glob("clip_*.wav"))
        scored = {round(c["start"], 1): c for c in json.load(open(BASE / f"{name}_scored.json", encoding="utf-8"))}
        rows = []
        for p in clips:
            st = float(p.stem.split("_")[1])
            sc = scored.get(round(st, 1), {})
            if sc.get("dur", 0) < 1.0:
                continue
            rows.append({"clip": p.name, "start": st, "dur": sc.get("dur", 0), "emb": emb(m, p)})
        X = np.stack([r["emb"] for r in rows])
        best = None
        for seed in range(8):
            cent, lab = kmeans2(X, k, minit="++", seed=seed, iter=50)
            intra = np.mean([np.linalg.norm(X[i] - cent[lab[i]]) for i in range(len(X))])
            if best is None or intra < best[0]:
                best = (intra, cent, lab)
        intra, cent, lab = best
        print(f"== {name}: {len(rows)} clips k={k} intra={intra:.3f}")
        for ci, c in enumerate(cent):
            n = int((lab == ci).sum())
            secs = sum(r["dur"] for i, r in enumerate(rows) if lab[i] == ci)
            print(f"   c{ci} n={n:3d} {secs:5.0f}s alarm={float(c @ alarm):+.3f} radio={float(c @ radio):+.3f} kag={float(c @ kag):+.3f}")
        asr = {round(json.loads(l)["start"], 1): json.loads(l)["text"] for l in open(BASE / f"{name}_asr_full.jsonl", encoding="utf-8")}
        json.dump([{k2: v for k2, v in r.items() if k2 != "emb"} | {"lab": int(lab[i])} for i, r in enumerate(rows)],
                  open(BASE / f"{name}_ecapa_labels.json", "w"), ensure_ascii=False, indent=1)
        # top cluster by alarm
        yc = int(np.argmax([float(c @ alarm) for c in cent]))
        mem = sorted([r for i, r in enumerate(rows) if lab[i] == yc], key=lambda r: -float(r["emb"] @ cent[yc]))
        print(f"   -- cluster{yc} by alarm, top 20:")
        for r in mem[:20]:
            print(f"   {r['start']:8.1f} {r['dur']:5.1f}s | {asr.get(round(r['start'],1),'')[:60]}")


if __name__ == "__main__":
    main()
