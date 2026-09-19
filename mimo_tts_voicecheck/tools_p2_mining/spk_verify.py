# Neural speaker verification (resemblyzer) with tri-anchor argmax + chunk purity.
# Anchors: yachiyo = production solo ref; kaguya = P2 self-naming solo lines; (iroha via exclusion).
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")
CAND = BASE.parents[1] / "candidates"
P2SRC = BASE / "BV1eUem6yE3x_P2_全语音展示.m4s"
KAG_LINES = [(313.5, 315.5), (340.9, 345.3), (346.8, 353.1), (361.9, 366.1), (367.2, 371.6)]
TH_HI = 0.80      # utterance cosine to be considered same speaker
MARGIN = 0.06     # required gap to runner-up anchor
CHUNK = 1.6       # purity chunk seconds; clips >= 5s must have all chunks agree
MIN_CHUNK_COS = 0.72


def build_kaguya_anchor():
    parts = []
    for s, e in KAG_LINES:
        p = BASE / f"kag_{s:.1f}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(s), "-i", str(P2SRC), "-to", str(e),
                        "-ac", "1", "-ar", "16000", str(p)], check=True)
        parts.append(p)
    out = CAND / "kaguya_anchor_p2.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "concat:" + "|".join(p.as_posix() for p in parts),
                    "-ac", "1", "-ar", "16000", str(out)], check=True)
    return out


def embed_clips(encoder, pre, paths):
    return {p.name: encoder.embed_utterance(pre(str(p))) for p in paths}


def cos(a, b):
    return float(a @ b)


def chunk_ok(encoder, pre, path, anchors):
    import wave
    with wave.open(str(path), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        sr = w.getframerate()
    n = int(CHUNK * sr)
    if len(x) < n * 2:
        return True, []
    votes, sims = [], []
    for off in range(0, len(x) - n + 1, n):
        emb = encoder.embed_utterance(x[off:off + n].astype(np.float32))
        sims_i = {k: cos(emb, v) for k, v in anchors.items()}
        best = max(sims_i, key=sims_i.get)
        votes.append(best)
        sims.append((best, sims_i[best]))
    if len(set(votes)) != 1:
        return False, votes
    return all(s >= MIN_CHUNK_COS for _, s in sims), votes


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from resemblyzer import VoiceEncoder, preprocess_wav
    enc = VoiceEncoder("cpu", verbose=False)
    pre = lambda p: preprocess_wav(p)

    kag_path = build_kaguya_anchor()
    anchors = {
        "y": enc.embed_utterance(pre(str(CAND / "alarmP2_yachiyo_solo_v1.wav"))),
        "k": enc.embed_utterance(pre(str(kag_path))),
    }
    # anchor sanity: cross-cos should be low
    print(f"[anchor] cos(y,k) = {cos(anchors['y'], anchors['k']):.3f}")

    for name in ["p2", "bd"]:
        clips = sorted((BASE / f"{name}_all").glob("clip_*.wav"))
        embs = embed_clips(enc, pre, clips)
        rows = []
        for p in clips:
            e = embs[p.name]
            sy, sk = cos(e, anchors["y"]), cos(e, anchors["k"])
            best, runner = ("y", sy) if sy >= sk else ("k", sk)
            margin = abs(sy - sk)
            rows.append({"clip": p.name, "start": float(p.stem.split("_")[1]), "sy": round(sy, 3), "sk": round(sk, 3),
                         "best": best, "margin": round(margin, 3), "cand": bool(best == "y" and sy >= TH_HI and margin >= MARGIN)})
        # add dur from scored json
        scored = {round(c["start"], 1): c for c in json.load(open(BASE / f"{name}_scored.json", encoding="utf-8"))}
        for r in rows:
            sc = scored.get(round(r["start"], 1), {})
            r["dur"] = sc.get("dur", 0)
        # purity check on candidates >= 5s
        for r in rows:
            if r["cand"] and r["dur"] >= 5.0:
                okc, votes = chunk_ok(enc, pre, BASE / f"{name}_all" / r["clip"], anchors)
                r["pure"] = okc
                if not okc:
                    r["cand"] = False
                    r["why"] = f"chunk votes {votes}"
        json.dump(rows, open(BASE / f"{name}_spk.json", "w"), ensure_ascii=False, indent=1)
        cand = [r for r in rows if r["cand"]]
        print(f"== {name}: {len(cand)} yachiyo-candidates, {sum(r['dur'] for r in cand):.0f}s")
        for r in sorted(cand, key=lambda r: -r["sy"])[:40]:
            print(f"   {r['start']:8.1f} {r['dur']:5.1f}s sy={r['sy']:.3f} sk={r['sk']:.3f} pure={r.get('pure','-')}")


if __name__ == "__main__":
    main()
