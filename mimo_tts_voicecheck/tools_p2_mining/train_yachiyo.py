# Headless trainer replicating webui's pipeline (prep 1a/1b/semantic/sv + s2 + s1).
# Run from package root with the bundled runtime python:
#   runtime\python.exe train_yachiyo.py --exp yachiyo_A --dataset <abs dir with .list+wav/>
# Resumable: --skip-prep / --skip-s2 / --skip-gpt; artifacts under logs/<exp>/.
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PKGR = Path(__file__).resolve().parent
PY = sys.executable

# webui constants (config.py + open1a/1b/1B signatures)
BERT = "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large"
HUBERT = "GPT_SoVITS/pretrained_models/chinese-hubert-base"
SV = "GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt"
S2_CFG = "GPT_SoVITS/configs/s2v2ProPlus.json"
S1_CFG = "GPT_SoVITS/configs/s1longer-v2.yaml"
S2G = "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth"
S2D = "GPT_SoVITS/pretrained_models/v2Pro/s2Dv2ProPlus.pth"
S1W = "GPT_SoVITS/pretrained_models/s1v3.ckpt"


def run(cmd, env_extra, tag):
    env = os.environ.copy()
    env.update({k: str(v) for k, v in env_extra.items()})
    env["PATH"] = str(PKGR / "runtime") + os.pathsep + env.get("PATH", "")  # bundled ffmpeg first, like go-webui
    print(f"\n===== [{tag}] {cmd} =====", flush=True)
    p = subprocess.run(cmd, shell=True, env=env, cwd=str(PKGR))
    if p.returncode != 0:
        sys.exit(f"[abort] {tag} exited {p.returncode}")


def prep(args, opt_dir):
    base = {"inp_text": args.list, "inp_wav_dir": args.dataset, "exp_name": args.exp,
            "opt_dir": str(opt_dir), "i_part": 0, "all_parts": 1,
            "_CUDA_VISIBLE_DEVICES": 0, "is_half": "True"}
    run(f'"{PY}" -s GPT_SoVITS/prepare_datasets/1-get-text.py',
        {**base, "bert_pretrained_dir": BERT}, "1a-get-text")
    run(f'"{PY}" -s GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py',
        {**base, "cnhubert_base_dir": HUBERT, "sv_path": SV}, "1b-hubert-wav32k")
    run(f'"{PY}" -s GPT_SoVITS/prepare_datasets/3-get-semantic.py',
        {**base, "pretrained_s2G": S2G, "s2config_path": S2_CFG}, "1c-semantic")
    run(f'"{PY}" -s GPT_SoVITS/prepare_datasets/2-get-sv.py',
        {**base, "cnhubert_base_dir": HUBERT, "sv_path": SV}, "1d-sv(Pro)")
    # merge part files exactly like webui does
    merge(opt_dir, "2-name2text", ".txt")
    merge(opt_dir, "6-name2semantic", ".tsv", header="item_name\tsemantic_audio")


def merge(opt_dir, prefix, ext, header=None):
    import glob
    parts = sorted(glob.glob(str(opt_dir / f"{prefix}-*{ext}")))
    if not parts:
        return
    rows = []
    for p in parts:
        with open(p, encoding="utf8") as f:
            body = f.read().strip("\n")
        rows.append(body)
        os.remove(p)
    out = opt_dir / f"{prefix}{ext}"
    with open(out, "w", encoding="utf8") as f:
        if header:
            f.write(header + "\n")
        f.write("\n".join(rows) + "\n")
    print(f"[merge] {out.name}: {sum(len(r.splitlines()) for r in rows)} rows")


def train_s2(args, opt_dir):
    import json as _json
    import os as _os
    _os.makedirs(opt_dir / "logs_s2_v2ProPlus", exist_ok=True)  # s2_train expects it (webui open1Ba does this)
    _os.makedirs(opt_dir / "logs_s1_v2ProPlus", exist_ok=True)
    data = json.loads((PKGR / S2_CFG).read_text(encoding="utf-8"))
    data["train"].update({"batch_size": args.sovits_bs, "epochs": args.sovits_epochs,
                          "pretrained_s2G": S2G, "pretrained_s2D": S2D,
                          "if_save_latest": True, "if_save_every_weights": True,
                          "save_every_epoch": max(1, args.sovits_epochs // 2),
                          "text_low_lr_rate": 0.4, "gpu_numbers": "0",
                          "grad_ckpt": False, "lora_rank": "0"})
    data["model"]["version"] = "v2ProPlus"
    data["data"]["exp_dir"] = data["s2_ckpt_dir"] = str(opt_dir)
    data.update({"save_weight_dir": "SoVITS_weights_v2ProPlus", "name": args.exp, "version": "v2ProPlus"})
    cfg = opt_dir / "tmp_s2.json"
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    run(f'"{PY}" -s GPT_SoVITS/s2_train.py --config "{cfg}"', {}, "s2-train")


def train_s1(args, opt_dir):
    import yaml
    data = yaml.safe_load((PKGR / S1_CFG).read_text(encoding="utf-8"))
    data["train"].update({"batch_size": args.gpt_bs, "epochs": args.gpt_epochs,
                          "save_every_n_epoch": max(1, args.gpt_epochs // 3),
                          "if_save_every_weights": True, "if_save_latest": True,
                          "if_dpo": False, "half_weights_save_dir": "GPT_weights_v2ProPlus",
                          "exp_name": args.exp})
    data["pretrained_s1"] = S1W  # TOP-LEVEL key: t2s_lightning_module reads config.get("pretrained_s1")
    data.update({"train_semantic_path": str(opt_dir / "6-name2semantic.tsv"),
                 "train_phoneme_path": str(opt_dir / "2-name2text.txt"),
                 "output_dir": str(opt_dir / "logs_s1_v2ProPlus")})
    cfg = opt_dir / "tmp_s1.yaml"
    cfg.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    run(f'"{PY}" -s GPT_SoVITS/s1_train.py --config_file "{cfg}"', {}, "s1-train")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True)
    ap.add_argument("--dataset", required=True, help="dir containing yachiyo.list (or --list) and wav/")
    ap.add_argument("--list", default=None, help="override list path (default <dataset>/yachiyo.list)")
    ap.add_argument("--sovits-epochs", type=int, default=8)
    ap.add_argument("--gpt-epochs", type=int, default=15)
    ap.add_argument("--sovits-bs", type=int, default=1)
    ap.add_argument("--gpt-bs", type=int, default=2)
    ap.add_argument("--skip-prep", action="store_true")
    ap.add_argument("--skip-s2", action="store_true")
    ap.add_argument("--skip-gpt", action="store_true")
    args = ap.parse_args()
    args.dataset = str(Path(args.dataset).resolve())
    args.list = str(Path(args.list).resolve() if args.list else Path(args.dataset) / "yachiyo.list")
    opt_dir = PKGR / "logs" / args.exp
    opt_dir.mkdir(parents=True, exist_ok=True)
    print(f"[cfg] exp={args.exp}\n      dataset={args.dataset}\n      list={args.list}\n      opt={opt_dir}")
    if not args.skip_prep:
        prep(args, opt_dir)
    if not args.skip_s2:
        train_s2(args, opt_dir)
    if not args.skip_gpt:
        train_s1(args, opt_dir)
    print("\n[done] weights -> SoVITS_weights_v2ProPlus/ + GPT_weights_v2ProPlus/ "
          f"(pick latest {args.exp} files for inference)")


if __name__ == "__main__":
    main()
