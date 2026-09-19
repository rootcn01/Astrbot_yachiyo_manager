# -*- coding: utf-8 -*-
"""Task 2: re-transcribe suspicious lines with faster-whisper large-v3-turbo."""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
from faster_whisper import WhisperModel

BASE = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\finetune_dataset"
REV = os.path.join(BASE, "_review")

all_rows = json.load(open(os.path.join(REV, "crosscheck_all.json"), encoding="utf-8"))
sus = [r for r in all_rows if r["suspicious"]]
print("re-transcribing", len(sus), "clips")

try:
    model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
    # smoke test: transcribe returns a lazy generator, must iterate to force the CUDA path
    segs, _ = model.transcribe(os.path.join(BASE, "wav", sus[0]["wav"]), language="ja")
    for _ in segs:
        pass
    print("CUDA path OK")
except Exception as e:
    print("CUDA unavailable (%s); falling back to CPU int8" % type(e).__name__)
    model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
PROMPT = ("超かぐや姫！の月見八千代のセリフです。登場人物は八千代（あだ名やっちょ）、かぐや、イロハ。"
          "ツクヨミは仮想世界、ブラックオニキスはゲームチーム、井戸端はアパート名。")

out = {}
for r in sus:
    wav = os.path.join(BASE, "wav", r["wav"])
    segs, info = model.transcribe(
        wav, language="ja", beam_size=8, best_of=5, temperature=0,
        initial_prompt=PROMPT,
    )
    text = "".join(s.text for s in segs).strip()
    out[r["wav"]] = text
    print(r["wav"], "|", text)

json.dump(out, open(os.path.join(REV, "retranscribed.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("saved retranscribed.json")
