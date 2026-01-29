# normalize_songs.py
import json
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from collections import defaultdict


IN_PATH = Path("../data/songs.jsonl")
OUT_PATH = Path("../data/songs_marked.jsonl")

# --- Настройка распознавания спикеров ---
SPEAKER_MAP = {
    # варианты написания -> канон
    "алёхин": "alekhin",
    "алехин": "alekhin",
    "евгений алёхин": "alekhin",
    "евгений алехин": "alekhin",

    "сперанский": "speransky",
    "константин сперанский": "speransky",
}

# --- Нормализация типов секций ---
SECTION_TYPE_PATTERNS = [
    (re.compile(r"^\s*(куплет|verse)\b", re.I), "VERSE"),
    (re.compile(r"^\s*(припев|chorus)\b", re.I), "CHORUS"),
    (re.compile(r"^\s*(бридж|bridge)\b", re.I), "BRIDGE"),
    (re.compile(r"^\s*(интро|intro)\b", re.I), "INTRO"),
    (re.compile(r"^\s*(аутро|outro)\b", re.I), "OUTRO"),
    (re.compile(r"^\s*(рефрен|refrain)\b", re.I), "REFRAIN"),
    (re.compile(r"^\s*(хук|hook)\b", re.I), "HOOK"),
]

# Мусорные строки Genius/страницы
JUNK_LINE_PATTERNS = [
    re.compile(r"^\s*\d+\s+contributors?\s*$", re.I),
    re.compile(r"^\s*read more\s*$", re.I),
    re.compile(r"^\s*you might also like\s*$", re.I),
    re.compile(r".*\blyrics\b\s*$", re.I),  # строка вида "... Lyrics"
]

# Иногда до [Текст песни ...] есть описания — режем всё до маркера.
TEXT_SONG_MARKER = re.compile(r"^\s*\[текст песни", re.I)

# Заголовок секции: [Куплет 1: Сперанский] / [Припев: Алёхин]
SECTION_HEADER_RE = re.compile(r"^\s*\[(?P<header>.+?)\]\s*:?\s*$")


def normalize_speaker(raw: Optional[str]) -> str:
    if not raw:
        return "group"
    s = raw.strip().lower()
    s = s.replace("ё", "е")  # чтобы "алёхин" и "алехин" совпадали
    s = re.sub(r"feat\.?|ft\.?", "", s).strip()
    s = re.sub(r"\s+", " ", s)

    # точные маппинги
    for k, v in SPEAKER_MAP.items():
        kk = k.replace("ё", "е")
        if s == kk:
            return v

    # частичное вхождение (Евгений Алёхин, Алёхин и т.п.)
    for k, v in SPEAKER_MAP.items():
        kk = k.replace("ё", "е")
        if kk in s:
            return v

    return "group"


def normalize_section_type(header_text: str) -> str:
    ht = header_text.strip().lower()
    for pat, typ in SECTION_TYPE_PATTERNS:
        if pat.search(ht):
            return typ
    return "OTHER"


def parse_section_header(header: str) -> Tuple[str, Optional[int], Optional[str]]:
    """
    Возвращает: (section_type, index, speaker_raw)
    header может быть:
      "Куплет 1: Сперанский"
      "Припев: Алёхин"
      "Куплет 2"
    """
    parts = [p.strip() for p in header.split(":", 1)]
    left = parts[0]
    speaker_raw = parts[1] if len(parts) == 2 else None

    section_type = normalize_section_type(left)

    m = re.search(r"\b(\d+)\b", left)
    idx = int(m.group(1)) if m else None

    return section_type, idx, speaker_raw


def strip_pre_text(lines: List[str]) -> List[str]:
    """
    Если есть маркер [Текст песни ...], то всё до него выбрасываем.
    """
    for i, ln in enumerate(lines):
        if TEXT_SONG_MARKER.search(ln):
            return lines[i:]
    return lines


def is_junk_line(line: str) -> bool:
    ln = line.strip()
    if not ln:
        return False
    for pat in JUNK_LINE_PATTERNS:
        if pat.match(ln):
            return True
    return False


def stitch_broken_lines(text: str) -> str:
    """
    Склеивает разорванные переносами одиночные слова/знаки препинания:
      "Несколько\nиждивенцев\n, но лишь" -> "Несколько иждивенцев, но лишь"
    Делает это мягко, чтобы не испортить намеренные переносы строк.
    """
    lines = text.split("\n")
    out: List[str] = []
    i = 0

    def is_fragment(s: str) -> bool:
        s = s.strip()
        if not s:
            return False
        # одиночное слово / короткий фрагмент без пробелов
        if len(s) <= 14 and " " not in s:
            return True
        # одиночный знак препинания
        if s in {",", ".", "—", "-", "…", ":", ";", "!", "?", ")", "(", "»", "«"}:
            return True
        return False

    while i < len(lines):
        cur = lines[i].strip()
        if not cur:
            out.append("")
            i += 1
            continue

        # если текущая строка короткая и следующая тоже короткая — склеиваем
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if nxt and is_fragment(nxt) and cur and not cur.endswith(("\n", "")):
                # аккуратно склеим: пробел перед словом, без пробела перед пунктуацией
                if nxt in {",", ".", "—", "-", "…", ":", ";", "!", "?", ")", "»"}:
                    cur = cur + nxt
                else:
                    cur = cur + " " + nxt
                i += 2

                # также попробуем схлопнуть цепочку из нескольких фрагментов
                while i < len(lines):
                    nxt2 = lines[i].strip()
                    if nxt2 and is_fragment(nxt2):
                        if nxt2 in {",", ".", "—", "-", "…", ":", ";", "!", "?", ")", "»"}:
                            cur = cur + nxt2
                        else:
                            cur = cur + " " + nxt2
                        i += 1
                    else:
                        break

                out.append(cur)
                continue

        out.append(cur)
        i += 1

    text2 = "\n".join(out)
    text2 = re.sub(r"\n{3,}", "\n\n", text2).strip()
    return text2


def clean_lyrics(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [l.strip() for l in text.split("\n")]

    lines = strip_pre_text(lines)

    cleaned: List[str] = []
    for ln in lines:
        if not ln:
            cleaned.append("")
            continue

        # выбросим сам маркер [Текст песни ...]
        if TEXT_SONG_MARKER.search(ln):
            continue

        # выбрасываем любые заголовки секций [Куплет ...], [Припев ...] и т.п.
        if SECTION_HEADER_RE.match(ln):
            continue

        if is_junk_line(ln):
            continue

        cleaned.append(ln)

    out = "\n".join(cleaned)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    out = stitch_broken_lines(out)
    return out


def split_into_sections(raw_text: str) -> List[Dict]:
    """
    Делит исходный текст (где ещё есть заголовки секций в [...]) по заголовкам,
    и возвращает sections[]. При этом заголовки НЕ включаются в секционный text.
    """
    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    sections = []
    cur_type = "OTHER"
    cur_idx = None
    cur_speaker = "unknown"
    cur_buf: List[str] = []

    last_speaker = "unknown"

    def flush():
        nonlocal cur_buf, cur_type, cur_idx, cur_speaker, last_speaker
        # выкидываем пустые и мусорные строки из секционного текста
        buf = []
        for x in cur_buf:
            x = x.strip()
            if not x:
                buf.append("")
                continue
            if TEXT_SONG_MARKER.search(x):
                continue
            if is_junk_line(x):
                continue
            if SECTION_HEADER_RE.match(x):
                continue
            buf.append(x)

        text = "\n".join(buf).strip()
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        text = stitch_broken_lines(text)

        if text:
            sec = {
                "type": cur_type,
                "index": cur_idx,
                "speaker": cur_speaker,
                "text": text,
            }
            sections.append(sec)
            if cur_speaker != "unknown":
                last_speaker = cur_speaker

        cur_buf = []

    # перед разбором: обрежем пролог до [Текст песни ...], чтобы не попадали описания
    lines = strip_pre_text([l.strip() for l in lines])

    for ln in lines:
        ln = ln.strip()
        if not ln:
            cur_buf.append("")
            continue

        m = SECTION_HEADER_RE.match(ln)
        if m:
            header = m.group("header").strip()
            sec_type, sec_idx, speaker_raw = parse_section_header(header)

            is_real_section = (sec_type != "OTHER") or bool(
                re.match(r"^\s*(куплет|припев|бридж|интро|аутро|рефрен|хук)\b", header, re.I)
            )

            if is_real_section:
                flush()
                cur_type = sec_type
                cur_idx = sec_idx

                sp = normalize_speaker(speaker_raw)
                if sp == "unknown" and last_speaker != "unknown":
                    sp = last_speaker  # мягкое наследование голоса

                cur_speaker = sp
                continue  # заголовок не включаем

        # обычная строка
        if TEXT_SONG_MARKER.search(ln) or is_junk_line(ln):
            continue
        cur_buf.append(ln)

    flush()

    if not sections:
        # если заголовков не было — одна секция OTHER
        cleaned = clean_lyrics(raw_text)
        if cleaned:
            sections = [{"type": "OTHER", "index": None, "speaker": "unknown", "text": cleaned}]

    # добавим order
    for i, s in enumerate(sections):
        s["order"] = i

    return sections


def dominant_voice_by_textlen(sections: List[Dict]) -> str:
    speaker_len = defaultdict(int)
    for s in sections:
        sp = s.get("speaker", "unknown")
        if sp and sp != "unknown":
            speaker_len[sp] += len(s.get("text", ""))

    if not speaker_len:
        return "group"
    return max(speaker_len, key=speaker_len.get)


def main():
    if not IN_PATH.exists():
        raise SystemExit("Нет songs.jsonl (вход).")

    with IN_PATH.open("r", encoding="utf-8") as f_in, OUT_PATH.open("w", encoding="utf-8") as f_out:
        n_in, n_out = 0, 0
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            n_in += 1
            obj = json.loads(line)

            raw = obj.get("lyrics", "")

            # sections делаем из raw (там есть заголовки), но сами заголовки в text секций не попадут
            sections = split_into_sections(raw)

            # lyrics_clean делаем чисто: без заголовков секций
            lyrics_clean = clean_lyrics(raw)

            speakers = {s["speaker"] for s in sections if s["speaker"] not in ("group",)}
            if len(speakers) == 1:
                inferred = next(iter(speakers))
                for s in sections:
                    if s["speaker"] == "group":
                        s["speaker"] = inferred
                        
            out = {
                "artist": obj.get("artist"),
                "title": obj.get("title"),
                "url": obj.get("url"),
                "lyrics_clean": lyrics_clean,
                "sections": sections,
            }

            out["dominant_voice"] = dominant_voice_by_textlen(sections)

            f_out.write(json.dumps(out, ensure_ascii=False) + "\n")
            n_out += 1

        print(f"Готово. Прочитано: {n_in}, записано: {n_out}")
        print(f"Выход: {OUT_PATH}")


if __name__ == "__main__":
    main()