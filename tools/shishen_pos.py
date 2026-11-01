#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十神定位：财官派的入式一层（乙轨）。

为什么要有这一层
----------------
梁氏批命是**两套分批列叙**（R-MF-001）：
  甲 文人式——调候、格局、喜忌，以八字本身为主（《滴天髓》《栏江网》一路）；
  乙 财官派——十神定位，把母法总则散用于流年、六亲、实务。
本包此前只有甲轨（一到六节全是调候→格局→用神），乙轨一条也没接，
故「事业／财富／寿元」三项与梁氏呼应率为零——不是断不出，是这条路没修。

R-MF-001 之外，R-X13-077 讲得更直：「论命不必以调候、格局为第一优先，
当以『十神定位』为入式」。十神定位不是补充，是另一条并行的入口。

本模块只收「可机械核」的：
  ① 柱位×十神（年上比肩、时上七杀……）
  ② 「坐」的关系（自坐同一十神、七杀坐七杀、自坐七杀带马）
  ③ 数量（天干两比肩、比劫四柱皆见、四见变性、食伤四位）
  ④ 通根（R177：通根到哪一支，即管哪一段年限）
每出一条必附原文编号；条件不成立者不出。宁少不多——R-MF-024：
「吉命不可能件件俱吉」，全盘最多取六条，按「坐＞分柱＞数量」次第取。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A  # noqa: E402

POS = A.POS
TIER = ("本气", "中气", "余气")
# 梁氏柱位年限：R06 明言「月上比肩（16-30岁）」「时上比肩（46岁后）」；
# R177 以年支为同家长／幼年、月支为自身学校阶段、时支为晚年事业根基。
AGE = {"年": "1–15", "月": "16–30", "日": "31–45", "时": "46 以后"}
BIJIE = ("比肩", "劫财")
SHISHANG = ("食神", "伤官")


# ══════════════════════ 一、摆牌：四柱各是什么十神 ══════════════════════
def columns(a):
    """四柱逐柱：天干十神、支本气十神、支中余气十神。日主一栏标「日主」，不算十神。"""
    out = []
    for i, row in enumerate(a["expanded"]):
        hid = [{"tier": TIER[j] if j < 3 else "余气", "stem": h["stem"], "god": h["tg"]}
               for j, h in enumerate(row["hidden"])]
        out.append({
            "pos": POS[i], "pillar": a["pillars"][i], "age": AGE[POS[i]],
            "stem": row["stem"], "stem_god": row["stem_tg"],
            "branch": a["pillars"][i][1],
            "branch_god": hid[0]["god"] if hid else "",
            "hidden": hid,
        })
    return out


def counts(a):
    """十神之量。透干与支本气各计 2，中气 1，余气 1——与推演器 god_strength 同口径。

    另给「位」数（天干一位或地支本气一位），R21 的「天干地支加起来四个」
    与 R09 的「天干两比肩」都是数位，不是称重，故两笔分开算。
    """
    w, n, where = {}, {}, {}
    for row in a["expanded"]:
        if row["stem_tg"] != "日主":
            g = row["stem_tg"]
            w[g] = w.get(g, 0) + 2
            n[g] = n.get(g, 0) + 1
            where.setdefault(g, []).append("透" + row["pos"])
        for j, h in enumerate(row["hidden"]):
            g = h["tg"]
            w[g] = w.get(g, 0) + (2 if j == 0 else 1)
            if j == 0:
                n[g] = n.get(g, 0) + 1
                where.setdefault(g, []).append("支" + row["pos"])
    return {"w": w, "n": n, "where": where}


def _yima_at(a):
    """驿马落哪几柱（R19 要「带马」，须与七杀同宫，不能只问有没有）。"""
    out = set()
    for s in (a.get("shensha") or []):
        if s.get("name") == "驿马":
            for pos, _gz in (s.get("hits") or []):
                out.add(pos)
    return out


# ══════════════════════ 二、坐 ══════════════════════
def sits(a):
    """「坐」在梁氏笔下有两义：同柱上下（自坐）、上一柱压到下一柱（七杀坐七杀）。"""
    cols = columns(a)
    ym = _yima_at(a)
    out = []

    # R27 自坐同一十神：一柱之内干与支本气同神
    for c in cols:
        if c["pos"] == "日":
            continue                      # 日干为日主，无「自坐同神」可言
        if c["stem_god"] and c["stem_god"] == c["branch_god"] \
                and c["stem_god"] not in BIJIE:
            out.append({"kind": "自坐", "pos": c["pos"], "rule": "R27",
                        "text": "%s柱%s坐%s（%s%s）——R27：一柱之内同神重叠，主麻烦；"
                                "%s" % (c["pos"], c["stem_god"], c["branch_god"],
                                        c["pillar"], c["age"],
                                        "%s叠%s" % (c["stem_god"], c["branch_god"]))})

    # R19 自坐七杀带马
    for c in cols:
        if c["pos"] in ym and (c["stem_god"] == "七杀" and c["branch_god"] == "七杀"):
            out.append({"kind": "坐马", "pos": c["pos"], "rule": "R19",
                        "text": "%s柱自坐七杀又带驿马（%s）——R19：外出诸般事皆速，"
                                "其人到处有麻烦，是「是非人」；此类不必再论调候用神"
                                % (c["pos"], c["pillar"])})

    # R-MF-035 七杀坐七杀：上一柱见七杀，下一柱支本气亦七杀
    for i in range(3):
        up, dn = cols[i], cols[i + 1]
        up_sha = (up["stem_god"] == "七杀") or (up["branch_god"] == "七杀")
        if up_sha and dn["branch_god"] == "七杀":
            out.append({"kind": "重叠", "pos": up["pos"] + dn["pos"], "rule": "R-MF-035",
                        "text": "%s柱七杀，%s支本气亦七杀（%s／%s）——R-MF-035："
                                "七杀坐七杀，主有离婚、分居之兆"
                                % (up["pos"], dn["pos"], up["pillar"], dn["pillar"])})
    return out


# ══════════════════════ 三、分柱与数量 ══════════════════════
def _has_god(c, god):
    """某柱是否见某神（天干或支本气）。分柱取象以位为主，藏于中余气者不算。"""
    return c["stem_god"] == god or c["branch_god"] == god


def entries(a):
    """按柱位取象。每柱先坐后分柱，全盘取前六条。"""
    cols = columns(a)
    cnt = counts(a)
    out = []

    for c in cols:
        # R-X13-103 年干财官印主出身
        if c["pos"] == "年" and c["stem_god"] in ("正财", "偏财", "正官", "正印"):
            out.append({"pos": "年", "rule": "R-X13-103", "kind": "出身",
                        "text": "年干%s（%s）——R-X13-103：年干是财、官、印，指向出身良好，"
                                "旧说「书香门第」，纵非富贵亦不失中流" % (c["stem_god"], c["stem"])})
        # R-X13-104 年干七杀通根与否
        if c["pos"] == "年" and c["stem_god"] == "七杀":
            rooted = any(x["god"] == "七杀" and x["tier"] == "本气" for x in c["hidden"])
            out.append({"pos": "年", "rule": "R-X13-104", "kind": "出身",
                        "text": "年干七杀%s——R-X13-104：%s" % (
                            "且通根支中" if rooted else "而不通根",
                            "牵连到本人，性好是非，对内对外多涉是非" if rooted
                            else "只主家道中落，不牵及本人")})
        # R06 比肩分柱
        if c["pos"] in ("年", "月", "时") and _has_god(c, "比肩"):
            say = {"年": "拿不到家里的钱——年柱主家境，须先看家境是否成立；无财可破则不论",
                   "月": "16–30 岁之间男女朋友交不长",
                   "时": "46 岁以后至少改过三个行业"}[c["pos"]]
            out.append({"pos": c["pos"], "rule": "R06", "kind": "分柱",
                        "text": "%s上比肩——R06：%s" % (c["pos"], say)})
        # R184 七杀分柱
        if c["pos"] == "年" and _has_god(c, "七杀"):
            out.append({"pos": "年", "rule": "R184", "kind": "分柱",
                        "text": "年上七杀——R184：主「早年一场凶」，其凶有三种（家道糟、"
                                "为不良少年、体弱），不必三样俱来"})
        if c["pos"] == "时" and _has_god(c, "七杀"):
            out.append({"pos": "时", "rule": "R184", "kind": "分柱",
                        "text": "七杀通根到时支——R184：晚年仍有事业（女命则主晚年仍有"
                                "男人相伴）；七杀在时则性刚"})

    # R09 天干两比肩（日主不算）
    n_bj = cnt["n"].get("比肩", 0)
    if n_bj >= 2 and sum(1 for c in cols if c["pos"] != "日" and c["stem_god"] == "比肩") >= 2:
        out.append({"pos": "全盘", "rule": "R09", "kind": "数量",
                    "text": "天干明见两比肩——R09 五事并列：①兄弟相互缺乏帮助 ②好友之交不长久 "
                            "③夫妻时常不和谐 ④多讲闲话、自找麻烦 ⑤纵成好格亦为劳碌命"})

    # R130 比劫四柱皆见
    if all(_has_god(c, "比肩") or _has_god(c, "劫财") for c in cols):
        out.append({"pos": "全盘", "rule": "R130", "kind": "数量",
                    "text": "比劫四柱皆见——R130：终生不聚财；分段落看，年上比劫多则三十岁前"
                            "聚不起，日时比劫多则晚年方好"})

    # R255 四见变性
    for god, must in (("正官", 4), ("食神", 4), ("伤官", 4)):
        if cnt["n"].get(god, 0) >= must:
            alt = "正官四见变七杀（R255）" if god == "正官" else "食伤四见皆作伤官（R255）"
            out.append({"pos": "全盘", "rule": "R255", "kind": "数量",
                        "text": "%s %d 位——%s" % (god, cnt["n"][god], alt)})

    # R177 通根支位：三处皆可通根，只取最重一条（时支最具体，主晚年事业根基）
    for seg_pos in ("时", "月", "年"):
        c = next((x for x in cols if x["pos"] == seg_pos), None)
        if c and c["branch_god"] in ("七杀", "正财", "偏财", "正印"):
            seg = {"年": "与家长、幼年有关", "月": "主自身与学校阶段",
                   "时": "主晚年事业根基"}[seg_pos]
            out.append({"pos": seg_pos, "rule": "R177", "kind": "通根",
                        "text": "%s通根于%s支——R177：通根所落之支定六亲与年限，%s"
                                % (c["branch_god"], seg_pos, seg)})
            break
    return out[:6]


def shishang_four(a):
    """R21 食神变德／R255：食伤到底几位。两个口径并列，不合并成一个数。"""
    cnt = counts(a)
    pos_n = cnt["n"].get("食神", 0) + cnt["n"].get("伤官", 0)
    w = cnt["w"].get("食神", 0) + cnt["w"].get("伤官", 0)
    return {"by_pos": pos_n, "by_weight": w,
            "detail": "食神 %d 位／伤官 %d 位（天干与支本气计位）"
                      % (cnt["n"].get("食神", 0), cnt["n"].get("伤官", 0))}


def liunian_god(a, gz):
    """流年天干对本日主是什么十神——乙轨「十神散用于流年」的入口。"""
    day = a["pillars"][2][0]
    return {"stem_god": A.ten_god(day, gz[0]),
            "branch_god": A.ten_god(day, A.HIDDEN[gz[1]][0])}


def verdict(a):
    """一句总括：乙轨从哪里入、本盘最重的是哪一神。"""
    cnt = counts(a)
    if not cnt["w"]:
        return ""
    top = sorted(cnt["w"].items(), key=lambda x: -x[1])[:2]
    names = "、".join("%s（%s 处）" % (g, "、".join(cnt["where"].get(g, [])[:3])) for g, _ in top)
    return ("以十神定位入式：本盘以%s为最重。梁氏论命不必以调候格局为先（R-X13-077），"
            "十神定位另是一路；此处只摆牌，断语见下。" % names)


def self_test():
    ok = True
    cases = [(["甲子", "乙亥", "庚戌", "癸未"], "男"),
             (["癸巳", "戊午", "丙午", "壬辰"], "男"),
             (["辛酉", "丁酉", "乙巳", "丙子"], "女")]
    for p, g in cases:
        a = A.analyze(p, gender=g)
        cols = columns(a)
        assert len(cols) == 4, p
        assert cols[2]["stem_god"] == "日主", p
        cn = counts(a)
        assert cn["n"], p
        en = entries(a)
        for e in en:
            assert e["rule"] and e["text"], (p, e)
        print("  %s %s　列 %d／条 %d　%s" % (
            "".join(p), g, len(cols), len(en),
            "；".join(e["rule"] for e in en) or "（无）"))
    print("shishen_pos self-test:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    self_test()
