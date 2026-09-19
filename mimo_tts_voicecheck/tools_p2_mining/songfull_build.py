# Build A_songfull dataset: 106 narrow base + full-song wideband vocals cut by lrc timestamps.
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck")
LRC = Path(r"E:\CloudMusic\VipSongsDownload")
SEP = BASE / "separated/htdemucs"
OUT = BASE / "finetune_dataset_songfull"
SR = 16000
MAX_CLIP = 8.0
MIN_CLIP = 1.5

SONGS = [
    ("yuigot,月見ヤチヨ(cv.早見沙織),超かぐや姫！ - Remember", "sgR"),
    ("Aqu3ra,月見ヤチヨ(cv.早見沙織),超かぐや姫！ - 星降る海", "sgS"),
]


def load_vocals(stem):
    tmp = OUT / f"tmp_{stem[:6]}.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SEP / stem / "vocals.wav"),
                    "-ac", "1", "-ar", "16000", str(tmp)], check=True)
    w = wave.open(str(tmp))
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    w.close()
    tmp.unlink()
    return x


def parse_lrc(path):
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\[(\d+):(\d+)([.:]\d+)?\](.*)", line.strip())
        if not m:
            continue
        t = int(m.group(1)) * 60 + int(m.group(2)) + (float(m.group(3).replace(":", ".")) if m.group(3) else 0)
        text = m.group(4).strip()
        if text and not text.startswith("{"):
            rows.append((t, text))
    return rows


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    (OUT / "wav").mkdir(parents=True, exist_ok=True)
    rows = []
    import shutil
    for l in open(BASE / "finetune_dataset/yachiyo.list", encoding="utf-8"):
        wav = l.split("|")[0].split("/")[1]
        shutil.copy(BASE / "finetune_dataset/wav" / wav, OUT / "wav" / wav)
        rows.append(l.rstrip("\n"))
    for stem, tag in SONGS:
        x = load_vocals(stem)
        lrc = parse_lrc(LRC / f"{stem}.lrc")
        made = 0
        for i, (t, text) in enumerate(lrc):
            t_end = lrc[i + 1][0] if i + 1 < len(lrc) else t + MAX_CLIP
            dur = min(t_end - t, MAX_CLIP)
            if dur < MIN_CLIP or len(text) < 6:
                continue
            s, e = int(t * SR), int((t + dur) * SR)
            seg = x[s:e]
            if float(np.sqrt(np.mean(seg ** 2))) < 0.02:  # skip breath/silence
                continue
            name = f"{tag}_{int(t):03d}.wav"
            ww = wave.open(str(OUT / "wav" / name), "wb")
            ww.setnchannels(1); ww.setsampwidth(2); ww.setframerate(SR)
            ww.writeframes((seg * 32768).astype(np.int16).tobytes()); ww.close()
            rows.append(f"wav/{name}|yachiyo|JP|{text}")
            made += 1
        print(f"[{tag}] {made} clips from {stem.split(' - ')[1]}")
    (OUT / "yachiyo.list").write_text("\n".join(rows) + "\n", encoding="utf-8")
    n_song = sum(1 for r in rows if r.split("|")[0].startswith("wav/sg"))
    import wave as W
    tot = tot_song = 0.0
    for r in rows:
        wv = W.open(str(OUT / r.split("|")[0])); d = wv.getnframes() / wv.getframerate(); tot += d
        if r.split("|")[0].startswith("wav/sg"): tot_song += d
    print(f"[done] {len(rows)} rows | song {tot_song:.0f}s / total {tot:.0f}s = {tot_song/tot:.0%} wideband")


if __name__ == "__main__":
    main()
