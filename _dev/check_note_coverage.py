# -*- coding: utf-8 -*-
"""集 ↔ 笔记章节对照（用真笔记核对视频知识点）

背景
----
Part 24 曾断言「资料库没有每集笔记文件」——**这个结论是错的**。真正的笔记在
`D:\\梁湘润\\1_直接可识别文字\\`，只是当时没查到该目录：

  38 集（命理传承班）→ `梁湘润_命理传承班笔记_(梁湘润).pdf`（180 页、12.1 万字，有文本层＝E3）
  32 集（子平基础课）→ `新增文字版（待校对）\\WORD-子平基础概要.docx`（216 页、5.0 万字）
                        `新增文字版（待校对）\\WORD-子平教材讲义.docx`（283 页、8.5 万字）

本工具做两件事：

  A. 38 集 ↔ 笔记：**逐集逐页单调对齐**。
     取笔记每页的「稀有 8-gram」（全书中出现 ≤3 页者），算每集在每页的命中数，
     再做单调动态规划（集序不减、页序不减），得到 E01→E38 的页序列。
     若结果严格递增且走完全书，即证明「视频就是按这本笔记讲的」。

  B. 32 集 ↔ 笔记：**章目级对照**（不做页级）。
     32 集不是照本宣读（用 8-gram 对齐每集只有 1–2 处命中，远低于 38 集的 40+），
     但主题体系相同：标题词在对应章节里是专章，在正文里成片出现。

依赖：pymupdf + opencc，须用 Python 3.12 解释器：
  C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python312\\python.exe
（默认 `python` 是 3.13，没装这两个包。）

用法：
  python tools/check_note_coverage.py                 # 打印汇总
  python tools/check_note_coverage.py --write         # 写 data/note_crosswalk.csv
"""
import argparse
import collections
import csv
import io
import os
import re
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PY312 = "C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe"

try:
    import pymupdf
except ImportError:  # 老版本只有 fitz
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

try:
    import opencc
    _CC = opencc.OpenCC("t2s")
except ImportError:
    opencc = None
    _CC = None


def _require_deps():
    """缺依赖就明确退出，不静默降级。

    不静默的原因：没有 opencc 时繁简不统一，8-gram 命中会大幅掉（38 集的对齐直接失效），
    但程序仍会跑出「看起来正常」的低分结果——那比报错更糟。
    """
    miss = []
    if pymupdf is None:
        miss.append("pymupdf")
    if opencc is None:
        miss.append("opencc")
    if miss:
        sys.stderr.write(
            "缺少依赖：%s\n"
            "本脚本须用 Python 3.12 解释器（默认 python 是 3.13，没装这两个包）：\n"
            "  %s tools/check_note_coverage.py\n" % ("、".join(miss), PY312))
        return False
    return True

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# ---------------------------------------------------------------- 笔记目录
# 页码取自 PDF 自带的目录页（`梁湘润_命理传承班笔记` p2–3），已与正文页眉核对。
NOTE38_CHAPTERS = [
    ("前言小叙", 3, 4), ("十神定位·比肩", 5, 8), ("十神定位·劫财", 9, 9),
    ("十神定位·偏印", 10, 12), ("十神定位·正印", 13, 13), ("十神定位·偏财", 14, 14),
    ("十神定位·正财", 15, 15), ("十神定位·七杀", 16, 17), ("十神定位·正官", 18, 18),
    ("十神定位·食神", 19, 19), ("十神定位·伤官", 19, 20), ("杂论", 21, 26),
    ("女命", 27, 45), ("格局续论", 46, 56), ("日主喜忌再谈", 57, 62),
    ("墓的用处", 63, 63), ("拦江网节选", 64, 69), ("天元巫咸经节选", 70, 87),
    ("流年部分", 88, 93), ("滴天髓十天干", 94, 98), ("八字例解", 99, 104),
    ("生旺库", 105, 107), ("再说财官", 108, 111), ("八字例题", 112, 153),
    ("杂论二", 154, 158), ("女命要重点", 159, 163), ("玉照定真经", 164, 169),
    ("杂论三", 170, 175), ("附录", 176, 180),
]

# 《子平基础概要》目录（页码取自该书目录页，已与页脚「第N页」核对）
NOTE32_SECTIONS = [
    ("前言", 3), ("五行干支刑冲合会", 6), ("四柱大运排列法", 15), ("取格局", 30),
    ("日主强弱", 38), ("论神煞", 47), ("论胎元", 56), ("论命宫", 58),
    ("半合、半刑、合冲", 60), ("论十二生旺库", 65), ("十神生克", 68),
    ("六亲与十神", 74), ("支藏天干", 78), ("本运", 84), ("十神定位法", 87),
    ("大运", 148), ("拱、夹", 154), ("八格喜忌", 157), ("顺用、逆用", 157),
    ("正官格", 160), ("财格", 167), ("印格", 172), ("食神格", 177),
    ("七杀格", 181), ("伤官格", 187), ("偏印格", 191), ("羊刃格", 194),
    ("特别格喜忌", 199), ("特别格", 199), ("从旺格", 200), ("从势格", 204),
    ("建禄格", 206), ("魁罡格", 209), ("金神格", 211), ("六阴朝阳", 213),
    ("六乙鼠贵", 215),
]

# 32 集标题 → (书, 章名, 检索词)。章名一律按目录原名写，不做「密度竞赛」式的自动挑章——
# 《命理传承班笔记》的目录页码是「标题所在页」，章体常从次页起，自动挑章会串章。
# 「书」取值：概要＝《子平基础概要》，笔记＝《命理传承班笔记》。
EP32 = {
    1: ("概要", "十神定位法", ["十神", "定位"]),
    2: ("概要", "十神定位法", ["比肩", "劫财", "劫財"]),
    3: ("概要", "偏印格", ["偏印"]),
    4: ("概要", "印格", ["正印"]),
    5: ("概要", "财格", ["偏财", "偏財"]),
    6: ("概要", "正官格", ["正官", "正财", "正財"]),
    7: ("概要", "七杀格", ["七杀", "七殺"]),
    8: ("概要", "食神格", ["食神", "伤官", "傷官"]),
    9: ("", "", ["寿夭", "壽夭", "短命", "夭折"]),  # 两书均无专章，见 note
    10: ("概要", "论神煞", ["神煞", "桃花"]),
    11: ("概要", "论神煞", ["神煞", "驿马", "驛馬"]),
    12: ("概要", "取格局", ["格局", "天透地藏"]),
    13: ("概要", "八格喜忌", ["八格", "顺用", "順用"]),
    14: ("概要", "八格喜忌", ["八格", "羊刃格"]),
    15: ("笔记", "女命", ["女命", "夫星"]),
    16: ("笔记", "女命", ["女命", "夫星"]),
    17: ("笔记", "女命", ["女命", "夫星"]),
    18: ("笔记", "女命", ["女命", "夫星"]),
    19: ("笔记", "女命", ["女命", "夫星"]),
    20: ("笔记", "滴天髓十天干", ["十天干", "调候", "調候"]),
    21: ("笔记", "滴天髓十天干", ["十天干", "调候", "調候"]),
    22: ("笔记", "滴天髓十天干", ["十天干", "调候", "調候"]),
    23: ("概要", "五行干支刑冲合会", ["五行", "喜忌"]),
    24: ("概要", "五行干支刑冲合会", ["五行", "喜忌"]),
    25: ("概要", "日主强弱", ["用神", "强弱", "強弱"]),
    26: ("概要", "日主强弱", ["用神", "强弱", "強弱"]),
    27: ("概要", "大运", ["大运", "大運", "流年"]),
    28: ("概要", "大运", ["大运", "大運", "流年"]),
    29: ("概要", "大运", ["大运", "大運", "流年"]),
    30: ("笔记", "杂论三", ["流月"]),
    31: ("笔记", "杂论三", ["流月"]),
    32: ("笔记", "八字例题", ["批命", "例题", "八字"]),
}


def norm(s):
    """纯汉字 + 繁转简（opencc 缺失时退化为不转，38 集对齐仍可跑）。"""
    s = _CC.convert(s or "") if _CC else (s or "")
    return re.sub(r"[^\u4e00-\u9fff]", "", s)


# ---------------------------------------------------------------- 读笔记
def pdf_pages(path):
    doc = pymupdf.open(path)
    return [norm(doc[i].get_text()) for i in range(doc.page_count)]


def docx_pages(path, marker=r"第(\d+)页"):
    """按页脚标记切页。`WORD-子平基础概要.docx` 每页前有「简体版本来自闲鱼：十年打渔第N页」。"""
    z = zipfile.ZipFile(path)
    xml = z.read("word/document.xml").decode("utf-8")
    pages, cur, buf = {}, 0, []
    for pa in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", pa, re.S))
        t = re.sub(r"<[^>]+>", "", t).strip()
        if not t:
            continue
        m = re.search(marker, t)
        if m and len(t) < 40:
            if cur:
                pages[cur] = norm("".join(buf))
            cur, buf = int(m.group(1)), []
        else:
            buf.append(t)
    if cur:
        pages[cur] = norm("".join(buf))
    return pages


def chapter_of(page, chapters):
    for name, a, b in chapters:
        if a <= page <= b:
            return name
    return "（目录外）"


# ---------------------------------------------------------------- 字幕
def load_episodes(lib, series):
    if series == "38":
        base = os.path.join(lib, "梁湘润 38集视频教程")
        out = {}
        if not os.path.isdir(base):
            return out
        for fn in os.listdir(base):
            m = re.match(r"^P(\d+)_字幕全文(.*)\.txt$", fn)
            if not m:
                continue
            e = int(m.group(1))
            if e in out and "校正" not in fn:
                continue
            with io.open(os.path.join(base, fn), encoding="utf-8-sig", errors="replace") as f:
                out[e] = norm(f.read())
        return out

    base = os.path.join(lib, "梁湘润 32级视频任务")
    out = {}
    if not os.path.isdir(base):
        return out
    for dirpath, _d, filenames in os.walk(base):
        for fn in filenames:
            if fn.lower().endswith(".txt"):
                m = re.match(r"P(\d+)_字幕全文.*\.txt$", fn)
                if m and int(m.group(1)) not in out:
                    with io.open(os.path.join(dirpath, fn), encoding="utf-8-sig",
                                 errors="replace") as f:
                        out[int(m.group(1))] = norm(f.read())
            elif fn.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(os.path.join(dirpath, fn)) as z:
                        for name in z.namelist():
                            m = re.match(r"P(\d+)_字幕全文.*\.txt$", name)
                            if m and int(m.group(1)) not in out:
                                out[int(m.group(1))] = norm(
                                    z.read(name).decode("utf-8-sig", errors="replace"))
                except zipfile.BadZipFile:
                    continue
    return out


# ---------------------------------------------------------------- A. 38 集对齐
def align38(pages, eps, k=8, max_df=3):
    """稀有 k-gram + 单调 DP 对齐。返回 {集: (页, 命中数)}。"""
    grams = [set(p[i:i + k] for i in range(len(p) - k + 1)) for p in pages]
    df = collections.Counter()
    for s in grams:
        for g in s:
            df[g] += 1
    rare = [{g for g in s if df[g] <= max_df} for s in grams]

    order = sorted(eps)
    n, m = len(order), len(pages)
    score = [[sum(1 for g in rare[j] if g in eps[e]) for j in range(m)] for e in order]

    NEG = -10 ** 9
    dp = [[NEG] * m for _ in range(n)]
    bk = [[-1] * m for _ in range(n)]
    for j in range(m):
        dp[0][j] = score[0][j]
    for i in range(1, n):
        best, bi = NEG, -1
        for j in range(m):
            if dp[i - 1][j] > best:
                best, bi = dp[i - 1][j], j
            if best != NEG:
                dp[i][j] = best + score[i][j]
                bk[i][j] = bi
    j = max(range(m), key=lambda x: dp[n - 1][x])
    path = [j]
    for i in range(n - 1, 0, -1):
        j = bk[i][j]
        path.append(j)
    path.reverse()
    return {e: (path[i] + 1, score[i][path[i]]) for i, e in enumerate(order)}


def conf38(hits):
    if hits >= 20:
        return "已核（强）"
    if hits >= 10:
        return "已核（中）"
    if hits >= 3:
        return "待核（弱）"
    return "待核（极弱）"


# ---------------------------------------------------------------- B. 32 集章目
def section_text(pages, sections, name):
    """按章节名取正文；返回 (文本, 起页, 止页)。"""
    for i, item in enumerate(sections):
        nm, a = item[0], item[1]
        if nm != name:
            continue
        # 下一章「起页不同」者才算本章终点——同一页可能挂两个标题（如 p157 八格喜忌／顺用逆用）
        b = len(pages)
        for item2 in sections[i + 1:]:
            if item2[1] > a:
                b = item2[1] - 1
                break
        b = max(a, min(b, len(pages)))
        return "".join(pages[a - 1:b]), a, b
    return "", 0, 0


def density(text, terms):
    """每千字命中数。"""
    if not text:
        return 0.0
    return sum(text.count(t) for t in terms) * 1000.0 / len(text)


def probe32(pages32, pages38, book, section, terms):
    """在指派章节里算检索词密度，并与全书平均密度对比。

    返回 (起页, 止页, 章内密度‰, 章内命中, 全书命中, 全书密度‰)。
    「章内密度 ≥ 全书密度」即认为该章确实讲这个（ratio ≥ 1）。
    """
    pages, secs = (pages32, NOTE32_SECTIONS) if book == "概要" else (pages38, NOTE38_CHAPTERS)
    if not pages:
        return 0, 0, 0.0, 0, 0, 0.0
    body, s0, s1 = section_text(pages, secs, section)
    hit = sum(body.count(t) for t in terms)
    d = density(body, terms)
    total = sum(p.count(t) for p in pages for t in terms)
    dall = total * 1000.0 / max(1, sum(len(p) for p in pages))
    return s0, s1, d, hit, total, dall


def main():
    if not _require_deps():
        return 2

    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default="D:/梁湘润")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    note_dir = os.path.join(a.lib, "1_直接可识别文字")
    pdf38 = os.path.join(note_dir, "梁湘润_命理传承班笔记_(梁湘润).pdf")
    docx32 = os.path.join(note_dir, "新增文字版（待校对）", "WORD-子平基础概要.docx")
    if not os.path.exists(pdf38):
        print("找不到 38 集笔记：%s" % pdf38)
        return 2

    pages38 = pdf_pages(pdf38)
    eps38 = load_episodes(a.lib, "38")
    eps32 = load_episodes(a.lib, "32")
    pages32 = {}
    if os.path.exists(docx32):
        pd = docx32_pages = docx_pages(docx32)
        mx = max(pd) if pd else 0
        pages32 = [pd.get(i, "") for i in range(1, mx + 1)]

    rows = []

    # ---- A. 38 集
    align = align38(pages38, eps38)
    print("== 38 集 ↔《命理传承班笔记》（%d 页，%d 字）"
          % (len(pages38), sum(len(p) for p in pages38)))
    prev = 0
    mono = True
    for e in sorted(align):
        page, hits = align[e]
        if page < prev:
            mono = False
        prev = page
        chap = chapter_of(page, NOTE38_CHAPTERS)
        rows.append(dict(series="38", episode=e, title="（无标题）",
                         note_book="命理传承班笔记", note_section=chap, note_page=page,
                         match_hits=hits, confidence=conf38(hits),
                         note="稀有 8-gram 命中 %d 处；单调对齐" % hits))
        print("  E%02d → p%-4d %-16s 命中 %3d  %s"
              % (e, page, chap, hits, conf38(hits)))
    tot = sum(v[1] for v in align.values())
    print("  合计命中 %d 处；页序严格递增：%s" % (tot, "是" if mono else "否"))

    # ---- B. 32 集
    if pages32:
        print("== 32 集 ↔ 笔记章节（指派章，算章内密度／全书密度）")
        with io.open(os.path.join(DATA, "video_episode_map.csv"), encoding="utf-8-sig") as f:
            titles = {int(r["episode"]): r["title_join"]
                      for r in csv.DictReader(f) if r["series"] == "32"}
        for e in range(1, 33):
            book, section, terms = EP32.get(e, ("概要", "", []))
            if not book:
                n38 = sum(p.count(t) for p in pages38 for t in terms)
                n32 = sum(p.count(t) for p in pages32 for t in terms)
                rows.append(dict(series="32", episode=e, title=titles.get(e, ""),
                                 note_book="（两书均无）", note_section="（无专章）", note_page="",
                                 match_hits=n38 + n32, confidence="待核（无对应章）",
                                 note="《子平基础概要》《命理传承班笔记》均无寿夭专章；"
                                      "梁氏立场是「三不谈」——短命不谈（笔记 p8、p164）；"
                                      "两书「短命／夭折」合计仅 %d 次" % (n38 + n32)))
                print("  E%02d %-16s 无专章（两书 短命/夭折 共 %d 次）" % (e, titles.get(e, ""), n38 + n32))
                continue
            s0, s1, d, hit, total, dall = probe32(pages32, pages38, book, section, terms)
            ratio = d / dall if dall else 0.0
            span = (s1 - s0 + 1) if s0 else 0
            wide = span > 0.25 * len(pages32 if book == "概要" else pages38)
            if not s0:
                conf = "待核（章未找到）"
            elif hit == 0:
                conf = "无对应（章内 0 次）"
            elif wide:
                conf = "章目核（章过宽，密度不可判）"
            elif ratio >= 3.0 and hit >= 15:
                conf = "章目核（强）"
            elif ratio >= 1.0 and hit >= 8:
                conf = "章目核（中）"
            elif ratio >= 1.0:
                conf = "章目核（弱·命中少）"
            else:
                conf = "待核（章内密度低于全书）"
            note = "%s《%s》「%s」p%d-%d；章内 %.1f‰、全书 %.1f‰、比值 %.2f；章内 %d 次、全书 %d 次" % (
                book, "子平基础概要" if book == "概要" else "命理传承班笔记",
                section, s0, s1, d, dall, ratio, hit, total)
            rows.append(dict(series="32", episode=e, title=titles.get(e, ""),
                             note_book="子平基础概要" if book == "概要" else "命理传承班笔记",
                             note_section=section, note_page=s0, match_hits=hit,
                             confidence=conf, note=note))
            print("  E%02d %-16s %-6s %-10s p%-3d-%-3d %5.1f‰/%.1f‰ ×%.2f  %s"
                  % (e, titles.get(e, ""), book, section, s0, s1, d, dall, ratio, conf))
        c32 = collections.Counter(r["confidence"] for r in rows if r["series"] == "32")
        for k in sorted(c32):
            print("  %s：%d 集" % (k, c32[k]))
    else:
        print("（找不到《子平基础概要》，跳过 32 集）")

    if a.write:
        p = os.path.join(DATA, "note_crosswalk.csv")
        with io.open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["series", "episode", "title", "note_book",
                                              "note_section", "note_page", "match_hits",
                                              "confidence", "note"], lineterminator="\r\n")
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print("已写入 %s（%d 行）" % (p, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
