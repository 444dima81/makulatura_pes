"""Evaluate generated Makulatura song(s) with deterministic hard metrics,
calibrated against the real corpus. Prints corpus reference distribution +
per-song drilldown + aggregate mean±std (eval-discipline rules 6, 9).

Usage (from repo root):
    python3 eval/run_eval.py --input generated_song.txt
    python3 eval/run_eval.py --input eval/reference/            # a directory of songs
    python3 eval/run_eval.py --input out/ --json eval/last_run.json
    python3 eval/run_eval.py --input out/ --judge-bundle eval/judge_bundle.md

Hard metrics are deterministic — re-running on the same input yields identical
numbers. Soft (style) metrics are NOT here: they need a judge, N>=3, and reading
transcripts. See eval/rubric.md and eval/judge_aggregate.py.
"""
import argparse
import json
import statistics
from pathlib import Path
from typing import Dict, List

from metrics import (
    all_hard_metrics,
    build_corpus_index,
    content_lines,
    line_length_stats,
)

REPO = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent


def load_corpus(corpus_path: Path, holdout_ids: set) -> List[str]:
    texts = []
    with corpus_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("url", "") in holdout_ids:
                continue  # exclude hold-out so overlap == real memorization signal
            texts.append(rec.get("text", ""))
    return texts


def load_holdout_ids(path: Path) -> set:
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}


def load_songs(input_path: Path) -> Dict[str, str]:
    songs = {}
    if input_path.is_dir():
        for p in sorted(input_path.glob("*.txt")):
            songs[p.stem] = p.read_text(encoding="utf-8")
    else:
        songs[input_path.stem] = input_path.read_text(encoding="utf-8")
    return songs


def corpus_line_length(corpus_texts: List[str]) -> Dict[str, float]:
    """Words-per-line distribution across all real lines — the style reference."""
    lens = []
    for t in corpus_texts:
        lens.extend(len(ln.split()) for ln in content_lines(t))
    if not lens:
        return {"n_lines": 0, "mean": 0.0, "median": 0.0, "q1": 0.0, "q3": 0.0}
    q = statistics.quantiles(lens, n=4)
    return {
        "n_lines": len(lens),
        "mean": round(statistics.mean(lens), 2),
        "median": float(statistics.median(lens)),
        "q1": round(q[0], 2),
        "q3": round(q[2], 2),
    }


COLS = [
    "cyr", "line_rep", "gram_rep",
    "near_rep", "near_dup", "anaph", "intra",
    "broken_tags", "line_mean", "line_ov", "gram_ov",
]


def _flat(m: Dict) -> Dict[str, float]:
    """Pull scalar metrics out of the nested bundle for tabular display."""
    nr = m["near_rep"]
    return {
        "cyr": m["cyrillic_ratio"],
        "line_rep": m["line_repetition"],
        "gram_rep": m["gram_repetition"],
        "near_rep": nr["near_rep"],
        "near_dup": nr["near_dup"],
        "anaph": nr["anaphora"],
        "intra": nr["intra_loop"],
        "broken_tags": m["tags"]["broken_total"],
        "line_mean": m["line_length"]["mean"],
        "line_ov": m["corpus_overlap"]["line_overlap"],
        "gram_ov": m["corpus_overlap"]["gram_overlap"],
    }


def print_table(rows: Dict[str, Dict[str, float]]):
    name_w = max([len(n) for n in rows] + [4])
    header = "song".ljust(name_w) + "  " + "  ".join(c.rjust(9) for c in COLS)
    print(header)
    print("-" * len(header))
    for name, vals in rows.items():
        line = name.ljust(name_w) + "  " + "  ".join(f"{vals[c]:>9}" for c in COLS)
        print(line)


def aggregate(rows: Dict[str, Dict[str, float]]) -> Dict[str, str]:
    out = {}
    for c in COLS:
        vals = [r[c] for r in rows.values()]
        mean = statistics.mean(vals)
        std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        out[c] = f"{mean:.3f} ± {std:.3f}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="song file or directory of *.txt songs")
    ap.add_argument("--corpus", default=str(REPO / "data" / "canonical_corpus.jsonl"))
    ap.add_argument("--holdout", default=str(HERE / "holdout_ids.txt"))
    ap.add_argument("--json", default="", help="optional path to dump full metrics JSON")
    ap.add_argument("--judge-bundle", default="", help="optional: emit songs+rubric for the judge")
    args = ap.parse_args()

    holdout = load_holdout_ids(Path(args.holdout))
    corpus_texts = load_corpus(Path(args.corpus), holdout)
    line_set, gram_set = build_corpus_index(corpus_texts)
    ref_ll = corpus_line_length(corpus_texts)

    songs = load_songs(Path(args.input))
    if not songs:
        raise SystemExit(f"No songs found at {args.input}")

    full = {name: all_hard_metrics(text, line_set, gram_set) for name, text in songs.items()}
    rows = {name: _flat(m) for name, m in full.items()}

    print(f"=== CORPUS REFERENCE (non-holdout, {len(corpus_texts)} songs) ===")
    print(f"line length (words/line): mean={ref_ll['mean']} median={ref_ll['median']} "
          f"IQR=[{ref_ll['q1']}, {ref_ll['q3']}]  over {ref_ll['n_lines']} lines")
    print("(candidate line_mean far below this band = style mismatch)\n")

    print(f"=== PER-SONG DRILLDOWN ({len(rows)} songs) ===")
    print_table(rows)

    print("\n=== AGGREGATE (mean ± pstdev) ===")
    for c, v in aggregate(rows).items():
        print(f"  {c:>12}: {v}")

    if args.json:
        payload = {
            "corpus_reference": ref_ll,
            "n_corpus_songs": len(corpus_texts),
            "songs": full,
        }
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFull metrics JSON → {args.json}")

    if args.judge_bundle:
        rubric = (HERE / "rubric.md").read_text(encoding="utf-8")
        parts = ["# Judge bundle\n", rubric, "\n---\n# Songs to score\n"]
        for name, text in songs.items():
            parts.append(f"\n## {name}\n\n```\n{text.strip()}\n```\n")
        Path(args.judge_bundle).write_text("\n".join(parts), encoding="utf-8")
        print(f"\nJudge bundle → {args.judge_bundle} (score N>=3 per song, save to eval/judge_runs/)")


if __name__ == "__main__":
    main()
