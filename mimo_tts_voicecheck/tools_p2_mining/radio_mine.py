# radio_mine.py — Memories & Discoveries (早見沙織 hosted radio) natural-register supplement mining.
# Source: BV1FrJK6MET4_audio.m4s (2026-06-09, 7214s). Output: finetune_dataset_natural/
# Pipeline (each step resumable, run: python radio_mine.py <step>):
#   transcode -> segment -> cutclips -> ecapa -> asr -> package -> stats
# Speaker claiming uses the HOST anchor (mean of 7 hayami_w* windows), NOT the character anchor:
# natural register vs character anchor is only ~0.33, vs host anchor it is same-domain.
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")
SRC = BASE / "BV1FrJK6MET4_audio.m4s"
FULL = BASE / "radio_full.wav"
SEGS_J = BASE / "radio_segments.json"
ECAPA_J = BASE / "radio_ecapa.json"
SEL_J = BASE / "radio_selected.json"
ASR_J = BASE / "radio_asr.jsonl"
CLIPS = BASE / "radio_all"
OUT = BASE.parents[1] / "finetune_dataset_natural"
WAVD = OUT / "wav"

SR = 16000
FRAME = int(0.030 * SR)
GAP_MERGE = int(0.45 * SR)
MIN_CLIP = int(1.0 * SR)
MAX_CLIP = int(14.0 * SR)
HOST_WINS = [300, 900, 1800, 2700, 3600, 4500, 5400]  # w6300 excluded (task spec)

K = 4                # k-means clusters (spec; NOTE: claiming failed, see anchor2/select2)
SEEDS = 8
SY_MIN = 0.40        # utterance cos to host anchor (natural talk, slightly looser than chunk-strict char domain)
CHUNK_MIN = 0.30     # worst 1.6s chunk floor for >=3.2s clips (looser than char domain 0.35)
CHUNK_APPLY = 3.2    # apply chunk purity only to clips >= 3.2s
MIN_DUR, MAX_DUR = 1.5, 12.0
SPEAKER = "yachiyo"

# --- v2 selection (see README: the 7-window host anchor was music-contaminated; w300=song,
# w2700=Taylor Swift, w6300=vocaloid, w1800/w5400=instrumental->hallucinated transcripts.
# Only w900 is transcript-verified clean host talk, so v2 anchors on w900 alone and uses an
# ASR-confidence + text-style screen as the primary music/host discriminator, ECAPA secondary.)
SCREEN_J = BASE / "radio_screen.jsonl"
PREFILTER_J = BASE / "radio_prefilter.json"
SEL2_J = BASE / "radio_selected2.json"
ASR2_J = BASE / "radio_asr2.jsonl"
ANCHOR2_J = BASE / "radio_anchor2.json"
HALLUC = {"ご視聴ありがとうございました", "ご視聴ありがとうございました。",
          "ご清聴ありがとうございました", "おわり", "終わり", "Memories,Discoveries"}


def load16k(path):
    with wave.open(str(path), "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        if ch == 2:
            x = x.reshape(-1, 2).mean(axis=1)
    return x, sr


def speech_mask(x):
    n = len(x) // FRAME
    rms = np.empty(n, dtype=np.float32)
    for i in range(0, n, 20000):  # chunked to cap memory
        blk = x[i * FRAME:(i + 20000) * FRAME]
        blk = blk[:len(blk) // FRAME * FRAME].reshape(-1, FRAME)
        rms[i:i + blk.shape[0]] = np.sqrt(np.mean(blk ** 2, axis=1))
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
    # Enforce the 14s piece cap (spec): search the lowest-energy cut point only within
    # [seg_start+6s, seg_start+14s]. bc_mine's original unbounded search let pieces run to
    # 100s+ on this BGM-heavy radio (min-energy points are sparse), starving the dur<=12 filter.
    out, seg_start = [], s
    guard = 0
    while e - seg_start >= MAX_CLIP + SR and guard < 300:
        guard += 1
        window = int(0.2 * SR)
        hi = min(e - int(0.5 * SR), seg_start + MAX_CLIP)
        best_t, best_e = None, 1e9
        for t in range(seg_start + int(6 * SR), hi, window):
            en = float(np.mean(x[t:t + window] ** 2))
            if en < best_e:
                best_e, best_t = en, t
        if best_t is None:
            best_t = max(seg_start + int(6 * SR), hi - window)
        out.append((seg_start, best_t))
        seg_start = best_t + int(0.15 * SR)
    out.append((seg_start, e))
    return out


def step_transcode():
    if FULL.exists():
        print(f"[transcode] exists, skip: {FULL}")
        return
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SRC), "-vn",
                    "-ac", "1", "-ar", str(SR), "-sample_fmt", "s16", str(FULL)], check=True)
    print(f"[transcode] -> {FULL} ({FULL.stat().st_size / 1e6:.0f} MB)")


def step_segment():
    if SEGS_J.exists():
        print(f"[segment] exists, skip: {SEGS_J}")
        return
    x, _ = load16k(FULL)
    clips = []
    for s, e in merge_runs(speech_mask(x)):
        pieces = split_long(x, s, e) if e - s > MAX_CLIP else [(s, e)]
        for a, b in pieces:
            if b - a < MIN_CLIP:
                continue
            clips.append({"start": round(a / SR, 2), "end": round(b / SR, 2),
                          "dur": round((b - a) / SR, 2)})
    json.dump(clips, open(SEGS_J, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[segment] {len(clips)} clips, {sum(c['dur'] for c in clips):.0f}s speech "
          f"(of {len(x) / SR:.0f}s total)")


def clip_name(start):
    return f"clip_{start:.1f}.wav"


def step_cutclips():
    CLIPS.mkdir(exist_ok=True)
    segs = json.load(open(SEGS_J, encoding="utf-8"))
    n_new = 0
    for i, c in enumerate(segs):
        p = CLIPS / clip_name(c["start"])
        if p.exists():
            continue
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(c["start"]), "-i", str(FULL),
                        "-t", str(c["dur"]), "-ac", "1", "-ar", str(SR), str(p)], check=True)
        n_new += 1
        if (i + 1) % 100 == 0:
            print(f"[cutclips] {i + 1}/{len(segs)} ...", flush=True)
    print(f"[cutclips] {len(segs)} segments, {n_new} newly cut -> {CLIPS}")


def step_ecapa():
    if SEL_J.exists():
        print(f"[ecapa] exists, skip: {SEL_J}")
        return
    import torch
    import torchaudio
    from scipy.cluster.vq import kmeans2
    from speechbrain.inference.speaker import EncoderClassifier

    def load16k_tensor(p):
        x, sr = load16k(p)
        t = torch.from_numpy(x).unsqueeze(0)
        if sr != 16000:
            t = torchaudio.functional.resample(t, sr, 16000)
        return t

    m = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                       savedir=str(BASE.parents[1] / "_tmp/ecapa"),
                                       run_opts={"device": "cpu"})

    def emb(x):
        with torch.no_grad():
            e = m.encode_batch(x).squeeze().numpy()
        return e / np.linalg.norm(e)

    # host anchor = mean of the 7 window embeddings, renormalized (task spec)
    host_vec = np.mean([emb(load16k_tensor(BASE / f"hayami_w{t}.wav")) for t in HOST_WINS], axis=0)
    host = host_vec / np.linalg.norm(host_vec)

    segs = json.load(open(SEGS_J, encoding="utf-8"))
    rows, X = [], []
    for i, c in enumerate(segs):
        p = CLIPS / clip_name(c["start"])
        if not p.exists():
            continue
        e = emb(load16k_tensor(p))
        X.append(e)
        rows.append({"start": c["start"], "dur": c["dur"], "sy": round(float(e @ host), 3)})
        if (i + 1) % 100 == 0:
            print(f"[ecapa] embedded {i + 1}/{len(segs)} ...", flush=True)
    X = np.stack(X)

    # k-means k=4, multi-seed, keep min intra
    best = None
    for seed in range(SEEDS):
        cent, lab = kmeans2(X, K, minit="++", seed=seed, iter=50)
        intra = float(np.mean([np.linalg.norm(X[i] - cent[lab[i]]) for i in range(len(X))]))
        if best is None or intra < best[0]:
            best = (intra, cent, lab)
    intra, cent, lab = best
    print(f"[ecapa] {len(rows)} clips k={K} intra={intra:.3f}")
    claimed = -1
    for ci, c in enumerate(cent):
        n = int((lab == ci).sum())
        secs = sum(r["dur"] for i, r in enumerate(rows) if lab[i] == ci)
        cos = float(c @ host)
        print(f"   c{ci} n={n:4d} {secs:6.0f}s host_cos={cos:+.3f}")
    claimed = int(np.argmax([float(c @ host) for c in cent]))
    print(f"[ecapa] claimed cluster c{claimed} (host_cos={float(cent[claimed] @ host):+.3f})")
    for i, r in enumerate(rows):
        r["lab"] = int(lab[i])

    # per-clip filter: claimed cluster + sy>=0.40 + dur 1.5-12 + chunk purity >=0.30 for >=3.2s
    sel = []
    n_dur = n_sy = n_chunk = 0
    for i, r in enumerate(rows):
        if lab[i] != claimed:
            continue
        if not (MIN_DUR <= r["dur"] <= MAX_DUR):
            n_dur += 1
            continue
        if r["sy"] < SY_MIN:
            n_sy += 1
            continue
        x = load16k_tensor(CLIPS / clip_name(r["start"])).squeeze().numpy()
        n = int(1.6 * SR)
        if r["dur"] >= CHUNK_APPLY and len(x) >= 2 * n:
            cs = [float(emb(torch.from_numpy(x[j:j + n]).unsqueeze(0)) @ host)
                  for j in range(0, len(x) - n + 1, n)]
            r["chunk_min"] = round(min(cs), 3)
            if r["chunk_min"] < CHUNK_MIN:
                n_chunk += 1
                continue
        else:
            r["chunk_min"] = None
        sel.append(r)
    json.dump(rows, open(ECAPA_J, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(sel, open(SEL_J, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[ecapa] selected {len(sel)} clips, {sum(r['dur'] for r in sel):.0f}s "
          f"(dropped: dur={n_dur}, sy={n_sy}, chunk={n_chunk})")


def step_asr():
    from faster_whisper import WhisperModel
    sel = json.load(open(SEL_J, encoding="utf-8"))
    done = {}
    if ASR_J.exists():
        for line in open(ASR_J, encoding="utf-8"):
            r = json.loads(line)
            done[round(r["start"], 1)] = r["text"]
    todo = [r for r in sel if round(r["start"], 1) not in done]
    print(f"[asr] {len(sel)} selected, {len(done)} cached, {len(todo)} to go "
          f"(~{sum(r['dur'] for r in todo):.0f}s audio)", flush=True)
    if not todo:
        return
    wm = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    t0 = __import__("time").time()
    with open(ASR_J, "a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            segs, info = wm.transcribe(str(CLIPS / clip_name(r["start"])), language="ja",
                                       beam_size=5, vad_filter=False)
            text = "".join(s.text for s in segs).strip().replace(" ", "")
            f.write(json.dumps({"start": r["start"], "dur": r["dur"], "text": text},
                               ensure_ascii=False) + "\n")
            f.flush()
            if i % 20 == 0 or i == len(todo):
                rate = sum(x["dur"] for x in todo[:i]) / max(1e-9, __import__("time").time() - t0)
                print(f"[asr] {i}/{len(todo)} ({rate:.1f}x realtime) | {text[:50]}", flush=True)


def get_model():
    from speechbrain.inference.speaker import EncoderClassifier
    import torch
    import torchaudio

    def load16k_tensor(p):
        x, sr = load16k(p)
        t = torch.from_numpy(x).unsqueeze(0)
        if sr != 16000:
            t = torchaudio.functional.resample(t, sr, 16000)
        return t

    m = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                       savedir=str(BASE.parents[1] / "_tmp/ecapa"),
                                       run_opts={"device": "cpu"})

    def emb(x):
        with torch.no_grad():
            e = m.encode_batch(x).squeeze().numpy()
        return e / np.linalg.norm(e)

    return emb, load16k_tensor


def step_anchor2():
    """Clean host anchor from w900 ONLY (transcript-verified hosting talk), chunked 5s,
    robust to edge jingle. Calibrates against known music windows/clips."""
    if ANCHOR2_J.exists():
        print(f"[anchor2] exists, skip: {ANCHOR2_J}")
        return
    import torch
    emb, load16k_tensor = get_model()
    x = load16k_tensor(BASE / "hayami_w900.wav").squeeze().numpy()
    n = 5 * SR
    chunks = [emb(torch.from_numpy(x[i:i + n]).unsqueeze(0))
              for i in range(0, len(x) - n + 1, n) if float(np.mean(x[i:i + n] ** 2)) > 1e-4]
    med = np.median(np.stack(chunks), axis=0)
    med /= np.linalg.norm(med)
    keep = [c for c in chunks if float(c @ med) >= 0.55]
    anchor = np.mean(keep, axis=0)
    anchor /= np.linalg.norm(anchor)
    print(f"[anchor2] w900: {len(chunks)} chunks -> {len(keep)} kept for anchor")

    # calibration: songs must be low, known host talk must be high
    cal_music = {"w300(song)": BASE / "hayami_w300.wav", "w2700(TS-song)": BASE / "hayami_w2700.wav",
                 "w6300(vocaloid)": BASE / "hayami_w6300.wav", "w1800(instr?)": BASE / "hayami_w1800.wav",
                 "w5400(instr?)": BASE / "hayami_w5400.wav"}
    cal_host = {"w4500(host+guest)": BASE / "hayami_w4500.wav", "clip@42.1(time-sign)": CLIPS / "clip_42.1.wav",
                "clip@56.3(self-intro)": CLIPS / "clip_56.3.wav", "clip@5043.6(talk)": CLIPS / "clip_5043.6.wav",
                "clip@5187.0(talk)": CLIPS / "clip_5187.0.wav", "clip@5948.6(talk)": CLIPS / "clip_5948.6.wav"}
    for k, p in cal_music.items():
        print(f"   [music?] {k:24s} cos={float(emb(load16k_tensor(p)) @ anchor):+.3f}")
    for k, p in cal_host.items():
        print(f"   [host?]  {k:24s} cos={float(emb(load16k_tensor(p)) @ anchor):+.3f}")
    np.save(BASE / "radio_anchor2.npy", anchor)
    json.dump({"source": "hayami_w900", "chunks": len(chunks), "kept": len(keep)},
              open(ANCHOR2_J, "w"))


def step_prefilter():
    """ECAPA-embed ALL clips vs clean w900 anchor -> radio_prefilter.json.
    Music calibrates at ~0.0, host talk 0.35-0.8, so sy>=0.30 pre-filters before the
    (much slower) ASR screen."""
    if PREFILTER_J.exists():
        print(f"[prefilter] exists, skip: {PREFILTER_J}")
        return
    emb, load16k_tensor = get_model()
    anchor = np.load(BASE / "radio_anchor2.npy")
    segs = json.load(open(SEGS_J, encoding="utf-8"))
    out = []
    for i, c in enumerate(segs):
        p = CLIPS / clip_name(c["start"])
        if not p.exists():
            continue
        out.append({"start": c["start"], "dur": c["dur"],
                    "sy": round(float(emb(load16k_tensor(p)) @ anchor), 3)})
        if (i + 1) % 200 == 0:
            print(f"[prefilter] {i + 1}/{len(segs)} ...", flush=True)
    json.dump(out, open(PREFILTER_J, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ys = [r for r in out if r["sy"] >= 0.30]
    print(f"[prefilter] {len(out)} embedded; sy>=0.30: {len(ys)} clips "
          f"{sum(r['dur'] for r in ys):.0f}s; sy>=0.40: {len([r for r in out if r['sy'] >= 0.40])} clips")


def step_screen():
    """Greedy ASR pass over sy>=0.30 survivors -> radio_screen.jsonl (start,dur,text,lp,ns).
    Resumable; primary host-talk vs music/lyrics discriminator."""
    from faster_whisper import WhisperModel
    pre = json.load(open(PREFILTER_J, encoding="utf-8"))
    cand = [r for r in pre if r["sy"] >= 0.30]
    done = set()
    if SCREEN_J.exists():
        for line in open(SCREEN_J, encoding="utf-8"):
            done.add(round(json.loads(line)["start"], 1))
    todo = [r for r in cand if round(r["start"], 1) not in done]
    print(f"[screen] {len(cand)} candidates (sy>=0.30), {len(done)} cached, {len(todo)} to go "
          f"(~{sum(r['dur'] for r in todo):.0f}s audio)", flush=True)
    if not todo:
        return
    wm = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=12)
    t0 = __import__("time").time()
    aud = 0.0
    with open(SCREEN_J, "a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            sgs, info = wm.transcribe(str(CLIPS / clip_name(r["start"])), language="ja",
                                      beam_size=1, vad_filter=False)
            sgs = list(sgs)
            text = "".join(s.text for s in sgs).strip().replace(" ", "")
            lp = sum(s.avg_logprob * len(s.text) for s in sgs) / max(1, sum(len(s.text) for s in sgs))
            ns = max((s.no_speech_prob for s in sgs), default=1.0)
            f.write(json.dumps({"start": r["start"], "dur": r["dur"], "sy": r["sy"],
                                "text": text, "lp": round(lp, 3), "ns": round(ns, 3)},
                               ensure_ascii=False) + "\n")
            f.flush()
            aud += r["dur"]
            if i % 25 == 0 or i == len(todo):
                print(f"[screen] {i}/{len(todo)} ({aud / max(1e-9, __import__('time').time() - t0):.1f}x realtime)",
                      flush=True)


def looks_like_talk(text, lp, ns, dup_short):
    if not text or len(text) < 6:
        return False, "empty"
    if text in HALLUC:
        return False, "halluc"
    if text in dup_short:
        return False, "dup"
    if ns > 0.5:
        return False, "nospeech"
    if lp < -0.55:
        return False, "lowconf"
    latin = sum(c.isascii() and c.isalpha() for c in text) / len(text)
    if latin > 0.5:
        return False, "latin"
    if len(set(text)) < max(4, len(text) * 0.18):  # memememe / sickwithmesickwithme
        return False, "lowdiv"
    return True, ""


def step_select2():
    """v2 selection: ASR text screen -> ECAPA vs clean w900 anchor (sy>=0.40) -> chunk purity."""
    if SEL2_J.exists():
        print(f"[select2] exists, skip: {SEL2_J}")
        return
    import torch
    emb, load16k_tensor = get_model()
    anchor = np.load(BASE / "radio_anchor2.npy")
    pre = {round(r["start"], 1): r["sy"] for r in json.load(open(PREFILTER_J, encoding="utf-8"))}
    screen = [json.loads(l) for l in open(SCREEN_J, encoding="utf-8")]
    screen = [r for r in screen if pre.get(round(r["start"], 1), 0) >= 0.30]  # sy-gated
    from collections import Counter
    c = Counter(r["text"] for r in screen)
    dup_short = {t for t, n in c.items() if n >= 2 and len(t) < 25}
    rows = []
    stats = {}
    for r in screen:
        ok, why = looks_like_talk(r["text"], r["lp"], r["ns"], dup_short)
        stats[why or "ok"] = stats.get(why or "ok", 0) + 1
        if ok:
            rows.append(r)
    print(f"[select2] text screen: {stats}")
    sel = []
    n_dur = n_sy = n_chunk = 0
    for r in sorted(rows, key=lambda r: r["start"]):
        if not (MIN_DUR <= r["dur"] <= MAX_DUR):
            n_dur += 1
            continue
        p = CLIPS / clip_name(r["start"])
        t = load16k_tensor(p)
        sy = float(emb(t) @ anchor)
        if sy < SY_MIN:
            n_sy += 1
            continue
        x = t.squeeze().numpy()
        n = int(1.6 * SR)
        chunk_min = None
        if r["dur"] >= CHUNK_APPLY and len(x) >= 2 * n:
            cs = [float(emb(torch.from_numpy(x[j:j + n]).unsqueeze(0)) @ anchor)
                  for j in range(0, len(x) - n + 1, n)]
            chunk_min = round(min(cs), 3)
            if chunk_min < CHUNK_MIN:
                n_chunk += 1
                continue
        sel.append({"start": r["start"], "dur": r["dur"], "sy": round(sy, 3),
                    "chunk_min": chunk_min, "lp": r["lp"], "text": r["text"]})
    json.dump(sel, open(SEL2_J, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[select2] {len(sel)} clips, {sum(r['dur'] for r in sel):.0f}s "
          f"(dropped: dur={n_dur}, sy={n_sy}, chunk={n_chunk})")
    for r in sel:
        print(f"   @{r['start']:7.1f} {r['dur']:5.1f}s sy={r['sy']:.2f} lp={r['lp']:5.2f} | {r['text'][:58]}")


def step_asr2():
    """beam=5 re-transcription of the final v2 selection for training text quality."""
    sel = json.load(open(SEL2_J, encoding="utf-8"))
    done = {}
    if ASR2_J.exists():
        for line in open(ASR2_J, encoding="utf-8"):
            r = json.loads(line)
            done[round(r["start"], 1)] = True
    todo = [r for r in sel if round(r["start"], 1) not in done]
    print(f"[asr2] {len(sel)} selected, {len(done)} cached, {len(todo)} to go "
          f"(~{sum(r['dur'] for r in todo):.0f}s audio)", flush=True)
    if not todo:
        return
    from faster_whisper import WhisperModel
    wm = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    t0 = __import__("time").time()
    aud = 0.0
    with open(ASR2_J, "a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            sgs, info = wm.transcribe(str(CLIPS / clip_name(r["start"])), language="ja",
                                      beam_size=5, vad_filter=False)
            text = "".join(s.text for s in sgs).strip().replace(" ", "")
            f.write(json.dumps({"start": r["start"], "dur": r["dur"], "text": text},
                               ensure_ascii=False) + "\n")
            f.flush()
            aud += r["dur"]
            if i % 20 == 0 or i == len(todo):
                print(f"[asr2] {i}/{len(todo)} ({aud / max(1e-9, __import__('time').time() - t0):.1f}x realtime) "
                      f"| {text[:50]}", flush=True)


def step_package():
    sel = json.load(open(SEL2_J, encoding="utf-8"))
    asr = {}
    for line in open(ASR2_J, encoding="utf-8"):
        r = json.loads(line)
        asr[round(r["start"], 1)] = r["text"]
    keep, drop_tx = [], 0
    for r in sorted(sel, key=lambda r: r["start"]):
        t = asr.get(round(r["start"], 1), r.get("text", ""))  # beam5 text, fallback screen text
        if len(t) < 6 or t in HALLUC:  # near-empty / boilerplate hallucination
            drop_tx += 1
            continue
        keep.append({**r, "text": t})
    WAVD.mkdir(parents=True, exist_ok=True)
    manifest, list_rows = [], []
    for i, r in enumerate(keep, 1):
        name = f"na_{i:03d}.wav"
        shutil.copy(CLIPS / clip_name(r["start"]), WAVD / name)
        manifest.append({"wav": name, "path": str(CLIPS / clip_name(r["start"])),
                         "start": r["start"], "dur": r["dur"], "sy": r["sy"],
                         "chunk_min": r["chunk_min"], "text": r["text"]})
        list_rows.append(f"wav/{name}|{SPEAKER}|JP|{r['text']}")
    (OUT / f"{SPEAKER}_natural.list").write_text("\n".join(list_rows) + "\n", encoding="utf-8")
    json.dump(manifest, open(OUT / "manifest_natural.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    total = sum(r["dur"] for r in keep)
    stats_block = step_stats(manifest, write_readme=True)
    print(f"[package] {len(keep)} wavs, {total:.1f}s -> {OUT} (dropped {drop_tx} near-empty transcripts)")


def step_stats(manifest=None, write_readme=False):
    if manifest is None:
        manifest = json.load(open(OUT / "manifest_natural.json", encoding="utf-8"))
    durs = [r["dur"] for r in manifest]
    print(f"[stats] clips={len(manifest)} total={sum(durs):.1f}s "
          f"mean={np.mean(durs):.1f}s min={min(durs):.1f}s max={max(durs):.1f}s")
    print("[stats] hourly distribution:")
    lines = []
    for h in range(2):
        sub = [r for r in manifest if int(r["start"] // 3600) == h]
        s = sum(r["dur"] for r in sub)
        print(f"   hour {h}: {len(sub):3d} clips, {s:6.1f}s")
        lines.append((h, len(sub), s))
    print("[stats] 15-min bins:")
    bins = []
    for b in range(8):
        sub = [r for r in manifest if int(r["start"] // 900) == b]
        s = sum(r["dur"] for r in sub)
        print(f"   {b * 15:02d}-{(b + 1) * 15:02d}min: {len(sub):3d} clips, {s:6.1f}s")
        bins.append((b, len(sub), s))
    if write_readme:
        write_readme_file(manifest, lines, bins)
    return {"clips": len(manifest), "total": sum(durs), "hourly": lines, "bins": bins}


def write_readme_file(manifest, hourly, bins):
    total = sum(r["dur"] for r in manifest)
    bin_txt = "\n".join(f"| {b * 15:02d}-{(b + 1) * 15:02d}min | {n} | {s:.0f}s |" for b, n, s in bins)
    top10 = sorted(manifest, key=lambda r: -r["dur"])[:10]
    top_txt = "\n".join(f"- `na_{manifest.index(r) + 1:03d}.wav` ({r['dur']:.1f}s @{r['start']:.0f}s) {r['text']}"
                        for r in top10)
    readme = f"""# 早見沙織 自然语域补充集（finetune_dataset_natural）· 2026-09-19

**{len(manifest)} 片 / {total:.1f}s（~{total / 60:.1f} 分钟）主持人自然谈话语域。**
与主数据集 `finetune_dataset/`（角色域 108 片）**源不同、文件名前缀不同（na_ vs p2_/bd_/bc_），零重叠**。

## 来源

- 广播「Memories & Discoveries」2026-06-09 期（B 站 `BV1FrJK6MET4`，audio m4s 111kbps → 16k/mono wav，全长 7214s ≈ 2h）。
- 主持人早見沙織单人时段；节目含嘉宾段与音乐段，已用说话人过滤剔除。

## 方法（tools_p2_mining/radio_mine.py，可分步重跑）

1. ffmpeg 全量转码 → 静音切分（30ms 帧 / 70 分位×0.28 阈 / 0.45s 合并 / 1.0s 下限 + 长段最低能量点切，**切点搜索限制在 14s 窗口内强制上限**——bc_mine 原版无界搜索在本节目 BGM 下会产生 100s+ 单片）。
2. **锚修正**：原计划的 7 窗 host 锚经转写取证被证伪——w300=英文歌、w2700=Taylor Swift、w6300=初音ミク系歌、w1800/w5400=纯音乐（whisper 全幻觉「ご視聴ありがとうございました」）、w4500=主持+嘉宾古典解说角；仅 **w900 是干净主持人读信环节**。v2 锚 = w900 切 5s 块嵌入的稳健均值。
3. **全量 ASR 筛**（faster-whisper turbo beam1 快扫全部切片）：文字风格判别主持谈话 vs 歌词/幻觉（幻觉黑名单 + 置信度 lp<-0.55 + 拉丁占比 + 低字多样性 + 短文本重复剔除）。k-means k=4 认领方案作废：污染锚下认领簇 c0 实为女声歌曲簇（88/111 片转写为同一幻觉句）。
4. ECAPA 逐片把关（对 w900 干净锚）：utterance cos≥0.40 + 时长 1.5-12s + ≥3.2s 片最差 1.6s 块≥0.30。
5. beam=5 重转写定稿训练文本；<6 字符/黑名单丢弃。

## 统计

- 按小时段：{f"{hourly[0][1]} clips/{hourly[0][2]:.0f}s (0-1h), {hourly[1][1]} clips/{hourly[1][2]:.0f}s (1-2h)"}
- 15 分钟分布：

| 时段 | 片数 | 秒数 |
|---|---|---|
{bin_txt}

## 使用建议

- **自然语域补充集**：为 TTS 增加日常谈话的自然韵律/填充/语速变化，勿当主力训练集。
- 与角色域混合训练时，本集占比**勿超 30-40%**，否则角色音色与语域会被日常腔稀释。
- 训练时说话人列与主集一致用 `yachiyo`（同模型同说话人名），但本集独立成包，混合比例训练时再定。
- `hayami_natural.list` 为 GPT-SoVITS 格式：`wav/na_NNN.wav|yachiyo|JP|文本`。
- `manifest_natural.json` 含 start/dur/sy/chunk_min/text，供复核与再筛。

## 最长 10 条（人肉核验主持人风格用）

{top_txt}
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")


STEPS = {"transcode": step_transcode, "segment": step_segment, "cutclips": step_cutclips,
         "ecapa": step_ecapa, "asr": step_asr, "anchor2": step_anchor2, "prefilter": step_prefilter,
         "screen": step_screen, "select2": step_select2, "asr2": step_asr2,
         "package": step_package, "stats": step_stats}

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step == "all":
        for name in ["transcode", "segment", "cutclips", "ecapa", "asr",
                     "anchor2", "prefilter", "screen", "select2", "asr2", "package"]:
            STEPS[name]()
    else:
        STEPS[step]()
