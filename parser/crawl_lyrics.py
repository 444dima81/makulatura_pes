import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "ru,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

INDEX_PATH = Path("songs_index.jsonl")
OUT_PATH = Path("songs.jsonl")
ERR_PATH = Path("errors.log")


def parse_lyrics_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select('div[data-lyrics-container="true"]')

    if not containers:
        # fallback (на всякий случай для старых страниц)
        legacy = soup.select_one("div.lyrics")
        if not legacy:
            return ""
        for br in legacy.find_all("br"):
            br.replace_with("\n")
        text = legacy.get_text("\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    chunks = []
    for c in containers:
        for br in c.find_all("br"):
            br.replace_with("\n")
        chunks.append(c.get_text("\n", strip=True))

    text = "\n\n".join(chunks)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def fetch_html(session: requests.Session, url: str) -> str:
    r = session.get(url, headers=HEADERS, timeout=40)
    r.raise_for_status()
    return r.text


def load_index() -> list[dict]:
    songs = []
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            songs.append(json.loads(line))
    return songs


def load_done_urls() -> set[str]:
    done = set()
    if not OUT_PATH.exists():
        return done
    with OUT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                if "url" in obj:
                    done.add(obj["url"])
            except Exception:
                continue
    return done


def log_error(msg: str):
    with ERR_PATH.open("a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def main():
    if not INDEX_PATH.exists():
        raise SystemExit("Нет songs_index.jsonl — сначала запусти get_index.py")

    songs = load_index()
    done = load_done_urls()

    print(f"В индексе: {len(songs)}")
    print(f"Уже скачано: {len(done)}")

    session = requests.Session()

    # чтобы можно было безопасно продолжать
    out_f = OUT_PATH.open("a", encoding="utf-8")

    try:
        for i, s in enumerate(songs, 1):
            title = s.get("title", "").strip()
            url = s.get("url", "").strip()

            if not url:
                continue
            if url in done:
                continue

            print(f"[{i}/{len(songs)}] {title}")

            try:
                html = fetch_html(session, url)
                lyrics = parse_lyrics_from_html(html)

                if not lyrics or len(lyrics) < 100:
                    log_error(f"EMPTY_OR_SHORT\t{url}\t{title}")
                    continue

                rec = {
                    "artist": "Макулатура",
                    "title": title,
                    "url": url,
                    "lyrics": lyrics,
                }
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()

                # бережно к сайту
                time.sleep(0.9)

            except Exception as e:
                log_error(f"ERROR\t{url}\t{title}\t{type(e).__name__}: {e}")
                time.sleep(2.0)

    finally:
        out_f.close()

    print("Готово:", OUT_PATH)
    if ERR_PATH.exists():
        print("Ошибки (если есть):", ERR_PATH)


if __name__ == "__main__":
    main()