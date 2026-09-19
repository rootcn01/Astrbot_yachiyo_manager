# Score BD clips against BOTH Yachiyo anchors (recutB dense + alarmP2 solo V2); simV2 usually cleaner.
import json
import sys
import wave

import numpy as np

BD = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl\BV1Jhe16EELF_main.wav"
REFS = {
    "sim": r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\candidates\recutB_yachiyo_dense.wav",
    "simV2": r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\candidates\alarmP2_yachiyo_solo_v1.wav",
}
SEGS = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl\bd_segments.json"
OUT = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl\bd_scored.json"
SR = 16000


def load16k(path):
    with wave.open(path, "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        sr = w.getframerate()
    if sr != SR:
        t = np.arange(len(x)) / sr
        x = np.interp(np.arange(int(len(x) * SR / sr)) / SR, t, x).astype(np.float32)
    return x


def mel_bank(nfilt=40, nfft=1024):
    lo, hi = 80, 7600
    def hz2mel(f): return 2595 * np.log10(1 + f / 700)
    def mel2hz(m): return 700 * (10 ** (m / 2595) - 1)
    pts = np.linspace(hz2mel(lo), hz2mel(hi), nfilt + 2)
    bins = np.floor((nfft + 1) * mel2hz(pts) / SR).astype(int)
    bank = np.zeros((nfilt, nfft // 2 + 1))
    for i in range(nfilt):
        for k in range(bins[i], bins[i + 1]):
            bank[i, k] = (k - bins[i]) / max(1, bins[i + 1] - bins[i])
        for k in range(bins[i + 1], bins[i + 2]):
            bank[i, k] = (bins[i + 2] - k) / max(1, bins[i + 2] - bins[i + 1])
    return bank


BANK = mel_bank()
NFFT = 1024


def mel_ltas(x):
    fl, hop = NFFT, NFFT // 2
    feats = []
    for off in range(0, len(x) - fl, hop):
        seg = x[off:off + fl]
        if float(np.mean(seg ** 2)) < 4e-4:
            continue
        spec = np.abs(np.fft.rfft(seg * np.hanning(fl).astype(np.float32))) ** 2
        feats.append(np.log(BANK @ spec + 1e-10))
    if not feats:
        return None
    return np.mean(feats, axis=0)


def cosine(a, b):
    a = a - a.mean()
    b = b - b.mean()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    x = load16k(BD)
    refs = {k: mel_ltas(load16k(p)) for k, p in REFS.items()}
    segs = json.load(open(SEGS))
    out = []
    for c in segs:
        v = mel_ltas(x[int(c["start"] * SR):int(c["end"] * SR)])
        if v is None:
            continue
        out.append({**c, **{k: round(cosine(v, r), 4) for k, r in refs.items()}})
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    sims = np.array([max(c["sim"], c["simV2"]) for c in out])
    print(f"scored {len(out)}; max-anchor percentiles 10/25/50/75/90:", np.percentile(sims, [10, 25, 50, 75, 90]).round(3))
    out.sort(key=lambda c: -max(c["sim"], c["simV2"]))
    print("TOP 15:")
    for c in out[:15]:
        print(f"  {c['start']:8.1f}-{c['end']:8.1f} {c['dur']:5.1f}s f0={c['f0']} sim={c['sim']} simV2={c['simV2']}")


if __name__ == "__main__":
    main()
