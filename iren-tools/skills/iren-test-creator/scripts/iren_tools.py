#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iren_tools.py — проверка, сборка, распаковка и сводка тестов «Айрен» (.itx).

Команды:
  build   --source <папка с test.xml и images/> [--output <файл.itx>] [--no-pack]
          [--check-near-dups] [--check-images-blank]
          Валидация test.xml; без --no-pack — упаковка в .itx (ZIP: test.xml, images/...).
          --check-near-dups — доп. предупреждения о «почти-дублях» вариантов (варианты,
          различающиеся 1–2 символами в одном слове — вероятные опечатки). По умолчанию
          выключено: по методике близкие варианты (НЗ/НО и т.п.) — норма.
          --check-images-blank — предупреждать о пустых/однородных PNG.
          Код выхода: 0 — ошибок нет, 1 — есть ошибки (архив при этом всё равно собирается).
  unpack  --source <файл.itx> [--dest <папка>]
          Распаковка .itx в папку (по умолчанию — рядом с архивом, по имени файла).
  info    --source <файл.itx или папка> [--answers]
          JSON-сводка: секции, вопросы по типам, профили (с атрибутами), теги, сценарии,
          формулы, картинки, статистика вариантов. --answers — дополнительно вывести
          для каждого вопроса картинки и правильные ответы (для визуальной сверки).

Зависимости: только стандартная библиотека Python 3.8+.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import zipfile
import zlib
import xml.etree.ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

NO_CORRECT_TEXT = "Среди предложенных вариантов нет верного."

errors = 0
warnings = 0


def warn(msg):
    global warnings
    warnings += 1
    print("ПРЕДУПРЕЖДЕНИЕ:", msg)


def fail(msg):
    global errors
    errors += 1
    print("ОШИБКА:", msg)


def norm_space(s):
    return re.sub(r"\s+", " ", s or "").strip()


def levenshtein(a, b, cap=3):
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ----------------------------------------------------------- PNG: проверка пустых

def png_is_blank(path):
    """True, если PNG однородный (все пиксели одного цвета). None — не удалось проверить."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        pos = 8
        width = height = bit_depth = color_type = interlace = None
        palette = None
        idat = bytearray()
        while pos + 8 <= len(data):
            length = int.from_bytes(data[pos:pos + 4], "big")
            ctype = data[pos + 4:pos + 8]
            body = data[pos + 8:pos + 8 + length]
            pos += 12 + length
            if ctype == b"IHDR":
                width = int.from_bytes(body[0:4], "big")
                height = int.from_bytes(body[4:8], "big")
                bit_depth = body[8]
                color_type = body[9]
                interlace = body[12]
            elif ctype == b"PLTE":
                palette = body
            elif ctype == b"IDAT":
                idat.extend(body)
            elif ctype == b"IEND":
                break
        if None in (width, height, bit_depth, color_type, interlace):
            return None
        if interlace != 0 or bit_depth != 8 or color_type not in (0, 2, 3, 4, 6):
            return None  # не поддерживаем — не проверяем
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        raw = zlib.decompress(bytes(idat))
        stride = width * channels
        if len(raw) < (stride + 1) * height:
            return None
        first_pixel = None
        out_prev = bytearray(stride)
        for y in range(height):
            ft = raw[y * (stride + 1)]
            line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
            if ft == 1:
                for i in range(channels, stride):
                    line[i] = (line[i] + line[i - channels]) & 0xFF
            elif ft == 2:
                for i in range(stride):
                    line[i] = (line[i] + out_prev[i]) & 0xFF
            elif ft == 3:
                for i in range(stride):
                    left = line[i - channels] if i >= channels else 0
                    line[i] = (line[i] + ((left + out_prev[i]) >> 1)) & 0xFF
            elif ft == 4:
                for i in range(stride):
                    a = line[i - channels] if i >= channels else 0
                    b = out_prev[i]
                    c = out_prev[i - channels] if i >= channels else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[i] = (line[i] + pr) & 0xFF
            out_prev = line
            for x in range(width):
                px = line[x * channels:(x + 1) * channels]
                if color_type == 3:
                    i = px[0] * 3
                    px = palette[i:i + 3] if palette and i + 3 <= len(palette) else b"\x00\x00\x00"
                elif color_type == 0:
                    px = bytes([px[0]] * 3)
                elif color_type == 4:
                    px = bytes([px[0]] * 3)
                if first_pixel is None:
                    first_pixel = px
                else:
                    if any(abs(px[k] - first_pixel[k]) > 8 for k in range(3)):
                        return False
        return True
    except Exception:
        return None


# ------------------------------------------------------------------ build

def content_texts(content):
    return " ".join(t.get("value", "") for t in content.iter("text"))


def content_images(content):
    return [i.get("src", "") for i in content.iter("img")]


def validate(root, source_dir, check_near_dups=False, check_blank=False,
             img_min=24, img_max_question=500, img_max_answer=400):
    """Все проверки теста. Возвращает (список вопросов, число картинок-ссылок)."""
    questions = list(root.iter("question"))
    # Номер вопроса в списке программы «Айрен» = порядковый номер в файле
    num_of = {id(q): i for i, q in enumerate(questions, 1)}

    def qname(q):
        return "вопрос №%d (тег %s)" % (num_of[id(q)], q.get("tag"))
    if not questions:
        fail("В тесте нет ни одного вопроса.")

    # 1. Теги
    tags = set()
    max_tag = 0
    for q in questions:
        t = q.get("tag", "")
        if t:
            if t in tags:
                warn("Дубликат тега вопроса: " + t)
            tags.add(t)
            n = int(t) if t.isdigit() else 0
            if n > max_tag:
                max_tag = n
        else:
            fail("Вопрос без тега: " + str(q.get("type")))
    last = root.find("testInfo")
    if last is not None:
        lv = last.get("lastGeneratedTag")
        if lv and lv.isdigit() and int(lv) < max_tag:
            warn("lastGeneratedTag (%s) меньше максимального тега (%d) — обновите его" % (lv, max_tag))

    # 2. Картинки
    img_count = 0
    for img in root.iter("img"):
        img_count += 1
        src = img.get("src", "")
        if src and not os.path.exists(os.path.join(source_dir, src.replace("/", os.sep))):
            fail("Нет файла картинки: " + src)

    # Карта родителей (для проверки модификаторов секций-предков)
    parent = {c: p for p in root.iter() for c in p}

    def sections_of(el):
        p = parent.get(el)
        while p is not None:
            if p.tag == "section":
                yield p
            p = parent.get(p)

    def has_add_negative(q):
        return any(m.get("type") == "addNegativeChoice"
                   for s in sections_of(q) for m in s.findall("modifiers/modifier"))

    # 2б. Размеры изображений (ширина и высота, пиксели; PNG)
    def png_size(path):
        try:
            with open(path, "rb") as f:
                head = f.read(24)
            if head[:8] != bytes([0x89]) + b'PNG' + bytes([0x0D, 0x0A, 0x1A, 0x0A]):
                return None
            return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))
        except Exception:
            return None

    def ancestors_tags(el):
        a = parent.get(el)
        while a is not None:
            yield a.tag
            a = parent.get(a)

    answer_markers = ("choice", "baseItem", "matchingItem", "distractor", "sequenceItem", "categoryItem")
    for img in root.iter("img"):
        src = img.get("src", "")
        if not src or not src.lower().endswith(".png"):
            continue
        fp = os.path.join(source_dir, src.replace("/", os.sep))
        if not os.path.isfile(fp):
            continue
        dims = png_size(fp)
        if not dims:
            continue
        w, h = dims
        chain = list(ancestors_tags(img))
        ctx = "answer" if any(t in chain for t in answer_markers) else "question"
        cap = img_max_answer if ctx == "answer" else img_max_question
        ctx_name = "варианта ответа" if ctx == "answer" else "вопроса"
        if w > cap or h > cap:
            warn("изображение %s (%dx%d) превышает максимум для %s (%dx%d) — уменьшите рисунок; файл собран" % (src, w, h, ctx_name, cap, cap))
        elif w < img_min or h < img_min:
            warn("изображение %s (%dx%d) меньше минимума (%dx%d) — размер шрифта; при необходимости увеличьте" % (src, w, h, img_min, img_min))

    # 3. select-вопросы
    series = {}  # (frozenset вариантов) -> [(tag, correct_set)]
    for q in questions:
        if q.get("type") != "select":
            continue
        tag = q.get("tag")
        choices = q.findall("choices/choice")
        correct = [c for c in choices if c.get("correct") == "true"]
        if not correct:
            neg_choice = any(c.get("negative") == "true" for c in choices)
            if not neg_choice and not has_add_negative(q):
                warn("select %s: нет ни одного correct=true и нет варианта «нет верного»" % qname(q))
        if len(choices) < 2:
            warn("select %s: меньше двух вариантов ответа" % qname(q))

        # Механизмы «нет верного»: явный вариант и addNegativeChoice нельзя совмещать
        neg_texts = 0
        for c in choices:
            content = c.find("content")
            txt = norm_space(content_texts(content)) if content is not None else ""
            if c.get("negative") == "true" or txt == NO_CORRECT_TEXT:
                neg_texts += 1
        if neg_texts >= 2:
            warn("select %s: задвоение варианта «нет верного» (%d шт.)" % (qname(q), neg_texts))
        if neg_texts == 1 and has_add_negative(q):
            warn("select %s: совмещение явного варианта «нет верного» с addNegativeChoice — уберите одно из двух" % qname(q))

        # Тексты и почти-дубли
        variants = []
        for c in choices:
            content = c.find("content")
            texts = content_texts(content) if content is not None else ""
            imgs = " ".join(content_images(content)) if content is not None else ""
            variants.append((norm_space(texts), imgs))
        seen = {}
        for texts, imgs in variants:
            key = norm_space(texts + "|" + imgs).strip()
            if key.strip("|") == "":
                continue
            if key in seen:
                warn("select %s: дубликат варианта «%s»" % (qname(q), seen[key]))
            else:
                seen[key] = texts

        if check_near_dups:
            texts_list = [v[0] for v in variants if v[0]]
            for i in range(len(texts_list)):
                for j in range(i + 1, len(texts_list)):
                    a, b = texts_list[i], texts_list[j]
                    wa, wb = norm_space(a).lower().split(), norm_space(b).lower().split()
                    if len(wa) != len(wb) or wa == wb:
                        continue
                    diff = [(x, y) for x, y in zip(wa, wb) if x != y]
                    if len(diff) <= 2 and all(levenshtein(x, y) <= 2 for x, y in diff):
                        warn("select %s: возможная опечатка — варианты «%s» / «%s» различаются близкими словами: %s"
                             % (qname(q), a[:60], b[:60], ", ".join(x + "/" + y for x, y in diff)))

        # Серии: одинаковые списки вариантов в одной секции
        key = frozenset(v[0] for v in variants if v[0])
        sec = next(iter(sections_of(q)), None)
        sec_title = sec.get("title") if sec is not None else "?"
        correct_set = frozenset(norm_space(content_texts(c.find("content"))) for c in correct if c.find("content") is not None)
        series.setdefault((sec_title, key), []).append((q, correct_set))

    for (sec_title, _key), group in series.items():
        if len(group) >= 2:
            corr_sets = {}
            for q, cs in group:
                corr_sets.setdefault(cs, []).append(q)
            for cs, qs_same in corr_sets.items():
                if len(qs_same) >= 2:
                    warn("в разделе «%s» у вопросов с одинаковым списком вариантов правильный ответ совпадает (вопросы: %s)"
                         % (sec_title, ", ".join(qname(q) for q in qs_same)))

    # 4. input
    for q in questions:
        if q.get("type") != "input":
            continue
        if not q.findall("patterns/pattern"):
            fail("input %s: нет ни одного pattern" % qname(q))

    # 5. order
    for q in questions:
        if q.get("type") != "order":
            continue
        if len(q.findall("sequence/sequenceItem")) < 2:
            warn("order %s: меньше двух элементов последовательности" % qname(q))

    # 6. match
    for q in questions:
        if q.get("type") != "match":
            continue
        if len(q.findall("pairs/pair")) < 2:
            warn("match %s: меньше двух пар" % qname(q))

    # 7. classify
    for q in questions:
        if q.get("type") != "classify":
            continue
        if len(q.findall("categories/category")) < 2:
            warn("classify %s: меньше двух категорий" % qname(q))

    # 8. sectionProfile: ссылки на существующие секции
    section_titles = {s.get("title") for s in root.iter("section")}
    for sp in root.iter("sectionProfile"):
        title = sp.get("title")
        if title and title not in section_titles:
            warn("sectionProfile ссылается на несуществующую секцию: «%s»" % title)
        qq = sp.get("questions")
        if qq and not re.match(r"^\d+(\.\d+)?%$", qq):
            warn("sectionProfile «%s»: неожиданный формат questions=«%s»" % (title, qq))

    # 8а. Дубликаты заголовков секций (Айрен линкует sectionProfile по заголовку)
    seen_titles = set()
    for s_el in root.iter("section"):
        t = s_el.get("title")
        if t:
            if t in seen_titles:
                fail("дубликат заголовка секции: «%s» — заголовки секций должны быть уникальны" % t)
            seen_titles.add(t)

    # 8б. Профили: совместимость с читателем Айрен
    profiles_el = root.find("profiles")
    if profiles_el is not None:
        for prof in profiles_el.findall("profile"):
            ptitle = prof.get("title") or "?"
            has_sp = prof.find("sectionProfile") is not None
            qs_el = prof.find("questionSelection")
            if qs_el is None:
                fail("профиль «%s»: нет questionSelection" % ptitle)
            elif has_sp and qs_el.get("questionsPerSection") is not None:
                fail("профиль «%s»: questionsPerSection совместно с sectionProfile — ридер Айрен падает (строка 286); оставьте что-то одно" % ptitle)
            elif not has_sp and qs_el.get("questionsPerSection") is None:
                fail('профиль «%s»: в questionSelection обязателен questionsPerSection (например "all") — без него Айрен не откроет тест' % ptitle)

    # 9. Сценарии: подстановки $(var) против объявлений var
    re_var_block = re.compile(r"^\s*var\s*$")
    re_var_inline = re.compile(r"^\s*var\s+(.+)$")
    re_block_end = re.compile(r"^\s*(begin|const|type|procedure|function)\b")
    re_decl = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_,\s]*?)\s*:")
    re_usage = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")

    for q in questions:
        script_lines = [s.get("line", "") for s in q.findall("modifiers/modifier[@type='script']/script")]
        if not script_lines:
            continue
        declared = set()
        in_var = False
        for line in script_lines:
            if re_var_block.match(line):
                in_var = True
                continue
            m = re_var_inline.match(line)
            if m:
                dm = re.match(r"^([A-Za-z_][A-Za-z0-9_,\s]*?)\s*:", m.group(1))
                if dm:
                    for name in dm.group(1).split(","):
                        name = name.strip()
                        if name:
                            declared.add(name.lower())
                continue
            if re_block_end.match(line):
                in_var = False
                continue
            if in_var and ":=" not in line:
                dm = re_decl.match(line)
                if dm:
                    for name in dm.group(1).split(","):
                        name = name.strip()
                        if name:
                            declared.add(name.lower())
        usages = set()
        for a in q.iter():
            if a.tag in ("text", "pattern"):
                for m in re_usage.finditer(a.get("value", "")):
                    usages.add(m.group(1))
        for u in usages:
            if u.lower() not in declared:
                warn("%s: подстановка $(%s) не объявлена в var сценария" % (qname(q), u))

    # 10. Пустые картинки
    if check_blank:
        checked = 0
        for img in root.iter("img"):
            src = img.get("src", "")
            if not src:
                continue
            p = os.path.join(source_dir, src.replace("/", os.sep))
            if os.path.isfile(p) and p.lower().endswith(".png"):
                res = png_is_blank(p)
                if res:
                    warn("Картинка пустая/однородная: " + src)
                checked += 1
        if checked:
            print("(проверено PNG на однородность: %d)" % checked)

    return questions, img_count


def cmd_build(args):
    source = os.path.abspath(args.source)
    if not os.path.isdir(source):
        print("ОШИБКА: папка не найдена:", args.source)
        return 1
    xml_path = os.path.join(source, "test.xml")
    if not os.path.isfile(xml_path):
        print("ОШИБКА:", xml_path, "не найден. Укажите папку, содержащую test.xml.")
        return 1
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as e:
        print("ОШИБКА: XML не разбирается:", e)
        return 1

    questions, img_count = validate(root, source,
                                    check_near_dups=args.check_near_dups,
                                    check_blank=args.check_images_blank,
                                    img_min=args.img_min,
                                    img_max_question=args.img_max_question,
                                    img_max_answer=args.img_max_answer)

    out = None
    if not args.no_pack:
        out = args.output or os.path.join(
            os.path.dirname(source), os.path.basename(os.path.normpath(source)) + ".itx")
        for name in os.listdir(source):
            full = os.path.join(source, name)
            if name != "test.xml" and os.path.isfile(full):
                warn("Файл вне test.xml и images\\ не будет включён в архив: " + name)

        if os.path.exists(out):
            os.remove(out)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(xml_path, "test.xml")
            images_dir = os.path.join(source, "images")
            if os.path.isdir(images_dir):
                for root_d, _dirs, files in os.walk(images_dir):
                    for fn in sorted(files):
                        full = os.path.join(root_d, fn)
                        rel = os.path.relpath(full, images_dir).replace(os.sep, "/")
                        z.write(full, "images/" + rel)

    print("Вопросов: %d, картинок: %d" % (len(questions), img_count))
    if out:
        print("Собран:", out)
    print("Итог: ошибок=%d, предупреждений=%d" % (errors, warnings))
    return 1 if errors else 0


# ------------------------------------------------------------------ unpack

def cmd_unpack(args):
    source = os.path.abspath(args.source)
    if not os.path.isfile(source):
        print("ОШИБКА: файл не найден:", args.source)
        return 1
    dest = args.dest or os.path.join(
        os.path.dirname(source), os.path.splitext(os.path.basename(source))[0])
    if os.path.exists(dest):
        if os.listdir(dest):
            print("ОШИБКА: папка назначения существует и не пуста:", dest)
            return 1
    else:
        os.makedirs(dest)
    try:
        with zipfile.ZipFile(source) as z:
            z.extractall(dest)
    except zipfile.BadZipFile as e:
        print("ОШИБКА: не удалось распаковать:", e)
        return 1
    files = []
    for root_d, _dirs, names in os.walk(dest):
        files.extend(os.path.join(root_d, n) for n in names)
    xml_ok = sum(1 for f in files if os.path.basename(f) == "test.xml") == 1
    images = sum(1 for f in files if os.sep + "images" + os.sep in f)
    print("Распаковано:", dest)
    print("test.xml:", "найден" if xml_ok else "НЕ найден")
    print("Файлов всего: %d, картинок: %d" % (len(files), images))
    for f in sorted(files)[:10]:
        print("  " + os.path.relpath(f, dest))
    return 0


# ------------------------------------------------------------------ info

def sec_info(sec):
    qs = sec.findall("questions/question")
    by_type = {}
    for q in qs:
        t = q.get("type")
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "title": sec.get("title"),
        "questions": len(qs),
        "byType": by_type,
        "modifiers": [m.get("type") for m in sec.findall("modifiers/modifier")],
        "sections": [sec_info(s) for s in sec.findall("sections/section")],
    }


def cmd_info(args):
    source = os.path.abspath(args.source)
    is_itx = False
    if os.path.isdir(source) and os.path.isfile(os.path.join(source, "test.xml")):
        work_dir = source
    elif os.path.isfile(source) and source.lower().endswith(".itx"):
        is_itx = True
        work_dir = tempfile.mkdtemp(prefix="iren-info-")
        try:
            with zipfile.ZipFile(source) as z:
                z.extractall(work_dir)
        except zipfile.BadZipFile as e:
            print("ОШИБКА: не удалось распаковать .itx:", e)
            return 1
    else:
        print("ОШИБКА: в папке нет test.xml и расширение не .itx:", source)
        return 1

    try:
        xml_path = os.path.join(work_dir, "test.xml")
        if not os.path.isfile(xml_path):
            print("ОШИБКА: test.xml не найден внутри", ".itx" if is_itx else "папки")
            return 1
        root = ET.parse(xml_path).getroot()

        profiles = []
        profiles_el = root.find("profiles")
        if profiles_el is not None:
            for p in profiles_el.findall("profile"):
                so = p.find("sessionOptions")
                fb = p.find("instantFeedback")
                marks = [
                    {"title": m.get("title"), "lowerBound": m.get("lowerBound")}
                    for m in p.findall("markScale/marks/mark")
                ]
                profiles.append({
                    "title": p.get("title"),
                    "durationMinutes": so.get("durationMinutes") if so is not None else None,
                    "shuffleQuestions": (p.find("questionSelection").get("shuffleQuestions")
                                         if p.find("questionSelection") is not None else None),
                    "sessionOptions": {
                        "editableAnswers": so.get("editableAnswers") if so is not None else None,
                        "browsableQuestions": so.get("browsableQuestions") if so is not None else None,
                        "weightCues": so.get("weightCues") if so is not None else None,
                    },
                    "instantFeedback": (None if fb is None else {
                        "answerCorrectness": fb.get("answerCorrectness"),
                        "totalPercentCorrect": fb.get("totalPercentCorrect"),
                    }),
                    "marks": marks,
                })

        refs = list(dict.fromkeys(
            img.get("src", "") for img in root.iter("img") if img.get("src")))
        missing = [r for r in refs
                   if not os.path.exists(os.path.join(work_dir, r.replace("/", os.sep)))]
        images_dir = os.path.join(work_dir, "images")
        present = sum(len(fn) for _d, _s, fn in os.walk(images_dir)) if os.path.isdir(images_dir) else 0

        tag_nums = [int(q.get("tag")) for q in root.iter("question") if (q.get("tag") or "").isdigit()]
        last = root.find("testInfo")

        # Статистика вариантов по select-вопросам
        sel_counts = []
        multi_correct = 0
        for q in root.iter("question"):
            if q.get("type") != "select":
                continue
            choices = q.findall("choices/choice")
            sel_counts.append(len(choices))
            if sum(1 for c in choices if c.get("correct") == "true") > 1:
                multi_correct += 1
        choices_stats = None
        if sel_counts:
            choices_stats = {
                "selectQuestions": len(sel_counts),
                "min": min(sel_counts),
                "max": max(sel_counts),
                "avg": round(sum(sel_counts) / len(sel_counts), 1),
                "multiCorrectQuestions": multi_correct,
            }

        result = {
            "source": source,
            "isItx": is_itx,
            "version": root.get("version"),
            "questionCount": len(list(root.iter("question"))),
            "enabledQuestions": sum(1 for q in root.iter("question") if q.get("enabled") == "true"),
            "disabledQuestions": sum(1 for q in root.iter("question") if q.get("enabled") == "false"),
            "tags": {
                "count": sum(1 for q in root.iter("question") if q.get("tag")),
                "min": min(tag_nums) if tag_nums else None,
                "max": max(tag_nums) if tag_nums else None,
                "lastGeneratedTag": int(last.get("lastGeneratedTag")) if last is not None and (last.get("lastGeneratedTag") or "").isdigit() else None,
            },
            "sections": [sec_info(s) for s in root.findall("section")],
            "profiles": profiles,
            "choicesStats": choices_stats,
            "scripts": sum(1 for m in root.iter("modifier") if m.get("type") == "script"),
            "formulas": len(list(root.iter("formula"))),
            "images": {"referenced": len(refs), "present": present, "missing": missing},
        }

        if args.answers:
            answers = []
            parent = {c: p for p in root.iter() for c in p}
            for q in root.iter("question"):
                entry = {"tag": q.get("tag"), "type": q.get("type"),
                         "section": (parent.get(q).get("title") if parent.get(q) is not None else None)}
                if q.get("type") == "select":
                    content = q.find("content")
                    entry["images"] = content_images(content) if content is not None else []
                    entry["correct"] = [norm_space(content_texts(c.find("content")))
                                        for c in q.findall("choices/choice") if c.get("correct") == "true"]
                elif q.get("type") == "match":
                    entry["pairs"] = [{"base": norm_space(content_texts(p.find("baseItem/content"))),
                                       "match": norm_space(content_texts(p.find("matchingItem/content")))}
                                      for p in q.findall("pairs/pair")]
                answers.append(entry)
            result["answers"] = answers

        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    finally:
        if is_itx and os.path.isdir(work_dir):
            import shutil
            shutil.rmtree(work_dir, ignore_errors=True)


# ------------------------------------------------------------------ main

def main():
    parser = argparse.ArgumentParser(description="Проверка, сборка, распаковка и сводка тестов «Айрен» (.itx)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="валидация и (опционально) упаковка в .itx")
    p_build.add_argument("--source", required=True, help="папка с test.xml и images/")
    p_build.add_argument("--output", help="путь итогового .itx (по умолчанию рядом с папкой)")
    p_build.add_argument("--no-pack", action="store_true", help="только проверка, без сборки архива")
    p_build.add_argument("--check-near-dups", action="store_true",
                         help="предупреждать о вариантах-«почти-дублях» (возможные опечатки)")
    p_build.add_argument("--check-images-blank", action="store_true",
                         help="предупреждать о пустых/однородных PNG")
    p_build.add_argument("--img-min", type=int, default=24,
                         help="минимальный размер стороны изображения в пикселях (по умолчанию 24 — размер шрифта)")
    p_build.add_argument("--img-max-question", type=int, default=500,
                         help="максимум стороны рисунка в ВОПРОСЕ (по умолчанию 500)")
    p_build.add_argument("--img-max-answer", type=int, default=400,
                         help="максимум стороны рисунка в ВАРИАНТЕ ОТВЕТА (по умолчанию 400)")

    p_unpack = sub.add_parser("unpack", help="распаковка .itx в папку")
    p_unpack.add_argument("--source", required=True, help="файл .itx")
    p_unpack.add_argument("--dest", help="папка назначения (по умолчанию рядом с архивом)")

    p_info = sub.add_parser("info", help="JSON-сводка по тесту")
    p_info.add_argument("--source", required=True, help="файл .itx или папка с test.xml")
    p_info.add_argument("--answers", action="store_true",
                        help="вывести также вопросы с картинками и правильными ответами")

    args = parser.parse_args()
    if args.command == "build":
        sys.exit(cmd_build(args))
    if args.command == "unpack":
        sys.exit(cmd_unpack(args))
    if args.command == "info":
        sys.exit(cmd_info(args))


if __name__ == "__main__":
    main()
