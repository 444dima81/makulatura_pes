# make_canonical_text.py
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

IN_PATH = Path("../data/songs_marked.jsonl")

OUT_TXT = Path("../data/canonical_corpus.txt")
OUT_JSONL = Path("../data/canonical_corpus.jsonl")
OUT_INDEX = Path("../data/canonical_index.jsonl")


def sanitize_text(text: str) -> str:
    """
    Мягкая нормализация:
    - убрать хвостовые пробелы
    - сжать слишком много пустых строк
    - нормализовать переносы
    """
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def section_label(sec: Dict[str, Any]) -> str:
    t = sec.get("type", "OTHER")
    idx = sec.get("index", None)
    sp = sec.get("speaker", "unknown")
    if t == "VERSE" and idx is not None:
        return f"{t}{idx}({sp})"
    return f"{t}({sp})"


def build_structure_line(sections: List[Dict[str, Any]]) -> str:
    return " > ".join(section_label(s) for s in sections)


def tag_open(sec: Dict[str, Any]) -> str:
    t = sec.get("type", "OTHER")
    sp = sec.get("speaker", "unknown")
    idx = sec.get("index", None)

    attrs = [f"speaker={sp}"]
    if idx is not None:
        attrs.insert(0, f"index={idx}")

    # ORDER можно оставить, но обычно не нужно внутри тега
    return f"<{t} " + " ".join(attrs) + ">"


def tag_close(sec: Dict[str, Any]) -> str:
    t = sec.get("type", "OTHER")
    return f"</{t}>"


def canonicalize_song(obj: Dict[str, Any]) -> Dict[str, Any]:
    artist = obj.get("artist", "")
    title = obj.get("title", "")
    url = obj.get("url", "")
    dominant = obj.get("dominant_voice", "unknown")
    sections = obj.get("sections", [])

    # сортируем по order, если вдруг где-то нарушено
    sections = sorted(sections, key=lambda s: (s.get("order", 10**9), s.get("index") is None, s.get("index", 0)))

    structure = build_structure_line(sections)

    blocks: List[str] = []
    for sec in sections:
        text = sanitize_text(sec.get("text", ""))
        if not text:
            continue
        blocks.append(tag_open(sec))
        blocks.append(text)
        blocks.append(tag_close(sec))
        blocks.append("")  # пустая строка между секциями

    canonical_text = "\n".join(blocks).rstrip()

    # метрики для индекса
    n_sections = len([s for s in sections if sanitize_text(s.get("text", ""))])
    n_chars = len(canonical_text)

    return {
        "artist": artist,
        "title": title,
        "url": url,
        "dominant_voice": dominant,
        "structure": structure,
        "canonical_text": canonical_text,
        "n_sections": n_sections,
        "n_chars": n_chars,
    }


def main():
    if not IN_PATH.exists():
        raise SystemExit("Нет songs_marked.jsonl — сначала запусти normalize_songs.py")

    OUT_TXT.write_text("", encoding="utf-8")
    OUT_JSONL.write_text("", encoding="utf-8")
    OUT_INDEX.write_text("", encoding="utf-8")

    n = 0
    with IN_PATH.open("r", encoding="utf-8") as f_in, \
         OUT_TXT.open("w", encoding="utf-8") as f_txt, \
         OUT_JSONL.open("w", encoding="utf-8") as f_jsonl, \
         OUT_INDEX.open("w", encoding="utf-8") as f_idx:

        for line in f_in:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            can = canonicalize_song(obj)

            # 1) TXT-корпус
            f_txt.write("=== SONG ===\n")
            f_txt.write(f"TITLE: {can['title']}\n")
            f_txt.write(f"URL: {can['url']}\n")
            f_txt.write(f"ARTIST: {can['artist']}\n")
            f_txt.write(f"DOMINANT_VOICE: {can['dominant_voice']}\n")
            f_txt.write(f"STRUCTURE: {can['structure']}\n\n")
            f_txt.write(can["canonical_text"])
            f_txt.write("\n=== END SONG ===\n\n")

            # 2) JSONL (по песне на строку)
            f_jsonl.write(json.dumps({
                "artist": can["artist"],
                "title": can["title"],
                "url": can["url"],
                "dominant_voice": can["dominant_voice"],
                "structure": can["structure"],
                "text": can["canonical_text"],
            }, ensure_ascii=False) + "\n")

            # 3) индекс
            f_idx.write(json.dumps({
                "title": can["title"],
                "url": can["url"],
                "dominant_voice": can["dominant_voice"],
                "structure": can["structure"],
                "n_sections": can["n_sections"],
                "n_chars": can["n_chars"],
            }, ensure_ascii=False) + "\n")

            n += 1

    print(f"Готово. Песен обработано: {n}")
    print("Файлы:")
    print(f" - {OUT_TXT}")
    print(f" - {OUT_JSONL}")
    print(f" - {OUT_INDEX}")


if __name__ == "__main__":
    main()