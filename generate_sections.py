import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Tuple

from post_filter import clean_section_text, score_section, score_section_in_context, FilterConfig, near_repetition

# repo root on path so eval.* is importable (reuse T01 metrics, no duplication)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval.metrics import tag_health, line_repetition_rate, gram_repetition_rate

from prompts import SYSTEM  # canonical prompt shared with make_instructions (train==inference)


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
    chat_template_config: str = "",
) -> str:
    cmd = [
        sys.executable, "-m", "mlx_lm.generate",
        "--model", model,
    ]
    if adapter_dir:  # optional: empty = run base model with no LoRA adapter
        cmd += ["--adapter-path", adapter_dir]
    if chat_template_config:  # e.g. '{"enable_thinking": false}' for Qwen3/QVikhr-3
        cmd += ["--chat-template-config", chat_template_config]
    cmd += [
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


def section_ok(text: str) -> bool:
    """Post-hoc acceptance gate. mlx_lm 0.31.3 has no repetition_penalty, so we
    reject loop-y / structurally broken sections after generation instead.
    Thresholds sit well above real corpus (line_rep ~0.01) and below the known
    degenerate output (line_rep ~0.27)."""
    if tag_health(text)["broken_total"] > 0:
        return False
    if line_repetition_rate(text) > 0.15:
        return False
    if gram_repetition_rate(text) > 0.20:
        return False
    # near-rep (near-dup / анафора / intra-loop) — класс, который line_rep пропускает.
    # Порог 0.30: reference-хвост ~0.1, филлер-секции 0.3-0.6 (калибровка T05).
    if near_repetition(text)["near_rep"] > 0.30:
        return False
    return True


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
    chat_template_config: str = "",
    max_rounds: int = 3,
) -> str:
    prompt = build_section_prompt(theme, sec_type, speaker, index, context)

    best_overall = ""
    best_overall_score = -1e18
    for r in range(max_rounds):
        # diversify each round to escape repetition loops (bump temp / min_p)
        r_temp = min(0.95, temp + 0.05 * r)
        r_min_p = min(0.15, min_p + 0.02 * r)

        candidates: List[str] = []
        for t in range(tries):
            out = run_mlx_generate(
                model=model,
                adapter_dir=adapter_dir,
                system_prompt=SYSTEM,
                prompt=prompt,
                max_tokens=max_tokens,
                temp=r_temp,
                top_p=top_p,
                top_k=top_k,
                min_p=r_min_p,
                seed=seed + r * 1000 + t,
                chat_template_config=chat_template_config,
            )
            candidates.append(clean_section_text(out, cfg=filter_cfg))

        best, score = choose_best_candidate(candidates, context=context)
        if score > best_overall_score:
            best_overall, best_overall_score = best, score
        if section_ok(best):
            return best.strip()

    # no round produced a clean section — return least-bad (caller measures it)
    return best_overall.strip()


def parse_structure(structure: str) -> List[Dict]:
    """'VERSE(speransky) > CHORUS(alekhin)' -> [{type, speaker, index}, ...]."""
    plan: List[Dict] = []
    verse_idx = 0
    for p in (x.strip() for x in structure.split(">")):
        if not p:
            continue
        if "(" not in p or ")" not in p:
            raise SystemExit(f"Не понял элемент структуры: {p}")
        sec_type = p.split("(")[0].strip().upper()
        speaker = p.split("(", 1)[1].split(")", 1)[0].strip().lower()
        index = None
        if sec_type == "VERSE":
            verse_idx += 1
            index = verse_idx
        plan.append({"type": sec_type, "speaker": speaker, "index": index})
    return plan


def generate_song(
    theme: str,
    structure: str,
    model: str,
    adapter_dir: str,
    max_tokens: int,
    temp: float,
    top_p: float,
    top_k: int,
    min_p: float,
    seed: int,
    tries: int,
    filter_cfg: FilterConfig,
    chat_template_config: str = "",
) -> str:
    """Generate a full song section-by-section. Reusable by main() and the
    baseline driver (eval/generate_set.py)."""
    plan = parse_structure(structure)
    generated: List[str] = []
    context_window_sections = 2  # сколько последних секций давать в контекст

    for i, step in enumerate(plan):
        context = "\n\n".join(generated[-context_window_sections:])

        sec_text = generate_section_with_retries(
            model=model,
            adapter_dir=adapter_dir,
            theme=theme,
            sec_type=step["type"],
            speaker=step["speaker"],
            index=step["index"],
            context=context,
            max_tokens=max_tokens,
            temp=temp,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            seed=seed + i * 100,
            tries=tries,
            filter_cfg=filter_cfg,
            chat_template_config=chat_template_config,
        )

        if step["type"] == "OUTRO":
            inner = [ln for ln in sec_text.splitlines() if ln.strip() and not ln.strip().startswith("<")]
            if len(inner) < 4:
                sec_text = generate_section_with_retries(
                    model=model,
                    adapter_dir=adapter_dir,
                    theme=theme,
                    sec_type=step["type"],
                    speaker=step["speaker"],
                    index=step["index"],
                    context=context,
                    max_tokens=max(300, max_tokens),
                    temp=min(0.85, temp + 0.1),
                    top_p=min(0.92, top_p + 0.04),
                    top_k=max(60, top_k),
                    min_p=max(0.05, min_p - 0.02),
                    seed=seed + i * 100 + 999,
                    tries=max(3, tries),
                    filter_cfg=filter_cfg,
                    chat_template_config=chat_template_config,
                )

        generated.append(sec_text)

    return "\n\n".join(generated).strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", required=True)
    ap.add_argument("--structure", required=True, help='Напр: "VERSE(speransky) > CHORUS(alekhin) > VERSE(speransky) > CHORUS(alekhin) > OUTRO(alekhin)"')
    ap.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--adapter_dir", default="", help="LoRA adapter dir; empty = base model")
    ap.add_argument("--chat_template_config", default="", help='e.g. \'{"enable_thinking": false}\' to disable Qwen3/QVikhr-3 reasoning')

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

    filter_cfg = FilterConfig(
        min_words_per_line=args.min_words_per_line,
        max_same_line_repeats=2,
        drop_latin_lines=True,
        drop_mixed_cyr_lat_words=True,
        keep_tag_lines=True,
        collapse_whitespace=True,
    )

    song = generate_song(
        theme=args.theme,
        structure=args.structure,
        model=args.model,
        adapter_dir=args.adapter_dir,
        max_tokens=args.max_tokens_section,
        temp=args.temp,
        top_p=args.top_p,
        top_k=args.top_k,
        min_p=args.min_p,
        seed=args.seed,
        tries=args.tries,
        filter_cfg=filter_cfg,
        chat_template_config=args.chat_template_config,
    )
    Path(args.out).write_text(song, encoding="utf-8")
    print(song)


if __name__ == "__main__":
    main()