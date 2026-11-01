#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多因子交叉验证：把「一个信号不下结论」变成可执行的检查。

为什么要有这一件东西

  梁先生有一句诫：「一见未月就说是比劫格——这是机械的、错误的。」
  这句话不是文风问题，是方法问题。凡断语只挂一个信号，就是机械断。
  本器不替批者下断，只做三件事：

    一、**把信号摊开**。每个判断点该看哪几路，逐路列出事实。
    二、**数独立来源**。同一路的两种起法只算一路（如桃花年支起与日支起同属神煞）。
    三、**标矛盾与单薄**。来源不足门槛者，标「不得写肯定句」；
       方向相反者，标「须说明权衡」。这两条一旦标出，底稿里就不许绕过去。

  刻意不做的事：**不替批者定方向**。「倾向」一栏留给批者填，
  因为方向是判断，判断要有依据，依据在 rules.csv 里，不在本器里。

用法：
    python tools/crosscheck.py 甲子 乙亥 庚戌 癸未 --gender 男
    python tools/crosscheck.py 甲子 乙亥 庚戌 癸未 --gender 男 --json
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A  # noqa: E402

# 各判断点的门槛（独立来源数）与必查路数
POINTS = [
    ("格局", 3, ["月令天透地藏", "三合三会", "十神清浊", "日主强弱", "调候需求"]),
    ("用神", 3, ["调候", "扶抑", "通关", "日主十干喜忌", "格局需求", "忌神复核"]),
    ("婚姻", 3, ["妻星／夫星旺衰", "夫妻宫（日支）状态", "神煞落夫妻宫", "十神组合", "刑冲合会"]),
    ("子女", 2, ["官杀（男）／食伤（女）", "时柱子女宫", "大运何时见子星"]),
    ("父母", 3, ["财星位置", "印星位置", "年月柱组合", "年月柱空亡"]),
    ("财富", 3, ["财星透藏", "食伤能否生财", "比劫是否夺财", "财之根气", "调候是否护财"]),
    ("健康", 3, ["五行偏枯", "调候燥湿", "刑冲部位", "日主受克"]),
    ("事业学业", 3, ["格局类型", "十神旺弱", "用神五行", "印星状态", "食伤状态"]),
]


def _ss(res, pos_i, which="stem"):
    """取某柱天干／地支（本气）的十神。analyze 的 expanded 结构。"""
    d = res["expanded"][pos_i]
    if which == "stem":
        return d["stem_tg"]
    return d["hidden"][0]["tg"]


def _has(res, name):
    """神煞中是否见。"""
    for x in res.get("shensha", []):
        if x["name"] == name:
            return bool(x["hits"]), x
    return False, None


def _rel_kinds(res):
    return {r["kind"] for r in res["relations"]}


def build_signals(res):
    """逐判断点摊开信号。每路一条：来源子系统、事实、证据、门槛内是否成立。"""
    P = res["pillars"]
    day, month = P[2][0], P[1][1]
    wx = res["wuxing"]
    out = []

    # ---- 格局 ----
    s = []
    cang = A.HIDDEN[month]
    tou = [g for g in cang if g in (p[0] for p in P)]
    s.append(("十神", "月令%s藏%s；透出者：%s" % (
        month, "／".join(cang), "、".join(tou) if tou else "无"),
        "月令天透地藏", "格局"))
    he = [r for r in res["relations"] if r["kind"] in ("三合", "三会")]
    s.append(("刑冲合会", ("有%s" % "、".join(r["kind"] + "".join(r["members"]) for r in he))
              if he else "无三合三会", "三合三会", "格局"))
    shi = [p[0] for p in P if _ss(res, P.index(p), "stem") in ("食神", "伤官")]
    guan = [p[0] for p in P if _ss(res, P.index(p), "stem") in ("正官", "七杀")]
    s.append(("十神", "食伤透%s；官杀透%s" % (len(shi), len(guan)),
              "十神清浊", "格局"))
    s.append(("五行", "／".join("%s%d" % (k, v) for k, v in wx.items()),
              "日主强弱", "格局"))
    s.append(("用神", "调候：%s" % ("、".join(c["value"] for c in res["th"][:1]) or "未取"),
              "调候需求", "格局"))
    out.append(("格局", 3, s))

    # ---- 用神 ----
    s = []
    s.append(("用神", "调候表取：%s" % ("／".join(
        "%s[%s]" % (c["value"], c["cell_id"]) for c in res["th"]) or "未取"),
        "调候", "用神"))
    s.append(("五行", "日主%s，五行%s" % (day, "／".join("%s%d" % (k, v) for k, v in wx.items())),
              "扶抑", "用神"))
    kinds = _rel_kinds(res)
    s.append(("刑冲合会", "见%s" % "、".join(sorted(kinds)) if kinds else "无刑冲合会",
              "通关", "用神"))
    s.append(("十神", "日主%s 之十干喜忌见 rules.csv「日主喜忌」组" % day,
              "日主十干喜忌", "用神"))
    s.append(("格局", "取格：%s（%s）" % (res["geju"]["name"], res["geju"]["shun"]), "格局需求", "用神"))
    ji = [k for k, v in wx.items() if v >= 4]
    s.append(("五行", "偏多者：%s" % ("、".join(ji) or "无"), "忌神复核", "用神"))
    out.append(("用神", 3, s))

    # ---- 婚姻 ----
    s = []
    star = "正财" if res["gender"] == "男" else "正官"
    pos = [A.POS[i] for i in range(4) if _ss(res, i, "stem") == star]
    s.append(("十神", "%s（%s）透于：%s" % (star, "妻星" if res["gender"] == "男" else "夫星",
                                          "、".join(pos) or "不透"),
              "妻星／夫星旺衰", "婚姻"))
    s.append(("十神", "日支%s，本气%s" % (P[2][1], _ss(res, 2, "branch")),
              "夫妻宫（日支）状态", "婚姻"))
    got = [n for n in ("寡宿", "红艳", "桃花", "华盖")
           if _has(res, n)[0] and any(h[0] == "日" for h in _has(res, n)[1]["hits"])]
    s.append(("神煞", "落日支者：%s" % ("、".join(got) or "无"), "神煞落夫妻宫", "婚姻"))
    s.append(("十神", "官杀透%s、食伤透%s" % (len(guan), len(shi)), "十神组合", "婚姻"))
    s.append(("刑冲合会", "见%s" % "、".join(sorted(kinds)) if kinds else "无",
              "刑冲合会", "婚姻"))
    out.append(("婚姻", 3, s))

    # ---- 子女 ----
    s = []
    zi = "正官" if res["gender"] == "男" else "食神"
    s.append(("十神", "%s（子星）透：%s" % (zi, "是" if any(
        _ss(res, i, "stem") in ("正官", "七杀") for i in range(4)) else "否"),
        "官杀（男）／食伤（女）", "子女"))
    s.append(("十神", "时柱%s，天干%s、地支%s" % (P[3], _ss(res, 3, "stem"), _ss(res, 3, "branch")),
              "时柱子女宫", "子女"))
    s.append(("大运", "大运：%s" % ("、".join(res.get("dayun") or []) or "未给"),
              "大运何时见子星", "子女"))
    out.append(("子女", 2, s))

    # ---- 父母 ----
    s = []
    cai = [A.POS[i] for i in range(4) if _ss(res, i, "stem") in ("正财", "偏财")]
    yin = [A.POS[i] for i in range(4) if _ss(res, i, "stem") in ("正印", "偏印")]
    s.append(("十神", "财星透：%s" % ("、".join(cai) or "无"), "财星位置", "父母"))
    s.append(("十神", "印星透：%s" % ("、".join(yin) or "无"), "印星位置", "父母"))
    s.append(("十神", "年柱%s／月柱%s" % (P[0], P[1]), "年月柱组合", "父母"))
    kn = [k for k in res["kong_hits"] if k["位"] in ("年", "月")]
    s.append(("空亡", "年月落空：%s" % ("、".join("%s%s" % (k["位"], k["落"]) for k in kn) or "无"),
              "年月柱空亡", "父母"))
    out.append(("父母", 3, s))

    # ---- 财富 ----
    s = []
    s.append(("十神", "财星透于：%s" % ("、".join(cai) or "不透"), "财星透藏", "财富"))
    s.append(("十神", "食伤透：%s" % ("、".join(
        [A.POS[i] for i in range(4) if _ss(res, i, "stem") in ("食神", "伤官")]) or "无"),
        "食伤能否生财", "财富"))
    s.append(("十神", "比劫透：%s" % ("、".join(
        [A.POS[i] for i in range(4) if _ss(res, i, "stem") in ("比肩", "劫财")]) or "无"),
        "比劫是否夺财", "财富"))
    # 财之五行＝日主所克者（庚金克木 → 财为木）
    order = "木火土金水"
    me = A.STEM_ELEM[day]
    cai_elem = order[(order.index(me) + 2) % 5]
    root = [A.POS[i] for i, p in enumerate(P)
            if any(A.STEM_ELEM[g] == cai_elem for g in A.HIDDEN[p[1]])]
    s.append(("藏干", "财属%s；通根之支：%s" % (cai_elem, "、".join(root) or "无"),
              "财之根气", "财富"))
    s.append(("用神", "调候取：%s" % ("／".join(c["value"] for c in res["th"]) or "未取"),
              "调候是否护财", "财富"))
    out.append(("财富", 3, s))

    # ---- 健康 ----
    s = []
    s.append(("五行", "／".join("%s%d" % (k, v) for k, v in wx.items())
              + ("　缺%s" % "、".join(res["missing"]) if res["missing"] else ""),
              "五行偏枯", "健康"))
    s.append(("用神", "调候：%s（%s月生）" % (
        "／".join(c["value"] for c in res["th"]) or "未取", month), "调候燥湿", "健康"))
    chong = [r for r in res["relations"] if r["kind"] in ("六冲", "六害", "相刑", "三刑")]
    s.append(("刑冲合会", "见%s" % "、".join(r["kind"] for r in chong) if chong else "无冲害刑",
              "刑冲部位", "健康"))
    s.append(("十神", "日主%s 受克于：%s" % (day, "、".join(
        [A.POS[i] for i in range(4) if _ss(res, i, "stem") in ("正官", "七杀")]) or "无"),
        "日主受克", "健康"))
    out.append(("健康", 3, s))

    # ---- 事业学业 ----
    s = []
    s.append(("格局", "%s，%s" % (res["geju"]["name"], res["geju"]["verdict"].split("（")[0]), "格局类型", "事业学业"))
    s.append(("十神", "食伤%s、官杀%s、印%s" % (len(shi), len(guan), len(yin)),
              "十神旺弱", "事业学业"))
    s.append(("用神", "调候取：%s" % ("／".join(c["value"] for c in res["th"]) or "未取"),
              "用神五行", "事业学业"))
    s.append(("十神", "印星：%s" % ("、".join(yin) or "不透"), "印星状态", "事业学业"))
    s.append(("十神", "食伤：%s" % ("、".join(
        [A.POS[i] for i in range(4) if _ss(res, i, "stem") in ("食神", "伤官")]) or "无"),
        "食伤状态", "事业学业"))
    out.append(("事业学业", 3, s))

    return out


def crosscheck(res):
    """输出判断点 × 信号的矩阵 + 门槛判定。"""
    res = dict(res)
    res.setdefault("shensha", A.shensha(res["pillars"]))
    res.setdefault("kong_hits", [])
    res.setdefault("dayun", [])
    rows = []
    for name, floor, sig in build_signals(res):
        # 独立来源：同一子系统只算一路
        srcs = []
        for src, fact, slot, _ in sig:
            if src not in srcs:
                srcs.append(src)
        n = len(srcs)
        verdict = []
        if n < floor:
            verdict.append("来源 %d < 门槛 %d：**信号单薄，不得写肯定句**" % (n, floor))
        rows.append({"point": name, "floor": floor, "n": n,
                     "sources": srcs, "signals": sig, "verdict": verdict})
    return rows


def render(rows):
    L = ["# 多因子交叉验证（信号表）", "",
         "> 本表只摊信号、数来源、标缺口。**倾向一栏留给批者填**——方向是判断，",
         "> 判断要有依据，依据在 rules.csv，不在本器。", ""]
    for r in rows:
        L.append("## %s（门槛 %d 路，实得 %d 路）" % (r["point"], r["floor"], r["n"]))
        L.append("")
        L.append("| # | 来源 | 事实 | 该查的路 | 倾向（批者填） |")
        L.append("|---|---|---|---|---|")
        seen = set()
        for i, (src, fact, slot, _) in enumerate(r["signals"], 1):
            if src in seen:
                src_cell = "%s（同源，不重计）" % src
            else:
                src_cell = "%s（计入）" % src
                seen.add(src)
            L.append("| %d | %s | %s | %s |  |" % (i, src_cell, fact, slot))
        L.append("")
        for v in r["verdict"]:
            L.append("> ⚠️ " + v)
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="多因子交叉验证（只摊信号，不代下断）")
    ap.add_argument("pillars", nargs="+")
    ap.add_argument("--gender", choices=["男", "女"], required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if len(a.pillars) != 4:
        ap.error("须给四个干支，按年 月 日 时")
    res = A.analyze(a.pillars, a.gender)
    rows = crosscheck(res)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(render(rows))


if __name__ == "__main__":
    main()
