# iren-mcp

MCP-сервер (неофициальный) для работы с тестами программы **«Айрен»** (irenproject.ru) в формате `.itx`.

Пять инструментов для LLM-ассистентов (ZCode, Claude Desktop и любой другой MCP-клиент):

| Инструмент | Что делает |
|---|---|
| `iren_test_info` | JSON-сводка по тесту: дерево секций, вопросы по типам, профили (время, шкала оценок), теги, сценарии, формулы, картинки |
| `iren_validate_itx` | Проверка теста: XML, дубликаты тегов, `lastGeneratedTag`, битые ссылки на картинки, select-вопросы без верного ответа, дубликаты вариантов, необъявленные `$(var)` в сценариях |
| `iren_pack_itx` | Сборка `.itx` из папки (`test.xml` + `images/`) с предварительной проверкой; ZIP с корректными путями |
| `iren_unpack_itx` | Распаковка `.itx` в папку для правки |
| `iren_check_formula` | Проверка TeX-формул **тем же движком, что внутри Айрен** (MathJax 2.7.3, SVG). Сообщает, отрисуется ли формула, и ловит неизвестные макросы/символы («Undefined control sequence», «Unknown character») |

## Установка

Требования: Node.js ≥ 18 и Python 3.8+ (только стандартная библиотека, ничего доустанавливать не нужно). Скрипт ищет интерпретатор сам: `py` → `python` → типовые пути установки.

```bash
cd iren-mcp
npm install
node test.mjs   # самопроверка движка формул
```

Подключение в ZCode (`~/.zcode/cli/config.json` или `<проект>/.zcode/config.json`):

```json
{
  "mcp": {
    "servers": {
      "iren": {
        "command": "C:/Program Files/nodejs/node.exe",
        "args": ["C:/путь/к/iren-mcp/server.mjs"]
      }
    }
  }
}
```

Путь к node.exe и server.mjs указывайте абсолютный. Для других MCP-клиентов — стандартное подключение stdio-сервера.

Утилиту можно использовать и без MCP, напрямую:

```bash
py scripts/iren_tools.py build --source <папка теста> [--output <файл.itx>] [--no-pack]
py scripts/iren_tools.py unpack --source <файл.itx> [--dest <папка>]
py scripts/iren_tools.py info --source <файл.itx или папка>
```

## Как это работает

- Формат `.itx` — ZIP-архив: `test.xml` (UTF-8) + `images/`. Валидация, сборка, распаковка и сводка реализованы в `scripts/iren_tools.py` (Python, стандартная библиотека: `zipfile` + `xml.etree`).
- Проверка формул: `assets/formulaRenderer.js` — штатный headless-рендерер Айрен (внутри зашит MathJax 2.7.3 + пакеты AMSmath/AMSsymbols), запускается через jsdom. Формула считается годной, только если она реально отрисовывается в этом движке — ровно как в программе.

## Лицензии

- Код сервера и скриптов: Apache 2.0 (см. `LICENSE`).
- `assets/formulaRenderer.js` — компонент программы «Айрен» (© 2012–2020 Sergey Ostanin), распространяемой по Apache 2.0 (см. `NOTICE`).
- MathJax — Apache 2.0.

Проект не связан с автором «Айрен». Проверено на версии Айрен 0.2020.08.1.
