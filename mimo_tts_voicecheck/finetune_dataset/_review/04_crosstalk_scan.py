# -*- coding: utf-8 -*-
"""Task 4: text-pattern crosstalk (multi-speaker) scan over all 108 lines. Flag only, never delete."""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\finetune_dataset"
lines = open(os.path.join(BASE, "yachiyo.list"), encoding="utf-8").read().splitlines()

BACKCHANNEL = r"(うん|うんうん|はい|えっ?|えへへ|うん、いいよ|いいよ|わかった|知りたい|そうだね|そっか|なるほど|うんそう)"

flags = []
for l in lines:
    p = l.split("|")
    wav, text = p[0].replace("wav/", ""), p[3]
    notes = []
    # A: question mid-text followed by a short backchannel/answer tail (<=12 chars to end)
    for m in re.finditer(r"[?？]([^?？。！]{0,12})$", text):
        tail = m.group(1)
        if re.fullmatch(r"[、,]?\s*" + BACKCHANNEL + r"[。！!]?", tail):
            notes.append("Q+A同片: 「…%s?%s」問いかけ直後に短い応答" % (text[:text.rfind('?')][-10:], tail))
    # B: interjection/backchannel embedded after a sentence end or mid-flow
    for m in re.finditer(r"(。|！|って|ちゃって)" + BACKCHANNEL, text):
        notes.append("句読点後の短い相槌「%s」" % m.group(0))
    # C: register shift polite(です/ます) vs plain casual(だよ/じゃん) in one line
    if re.search(r"(です|ます|ました|ですね)", text) and re.search(r"(だよ|じゃん|だろ|だね|しちゃう|ちゃった)", text):
        # exclude です-ending lines where casual part precedes polite ending (narration style)
        notes.append("語体混在: 丁寧体と常体が同一行")
    if notes:
        flags.append({"wav": wav, "text": text, "notes": notes})

print("crosstalk pattern flags:", len(flags))
for f in flags:
    print("\n[%s] %s" % (f["wav"], f["text"]))
    for n in f["notes"]:
        print("   -", n)

json.dump(flags, open(os.path.join(BASE, "_review", "crosstalk_flags.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
