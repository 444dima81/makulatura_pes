# Makulatura LM

Генератор песенных текстов в стиле группы **«Макулатура»** — воспроизводит язык, интонацию и поэтику (не копирует тексты), сохраняя структуру секций по авторам (Алёхин / Сперанский).

**Статус:** экспериментальный, завершён. Рабочий генератор; упёрся в технологический потолок локальных открытых русских LLM (см. честные результаты ниже).

---

## Подход

- **База:** `Vikhrmodels/QVikhr-3-8B-Instruction-MLX_4bit` (русская, на Qwen3), 4-bit MLX.
- **Дообучение:** LoRA локально на Apple Silicon через `mlx_lm lora` → MLX-нативный адаптер, запуск без конвертаций.
- **Eval-first:** мерило качества (`eval/`) гейтит любой claim «стало лучше» — измерение прежде утверждений.
- **Deprecated:** ранний путь Qwen2.5-7B на Colab (`trl`/`peft`) — формат PEFT несовместим с локальным MLX, **списан**. Ещё раньше — v1 на Llama-3.2-3B (`adapters_v1_random/`, только конфиги).

---

## Пайплайн

```
parser/ (Genius)         → data/songs.jsonl              (скрейп)
preprocessed/            → data/canonical_corpus.jsonl   (нормализация, секции, спикеры)
make_instructions.py     → data/mlx_dataset/{train,valid}.jsonl  (chat-формат, holdout исключён)
mlx_lm lora              → adapters/qvikhr3_makulatura_lora       (LoRA-адаптер)
generate_sections.py     → песня                          (+ post-filter + acceptance gate)
```
Данные/адаптеры **gitignored** (копирайт + размер), но детерминированно регенерируются. Подробности и точные команды — в `CLAUDE.md` и `docs/HANDOFF.md`.

---

## Генерация

```bash
.venv/bin/python generate_sections.py \
  --model Vikhrmodels/QVikhr-3-8B-Instruction-MLX_4bit \
  --adapter_dir adapters/qvikhr3_makulatura_lora \
  --chat_template_config '{"enable_thinking": false}' \
  --theme "зима и пустые улицы" \
  --structure "VERSE(speransky) > CHORUS(alekhin) > VERSE(speransky) > CHORUS(alekhin) > OUTRO(alekhin)" \
  --out generated_song.txt
```

## Оценка

```bash
.venv/bin/python eval/run_eval.py --input <file|dir>     # hard-метрики (вкл. near_rep) + дрилдаун + reference-band
.venv/bin/python eval/generate_set.py --model <m> --out eval/out/<name> --n 3   # сгенерить набор
# рифма (внешний инструмент RPST, изолированный venv):
.venv-rpst/bin/python eval/rhyme_eval.py --input <dir> --models vendor/rpst-models/models
```
Hard-метрики детерминированы (рециклинг строк/4-грамм, **near-repetition/анафора**, теги, кириллица, длина строк, плагиат). Рифма — через RPST (стресс + slant). Soft (стиль) — judge + N≥3 + чтение транскриптов. См. `eval/README.md`, `eval/rubric.md`.

---

## Результаты (честно)

**Выигрыши (измерено):**
- Связный русский в стиле группы; конкретная образность, голос, бытовой сюр.
- Межсекционный рециклинг **−80%**; near-repetition филлер **−50%**; структура чистая (0 битых тегов); без зазубривания корпуса.
- Плотность рифмы **+86%** от дообучения (база → адаптер), измерено внешним инструментом (RPST).

**Потолок:**
- Обучение на **189 песнях** (весь каталог Genius — больше негде взять). Модель схватила **поверхность** стиля, не глубину.
- **Рифма — частично закрываемый разрыв, не стена.** Корпус плотно (часто неточно) рифмован. Готовые instruct-модели не рифмуют из-за **барьера токенизации** (subword рвёт фонологию, нужную для рифмы) — НО дообучение это двигает: адаптер дошёл до **≈54% корпусной плотности** рифмы (с 29% у базы). Дожать выше упирается в тяжёлые рычаги (рифмо-взвешенный fine-tune / большой стресс-словарь / constrained decoding); лёгкий отбор на генерации не сработал — нет torch-free источника ударения (T07). Сквозной сюжет ограничен размером корпуса.

**Лучшие примеры:** `SHOWCASE.md`.

---

## Структура

```
generate_sections.py    # генерация секций (adapter опционален, anti-rep gate, tag-валидатор)
prompts.py              # канонический SYSTEM (общий train+inference)
post_filter.py          # чистка + скоринг кандидатов
make_instructions.py    # сборка датасета (holdout исключён)
parser/                 # скрейп Genius
preprocessed/           # нормализация → канонический корпус
eval/                   # мерило: метрики (вкл. near_rep), run_eval, reference, rubric, generate_set, rhyme_eval (RPST)
lora_config.yaml        # гиперы LoRA (rank/scale/dropout)
requirements.txt        # MLX-стек (mlx, mlx_lm)
docs/                   # HANDOFF.md (состояние), roadmap
SHOWCASE.md             # лучшие сгенерённые песни
CLAUDE.md               # архитектурный референс
```

## Окружение

Apple Silicon (разрабатывалось на M5 24 GB). `.venv` (python3.12) с `mlx`/`mlx_lm` из `requirements.txt`. Запуск через `.venv/bin/python` (системный `python` не используется).
