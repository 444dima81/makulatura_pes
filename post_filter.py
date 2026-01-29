import re
from dataclasses import dataclass
from typing import List, Tuple

CYR = re.compile(r"[А-Яа-яЁё]")
LAT = re.compile(r"[A-Za-z]")
TAG_OPEN = re.compile(r"^\s*<([A-Z]+)([^>]*)>\s*$")
TAG_CLOSE = re.compile(r"^\s*</([A-Z]+)>\s*$")


@dataclass
class FilterConfig:
    min_words_per_line: int = 3
    max_same_line_repeats: int = 2
    drop_latin_lines: bool = True
    drop_mixed_cyr_lat_words: bool = True
    keep_tag_lines: bool = True
    collapse_whitespace: bool = True


def _is_tag_line(line: str) -> bool:
    return bool(TAG_OPEN.match(line) or TAG_CLOSE.match(line))


def _word_has_cyr_and_lat(word: str) -> bool:
    return bool(CYR.search(word) and LAT.search(word))


def _count_letters(s: str) -> Tuple[int, int]:
    c = len(CYR.findall(s))
    l = len(LAT.findall(s))
    return c, l


def clean_lines(lines: List[str], cfg: FilterConfig) -> List[str]:
    out: List[str] = []
    last_line = None
    last_count = 0

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if cfg.collapse_whitespace:
            line = re.sub(r"\s+", " ", line)

        # теги пропускаем как есть
        if cfg.keep_tag_lines and _is_tag_line(line):
            out.append(line)
            last_line, last_count = line, 0
            continue

        # выкидываем строки с латиницей
        if cfg.drop_latin_lines and LAT.search(line):
            continue

        # выкидываем "findeют" и любые слова со смешанной кириллицей/латиницей
        if cfg.drop_mixed_cyr_lat_words:
            words = re.findall(r"[A-Za-zА-Яа-яЁё0-9_-]+", line)
            if any(_word_has_cyr_and_lat(w) for w in words):
                continue

        # выкидываем строки с явными опечатками/мусорными стыками типа "по-прежему"
        if re.search(r"[А-Яа-яЁё]+-[А-Яа-яЁё]+[А-Яа-яЁё]*", line):
            # оставляем обычные дефисы, но ловим частые глюки
            if "по-преж" in line and "по-прежнему" not in line:
                continue

        # короткие строки (по словам)
        if len(line.split()) < cfg.min_words_per_line:
            continue

        # схлопываем повторы строк
        if last_line == line:
            last_count += 1
            if last_count >= cfg.max_same_line_repeats:
                continue
        else:
            last_line = line
            last_count = 0

        out.append(line)

    return out


def extract_tagged_block(text: str) -> Tuple[str, str, str]:
    """
    Возвращает (tag_name, open_line, close_line).
    Если не найдено — ("", "", "").
    """
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip()]
    open_line = ""
    close_line = ""
    tag = ""
    for ln in lines:
        m = TAG_OPEN.match(ln.strip())
        if m:
            tag = m.group(1)
            open_line = ln.strip()
            break
    for ln in reversed(lines):
        m = TAG_CLOSE.match(ln.strip())
        if m:
            close_line = ln.strip()
            break
    return tag, open_line, close_line


def clean_section_text(text: str, cfg: FilterConfig = FilterConfig()) -> str:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    cleaned = clean_lines(lines, cfg)

    # если потеряли теги, пытаемся восстановить из исходника
    tag, open_line, close_line = extract_tagged_block(text)
    if tag:
        if not cleaned or not TAG_OPEN.match(cleaned[0]):
            cleaned = [open_line] + cleaned
        if not cleaned or not TAG_CLOSE.match(cleaned[-1]):
            cleaned = cleaned + [close_line]

    return "\n".join(cleaned).strip()


def score_section(text: str) -> float:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return -1e9

    content = [ln for ln in lines if not _is_tag_line(ln)]
    if not content:
        return -1e9

    joined = " ".join(content)
    cyr, lat = _count_letters(joined)
    total_letters = max(1, cyr + lat)
    cyr_ratio = cyr / total_letters

    from collections import Counter
    cnt = Counter(content)
    reps = sorted(cnt.values(), reverse=True)
    max_rep = reps[0] if reps else 1
    top3_rep_sum = sum(reps[:3])  # если 2-3 строки доминируют — это луп

    words = joined.split()
    n = 4
    grams = [" ".join(words[i:i+n]) for i in range(0, max(0, len(words)-n+1))]
    gcnt = Counter(grams)
    rep_grams = sum(v-1 for v in gcnt.values() if v > 1)
    gram_penalty = rep_grams / max(1, len(grams))

    avg_len = sum(len(x.split()) for x in content) / max(1, len(content))
    uniq_line_ratio = len(cnt) / max(1, len(content))

    score = 0.0
    score += 4.0 * cyr_ratio
    score += 0.10 * len(content)
    score += 0.20 * avg_len
    score += 2.0 * uniq_line_ratio

    # жёсткие штрафы за лупы
    score -= 2.0 * max(0, max_rep - 2)
    score -= 0.8 * max(0, top3_rep_sum - 8)   # если 3 строки повторяются суммарно слишком часто
    score -= 3.5 * gram_penalty

    if lat > 0:
        score -= 10.0

    return score