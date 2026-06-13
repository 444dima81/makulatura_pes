# Makulatura — Quality Uplift Roadmap

**Date:** 2026-06-13
**Goal:** освоить fine-tuning pipeline и поднять измеримое качество генерации текстов в стиле «Макулатура». Важен и процесс, и результат.

## Принцип (eval-discipline)

Мерило → baseline → изменение → замер. Никаких claim'ов «стало лучше» без preceding measurement (rule 16). Soft-сигналы (LLM-judge) → N≥3 + читать транскрипты, не только aggregate (rules 5, 29). Hard-сигналы детерминированы → single-run OK (rule 7).

## Известные дефекты (по `generated_song.txt` + код, не гипотезы)

1. **Грамматический мусор** («лохмоток», «я спешит», «застрялось») — слабый русский базы Qwen2.5 + агрессивный сэмплинг.
2. **Циклы повторов** строк и 4-грамм.
3. **Битые/вложенные теги** (`<OUTRO>` внутри `<VERSE>`).
4. **Рассинхрон system prompt** train (`make_instructions.py`) ↔ inference (`generate_sections.py`). Модель кондиционирована не на тот промпт.
5. ~~Промпт+скоринг душат стиль длинных строк~~ **ОПРОВЕРГНУТО в T01.** Измерение корпуса: реальные строки короткие — mean **6.82** слова/строку, median 7, IQR [5,8] (171 песня, 10.5k строк). Орфанные/фрагментированные строки редки (~0.5%), длину не искажают. Инструкция «короткие строки» и штраф `avg_len>20` стилю НЕ противоречат. Это не дефект — claim был сделан с одной песни на глаз, без измерения (anti-pattern eval-discipline rule 17).
6. **Корпус 189 песен** (~86k слов, 442 train-примера) — потолок качества финтюна. Не дефект процесса, но жёсткое ограничение ceiling.
7. **Качество парсинга под вопросом** (флаг пользователя): в реальном корпусе есть осиротевшие строки (одинокая запятая после «подавлял крик счастья»). Кривой парсинг/нормализация портит и train-данные, и эталонный сет. Аудит — в T03; эталон T01 — ручная верификация.

## Задачи

Каждая: spec в `tasks/<NNN-slug>/<NNN>.md` ПЕРЕД кодом · sequence Research→Plan→**[STOP approval]**→Impl→Verify→Review · `commit+push` между тасками · T03+ в git worktree (rule 8).

| ID | Задача | Tier | Зависит от |
|----|--------|------|-----------|
| **T01** | Eval harness + reference set | Medium | — |
| **T02** | Fixed-inference baseline (без переобучения) | Small | T01 |
| **T03** | Data clean + fix | Small/Medium | T01 |
| **T04** | Retrain LoRA на Vikhr-7B (MLX, локально) | Medium | T01, T03 |
| **T05** | Serve в Ollama (GGUF + Modelfile) | Small/Medium | T04 |

### T01 — Eval harness + reference set
Без него всё остальное — гадание. Выход — `eval/`, который берёт N сгенерённых песен и отдаёт distribution (mean±std) + per-song таблицу для drilldown.
- Hold-out ~15-20 реальных куплетов как эталон стиля (исключить из обучения); **вручную проверить** — без артефактов парсинга (битые строки, осиротевшая пунктуация), иначе мерило кривое.
- **Hard-метрики** (детерминированные): repetition rate (строки + 4-граммы), Cyrillic ratio, доля битых/вложенных тегов, распределение длины строк vs реальный корпус.
- **Soft-метрики** (judge, N≥3, читаем транскрипты): грамматичность / связность / образность / «похоже на Макулатуру», рубрика 1–5.
- Judge по умолчанию: Claude по рубрике с чтением транскриптов (без API-ключа).

### T02 — Fixed-inference baseline
Чинит self-inflicted wounds на ТЕКУЩЕМ адаптере, без переобучения. Это честная точка отсчёта и тест «нужно ли вообще переобучать».
- Синхронизировать system prompt train↔inference.
- ~~Убрать «короткие строки»~~ — отменено (T01 показал: короткие строки = реальный стиль). Вместо этого главные рычаги ниже.
- Sampling против циклов (дефект №1/2): `repetition_penalty`, тюнинг temp/min_p.
- Фикс битых/вложенных тегов (дефект №3): валидатор структуры на выходе.
- Замер по T01.

### T03 — Data clean + fix
- **Аудит парсинга** (`normalize_songs.py`, `make_canonical_text.py`): на выборке песен сверить с оригиналом на Genius — корректность разбивки на секции, атрибуцию спикеров, line-stitching.
- Dedup повторяющихся куплетов/хоров, фикс битого line-stitching (осиротевшие запятые), привести system prompt датасета к финальному, augmentation ради сигнала на 189 песнях.

### T04 — Retrain LoRA на Vikhr-7B (MLX)
- База: Vikhr-7B (русскоязычная, есть в mlx-community) — бьёт в дефект №1.
- Гиперпараметры под крошечный корпус: следить за valid loss, не пережечь эпохами (overfit), подобрать rank.
- Замер по T01 vs T02, N≥3, distribution + per-query drilldown (eval-discipline rule 9).

### T05 — Serve в Ollama
- Экспорт fused → GGUF + Modelfile (sampling из T02). Сравнить локальный inference с MLX-путём.

## Sequencing & decision gates

- Строгий порядок T01 → T02 → T03 → T04 → T05.
- **После T02 — decision point:** если baseline уже «достаточно хорош» по T01, T03/T04 могут быть не нужны (но цель «освоить дообучение» → T04 делаем в любом случае).
- T04 deps: загрузка Vikhr-7B в MLX-формате, обучение в `.venv`.

## Standards applied

- `1. dev/standards/task-discipline.md` — spec per task, Research→Plan→STOP→Impl→Verify→Review, worktree, numbered acceptance.
- `1. dev/standards/eval-discipline.md` — measure-first, N≥3, hard vs soft, per-query drilldown, читать транскрипты.
