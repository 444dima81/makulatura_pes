# make_instructions.py
# Создаёт датасет под mlx_lm_lora.train (chat-style JSONL)
# Вход:  data/canonical_corpus.jsonl
# Выход: data/mlx_dataset/train.jsonl и valid.jsonl

import json
import random
import re
from pathlib import Path
from typing import List, Dict, Tuple

IN_PATH = Path("data/canonical_corpus.jsonl")
OUT_DIR = Path("data/mlx_dataset")
TRAIN_PATH = OUT_DIR / "train.jsonl"
VALID_PATH = OUT_DIR / "valid.jsonl"

RNG_SEED = 42
VALID_RATIO = 0.05  # ~5%

SYSTEM_PROMPT = (
    "Ты — поэтический генератор песен в стиле группы «Макулатура». "
    "Соблюдай структуру и теги секций (<VERSE>, <CHORUS>, <BRIDGE>, <INTRO>, <OUTRO>, <REFRAIN>, <HOOK>). "
    "Сохраняй голос, заданный атрибутом speaker (alekhin/speransky/group). "
    "Пиши по-русски. Не добавляй пояснений, только текст песен/секций в требуемом формате."
)

TOPICS = [
    "отчуждение в городе", "тревога и бессонница", "память и вина", "поездка и расставание",
    "социум и одиночество", "любовь как болезнь", "зима и пустые улицы", "больница и свобода",
    "детство и стыд", "жизнь после разрыва", "алкоголь и пустота", "страх будущего",
]

# --- разбор канонического текста на блоки <TYPE ...> ... </TYPE> ---
BLOCK_RE = re.compile(
    r"(?s)(<(?P<tag>[A-Z_]+)\s+[^>]*>\n.*?\n</(?P=tag)>)"
)

# --- Добавлено: Регулярка для поиска спикера ---
SPEAKER_RE = re.compile(r'speaker=["\']?(?P<name>\w+)["\']?')

def load_canonical() -> List[Dict]:
    items = []
    with IN_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items

def extract_blocks(canonical_text: str) -> List[str]:
    canonical_text = canonical_text.strip()
    blocks = [m.group(1).strip() for m in BLOCK_RE.finditer(canonical_text)]
    return blocks

# --- Добавлено: Функция определения спикера из текста блока ---
def get_speaker_from_block(block_text: str) -> str:
    """Возвращает имя спикера (alekhin, speransky, group) или None, если тега нет"""
    match = SPEAKER_RE.search(block_text)
    if match:
        return match.group("name")
    return "speransky" # Дефолт, если вдруг тег потерялся

def pick_theme(title: str, rng: random.Random) -> str:
    if rng.random() < 0.55:
        return rng.choice(TOPICS)
    base = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
    return base if base else rng.choice(TOPICS)

def mk_chat_example(user: str, assistant: str) -> Dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }

def task_full_song(item: Dict, rng: random.Random) -> Dict:
    theme = pick_theme(item.get("title", ""), rng)
    structure = item.get("structure", "")
    user = (
        "Напиши песню в стиле группы «Макулатура».\n"
        f"Тема: {theme}\n"
        f"Структура: {structure}\n"
        "Верни результат строго в каноническом формате с тегами секций."
    )
    return mk_chat_example(user, item["text"].strip())

def task_next_section(item: Dict, rng: random.Random, context_blocks: int = 2) -> Dict | None:
    blocks = extract_blocks(item["text"])
    if len(blocks) < 2:
        return None

    i = rng.randint(1, len(blocks) - 1)
    prefix = blocks[max(0, i - context_blocks):i]
    target = blocks[i].strip()

    # --- ИЗМЕНЕНИЕ: Определяем спикера и добавляем в промпт ---
    target_speaker = get_speaker_from_block(target)

    theme = pick_theme(item.get("title", ""), rng)
    user = (
        "Продолжи песню в стиле группы «Макулатура».\n"
        f"Тема: {theme}\n"
        "Ниже приведён контекст (последние секции). \n"
        f"Напиши СЛЕДУЮЩУЮ секцию. Обязательное требование: голос = {target_speaker}.\n"
        "Верни ровно один блок секции с тегами.\n\n"
        "КОНТЕКСТ:\n"
        + "\n\n".join(prefix)
    )
    return mk_chat_example(user, target)

def task_chorus_only(item: Dict, rng: random.Random) -> Dict | None:
    blocks = extract_blocks(item["text"])
    choruses = [b for b in blocks if b.startswith("<CHORUS")]
    if not choruses:
        return None
    target = rng.choice(choruses).strip()

    # --- ИЗМЕНЕНИЕ: Определяем спикера и добавляем в промпт ---
    target_speaker = get_speaker_from_block(target)

    theme = pick_theme(item.get("title", ""), rng)
    user = (
        "Напиши один припев (CHORUS) в стиле группы «Макулатура».\n"
        f"Тема: {theme}\n"
        f"Голос: {target_speaker}\n"
        "Верни ровно один блок <CHORUS ...>...</CHORUS> без пояснений."
    )
    return mk_chat_example(user, target)

def build_dataset(items: List[Dict], rng: random.Random) -> List[Dict]:
    out: List[Dict] = []
    for it in items:
        text = (it.get("text") or "").strip()
        if not text:
            continue

        # 1) полный трек (1 пример на песню)
        out.append(task_full_song(it, rng))

        # 2) продолжение секции (1–2 примера на песню, если есть что продолжать)
        ex = task_next_section(it, rng, context_blocks=2)
        if ex:
            out.append(ex)
        if rng.random() < 0.35:
            ex2 = task_next_section(it, rng, context_blocks=1)
            if ex2:
                out.append(ex2)

        # 3) припев отдельно (иногда)
        if rng.random() < 0.45:
            ex3 = task_chorus_only(it, rng)
            if ex3:
                out.append(ex3)

    rng.shuffle(out)
    return out

def write_jsonl(path: Path, rows: List[Dict]):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def main():
    if not IN_PATH.exists():
        raise SystemExit(f"Нет входного файла: {IN_PATH}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rng = random.Random(RNG_SEED)
    items = load_canonical()

    dataset = build_dataset(items, rng)

    # train/valid split
    n = len(dataset)
    n_valid = max(1, int(n * VALID_RATIO))
    valid = dataset[:n_valid]
    train = dataset[n_valid:]

    write_jsonl(TRAIN_PATH, train)
    write_jsonl(VALID_PATH, valid)

    print("Готово.")
    print(f"Всего примеров: {n}")
    print(f"train: {len(train)} -> {TRAIN_PATH}")
    print(f"valid: {len(valid)} -> {VALID_PATH}")

if __name__ == "__main__":
    main()