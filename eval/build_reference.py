"""Build the hold-out reference set: ~18 real Makulatura verses, deterministically
selected from the corpus, written one-per-file for manual inspection.

These verses are the STYLE yardstick and MUST be excluded from training in
T03/T04 (read eval/holdout_ids.txt there). Run from repo root:

    python3 eval/build_reference.py
"""
import argparse
import json
import re
from pathlib import Path

# Same block grammar as make_instructions.py: <TYPE ...>\n ... \n</TYPE>
BLOCK_RE = re.compile(r"(?s)(<(?P<tag>[A-Z_]+)\s+[^>]*>\n.*?\n</(?P=tag)>)")

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "canonical_corpus.jsonl"
OUT_DIR = Path(__file__).resolve().parent / "reference"
IDS_FILE = Path(__file__).resolve().parent / "holdout_ids.txt"


def slug_from_url(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    tail = re.sub(r"-lyrics$", "", tail)
    return re.sub(r"[^A-Za-z0-9_-]", "_", tail) or "song"


# A content line starting with closing punctuation = orphaned continuation,
# i.e. a long line the parser wrongly split (e.g. "...иждивенцев" / ", но лишь").
# Lowercase line starts are NOT artifacts — that is Makulatura's style.
_ORPHAN = re.compile(r"^\s*[,;:)»]")


def has_parse_artifact(block: str) -> bool:
    for ln in block.splitlines():
        s = ln.strip()
        if s and not s.startswith("<") and _ORPHAN.match(s):
            return True
    return False


def first_verse_block(text: str) -> str:
    blocks = [(m.group("tag"), m.group(1).strip()) for m in BLOCK_RE.finditer(text)]
    if not blocks:
        return ""
    for tag, block in blocks:
        if tag == "VERSE":
            return block
    return blocks[0][1]  # fallback: first block of any type


def load_corpus():
    items = []
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=18, help="how many verses to hold out")
    args = ap.parse_args()

    items = load_corpus()
    # deterministic, reproducible selection: stable sort by url, keep only songs
    # whose first verse is non-empty AND parse-artifact-free, then evenly space.
    items.sort(key=lambda it: it.get("url", ""))
    candidates = []
    for it in items:
        block = first_verse_block(it.get("text", ""))
        if block and not has_parse_artifact(block):
            candidates.append((it, block))
    n = len(candidates)
    k = min(args.count, n)
    step = n / k
    picked = [candidates[int(i * step)] for i in range(k)]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # clean stale reference files so the set is exactly what we select now
    for old in OUT_DIR.glob("*.txt"):
        old.unlink()

    ids = []
    written = 0
    for it, block in picked:
        slug = slug_from_url(it.get("url", ""))
        (OUT_DIR / f"{slug}.txt").write_text(block + "\n", encoding="utf-8")
        ids.append(it.get("url", ""))
        written += 1

    IDS_FILE.write_text("\n".join(ids) + "\n", encoding="utf-8")
    print(f"Wrote {written} reference verses → {OUT_DIR}")
    print(f"Hold-out ids ({len(ids)}) → {IDS_FILE}")
    print("\nNEXT (AC8): manually open each file, confirm no parsing artifacts")
    print("(orphaned punctuation, broken stitching) before trusting the yardstick.")


if __name__ == "__main__":
    main()
