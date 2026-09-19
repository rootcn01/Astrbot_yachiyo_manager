# Classify ASR'd clips by speaker markers -> attribution report for manual review.
# Yachiyo markers from handoff §3.1 + solo-verified lines; Kaguya = third-person self-reference.
import json
import re
import sys
from pathlib import Path

BASE = Path(r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl")

# signature phrases confirmed on solo-verified Yachiyo lines or her persona grammar
YACHIYO_MARKERS = [
    "神々のみんな", "良きかな", "物語を見届け", "幻の国", "月見", "お月様",
    "ごきげん", "ご機嫌", "拝", "そなた", "〜じゃ", "のう", "われて", "悠久",
]
YACHIYO_GRAMMAR = [r"じゃ$|じゃ。|じゃ、", r"であろう", r"〜ておる|ておった", r"わしは", r"そなた"]
KAGUYA_MARKERS = [r"かぐやは", r"かぐやも", r"かぐやが", r"かぐやに", r"かぐやの"]
YACHIYO_STRONG = ["神々のみんな", "良きかな", "物語を見届け"]


def classify(text):
    if text.startswith("[ERR"):
        return "err"
    if any(m in text for m in YACHIYO_STRONG):
        return "yachiyo_strong"
    if any(m in text for m in YACHIYO_MARKERS):
        return "yachiyo_kw"
    if any(re.search(p, text) for p in YACHIYO_GRAMMAR):
        return "yachiyo_gram"
    if any(re.search(p, text) for p in KAGUYA_MARKERS):
        return "kaguya"
    return "unknown"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for name in ["p2", "bd"]:
        rows = [json.loads(l) for l in open(BASE / f"{name}_asr_full.jsonl", encoding="utf-8")]
        for r in rows:
            r["attr"] = classify(r["text"])
        json.dump(rows, open(BASE / f"{name}_attributed.json", "w"), ensure_ascii=False, indent=1)
        from collections import Counter
        cnt = Counter(r["attr"] for r in rows)
        print(f"== {name}: {len(rows)} clips -> {dict(cnt)}")
        y = [r for r in rows if r["attr"].startswith("yachiyo")]
        print(f"   yachiyo seconds: {sum(r['dur'] for r in y):.0f}s over {len(y)} clips")
        print("   -- strong/kw/gram samples:")
        for r in y[:12]:
            print(f"   {r['start']:8.1f} {r['dur']:5.1f}s [{r['attr']}] {r['text'][:70]}")
        print("   -- unknown with yachiyo-ish F0 (280-360) for manual review:")
        unk = [r for r in rows if r["attr"] == "unknown" and r.get("f0") and 270 <= r["f0"] <= 370]
        print(f"   ({len(unk)} unknowns in F0 band)")
        for r in unk[:25]:
            print(f"   {r['start']:8.1f} {r['dur']:5.1f}s f0={r['f0']} simV2={r.get('simV2','-')} | {r['text'][:70]}")


if __name__ == "__main__":
    main()
