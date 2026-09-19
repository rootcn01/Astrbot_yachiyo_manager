# -*- coding: utf-8 -*-
"""Helper: for each suspect wav, print MiMo ASR records within +/-4s of manifest start (local context)."""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\finetune_dataset"
BILI = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl"

manifest = json.load(open(os.path.join(BASE, "selection_manifest.json"), encoding="utf-8"))
rows = json.load(open(os.path.join(BASE, "_review", "crosscheck_all.json"), encoding="utf-8"))
sus = {r["wav"] for r in rows if r["suspicious"]}

def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

p2 = load_jsonl(os.path.join(BILI, "p2_asr_full.jsonl"))
bd = load_jsonl(os.path.join(BILI, "bd_asr_full.jsonl"))
bc = json.load(open(os.path.join(BILI, "bc_asr_full.jsonl"), encoding="utf-8"))
pools = {"p2": p2, "bd": bd}
bc_by_track = {}
for r in bc:
    bc_by_track.setdefault(r["track"], []).append(r)

only = sys.argv[1:] if len(sys.argv) > 1 else None
for e in manifest:
    if e["wav"] not in sus:
        continue
    if only and e["wav"].replace(".wav", "") not in only:
        continue
    if e["src"] in pools:
        pool = pools[e["src"]]
    else:
        track = os.path.basename(e["path"]).split("_c")[0]
        pool = bc_by_track.get(track, [])
    s0, dur = e["start"], e["dur"]
    near = [r for r in pool if r["start"] < s0 + dur + 4 and r["end"] > s0 - 4]
    print("== %s  [%.2f + %.2fs]  W: %s" % (e["wav"], s0, dur, e["text"]))
    for r in near:
        mark = " *MATCH*" if abs(r["start"] - s0) < 0.05 else ""
        print("   %7.2f-%7.2f | %s%s" % (r["start"], r["end"], r["text"], mark))
