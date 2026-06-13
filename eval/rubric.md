# Judge rubric — Makulatura song quality (v1)

Soft, perceptual metrics. The judge (Claude by default) reads each song in full and
scores **four dimensions on a 1–5 scale**. Per eval-discipline: this is a *soft*
signal — run **N≥3 times per song**, report mean±std, and **read the transcripts**;
never ship/iterate on a single judge run or on the aggregate alone.

Save each run as JSON in `eval/judge_runs/` (see format below) so distributions
are comparable across T02/T04.

## Dimensions

### 1. grammar — грамматическая корректность
- **5** — безупречный русский, нет согласовательных ошибок, нет несуществующих слов.
- **3** — единичные ошибки/корявости, смысл сохранён.
- **1** — мусорные словоформы («лохмоток», «я спешит»), ломаное согласование.

### 2. coherence — связность
- **5** — строки связаны в образ/нарратив, нет логических разрывов и циклов.
- **3** — местами рвётся, есть повторы, но читается.
- **1** — набор несвязанных строк или зацикленные повторы.

### 3. imagery — образность
- **5** — плотные, неожиданные метафоры и образы (уровень оригинала).
- **3** — есть образы, но плоские/клишированные.
- **1** — прозаичные объяснения, нет образов.

### 4. style — похоже на «Макулатуру»
- **5** — интонация, длина строк, лексика, темы узнаваемо в стиле группы.
- **3** — частично попадает в стиль.
- **1** — generic-русский текст, не похоже.

## Анти-плагиат (важно)

`style` оценивает **интонацию и поэтику**, НЕ дословное совпадение с корпусом.
Если песня — это склейка реальных строк Макулатуры, это НЕ высокий `style`, это
плагиат: ставь `style` низко и отметь в `notes`. Дословное копирование ловится
отдельно hard-метрикой `corpus_overlap` в `run_eval.py` — сверяйся с ней.

## Формат прогона (`eval/judge_runs/<song>__run<N>.json`)

```json
{
  "song": "generated_song",
  "run": 1,
  "judge": "claude",
  "scores": {"grammar": 2, "coherence": 1, "imagery": 2, "style": 2},
  "notes": "циклы повторов в OUTRO; 'я спешит' — согласование; <OUTRO> обёрнут вокруг <VERSE>"
}
```
