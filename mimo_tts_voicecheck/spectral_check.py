#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参考音频频谱取证：量化有效带宽（滚降点）与高频衰减。

用法: python spectral_check.py <音频1> [音频2 ...]     # 无参数=跑内置候选集
依赖: numpy + ffmpeg 在 PATH。解码走 ffmpeg 管道，任何格式都能进。

判读口径（2026-09-19 取证基线,见 optimization-research-2026-09-19.md）:
- 现役参考源 candidate_01 = 74kbps mp3: f99≈5.0kHz, 12kHz 处 -94dB(数字无声)
- 声线辨识所需齿音/气声频段 5-15kHz 完全缺失 => 克隆相似度被硬约束
- 干净 CD 级女声预期 f99>=9kHz 且 10kHz 处 > -35dB(rel band peak)
"""
import subprocess
import sys

import numpy as np

DEFAULTS = [
    r"candidates\candidate_01_alarmapp_yachiyo.mp3",
    r"candidates\candidate_02_allscenes_ep.mp3",
    r"candidates\candidate_03_alarmapp_nextseg.mp3",
    r"candidates\candidate_04_tokuten_bonus.mp3",
    r"candidates\candidate_05_cute_comp.mp3",
    r"candidates\recutB_yachiyo_dense.wav",
]
HERE = __file__.rsplit("\\", 1)[0]


def load_mono(path: str, sr: int = 48000):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr),
         "-f", "f32le", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def ltas(x: np.ndarray, sr: int, nfft: int = 8192):
    """长时平均谱(dB, 相对 100-8000Hz 带内峰值归一)。"""
    win = np.hanning(nfft).astype(np.float32)
    frames = [np.abs(np.fft.rfft(x[o:o + nfft] * win)) ** 2
              for o in range(0, len(x) - nfft, nfft // 2)]
    psd = np.mean(frames, axis=0)
    f = np.fft.rfftfreq(nfft, 1.0 / sr)
    db = 10 * np.log10(psd + 1e-20)
    band = (f >= 100) & (f <= 8000)
    return f, db - db[band].max()


def rolloff(f: np.ndarray, db: np.ndarray, thr: float) -> float:
    idx = np.where((f >= 100) & (f <= 20000))[0]
    cum = np.cumsum(10 ** (db[idx] / 10))
    k = np.searchsorted(cum, thr * cum[-1])
    return float(f[idx[min(k, len(idx) - 1)]])


def report(path: str):
    x = load_mono(path)
    f, db = ltas(x, 48000)
    at = lambda hz: db[np.argmin(np.abs(f - hz))]
    name = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    print(f"{name:<44} f85={rolloff(f,db,.85):>6.0f} f95={rolloff(f,db,.95):>6.0f} "
          f"f99={rolloff(f,db,.99):>6.0f}  dB@10k={at(10000):>6.1f} "
          f"dB@12k={at(12000):>6.1f} dB@16k={at(16000):>6.1f}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:] or DEFAULTS
    for p in args:
        try:
            report(p)
        except subprocess.CalledProcessError:
            print(f"{p}: [E] ffmpeg 解码失败")


if __name__ == "__main__":
    main()
