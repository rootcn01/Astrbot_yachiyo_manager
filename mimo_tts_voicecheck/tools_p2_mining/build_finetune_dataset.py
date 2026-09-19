# Build GPT-SoVITS fine-tune dataset: ECAPA selection + chunk purity + faster-whisper JA transcripts.
# Sources: P2 alarm pack (character register) + BD commentary (talk register) + broadcasts (formal register).
import json
import shutil
import sys
import wave
from pathlib import Path

import numpy as np
import torch
import torchaudio
from speechbrain.inference.speaker import EncoderClassifier

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")
CAND = BASE.parents[1] / "candidates"
OUT = BASE.parents[1] / "finetune_dataset"
WAVD = OUT / "wav"
SY_MIN = 0.40       # utterance cos to anchor
CHUNK_MIN = 0.35    # worst 1.6s chunk floor (multi-chunk clips)
MIN_DUR, MAX_DUR = 1.5, 12.0
SPEAKER = "yachiyo"
# prompts per deploy plan §2.3: happy/tender/default, 3-6s, alarm (character) register
PROMPTS = {
    "happy": ("p2_all/clip_186.5.wav", "神々のみんなが楽しそうだと、やっちゃんも嬉しいよ。"),
    "tender": ("p2_all/clip_630.8.wav", "いつもいっぱい頑張ってるんだね。"),
    "default": ("p2_all/clip_1108.0.wav", "月夜の夜景が大好きなので。"),
}


def load16k(p):
    with wave.open(str(p), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    t = torch.from_numpy(x).unsqueeze(0)
    if sr != 16000:
        t = torchaudio.functional.resample(t, sr, 16000)
    return t


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    m = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                       savedir=str(BASE.parents[1] / "_tmp/ecapa"),
                                       run_opts={"device": "cpu"})

    def emb(x):
        with torch.no_grad():
            e = m.encode_batch(x).squeeze().numpy()
        return e / np.linalg.norm(e)

    anchor = emb(load16k(CAND / "alarmP2_yachiyo_solo_v1.wav"))

    # ---- 1) candidate pool
    pool = []
    p2 = json.load(open(BASE / "p2_ecapa_labels.json", encoding="utf-8"))
    bd = json.load(open(BASE / "bd_ecapa_labels.json", encoding="utf-8"))
    for r in p2:
        if r["lab"] == 1:
            pool.append(("p2", BASE / "p2_all" / r["clip"], r["start"], r["dur"]))
    for r in bd:
        if r["lab"] == 2:
            pool.append(("bd", BASE / "bd_all" / r["clip"], r["start"], r["dur"]))
    for r in json.load(open(BASE / "bc_ecapa.json", encoding="utf-8")):
        pool.append(("bc", BASE / "bc_all" / f"{r['track']}_c{r['start']:.1f}.wav", r["start"], r["dur"]))
    print(f"[pool] {len(pool)} candidates (p2 c1 + bd c2 + bc all)")

    # ---- 2) ECAPA utterance + chunk purity
    keep = []
    for src, p, st, dur in pool:
        if not (MIN_DUR <= dur <= MAX_DUR):
            continue
        t = load16k(p)
        sy = float(emb(t) @ anchor)
        if sy < SY_MIN:
            continue
        x = t.squeeze().numpy()
        n = int(1.6 * 16000)
        nch = max(1, (len(x) - n) // n + 1) if len(x) >= n else 1
        chunk_min = 1.0
        if len(x) >= n:
            cs = [float(emb(torch.from_numpy(x[i:i + n]).unsqueeze(0)) @ anchor) for i in range(0, len(x) - n + 1, n)]
            chunk_min = min(cs)
            if chunk_min < CHUNK_MIN:
                continue
        keep.append({"src": src, "path": str(p), "start": st, "dur": dur, "sy": round(sy, 3), "chunk_min": round(chunk_min, 3)})
    print(f"[ecapa] kept {len(keep)} clips, {sum(r['dur'] for r in keep):.0f}s  (by src: "
          + ", ".join(f"{s}={sum(1 for r in keep if r['src']==s)}" for s in ['p2','bd','bc']) + ")")

    # ---- 3) faster-whisper JA transcripts
    from faster_whisper import WhisperModel
    wm = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    for r in keep:
        segs, info = wm.transcribe(r["path"], language="ja", beam_size=5, vad_filter=False)
        r["text"] = "".join(s.text for s in segs).strip().replace(" ", "")
    drop_tx = [r for r in keep if len(r.get("text", "")) < 6]
    for r in drop_tx:
        keep.remove(r)
    print(f"[asr] dropped {len(drop_tx)} near-empty transcripts; {len(keep)} clips, {sum(r['dur'] for r in keep):.0f}s")

    # ---- 4) assemble
    WAVD.mkdir(parents=True, exist_ok=True)
    cnt = {}
    list_rows = []
    for r in sorted(keep, key=lambda r: (r["src"], r["start"])):
        cnt[r["src"]] = cnt.get(r["src"], 0) + 1
        name = f"{r['src']}_{cnt[r['src']]:03d}.wav"
        shutil.copy(r["path"], WAVD / name)
        r["wav"] = name
        list_rows.append(f"wav/{name}|{SPEAKER}|JP|{r['text']}")
        print(f"  {name} {r['dur']:5.1f}s sy={r['sy']} | {r['text'][:56]}")
    (OUT / f"{SPEAKER}.list").write_text("\n".join(list_rows) + "\n", encoding="utf-8")
    json.dump(keep, open(OUT / "selection_manifest.json", "w"), ensure_ascii=False, indent=1)

    # ---- 5) prompts (deploy plan §2.3 prompt_map seeds)
    pm = {}
    for style, (rel, text) in PROMPTS.items():
        dst = OUT / f"prompt_{style}.wav"
        shutil.copy(BASE / rel, dst)
        pm[style] = {"wav": dst.name, "text": text}
    (OUT / "prompt_map.json").write_text(json.dumps(pm, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[done] {OUT}: {len(list_rows)} wavs, {sum(r['dur'] for r in keep):.0f}s speech, 3 prompts")


if __name__ == "__main__":
    main()
