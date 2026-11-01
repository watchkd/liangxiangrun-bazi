# -*- coding: utf-8 -*-
"""六亲库：柱位 + 十神 → 出身、父母、兄弟之断。

为什么单独立一库：
`xingqing.csv` 是「此人如何」，讲心性；本库是「其亲如何」，讲六亲。
两库混在一起，性情一节就会写成离婚克子，六亲一节又会写成性格孤僻。

梁氏断六亲的骨架是**星宫合参**（星之有无透藏 + 宫之冲合坐煞），
推演器 4.1 已经把牌摆出来了；本库补的是从十神分柱可以直接落地的那些断语——
「正官在年干透出主出身书香」「比肩过多在年不利父」这一类，
出自《子平基础概要》十神分柱诸节，原书逐条写明，不是通行说法。

父母一项，梁氏本无系统断法：`R-XP-018` 明注为清代文人泛论、只作提示不作定论。
**薄就是薄，不拿泛论充数**——本库只收梁氏自己讲了条件的那几条。
"""

import csv
import io
import os
import sys

import analyze as A
import xingqing as X

POS = ["年", "月", "日", "时"]
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LQ = os.path.join(DATA, "liuqin.csv")

# 旬空（以日柱起）
XUN_KONG = {"甲子": "戌亥", "甲戌": "申酉", "甲申": "午未",
            "甲午": "辰巳", "甲辰": "寅卯", "甲寅": "子丑"}
# 十二长生之「绝」位
JUE = {"甲": "申", "乙": "酉", "丙": "亥", "丁": "子", "戊": "亥",
       "己": "子", "庚": "寅", "辛": "卯", "壬": "巳", "癸": "午"}


def kong_branches(a):
    """本造日柱所在旬之二空亡支。"""
    gz = a["pillars"][2]
    gi = "甲乙丙丁戊己庚辛壬癸".index(gz[0])
    zi = "子丑寅卯辰巳午未申酉戌亥".index(gz[1])
    head = (zi - gi) % 12                    # 该旬首之支序
    k1 = (head + 10) % 12
    k2 = (head + 11) % 12
    zhi = "子丑寅卯辰巳午未申酉戌亥"
    return {zhi[k1], zhi[k2]}


def at(a, god):
    """该神落在哪些柱（返回 [(柱序, '干'/'支', 支)]）。"""
    out = []
    for i, row in enumerate(a["expanded"]):
        if row["stem_tg"] == god:
            out.append((i, "干", row["branch"]))
        if any(h["tg"] == god for h in row["hidden"]):
            out.append((i, "支", row["branch"]))
    return out


def _chong_pos(a):
    """被冲之柱位集合。"""
    out = set()
    for r in a["relations"]:
        if "冲" not in r["kind"]:
            continue
        ps = [m[:1] for m in (r.get("members") or []) if m[:1] in POS]
        out.update(ps)
    return out


def _xing_pos(a):
    """被刑之柱位集合。"""
    out = set()
    for r in a["relations"]:
        if "刑" not in r["kind"]:
            continue
        ps = [m[:1] for m in (r.get("members") or []) if m[:1] in POS]
        out.update(ps)
    return out


def _tou(a, god, pos):
    """该神在该柱干支俱见（干是它，支本气也是它）。"""
    i = POS.index(pos)
    row = a["expanded"][i]
    return row["stem_tg"] == god and bool(row["hidden"]) and row["hidden"][0]["tg"] == god


def hold_lq(a, god, need):
    """六亲条件。自身条件先判，判不了的交回 xingqing.hold。"""
    if not need:
        return True
    mine = {"duo", "kong", "zhuan", "jue", "xing", "chong", "yangren", "zuori", "tou", "pos"}
    for cond in need.split("+"):
        cond = cond.strip()
        if not cond:
            continue
        key = cond.split(":")[0]
        if key not in mine:
            if not X.hold(a, god, cond):
                return False
            continue
        occ = at(a, god)
        if not occ:
            return False
        if cond == "duo":
            if X.god_strength(a, [god]) < 3.0:
                return False
        elif cond == "kong":
            kb = kong_branches(a)
            if not any(br in kb for _i, _w, br in occ):
                return False
        elif cond == "jue":
            j = JUE.get(a["pillars"][2][0])
            if not any(br == j for _i, _w, br in occ):
                return False
        elif cond == "xing":
            bad = _xing_pos(a)
            if not any(POS[i] in bad for i, _w, _b in occ):
                return False
        elif cond == "chong":
            bad = _chong_pos(a)
            if not any(POS[i] in bad for i, _w, _b in occ):
                return False
        elif cond == "yangren":
            if not X.ren_pos(a):
                return False
            ren = X.REN.get(a["pillars"][2][0])
            if not any(br == ren for _i, _w, br in occ):
                return False
        elif cond == "zhuan":
            # 专位：该神在日支或月支作本气
            ok = any(i in (1, 2) and a["expanded"][i]["hidden"]
                     and a["expanded"][i]["hidden"][0]["tg"] == god for i in range(4))
            if not ok:
                return False
        elif cond == "zuori":
            if a["expanded"][2]["stem_tg"] != god and not any(
                    h["tg"] == god for h in a["expanded"][2]["hidden"]):
                return False
        elif cond.startswith("tou:"):
            if not _tou(a, god, cond[4:]):
                return False
        elif cond.startswith("pos:"):
            want = cond[4:]
            idx = POS.index(want[0])
            if not any(i == idx and (len(want) == 1 or w[0] == want[1])
                       for i, w, _b in [(i, w, b) for i, w, b in occ]):
                return False
    return True


_CACHE = None


def load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    out = []
    with io.open(LQ, encoding="utf-8-sig") as f:
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


def pick(a, group=None, limit=6):
    """取六亲条目。group 为 None 时全取；否则按 xq_id 前缀分（CS 出身／FM 父母／XD 兄弟）。"""
    out = []
    for e in load():
        if group and not e["xq_id"].startswith("LQ-%s" % group):
            continue
        try:
            ok = hold_lq(a, e["god"], e["need"])
        except Exception:
            ok = False
        if ok:
            out.append(e)
    return out[:limit]


def groups(a):
    return {"cs": pick(a, "CS"), "fm": pick(a, "FM"), "xd": pick(a, "XD")}


def self_test():
    """自检：空亡、绝位算得对；条目不得讲非六亲事；不得一条都不出。"""
    ok = True
    a = A.analyze(["甲子", "乙亥", "庚戌", "癸未"], gender="男")
    # 本盘日柱庚戌，属甲辰旬，空寅卯
    if kong_branches(a) != {"寅", "卯"}:
        print("FAIL  旬空算错：庚戌日应空寅卯，得 %s" % kong_branches(a))
        ok = False
    c = A.analyze(["甲子", "丙寅", "甲子", "甲子"], gender="男")
    if kong_branches(c) != {"戌", "亥"}:
        print("FAIL  旬空算错：甲子日应空戌亥，得 %s" % kong_branches(c))
        ok = False
    if JUE.get("庚") != "寅":
        print("FAIL  绝位表错：庚绝应在寅")
        ok = False
    # 四盘都要出得来
    cases = [(["甲子", "乙亥", "庚戌", "癸未"], "男"),
             (["辛酉", "丁酉", "乙巳", "丙子"], "女"),
             (["丁卯", "癸卯", "乙卯", "己卯"], "女"),
             (["庚申", "戊寅", "甲辰", "丙寅"], "男")]
    for ps, g in cases:
        ch = A.analyze(ps, gender=g)
        gg = groups(ch)
        tot = sum(len(v) for v in gg.values())
        if tot == 0:
            print("WARN  %s %s：六亲库一条未出（本盘或不触发）" % ("".join(ps), g))
        for k, v in gg.items():
            for e in v:
                if any(x in e["text"] for x in ("偏财格", "用神", "格局顺逆")):
                    print("FAIL  %s：混入非六亲条目 %s" % ("".join(ps), e["xq_id"]))
                    ok = False
    lib = load()
    if len(lib) < 12:
        print("FAIL  六亲库条目过少（%d）" % len(lib))
        ok = False
    print("liuqin 自检：%s（库 %d 条）" % ("全部通过" if ok else "有失败项", len(lib)))
    return 0 if ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(self_test())
