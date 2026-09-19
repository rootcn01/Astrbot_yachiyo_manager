# Bandwidth enhancement for the fine-tune dataset (VoiceFixer mode 0).
# Source: finetune_dataset/wav (16k, f99~4k = "phone-call" ceiling inherited by the model).
# Output: finetune_dataset_enh/wav (44.1k wideband, 10kHz lift -133dB -> -45dB on samples).
# Usage: <spkenv>/Scripts/python enhance_bw.py     (resumable; list copied unchanged)
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

SRC = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\finetune_dataset\wav")
DST = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\finetune_dataset_enh\wav")
LIST_SRC = SRC.parents[0] / "yachiyo.list"
LIST_DST = DST.parents[0] / "yachiyo.list"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from voicefixer import VoiceFixer
    vf = VoiceFixer()
    DST.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(sorted(SRC.glob("*.wav")), 1):
        out = DST / p.name
        if out.exists():
            continue
        vf.restore(input=str(p), output=str(out), cuda=False, mode=0)
        if i % 20 == 0:
            print(f"{i} done", flush=True)
    shutil.copy(LIST_SRC, LIST_DST)
    print("enhanced:", len(list(DST.glob("*.wav"))), "| list copied (texts unchanged)")


if __name__ == "__main__":
    main()
