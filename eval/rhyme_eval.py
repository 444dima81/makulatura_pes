"""Rhyme metric for generated Makulatura songs, via RPST (Russian Poetry
Scansion Tool, Koziev, MIT). T06.

ISOLATION: this script runs in the SEPARATE `.venv-rpst` (torch/udpipe/... deps
that would conflict with the pinned mlx `.venv`). It imports nothing from the
main repo — fully self-contained. Run it with `.venv-rpst/bin/python`, never the
main interpreter.

Signal: rap mode (Makulatura is hip-hop-adjacent). `align_rap` returns a
per-line "rhyme graph" (rhyming_graf): 0 = the line rhymes with nothing,
non-zero = forward offset to the line it rhymes with. We report:
  rhyme_density = (# lines with non-zero graf) / (# lines)   <- rhyme-specific
  tech_score    = align_rap total score (meter+rhyme composite)  <- secondary

Usage (from repo root):
  .venv-rpst/bin/python eval/rhyme_eval.py --input <file|dir> --models <RPST_models_dir>
"""
import argparse
import glob
import os
import re
import statistics

import russian_scansion

TAG_RE = re.compile(r"^\s*</?[A-Z]+[^>]*>\s*$")


def content_lines(text: str):
    """Non-empty, non-tag lyric lines (mirrors eval/metrics.content_lines,
    inlined to avoid importing the main repo into this venv)."""
    return [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not TAG_RE.match(ln.strip())
    ]


def rhyme_stats(tool, text: str):
    """rhyme_density (fraction of lines that rhyme with something) + tech_score."""
    lines = content_lines(text)
    if len(lines) < 2:
        return {"n_lines": len(lines), "rhyme_density": 0.0, "tech_score": 0.0}
    # RPST.align_rap can crash (IndexError etc.) on Makulatura's slang/OOV — isolate
    # per-song so one bad song doesn't abort the whole set. (T06 Risk 6.)
    try:
        a = tool.align_rap("\n".join(lines))
        grafs = []
        for block in getattr(a, "blocks", []):
            grafs.extend(getattr(block, "rhyming_graf", []))
        if not grafs:
            return {"n_lines": len(lines), "rhyme_density": 0.0, "tech_score": 0.0}
        rhymed = sum(1 for g in grafs if g != 0)
        score = float(a.get_total_score())
        return {
            "n_lines": len(grafs),
            "rhyme_density": round(rhymed / len(grafs), 3),
            "tech_score": round(score, 4),
        }
    except Exception as e:
        return {"n_lines": len(lines), "rhyme_density": None, "tech_score": None,
                "error": type(e).__name__}


def iter_inputs(path: str):
    if os.path.isdir(path):
        for fn in sorted(glob.glob(os.path.join(path, "*.txt"))):
            yield os.path.splitext(os.path.basename(fn))[0], open(fn, encoding="utf-8").read()
    else:
        yield os.path.splitext(os.path.basename(path))[0], open(path, encoding="utf-8").read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="song file or dir of *.txt")
    ap.add_argument("--models", required=True, help="RPST extracted models directory")
    args = ap.parse_args()

    tool = russian_scansion.create_rpst_instance(args.models)

    rows = []
    print(f"{'song':<16} {'n_lines':>8} {'rhyme_density':>14} {'tech_score':>11}")
    print("-" * 52)
    for name, text in iter_inputs(args.input):
        s = rhyme_stats(tool, text)
        rows.append(s)
        if s["rhyme_density"] is None:
            print(f"{name:<16} {s['n_lines']:>8} {'ERR':>14} {s.get('error',''):>11}")
        else:
            print(f"{name:<16} {s['n_lines']:>8} {s['rhyme_density']:>14} {s['tech_score']:>11}")

    ok = [r for r in rows if r["rhyme_density"] is not None]
    n_err = len(rows) - len(ok)
    if len(ok) > 1:
        rd = [r["rhyme_density"] for r in ok]
        ts = [r["tech_score"] for r in ok]
        print("-" * 52)
        print(f"AGGREGATE (mean±pstdev, n={len(ok)} ok, {n_err} err)")
        print(f"  rhyme_density: {statistics.mean(rd):.3f} ± {statistics.pstdev(rd):.3f}")
        print(f"  tech_score   : {statistics.mean(ts):.3f} ± {statistics.pstdev(ts):.3f}")


if __name__ == "__main__":
    main()
