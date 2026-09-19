# Synthesize the fine-tune AB listening pack: model A (char-only) vs model B (char+natural)
# via inference_cli.py, each 3 sentences x default prompt + 1 happy-prompt variant.
# Run after BOTH trainings finish, from package root, GPU free:
#   runtime\python.exe make_ab_pack.py
import subprocess
import sys
from pathlib import Path

PKGR = Path(__file__).resolve().parent
PY = sys.executable
DS = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\finetune_dataset")
OUT = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\outputs\ab_finetune_2026-09-19")
OUT.mkdir(parents=True, exist_ok=True)

def latest(pattern):
    cands = sorted(PKGR.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not cands:
        sys.exit(f"[abort] no weights match {pattern}")
    return cands[-1]


MODELS = {
    "A": {"gpt": latest("GPT_weights_v2ProPlus/yachiyo_A_char-e*.ckpt"),
          "sovits": latest("SoVITS_weights_v2ProPlus/yachiyo_A_char_e*.pth")},
    "B": {"gpt": latest("GPT_weights_v2ProPlus/yachiyo_B_mix-e*.ckpt"),
          "sovits": latest("SoVITS_weights_v2ProPlus/yachiyo_B_mix_e*.pth")},
}
PROMPTS = {"default": ("wav/p2_002.wav", "お、今日はご機嫌かな、良きかな。"),
           "happy": ("wav/p2_008.wav", "神々のみんなが楽しそうだとやっちょも嬉しいよ"),
           "tender": ("wav/p2_036.wav", "いつももらってばっかりだから、今日は送れて嬉しいな")}
SENTS = {
    "s1": "やっちょのライブ、たくさん見てくれて嬉しいよ。",           # 近训练域（测泛化）
    "s2": "今日は少し疲れたけど、あなたの声を聞いて元気になったよ。もうすぐ夜ご飯の時間だね。",  # 日常闲聊=生产主域
    "s3": "もう遅いから、そろそろ寝ようか。おやすみ、いい夢を。",     # 哄睡人格域
}


def tf(name, text):
    p = OUT / f"{name}.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def synth(model, tag, sent_key, prompt_key):
    import numpy as np
    import soundfile as sf
    import os
    sys.path.insert(0, str(PKGR))
    from GPT_SoVITS.inference_webui import change_gpt_weights, change_sovits_weights, get_tts_wav
    pw, pt = PROMPTS[prompt_key]
    change_gpt_weights(gpt_path=str(MODELS[model]["gpt"]))
    change_sovits_weights(sovits_path=str(MODELS[model]["sovits"]))
    print(f"[synth] {model} {sent_key} @{prompt_key}", flush=True)
    chunks = list(get_tts_wav(ref_wav_path=str(DS / pw), prompt_text=pt, prompt_language="日文",
                              text=SENTS[sent_key], text_language="日文", top_p=1, temperature=1))
    if not chunks:
        print("  [warn] empty synthesis")
        return
    sr = chunks[0][0]
    audio = np.concatenate([c for _, c in chunks])
    dest = OUT / f"{model}_{sent_key}_{prompt_key}.wav"
    sf.write(str(dest), audio, sr)
    print(f"  -> {dest.name} {len(audio)/sr:.1f}s")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import os
    os.environ["PATH"] = str(PKGR / "runtime") + os.pathsep + os.environ.get("PATH", "")
    for m in MODELS:
        for k in SENTS:
            synth(m, "", k, "default")
        synth(m, "", "s2", "happy")
        synth(m, "", "s3", "tender")
    print("[done] ->", OUT)


if __name__ == "__main__":
    main()
