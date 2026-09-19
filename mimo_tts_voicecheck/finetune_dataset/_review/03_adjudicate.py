# -*- coding: utf-8 -*-
"""Task 3 rulings + outputs: backup, corrections.json, apply fixes to yachiyo.list, final report."""
import json, os, shutil, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE = r"E:\DATA\ClaudeWorkspace\Yachiyo_Project\mimo_tts_voicecheck\finetune_dataset"
LIST = os.path.join(BASE, "yachiyo.list")

# ---------------- rulings ----------------
# (action, now_text, basis)   now_text=None means unchanged
R = {
 # ---- keep: re-transcription (and/or context) confirms whisper original ----
 "p2_048": ("keep", None, "重转版逐句一致（かぐやも踊らっかな），MiMo「カクヤも惊くの」为误听"),
 "p2_051": ("keep", None, "重转版完全一致；MiMo该段为中文乱码，无反证"),
 "p2_001": ("keep", None, "重转版自身更乱（侵さっなっちゃう），原版「誘っちゃう」通顺且与MiMo尾音（…哟）对应"),
 "p2_005": ("keep", None, "重转版完全一致；MiMo英文「Got star, somebody star」即ごちそうさまの音译"),
 "p2_012": ("keep", None, "重转版确认「八千代カップはじまるよー」，MiMo「やちおカブ」为同音误听"),
 "p2_014": ("keep", None, "原版与重转版（带角色提示词）均写ルナミヤチオ，MiMoロナミアチュー同音——系八千代在ツクヨミ内的自称ID，非转写错误"),
 "p2_017": ("keep", None, "重转版结构一致（一緒に…めでたししちゃおう），MiMo整段乱码"),
 "p2_018": ("keep", None, "重转版完全一致；八千代为正字"),
 "p2_020": ("keep", None, "重转版完全一致；やっちょ为正字"),
 "p2_024": ("keep", None, "重转版完全一致"),
 "p2_031": ("keep", None, "重转版一致（ごめん、閉じっちゃった），MiMo乱码"),
 "p2_032": ("keep", None, "重转版同句（多出的１为冗余字符），かぐや姫为正字"),
 "p2_037": ("keep", None, "重转版「恒麗」与原版「恒例」同音kōrei（MiMo听成Curry），原版汉字正确"),
 "p2_040": ("keep", None, "重转版一致；「お返し」符合ホワイトデー前后文"),
 "p2_042": ("keep", None, "重转版一致（一年が終わっちゃう），MiMo乱码"),
 "p2_043": ("keep", None, "重转版一致；MiMo「Count down, right, baby」即カウントダウンライブ音译"),
 "p2_044": ("keep", None, "重转版完全一致"),
 "bd_019": ("keep", None, "重转版一致；前后文（運命を変えて…タイムパラドックス）印证"),
 "bd_024": ("keep", None, "重转版完全一致，やっちょ正字"),
 "bd_025": ("keep", None, "重转版完全一致，かぐや正字"),
 "bd_030": ("keep", None, "重转版一致（…かぐや……）"),
 "bd_037": ("keep", None, "原版与重转版同音（自分で調べろかす）；MiMo该段为错位乱码，无更优候选"),
 "bd_039": ("keep", None, "重转版逐字一致（イロハを助ける八千代）"),
 "bd_002": ("keep", None, "重转版一致（イロハを支えるやっちょ）；MiMo「井戸が…」为同音误归"),
 "bd_006": ("keep", None, "重转版完全一致"),
 "bd_008": ("keep", None, "重转版完全一致（かぐやを見たのは）"),
 "bd_011": ("keep", None, "重转版完全一致（イロハ育ててくれた），MiMo「surren」为乱码"),
 "bd_015": ("keep", None, "重转版确认「イロハとの」；MiMo「井戸端の」为关键词误归，2:1取イロハ"),
 "bc_008": ("keep", None, "重转版一致；MiMo「どうか月夜」即「ちょうかぐや（姫）」误听，且与bc_007「それでは最後まで」连成完整句"),
 "bc_002": ("keep", None, "重转版逐字一致"),
 # ---- fix ----
 "p2_009": ("fix", "八千代のライブたくさん見てくれたら嬉しいな",
            "「八千夜」非人名正字，重转版读音同为やちよ，统一为八千代"),
 "p2_013": ("fix", "仮想空間ツクヨミへようこそー!",
            "W/R同音つくよみ、MiMo亦含「…み」音节，按正字表统一为ツクヨミ（仅表记，发音不变）"),
 "p2_026": ("fix", "さあ、宴もたけなわ",
            "原版「縁も竹縄」与重转版同音（えんもたけなわ），唯一成立的惯用句为「宴もたけなわ」；MiMo「演目は竹名」同音乱写"),
 "p2_034": ("fix", "またイロハと一緒にパンケーキ",
            "重转版同音いろは、MiMo「色は」亦同音，按正字统一为イロハ（仅表记）"),
 "p2_041": ("fix", "ハッピーハロウィーンやっちょはどんな仮装をしようかなぁ",
            "W/R均听出「ヨッチ」，按语境归一为やっちょ；「仮装」正确（ハロウィン文脉，MiMo「服装」为误听）"),
 "bd_005": ("fix", "イロハとツクヨミで会った時ももちろんなんだけど",
            "重转版明确写「イロハとツクヨミ」，イルハ归一为イロハ；MiMo「井戸端作る意味」为同音关键词误归"),
 "bd_007": ("fix", "やっちょは寝てるときに分身のAIと記憶を同期するから",
            "原版「よっちおは」/重转版「八千代は」/MiMo「うちは」三方同为自称名音，归一为やっちょ；「同期」W/R一致（MiMo「活动する」为误听）"),
 "bd_017": ("fix", "それがイロハママのコミュニケーションなんだよね。",
            "重转版写「イロハママ」，いろは统一为イロハ（仅表记）"),
 "bd_034": ("fix", "だから犬同士とかぐやは",
            "MiMo「犬同士」与原版音节（イヌドアジ≈いぬどうし）互相印证，原版片假名连写不成立；重转版「井戸端」缺少两版均有的「いぬ」音节（提示词偏置），不取"),
 "bd_045": ("fix", "かぐやのママだったイロハの理想のママが八千代ででもイロハが八千代のママにもなっちゃった物語",
            "重转版整句结构一致（イロハ・八千代・物語），いろは统一为イロハ（仅表记）"),
 "bd_049": ("fix", "こうなるとやっちょもさすがに欲が出たよねー",
            "三方均含自称名音（やっちゅ/八千代/昨夜≈やちゅう），归一为やっちょ；「欲が出た」W/R一致"),
 "bc_006": ("fix", "じゃあ今日はガチ勢のイロハちゃんに進行をお願いしちゃおうかな",
            "重转版「ガチ勢のイロハちゃんに進行をお願い」逐节一致，いろは→イロハ（仅表记）；MiMo「2000号をねがい」为乱码"),
 # ---- extra name canonicalization on non-suspects ----
 "p2_007": ("fix", "やっちょの歌声聞いてって",
            "（任务1未标记，名称正字化补正）原版「やっちゃな」不成立；MiMo明确「やっちゃんの歌声聞いてて」，按正字归一为やっちょ"),
 "p2_015": ("fix", "八千代カップに勝てば、八千代とコラボライブできるよ!",
            "（任务1未标记，名称正字化补正）同一活动名：p2_012原版+重转版均确认「八千代カップ」；ヤチオ=やちよ同音，随活动名统一"),
 "p2_050": ("fix", "ツクヨミの夜景が大好きなのです",
            "（任务1未标记，名称正字化补正）MiMo「月夜」同音つくよ，按正字表统一表记，发音不变"),
 "bd_029": ("fix", "一部だけどツクヨミのサーバールームも兼ねてるんだ",
            "（任务1未标记，名称正字化补正）MiMo「月读」同音つくよみ，按正字表统一表记，发音不变"),
 "bd_042": ("fix", "イロハがなんて言うのか知らないから怖くて",
            "（任务1未标记，名称正字化补正）「ヒロハ」非正字，语境唯一候选为イロハ；MiMo该段乱码无反证"),
 # ---- unresolved ----
 "p2_038": ("unresolved", None, "「めんどく味」非词：原版与重转版同音但无日语词形，MiMo「面で详しい」亦乱；无两版以上可印证的修正→保留原版"),
 "bd_022": ("unresolved", None, "原版「思いだった」不成立；重转版作「両想いだったくせに」仅覆盖前半且与MiMo「回忆(おもいで)」冲突，整句无法两方印证→保留原版"),
 "bd_048": ("unresolved", None, "「パセット」非通用词：W/R同音但无法定词，MiMo「设定を组み」音节不对应→保留原版"),
}

CROSSTALK = {
 "p2_049": "「…しない?うん、いいよ」—提问后紧接短促应答，疑为两人对话同片（仅标记不删）",
 "bd_028": "「…思っちゃってえへへ」+「よくないよ」—含笑应声与其后叱责语气疑为两人同片（仅标记不删）",
}

# ---------------- load & verify ----------------
lines = open(LIST, encoding="utf-8").read().splitlines()
assert len(lines) == 108, len(lines)
rows = json.load(open(os.path.join(BASE, "_review", "crosscheck_all.json"), encoding="utf-8"))
suspects = [r["wav"].replace(".wav", "") for r in rows if r["suspicious"]]
assert len(suspects) == 45

# every suspect must have a ruling; no ruling for non-suspects except the 5 canonicalization extras
EXTRA = {"p2_007", "p2_015", "p2_050", "bd_029", "bd_042"}
ruled = set(R)
assert ruled == set(suspects) | EXTRA, ruled ^ (set(suspects) | EXTRA)

# ---------------- backup ----------------
bak = LIST + ".bak"
if not os.path.exists(bak):
    shutil.copyfile(LIST, bak)
    print("backup ->", bak)
else:
    print("backup already exists, kept:", bak)

# ---------------- apply ----------------
corrections = []
new_lines = []
for l in lines:
    p = l.split("|")
    wav = p[0].replace("wav/", "").replace(".wav", "")
    was = p[3]
    entry = None
    if wav in R:
        action, now, basis = R[wav]
        if now is None:
            now = was
        entry = {"wav": wav + ".wav", "action": action, "was": was, "now": now, "basis": basis}
        if now != was:
            p[3] = now
    if wav in CROSSTALK:
        note = CROSSTALK[wav]
        if entry is None:
            entry = {"wav": wav + ".wav", "action": "crosstalk_suspect", "was": was, "now": was,
                     "basis": "文本模式串音疑点（任务4）", "crosstalk_note": note}
        else:
            entry["crosstalk_note"] = note
    if entry:
        corrections.append(entry)
    new_lines.append("|".join(p))

assert len(new_lines) == 108
open(LIST, "w", encoding="utf-8", newline="\n").write("\n".join(new_lines) + "\n")
json.dump(corrections, open(os.path.join(BASE, "corrections.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# ---------------- report ----------------
from collections import Counter
c = Counter(e["action"] for e in corrections)
print("\n===== FINAL =====")
print("总行数: %d (写入 %d)" % (len(lines), len(new_lines)))
print("fix: %d | keep: %d | unresolved: %d | crosstalk_suspect: %d" % (
    c["fix"], c["keep"], c["unresolved"], c["crosstalk_suspect"]))
print("\n----- fix 对照表 -----")
for e in corrections:
    if e["action"] == "fix":
        print("%s | %s -> %s | %s" % (e["wav"], e["was"], e["now"], e["basis"]))
print("\n----- crosstalk 对照表 -----")
for e in corrections:
    if e["action"] == "crosstalk_suspect":
        print("%s | %s | %s" % (e["wav"], e["now"], e["crosstalk_note"]))
print("\n----- unresolved -----")
for e in corrections:
    if e["action"] == "unresolved":
        print("%s | %s | %s" % (e["wav"], e["was"], e["basis"]))
