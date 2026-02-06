import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple

from post_filter import clean_section_text, score_section, score_section_in_context, FilterConfig

SYSTEM = """Ты — поэтический генератор песен в стиле группы «Макулатура».

Правила:
- Пиши по-русски, связно и образно.
- Избегай повторов одной строки более 2 раз подряд.
- Каждая строка должна передавать образ, действие или состояние.
- Не добавляй пояснений и комментариев, только текст секций.

Стиль:
- Строки короткие, насыщенные образами (обычно до 12-15 слов).
- Используй метафоры, культурные отсылки, неожиданные сравнения.
- Не пиши объяснениями и описаниями — пиши образами.
- НИКОГДА не копируй и не пересказывай строки из контекста.

Соблюдай структуру и теги секций (<VERSE>, <CHORUS>, <OUTRO>) и атрибут speaker (alekhin/speransky/group).
""".strip()


def run_mlx_generate(
    model: str,
    adapter_dir: str,
    system_prompt: str,
    prompt: str,
    max_tokens: int,
    temp: float,
    top_p: float,
    top_k: int,
    min_p: float,
    seed: int,
) -> str:
    cmd = [
        "mlx_lm.generate",
        "--model", model,
        "--adapter-path", adapter_dir,
        "--system-prompt", system_prompt,
        "--prompt", prompt,
        "--max-tokens", str(max_tokens),
        "--temp", str(temp),
        "--top-p", str(top_p),
        "--top-k", str(top_k),
        "--min-p", str(min_p),
        "--seed", str(seed),
        "--verbose", "F",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "mlx_lm.generate failed")
    return res.stdout.strip()


def section_open_tag(sec_type: str, speaker: str, index: int | None) -> str:
    if sec_type == "VERSE" and index is not None:
        return f"<VERSE index={index} speaker={speaker}>"
    # для CHORUS/OUTRO index обычно не нужен
    return f"<{sec_type} speaker={speaker}>"


def section_close_tag(sec_type: str) -> str:
    return f"</{sec_type}>"


def build_section_prompt(
    theme: str,
    sec_type: str,
    speaker: str,
    index: int | None,
    context: str,
) -> str:
    tag_open = section_open_tag(sec_type, speaker, index)
    tag_close = section_close_tag(sec_type)

    rules = (
        "Сгенерируй РОВНО ОДНУ секцию.\n"
        f"Секция должна начинаться строкой:\n{tag_open}\n"
        f"и заканчиваться строкой:\n{tag_close}\n"
        "Минимум 8 строк текста внутри секции.\n"
        "Запрещено использовать латиницу.\n"
        "Запрещено повторять одну и ту же строку более 2 раз подряд.\n"
        "Каждая строка должна содержать конкретный образ/действие/наблюдение.\n"
        "Никаких пояснений — только секция.\n"
    )

    if context.strip():
        return (
            f"Тема: {theme}\n"
            f"{rules}\n"
            "Не повторяй и не переписывай строки из контекста. Каждая строка должна быть новой.\n\n"
            "КОНТЕКСТ (предыдущие секции, чтобы продолжать связно):\n"
            f"{context.strip()}\n"
        )
    return f"Тема: {theme}\n{rules}\n"


def choose_best_candidate(cands: List[str], context: str = "") -> Tuple[str, float]:
    best = ""
    best_score = -1e18
    for c in cands:
        if context:
            s = score_section_in_context(c, context)
        else:
            s = score_section(c)
        if s > best_score:
            best_score = s
            best = c
    return best, best_score


def generate_section_with_retries(
    model: str,
    adapter_dir: str,
    theme: str,
    sec_type: str,
    speaker: str,
    index: int | None,
    context: str,
    max_tokens: int,
    temp: float,
    top_p: float,
    top_k: int,
    min_p: float,
    seed: int,
    tries: int,
    filter_cfg: FilterConfig,
) -> str:
    prompt = build_section_prompt(theme, sec_type, speaker, index, context)

    candidates: List[str] = []
    for t in range(tries):
        out = run_mlx_generate(
            model=model,
            adapter_dir=adapter_dir,
            system_prompt=SYSTEM,
            prompt=prompt,
            max_tokens=max_tokens,
            temp=temp,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            seed=seed + t,
        )

        cleaned = clean_section_text(out, cfg=filter_cfg)

        # если после фильтра стало слишком коротко — всё равно оставим как кандидат,
        # но скоринг его утопит
        candidates.append(cleaned)

    best, _ = choose_best_candidate(candidates, context=context)
    return best.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", required=True)
    ap.add_argument("--structure", required=True, help='Напр: "VERSE(speransky) > CHORUS(alekhin) > VERSE(speransky) > CHORUS(alekhin) > OUTRO(alekhin)"')
    ap.add_argument("--model", default="mlx-community/Llama-3.2-3B-Instruct-4bit")
    ap.add_argument("--adapter_dir", default="adapters")

    ap.add_argument("--max_tokens_section", type=int, default=260)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--top_p", type=float, default=0.9)
    ap.add_argument("--top_k", type=int, default=40)
    ap.add_argument("--min_p", type=float, default=0.06)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tries", type=int, default=3)

    ap.add_argument("--min_words_per_line", type=int, default=3)
    ap.add_argument("--out", default="generated_song.txt")
    args = ap.parse_args()

    # парсим структуру: TYPE(speaker)
    parts = [p.strip() for p in args.structure.split(">")]
    plan: List[Dict] = []
    verse_idx = 0
    for p in parts:
        if not p:
            continue
        # VERSE(speransky)
        if "(" not in p or ")" not in p:
            raise SystemExit(f"Не понял элемент структуры: {p}")
        sec_type = p.split("(")[0].strip().upper()
        speaker = p.split("(", 1)[1].split(")", 1)[0].strip().lower()

        index = None
        if sec_type == "VERSE":
            verse_idx += 1
            index = verse_idx

        plan.append({"type": sec_type, "speaker": speaker, "index": index})

    filter_cfg = FilterConfig(
        min_words_per_line=args.min_words_per_line,
        max_same_line_repeats=2,
        drop_latin_lines=True,
        drop_mixed_cyr_lat_words=True,
        keep_tag_lines=True,
        collapse_whitespace=True,
    )

    generated: List[str] = []
    context_window_sections = 2  # сколько последних секций давать в контекст

    for i, step in enumerate(plan):
        context = "\n\n".join(generated[-context_window_sections:])

        sec_text = generate_section_with_retries(
            model=args.model,
            adapter_dir=args.adapter_dir,
            theme=args.theme,
            sec_type=step["type"],
            speaker=step["speaker"],
            index=step["index"],
            context=context,
            max_tokens=args.max_tokens_section,
            temp=args.temp,
            top_p=args.top_p,
            top_k=args.top_k,
            min_p=args.min_p,
            seed=args.seed + i * 100,
            tries=args.tries,
            filter_cfg=filter_cfg,
        )

        if step["type"] == "OUTRO":
            inner = [ln for ln in sec_text.splitlines() if ln.strip() and not ln.strip().startswith("<")]
            if len(inner) < 4:
                sec_text = generate_section_with_retries(
                    model=args.model,
                    adapter_dir=args.adapter_dir,
                    theme=args.theme,
                    sec_type=step["type"],
                    speaker=step["speaker"],
                    index=step["index"],
                    context=context,
                    max_tokens=max(300, args.max_tokens_section),
                    temp=min(0.85, args.temp + 0.1),
                    top_p=min(0.92, args.top_p + 0.04),
                    top_k=max(60, args.top_k),
                    min_p=max(0.05, args.min_p - 0.02),
                    seed=args.seed + i * 100 + 999,
                    tries=max(3, args.tries),
                    filter_cfg=filter_cfg,
                )

        generated.append(sec_text)

    song = "\n\n".join(generated).strip() + "\n"
    Path(args.out).write_text(song, encoding="utf-8")
    print(song)


if __name__ == "__main__":
    main()