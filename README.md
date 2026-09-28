# IREN Tools — скилл и MCP-сервер для тестов «Айрен» (.itx)

Неофициальный набор инструментов для [программы «Айрен»](https://irenproject.ru) (тесты в формате `.itx`): методика-скилл для LLM-ассистентов + MCP-сервер с пятью инструментами. Работает в ZCode и в любом другом MCP-клиенте.

> Не связан с автором «Айрен». Проверено на версии Айрен 0.2020.08.1 (Apache 2.0).

## Инструменты MCP

| Инструмент | Что делает |
|---|---|
| `iren_test_info` | JSON-сводка по тесту: дерево секций, вопросы по типам, профили, картинки, теги, сценарии, формулы |
| `iren_validate_itx` | Проверка: XML, теги, картинки, select без верного ответа, дубликаты вариантов, «нет верного» ×2, серии с одинаковым ответом, дубликаты заголовков секций, ссылки sectionProfile, `$(var)` в сценариях, **questionsPerSection в профилях** (без него Айрен не открывает тест) |
| `iren_pack_itx` | Сборка .itx из папки с предварительной проверкой |
| `iren_unpack_itx` | Распаковка .itx в папку |
| `iren_check_formula` | Проверка TeX-формул **тем же движком, что внутри Айрен** (MathJax 2.7.3) — ловит «Undefined control sequence» и неизвестные символы |

Скилл `iren-test-creator` добавляет LLM знания формата .itx и методику составления сложных тестов (по материалам, с картинками, вариантами-«близнецами», профилями обучения/контроля).

## Установка (ZCode)

1. **Settings → Plugin Marketplace → Add → Add Plugin Marketplace** — добавить этот репозиторий.
2. **Personal → IREN Tools (Айрен) → Install**.
3. Требования на машине: Node.js ≥ 18 (MCP) и Python 3.8+ (утилита `iren_tools.py`); npm-зависимости уже в комплекте (`mcp/node_modules`).

## Установка в другие MCP-клиенты

Добавить stdio-сервер:

```json
{ "command": "node", "args": ["<путь>/mcp/server.mjs"] }
```

Скилл — скопировать папку `skills/iren-test-creator` в каталог скиллов своего ассистента.

## Прямое использование утилиты (без MCP)

```bash
py iren-tools/mcp/scripts/iren_tools.py build  --source <папка теста> [--output <файл.itx>] [--no-pack]
py iren-tools/mcp/scripts/iren_tools.py unpack --source <файл.itx> [--dest <папка>]
py iren-tools/mcp/scripts/iren_tools.py info   --source <файл.itx или папка> [--answers]
```

## Лицензии

- Код — Apache 2.0 (`LICENSE`).
- `iren-tools/mcp/assets/formulaRenderer.js` — компонент «Айрен» (© 2012–2020 Sergey Ostanin), Apache 2.0 (`NOTICE`); MathJax 2.7.3 — Apache 2.0.
