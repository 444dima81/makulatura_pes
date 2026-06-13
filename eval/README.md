# eval/ — quality yardstick for Makulatura song generation

The measuring stick for every later change (T02 inference fixes, T04 retrain).
Built per `1. dev/standards/eval-discipline.md`: **measure before claiming
"better."** Hard metrics are deterministic (single run trustworthy); soft metrics
need a judge, N≥3, and reading transcripts.

## Quick start (run from repo root)

```bash
# 1. build the hold-out reference set (~18 real verses) — once
python3 eval/build_reference.py
#    then MANUALLY open eval/reference/*.txt and confirm no parsing artifacts.

# 2. score a generated song / a folder of songs
python3 eval/run_eval.py --input generated_song.txt
python3 eval/run_eval.py --input eval/reference/        # sanity: real verses

# 3. (soft) emit a judge bundle, score it N>=3, save to eval/judge_runs/, aggregate
python3 eval/run_eval.py --input some_dir/ --judge-bundle eval/judge_bundle.md
python3 eval/judge_aggregate.py
```

## Hard metrics (`metrics.py`, deterministic)

| metric | meaning | good direction |
|---|---|---|
| `cyrillic_ratio` | Cyrillic / (Cyr+Lat) over lyrics | →1.0 (pure Russian) |
| `line_repetition` | fraction of duplicate content lines | →0 |
| `gram_repetition` | fraction of repeated 4-grams (loops) | →0 |
| `broken_tags` | nested + mismatched + unclosed tags | =0 |
| `line_mean` | mean words/line | match corpus band (long!) |
| `line_ov` / `gram_ov` | verbatim overlap with corpus | low — high = memorization/plagiarism |

`run_eval.py` always prints the **corpus reference** line-length band first, so a
candidate's `line_mean` is read against real Makulatura, not in a vacuum
(eval-discipline rule 15: metrics need ground truth).

## Soft metrics (`rubric.md` + `judge_aggregate.py`)

Judge scores grammar / coherence / imagery / style on 1–5. **N≥3 per song**,
report mean±std, read every transcript. Soft scores are hypothesis-grade — ship
decisions lean on hard metrics + per-song drilldown first.

## Files

- `metrics.py` — pure hard-metric functions (reuses `post_filter.py`).
- `build_reference.py` — selects + writes the hold-out reference verses.
- `run_eval.py` — CLI: per-song drilldown + aggregate + corpus reference.
- `rubric.md` — fixed judge rubric (versioned).
- `judge_aggregate.py` — aggregates `judge_runs/*.json`.
- `holdout_ids.txt` — hold-out song ids; **exclude these from training in T03/T04.**
- `reference/` — the real verses (yardstick).
- `judge_runs/` — saved judge scorings (one JSON per run).
