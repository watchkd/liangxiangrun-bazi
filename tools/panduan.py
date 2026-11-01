#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批命推演器（panduan）：按梁氏次序走一遍，出「看到什么／依什么理／断什么」。

与 analyze.py 的分工：
  analyze  —— 以**资料**为纲：四柱、藏干、形态、用神、刑冲……有什么列什么（台账）
  panduan  —— 以**判断**为纲：先看什么、看到什么、因此断什么、断到哪一档（推演）

本器不排历法（仍用 paipan.py）、不改四柱、不补通行术数。断语一律给方向与分寸，
不给「必然／注定」；引文出处只在 --trace 时附，正常输出不出现 rule_id。

用法：
  python tools/panduan.py 甲子 乙亥 庚戌 癸未 --gender 男
  python tools/panduan.py 甲子 乙亥 庚戌 癸未 --gender 男 \\
      --birth-year 1984 --start-age 10 --dayun 丙子,丁丑,戊寅 --liunian 2026,2027
  python tools/panduan.py 甲子 乙亥 庚戌 癸未 --gender 男 \\
      --birth-year 1984 --start-age 10 --dayun 丙子,丁丑,戊寅 --recent 5
      # 当前大运近五年：先定今年在第几运、运内第几年，再论这五年
  python tools/panduan.py … --trace          # 附依据编号（批者自看）
  python tools/panduan.py … --out 提纲.md
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A  # noqa: E402
import xingqing as XQ  # noqa: E402
import liuqin as LQ  # noqa: E402
import shishen_pos as SP  # noqa: E402

POS = ["年", "月", "日", "时"]
STEM_ELEM = A.STEM_ELEM
BRANCH_ELEM = {"子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土", "巳": "火",
               "午": "火", "未": "土", "申": "金", "酉": "金", "戌": "土", "亥": "水"}
ELEM_OF_GOD = {"比肩": "同我", "劫财": "同我", "食神": "我生", "伤官": "我生",
               "正财": "我克", "偏财": "我克", "正官": "克我", "七杀": "克我",
               "正印": "生我", "偏印": "生我"}
TRIAD = {"三合", "三会", "半合", "拱合"}
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ═════════════ 〇、判断点→条文（一致率审计的「边」） ═════════════
# 为什么要有这张表
#   之前每个判断点都写「依什么理」，但那是散文——梁氏原话的转写，不是可核验的边。
#   一旦要问「这盘断得对不对」，就得能回答：这一点压在哪几条条文上。
#   故另立 data/point_rules.csv：每点一到十条，附一句「凭什么算依据」。
#   收条只收原书直接说该点之理者；查表类（宰公要诀／金不换月令）不入此表，
#   那是结构触发，由 trace_audit 按盘面现算，两笔账分开记。
def _load_point_rules():
    import csv
    import io as _io
    fp = os.path.join(_ROOT, "data", "point_rules.csv")
    out = {}
    if not os.path.exists(fp):
        return out
    for r in csv.DictReader(_io.open(fp, encoding="utf-8-sig")):
        ids = [x.strip() for x in (r.get("rule_ids") or "").split("|") if x.strip()]
        out[r["pid"]] = {"name": r["name"], "ids": ids,
                         "note": (r.get("basis_note") or "").strip()}
    return out


PR = _load_point_rules()


def point_ids(pid):
    return list((PR.get(pid) or {}).get("ids") or [])


def _ids_tail(pid):
    ids = point_ids(pid)
    return ("　`%s`" % "／".join(ids)) if ids else ""


def basis_line(pid):
    d = PR.get(pid) or {}
    ids = d.get("ids") or []
    if not ids:
        return ""
    tail = ("——" + d["note"]) if d.get("note") else ""
    return "> 本点依据：`%s`%s" % ("／".join(ids), tail)


# ══════════════════════════ 一、盘面事实 ══════════════════════════
def facts(a):
    """把散在 a 里的东西收成一张事实表，供后文各节取用。不在此下断。"""
    day = a["pillars"][2][0]
    month = a["pillars"][1][1]
    # 天干四字 / 地支四字 / 支藏全字
    stems = [(POS[i], r["stem"], r["stem_tg"]) for i, r in enumerate(a["expanded"])]
    hidden = [(r["pos"], h["stem"], h["tg"]) for r in a["expanded"] for h in r["hidden"]]
    all_stems = {s for _, s, _ in stems}
    all_hidden = {s for _, s, _ in hidden}
    # 位置索引：某十神落在哪（透干优先）
    where = {}
    for pos, s, tg in stems:
        if tg != "日主":
            where.setdefault(tg, []).append(("透" + pos, s))
    for pos, s, tg in hidden:
        where.setdefault(tg, []).append(("藏" + pos, s))
    # 冲的落点（梁氏四种双冲各有定论，须按柱位分）
    chong = []
    for r in a["relations"]:
        if "冲" in r["kind"] and r.get("members"):
            ms = r["members"]
            if len(ms) == 2 and all(isinstance(m, (list, tuple)) and len(m) >= 1 for m in ms):
                p1 = ms[0][0] if isinstance(ms[0], (list, tuple)) else str(ms[0])
                p2 = ms[1][0] if isinstance(ms[1], (list, tuple)) else str(ms[1])
                chong.append((p1, p2))
    return {
        "day": day, "month": month,
        "season": a["xingtai"]["season"],
        "xiadong": a["xingtai"]["xiadong"],
        "stem_rows": stems, "hidden_rows": hidden,
        "all_stems": all_stems, "all_hidden": all_hidden, "all_chars": all_stems | all_hidden,
        "where": where,
        "chong": chong,
        "pillars": a["pillars"],
    }


def th_presence(a, f):
    """调候格值那几个字，在盘里到底是「透干／只藏／全无」。

    梁氏批调候，不只查表取字，还要看这个字在命中立不立得住——
    格值给了「丁丙」而盘中一字不见，与「透在年干」，断法完全不同。
    """
    out = []
    for c in a["th"]:
        if not c["table_id"].endswith("-ORIG"):
            continue
        val = c["value"] or ""
        chars = [x for x in val if x in "甲乙丙丁戊己庚辛壬癸"]
        rows = []
        for ch in chars:
            if ch in f["all_stems"]:
                p = [r["pos"] for r in a["expanded"] if r["stem"] == ch]
                rows.append((ch, "透干", "／".join(p)))
            elif ch in f["all_hidden"]:
                p = [r["pos"] for r in a["expanded"] if ch in [h["stem"] for h in r["hidden"]]]
                rows.append((ch, "只藏支", "／".join(p)))
            else:
                rows.append((ch, "全无", "—"))
        out.append({"value": val, "cell": c["cell_id"], "rows": rows})
    return out


def sixkin(a):
    """六亲星定位：妻／夫、子、父母、兄弟。只报「在哪、透不透」，不下断。"""
    g = a["gender"]
    f = a["where"] if "where" in a else {}
    where = a["where"]
    def loc(gods):
        items = []
        for gd in gods:
            for at, ch in where.get(gd, []):
                items.append((gd, at, ch))
        return items
    if g == "男":
        spouse = loc(["正财", "偏财"])
        child = loc(["正官", "七杀"])
    elif g == "女":
        spouse = loc(["正官", "七杀"])
        child = loc(["食神", "伤官"])
    else:
        spouse, child = [], []
    return {
        "spouse": spouse, "child": child,
        "parent": loc(["正印", "偏印"]), "sib": loc(["比肩", "劫财"]),
        "wealth": loc(["正财", "偏财"]), "career": loc(["正官", "七杀"]),
    }


# ══════════════════════════ 二、十项优先 ══════════════════════════
def _it(no, name, seen, why, say, grade, weight=0, tag="", ids=()):
    return {"no": no, "name": name, "seen": seen, "why": why,
            "say": say, "grade": grade, "w": weight, "tag": tag,
            "ids": list(ids)}



def item_wuxing(a, f):
    miss = a["missing"]
    if not miss:
        wx = a["wuxing"]
        s = "五行为%s，不缺。" % "／".join("%s%d" % (e, wx[e]) for e in "木火土金水")
        return _it(1, "五行全不全", s,
                   "梁氏：缺一行才重，缺二三行反平常。全而不缺者，此一项不落断。",
                   "五行不缺，第 1 项不作断语，直接过。", "确断", 0)
    # 缺一行 —— 三分法：四大空亡／调候不全／眷属
    lines = []
    th_chars = set()
    for c in a["th"]:
        if c["table_id"].endswith("-ORIG"):
            th_chars |= {x for x in (c["value"] or "") if x in "甲乙丙丁戊己庚辛壬癸"}
    miss_th = [x for x in th_chars if STEM_ELEM.get(x) in miss]
    if miss_th:
        lines.append("所缺正是调候用神（%s 属%s），此项最重" %
                     ("／".join(miss_th), "、".join(sorted({STEM_ELEM[x] for x in miss_th}))))
    # 四大空亡：缺的五行正落旬空
    kw = [A.kongwang(p) for p in a["pillars"]]
    lines.append("旬空：%s" % "；".join("%s柱%s" % (POS[i], "／".join(kw[i])) for i in range(4)))
    sage = ("缺 %s 一行。%s。" % ("、".join(miss), "；".join(lines)))
    w = 3 if miss_th else 2
    return _it(1, "五行全不全", sage,
               "梁氏三分法：①四大空亡（缺者落旬空）②调候不全（缺的正是调候用神，最重）③眷属（女缺夫星、男缺妻星）。",
               "缺的那一行要单独看它是不是调候、是不是财官；是则重，不是则只记形态。",
               "倾向", w, "缺行")


def item_yinyang(a, f):
    xt = a["xingtai"]
    if xt["all_yang"]:
        return _it(2, "阴阳有无偏枯", "四柱全阳。",
                   "梁氏：全阳不利男，全阴不利女。",
                   "全阳之造，男命作「孤刚」看；女命不论。", "倾向", 2, "全阳")
    if xt["all_yin"]:
        return _it(2, "阴阳有无偏枯", "四柱全阴。",
                   "梁氏：全阳不利男，全阴不利女。",
                   "全阴之造，女命作「偏柔少断」看；男命不论。", "倾向", 2, "全阴")
    n_y = sum(1 for r in a["expanded"] if r["stem"] in A.YANG)
    return _it(2, "阴阳有无偏枯", "阴阳相参（阳干 %d／4）。" % n_y,
               "未全阳全阴者，此项不作断，只记结构。", "阴阳不偏，过。", "确断", 0)


def item_xingchong(a, f):
    """四种双冲各有定论——这是梁氏最硬的一处柱位断法，务必按落点分。"""
    rules = {("日", "月"): ("常法之最重", 3), ("月", "日"): ("常法之最重", 3),
             ("年", "日"): ("主本不和，纵富贵亦不久", 3), ("日", "年"): ("主本不和，纵富贵亦不久", 3),
             ("年", "时"): ("别立根基之人", 2), ("时", "年"): ("别立根基之人", 2),
             ("月", "时"): ("恐有迭次起倒之遇", 3), ("时", "月"): ("恐有迭次起倒之遇", 3)}
    hits, w, say = [], 0, []
    for p1, p2 in f["chong"]:
        k = (p1, p2)
        if k in rules:
            txt, ww = rules[k]
            hits.append("%s%s双冲 → %s" % (p1, p2, txt))
            w = max(w, ww)
            say.append(txt)
    others = [r for r in a["relations"] if r["kind"] not in ("六冲",) and r["kind"] not in TRIAD]
    rel_all = a["relations"]
    if not rel_all:
        return _it(3, "刑冲形态", "四柱无刑冲合会。",
                   "无刑冲者，此项不作断；但须记「无冲不等于无动」，运来冲之则动。",
                   "本命支间无事，静盘。", "确断", 0)
    seen = "；".join("%s（%s）" % (r["kind"], "、".join(
        x if isinstance(x, str) else "".join(map(str, x)) for x in r.get("members", [])[:4]))
        for r in rel_all[:8])
    if hits:
        return _it(3, "刑冲形态", "见：" + seen + "。其中" + "；".join(hits) + "。",
                   "梁氏四种双冲各系定论，按落柱判，不按冲的字面判。",
                   "；".join(say) + "。此一层可作确断，因柱位是死的。", "确断", w, "双冲")
    return _it(3, "刑冲形态", "见：" + seen + "。无日月／年日／年时／月时四种双冲。",
               "无四种双冲者，刑冲只作「动的方向」记，不单独断吉凶。",
               "支间有动而无重冲，事项随运引发，本命不先断。", "倾向", 1)


SS_BY = {"JS-SS-01": "年支", "JS-SS-02": "月支", "JS-SS-03": "日干", "JS-SS-04": "日支"}
XING_GOD = {"克我"}  # 神煞所落之支，五行克日主者


def item_shensha(a, f):
    hit = [s for s in a["shensha"] if s.get("hits")]
    sp = a.get("shensha_sp") or {}
    sp_hit = [x for x in (sp.get("items") or []) if x.get("state") == "命中"] if isinstance(sp, dict) else []
    if not hit:
        return _it(4, "神煞性质与日主冲克", "四表实查未见落点。",
                   "神煞不宜克日主——这是梁氏唯一一句肯给吉凶的话。",
                   "神煞不临，此项不作断。", "确断", 0)
    # 按表归组：年支查／月支查／日干查／日支查
    groups = {}
    ke = []
    ed = STEM_ELEM.get(f["day"])
    for s in hit:
        by = SS_BY.get(s.get("table", ""), "他")
        br = s.get("key") or ""
        groups.setdefault(by, []).append(s.get("name", ""))
        eb = BRANCH_ELEM.get(br)
        if eb and ed and A.KE.get(eb) == ed:
            ke.append(s.get("name", ""))
    parts = ["%s查得%s" % (by, "、".join(v)) for by, v in groups.items()]
    txt = "；".join(parts) + "。"
    if sp_hit:
        txt += "另，神煞探源起例命中 %d 条。" % len(sp_hit)
    if ke:
        say = "%s落支克日主——这是唯一可论的一处，须在命书里点出。" % "、".join(ke)
        w = 2
    else:
        say = ("所见诸煞，落支皆不克日主，故只记名目，不作祸福之断。"
               "凡称某煞主某祸福者（孤寡、桃花、羊刃之类），两说并存，本包不代裁。")
        w = 1
    return _it(4, "神煞性质与日主冲克", txt,
               "梁氏：神煞之吉凶，只在「克不克日主」四字。不克日主者，只记名目。",
               say, "倾向", w, "神煞")


def item_liuqin(a, f):
    sk = sixkin(a)
    g = a["gender"]
    if not g:
        return _it(5, "六亲概括特征", "性别未给，六亲星无从取。",
                   "女以官杀为夫、食伤为子；男以财为妻、官杀为子。性别不定，此一项不落算。",
                   "补性别后再断六亲。", "不适用", 0)
    def fmt(lst, label):
        if not lst:
            return "%s不见" % label
        # 透干在前，正星在前
        lst = sorted(lst, key=lambda x: (0 if x[1].startswith("透") else 1,
                                         0 if x[0].startswith("正") else 1))
        return "%s：%s" % (label, "、".join("%s%s（%s）" % (gd, at, ch) for gd, at, ch in lst[:4]))
    sp = fmt(sk["spouse"], "妻星" if g == "男" else "夫星")
    ch = fmt(sk["child"], "子星")
    say = ("星透者，其事摆在明处；星藏者，其事在暗处、须运引发；"
           "星不见者，不以「无」断「没有」，只断「淡」。")
    w = 1
    # 权重按星之状态浮动——六亲项不该恒为一分
    n_sp = _has(a, ["正财", "偏财"]) if g == "男" else _has(a, ["正官", "七杀"])
    if g == "女" and _has(a, ["正官"]) and _has(a, ["七杀"]):
        w = 3
        say = ("**官杀混杂**——梁氏以此为女命夫星通忌。然逐月有开禁，须看有无合杀留官、"
               "合官留杀；不见合者，主夫缘反复、择偶难定。" + say)
    elif not n_sp:
        w = 2
        say = ("**" + ("妻" if g == "男" else "夫") + "星不见**——作「缘淡」或「事迟」论，"
               "不作「没有」论；运岁见星旺之乡则可补。" + say)
    elif g == "男" and _mu(a, ["正财", "偏财"]):
        w = 2
        say = "**妻星归库**，忌早婚；须看运冲开库。" + say
    return _it(5, "六亲概括特征", "%s；%s。" % (sp, ch),
               "六亲以星论，先看星之有无与透藏，再看星落何宫——星宫合看，不可只论一字。",
               say, "倾向", w, "六亲")


def item_nianshi(a, f):
    y, s = a["pillars"][0], a["pillars"][3]
    return _it(6, "年、时二柱关联", "年柱 %s，时柱 %s。" % (y, s),
               "梁氏列此项为明代纳音法余绪，用以补用神格局之不足；本包纳音断语未入库，只作结构对照。",
               "年时为始终二端：年主根源、时主归宿。此一项本包只记，不断——纳音断法尚未入库。",
               "不适用", 0)


def item_tiaohou(a, f):
    tp = th_presence(a, f)
    if not tp:
        return _it(7, "调候用神喜忌", "调候原表未检索到本命格值。",
                   "无格值者不得按常法补——补出来的字，书里没有。",
                   "此项查不出，不作断；命书里以「调候之字须再核」一句带过。", "存疑", 0)
    blocks, w, absent = [], 0, []
    for t in tp:
        seg = []
        for ch, mode, pos in t["rows"]:
            seg.append("%s%s%s" % (ch, mode, "" if mode == "全无" else "（" + pos + "）"))
            if mode == "全无":
                absent.append(ch)
        blocks.append("格值「%s」：%s" % (t["value"], "、".join(seg)))
        if any(m == "透干" for _, m, _ in t["rows"]):
            w = max(w, 1)
        elif any(m == "只藏支" for _, m, _ in t["rows"]):
            w = max(w, 2)
        else:
            w = max(w, 3)
    seen = "；".join(blocks) + "。"
    if absent:
        say = ("调候所取之字有「%s」在命中全无——这是本命第一等处。"
               "调候之字不见，不是「缺个喜用」那么轻，是这一生的气候少了一味；"
               "须看运来补不补得上。" % "、".join(absent))
    else:
        say = "调候之字在命中有著落，只须看它透不透、受不受制。"
    return _it(7, "调候用神喜忌", seen,
               "梁氏：调候用神须与格局配属，不是有则吉。字在不在、透不透、被不被合，三件事分开看。",
               say, "倾向", w, "调候")


# 格局的「用格」层：成在哪一字、败在哪一字。同格不同用，全看这一处。
# 格 → (关键之神, 该神之名, 克它的是谁, 克它之名, 无它则如何)
GE_KEY = {
    "羊刃格": (["七杀"], "制刃之神（七杀）", ["食神", "伤官"], "克杀之神（食伤）",
               "刃旺无制——性刚而易折，一生之气无处泄"),
    "七杀格": (["食神", "伤官", "正印", "偏印"], "制化之神（食伤／印）", ["偏财", "正财"], "坏制之神（财）",
               "杀无制化——压力直接上身，须看运来救"),
    "伤官格": (["正印", "偏印"], "佩印之神（印）", ["正财", "偏财"], "破印之神（财）",
               "伤官无制——才气外泄，须看运"),
    "正官格": (["正财", "偏财", "正印", "偏印"], "护官之神（财／印）", ["伤官"], "伤官",
               "官无护——名位须运来"),
    "偏财格": (["正官", "七杀"], "护财之神（官杀）", ["比肩", "劫财"], "夺财之神（比劫）",
               "财无护——财来财去，须看运"),
    "正财格": (["正官", "七杀"], "护财之神（官杀）", ["比肩", "劫财"], "夺财之神（比劫）",
               "财无护——财来财去，须看运"),
    "偏印格": (["正财", "偏财"], "制枭之神（财）", ["正印", "偏印"], "助枭之神（印）",
               "枭无制——多思而少成"),
    "正印格": (["正官", "七杀"], "生印之神（官杀）", ["正财", "偏财"], "破印之神（财）",
               "印无生——学而无位"),
}
LEVEL = [1.0, 0.6, 0.4]  # 本气／中气／余气


def god_strength(a, gods):
    """某类十神在本盘的力量：透干计 2，支藏按本中余气递减，得月令再加半分。"""
    if not gods:
        return 0.0, []
    tot, where = 0.0, []
    moy = a["pillars"][1][1]
    for i, row in enumerate(a["expanded"]):
        if row["stem_tg"] in gods:
            tot += 2.0
            where.append(row["pos"] + "干" + row["stem"])
        for j, h in enumerate(row["hidden"]):
            if h["tg"] in gods:
                tot += LEVEL[min(j, 2)]
                where.append(row["pos"] + "支" + h["stem"])
    # 得月令者加力
    if a["expanded"][1]["hidden"] and a["expanded"][1]["hidden"][0]["tg"] in gods:
        tot += 0.5
    return round(tot, 1), where


def ge_key_point(a):
    """格局的关键制化：成格看这一字有没有，用格看这一字有没有力。"""
    gj = a.get("geju") or {}
    name = gj.get("name", "")
    if name not in GE_KEY:
        return None
    key_gods, key_name, rival_gods, rival_name, bad = GE_KEY[name]
    ks, kw = god_strength(a, key_gods)
    rs, rw = god_strength(a, rival_gods)
    has = ks > 0
    if not has:
        return {"state": "无", "say": "本格取「%s」，而盘中%s不见——%s。" % (name, key_name, bad),
                "weight": 3, "key": key_name, "ks": 0, "rs": rs}
    if rs > ks:
        return {"state": "受制", "say": "「%s」虽在（%s），而%s更重（%s）——制之太过。"
                                        "本事有而舞台小，须看运来解。" % (key_name, "、".join(kw[:3]),
                                                                          rival_name, "、".join(rw[:3])),
                "weight": 3, "key": key_name, "ks": ks, "rs": rs}
    if ks >= rs * 2 and ks >= 2:
        return {"state": "有力", "say": "「%s」得力（%s），格之关键立得住——此造一生之要，就在这里。"
                % (key_name, "、".join(kw[:3])), "weight": 3, "key": key_name, "ks": ks, "rs": rs}
    return {"state": "薄", "say": "「%s」虽见（%s），而力薄；格有其名，用则须运助。"
            % (key_name, "、".join(kw[:3])), "weight": 2, "key": key_name, "ks": ks, "rs": rs}


def item_geju(a, f):
    gj = a.get("geju") or {}
    if not gj:
        return _it(8, "格局顺逆及用格喜忌", "格局未能裁定。", "—", "此项不作断。", "存疑", 0)
    name = gj.get("name", "（未裁）")
    shun = gj.get("shun", "")
    how = gj.get("how", "")
    verdict = gj.get("verdict", "")
    waige = gj.get("waige", "")
    seen = "取格：%s；%s；%s。" % (name, shun, how)
    if verdict:
        seen += "顺逆之判：%s。" % verdict
    if waige:
        seen += "成格：%s。" % waige
    w = 3 if waige else 0
    kp = ge_key_point(a)
    say = ("成格看形式，用格看力量——同格不同用。伤官佩印而伤官弱、印无根，纵有其名亦有限之论。")
    if kp:
        seen += "格之关键：%s。" % kp["say"]
        w = max(w, kp["weight"])
        say = kp["say"]
    elif w:
        say = "格成（%s），此为本造骨架。" % waige
    # 格的专条（R-MF-038 偏印格三依据／R21 食神变德）：原先引擎一条也未算
    special = gj.get("special") or []
    ids = []
    if special:
        seen += "本格专条：%s。" % "；".join(special)
        w = max(w, 3)
        say = special[-1]
        if gj.get("name") == "偏印格":
            ids.append("R-MF-038")
        if any("R21" in x or "食神变德" in x for x in special):
            ids.append("R21")
    # R13：今无科举，月令纵好亦难成大事——格局一层须降半级看，不照古法作第一优先
    seen = seen.rstrip("。；， ")
    seen += "。按梁师的意思：今无科举，月令之格纵好亦难成大事——故格局虽列第二，只作骨架、不作定论。"
    ids.append("R13")
    return _it(8, "格局顺逆及用格喜忌", seen,
               "成格看形式，用格看力量——同格不同用。",
               say, "确断" if w >= 3 else "倾向", w, "格局", ids)


def item_shenqiang(a, f):
    if a["xingtai"]["xiadong"]:
        return _it(9, "日主强弱扶抑", "月支 %s 属%s，夏冬生人。" % (f["month"], a["xingtai"]["season"]),
                   "梁氏原话：夏冬生人，以调候为第一，并没有身强身弱的问题。身强弱属第五级。",
                   "此一项在本命不适用——不套「身弱不能托财官」「克泄交加」。误套则全盘皆错。",
                   "确断", 0, "压后")
    wr = a["xingtai"]["heavy_roots"]
    say = ("日主有重根，作「立得住」看。" if wr else
           "日主无重根，作「漂浮」看——但原文另言「若无根……然也未必贫贱」，故只断根基，不断穷通。")
    seen = "重根 %d 处（临官／帝旺计重）。" % wr
    ids = []
    if f["day"] in ("戊", "己"):
        # R-MF-039：戊己土借火之生旺库。宫位表两说并存，本器不改表，但根气一项须两说并列
        seen += ("生旺库另有一说：梁氏主「丙丁与戊己皆以火之生寅、旺午、库戌」——"
                 "戊己之根气随火，不随水土。本器宫位表仍按十干禄自洽，二说未合并。")
        ids.append("R-MF-039")
        say += "（%s日主，根气须两说并看：本表之根与「土借火」之根，可能不同档。）" % f["day"]
    return _it(9, "日主强弱扶抑", seen,
               "身强弱压第五级；重根只定「漂浮／扎实」，不得据此独断富贵。",
               say, "倾向", 0 if wr else 1, "", ids)



def ten_items(a, f):
    return [item_wuxing(a, f), item_yinyang(a, f), item_xingchong(a, f),
            item_shensha(a, f), item_liuqin(a, f), item_nianshi(a, f),
            item_tiaohou(a, f), item_geju(a, f), item_shenqiang(a, f)]


# ══════════════════════════ 三、核心矛盾 ══════════════════════════
def core_conflict(a, items):
    """挑出「这一造最要紧的一处」。梁氏批命先抓主矛，不平均用力。

    取权重最高者；同权重按梁氏次序（调候＞格局＞双冲＞六亲）取前。
    权重不足者（全为 0／1）不硬凑——无大病之造，本就不该硬找一句话。
    """
    order = {"调候": 0, "格局": 1, "双冲": 2, "缺行": 3, "六亲": 4,
             "全阳": 5, "全阴": 5, "神煞": 6}
    cand = [x for x in items if x["w"] >= 2]
    if not cand:
        sub = [x for x in items if x["w"] == 1]
        return {"has": False, "near": sub,
                "say": "本造未见哪一处压倒性地重——这本身是一种结构：无大病，亦无大药。"
                       "批此类命，不可硬找「一句话定调」，宁可分项说、按运说。"}
    cand.sort(key=lambda x: (-x["w"], order.get(x["tag"], 9)))
    top = cand[0]
    rest = [x for x in items if x is not top and x["w"] >= 2][:3]
    return {"has": True, "top": top, "all": cand, "rest": rest,
            "say": "本造最要紧一处在「%s」：%s" % (top["name"], top["say"])}


# ══════════════════════════ 四、用神落定 ══════════════════════════
def yongshen_ruling(a, f):
    """五级取用，取到即止——梁氏次序不是逐级全看，是「上面定了，下面不谈」。"""
    wy = a.get("wuyong") or []
    lines, decided = [], None
    for x in wy:
        lv, nm, this, use = x["lv"], x["name"], x["this"], x["use"]
        if decided is not None and lv > decided:
            lines.append({"lv": lv, "name": nm, "this": this,
                          "verdict": "不谈（第 %d 级已定）" % decided, "closed": True})
            continue
        if x.get("use") and decided is None:
            decided = lv
            lines.append({"lv": lv, "name": nm, "this": this, "verdict": "取用", "closed": False})
        else:
            if lv == 3:
                this = "病药之「病」指克月令之六神，不是五行缺；本盘月令无克之者，第 3 级不取"
            lines.append({"lv": lv, "name": nm, "this": this,
                          "verdict": "不取（未见其病）" if lv == 3 else "不适用", "closed": False})
    return {"lines": lines, "decided": decided}


# ══════════════════════════ 五、断语素材 ══════════════════════════
TOPIC_ORDER = ["性情", "婚姻", "财官", "子息", "六亲", "疾病寿元", "大运", "岁运流年"]

# 元语言／考据／体例类 theme——不是断语，混进六亲节就是废话
META_THEME = ("序言", "版本", "学命", "体例", "术语", "自省", "限度", "精度",
              "改版", "作者", "考据", "取法", "泛论", "细论", "分列", "逐项",
              "不以", "相反", "为主", "为星", "六亲星全不见")
# 十神类别 → 本盘计数
GODSET = {"财": ["正财", "偏财"], "官杀": ["正官", "七杀"], "官": ["正官", "七杀"],
          "印": ["正印", "偏印"], "食伤": ["食神", "伤官"], "比劫": ["比肩", "劫财"]}
GAN = "甲乙丙丁戊己庚辛壬癸"
NEG_RE = None


def _neg_re():
    global NEG_RE
    if NEG_RE is None:
        import re
        NEG_RE = re.compile(r"(四柱|命中|八字|全|原局)?(无|不见|未有|不现|缺)"
                            r"(财|官杀|官|印|食伤|比劫|正官|七杀|正财|偏财|正印|偏印)")
    return NEG_RE


def _fits(r, a):
    """本盘核对：这条断语的前提，在本命到底成不成立。

    宁可少给一条，不可给一条与本盘相反的话——批命最忌「材料对、前提错」。
    只作否证（能证明不成立就剔），不作证成。
    """
    import re
    txt = (r.get("normalized_statement") or "") + (r.get("theme") or "")
    theme = r.get("theme") or ""
    day = a["pillars"][2][0]
    g = a["gender"]
    tg = a["ten_gods"]

    # ① 元语言／体例条目：讲「怎么讲」，不讲「命主怎样」
    if any(k in theme for k in META_THEME):
        return False
    # ② 日主不符：「甲日夏月……」而本盘非甲日
    days = set(re.findall(r"([%s])日(?:主|干|人)?" % GAN, txt))
    if days and day not in days:
        return False
    # ③ 性别不符
    if g == "男" and ("女命" in txt or "夫星" in txt) and "男命" not in txt:
        return False
    if g == "女" and "男命" in txt and "女命" not in txt:
        return False
    # ④ 「四柱无财」而本盘财透 —— 前提正相反
    for m in _neg_re().finditer(txt):
        kind = m.group(3)
        gods = GODSET.get(kind)
        if gods and sum(tg.get(x, 0) for x in gods) > 0:
            return False
    # ⑤ 「X坐Y」而本盘无一柱天干为 X、地支本气为 Y
    for x, y in re.findall(r"([正偏七]?[财官印食比劫杀伤]{1,2})坐([正偏七]?[财官印食比劫杀伤]{1,2})", txt):
        ok = False
        for row in a["expanded"]:
            if row["stem_tg"] == x and row["hidden"] and row["hidden"][0]["tg"] == y:
                ok = True
                break
        if not ok:
            return False
    # ⑥ 柱位十神核对：「月上偏印」「日支正财」之类，本盘该柱是否真是这个十神
    for pos, where, god in re.findall(
            r"([年月日时])(上|干|支|柱)([正偏]?[财官印食比劫杀伤]{1,2})", txt):
        idx = POS.index(pos)
        row = a["expanded"][idx]
        if where in ("上", "干"):
            actual = row["stem_tg"]
        elif where == "支":
            actual = row["hidden"][0]["tg"] if row["hidden"] else ""
        else:
            actual = {row["stem_tg"], row["hidden"][0]["tg"] if row["hidden"] else ""}
        if isinstance(actual, set):
            if god not in actual:
                return False
        elif actual != god:
            return False
    # ⑦ 「俱见／并见」而本盘数不足；言「天干」者须真透在干上
    if re.search(r"俱见|并见|重见", txt):
        m = re.search(r"(?:俱见|并见|重见)([正偏]?[财官印食比劫杀伤]{1,3})", txt)
        kind = m.group(1) if m else ""
        gods = GODSET.get(kind) or ([kind] if kind else [])
        if "天干" in txt or "干上" in txt:
            stem_gods = [row["stem_tg"] for i, row in enumerate(a["expanded"]) if i != 2]
            n = sum(1 for x in stem_gods if x in gods) if gods else len(
                [x for x in stem_gods if x != "日主"])
            if n < 2:
                return False
        elif sum(1 for v in tg.values() if v >= 1) < 3:
            return False
    # ⑧ 程度语核对：「财旺」「比劫重」是量判，本盘量不到就不成立
    for kind, _tai, _word in re.findall(
            r"(财|官杀|官|印|食伤|比劫|伤官|七杀|正官|日主)星?(太)?(旺|重|盛|强|多)", txt):
        gods = GODSET.get(kind) or [kind]
        lvl, _ = god_strength(a, gods)
        if lvl < 2.0:
            return False
    # ⑨ 计数式：「二辛」「三甲」——本盘数不到就不成立
    for num, gan in re.findall(r"([二三两])([%s])(?![%s])" % (GAN, GAN), txt):
        need = {"二": 2, "两": 2, "三": 3}[num]
        if len(re.findall(gan, "".join(a["pillars"]))) < need:
            return False
    # ⑩ 「带马」「见驿马」而本盘无驿马
    if re.search(r"驿马|带马", txt) and not a.get("yima"):
        return False
    # ⑪ 「无根」「全无根气」而本盘有根
    if re.search(r"无根|不承祖业|无祖业", txt) and a["xingtai"]["heavy_roots"] > 0:
        return False
    # ⑫ 定义句（「X 为 Y」式），不是断语，进六亲节只是废话
    if re.search(r"为(妻|夫|子|女|子女|母|父|侧室|星|用神|忌神)", theme):
        return False
    if re.search(r"(即|就是|故|是以|所谓)[^。]{0,14}为(子女|妻|夫|母|父|子星)", txt):
        return False
    return True


def _clip(s, n=110):
    s = (s or "").strip().replace("\n", " ")
    if len(s) <= n:
        return s
    cut = s[:n]
    for ch in ("；", "。", "，", "、"):  # 尽量断在句读处
        p = cut.rfind(ch)
        if p >= n * 0.55:
            return cut[:p] + "……"
    return cut + "……"


def _empty_note(key, gender, has_extra=False):
    """某一节检索不到可用之条时，按节、按性别说实话——不套同一句。

    旧稿把「财官仅 8 条皆男命妻妾论」一句套到婚姻、子息两节，是错的：
    婚姻全库 68 条、子息 20 条，条数不缺，缺的是「条件未结构化」与「女命子息未收」。
    说错比不说更坏——来客会以为原书无此论，其实是本器接不上。
    """
    def cnt(topic, scope=None):
        return sum(1 for r in A.RULES
                   if (r.get("topic") or "") == topic
                   and (scope is None or (r.get("scope") or "通用") == scope))

    if key == "spouse":
        if gender == "女":
            body = ("婚姻一门全库 %d 条，其中女命论夫 %d 条——这一批的条件写在叙述里"
                    "（夫星入库、合杀留官、财居专位之类），未抽成可比对的触发标签，"
                    "本器因此一条也判不出。**这不是本盘无婚姻，是这一门还没接上检索。**"
                    "本节改以 4.1 的星宫四项为主：星之有无、官杀混杂、夫宫坐煞、星之透藏。"
                    % (cnt("婚姻"), cnt("婚姻", "女命")))
        else:
            body = ("婚姻一门全库 %d 条，男命妻财一路 %d 条；本器按标签逐条比对，"
                    "本盘一条未对上。本节以 4.1 的星宫四项为主，不补通行说法。"
                    % (cnt("婚姻"), cnt("婚姻", "男命")))
    elif key == "child":
        if gender == "女":
            body = ("子息一门全库 %d 条，**全为男命**（男以财或官杀为子星）。"
                    "女命子息从食伤与子女宫看，本包尚未收成条——这是**缺库，不是本盘无子**。"
                    "本节只列 4.1 的子星与子女宫两行，断语一条也不补。" % cnt("子息"))
        else:
            body = ("子息一门全库 %d 条，皆男命；其条件多为「日主旺衰」「运岁三会」一类，"
                    "本盘一条未对上。本节只列 4.1 的子星与子女宫，不补通行说法。"
                    % cnt("子息"))
    elif key == "wealth":
        body = ("**「财官」一类全库仅 %d 条，且皆男命妻妾论**，本节不取。"
                "财与事业的料改由上面的乙轨出——明暗、通根、盖财三处都是可算的；"
                "仍无者，是这一造在财上本无特殊结构，不是无财。" % cnt("财官"))
    else:
        body = "本节未检索到可用之条。"
    if has_extra:
        body += "上列乙轨诸条，即为本节可落笔之处。"
    return "> " + body


def material(a, topic, limit=4, prefer=(), theme_kw=(), deny=()):
    """从命盘命中的规则里，按主题取断语素材。

    三道筛：topic 对上 → 本盘前提成立（_fits）→ 与本盘字面贴得近者优先。
    prefer 给 rule_id 前缀偏好（男命六亲优先 R-ML／R-XP，女命优先 R-X13）。
    """
    hits = a.get("rule_hit") or []
    chars = set(a["pillars"][2]) | set("".join(a["pillars"])) | set(a["ten_gods"])
    out = []
    for r, _miss in hits:
        if r.get("topic") != topic:
            continue
        if theme_kw and not any(k in (r.get("theme") or "") for k in theme_kw):
            continue
        txt = r.get("normalized_statement") or r.get("rule_text") or ""
        if len(txt) < 8:
            continue
        if deny and any(k in txt for k in deny):
            continue
        if not _fits(r, a):
            continue
        score = sum(2 for c in chars if c and c in txt)
        if r.get("attribution_type", "").startswith("梁氏明确判断"):
            score += 2
        if r.get("confidence") == "高":
            score += 1
        if prefer and r["rule_id"].startswith(tuple(prefer)):
            score += 3
        out.append((score, r["rule_id"], _clip(txt), r.get("theme", "")))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out[:limit]


def material_gods(a, limit=4):
    """性情一节的补料：只取「此人如何」的取象。

    心性库（xingqing.csv）已经是这一节的主料，这里只补它讲不到的**纠误与例外**，
    如「乙日见甲不作劫财」「伤官见官须看合」。凡涉及某位六亲如何者（离婚、克子、
    祖产、寿元）一律不取——那些归 4.2–4.7，混进来就是串门。
    """
    hits = a.get("rule_hit") or []
    bad_theme = ("婚姻", "妻", "夫", "子息", "祖产", "六亲", "忌神", "喜神", "格局",
                 "真义", "入库", "合正官", "合偏财", "见官", "取干", "论式", "诗诀",
                 "壽元", "寿元", "四法", "驿马", "带马", "別法", "三刑", "克子", "伤夫")
    bad_txt = ("为文星", "主妻", "伤妻", "子女", "祖产", "离婚", "分居", "克子", "伤夫",
               "头胎", "婚", "二度", "再婚")
    good_txt = ("性格", "心性", "为人", "性情", "脾气", "纠误", "不作", "不忌", "反作",
                "聪明", "刚", "柔", "含蓄", "急躁")
    out = []
    for r, _m in hits:
        if r.get("topic") not in ("十神", "实务杂项"):
            continue
        theme = r.get("theme", "")
        txt = r.get("normalized_statement") or ""
        if len(txt) < 10 or not _fits(r, a):
            continue
        if any(b in theme for b in bad_theme) or any(b in txt for b in bad_txt):
            continue
        if not any(k in txt for k in good_txt):
            continue
        out.append((theme, _clip(txt, 120)))
    return out[:limit]


# ══════════════════════════ 六、大运 ══════════════════════════
HARD = [("十干败亡", "最硬的一条：运干与本命日主成「绝」位者，此十年不作大事。"),
        ("墓库", "四库互换，只四个月生人有。入墓之运，事体停滞，须看冲开。"),
        ("冲提", "冲月令为冲提，十年之中前五年最紧。"),
        ("接角", "运与命接角，换运之交，事前事后两截，不可连读。"),
        ("空亡", "运落旬空，虚而不实，宜守不宜进。")]


# ══════════════════════════ 五·补、星宫合参 ══════════════════════════
# 六亲断法不是「有这条规则就断」，是「星与宫两头合看」。本节把两头都摊开：
# 星在哪、宫怎样、二者相合主什么。信号由结构算出（可核），说法取梁氏常法。
def _has(a, gods):
    return sum(a["ten_gods"].get(g, 0) for g in gods)


def _tou(a, gods):
    """透干者（年／月／时）。"""
    out = []
    for i, row in enumerate(a["expanded"]):
        if i != 2 and row["stem_tg"] in gods:
            out.append(POS[i])
    return out


def _cang(a, gods):
    """藏支者。"""
    out = []
    for row in a["expanded"]:
        for h in row["hidden"]:
            if h["tg"] in gods:
                out.append("%s支%s" % (row["pos"], h["stem"]))
                break
    return out


MU_OF = {"木": "未", "火": "戌", "金": "丑", "水": "辰"}   # 土无库
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
BEI_SHENG = {v: k for k, v in SHENG.items()}


def god_elem(day, god):
    """十神 → 五行。日主五行加生克关系反推。"""
    de = STEM_ELEM.get(day)
    if not de or not god:
        return None
    rel = ELEM_OF_GOD.get(god)
    return {"同我": de, "我生": SHENG.get(de), "我克": A.KE.get(de),
            "克我": BEI_SHENG.get(de), "生我": None}.get(rel) if rel != "生我" \
        else {v: k for k, v in A.KE.items()}.get(de)


def _mu(a, gods):
    """星落本库才算入库：木归未、火归戌、金归丑、水归辰。

    见辰戌丑未就计「入库」是通行本的懒法；梁氏讲归库，指的是**本行之库**。
    """
    day = a["pillars"][2][0]
    out = []
    for god in gods:
        mu = MU_OF.get(god_elem(day, god) or "")
        if not mu:
            continue
        for row in a["expanded"]:
            if row["branch"] == mu and any(h["tg"] == god for h in row["hidden"]):
                out.append("%s%s（%s）" % (row["pos"], row["branch"], god))
    return out


def _gong_state(a, pos_idx):
    """某一柱（宫）的状态：被不被冲、坐什么十神、落不落神煞。"""
    row = a["expanded"][pos_idx]
    chonged = []
    for p1, p2 in _chong_pairs(a):
        if POS[pos_idx] in (p1, p2):
            chonged.append(p2 if p1 == POS[pos_idx] else p1)
    ss = [s.get("name", "") for s in a["shensha"]
          if s.get("hits") and s.get("key") == row["branch"]]
    return {"pos": POS[pos_idx], "pillar": row["pillar"],
            "stem_tg": row["stem_tg"],
            "branch_tg": row["hidden"][0]["tg"] if row["hidden"] else "",
            "chong": chonged, "shensha": ss}


def _chong_pairs(a):
    out = []
    for r in a["relations"]:
        if "冲" not in r["kind"]:
            continue
        ms = r.get("members") or []
        ps = []
        for m in ms:
            if isinstance(m, (list, tuple)) and m and str(m[0]) in POS:
                ps.append(str(m[0]))
            elif isinstance(m, str) and m in POS:
                ps.append(m)
        if len(ps) == 2:
            out.append((ps[0], ps[1]))
    return out


def star_palace(a):
    """星宫合参：每类六亲给一组「信号 → 梁氏怎么讲」。不替批者下断，只把牌摆开。"""
    g = a["gender"]
    f_day = a["pillars"][2]
    blocks = []
    chong = _chong_pairs(a)

    def bloc(title, rows, note=""):
        blocks.append({"title": title, "rows": rows, "note": note})

    # ── 妻／夫
    if g == "男":
        star, other = ["正财", "偏财"], "妻"
        rows = []
        n = _has(a, star)
        tou, cang = _tou(a, star), _cang(a, star)
        rows.append(("妻星之有无", "财星共 %d 处%s" % (n, "（透 " + "／".join(tou) + "）" if tou else "（皆藏）"),
                     "四柱无财则以财为妻星、作婚迟论；本盘财星不缺，此一层不成立" if n else
                     "梁氏：四柱无财，财即妻星，作「婚迟」或「妻缘淡」论，不作「无妻」论"))
        if _has(a, ["正财"]) and _has(a, ["偏财"]):
            rows.append(("正偏并见", "正财偏财同见", "梁氏：正偏财叠合，妻妾有暗——主婚姻中易有第三方或前后反复；只作倾向，不作确断"))
        mu = _mu(a, star)
        if mu:
            rows.append(("妻星归库", "落 " + "／".join(mu), "梁氏：妻星归库，忌早婚；早婚者多不终。须看运冲开库"))
        gong = _gong_state(a, 2)
        rows.append(("妻宫（日支）", "%s，本气%s" % (gong["pillar"], gong["branch_tg"]),
                     {"偏印": "日坐偏印者，夫妻不恩爱、彼此少信，有孤独之感",
                      "正印": "日坐正印者，妻厚重而近于母性，家中主事者多为妻",
                      "正财": "日坐正财，妻贤而助，然亦主自身受妻管",
                      "偏财": "日坐偏财，有二种以上财源，感情上亦易另起",
                      "正官": "日坐正官，妻端方而约束多",
                      "七杀": "日坐七杀，妻性刚，夫妻间多压强",
                      "食神": "日坐食神，妻随和而善持家",
                      "伤官": "日坐伤官，妻聪敏而好胜，言语上易伤人",
                      "比肩": "日坐比肩，夫妻如友，然亦易分财",
                      "劫财": "日坐劫财，妻宫被夺，婚事宜缓"}.get(gong["branch_tg"], "宫位十神主妻之性情，须再细看")))
        if gong["chong"]:
            rows.append(("妻宫被冲", "日支被 %s 冲" % "／".join(gong["chong"]),
                         "梁氏：日月双冲为常法之最重，主婚宫不安；年日双冲主本不和，纵富贵亦不久"))
        if gong["shensha"]:
            rows.append(("妻宫见煞", "、".join(gong["shensha"]),
                         "神煞落夫妻宫，只记名目；不克日主者不作祸福之断"))
        if _tou(a, ["比肩", "劫财"]):
            rows.append(("比劫夺财", "比劫透 " + "／".join(_tou(a, ["比肩", "劫财"])),
                         "梁氏：比劫克财为男命婚姻之忌，主感情反复、财为他人所分"))
        bloc("妻（男命以财为妻）", rows)
    elif g == "女":
        star = ["正官", "七杀"]
        rows = []
        n = _has(a, star)
        tou, cang = _tou(a, star), _cang(a, star)
        rows.append(("夫星之有无", "官杀共 %d 处%s" % (n, "（透 " + "／".join(tou) + "）" if tou else "（皆藏）" if n else ""),
                     "梁氏：女命先观夫子二星。夫星不见者，作「夫缘淡」论，不作「无夫」论" if not n else
                     "夫星有著落，再看其旺衰与有无混杂"))
        if _has(a, ["正官"]) and _has(a, ["七杀"]):
            rows.append(("官杀混杂", "正官、七杀并见",
                         "梁氏：官杀混杂为夫星通忌，然逐月有开禁；合杀留官、合官留杀是通法，须看有无合"))
        mu = _mu(a, star)
        if mu:
            rows.append(("夫星归库", "落 " + "／".join(mu),
                         "梁氏：夫星入库为第一关切，主夫缘迟、或夫体弱，须看冲开"))
        gong = _gong_state(a, 2)
        FUGONG = {"伤官": "伤官坐夫宫，女命最忌——主夫受制、口舌多，婚事难顺；须看有无印制伤",
                  "食神": "食神坐夫宫，夫性和缓，然女主内而少威",
                  "正官": "正官坐夫宫，夫端方，宫星得位者婚稳",
                  "七杀": "七杀坐夫宫，夫性刚，夫妻间多压强",
                  "正印": "正印坐夫宫，夫厚重，然近于长辈之亲",
                  "偏印": "偏印坐夫宫，夫妻少信，有孤独之感",
                  "正财": "正财坐夫宫，夫务实，家中以财为纲",
                  "偏财": "偏财坐夫宫，夫善交际而心易分",
                  "比肩": "比肩坐夫宫，夫妻如友，亦主各持己见",
                  "劫财": "劫财坐夫宫，夫宫被夺，婚事宜缓"}
        rows.append(("夫宫（日支）", "%s，本气%s" % (gong["pillar"], gong["branch_tg"]),
                     FUGONG.get(gong["branch_tg"], "日支为夫宫，宫位十神主夫之性情；宫被冲则婚宫不安")))
        if gong["chong"]:
            rows.append(("夫宫被冲", "日支被 %s 冲" % "／".join(gong["chong"]), "婚宫动，主聚少离多或中途生变"))
        bloc("夫（女命以官杀为夫）", rows)

    # ── 子息
    child = ["正官", "七杀"] if g == "男" else ["食神", "伤官"]
    rows = []
    n = _has(a, child)
    rows.append(("子星之有无", "共 %d 处" % n,
                 "梁氏：子星不见者，主子女缘薄或得子迟，运岁见子星旺乡则可补" if not n
                 else "子星有著落"))
    shi = _gong_state(a, 3)
    rows.append(("子女宫（时柱）", "%s，天干%s、支本气%s" % (
        shi["pillar"], shi["stem_tg"], shi["branch_tg"]),
        "时柱为归宿亦为子息之宫。时干伤官者，晚年子女不在身边（非子女有损）"
        if shi["stem_tg"] == "伤官" else "时柱状态须与子星合看：星好宫破者，得子而难养"))
    if shi["chong"]:
        rows.append(("子息宫被冲", "时支被 %s 冲" % "／".join(shi["chong"]),
                     "时支为归宿，被冲者晚运多动；月时双冲主迭次起倒"))
    if _mu(a, child):
        rows.append(("子星入库", "落 " + "／".join(_mu(a, child)), "子星归库，主得子晚"))
    bloc("子息", rows)

    # ── 财
    rows = []
    n = _has(a, ["正财", "偏财"])
    rows.append(("财星", "共 %d 处" % n, "财为养命之源，先看有无，再看能不能守"))
    if _tou(a, ["比肩", "劫财"]) and n:
        rows.append(("比劫夺财", "比劫透干而财星亦见", "梁氏：偏财遇劫财，主田园破尽、伤妻损妾；比肩夺财则以性格论，主感情与钱财两伤"))
    if _tou(a, ["正官", "七杀"]) and n:
        rows.append(("财生官", "财、官俱透", "财生官，官护财：有约束之财，走得稳；然官旺则身受制"))
    bloc("财", rows)

    # ── 禄与事业
    rows = []
    off = _tou(a, ["正官", "七杀"])
    rows.append(("官杀", "透 " + "／".join(off) if off else "不透",
                 "官杀为名位。透而有制者，可任事；无制者，任事而易折" if off else
                 "官杀不透，名位须由运来；不在本命先断"))
    if _tou(a, ["食神", "伤官"]) and off:
        rows.append(("食伤制杀", "食伤与官杀俱透",
                     "食神制杀则贵，伤官见官则祸福在引归时支之旺绝——坐旺为祸、坐绝无妨"))
    bloc("禄与事业", rows)

    # ── 寿元
    rows = []
    rows.append(("日主之根", "重根 %d 处" % a["xingtai"]["heavy_roots"],
                 "有根者立得住，无根者漂浮；然原文亦言「未必贫贱」，只断根基不断寿数"))
    tp = th_presence(a, facts(a))
    absent = [ch for t in tp for ch, m, _ in t["rows"] if m == "全无"]
    if absent:
        rows.append(("调候之字", "「%s」命中全无" % "、".join(absent),
                     "调候之字不见，看运来补；补不上者，一生气候少一味"))
    bloc("寿元与根基", rows, "梁氏批寿只判长短，不判年岁——不得写具体岁数，不得写「某年有大限」。")
    return blocks


def dayun_notes(a):
    dy = a.get("dayun") or []
    rows = []
    for d in dy:
        gz = d.get("gz") or d.get("pillar") or ""
        tags = []
        for k in ("败亡", "墓", "冲提", "接角", "空"):
            for key, val in d.items():
                if key.endswith("_note") and val and k in str(val):
                    tags.append(_clip(str(val), 60))
                    break
        rows.append({"gz": gz, "age": d.get("age", ""), "raw": d})
    return rows


def _dy_hits(a, gz):
    for d in a.get("dayun") or []:
        if d.get("gz") == gz:
            return d.get("hits") or []
    return []


# ══════════════════ 三之二、十神定位（财官派 · 乙轨） ══════════════════
# 为什么单立一节
#   梁氏批命是两套分批列叙（R-MF-001）：甲 文人式（调候／格局／喜忌，以八字本身为主），
#   乙 财官派（十神定位，散用于流年与实务）。此前本器只有甲轨——一到六节全是
#   调候→格局→用神，乙轨一条没接，故「财、事业、寿元」诸项与梁氏呼应率为零。
#   R-X13-077 更直白：论命不必以调候格局为第一优先，当以十神定位为入式。
#   两轨分列，不合成一套；乙轨只摆可机械核的牌（柱位×十神、坐、数量、通根）。
def shishen_section(a, S):
    L = []
    P = L.append
    cols = SP.columns(a)
    P("### 3.2 十神定位（财官派入式）")
    P("")
    P("> 上节是甲轨（调候、格局、用神）；本节是乙轨。梁氏批一个八字用**两套层次分别批、"
      "分批列叙**，不混成一套。乙轨的入口不是用神，是十神落点：")
    P("> 同一位十神，落在年、月、日、时，所断之事不同——年上主早年与家世，月上主青年与自身，"
      "日支为配偶宫，时上主晚年与子女。")
    P("")
    P("| 柱 | 干支 | 年段 | 天干 | 支本气 | 支中余气 |")
    P("|---|---|---|---|---|---|")
    for c in cols:
        rest = "、".join("%s%s" % (x["stem"], x["god"]) for x in c["hidden"][1:]) or "—"
        P("| %s | %s | %s | %s | %s | %s |"
          % (c["pos"], c["pillar"], c["age"],
             "日主" if c["stem_god"] == "日主" else "%s（%s）" % (c["stem"], c["stem_god"]),
             "%s（%s）" % (c["branch"], c["branch_god"]) if c["branch_god"] else "—",
             rest))
    P("")

    hits, seen = [], set()
    for e in SP.sits(a) + SP.entries(a):
        key = (e["rule"], e["pos"], e["kind"] if "kind" in e else "")
        if key in seen:
            continue
        seen.add(key)
        hits.append(e)
    if hits:
        P("**乙轨所得**")
        P("")
        for e in hits:
            P("- %s" % e["text"])
        P("")
        P("> 乙轨不出吉凶方向，只出「此人此事落在哪一段、以何种方式成立」。"
          "方向仍归甲轨（调候格局）与运。")
        P("")
    else:
        P("**乙轨无可断之条**：本盘无自坐同神、无七杀相叠、无比劫分柱之象，"
          "十神散得开——这本身是一种结构（R-MF-024：吉命不必件件有说）。"
          "命书里以一句话带过，不硬凑。")
        P("")

    ids = []
    for e in hits:
        if e["rule"] not in ids:
            ids.append(e["rule"])
    return {"lines": L, "ids": ids, "n": len(hits)}


def cai_view(a):
    """财星的三处可算：明暗（R38）、通根时支（R38）、盖财（R234）。

    4.3 此前 59 盘全空，根因是 `topic=财官` 全库仅 8 条且全为男命妻妾论。
    财星定位本不必靠那 8 条——梁氏断财，先分明暗与通根，这两处都算得出来。
    """
    out = []
    exp = a["expanded"]
    cai = ("正财", "偏财")
    tou = [(r["pos"], r["stem"], r["stem_tg"]) for i, r in enumerate(exp)
           if i != 2 and r["stem_tg"] in cai]
    hour = exp[3]
    hour_root = [h["tg"] for h in hour["hidden"]]
    if tou:
        rooted_hour = [g for p, s, g in tou if g in hour_root]
        if rooted_hour:
            out.append({"rule": "R38",
                        "text": "财透天干而通根至时支——R38：偏财通根时支者，一辈子都有钱；"
                                "财在时支有根，是「晚年仍在财上」之象"})
        else:
            out.append({"rule": "R38",
                        "text": "财只在天干（%s）——R38：财在天干为「明」，人皆见之；"
                                "仅明而无根者，是别人认为你有钱，未必真有钱"
                                % "、".join("%s干%s" % (p, s) for p, s, _g in tou)})
    else:
        hidden_cai = [r["pos"] for i, r in enumerate(exp)
                      if any(h["tg"] in cai for h in r["hidden"])]
        if hidden_cai:
            out.append({"rule": "R7",
                        "text": "财只藏于支（%s）而不透干——R7：在支为「暗」，隐而不显；"
                                "财暗者，进财不张扬，亦不易被外人算计" % "、".join(hidden_cai)})
    for i, r in enumerate(exp):
        if i == 2:
            continue
        if r["stem_tg"] == "比肩" and any(h["tg"] in cai for h in r["hidden"]):
            out.append({"rule": "R234",
                        "text": "%s柱比肩盖财（%s坐%s）——R234：财星之上坐比肩，不论财多旺，"
                                "最多只拿到一半，须先付出"
                                % (r["pos"], r["stem"], a["pillars"][i][1])})
    return out


def health_view(a):
    """寿元疾病之可算四条。

    4.7 此前 59 盘全空，根因是「疾病寿元」九条未接进检索。九条之中四条可以机械核：
    月时官杀混杂（R-X13-014）、庚日冬月无火（R-XP-045）、男命甲乙伤官多而乏水
    （R-ML-022）、男命枭重身弱（R-ML-057）。另有三条须运（R-ML-029／060／066），
    一条是学命门径（R-X13-079）本不属病，一条是分寸（R-XP-046：无显明症兆不出断句）。
    故本节只出四条，出不来就留白——「无显明症兆」正是梁氏许可的留白。
    """
    out = []
    exp = a["expanded"]
    day = a["pillars"][2][0]
    g = a["gender"]
    all_stems = "".join(r["stem"] for r in exp)
    all_br = "".join(a["pillars"][i][1] for i in range(4))
    n, _w = A.god_pos_count(exp)
    # R-X13-014 月干时干官杀混杂
    m_god, h_god = exp[1]["stem_tg"], exp[3]["stem_tg"]
    if {m_god, h_god} == {"正官", "七杀"}:
        out.append({"rule": "R-X13-014",
                    "text": "月干%s、时干%s，官杀混杂于月时两干——R-X13-014：不论男女，"
                            "皆作体弱多病" % (m_god, h_god)})
    # R-XP-045 庚日冬月无火
    if day == "庚" and a["pillars"][1][1] in ("亥", "子", "丑") and not any(
            x in all_stems + all_br for x in "丙丁巳午"):
        out.append({"rule": "R-XP-045",
                    "text": "庚日生于%s月，四柱无丙丁巳午——R-XP-045：金寒无火暖局，主肾疾；"
                            "此条只言「主肾疾」，不言轻重" % a["pillars"][1][1]})
    # R-ML-022 男命甲乙伤官多乏水
    if g == "男" and day in ("甲", "乙") and n.get("伤官", 0) >= 2 and not any(
            x in all_stems + all_br for x in "壬癸亥子"):
        out.append({"rule": "R-ML-022",
                    "text": "男命%s日，伤官 %d 位而四柱乏水——R-ML-022：主痨喘，"
                            "或中风不语" % (day, n["伤官"])})
    # R-ML-057 男命枭重身弱
    if g == "男" and n.get("偏印", 0) >= 2 and not a["xingtai"]["heavy_roots"]:
        out.append({"rule": "R-ML-057",
                    "text": "男命偏印 %d 位而日主无重根——R-ML-057：枭神重重而身弱，"
                            "多主痨病" % n["偏印"]})
    return out


TOMB_OF = {"木": "未", "火": "戌", "金": "丑", "水": "辰", "土": "辰"}


def marriage_struct(a):
    """婚姻之结构三条：星之有无、星之入库、宫之受冲。

    梁氏断婚姻，先看星宫（R-SZ-047）：星论有无、宫论亲疏。这三处都算得出来，
    此前却只在 4.1 摆牌、未落 4.2 的断——故「婚姻」一条的呼应率卡在六成。
    """
    out = []
    exp = a["expanded"]
    g = a["gender"]
    star = ("正财", "偏财") if g == "男" else ("正官", "七杀")
    name = "妻星" if g == "男" else "夫星"
    tou = [r["pos"] for i, r in enumerate(exp) if i != 2 and r["stem_tg"] in star]
    hid = [(r["pos"], h) for i, r in enumerate(exp) for h in r["hidden"] if h["tg"] in star]
    if not tou and not hid:
        out.append({"rule": "R-SZ-047",
                    "text": "%s不见（原局%s俱无）——星不见为缘浅；不是无婚，是%s不显，"
                            "须看运来补" % (name, "财" if g == "男" else "官杀", name)})
    elif not tou:
        tombs = [(p, h["stem"]) for p, h in hid
                 if TOMB_OF.get(A.STEM_ELEM.get(h["stem"], "")) == a["pillars"][POS.index(p)][1]]
        if tombs:
            out.append({"rule": "R-SZ-047",
                        "text": "%s藏而不透，且入%s之库（%s）——星入库者，"
                                "主婚缘迟、或对方不显于外；须看冲开之运"
                                % (name, "／".join(sorted({A.STEM_ELEM[t[1]] for t in tombs})),
                                   "、".join("%s支%s" % t for t in tombs))})
    for rel in (a.get("relations") or []):
        if "冲" not in (rel.get("kind") or ""):
            continue
        ps = [str(x) for x in (rel.get("positions") or [])]
        if any("日" in x for x in ps):
            out.append({"rule": "R-SZ-046",
                        "text": "夫妻宫（日支）受冲（%s）——宫被冲，主婚有变动；"
                                "冲之为感受，不言必离" % "、".join(ps)})
            break
    xt = a.get("xingtai") or {}
    if g == "女" and xt.get("all_yin"):
        out.append({"rule": "R-XP-005",
                    "text": "四柱全阴——R-XP-005：全阴不利女。阴气偏重，夫星不显，"
                            "婚事宜迟不宜早"})
    elif g == "男" and xt.get("all_yang"):
        out.append({"rule": "R-XP-005",
                    "text": "四柱全阳——R-XP-005：全阳不利男。阳气偏重，妻星难近，"
                            "夫妻之间宜各留余地"})
    return out


def marriage_sp(a):
    """婚配之乙轨：R-MF-040（壬癸女命杀印相生）与 R-MF-035（七杀坐七杀）。"""
    out = marriage_struct(a)
    for e in SP.sits(a):
        if e["rule"] == "R-MF-035":
            out.append({"rule": "R-MF-035", "text": "婚配一层另有一处：" + e["text"]})
    day = a["pillars"][2][0]
    if a.get("gender") == "女" and day in ("壬", "癸"):
        exp = a["expanded"]
        fu = [r["pos"] for i, r in enumerate(exp)
              if (i != 2 and r["stem_tg"] in ("正官", "七杀"))
              or any(h["tg"] in ("正官", "七杀") for h in r["hidden"])]
        if fu:
            shi = [r["pos"] for i, r in enumerate(exp)
                   if i != 2 and r["stem_tg"] == "食神"]
            out.append({"rule": "R-MF-040",
                        "text": "壬癸日主之女命以戊己土为夫（官杀），见夫星于%s——R-MF-040："
                                "因火土同生旺，此类女命皆成杀印相生%s"
                                % ("、".join(sorted(set(fu))),
                                   "；而食神%s出干，原文谓「反而不宜再见食神出干」，"
                                   "伤官见官之外，另有一层克夫之忌" % "、".join(shi) if shi
                                   else "；本盘食神未出干，不犯「再见食神」之忌")})
    return out


def _main_word(r):
    """流年一格的命书短语；无 brief 时退回 kind。"""
    return r.get("brief") or r.get("kind") or ""


def _flat(t):
    """汇总行里去掉内层括号，免得「（冲大运（新起之事））」套两层。"""
    return (t or "").replace("（", "·").replace("）", "")


def liunian_block(a, S):
    """第六节：当前大运之近五年。

    批流年先定运。只在五年里看五年，看到的是五个孤立的干支；先知道这五年落在
    哪一步运、运内第几年、这一步运有没有硬法，年份才有秤可称。
    """
    L = []
    P = L.append
    now = a.get("now")
    years = a.get("liunian") or []

    if not years:
        P("未给流年，本节留空。")
        if now:
            P("")
            P("当前行第 %d 运（%s，%d–%d，虚岁 %d–%d）。加 `--recent 5` 即出这一运的近五年。"
              % (now["n"], now["gz"], now["from"], now["to"],
                 now["age_from"], now["age_to"]))
        elif a.get("dayun"):
            P("")
            P("要批「当前大运近五年」，还缺 `--birth-year` 与 `--start-age`——"
              "不起运岁定不出，就说不清今年在第几运。")
        return L

    # ── 6.1 所行何运
    if now:
        P("### 6.1 所行何运")
        P("")
        P("现行**第 %d 运 %s**（%d–%d，虚岁 %d–%d）；%d 年为运内第 **%d** 年。"
          % (now["n"], now["gz"], now["from"], now["to"], now["age_from"],
             now["age_to"], now["year"], now["idx"]))
        P("")
        hits = _dy_hits(a, now["gz"])
        if hits:
            P("- **本运硬法**：%s" % "；".join(S(h) for h in hits))
        else:
            P("- **本运五硬法俱不犯**：不作大断，按干支与命局之冲合看。")
        ths = [c for c in ((a["th"][0]["value"] if a.get("th") else "") or "") if c in GAN]
        if ths:
            same = now["gz"][0] in ths
            P("- **调候接不接**：本格调候之字为「%s」，运干「%s」%s。"
              % ("、".join(ths), now["gz"][0],
                 "正在其中，这十年气候接得上" if same else "不在其中，这十年气候不由这一字接"))
            P("- 调候到不到，只算「气候」一层。梁氏讲须与格局配属，不是有则吉——"
              "本器只标同异，配属那层留批者裁。")
        P("")
        P("**层次不可乱**：流年第一、大运第二、命局第三。流年有权生克大运与命局，反之无权；"
          "干对干说话、支对支说话，运干再有力也克不到命局之支。")
        P("")
        P("**流年层不论身强弱**：批八字本身可先以身弱论，到流年这一层改以妻财子禄分则为优先，"
          "重点在流月，不在身之强弱——六○年代「身弱不能托财官」在流年层本不是要紧问题。"
          "故本节不再算日主强弱，只算各年落在哪一柱、哪一神。")
        P("")
    elif not all(y.get("dy_n") == 0 for y in years):
        P("> 缺 `--dayun`／`--birth-year`／`--start-age` 之一，只论年、不论运。"
          "下面的年份没有运作背景，只能按命中结构看，不作流年大断。")
        P("")

    # ── 6.2 结构表
    n = len(years)
    sw = "近五年" if n == 5 else "近 %d 年" % n
    multi = len({y.get("dy_n") for y in years if y.get("dy_n")}) > 1   # 窗口跨运
    P("### 6.2 %s结构" % sw)
    P("")
    P("| 年 | 干支 | 虚岁 | 运内 | 主命中（可断） | 只记结构（不作断） |")
    P("|---|---|---|---|---|---|")
    for y in years:
        mm = "、".join(sorted({_main_word(r) for r in y["rows"] if r["main"]})) or "—"
        aux = "、".join(sorted({r["kind"] for r in y["rows"] if not r["main"]})) or "—"
        if y.get("in_dy"):
            pos = ("%s·第%d年" % (y["dayun"], y["in_dy"])) if multi else ("第%d年" % y["in_dy"])
        else:
            pos = "未起运" if y.get("dy_n") == 0 else "—"
        P("| %s | %s | %s | %s | %s | %s |"
          % (y.get("year") or "—", y["gz"], y.get("age") or "—", pos, mm, aux))
    P("")

    # ── 6.3 五年合看
    mains = [y for y in years if y.get("n_main")]
    rest = [y for y in years if not y.get("n_main")]
    P("### 6.3 %s合看" % ("五年" if n == 5 else "%d 年" % n))
    P("")
    if mains:
        P("- **可断之年**（%d 年）：%s" % (len(mains), "；".join(
            "%d %s 见%s" % (y.get("year") or 0, y["gz"],
                            "、".join(sorted({_flat(_main_word(r)) for r in y["rows"] if r["main"]})))
            for y in mains)))
    else:
        P("- 五年之中无一年见主命中——照「流年非每年有事」，这几年不逐年批，只作背景。")
    if rest:
        P("- **无事之年**（%d 年）：%s。不充数，命书里可一笔带过或干脆不提。"
          % (len(rest), "、".join("%d %s" % (y.get("year") or 0, y["gz"]) for y in rest)))

    cy = [y for y in years if any(r["kind"] == "冲运" for r in y["rows"])]
    cz = [y for y in years if any(r["kind"] == "冲柱" for r in y["rows"])]
    if cy:
        P("- **冲运**：%s——冲大运主「新发生之事」，与冲四柱之「旧事重讲」不是一回事。"
          % "、".join("%d %s" % (y["year"], y["gz"]) for y in cy))
    if cz:
        P("- **冲柱**：%s——旧事被拉回重讲，事发在旧处。"
          % "、".join("%d %s" % (y["year"], y["gz"]) for y in cz))

    if now:
        dns = {y.get("dy_n") for y in years if y.get("dy_n")}
        spans = a.get("dayun_spans") or []
        nxt = next((s for s in spans if s["n"] == now["n"] + 1), None)
        if len(dns) > 1:
            P("- **窗口跨运**：这几年里换过运。接角之运，事前事后两截，不可连读——"
              "换运那一年前后，宜分作两段批。")
        elif nxt and years[-1].get("year") and years[-1]["year"] >= nxt["year_from"] - 1:
            P("- **运尾接角**：%d 年为 %s 之末，%d 年交 %s。换运之交称「接角」，"
              "事前事后两截，不可连读。" % (now["to"], now["gz"], nxt["year_from"], nxt["gz"]))
        elif now["idx"] <= 3:
            P("- **运头**：本年在此运前三年内。冲提一类的紧处在前五年，运头尤须留意。")
    elif years and all(y.get("dy_n") == 0 for y in years):
        P("- **尚未起运**：上列各年皆在第一运之先，运未立。运未立则流年只作结构记，"
          "本器不据此下断；起运之年由 `paipan.py` 排，本器不推。")
    P("")

    # ── 6.4 逐年
    P("### 6.4 逐年落笔")
    P("")
    for y in years:
        tag = ""
        if y.get("in_dy"):
            tag = ("，%s 运内第 %d 年" % (y["dayun"], y["in_dy"])) if multi \
                else ("，运内第 %d 年" % y["in_dy"])
        head = "**%s %s**（虚岁 %s%s）" % (y.get("year") or "", y["gz"], y.get("age") or "—", tag)
        P(head)
        P("")
        if not y["rows"]:
            P("- 无结构落点。不占命书一行。")
            P("")
            continue
        if not y["n_main"]:
            P("- 只记结构（%s），无主命中——不批。" % "、".join(sorted({r["kind"] for r in y["rows"]})))
            P("")
            continue
        # 乙轨散用于流年：流年十神对日主是谁，本盘原有几位
        _lg = SP.liunian_god(a, y["gz"])
        _wh = SP.counts(a)["where"]
        P("- 十神：%s 干为%s（本盘%s），%s 支本气为%s（本盘%s）——乙轨以此二神入年，"
          "先问它在本盘原本几位、压在何处，再论此年之事"
          % (y["gz"][0], _lg["stem_god"], "、".join(_wh.get(_lg["stem_god"], [])[:3]) or "原无",
             y["gz"][1], _lg["branch_god"], "、".join(_wh.get(_lg["branch_god"], [])[:3]) or "原无"))
        P("- 看到：%s" % "；".join(S(r.get("text") or r["kind"]) for r in y["rows"] if r["main"]))
        P("- 断：%s" % "；".join(_main_word(r) for r in y["rows"] if r["main"]))
        left = [r for r in y["rows"] if not r["main"]]
        if left:
            P("- 另记（不作断）：%s" % "、".join(sorted({r["kind"] for r in left})))
        # 流月应期（R-MF-018）：月运同途／月运反吟连贯于刑冲运岁者，为运岁最应验之时段
        mm = [m for m in (y.get("months") or []) if m["grade"] == "主变"]
        if mm:
            P("- 应期（流月）：%s——月运同途／月运反吟落在刑冲运岁之中，即运岁最应验之时段；"
              "只标月份与结构，不预判吉凶"
              % "；".join("%s %s" % (m["gz"], m["tag"]) for m in mm))
        P("")
    P("> 落到命书：可断之年各写一段，无事之年一笔带过。年年都写「今年如何」，"
      "是拿流年当小型大运批——四禁里明禁的一条。")
    P("")
    return L



# ══════════════════════════ 七、输出 ══════════════════════════
# 编号特征：既有 R06 这种短的，也有 R-SS-002／T-ORIG-TH01-092／JS-SS-01／NM-TBL-02 这种长的。
ID_PAT = (r"(?:XQ-[A-Z]{2}-\d+|TAB-[A-Z0-9]+(?:-[A-Z0-9]+)*|JS-SS-\d+|NM-TBL-\d+|"
          r"R-[A-Z0-9]+(?:-[A-Z0-9]+)*|T-[A-Z0-9]+(?:-[A-Z0-9]+)*|R\d{1,3})")


def _strip_ids(t):
    """去掉正文里的工程编号。批命看的是理，不是编号；要编号用 --trace。"""
    import re
    if not t:
        return t
    t = re.sub(r"[（(]\s*" + ID_PAT + r"\s*[）)]", "", t)
    t = re.sub(r"(?<![A-Za-z0-9])" + ID_PAT + r"(?![A-Za-z0-9])", "", t)
    t = t.replace("（）", "").replace("()", "")
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"[，、；]\s*[，、；]", "，", t)
    t = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5「『（《])", "", t)
    t = re.sub(r"(?<=[」』）》])\s+(?=[\u4e00-\u9fa5])", "", t)
    t = re.sub(r"——\s*[：:]\s*", "——", t)
    t = re.sub(r"\s*(?:→|-->|=>)\s*", "，", t)
    # 编号删掉后常留「（：主变动…）」这种残壳：整段去掉括号，留内容
    t = re.sub(r"[（(]\s*[：:，、；]\s*([^（）()]{0,60})[）)]", r"\1", t)
    t = re.sub(r"[（(]\s*[：:，、；]\s*", "", t)
    t = re.sub(r"([，、；：])\s*([，、；：])+", r"\1", t)
    return t.strip(" ，、；")


def render(a, trace=False):
    f = facts(a)
    f["where"] = a["where"] if "where" in a else _where_of(a)
    items = ten_items(a, f)
    core = core_conflict(a, items)
    ys = yongshen_ruling(a, f)
    gj = a.get("geju") or {}
    L = []
    P = L.append
    S = (lambda t: t) if trace else _strip_ids

    P("# 批命推演　%s　%s" % ("　".join(a["pillars"]), a["gender"] or "性别未给"))
    P("")
    P("> 按梁氏次序走：十项优先 → 定形态 → 定用神 → 格局顺逆 → 六亲十项 → 大运 → 流年。")
    P("> 每项三段：**看到什么／依什么理／断什么**。本稿是「批命提纲」，不是命书——")
    P("> 命书的行文另循六段体例（已知因／总评／六亲／提要），此处只保证不漏点、不走偏。")
    if trace:
        P("> `--trace` 已开：依据编号随条附注，供批者自核。")
    P("")

    # ── 一、十项
    P("## 一、十项优先（梁氏次序，逐项过）")
    P("")
    P("| # | 项 | 看到什么 | 断到哪一档 |")
    P("|---|---|---|---|")
    for x in items:
        P("| %d | %s | %s | %s |" % (x["no"], x["name"], S(x["seen"]).rstrip("。"), x["grade"]))
    P("")
    P("逐项伸说：")
    P("")
    for x in items:
        P("**%d. %s**　〔%s〕" % (x["no"], x["name"], x["grade"]))
        P("")
        P("- 看到：%s" % S(x["seen"]))
        P("- 依理：%s%s" % (S(x["why"]),
                            _ids_tail("item%d" % x["no"]) if trace else ""))
        P("- 断：%s" % S(x["say"]))
        P("")

    # ── 二、核心矛盾
    P("## 二、此造最要紧的一处")
    P("")
    P(core["say"])
    P("")
    if core.get("rest"):
        P("次一等（同属要处，落笔时须一并带到）：")
        for x in core["rest"]:
            P("- **%s**——%s" % (x["name"], S(x["say"])))
        P("")
    elif core.get("near"):
        P("其余各项只到「倾向」：")
        for x in core["near"][:3]:
            P("- %s——%s" % (x["name"], S(x["say"])))
        P("")

    # ── 三、用神
    P("## 三、用神落定（五级，取到即止）")
    P("")
    P("| 级 | 用神 | 本命对应 | 判 |")
    P("|---|---|---|---|")
    for x in ys["lines"]:
        P("| %d | %s | %s | %s%s |" % (x["lv"], x["name"], S(x["this"]), x["verdict"],
                                        _ids_tail("ys%d" % x["lv"]) if trace else ""))
    P("")
    if ys["decided"]:
        P("第 %d 级已定，其下不谈——这是梁氏的次序，不是省略。"
          "通行批法一上手就判身强弱、再套「身弱不能托财官」，次序正好颠倒。" % ys["decided"])
    P("")

    # ── 三之二、十神定位（乙轨）
    _ss = shishen_section(a, S)
    for line in _ss["lines"]:
        P(S(line))
    if trace:
        P(basis_line("shishen"))
        P("")

    # ── 四、六亲十项
    P("## 四、六亲与实务")
    P("")
    P("> 先摆牌，再落笔。**星宫合参**是梁氏断六亲的骨架：星之有无透藏算一半，")
    P("> 宫之冲合坐煞算另一半，两半合看才成一句断语。下面的「条目补充」只是补料，")
    P("> 牌没摆全，条目不许多列。")
    P("")

    P("### 4.1 星宫合参")
    P("")
    for blk in star_palace(a):
        P("**%s**" % blk["title"])
        P("")
        P("| 信号 | 本盘 | 梁氏怎么讲 |")
        P("|---|---|---|")
        for name, seen, why in blk["rows"]:
            P("| %s | %s | %s |" % (name, seen, why))
        P("")
        if blk.get("note"):
            P("> %s" % blk["note"])
            P("")

    if trace:
        P(basis_line("sp"))
        P("")

    sk = sixkin(a)
    g = a["gender"]
    blocks = [("4.2 条目补充·婚姻", "spouse", "妻星" if g == "男" else "夫星", "婚姻",
               ("R-ML", "R-XP-020"), ("婚", "妻", "夫"), ()),
              ("4.3 条目补充·财与事业", "wealth", "财星", "财官",
               ("R-ML", "R-XP", "R-SZ"), ("财", "禄"), ("妻", "妾", "婚", "夫")),
              ("4.4 条目补充·子息", "child", "子星", "子息",
               ("R-ML", "R-XP-019"), ("子息", "子女", "子"), ())]
    for title, key, label, topic, pref, tkw, dny in blocks:
        lst = sk.get(key) or []
        if g == "女" and key == "spouse":
            pref = ("R-X13", "R56", "R69", "R85", "R84", "R228")
        mat = material(a, topic, prefer=pref, theme_kw=tkw, deny=dny)
        extra = marriage_sp(a) if key == "spouse" else (cai_view(a) if key == "wealth" else [])
        P("### " + title)
        P("")
        if extra:
            P("**十神定位（乙轨）**")
            P("")
            for e in extra:
                P("- %s%s" % (S(e["text"]), "　`%s`" % e["rule"] if trace else ""))
            P("")
        if not mat:
            P(S(_empty_note(key, a.get("gender") or "男", bool(extra))))
        else:
            for _s, rid, txt, theme in mat:
                tail = "　`%s`" % rid if trace else ""
                P("- %s%s" % (S(txt), tail))
        P("")
        if trace:
            P(basis_line({"spouse": "marriage", "wealth": "wealth",
                          "child": "child"}.get(key, "")))
            P("")

    P("### 4.5 父母兄弟")
    P("")
    P("> **父母一项，梁氏本无系统断法。** 书里那组「先丧母／先丧父／父母分离」，"
      "他自注为清代文人「搜锦句」之集成，非他所创——只作提示，不进命书。"
      "能落字的只有三处：年柱看出身、父星母星看缘之厚薄、比劫看兄弟。都不成立就留白。")
    P("")
    if trace:
        P(basis_line("parent"))
        P("")
    lq = LQ.groups(a)
    if lq["cs"]:
        P("**出身（年柱）**")
        P("")
        for e in lq["cs"]:
            tail = "　`%s`" % e["xq_id"] if trace else ""
            P("- %s%s" % (S(e["text"]), tail))
        P("")
    if lq["fm"]:
        P("**父母（父看偏财，母看印；宫看年月）**")
        P("")
        for e in lq["fm"]:
            tail = "　`%s`" % e["xq_id"] if trace else ""
            P("- %s%s" % (S(e["text"]), tail))
        P("")
    if lq["xd"]:
        P("**兄弟（看比劫）**")
        P("")
        for e in lq["xd"]:
            tail = "　`%s`" % e["xq_id"] if trace else ""
            P("- %s%s" % (S(e["text"]), tail))
        P("")

    # 规则库里的六亲补料：只作补，不作主
    mat = material(a, "六亲", prefer=("R-ML", "R-XP"), theme_kw=("父母", "兄弟", "祖"))
    if mat:
        P("**补料（规则库另出）**")
        P("")
        for _s_, rid, txt, _theme in mat:
            tail = "　`%s`" % rid if trace else ""
            P("- %s%s" % (S(txt), tail))
        P("")

    if not (lq["cs"] or lq["fm"] or lq["xd"] or mat):
        P("本盘三处皆不成立——**此节留白**。命书里以 4.1 的星宫语带过，"
          "写「父母缘之厚薄，须看运与年柱之合冲」，不硬凑一句。")
        P("")

    P("### 4.6 性情")
    P("")
    P("先看日主与格：%s 日主，%s 月令，格取%s，%s。" % (
        f["day"], f["month"], gj.get("name", "未裁"), gj.get("shun", "")))
    xp = XQ.profile(a)
    xp_verdict_para = XQ.verdict(a, xp)
    if xp["gods"]:
        P("十神量过，%s过旺——此即性分之主。梁氏断性情，从这里入手，不从「金性刚、水性柔」一类套语入手。"
          % "、".join(g for g, _s in xp["gods"]))
    else:
        P("十神无一过旺——**性情不偏**。此非无性，是无偏执；批此类命，只以日主之性与格局顺逆说。")
    P("")
    P("**总断（可直入命书）**")
    P("")
    P(xp_verdict_para)
    P("")
    used = set()
    for g, _s in xp["gods"]:
        used.update(id(e) for e in [x for x in xp["rows"] if x["god"] == g][:2])
    rest = [e for e in xp["rows"] if id(e) not in used]
    if rest:
        P("**备取条列（总断未用，供批者按人添减）**")
        P("")
        for e in rest:
            tail = "　`%s`" % e["xq_id"] if trace else ""
            P("- %s%s" % (S(e["text"]), tail))
        P("")
    mg = material_gods(a)
    if mg:
        P("**十神取象补料（规则库另出）**")
        P("")
        for theme, txt in mg:
            P("- **%s**：%s" % (theme or "取象", S(txt)))
        P("")
    P("**批者提示**")
    P("")
    P(XQ.caveat(a, xp))
    P("")
    if trace:
        P(basis_line("xingqing"))
        P("")

    P("### 4.7 寿元与疾病")
    P("")
    hv = health_view(a)
    if hv:
        for e in hv:
            P("- %s%s" % (S(e["text"]), "　`%s`" % e["rule"] if trace else ""))
        P("")
    mat = material(a, "疾病寿元", 3)
    if mat:
        for _s, rid, txt, theme in mat:
            P("- %s%s" % (S(txt), "　`%s`" % rid if trace else ""))
        P("")
    elif not hv:
        _sym = ("本盘可算之病象只一条，即月干、时干官杀混杂（原书明言此一条不论男女），"
                "本盘不犯；余八条或为男命专条、或条件未结构化，本器不判。"
                if (a.get("gender") or "男") == "女" else
                "本盘四条可算之病象（月时官杀混杂、庚日冬月无火、男命伤官多乏水、"
                "男命枭重身弱）一条不犯。")
        P(S("- **无显明症兆，不出断句**——原书：「一般性疾病不必细批，须有显明症兆，"
            "方出断句」。%s故留白。这不是本盘无疾，是本节宁可留白。" % _sym))
        P("")
    P(S("> **梁氏批寿只判长短，不判年岁**——不得写具体岁数，不得写「某年有大限」。"
        "寿元从日主之根、调候之有无、冲提三处看（见 4.1 末节与第五节）。"
        "另有须运方能判者：四正会冲提男命作官非（R-ML-029）、阳男顺运入午（R-ML-060）、"
        "寿元四推法（R-ML-066）——本器只在给运时标结构，不逐年断生死。"))
    P("")
    if trace:
        P(basis_line("health"))
        P("")

    # ── 五、大运
    P("## 五、大运批导")
    P("")
    if not a.get("dayun"):
        P("未给大运，本节留空。给 `--dayun` 后重跑。")
    else:
        sp = {s["n"]: s for s in (a.get("dayun_spans") or [])}
        nw = a.get("now")
        if sp:
            P("| 运 | 干支 | 公历年（虚岁） | 硬法落点 | 怎么批 |")
            P("|---|---|---|---|---|")
        else:
            P("| 运 | 干支 | 硬法落点 | 怎么批 |")
            P("|---|---|---|---|")
        for d in a["dayun"]:
            hits = d.get("hits") or []
            brief = "；".join(S(h) for h in hits) if hits else "五硬法俱不犯"
            hard = [h for h in hits if any(k in h for k in ("败亡", "墓库", "冲提", "双冲"))]
            if hard:
                verdict = "**有硬法**，先论硬法，再论干支生克"
            elif hits:
                verdict = "只犯修饰（空亡／接角／拱），减力而不改局"
            else:
                verdict = "无硬法，按干支与命局之冲合看，不作大断"
            mark = " **←现行**" if nw and nw["n"] == d.get("n") else ""
            if sp:
                s = sp.get(d.get("n"), {})
                rng = "%s–%s（%s–%s）" % (s.get("year_from", "—"), s.get("year_to", "—"),
                                          s.get("age_from", "—"), s.get("age_to", "—"))
                P("| 第%d运 | %s%s | %s | %s | %s |"
                  % (d.get("n", 0), d.get("gz", ""), mark, rng, brief, verdict))
            else:
                P("| 第%d运 | %s%s | %s | %s |"
                  % (d.get("n", 0), d.get("gz", ""), mark, brief, verdict))
        P("")
        if sp:
            P("> 第 1 运起于 **%d** 年——须与 `paipan.py` 的「交运日」同年。"
              "不同即 `--start-age` 抄错：那是「交运虚岁」，不是「起运折几年」。" % sp[1]["year_from"])
            P("")
        else:
            P("未给 `--birth-year`／`--start-age`，运只排次序，不落公历年——"
              "故「当前行第几运」定不出。")
            P("")
        P("批运的次序是**固定四问**，每问必须出结论，不许跳过：")
        P("")
        P("① **调候**——补不补调候字（含支藏）；补的是正官还是七杀，两样口气，不作并列不分。")
        P("")
        P("② **扶抑**——运干十神对日主是帮（比劫、印）还是泄耗克（食伤、财、官杀）；"
          "运支是日主的什么气地（禄、刃、生、库、绝）。")
        P("")
        P("③ **格局**——原局用神（财官印食）在此运是被引出、被合走、还是入墓被收。")
        P("")
        P("④ **刑冲合会破穿**——对宫位与六亲的冲击面。")
        P("")
        P("裁决：四问同向直断；两两相反，写成「得中带失／凶中带财」的复合断并列成立条件；"
          "**不许拿任何一问单独一票否决其余三问**——旧法「先看调候再看刑冲」是单键排序，"
          "比肩帮身、印星生金这类第二问的事在里头没有位置，已废。")
        P("")
        P("关系扫描是**三层矩阵**：原局×原局、大运×原局、大运×流年。"
          "原局已有某三会／三刑／三合中的两支，运年补第三支，即作**成局成刑**论，"
          "不得降级为「不相涉」；应验期从补齐之运起算。凡落笔「无涉、不相干、无冲」"
          "这类否定断语，须先跑完三层矩阵，否则不许写。")
        P("")
        P("三条硬法不许忘：**十干败亡**最硬（成绝位者，此十年不作大事）；"
          "**墓库运**只四个月生人有；**冲提**前五年最紧。"
          "双冲月柱另有两说并列（一云「本身无大碍」、一云「全面性之凶」），本包不代裁。")
        P("")
        P("另有一层不在这三条内：**大运对四柱之喜忌，梁氏明确推荐以《神峰通考》之金不换"
          "大运喜忌为最中肯**。本包未收金不换大运表，故于败亡、墓库、冲提、双冲之外，"
          "不作「此运喜何忌何」的总断——不是不判，是无据不判；拿常法代金不换，正是"
          "梁氏所不许。")
    P("")
    P("五条硬法备查：")
    for k, v in HARD:
        P("- **%s**：%s" % (k, v))
    P("")
    P("引用成法的**适用条件**不许省：如「禄入墓库运主凶」，所指是**日主自身之禄或用神**"
      "入墓——忌神、闲神之禄入墓，先判该字在盘上是病是用，病者入墓反吉。"
      "凡引他人成法，补一行适用条件再落笔。")
    P("")
    P("每个刑冲合墓**两面读**再裁决：此象吉在何处、凶在何处，两槽都填完才许下断——"
      "辰戌冲既冲妻宫破魁罡、亦冲开库门取用；病神入墓是去病不是添凶。只读一面即是误套。")
    P("")

    if trace and a.get("dayun"):
        P(basis_line("dayun"))
        P("")

    # ── 六、流年
    now = a.get("now")
    _ys = a.get("liunian") or []
    in_now = bool(now) and any(y.get("dy_n") == now["n"] for y in _ys)
    _sw = "近五年" if len(_ys) == 5 else ("近 %d 年" % len(_ys) if _ys else "")
    P("## 六、流年举要" + ("（现行第 %d 运 %s · %s）" % (now["n"], now["gz"], _sw) if in_now else ""))
    P("")
    for line in liunian_block(a, S):
        P(line)
    if trace:
        P("")
        P(basis_line("liunian"))
        P("")

    # ── 七、落笔须知
    P("## 七、落笔须知")
    P("")
    P("**六段体例**：四柱 → 已知因（只列结构，不带断语）→ 总评（必以「贵造」起，第一句点调候）"
      "→ 妻／财／子／禄各一条 → 具体事项 → 提要三条。")
    P("")
    P("**四禁**：一禁堆「金寒水冷、火炎土燥」套语；二禁「身弱不能托财官、用神得地」空话；"
      "三禁把大运当缩版八字批、把流年当小型大运批；四禁把八字用神硬套流月。")
    P("")
    P("**分寸**：能七成应验，即为合理合宜。凡「一定、必然、肯定」，一律改作"
      "「照结构看是／多半是／这一步要留意」。命书末尾须留「不准」的余地。")
    P("")
    P("**不引原文**：命书与报告都不出书目页码；要回查才用 `corpus_search.py`。"
      "本稿的断语方向须由批者改写为梁氏口吻，不得原文照抄。")
    P("")
    return "\n".join(L)


NO_SAY = ("不作断", "不适用", "查不出", "留白", "未判", "不补通行", "本节留空")


def _has_sent(t):
    t = (t or "").strip()
    return bool(t) and not any(k in t for k in NO_SAY)


def build_trace(a):
    """机器可读版：逐判断点给出「立不立得住、挂在哪些条文上」。

    与 render 分开写，为的是让审计器不必解析 markdown。点数与 render 对齐（22 点）。
    """
    f = facts(a)
    f["where"] = a.get("where") or _where_of(a)
    rows = []

    def add(pid, name, fired, say, extra=()):
        ids = []
        for x in list(point_ids(pid)) + [e for e in extra if e]:
            if x and x not in ids:
                ids.append(x)
        rows.append({"pid": pid, "name": name, "fired": bool(fired),
                     "sent": _has_sent(say), "say": _clip(say or "", 90),
                     "raw": _clip(say or "", 500),
                     "ids": ids})

    items = ten_items(a, f)
    for x in items:
        add("item%d" % x["no"], x["name"], True, x["say"], x.get("ids") or ())
    core = core_conflict(a, items)
    add("core", "此造最要紧的一处", core.get("has"), core.get("say"))
    ys = yongshen_ruling(a, f)
    for l in ys["lines"]:
        add("ys%d" % l["lv"], l["name"], ys["decided"] == l["lv"], l["this"])
    spb = star_palace(a)
    add("sp", "星宫合参", bool(spb), "；".join(b["title"] for b in spb))
    ss_hits = SP.sits(a) + SP.entries(a)
    add("shishen", "十神定位（乙轨）", bool(ss_hits),
        "；".join(e["text"] for e in ss_hits), [e["rule"] for e in ss_hits])
    g = a["gender"]
    for key, pid, topic, tkw, dny, pref in (
            ("spouse", "marriage", "婚姻", ("婚", "妻", "夫"), (), ("R-ML", "R-XP-020")),
            ("wealth", "wealth", "财官", ("财", "禄"), ("妻", "妾", "婚", "夫"),
             ("R-ML", "R-XP", "R-SZ")),
            ("child", "child", "子息", ("子息", "子女", "子"), (), ("R-ML", "R-XP-019"))):
        if g == "女" and key == "spouse":
            pref = ("R-X13", "R56", "R69", "R85", "R84", "R228")
        mat = material(a, topic, prefer=pref, theme_kw=tkw, deny=dny)
        extra = marriage_sp(a) if key == "spouse" else (cai_view(a) if key == "wealth" else [])
        add(pid, {"spouse": "婚姻", "wealth": "财与事业", "child": "子息"}[key],
            bool(mat) or bool(extra),
            "；".join([m[2] for m in mat] + [e["text"] for e in extra]),
            [m[1] for m in mat] + [e["rule"] for e in extra])
    lq = LQ.groups(a)
    pn = (lq.get("cs") or []) + (lq.get("parent") or []) + (lq.get("sib") or [])
    add("parent", "父母兄弟", bool(pn), "；".join(e["text"] for e in pn),
        [e["xq_id"] for e in pn])
    xp = XQ.profile(a)
    add("xingqing", "性情", bool(xp.get("gods")), XQ.verdict(a, xp))
    mh = material(a, "疾病寿元", 3)
    hvc = health_view(a)
    add("health", "寿元与疾病", bool(mh) or bool(hvc),
        "；".join([m[2] for m in mh] + [e["text"] for e in hvc]),
        [m[1] for m in mh] + [e["rule"] for e in hvc])
    add("dayun", "大运五硬法", bool(a.get("dayun")),
        "；".join(h for d in (a.get("dayun") or []) for h in (d.get("hits") or [])[:2]))
    ln_ids = []
    for y in (a.get("liunian") or []):
        for r in y.get("rows") or []:
            if r.get("rule") in ("R-MF-017", "R-MF-018") and r["rule"] not in ln_ids:
                ln_ids.append(r["rule"])
        if y.get("months") and "R-MF-018" not in ln_ids:
            ln_ids.append("R-MF-018")
    add("liunian", "流年三层", bool(a.get("liunian")),
        "；".join((y.get("gz") or "") for y in (a.get("liunian") or [])), ln_ids)
    return {"pillars": a["pillars"], "gender": a["gender"], "points": rows}


def _where_of(a):
    w = {}
    for i, r in enumerate(a["expanded"]):
        if r["stem_tg"] != "日主":
            w.setdefault(r["stem_tg"], []).append(("透" + POS[i], r["stem"]))
        for h in r["hidden"]:
            w.setdefault(h["tg"], []).append(("藏" + POS[i], h["stem"]))
    return w


def self_test():
    """自检：男女两盘都要出得来，且不许漏项、不许漏编号。"""
    import re
    ok = True
    cases = [(["甲子", "乙亥", "庚戌", "癸未"], "男",
              ["十项优先", "此造最要紧", "用神落定", "星宫合参", "大运批导", "落笔须知"]),
             (["辛酉", "丁酉", "乙巳", "丙子"], "女",
              ["十项优先", "用神落定", "星宫合参", "落笔须知"])]
    for pillars, g, need in cases:
        a = A.analyze(pillars, gender=g)
        a["where"] = _where_of(a)
        md = render(a, trace=False)
        for k in need:
            if k not in md:
                print("FAIL  %s %s：缺「%s」" % ("".join(pillars), g, k))
                ok = False
        # 十项须九行
        n = len(re.findall(r"^\| \d \| ", md, re.M))
        if n < 9:
            print("FAIL  %s %s：十项只出 %d 行" % ("".join(pillars), g, n))
            ok = False
        # 非 trace 不得出现 rule_id
        bad = re.findall(r"(?<![A-Za-z0-9])" + ID_PAT + r"(?![A-Za-z0-9])", md)
        if bad:
            print("FAIL  %s %s：正文残留编号 %s" % ("".join(pillars), g, bad[:3]))
            ok = False
        # trace 模式须能出编号
        md2 = render(a, trace=True)
        if not any(k in md2 for k in ("`R-", "`T-", "`XQ-")):
            print("WARN  %s %s：trace 模式未附编号（本盘或无可挂条目）" % ("".join(pillars), g))
        # 星宫合参不得为空表
        if md.count("| 信号 | 本盘 |") < 2:
            print("FAIL  %s %s：星宫合参表不足两张" % ("".join(pillars), g))
            ok = False

    # 近五年：给了运与起运岁，须定得出「当前行第几运」，并铺出 6.1～6.4
    a = A.analyze(["辛酉", "丁酉", "乙巳", "丙子"], gender="女", birth_year=1981,
                  start_age=7, dayun=["戊申", "己酉", "庚戌", "辛亥", "壬子"],
                  recent=5, base_year=2026)
    now = a.get("now") or {}
    if now.get("n") != 4 or now.get("idx") != 10:
        print("FAIL  近五年：当前运定位错（%s）" % now)
        ok = False
    if [y["year"] for y in a["liunian"]] != [2022, 2023, 2024, 2025, 2026]:
        print("FAIL  近五年：年份窗口不对 %s" % [y["year"] for y in a["liunian"]])
        ok = False
    a["where"] = _where_of(a)
    md = render(a, trace=False)
    for k in ("6.1 所行何运", "6.2 近五年结构", "6.3 五年合看", "运尾接角"):
        if k not in md:
            print("FAIL  近五年：缺「%s」" % k)
            ok = False
    if re.findall(r"(?<![A-Za-z0-9])" + ID_PAT + r"(?![A-Za-z0-9])", md):
        print("FAIL  近五年：正文残留编号")
        ok = False

    print("panduan 自检：%s（%d 盘＋近五年校验）" % ("全部通过" if ok else "有失败项", len(cases)))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="批命推演器（梁氏次序）")
    ap.add_argument("--self-test", action="store_true", help="自检（不出盘）")
    ap.add_argument("pillars", nargs="*", metavar="柱", help="四柱，如 甲子 乙亥 庚戌 癸未")
    ap.add_argument("--gender", choices=["男", "女"])
    ap.add_argument("--dayun", help="大运干支，逗号分隔")
    ap.add_argument("--liunian", help="流年，逗号分隔")
    ap.add_argument("--birth-year", type=int)
    ap.add_argument("--start-age", type=int,
                    help="起运虚岁，取 paipan 输出的「交运虚岁」；不是「起运折几年」那年数")
    ap.add_argument("--recent", type=int, nargs="?", const=5, metavar="N",
                    help="不出 --liunian 而取「最近 N 年」（含今年，默认 5），须配 --dayun --birth-year --start-age")
    ap.add_argument("--base-year", type=int, help="以某年为「今年」（回批旧盘用；默认系统当前年）")
    ap.add_argument("--from-paipan", metavar="JSON",
                    help="直接读 paipan.py --json 的输出：四柱／性别／大运／交运虚岁一并取来，不必手抄")
    ap.add_argument("--liuyue", action="store_true")
    ap.add_argument("--trace", action="store_true", help="附依据编号（批者自核用）")
    ap.add_argument("--out", metavar="FILE")
    ap.add_argument("--json", action="store_true",
                    help="输出机器可读的判断点清单（供 trace_audit 用）")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    src = None
    if args.from_paipan:
        try:
            src = A.load_paipan(args.from_paipan)
        except (OSError, ValueError) as e:
            ap.error("读 paipan 输出失败：%s" % e)
        args.pillars = args.pillars or src["pillars"]
        args.gender = args.gender or src["gender"]
        args.dayun = args.dayun or ",".join(src["dayun"])
        args.birth_year = args.birth_year or src["birth_year"]
        args.start_age = args.start_age or src["start_age"]

    if len(args.pillars) != 4:
        ap.error("须给四个干支，例如：甲子 乙亥 庚戌 癸未（或给 --from-paipan）")

    dyn = None
    if args.dayun:
        dyn = [x.strip() for x in args.dayun.replace("，", ",").split(",") if x.strip()]
        bad = [x for x in dyn if x not in A.JIAZI_SET]
        if bad:
            ap.error("大运干支不合法：" + "、".join(bad))
    lns = None
    if args.liunian:
        lns = []
        for x in args.liunian.replace("，", ",").split(","):
            x = x.strip()
            if not x:
                continue
            if x.isdigit():
                lns.append(int(x))
            elif x in A.JIAZI_SET:
                lns.append(x)
            else:
                ap.error("流年须为公历年或干支：" + x)
    try:
        a = A.analyze(args.pillars, gender=args.gender, dayun=dyn, liunian=lns,
                      birth_year=args.birth_year, start_age=args.start_age,
                      liuyue=args.liuyue, recent=args.recent, base_year=args.base_year)
    except ValueError as e:
        ap.error(str(e))
    a["where"] = _where_of(a)
    # 与 paipan 自报的「当前大运」对账：起运岁若抄错，这里立刻现形
    cur = (src or {}).get("current") or {}
    if cur and a.get("now") and not args.base_year:
        if (cur.get("gz"), cur.get("from")) != (a["now"]["gz"], a["now"]["from"]):
            ap.error("与 paipan 的当前大运不符：paipan 作 %s（%s 起），本器算成 %s（%d 起）——"
                     "多半是 --start-age 抄错（须用「交运虚岁」）" %
                     (cur.get("gz"), cur.get("from"), a["now"]["gz"], a["now"]["from"]))
    if args.json:
        import json as _json
        print(_json.dumps(build_trace(a), ensure_ascii=False, indent=1))
        return 0
    md = render(a, trace=args.trace)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print("→ %s（%d 字）" % (args.out, len(md)))
    else:
        print(md)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main() or 0)
