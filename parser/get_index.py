import json
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

ARTIST_SONGS_URL = "https://genius.com/artists/Makulatura/songs"
BASE_URL = "https://genius.com"

def parse_artist_songs_full(url: str, scrolls: int = 140, pause_ms: int = 450) -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="ru-RU",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        )
        page = context.new_page()

        # Блокируем только тяжелое (JS НЕ трогаем)
        def route_filter(route, request):
            if request.resource_type in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        page.route("**/*", route_filter)

        page.set_default_navigation_timeout(120_000)
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)

        # Важно: дождаться, что на странице вообще появились ссылки на lyrics
        page.wait_for_timeout(1500)
        page.wait_for_selector('a[href*="-lyrics"]', timeout=60_000)

        prev_count = 0
        stable_rounds = 0

        for _ in range(scrolls):
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(pause_ms)

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Берём все ссылки на lyrics (абсолютные и относительные)
            hrefs = set()
            for a in soup.select('a[href*="-lyrics"]'):
                h = a.get("href")
                if h:
                    hrefs.add(h)

            cur_count = len(hrefs)

            if cur_count == prev_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                prev_count = cur_count

            if stable_rounds >= 12:
                break

        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "html.parser")

    songs = []
    seen = set()

    for a in soup.select('a[href*="-lyrics"]'):
        href = a.get("href")
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)  # нормализуем относительные ссылки

        # фильтр: только Makulatura
        path = urlparse(full_url).path.lstrip("/")  # "Makulatura-...-lyrics"
        if not path.startswith("Makulatura-"):
            continue

        if full_url in seen:
            continue
        seen.add(full_url)

        h3 = a.find("h3")
        if h3:
            title = h3.get_text(strip=True)
        else:
            core = path.replace("Makulatura-", "").replace("-lyrics", "")
            title = core.replace("-", " ")

        songs.append({"title": title, "url": full_url})

    return songs

if __name__ == "__main__":
    songs = parse_artist_songs_full(ARTIST_SONGS_URL)
    print("Найдено песен:", len(songs))
    print("Первые 10:", songs[:10])

    out = "songs_index.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for s in songs:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print("Сохранено в:", out)