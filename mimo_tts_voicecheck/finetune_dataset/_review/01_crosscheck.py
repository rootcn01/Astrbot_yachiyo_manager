# -*- coding: utf-8 -*-
"""Task 1: cross-compare whisper (manifest) vs MiMo ASR, flag suspicious lines."""
import json, os, re, difflib
from collections import defaultdict

BASE = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\finetune_dataset"
BILI = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\_tmp\bili_dl"

# ---------- load ----------
manifest = json.load(open(os.path.join(BASE, "selection_manifest.json"), encoding="utf-8"))

def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

p2 = load_jsonl(os.path.join(BILI, "p2_asr_full.jsonl"))
bd = load_jsonl(os.path.join(BILI, "bd_asr_full.jsonl"))
bc = json.load(open(os.path.join(BILI, "bc_asr_full.jsonl"), encoding="utf-8"))  # JSON array

# ---------- mimo lookup: key = round(start,1); bc keyed by (track, start) ----------
p2_map = {round(r["start"], 1): r["text"] for r in p2}
bd_map = {round(r["start"], 1): r["text"] for r in bd}
bc_map = defaultdict(dict)
for r in bc:
    bc_map[r["track"]][round(r["start"], 1)] = r["text"]

# bc: verify claimed order alignment as sanity check (sorted by (track,start) vs file order)
m_bc = [e for e in manifest if e["src"] == "bc"]
m_bc_sorted = sorted(m_bc, key=lambda e: (os.path.basename(e["path"]).split("_c")[0], e["start"]))
bc_sorted = sorted(bc, key=lambda r: (r["track"], r["start"]))
order_ok = all(
    abs(a["start"] - b["start"]) < 0.15 for a, b in zip(m_bc_sorted, [r for r in bc_sorted if r["track"] in {os.path.basename(x["path"]).split("_c")[0] for x in m_bc_sorted}])
) if m_bc_sorted else True
print("[bc] manifest count:", len(m_bc), "| asr total:", len(bc))
print("[bc] exact (track,round(start,1)) key matches below are the authoritative check")

def get_mimo(e):
    s = round(e["start"], 1)
    if e["src"] == "p2":
        return p2_map.get(s)
    if e["src"] == "bd":
        return bd_map.get(s)
    track = os.path.basename(e["path"]).split("_c")[0]  # e.g. BV1nZjz6REQK_P3
    return bc_map.get(track, {}).get(s)

# ---------- normalization & similarity ----------
PUNCT = set("、。！？!?.,，。:；;()（）「」『』~〜ー・…\"'“”\\ /　 \t") | set(" ")
def norm(s):
    return "".join(c for c in (s or "") if c not in PUNCT)

def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()

# ---------- character-name detection ----------
NAME_GROUPS = {
    "yachiyo": ["八千代", "八千夜", "やっちょ", "やっちゃん", "やっちゃ", "ヨッチ", "よっちお",
                 "やちよ", "ヤッチョ", "やっちょー", "八千代ちゃん"],
    "kaguya":  ["かぐや", "カグヤ", "輝夜"],
    "iroha":   ["イロハ", "イルハ", "いろは", "色葉"],
    "tsukuyomi": ["ツクヨミ", "月読"],
}
def names_in(s):
    s = s or ""
    return {g for g, pats in NAME_GROUPS.items() if any(p in s for p in pats)}

# ---------- garbage patterns (whisper side) ----------
# strictly simplified-only forms (never valid Japanese shinjitai/kanji)
ZH_ONLY = set(
    "备们说话这吗听为么妈觉对谁谢请时问见长关汉现络违团欢爱样实讲师势语词线"
    "转轮轻输头续尝册场块处终给后过还运连远东车门义乐气开剧记调谈赛"
)

def garbage_flags(s):
    flags = []
    if re.search(r"(.)\1{2,}", s):  # single char repeated 3+
        flags.append("char_repeat:" + re.search(r"(.)\1{2,}", s).group(0))
    kana_run = re.findall(r"[ァ-ヴー]{10,}", s)  # absurdly long katakana run
    if kana_run:
        flags.append("katakana_run:" + kana_run[0][:15])
    hit = set(re.findall(r"[\u4e00-\u9fff]", s)) & ZH_ONLY
    if hit:
        flags.append("zh_chars:" + "".join(sorted(hit)))
    return flags

# ---------- main scan ----------
# collision check: two manifest entries must not map to the same MiMo key
key_count = defaultdict(int)
for e in manifest:
    k = (e["src"], round(e["start"], 1)) if e["src"] in ("p2", "bd") else ("bc", os.path.basename(e["path"]).split("_c")[0], round(e["start"], 1))
    key_count[k] += 1
dups = {k: v for k, v in key_count.items() if v > 1}
print("[collision] duplicate mimo keys:", dups if dups else "none")

results = []
for e in manifest:
    wav = e["wav"]
    w_text = e["text"]
    m_text = get_mimo(e)
    reasons = []
    if m_text is None:
        s_val = None
        reasons.append("no_mimo")
        m_text = ""
    else:
        s_val = sim(w_text, m_text)
        if s_val < 0.5:
            reasons.append("low_sim:%.2f" % s_val)
    wn, mn = names_in(w_text), names_in(m_text or "")
    if wn != mn:
        reasons.append("name_mismatch:%s vs %s" % (sorted(wn) or "-", sorted(mn) or "-"))
    gf = garbage_flags(w_text)
    if gf:
        reasons.append("garbage:" + ",".join(gf))
    results.append({
        "wav": wav, "src": e["src"], "start": e["start"], "dur": e["dur"],
        "whisper": w_text, "mimo": m_text, "sim": round(s_val, 3) if s_val is not None else None,
        "suspicious": bool(reasons), "reasons": reasons,
    })

json.dump(results, open(os.path.join(BASE, "_review", "crosscheck_all.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

sus = [r for r in results if r["suspicious"]]
print("\n==== total %d | matched mimo %d | no_mimo %d | suspicious %d ====" % (
    len(results), sum(1 for r in results if r["mimo"]), sum(1 for r in results if "no_mimo" in r["reasons"]), len(sus)))
for r in sus:
    print("\n[%s] %s  (%s)" % (r["wav"], r["src"], "; ".join(r["reasons"])))
    print("  W:", r["whisper"])
    print("  M:", r["mimo"] or "(none)")
