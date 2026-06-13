"""Aggregate soft judge runs from eval/judge_runs/*.json into mean±std per song
per dimension. Enforces the N>=3 discipline (warns on under-sampled songs).

Usage (from repo root):
    python3 eval/judge_aggregate.py
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS_DIR = HERE / "judge_runs"
DIMENSIONS = ["grammar", "coherence", "imagery", "style"]
MIN_RUNS = 3  # eval-discipline rule 5


def main():
    runs = sorted(RUNS_DIR.glob("*.json"))
    if not runs:
        raise SystemExit(f"No judge runs in {RUNS_DIR}. Score songs per eval/rubric.md first.")

    by_song = defaultdict(list)
    for p in runs:
        rec = json.loads(p.read_text(encoding="utf-8"))
        by_song[rec["song"]].append(rec["scores"])

    for song, score_list in by_song.items():
        n = len(score_list)
        flag = "" if n >= MIN_RUNS else f"  ⚠ N={n} < {MIN_RUNS} (under-sampled, treat as hypothesis)"
        print(f"\n=== {song}  (N={n}){flag}")
        for dim in DIMENSIONS:
            vals = [s[dim] for s in score_list if dim in s]
            if not vals:
                continue
            mean = statistics.mean(vals)
            std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
            print(f"  {dim:>10}: {mean:.2f} ± {std:.2f}")
    print("\nReminder: read the transcripts/notes — do not act on aggregate alone (rule 29).")


if __name__ == "__main__":
    main()
