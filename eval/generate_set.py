"""Generate a baseline song set: each prompt in eval/prompts.jsonl x N samples
for one model. Writes <out>/<id>_n<j>.txt for scoring by run_eval.py.

Usage (from repo root):
    python3 eval/generate_set.py \
        --model Vikhrmodels/QVikhr-3-8B-Instruction-MLX_4bit \
        --out eval/out/qvikhr3 --n 3
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from generate_sections import generate_song  # noqa: E402
from post_filter import FilterConfig  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter_dir", default="", help="LoRA dir; empty = base model")
    ap.add_argument("--prompts", default=str(Path(__file__).resolve().parent / "prompts.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=3, help="samples per prompt (eval-discipline N>=3)")
    ap.add_argument("--tries", type=int, default=3, help="candidates per section")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max_tokens_section", type=int, default=260)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--top_p", type=float, default=0.9)
    ap.add_argument("--top_k", type=int, default=40)
    ap.add_argument("--min_p", type=float, default=0.06)
    ap.add_argument("--chat_template_config", default="", help='e.g. \'{"enable_thinking": false}\' for QVikhr-3')
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    filter_cfg = FilterConfig(
        min_words_per_line=3,
        max_same_line_repeats=2,
        drop_latin_lines=True,
        drop_mixed_cyr_lat_words=True,
        keep_tag_lines=True,
        collapse_whitespace=True,
    )

    prompts = [json.loads(ln) for ln in open(args.prompts, encoding="utf-8") if ln.strip()]
    total = len(prompts) * args.n
    done = 0
    for p in prompts:
        for j in range(args.n):
            song = generate_song(
                theme=p["theme"],
                structure=p["structure"],
                model=args.model,
                adapter_dir=args.adapter_dir,
                max_tokens=args.max_tokens_section,
                temp=args.temp,
                top_p=args.top_p,
                top_k=args.top_k,
                min_p=args.min_p,
                seed=args.seed + j * 7,
                tries=args.tries,
                filter_cfg=filter_cfg,
                chat_template_config=args.chat_template_config,
            )
            fn = out / f"{p['id']}_n{j}.txt"
            fn.write_text(song, encoding="utf-8")
            done += 1
            print(f"[{done}/{total}] {fn.name}  ({len([x for x in song.splitlines() if x.strip()])} non-empty lines)")
    print(f"done -> {out}")


if __name__ == "__main__":
    main()
