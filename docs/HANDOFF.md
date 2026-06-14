# Makulatura — Handoff (state + how to continue)

Continuity doc for the next stages. Read this first after a fresh start.
Goal of the project: поднять качество генерации песен в стиле «Макулатуры»;
параллельная цель пользователя — **освоить дообучение** (важен и процесс).

## TL;DR — где мы

- **T01 (eval harness) — DONE.** Мерило качества в `eval/`.
- **T02 (base baseline) — DONE.** Сравнили 2 русские базы → **выбран QVikhr-3-8B**.
- **T03 (data clean) — DONE.** Починен парсинг, holdout исключён, train==inference.
- **СЛЕДУЮЩЕЕ: T04** — LoRA-дообучение QVikhr-3 на чистых данных через `mlx_lm lora`.
- Потом **T05** — отдать в Ollama (GGUF) для удобного инференса (опционально).

Дисциплина: specs+reports в `1. dev/tasks/makulatura/00{1,2,3}/`; стандарты в
`1. dev/standards/{task,eval}-discipline.md`. **commit+push между тасками.**
Код — в репо; лирики/данные/адаптеры — gitignored.

## Окружение

- Apple **M5, 24 GB**. `.venv` (python3.12), `mlx` 0.31.2 / `mlx_lm` 0.31.3 (`requirements.txt` запинен).
- **База: `Vikhrmodels/QVikhr-3-8B-Instruction-MLX_4bit`** (в HF-кэше, ~4.3GB). Это **reasoning-модель Qwen3** → глушить thinking флагом `--chat-template-config '{"enable_thinking": false}'`.
- **Legacy `adapters/qwen_makulatura_lora/` — PEFT-формат, mlx_lm его НЕ грузит. СПИСАН.** Не пытаться запускать.
- Всё запускать через `.venv/bin/python` (системный `python` отсутствует/битый).

## Как оцениваем (мерило `eval/`)

Принцип (eval-discipline): **мерило → baseline → изменение → замер.** Никаких «лучше» без замера. Soft-сигналы N≥3 + **читать транскрипты**, не верить агрегату.

**Hard-метрики** (детерминированные, single-run OK):
| метрика | что значит | куда хотим |
|---|---|---|
| `line_repetition` / `gram_repetition` | повтор строк / 4-грамм | →0 (НО повтор припева легитимен — читать дрилдаун) |
| `broken_tags` | битые/вложенные/незакрытые теги | =0 |
| `cyrillic_ratio` | доля кириллицы | →1.0 |
| `line_mean` | слов/строку | ≈ корпус **6.8** (IQR 5–8) |
| `corpus_overlap` | дословное совпадение с корпусом | низко (высоко = плагиат/ememorization) |

**Soft-метрики** (judge=Claude, рубрика `eval/rubric.md`, шкала 1–5, **N≥3**): grammar / coherence / imagery / style. Сохранять прогоны в `eval/judge_runs/*.json`, агрегировать `eval/judge_aggregate.py`.

**Калибровка (gate):** мерило обязано разделять известно-плохое (`generated_song.txt`: line_rep 0.27, 7 broken) и реальные куплеты (`eval/reference/`: line_rep 0.01, 0 broken).

Команды (из корня репо):
```bash
.venv/bin/python eval/run_eval.py --input <file|dir>          # hard-метрики + дрилдаун + reference-band
.venv/bin/python eval/generate_set.py --model <m> --out eval/out/<name> --n 3 \
    --chat_template_config '{"enable_thinking": false}'        # сгенерить N песен на eval/prompts.jsonl
.venv/bin/python eval/judge_aggregate.py                       # агрегат soft-прогонов
```

## На что смотрим (рычаги и известные проблемы)

1. **#1 рычаг — межсекционный рециклинг.** Секции копируют друг друга / припев (base-модели обе грешат). Лечится: дообучение на различных секциях + усиление штрафа `score_section_in_context` (post_filter.py) + tries↑.
2. **Структура.** QVikhr-3 base = 0 битых тегов. Следить, чтобы оставалось 0.
3. **Повторы шумят** (high variance) — опираться на hard + дрилдаун + чтение транскриптов, judge вторичен.
4. **Потолок: 189 песен.** Дообучение учит ПОВЕРХНОСТЬ стиля, не глубину. Честное ожидание: уберёт явные дефекты, но «неотличимо от оригинала» — нет. Следующий рычаг за пределами T04 — **расширять корпус**, не крутить модель.

## Baseline (T02, QVikhr-3 base, N=15) — точка отсчёта для A/B в T04

`line_rep 0.174±0.178 · gram_rep 0.181±0.158 · broken_tags 0 · line_mean 6.78 · overlap ~0 · cyr 1.0`

T04 сравнивается с этим **на тех же** `eval/prompts.jsonl`, N≥3. Для чистого A/B
перегенерить и base-QVikhr на финальном промпте (он не менялся в T03).

## Данные (gitignored, локально; регенерируются детерминированно)

```bash
cd preprocessed && ../.venv/bin/python normalize_songs.py && ../.venv/bin/python make_canonical_text.py && cd ..
.venv/bin/python eval/build_reference.py    # эталон + eval/holdout_ids.txt (18 песен)
.venv/bin/python make_instructions.py        # data/mlx_dataset/{train,valid}.jsonl (holdout исключён)
```
- Датасет: **418 примеров** (train 398 / valid 20), chat-формат `{"messages":[system,user,assistant]}`.
- **Holdout (`eval/holdout_ids.txt`, 18 песен) ИСКЛЮЧЁН из обучения — так и держать** (иначе leakage → кривой eval).
- System prompt — единый источник `prompts.py` (train==inference). **Не рассинхронить.**

## T04 — план (LoRA-дообучение QVikhr-3)

Инструмент: `mlx_lm lora` → MLX-нативный адаптер → запуск через
`generate_sections.py --adapter_dir <path>` (без конвертаций — урок legacy-PEFT).

Стартовая команда (гиперпараметры подобрать на plan-review):
```bash
.venv/bin/python -m mlx_lm lora \
  --model Vikhrmodels/QVikhr-3-8B-Instruction-MLX_4bit \
  --train --data data/mlx_dataset \
  --fine-tune-type lora --num-layers 16 --mask-prompt \
  --batch-size 2 --iters <N> --learning-rate 1e-4 --max-seq-length 1200 \
  --adapter-path adapters/qvikhr3_makulatura_lora --save-every 50 --steps-per-eval 50 --seed 42 \
  -c lora_config.yaml   # для rank/alpha/dropout: lora_parameters{rank:16,scale:2.0,dropout:0.05}
```
Замечания:
- **Маленький корпус (398 примеров)** → главный риск **overfit**. Следить за `valid loss`, мало итераций, ранний стоп. Начать консервативно (напр. 1–3 «эпохи»; iters ≈ examples/batch × epochs).
- `--mask-prompt` — считать loss только по ассистенту (тексту песни).
- rank/alpha/dropout задаются через `-c config.yaml` (CLI не экспонирует `--rank`).
- Thinking у QVikhr-3 при инференсе адаптера — глушить тем же `--chat_template_config`.
- После обучения: `generate_set` с `--adapter_dir adapters/qvikhr3_makulatura_lora` → `run_eval` vs base baseline, N≥3, **читать транскрипты**.

Открытые вопросы на plan-review T04: число iters/epochs, rank, нужен ли config.yaml, как считать «эпоху» от iters, перегенерить ли base-baseline на финальном промпте.

## Гочи / уроки

- Дообучать и запускать — **только MLX-нативно** (Colab/PEFT дал несовместимый формат → боль).
- `generate_sections` = subprocess на генерацию → модель грузится каждый раз (**перф-долг**; load-once через Python API ускорит ×5-10, кандидат на отдельную таску перед длинными прогонами).
- Не коммитить лирику: `data/`, `eval/reference/`, `eval/holdout_ids.txt`, `eval/out/`, `eval/judge_runs/*.json`, адаптеры — все gitignored.

## Карта файлов

- `eval/` — мерило (metrics/run_eval/build_reference/rubric/judge_aggregate/generate_set/prompts.jsonl).
- `generate_sections.py` — генерация (adapter опционален, anti-rep gate, tag-валидатор, chat_template_config).
- `prompts.py` — канонический SYSTEM (общий train+inference).
- `preprocessed/` — пайплайн данных. `make_instructions.py` — сборка датасета. `post_filter.py` — скоринг/чистка.
- `docs/` — `2026-06-13-quality-uplift-roadmap.md`, этот `HANDOFF.md`.
- `1. dev/tasks/makulatura/` — specs + reports по T01–T03.
