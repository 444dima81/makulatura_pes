"""Hard (deterministic) quality metrics for generated Makulatura songs.

Reuses regexes/helpers from post_filter (no duplication). All functions are
pure over the input text → identical output on re-run (eval-discipline rule 7).
"""
import os
import sys
import statistics
from collections import Counter
from typing import Dict, List, Set, Tuple

# eval/ is a subdir; put repo root on path so `import post_filter` works
# regardless of the current working directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from post_filter import (  # noqa: E402
    TAG_OPEN,
    TAG_CLOSE,
    _is_tag_line,
    _count_letters,
    _ngrams,
)


def content_lines(text: str) -> List[str]:
    """Non-empty, non-tag lines (the actual lyrics)."""
    return [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not _is_tag_line(ln.strip())
    ]


def cyrillic_ratio(text: str) -> float:
    """Cyrillic letters / (Cyrillic + Latin). 1.0 = pure Russian, low = garbage."""
    joined = " ".join(content_lines(text))
    cyr, lat = _count_letters(joined)
    total = cyr + lat
    return cyr / total if total else 0.0


def line_repetition_rate(text: str) -> float:
    """Fraction of content lines that are duplicates. 0 = all unique."""
    lines = content_lines(text)
    if not lines:
        return 0.0
    cnt = Counter(lines)
    duplicates = sum(c - 1 for c in cnt.values())
    return duplicates / len(lines)


def gram_repetition_rate(text: str, n: int = 4) -> float:
    """Fraction of n-grams that are repeats. Catches loop-y degeneration."""
    words = " ".join(content_lines(text)).split()
    grams = _ngrams(words, n)
    if not grams:
        return 0.0
    cnt = Counter(grams)
    duplicates = sum(c - 1 for c in cnt.values() if c > 1)
    return duplicates / len(grams)


def tag_health(text: str) -> Dict[str, int]:
    """Structural tag integrity. broken_total > 0 = malformed structure
    (nested sections, mismatched/unclosed tags — e.g. <OUTRO> wrapping <VERSE>).
    """
    stack: List[str] = []
    nested = mismatched = tag_lines = 0
    for raw in text.splitlines():
        ln = raw.strip()
        mo = TAG_OPEN.match(ln)
        mc = TAG_CLOSE.match(ln)
        if mo:
            tag_lines += 1
            if stack:  # opening a section while another is still open
                nested += 1
            stack.append(mo.group(1))
        elif mc:
            tag_lines += 1
            if stack and stack[-1] == mc.group(1):
                stack.pop()
            else:
                mismatched += 1
    unclosed = len(stack)
    return {
        "tag_lines": tag_lines,
        "nested": nested,
        "mismatched": mismatched,
        "unclosed": unclosed,
        "broken_total": nested + mismatched + unclosed,
    }


def _quantiles(values: List[float]) -> Tuple[float, float]:
    """(q1, q3); degrades gracefully for tiny samples."""
    if len(values) < 2:
        v = values[0] if values else 0.0
        return v, v
    q = statistics.quantiles(values, n=4)  # [q1, q2, q3]
    return q[0], q[2]


def line_length_stats(text: str) -> Dict[str, float]:
    """Words-per-line distribution. Makulatura's real style is LONG lines."""
    lens = [len(ln.split()) for ln in content_lines(text)]
    if not lens:
        return {"n_lines": 0, "mean": 0.0, "median": 0.0, "q1": 0.0, "q3": 0.0}
    q1, q3 = _quantiles(lens)
    return {
        "n_lines": len(lens),
        "mean": round(statistics.mean(lens), 2),
        "median": float(statistics.median(lens)),
        "q1": round(q1, 2),
        "q3": round(q3, 2),
    }


def build_corpus_index(corpus_texts: List[str], n: int = 4) -> Tuple[Set[str], Set[str]]:
    """Index of all content lines and n-grams in the (non-holdout) real corpus.
    Used to detect memorization/plagiarism in generated output.
    """
    line_set: Set[str] = set()
    gram_set: Set[str] = set()
    for t in corpus_texts:
        cl = content_lines(t)
        line_set |= set(cl)
        gram_set |= set(_ngrams(" ".join(cl).split(), n))
    return line_set, gram_set


def corpus_overlap(
    text: str, line_set: Set[str], gram_set: Set[str], n: int = 4
) -> Dict[str, float]:
    """Fraction of a candidate's lines / n-grams copied verbatim from the corpus.
    High = the model memorized rather than learned the style.
    """
    cl = content_lines(text)
    if not cl:
        return {"line_overlap": 0.0, "gram_overlap": 0.0}
    line_overlap = sum(1 for ln in cl if ln in line_set) / len(cl)
    grams = _ngrams(" ".join(cl).split(), n)
    gram_overlap = (
        sum(1 for g in grams if g in gram_set) / len(grams) if grams else 0.0
    )
    return {
        "line_overlap": round(line_overlap, 3),
        "gram_overlap": round(gram_overlap, 3),
    }


def all_hard_metrics(
    text: str, line_set: Set[str], gram_set: Set[str]
) -> Dict[str, object]:
    """Full deterministic metric bundle for one song."""
    return {
        "cyrillic_ratio": round(cyrillic_ratio(text), 3),
        "line_repetition": round(line_repetition_rate(text), 3),
        "gram_repetition": round(gram_repetition_rate(text), 3),
        "tags": tag_health(text),
        "line_length": line_length_stats(text),
        "corpus_overlap": corpus_overlap(text, line_set, gram_set),
    }
