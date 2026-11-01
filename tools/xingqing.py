# -*- coding: utf-8 -*-
"""心性库：十神 → 心性条列。

梁氏断性情，不从「金性刚、水性柔」一类套语出，而从**十神过旺**出。
《子平基础概要》里十神各有整段心性条列（比肩十一项、劫财九项、偏印九项、
偏财九项、七杀十四项……），此前本包一条未用，性情一节只能写「素材薄」。

本模块把那一层结构化：先量各十神之力量，取「过多」者为主神，
再按主神取其心性条列，加跨神组合（食伤混杂、官杀并见、比劫并见、财印并见），
末了合成一段可入命书的总断。

两处「变性」照原文办：
- 食神四见以上，作伤官论；
- 正官过多，作七杀论。
"""

import csv
import io
import os
import sys

import analyze as A

POS = ["年", "月", "日", "时"]
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
XQ = os.path.join(DATA, "xingqing.csv")

# 五行生
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
# 十神 → 与日主的关系
ELEM_OF_GOD = {
    "比肩": "同我", "劫财": "同我",
    "食神": "我生", "伤官": "我生",
    "偏财": "我克", "正财": "我克",
    "七杀": "克我", "正官": "克我",
    "偏印": "生我", "正印": "生我",
}
# 支藏本中余气之权
LEVEL = [1.0, 0.6, 0.4]
# 十二长生之「禄」「刃」位
LU = {"甲": "寅", "乙": "卯", "丙": "巳", "丁": "午", "戊": "巳",
      "己": "午", "庚": "申", "辛": "酉", "壬": "亥", "癸": "子"}
REN = {"甲": "卯", "乙": "寅", "丙": "午", "丁": "巳", "戊": "午",
       "己": "巳", "庚": "酉", "辛": "申", "壬": "子", "癸": "亥"}
# 四见即变性者
BIAN = {"食神": "伤官", "正官": "七杀"}


# ─────────────────────────── 量力量 ───────────────────────────

def god_count(a, god):
    """某十神在四柱的见数：天干一 + 支藏各一。"""
    n = 0
    for row in a["expanded"]:
        if row["stem_tg"] == god:
            n += 1
        n += sum(1 for h in row["hidden"] if h["tg"] == god)
    return n


def god_strength(a, gods):
    """某类十神之力量：透干 2、支藏本气 1／中气 0.6／余气 0.4，得月令再加 0.5。

    口径照梁氏「过多」之定义校准：天干一 + 支藏二 ≈ 3.6，天干二 + 支藏一 ≈ 5，
    皆过 3.0 之门；天干独透（2.0）或支藏独本气（1.0）皆不足。故以 3.0 为「过多」。
    """
    if not gods:
        return 0.0
    tot = 0.0
    for row in a["expanded"]:
        if row["stem_tg"] in gods:
            tot += 2.0
        for j, h in enumerate(row["hidden"]):
            if h["tg"] in gods:
                tot += LEVEL[min(j, 2)]
    mh = a["expanded"][1]["hidden"]
    if mh and mh[0]["tg"] in gods:
        tot += 0.5
    return round(tot, 1)


def god_stems(a, god):
    """该神透在几个天干上。"""
    return sum(1 for row in a["expanded"] if row["stem_tg"] == god)


def has_root(a, god):
    """该神在地支有无藏根。"""
    return any(h["tg"] == god for row in a["expanded"] for h in row["hidden"])


def ren_pos(a):
    """羊刃落在何支（按日主之刃位查）。"""
    r = REN.get(a["pillars"][2][0])
    return [row["pos"] + row["branch"] for row in a["expanded"] if row["branch"] == r]


def lu_pos(a):
    """日主之禄落在何支。"""
    r = LU.get(a["pillars"][2][0])
    return [row["pos"] + row["branch"] for row in a["expanded"] if row["branch"] == r]


# ─────────────────────────── 判条件 ───────────────────────────

def _force(a, spec):
    """该类十神是否成气候：透干，或藏而得本气。"""
    for g in spec.split("|"):
        if not g:
            continue
        if god_stems(a, g):
            return True
        for row in a["expanded"]:
            if row["hidden"] and row["hidden"][0]["tg"] == g:
                return True
    return False


def gan_he(a):
    """天干五合：返回 [(干1, 干2, 神1, 神2)]。日主之干不参与。"""
    pairs = [("甲", "己"), ("乙", "庚"), ("丙", "辛"), ("丁", "壬"), ("戊", "癸")]
    rows = a["expanded"]
    out = []
    for i in range(4):
        for j in range(i + 1, 4):
            if i == 2 or j == 2:
                continue          # 日主不与旁干论合
            si, sj = rows[i]["stem"], rows[j]["stem"]
            if any((si, sj) == p or (sj, si) == p for p in pairs):
                out.append((si, sj, rows[i]["stem_tg"], rows[j]["stem_tg"]))
    return out


def _he_qu(a, gods):
    """官杀之中有一被合去者，则不作混杂论。"""
    for _s1, _s2, g1, g2 in gan_he(a):
        if (g1 in gods) != (g2 in gods):
            return True
    return False


def _presence(a, spec):
    """A|B 中是否有任一（或全无）。"""
    names = [x for x in spec.split("|") if x]
    return any(god_strength(a, [g]) > 0 for g in names)


def hold(a, god, need):
    """need 为一串以 `+` 相连的条件，全部成立才算成立。"""
    if not need:
        return True
    for cond in need.split("+"):
        cond = cond.strip()
        if not cond:
            continue
        if cond.startswith("no:"):
            if _presence(a, cond[3:]):
                return False
        elif cond.startswith("has2:"):
            # 须真成气候：该类十神透干，或藏而有本气之根；余气一藏不算
            if not _force(a, cond[5:]):
                return False
        elif cond.startswith("has:"):
            if not _presence(a, cond[4:]):
                return False
        elif cond.startswith("zuo:"):
            # 该神所透之干，其坐下之支是否另有某神（如「伤官坐劫财」）
            other = cond[4:]
            ok = False
            for row in a["expanded"]:
                if row["stem_tg"] == god and any(h["tg"] == other for h in row["hidden"]):
                    ok = True
                    break
            if not ok:
                return False
        elif cond.startswith("tong:"):
            other = cond[5:]
            ok = False
            for row in a["expanded"]:
                gods_here = {row["stem_tg"]} | {h["tg"] for h in row["hidden"]}
                if god in gods_here and other in gods_here:
                    ok = True
                    break
            if not ok:
                return False
        elif cond.startswith("pos:"):
            where = cond[4:]
            idx = {"年": 0, "月": 1, "日": 2, "时": 3}.get(where[0], -1)
            if idx < 0:
                return False
            row = a["expanded"][idx]
            if where.endswith("干"):
                if row["stem_tg"] != god:
                    return False
            elif where.endswith("支"):
                if not any(h["tg"] == god for h in row["hidden"]):
                    return False
        elif cond == "wang":
            if god_strength(a, [god]) < 3.0:
                return False
        elif cond == "stem2":
            if god_stems(a, god) < 2:
                return False
        elif cond == "si4":
            if god_count(a, god) < 4:
                return False
        elif cond == "all_yin":
            if not a["xingtai"].get("all_yin"):
                return False
        elif cond == "root_strong":
            # 日主本有临官帝旺之根
            if not (lu_pos(a) or ren_pos(a)):
                return False
        elif cond == "wuxu":
            # 该神全透天干而不见藏根
            if has_root(a, god):
                return False
        elif cond == "fu":
            # 浮：透干而无根
            if has_root(a, god) or god_stems(a, god) == 0:
                return False
        elif cond == "sheng_yin":
            if not (_presence(a, "正印|偏印") and _presence(a, "七杀")):
                return False
        elif cond == "you_yangren":
            if not ren_pos(a):
                return False
        elif cond == "pei_yin2":
            if not _force(a, "正印|偏印"):
                return False
        elif cond == "pei_yin":
            if not _presence(a, "正印|偏印"):
                return False
        elif cond == "sheng_cai":
            if not _presence(a, "正财|偏财"):
                return False
        elif cond == "shishang_hun":
            # 原文：「食神、伤官，不喜同时在天干并见」——只藏支者不作此论
            if not (god_stems(a, "食神") and god_stems(a, "伤官")):
                return False
        elif cond == "guansha_hun":
            # 原文：官杀「不可以并见天干」；然逐月有开禁——合杀留官、合官留杀则不论混杂
            if not (god_stems(a, "正官") and god_stems(a, "七杀")):
                return False
            if _he_qu(a, ("正官", "七杀")):
                return False
        elif cond == "nv":
            if a.get("gender") != "女":
                return False
        elif cond == "bijie_bing":
            if not (god_stems(a, "比肩") and god_stems(a, "劫财")):
                return False
        elif cond == "cai_yin_bing":
            if not (_presence(a, "正财|偏财") and _presence(a, "正印|偏印")):
                return False
        else:
            return False
    return True


# ─────────────────────────── 取条列 ───────────────────────────

_CACHE = None


def load():
    """读心性库。字段：xq_id, god, need, order, text。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    out = []
    with io.open(XQ, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out.append({
                "xq_id": (r["xq_id"] or "").strip(),
                "god": (r["god"] or "").strip(),
                "need": (r["need"] or "").strip(),
                "order": int((r["order"] or "0").strip() or 0),
                "text": (r["text"] or "").strip(),
            })
    out.sort(key=lambda x: (x["god"], x["order"]))
    _CACHE = out
    return out


def bian_god(a):
    """变性：食神四见作伤官论；正官过多作七杀论。返回 {原神: 实论之神}。"""
    m = {}
    for src, dst in BIAN.items():
        if src == "食神" and god_count(a, "食神") >= 4:
            m[src] = dst
        elif src == "正官" and god_strength(a, ["正官"]) >= 4.0:
            m[src] = dst
    return m


def main_gods(a, top=2, floor=3.0, soft=2.0):
    """取性分之主，分三档。

    过旺（≥3.0）——梁氏所谓「过多」，双透之数，可直断。
    微偏（2.0–3.0）——一神稍胜，未成过旺，只可「略偏于」。
    无偏（<2.0）——实测三百盘未见此档，留作兜底。
    """
    score = {g: god_strength(a, [g]) for g in ELEM_OF_GOD}
    for src, dst in bian_god(a).items():
        # 食神四见 / 正官过多：力量归并入实论之神
        score[dst] = round(score.get(dst, 0) + score.get(src, 0), 1)
        score[src] = 0.0
    order = list(ELEM_OF_GOD).index

    picked = [(g, v) for g, v in score.items() if v >= floor]
    picked.sort(key=lambda x: (-x[1], order(x[0])))
    if picked:
        return picked[:top], score, "wang"

    soft_pick = [(g, v) for g, v in score.items() if v >= soft]
    soft_pick.sort(key=lambda x: (-x[1], order(x[0])))
    if soft_pick:
        return soft_pick[:1], score, "pian"
    return [], score, "flat"


# 条件越具体，越贴本盘，越该先说。「泛说」只作底，「专说」才见本事。
_SPECIFIC = ("no:", "has:", "has2:", "zuo:", "tong:", "pos:", "si4", "stem2",
             "all_yin", "root_strong", "wuxu", "fu", "sheng_yin", "you_yangren",
             "pei_yin", "sheng_cai", "nv")


def _spec(need):
    """条件之具体度：有几个只在本盘才成立的条件。"""
    if not need:
        return 0
    return sum(1 for c in need.split("+")
               if any(c.strip().startswith(k) or c.strip() == k for k in _SPECIFIC))


# 「多者」「过旺」「入格」——这些话以神已过旺为前提。微偏档禁用。
OVERCLAIM = ("多者", "过多", "过旺", "入格", "甚多", "太旺")


def pick(a, gods, limit=8, mode="wang"):
    """按主神取心性条目。

    排序不按库里行号，按**贴盘程度**：泛说（只标「旺」）在后，
    专说（「多而无官杀」「坐羊刃」「浮于天干」）在前——
    梁氏批性，先抓那一句只对本盘成立的话。
    """
    lib = load()
    out, seen = [], set()
    each = max(2, limit // max(1, len(gods))) if gods else limit
    for g, _s in gods:
        cand = [e for e in lib if e["god"] == g and hold(a, g, e["need"])]
        if mode == "pian":
            cand = [e for e in cand if not any(k in e["text"] for k in OVERCLAIM)]
        base = [e for e in cand if _spec(e["need"]) == 0]
        spec = [e for e in cand if _spec(e["need"]) > 0]
        spec.sort(key=lambda e: (-_spec(e["need"]), e["order"]))
        base.sort(key=lambda e: e["order"])
        take = base[:1] + spec[:each - 1] if spec else base[:each]
        if len(take) < each:
            take += [e for e in base[1:] if e not in take][:each - len(take)]
        for e in take:
            if e["xq_id"] in seen:
                continue
            out.append(e)
            seen.add(e["xq_id"])
    combos = []
    for e in lib:
        if e["god"] != "*" or e["xq_id"] in seen:
            continue
        if hold(a, "*", e["need"]):
            combos.append(e)
            seen.add(e["xq_id"])
    return out, combos[:2]


# ─────────────────────────── 总断 ───────────────────────────

DAY_NATURE = {
    "甲": ("甲木参天，性直而好高，不肯屈就于矮檐之下", "过刚则折，须有庚金修枝、丙火发荣"),
    "乙": ("乙木藤萝，性柔而善攀，能屈能伸，遇物即附", "过柔则失主，须有丙火暖之、癸水润之"),
    "丙": ("丙火太阳，性烈而外扬，光明磊落，不肯藏私", "过烈则燥，须有壬水既济"),
    "丁": ("丁火灯烛，性静而内照，心事细密，外柔而中执", "过晦则疑，须有甲木引焰"),
    "戊": ("戊土城墙，性厚而固执，能容能守，而不易移志", "过厚则滞，须有甲木疏之"),
    "己": ("己土田园，性顺而多虑，能受能藏，而主意常摇", "过湿则陷，须有丙火暖之"),
    "庚": ("庚金顽铁，性刚而重义，直来直往，不惯委曲", "过顽则伤，须有丁火炼之"),
    "辛": ("辛金珠玉，性锐而自重，外和而内有所不屑", "过锐则孤，须有壬水淘之"),
    "壬": ("壬水江河，性动而多智，胸襟开阔，而不耐拘束", "过泛则散，须有戊土为之堤"),
    "癸": ("癸水雨露，性沉而善感，心思深细，不轻示人", "过寒则滞，须有丙火暖之"),
}


def _day_line(a):
    f = a["pillars"][2][0]
    d = DAY_NATURE.get(f)
    if not d:
        return ""
    return "日主%s：%s。%s。" % (f, d[0], d[1])


def profile(a, limit=6):
    """出性情一节：主神、条列、组合、总断。"""
    gods, score, mode = main_gods(a)
    rows, combos = pick(a, gods, limit, mode)
    return {
        "mode": mode,
        "gods": gods,
        "score": score,
        "rows": rows,
        "combos": combos,
        "day": _day_line(a),
        "bian": bian_god(a),
        "yangren": ren_pos(a),
    }


def _join_gods(gods):
    return "、".join(g for g, _s in gods)


def _clause(t):
    """取一条断语，去尾句号，留中间标点。"""
    return t.rstrip("。").strip()


def verdict(a, p=None):
    """总断一段：四到六句，可直入命书。

    次序照梁氏：先说何神过旺（性分之主），再说日主之本是何性，最后落一句分寸。
    不写力量分数，不堆条列——三句说得清的，不用十句。

    三档分量不同，措辞也不同：过旺者可「断」，微偏者只可「略偏于」，无偏者只论日主。
    """
    p = p or profile(a)
    gods = p["gods"]
    mode = p.get("mode", "wang")
    f = a["pillars"][2][0]
    d = DAY_NATURE.get(f)

    if mode == "flat" or not gods:
        parts = ["十神无一处过旺，亦无一神稍胜——**性情不偏**。",
                 "此非无性，是无偏执：心气平，喜怒不形于色，长处是无偏，短处是少一股非做不可的狠劲。"]
        if d:
            parts.append("仍以日主为底：日主%s，%s。" % (f, d[0]))
        parts.append("批此类命，不可硬安一个「刚」字或「柔」字。")
        return "".join(parts)

    names = [g for g, _s in gods]
    if mode == "pian":
        parts = ["此造无一神过旺，诸神之中以%s稍胜——其性不偏，而略偏于%s。"
                 % (names[0], names[0])]
    elif len(names) == 1:
        parts = ["此造%s过旺。" % names[0]]
    else:
        parts = ["此造%s两神并旺，性分之主不止一端，须分主次看。" % "、".join(names)]

    # 日主之本性 —— 梁氏断性情，以日主为底，以过旺之神为用
    if d:
        parts.append("日主%s，%s。" % (f, d[0]))

    # 主神之性：过旺取两条，微偏只取一条（分寸不到，话不可说满）
    cap = 1 if mode == "pian" else 2
    for g, _s in gods:
        txts = [_clause(e["text"]) for e in p["rows"] if e["god"] == g][:cap]
        if not txts:
            continue
        if len(gods) == 1:
            parts.append("；".join(txts) + "。")
        else:
            parts.append("以%s为主，" % g + "；".join(txts) + "。")

    if mode == "wang":
        for e in p["combos"]:
            parts.append(_clause(e["text"]) + "。")

    if p["yangren"]:
        parts.append("本盘带羊刃，刚气外显——然刃须有制，无制则刚而折。")
    return "".join(parts)


def caveat(a, p=None):
    """批者提示，不入命书：性情这一节最容易写坏的两处。"""
    p = p or profile(a)
    out = []
    mode = p.get("mode", "wang")
    if mode == "wang":
        out.append("主神 %s——先写主神之性，再写日主之本，次序不可倒。"
                   % "、".join(g for g, _s in p["gods"]))
    elif mode == "pian":
        out.append("只到「微偏」一档（%s），话不可说满：写「略偏于」，不写「过旺」。"
                   % "、".join(g for g, _s in p["gods"]))
    else:
        out.append("十神无一处过多——不可硬安一个「刚」字或「柔」字。")
    out.append("性情只言其常，不论其变；变在运岁，不在原局。")
    out.append("断语不写「天生如何」，写「遇事如何」——梁氏断性，落点都在处事上。")
    return "\n".join("- " + x for x in out)


def self_test():
    """自检：男女老少几盘都要出得来，且条列不得空、不得重、不得夹编号。"""
    import re
    ok = True
    cases = [(["甲子", "乙亥", "庚戌", "癸未"], "男"),
             (["辛酉", "丁酉", "乙巳", "丙子"], "女"),
             (["癸巳", "戊午", "丙午", "壬辰"], "男"),
             (["庚申", "戊寅", "甲辰", "丙寅"], "男")]
    for pillars, g in cases:
        a = A.analyze(pillars, gender=g)
        p = profile(a)
        v = verdict(a, p)
        tag = "".join(pillars) + " " + g
        if not p["rows"] and p["gods"]:
            print("FAIL  %s：主神在而条列空" % tag)
            ok = False
        ids = [e["xq_id"] for e in p["rows"]] + [e["xq_id"] for e in p["combos"]]
        if len(ids) != len(set(ids)):
            print("FAIL  %s：条列重复" % tag)
            ok = False
        if re.search(r"XQ-|R\d|R-", v):
            print("FAIL  %s：总断夹编号" % tag)
            ok = False
        if len(v) < 40:
            print("FAIL  %s：总断过短（%d 字）" % (tag, len(v)))
            ok = False
        for e in p["rows"]:
            if len(e["text"]) < 8:
                print("FAIL  %s：条目过短 %s" % (tag, e["xq_id"]))
                ok = False
    # 数据完整性
    lib = load()
    gods = set(ELEM_OF_GOD) | {"*"}
    bad = [e["xq_id"] for e in lib if e["god"] not in gods]
    if bad:
        print("FAIL  心性库 god 字段非法：" + "、".join(bad[:5]))
        ok = False
    for g in ELEM_OF_GOD:
        if not any(e["god"] == g for e in lib):
            print("FAIL  心性库缺「%s」条列" % g)
            ok = False
    print("xingqing 自检：%s（%d 盘，库 %d 条）" % ("全部通过" if ok else "有失败项", len(cases), len(lib)))
    return 0 if ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(self_test())
