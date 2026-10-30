"""题库加载与答案匹配。

支持 .xlsx / .csv / .tsv / .txt / .json / .docx。
自动识别「题目/题干」与「答案」列。匹配时做归一化 + 精确匹配 + 保守的模糊匹配。
"""
import csv
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher

QUESTION_KEYS = ("题目", "题干", "问题", "试题", "question", "content", "title")
ANSWER_KEYS = ("答案", "正确答案", "标准答案", "answer", "key", "correct")
TYPE_KEYS = ("题型", "类型", "type")

_PUNCT = set("，。、；：？！“”‘’（）()【】[]《》<>·—…,.;:?!\"'`~-_=+*/\\|@#$%^&{}[]")


def normalize(s):
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.strip().lower()
    s = re.sub(r"\s+", "", s)
    s = "".join(ch for ch in s if ch not in _PUNCT)
    return s


def strip_question_number(s):
    """只去掉题干开头的题号，如 '1.' '2、' '第3题'；不会误伤 '20%' 这类内容。"""
    return re.sub(r"^(第)?\d+(题|[.、)．])\s*", "", s)


def _pick(header, keys):
    for h in header:
        hn = normalize(h)
        for k in keys:
            if normalize(k) == hn or normalize(k) in hn:
                return h
    return None


def _rows_from_csv(path):
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, newline="", encoding=enc) as f:
                sample = f.read(4096)
                f.seek(0)
                delim = "\t" if sample.count("\t") > sample.count(",") else ","
                return list(csv.reader(f, delimiter=delim))
        except UnicodeDecodeError:
            continue
    raise RuntimeError("无法识别文件编码: %s" % path)


def _rows_from_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            rows.append(["" if c is None else str(c) for c in row])
    return rows


def _rows_from_docx(path):
    from docx import Document
    doc = Document(path)
    return [[p.text] for p in doc.paragraphs if p.text.strip()]


def _rows_from_json(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("items") or data.get("questions") or list(data.values())
    rows = []
    for it in data:
        if isinstance(it, dict):
            q = it.get("question") or it.get("content") or it.get("题目") or it.get("题干")
            a = it.get("answer") or it.get("答案") or it.get("correct")
            t = it.get("type") or it.get("题型")
            rows.append([q, a, t])
        elif isinstance(it, (list, tuple)):
            rows.append([str(x) for x in it])
    return rows


def load_rows(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return _rows_from_xlsx(path)
    if ext == ".docx":
        return _rows_from_docx(path)
    if ext == ".json":
        return _rows_from_json(path)
    if ext in (".csv", ".tsv", ".txt"):
        return _rows_from_csv(path)
    raise RuntimeError("不支持的题库格式: %s" % ext)


def load_bank(path):
    if os.path.splitext(path)[1].lower() == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("items") or data.get("questions") or []
        items = []
        for it in data:
            if not isinstance(it, dict):
                continue
            q = it.get("question") or it.get("q")
            a = it.get("answer") or it.get("a")
            if not q or not a:
                continue
            items.append({
                "q": q, "a": a, "t": it.get("type", ""),
                "nq": strip_question_number(normalize(q)),
                "answer_options": it.get("answer_options"),
            })
        index = {}
        for it in items:
            index.setdefault(it["nq"], []).append(it)
        return {"items": items, "index": index}

    rows = load_rows(path)
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise RuntimeError("题库为空")
    header = rows[0]
    qcol = _pick(header, QUESTION_KEYS)
    acol = _pick(header, ANSWER_KEYS)
    tcol = _pick(header, TYPE_KEYS)
    if qcol is None or acol is None:
        # 没表头：假设第 1 列题目、第 2 列答案
        body = rows
        qidx, aidx, tidx = 0, 1, None
    else:
        body = rows[1:]
        qidx, aidx = header.index(qcol), header.index(acol)
        tidx = header.index(tcol) if tcol else None

    bank = []
    for r in body:
        if len(r) <= max(qidx, aidx):
            continue
        q = str(r[qidx]).strip()
        a = str(r[aidx]).strip()
        if not q or not a:
            continue
        t = str(r[tidx]).strip() if tidx is not None and tidx < len(r) else ""
        bank.append({"q": q, "a": a, "t": t, "nq": strip_question_number(normalize(q))})

    index = {}
    for item in bank:
        index.setdefault(item["nq"], []).append(item)
    return {"items": bank, "index": index}


def lookup_item(bank, question, threshold=0.90):
    """返回 (item, score, method)；item 保留 answer_options 等原始字段。"""
    nq = strip_question_number(normalize(question))
    if not nq:
        return None, 0.0, None
    if nq in bank["index"]:
        hits = bank["index"][nq]
        answers = {h["a"] for h in hits}
        return hits[0], 1.0, ("exact" if len(answers) == 1 else "exact-conflict")

    best, best_item = 0.0, None
    for item in bank["items"]:
        r = SequenceMatcher(None, nq, item["nq"]).ratio()
        if r > best:
            best, best_item = r, item
    if best >= threshold and best_item:
        return best_item, best, "fuzzy"
    return None, best, None


def lookup(bank, question, threshold=0.90):
    """返回 (answer, score, method)。找不到返回 (None, 0, None)。"""
    item, score, method = lookup_item(bank, question, threshold)
    if item is None:
        return None, score, method
    return item["a"], score, method


_TRUE_WORDS = {"对", "正确", "是", "true", "t", "y", "√", "yes", "1"}
_FALSE_WORDS = {"错", "错误", "否", "false", "f", "n", "×", "x", "no", "0"}

_OPT_PREFIX = re.compile(r"^\s*([A-Za-z])\s*[）).、:：]")


def strip_opt_prefix(text):
    return _OPT_PREFIX.sub("", str(text or ""))


def option_letter_map(options):
    """返回 ({'A': optionCode, ...}, 来源)。

    真实数据里 optionCode 是 Q2024...D 这类唯一 ID，
    字母写在 optionsContent 前缀（"D）20%"），所以优先解析前缀。
    """
    by_letter = {}
    for o in options:
        m = _OPT_PREFIX.match(str(o.get("optionsContent") or ""))
        if m:
            by_letter[m.group(1).upper()] = str(o.get("optionCode"))
    if len(by_letter) >= 2:
        return by_letter, "prefix"
    return {chr(65 + i): str(o.get("optionCode")) for i, o in enumerate(options)}, "index"


def resolve_answer(answer_text, options, multi=False):
    """把题库答案转成 optionCode 列表。

    支持：
      1) 选项字母：A / AB / A,C / "D）20%"（字母取自 optionsContent 前缀）
      2) 选项内容原文（含/不含字母前缀）
      3) 判断题：对/错/正确/错误/√/×/是/否
    """
    if answer_text is None or not options:
        return []
    raw = unicodedata.normalize("NFKC", str(answer_text)).strip()
    lmap, _src = option_letter_map(options)
    contents = [str(o.get("optionsContent") or "") for o in options]

    # 1) 字母形式（整串只由字母/分隔符组成时才按字母解释）
    compact = re.sub(r"[\s,，、;；/|]+", "", raw).upper()
    if compact and re.fullmatch(r"[A-H]{1,8}", compact) and all(ch in lmap for ch in compact):
        picked = []
        for ch in compact:
            code = lmap[ch]
            if code not in picked:
                picked.append(code)
        if not multi:
            picked = picked[:1]
        return picked

    # 2) 判断题关键词
    key = re.sub(r"[\s，。、；:：.()（）]", "", raw).lower()
    if key in _TRUE_WORDS or key in _FALSE_WORDS:
        want = "对" if key in _TRUE_WORDS else "错"
        for o, c in zip(options, contents):
            if normalize(strip_opt_prefix(c)) in {normalize(want), normalize("正确" if want == "对" else "错误")}:
                return [str(o.get("optionCode"))]
        if len(options) == 2:
            return [str(options[0 if want == "对" else 1].get("optionCode"))]

    # 3) 内容匹配
    na = normalize(strip_opt_prefix(raw))
    picked = []
    for o, c in zip(options, contents):
        nc = normalize(strip_opt_prefix(c))
        if nc and (nc == na or nc in na):
            picked.append(str(o.get("optionCode")))
    if picked:
        picked = [p for p in picked if p]
        return picked if multi else picked[:1]

    # 4) 模糊内容匹配
    best, best_code = 0.0, None
    for o, c in zip(options, contents):
        r = SequenceMatcher(None, na, normalize(strip_opt_prefix(c))).ratio()
        if r > best:
            best, best_code = r, str(o.get("optionCode"))
    if best >= 0.85 and best_code:
        return [best_code]
    return []

def resolve_answer_options(ans_opts, options, multi=False, trace=None):
    """按答案选项的「原文」匹配到考卷选项（选项顺序可能被打乱），字母仅作兜底。

    trace: 传入 list 时，会为每个答案选项追加 True/False，
           表示它是靠文本匹配到的（True）还是靠字母兜底的（False）。
    """
    if not ans_opts or not options:
        return []
    lmap, _ = option_letter_map(options)
    opt_norm = [(o, normalize(strip_opt_prefix(o.get("optionsContent")))) for o in options]
    picked = []
    for ao in ans_opts:
        text = normalize(strip_opt_prefix(ao.get("text", "")))
        letter = (ao.get("letter") or "").upper()
        code = None
        text_hit = False

        if text:
            exact = [o for o, n in opt_norm if n == text]
            if exact:
                code = str(exact[0]["optionCode"])
                text_hit = True
            else:
                # 题库答案可能只写了选项的一部分（如只写"包乘制"→"目前…采用包乘制"）。
                # 只允许「答案文本被包含在选项里」，反向包含会把短选项误判成唯一命中。
                sub = [o for o, n in opt_norm
                       if text and len(text) >= 4 and n and text in n]
                if len(sub) == 1:
                    code = str(sub[0]["optionCode"])
                    text_hit = True
            if code is None:
                best, best_o = 0.0, None
                for o, n in opt_norm:
                    r = SequenceMatcher(None, text, n).ratio()
                    if r > best:
                        best, best_o = r, o
                if best >= 0.90 and best_o is not None:
                    code = str(best_o["optionCode"])
                    text_hit = True

        if code is None and letter:
            code = lmap.get(letter)
        if code is None and letter and "A" <= letter <= "H":
            idx = ord(letter) - 65
            if idx < len(options):
                code = str(options[idx]["optionCode"])

        if code and code not in picked:
            picked.append(code)
        if trace is not None:
            trace.append(text_hit)

    return picked if multi else picked[:1]
