#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""详批命书生成器（XP 批例六段体例）

analyze.py 出的是「底稿」——结构、格值、命中清单，它自己也不讳言「做不出命书」。
本脚本把那堆底稿按《细批终身详解》的批例体例重排成一份命书：
命序 → 已知因 → 总评 → 妻／财／子／禄 → 大运分述 → 提要 → 边界 → 依据表。

两条硬规矩：

  一、**断语只用能核到位的规则**。命中的规则里，凡触发标签只有「十神:某」而无
      「位」（日支／年干／时柱／月支…）者，一律不进断语——因为「偏财出现」不等于
      「日支坐偏财」，这是本包最容易出的误命中。这类规则另列「待人工核位」。
  二、**断语即原文**。命书里每句判断后面都挂 rule_id 与证据等级，不写无据之词；
      本包无据的项，明写不判，不以常法补。

用法：
    python tools/mingshu.py 甲子 乙亥 庚戌 癸未 --gender 男 --start-age 10
    python tools/mingshu.py 甲子 乙亥 庚戌 癸未 --gender 男 --start-age 10 --out 命书/x.md
    python tools/mingshu.py ... --dayun 丙子,丁丑,戊寅    # 也可自排
"""
import argparse
import datetime
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A  # noqa: E402
import panduan as PD  # noqa: E402

# 只有「十神:某」一类标签的规则，不足以定断语（十神出现 ≠ 十神在某位）
POS_DIMS = ("月", "日主", "支", "关系", "大运", "五行缺")

# conditions 里的「位」词 → 取哪一位的天干十神；本气一词另标，走本气比对
WEI_PAT = [
    (r"日支所藏本气|日支本气|日支所藏之?本气", "日", True),
    (r"自坐", "日", True),
    (r"日支为", "日", True),
    (r"年干", "年", False),
    (r"月干|月上", "月", False),
    (r"时干|时柱", "时", False),
]


def wei_check(r, f):
    """按原文所要求的「位」复核一条十神类命中。

    返回 ok／unsure／no／n/a：
      ok    —— 该位的十神与规则所指相符
      unsure—— 天干不符，但该位藏干中有该十神（藏干口径，须人工定）
      no    —— 该位天干与本气皆无，属误命中
      n/a   —— conditions 未提位，无法复核
    """
    cond = r.get("conditions") or ""
    named = {t.split(":", 1)[1] for t in (r.get("trigger_tags") or "").split("|")
             if t.startswith("十神:")}
    if not named:
        return "n/a"
    for pat, pos, is_benqi in WEI_PAT:
        if not re.search(pat, cond):
            continue
        stem_tg = f["stem_tg"][pos]
        benqi = f["branch_tg"][pos]
        hidden = set(f["branch_hidden"][pos])
        if is_benqi:
            if named & {benqi}:
                return "ok"
            if named & hidden:
                return "unsure"
            return "no"
        if named & {stem_tg}:
            return "ok"
        if named & hidden:
            return "unsure"
        return "no"
    return "n/a"


def paipai(month_pillar, forward, n=8):
    """自月柱起排 n 步大运；阳男阴女顺行、阴男阳女逆行。"""
    i = A.JIAZI.index(month_pillar)
    step = 1 if forward else -1
    return [A.JIAZI[(i + step * k) % 60] for k in range(1, n + 1)]


# ══════════════════════════════════════════════════════════════════════════
# 结构层（E6）：天干五合、空亡、调候向背、全流对撞、流年
#
# 这些是算得出来的，不需要 rule_id 撑。Part 42 首版为了让交付件「零工程标记」，
# 把它们连同证据链一起删了——脏水与孩子一起泼掉。此处补回。
# ══════════════════════════════════════════════════════════════════════════

GAN_HE = [("甲", "己"), ("乙", "庚"), ("丙", "辛"), ("丁", "壬"), ("戊", "癸")]
ZHI12 = "子丑寅卯辰巳午未申酉戌亥"
POS4 = "年月日时"


def gan_he(a):
    """天干五合。本造乙庚合：阳日主对正财，连克带合。"""
    st = [r["stem"] for r in a["expanded"]]
    pos = {r["stem"]: r["pos"] for r in a["expanded"]}
    return ["%s%s与%s%s合" % (x, pos[x], y, pos[y]) for x, y in GAN_HE if x in st and y in st]


def xun_kong(pillar):
    """一柱之旬空两支：旬首之后第十、十一支，即本旬所无之二支。

    旧写法取旬首前二支，只在甲子旬偶合；庚戌属甲辰旬，旧法误报戌亥，
    实为寅卯。此误入过 {{空亡}} 一栏，Part 44 改正。
    """
    i = A.JIAZI.index(pillar)
    head = i - i % 10
    return A.JIAZI[(head + 10) % 60][1], A.JIAZI[(head + 11) % 60][1]


def kongwang(a):
    """空亡两说：按日柱旬、按年柱旬。基准包内未定，两说并列，不代裁。"""
    return {"日柱旬": xun_kong(a["pillars"][2]), "年柱旬": xun_kong(a["pillars"][0])}


def tiaohou_chars(a):
    v = a["th"][0]["value"] if a["th"] else ""
    return [c for c in v if c in "甲乙丙丁戊己庚辛壬癸"]


def dayun_tiaohou(a, dayun):
    """每步大运补不补调候字：看运干与运支所藏。纯结构，不判吉凶。"""
    want = tiaohou_chars(a)
    out = []
    for gz in dayun:
        got = []
        if gz[0] in want:
            got.append("运干%s" % gz[0])
        for h in A.HIDDEN.get(gz[1], []):
            if h in want:
                got.append("支藏%s" % h)
        out.append((gz, got))
    return out


def rel_between(x, y):
    """两支之间的关系名。三合三会要三支，另算。"""
    out = []
    if {x, y} in [set(p) for p in A.CHONG]:
        out.append("冲")
    if {x, y} in [set(p) for p in A.HAI]:
        out.append("害")
    if {x, y} in [set(p) for p in A.LIUHE]:
        out.append("六合")
    if {x, y} in [set(p) for p in A.XING_PAIR]:
        out.append("刑")
    if x != y and any(x in g and y in g for g in A.XING3):
        out.append("刑")
    if x == y and x in A.SELF_XING:
        out.append("自刑")
    return out


def quanliu_rows(a, dayun):
    """全流冲刑会合：运支 × 流年支撞出的结构。只列结构，不列吉凶。"""
    br = [r["branch"] for r in a["expanded"]]
    rows = []
    for gz in dayun:
        y = gz[1]
        for nb in ZHI12:
            hit = []
            for k in rel_between(y, nb):
                hit.append("运支与流年%s" % k)
            for i, b in enumerate(br):
                for k in rel_between(nb, b):
                    hit.append("%s%s%s" % (nb, POS4[i], k))
            for grp, nm in ((A.SANHE, "三合"), (A.SANHUI, "三会")):
                for g in grp:
                    st = set(g)
                    if y in st and nb in st and y != nb:
                        rest = [b for b in st if b not in (y, nb)]
                        if all(r in br for r in rest):
                            hit.append("运%s年%s与柱%s凑成%s全" % (y, nb, "".join(rest), nm))
            if hit:
                rows.append((gz, nb, "；".join(dict.fromkeys(hit))))
    return rows


def liunian_rows(a, dayun, start_age, birth_year, y0, n=6):
    """自 y0 起 n 个流年：干支、虚岁、所在大运、与四柱及运支的关系。"""
    if not birth_year:
        return []
    base = A.JIAZI.index(a["pillars"][0])
    br = [r["branch"] for r in a["expanded"]]
    out = []
    for y in range(y0, y0 + n):
        gz = A.JIAZI[(base + (y - birth_year)) % 60]
        age = y - birth_year + 1
        step = (age - start_age) // 10
        dy = dayun[step] if 0 <= step < len(dayun) else ""
        rels = []
        for i, b in enumerate(br):
            for k in rel_between(gz[1], b):
                rels.append("流年%s%s%s" % (gz[1], POS4[i], k))
        if dy:
            for k in rel_between(gz[1], dy[1]):
                rels.append("与运支%s%s" % (dy[1], k))
        out.append((y, gz, age, dy, rels))
    return out


def wei_facts(a):
    """把「位」算出来：干在何柱、支之本气十神、财官之透藏。"""
    day = a["pillars"][2][0]
    f = {"stem_tg": {}, "branch_tg": {}, "branch_hidden": {}}
    for r in a["expanded"]:
        f["stem_tg"][r["pos"]] = r["stem_tg"]
        f["branch_tg"][r["pos"]] = A.ten_god(day, A.HIDDEN[r["branch"]][0])
        f["branch_hidden"][r["pos"]] = [h["tg"] for h in r["hidden"]]
    tg = a["ten_gods"]
    f["cai_stems"] = [p for p in A.POS if f["stem_tg"][p] in ("正财", "偏财")]
    f["guan_stems"] = [p for p in A.POS if f["stem_tg"][p] in ("正官", "七杀")]
    f["cai_hidden"] = [p for p in A.POS
                       if any(x in ("正财", "偏财") for x in f["branch_hidden"][p])]
    f["guan_hidden"] = [p for p in A.POS
                        if any(x in ("正官", "七杀") for x in f["branch_hidden"][p])]
    f["shi"] = [x for x in ("食神", "伤官") if tg.get(x)]
    f["day_tg"] = f["branch_tg"]["日"]
    return f


def ge_gate(r):
    """凡原文以「格已定」为前提者，本包一律不进断语。

    格局在包内为开放项（F05），任何「已判为某格」「格＝某」的规则，前提都不成立；
    不是待核位置，是前提缺失。返回 True 表示须剔出断语。
    """
    cond = r.get("conditions") or ""
    return bool(re.search(r"格＝|已判为|定正官格|成.{0,3}格|格局|月令为当令|^\[[^\]]*\]\s*格\s*\+", cond))


# 体例类：只讲次序与体例，不构成本造断语。命中亦不作断语，列在附三。
BODY_IDS = {
    "R-JB-007", "R-JB-008", "R-JB-022", "R-JB-155", "R-JB-164",
    "R-X11-001", "R-X11-002", "R-X11-003",
}

# 前提复核表：规则成立另有前提，本造前提不成立者剔出断语，并记明理由。
# 这张表须随规则入库同步扩充；未列入者走位条件复核或交人工。
PREMISE = {
    "R-SZ-022": (lambda c: c["a"]["pillars"][1][1] not in "辰戌丑未", "须月支为辰戌丑未，本造月支非四库"),
    "R-SZ-024": (lambda c: c["a"]["pillars"][1][1] not in "辰戌丑未", "须先成立墓库运，本造月支非四库"),
    "R-SZ-029": (lambda c: c["forward"], "须大运逆排，本造顺排"),
    "R-SZ-036": (lambda c: not c["a"]["missing"], "须五行有缺，本造不缺"),
    "R-SZ-041": (lambda c: True, "须逐年流年，流年层未入库"),
    "R-SZ-046": (lambda c: not any((r.get("kind") or "") in ("三刑", "双冲")
                                   or "全三刑" in (r.get("kind") or "")
                                   for r in c["a"]["relations"]),
                 "须本命已有双冲或全三刑，本造无"),
    "R-SZ-047": (lambda c: bool(c["f"]["cai_stems"] or c["f"]["cai_hidden"])
                 and bool(c["f"]["guan_hidden"] or c["f"]["guan_stems"]),
                 "须某六亲星全不见，本造财官俱在"),
    "R210": (lambda c: True, "须给定年份，未给"),
    "R-SS-020": (lambda c: True, "须格已定，格局未裁"),
    "R-SS-027": (lambda c: True, "须格已定，格局未裁"),
    "R-SS-038": (lambda c: True, "须格已定，格局未裁"),
}


GE_NAME = {"正财": "正财格", "偏财": "偏财格", "正官": "正官格", "七杀": "七杀格",
           "正印": "正印格", "偏印": "偏印格", "食神": "食神格", "伤官": "伤官格",
           "比肩": "建禄格", "劫财": "月刃格"}


def qu_ge(a):
    """取格。月令透干为极限（R73）；只许取月令，不许取他支之天透地藏（R213）。

    本气先于中气、余气。所藏皆不透则无格可定，返回 None——不拿常法补。
    返回 (格名, 说明)。
    """
    month = a["pillars"][1][1]
    day = a["pillars"][2][0]
    stems = [r["stem"] for r in a["expanded"]]
    pos = {r["stem"]: r["pos"] for r in a["expanded"]}
    for s in A.HIDDEN[month]:
        if s in stems:
            tg = A.ten_god(day, s)
            return (GE_NAME.get(tg, tg + "格"),
                    "%s藏%s，%s透%s干" % (month, s, s, pos.get(s, "")))
    return None, "%s所藏皆不透干，无格可定" % month


def ge_ok(r, ge):
    """格级门控：原文以「某格」为前提者，须所定之格相符。

    conditions 未涉格者，此门不拦。泛称「已知格局／进入表述」者，格已定即可。
    """
    c = r.get("conditions") or ""
    if "格" not in c:
        return True
    if not ge:
        return False
    named = re.findall(r"(正财格|偏财格|正官格|七杀格|正印格|偏印格|食神格|伤官格|羊刃格|建禄格)", c)
    if not named:
        return True
    return ge in named


# 原文属「辨异／正名／纠误」一类者，是界定而非断语：可用以定名，不可当批词。
BIANYI = ("辨", "纠误", "要件", "之别", "真义", "反对", "误", "读法", "话术")


def yinyang_ok(r, a):
    """日主阴阳门。conditions 或原文点名「阴日主／阳日主」者，须与日主相符。

    这一维 Part 42 首版漏了：位复核只管位，管不了阴阳，于是「阴日主劫财合偏财」
    一类条子直接漏进阳日主的命书里。
    """
    day = a["pillars"][2][0]
    yang = day in A.YANG
    c = r.get("conditions") or ""
    t = r.get("rule_text") or ""
    for src in (c, t):
        if "阴日主" in src and "阳日主" not in src:
            return not yang
        if "阳日主" in src and "阴日主" not in src:
            return yang
    return True


def need_calc(r):
    """conditions 标了 [可算] 者，须按该条自己的算式逐条算，本轮不自动放行。"""
    return "[可算]" in (r.get("conditions") or "")


def is_bianyi(r):
    return any(k in (r.get("theme") or "") for k in BIANYI)


def premise_fail(r, ctx):
    """返回剔除理由；None 表示前提无碍。"""
    fn = PREMISE.get(r["rule_id"])
    if fn and fn[0](ctx):
        return fn[1]
    return None


def split_hits(a, f, ctx):
    """命中分段：可入命书／待人工／体例／误命中（前提不成立或位不符）。"""
    usable, pending, body, wrong = [], [], [], []
    for r, _ in a["rule_hit"]:
        tags = [t for t in (r.get("trigger_tags") or "").split("|") if t]
        if tags == ["恒真"] or r["rule_id"] in BODY_IDS:
            body.append(r)
            continue
        why = premise_fail(r, ctx)
        if why:
            wrong.append((r, why))
            continue
        if ge_gate(r):
            pending.append(r)
            continue
        if not ge_ok(r, ctx.get("ge")):
            pending.append(r)       # 格级规则：所定之格不符，或格未定
            continue
        if not yinyang_ok(r, ctx["a"]):
            wrong.append((r, "原文限阴日主或阳日主，本造日主不符"))
            continue
        if need_calc(r):
            pending.append(r)       # 带 [可算] 标记，须按该条算式逐条算
            continue
        if any(t.split(":")[0] in POS_DIMS for t in tags):
            usable.append(r)
            continue
        v = wei_check(r, f)
        if v == "ok":
            usable.append(r)
        elif v == "no":
            wrong.append((r, "原文所指之位不符"))
        elif v == "unsure":
            pending.append(r)       # 藏干口径，须人工定
        else:
            # n/a：原文 conditions 未提位。位复核管不着这一类，不得据以拦下。
            # 全库 798 条中只有 27 条 conditions 带位词，若把 n/a 也拦，等于用
            # 一把只该管 27 条的尺量了全部——Part 42 首版即错在此。
            usable.append(r)
    return usable, pending, body, wrong


# 按批命环节取料。这一层不靠 trigger_tags——标签为空的关键条（取格法 R73、
# 格局与性格 R26 等）永远进不了标签匹配，可它们恰恰是批命最先要用的。故按 theme
# 归环节，列出供批者自取。全库 798 条里 conditions 带位词者只有 27 条，tags 为空
# 者亦不在少数；这是检索层的硬伤，不是加几个标签能补的。
LENS = {
    "取格": ("取格",),
    "格局与性情": ("性情", "格局与性格", "格局性格"),
    "日干自坐": ("日干自坐", "自坐"),
    "调候与身强弱": ("夏冬",),
    "根气轻重": ("根气",),
    "食财关系": ("食神生财", "偏财之明暗", "偏财格"),
    "大运诸法": ("十干败亡", "墓库运", "冲提", "接角", "空亡"),
    "寿元": ("寿元",),
    "批例体例": ("纲目",),
}


def pull_by_lens():
    """按环节取料，返回 [(环节, [rule…])]。"""
    out = []
    for sec, kws in LENS.items():
        got = [r for r in A.RULES
               if r.get("deterministic_use") != "禁止"
               and any(k in (r.get("theme") or "") for k in kws)]
        if got:
            out.append((sec, got))
    return out


def quote_rule(r, n=170):
    """原文摘句 + 出处三件套。"""
    return ("%s〔%s｜%s｜%s｜%s〕"
            % (A.quote(r["rule_text"], n), r["rule_id"], r["evidence_grade"],
               r["verification_status"], r["source_locator"]))


def render(a, start_age, dayun, forward):
    day = a["pillars"][2][0]
    month = a["pillars"][1][1]
    f = wei_facts(a)
    ge, ge_why = qu_ge(a)
    ctx = {"a": a, "f": f, "forward": forward, "ge": ge}
    usable, pending, body, wrong = split_hits(a, f, ctx)
    xt = a["xingtai"]
    L = []

    def P(s=""):
        L.append(s)

    # ── 命序 ──
    P("# 详批命书")
    P()
    P("> 规格：大批（大流年）。六段体例依《细批终身详解》批例；大运批导依《子平母法》；"
      "日主×月令条依《金不换大运详解》。")
    P("> 每条断语后附出处与证据等级。本包无据者明写不判，不以常法补。")
    P()
    P("---")
    P()
    P("## 命序")
    P()
    P("**四柱**：%s" % "　".join(a["pillars"]))
    P()
    P("**%s命**" % (a["gender"] or "未注"))
    P()
    P("**起运**：%d 岁（虚岁口径，若用周岁整体减一）" % start_age)
    P()
    P("**运序**：%s行，自月柱%s排——%s。"
      % ("阳男顺" if forward and a["gender"] == "男" else
         ("阴男逆" if not forward and a["gender"] == "男" else
          ("阳女逆" if not forward else "阴女顺")),
         a["pillars"][1], "、".join(dayun)))
    P()
    P("---")
    P()

    # ── 一、已知因 ──
    P("## 一、已知因")
    P()
    P("此段只列结构事实，不带断语。梁氏批例之例，先摆事实，再下判断。")
    P()
    P("一：日主%s，生%s月，%s生。" % (day, month, "夏" if xt.get("xiadong") and month in "巳午未" else
                                ("冬" if xt.get("xiadong") else "非夏冬")))
    mh = A.HIDDEN[month]
    P()
    P("二：月令%s，本气%s为%s，中气%s为%s。%s"
      % (month, mh[0], A.ten_god(day, mh[0]),
         mh[1] if len(mh) > 1 else "无", A.ten_god(day, mh[1]) if len(mh) > 1 else "",
         "本气不透干。" if mh[0] not in [r["stem"] for r in a["expanded"]] else "本气透干。"))
    P()
    P("三：天干——%s。" % "，".join("%s%s（%s）" % (r["pos"], r["stem"], r["stem_tg"])
                                for r in a["expanded"]))
    P()
    P("四：地支——%s。日支%s本气%s（%s），时支%s本气%s（%s）。"
      % ("、".join(r["branch"] for r in a["expanded"]),
         a["pillars"][2][1], A.HIDDEN[a["pillars"][2][1]][0], f["day_tg"],
         a["pillars"][3][1], A.HIDDEN[a["pillars"][3][1]][0], f["branch_tg"]["时"]))
    P()
    P("五：五行——%s，%s。"
      % ("、".join("%s%d" % (k, v) for k, v in a["wuxing"].items() if v),
         ("缺" + "、".join(a["missing"])) if a["missing"] else "不缺"))
    P()
    P("六：财星——天干%s；支藏%s。官星——天干%s；支藏%s。"
      % ("、".join(f["cai_stems"]) or "不透",
         "、".join(f["cai_hidden"]) or "无",
         "、".join(f["guan_stems"]) or "不透",
         "、".join(f["guan_hidden"]) or "无"))
    P()
    rels = [r for r in a["relations"] if r.get("kind")]
    if rels:
        P("七：刑冲合会——%s。" % "；".join(
            "%s（%s）〔%s｜%s｜%s〕" % (
                r["kind"], "、".join(r.get("positions") or r.get("members") or []),
                (r.get("cell") or {}).get("cell_id", ""),
                (r.get("cell") or {}).get("evidence_grade", ""),
                (r.get("cell") or {}).get("verification_status", ""))
            for r in rels))
    else:
        P("七：刑冲合会——四柱无冲、无合、无刑、无害。")
    P()
    P("八：日主根气——%s。" % "、".join(
        "%s在%s%s" % (day, r["branch"], A.stage12(day, r["branch"])) for r in a["expanded"]))
    P()
    thv = a["th"][0]["value"] if a["th"] else "（无可用格值）"
    if a["th"] and len(thv) > 1:
        _parts = re.split("[、／]", thv if "、" in thv or "／" in thv else "、".join(thv))
        _gods = "、".join("%s（%s）" % (c, A.ten_god(day, c)) for c in _parts if c)
        P("九：调候——%s日×%s月，表列%s，同气不同性、各挂其神：%s；先后再定，不作并列不分。"
          % (day, month, thv, _gods))
    else:
        P("九：调候——%s日×%s月，表列%s%s。"
          % (day, month, thv,
             "，并列不分正副〔%s｜%s｜%s〕" % (a["th"][0]["cell_id"], a["th"][0]["evidence_grade"],
                                         a["th"][0]["verification_status"]) if a["th"] else "，本包无格值，不判"))
    P()
    if a["pillars"][2] in A.KUIGANG:
        P("十：日柱%s，属魁罡名目。成立要件未入库，此条不判。" % a["pillars"][2])
    else:
        P("十：日柱%s，非魁罡名目。" % a["pillars"][2])
    P()
    P("---")
    P()

    # ── 二、总评 ──
    P("## 二、总评")
    P()
    if a["th"]:
        P("**贵造%s日生于%s月，必以%s为调候用神。**〔%s｜%s｜%s〕"
          % (day, month, thv, a["th"][0]["cell_id"], a["th"][0]["evidence_grade"],
             a["th"][0]["verification_status"]))
        P()
    if xt.get("xiadong"):
        P("月支%s属%s，依原文「四柱出生于夏、冬之人，以调候用神为第一，并没有身强、身弱的问题」"
          "〔R-SZ-016｜E3｜部分核〕，**此造不得套身弱不能托财官，亦不得作克泄交加论**。"
          % (month, "夏" if month in "巳午未" else "冬"))
        P()
    gj = a.get("geju") or {}
    if gj:
        v = gj["verdict"]
        if v.startswith("结构无破"):
            short = "格无破"
        elif v.startswith("结构有破"):
            short = "有破而有救"
        elif v.startswith("结构破"):
            short = "格破"
        elif v.startswith("该逆得逆"):
            short = "逆用得宜"
        elif v.startswith("该逆不逆"):
            short = "该逆不逆"
        elif v.startswith("反克之神仅藏"):
            short = "制神力薄"
        else:
            short = "另途见"
        how = gj["how"] if gj["how"].startswith("月令") else "月令%s，%s" % (month, gj["how"])
        P("**取格：%s。** %s；此格属%s，%s。"
          % (gj["name"], how, gj["shun"], short))
        if gj.get("waige"):
            P()
            P("%s。" % gj["waige"])
    P()
    zhu = []
    if f["cai_stems"] or f["cai_hidden"]:
        zhu.append("财")
    if f["guan_stems"]:
        zhu.append("官")
    P("**此造之骨在%s。** 财星%s，官星%s——%s"
      % ("与".join(zhu) if zhu else "食伤",
         "双透" if len(f["cai_stems"]) >= 2 else ("透干" if f["cai_stems"] else "不透"),
         "透干" if f["guan_stems"] else "不透",
         "官藏而财透，事以财为主、以官为次。" if (f["cai_stems"] and not f["guan_stems"])
         else "财官俱见，须分主从。" if (f["cai_stems"] and f["guan_stems"])
         else "官透而财藏，事以官为主。" if (f["guan_stems"] and not f["cai_stems"])
         else "财官俱不透，只以食伤、印比论。"))
    P()
    P("---")
    P()

    # ── 三至六：妻财子禄 ──
    used = set()

    def seg(title, keys, fallback, extra=()):
        P("## %s" % title)
        P()
        got = [r for r in usable
               if r["rule_id"] not in used and any(k in r["theme"] for k in keys)]
        for r in got:
            used.add(r["rule_id"])
        if got:
            for r in got[:3]:
                P("- " + quote_rule(r))
                P()
        elif extra:
            # 规则库按主题捞不到料时，走乙轨（十神定位）的可算三条——
            # 命书的「四、财」此前只写「无可用之规则入库，不判」，那是库的缺口冒充本盘无事。
            for t in extra:
                P("- " + PD._strip_ids(t))
                P()
        else:
            P(fallback)
            P()
        P("---")
        P()

    seg("三、妻", ["妻", "夫妻"], "妻宫无可用之规则入库，本命书不判。只列结构：日支%s本气%s（%s）。"
        % (a["pillars"][2][1], A.HIDDEN[a["pillars"][2][1]][0], f["day_tg"]),
        [e["text"] for e in PD.marriage_struct(a)])
    seg("四、财", ["财"], "财星无可用之规则入库，本命书不判。",
        [e["text"] for e in PD.cai_view(a)])
    seg("五、子", ["子女"], "子星无可用之规则入库，本命书不判。只列结构：官星%s。"
        % ("、".join(f["guan_hidden"]) + "（藏）" if f["guan_hidden"] else "不见"))
    seg("六、禄（兼寿元）", ["禄", "寿元", "根气"], "寿元无可用之规则入库，本命书不判。",
        [e["text"] for e in PD.health_view(a)])

    rest = [r for r in usable if r["rule_id"] not in used]
    if rest:
        P("## 六·补、其余可核断语")
        P()
        P("下列规则原文所要求的位已逐条核过，可用，但不属妻财子禄四段，另列于此。")
        P()
        for r in rest:
            P("- " + quote_rule(r))
            P()
        P("---")
        P()

    # ── 七、大运分述 ──
    P("## 七、大运分述")
    P()
    P("依《子平母法》大运批导：细批之大运只批纲目、不批细则，妻财子禄另立分项，"
      "免与大运批注重叠〔R-JB-164｜E3｜部分核〕。以下各步，各出一纲。")
    P()
    P("本节只出五法（十干败亡／墓库／空亡／接角／冲提）。日主×月令条（如 R-JB-108）"
      "对顺逆运各步另有喜忌，已见前节，不在此重复。")
    P()
    for i, info in enumerate(a["dayun"], 1):
        lo = start_age + (i - 1) * 10
        P("**%d、%s（%d 岁至 %d 岁）**" % (i, info["gz"], lo, lo + 9))
        hits = info.get("hits") or []
        if hits:
            for h in hits:
                P("- " + h)
        else:
            P("- 本包五法皆未触发。")
        P()
    P("---")
    P()

    # ── 八、提要 ──
    P("## 八、提要")
    P()
    P("**一：此造以调候为第一，用%s%s。**"
      % (thv, "；冬生不论身强弱，全篇禁引身弱不能托财官与克泄交加" if xt.get("xiadong") else ""))
    P()
    if a["dayun"]:
        heavy = [d for d in a["dayun"] if len(d.get("hits") or []) >= 2]
        if heavy:
            P("**二：大运之中，%s所聚之法最多，为全篇须预为之备者。**"
              % "、".join("%s（第%d步，%d 法）" % (d["gz"], d["n"], len(d["hits"])) for d in heavy))
        else:
            P("**二：大运各步未见两法以上同聚者，无特别须预为之备的一步。**")
        P()
    P("**三：%s**" % ("财官主从见总评，取用次序以调候居首、扶抑居末（身强弱为初阶，"
                    "夏冬豁免）〔R-SZ-010～016〕。" if xt.get("xiadong")
                    else "身强弱须在前四项排除后才论，不可一上手即判强弱〔R-SZ-015〕。"))
    P()
    P("---")
    P()

    # ── 九、边界 ──
    P("## 九、边界")
    P()
    ev = {}
    for r in usable:
        ev[r["evidence_grade"]] = ev.get(r["evidence_grade"], 0) + 1
    P("**一、证据等级。** 本命书所用规则：%s（另有待人工核位 %d 条、剔除 %d 条，见附二、附四）。"
      "凡 E4 字幕者只能作参考，不能作定论；"
      "E1 者仅限格值本身（调候表、刑冲表），不因格值为 E1 而令所引规则升等。"
      % ("、".join("%s %d 条" % (k, v) for k, v in sorted(ev.items())) or "无",
         len(pending), len(wrong)))
    P()
    P("**二、空亡基准未定。** 本包按日柱取旬空；若按年柱取，结论可能相反。"
      "此层包内空白（R-SZ-025 未定基准，U30 只登记四大空亡），须两说并列看。")
    P()
    P("**三、规格。** 本命书为大批，无流月。流月层未入库，不以常法补。")
    P()
    P("**四、未判之项。** 格局成否（F05 开放）、魁罡成立与否（要件未入库）、伏吟、"
      "三合会配财、日主入墓、流年诸法——皆本包无据，非无结论。")
    P()
    P("**五、不居包准。** 原文：「不论是简批八字，或者是细批流年；切忌以「包准」自居……"
      "但能有百分之七十之应验性，就可以视之为合理合宜的标准了。」"
      "所批各条，验与不验，仍须以来客实事回证。")
    P()
    P("---")
    P()

    # ── 附：依据表 ──
    P("## 附一、批词依据表")
    P()
    P("| 规则 | 主题 | 等级 | 状态 | 出处 |")
    P("|---|---|---|---|---|")
    for r in usable:
        P("| %s | %s | %s | %s | %s |"
          % (r["rule_id"], r["theme"], r["evidence_grade"], r["verification_status"],
             r["source_locator"]))
    P()
    P("## 附二、待人工核位（不进断语）")
    P()
    P("下列命中或只有「十神:某」一类标签而没有位，或另有未具足之前提（如格未定、藏干取法未定）。"
      "十神出现不等于十神在某位——如「偏财出现」不能推「日支坐偏财」。"
      "故一律不进断语，须批者按原文位置条件逐条复核后自定去取。")
    P()
    if pending:
        P("| 规则 | 主题 | 条件（原文位置要求） |")
        P("|---|---|---|")
        for r in pending:
            P("| %s | %s | %s |" % (r["rule_id"], r["theme"], A.quote(r["conditions"], 90)))
    else:
        P("无。")
    P()
    P("## 附三、体例类命中（恒真，作次序不作断语）")
    P()
    P("　" + "、".join(r["rule_id"] for r in body) if body else "无。")
    P()
    if wrong:
        P("## 附四、已剔除的误命中")
        P()
        P("下列命中的原文另有前提或另有位的要求，而本造不符。十神虽在四柱中出现，"
          "却不在原文所指定的位置，或该条另有未具足的前提。属误命中，不得入命书。")
        P()
        P("| 规则 | 主题 | 剔除理由 | 原文条件 |")
        P("|---|---|---|---|")
        for r, why in wrong:
            P("| %s | %s | %s | %s |"
              % (r["rule_id"], r["theme"], why, A.quote(r["conditions"], 70)))
        P()
    # ── 附五：按环节取料 ──
    P("## 附五、按环节取料（不经标签，供批者自取）")
    P()
    P("检索层只认 trigger_tags。标签为空者永远匹配不上，可关键条往往就在其中——"
      "取格法 R73、格局与性格 R26 皆是 tags 为空。故另按 theme 归环节列出，"
      "本节不作断语，只把料摆出来。批者用哪一条，须自行核其前提。")
    P()
    for sec, got in pull_by_lens():
        P("**%s**（%d 条）" % (sec, len(got)))
        P()
        for r in got:
            P("- %s｜%s｜%s" % (r["rule_id"], r["theme"], A.quote(r["rule_text"], 60)))
        P()
    P("---")
    P()
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════════════════
# HTML 交付层（Part 42）
#
# 上面那套 render() 是**工程底稿**：每条断语后挂 rule_id、证据等级、核验状态，
# 末尾还有依据表、待核表、误命中表。那是给批者自查用的，不是给来客看的。
#
# 来客要看的是一本命书。所以这一层做两件事：
#   一、版式：宣纸底、朱红点缀、宋体正文（同 references/example_pijing_gengxu.html）。
#   二、去工程化：不留 rule_id、不留证据等级、不留附录。命式与长生由本脚本算，
#       断语另由批者写成 --prose 文件（那是判断，工具不该替人做）。
# ══════════════════════════════════════════════════════════════════════════

CN_NO = "一二三四五六七八九十"
CN_DIGIT = "〇一二三四五六七八九"
WX_ORDER = "木火土金水"
YANG_BRANCH = set("子寅辰午申戌")   # 阳支；A.YANG 只是阳干，不可混用


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(s):
    """**粗体** → <b>，其余转义。命书里不用行内代码与链接。"""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _esc(s))


def cn_no(n):
    """1→一 … 10→十 … 11→十一。章序号过十也要接得住。"""
    if n <= 10:
        return CN_NO[n - 1]
    if n < 20:
        return "十" + CN_NO[n - 11]
    return str(n)


def _cn_year(y):
    return "".join(CN_DIGIT[int(c)] for c in str(y))


def cn_num(n):
    """43→四十三。cn_no 只管一至十九，虚岁、年龄过二十要接得住。"""
    if 0 < n < 20:
        return cn_no(n)
    if 20 <= n < 100:
        tens, ones = divmod(n, 10)
        s = CN_NO[tens - 1] + "十"
        if ones:
            s += CN_NO[ones - 1]
        return s
    return str(n)


def year_gz(y):
    """公元年→干支。以一九八四甲子为基准，只用于命书抬头的「今年」。"""
    G, Z = "甲乙丙丁戊己庚辛壬癸", "子丑寅卯辰巳午未申酉戌亥"
    i = (y - 1984) % 60
    return G[i % 10] + Z[i % 12]


def now_yun_of(start_age, dayun, birth_year, now_year):
    """→ (当前大运干支或None, 当前虚岁或None)。虚岁口径，十年一步。"""
    if not (birth_year and now_year):
        return None, None
    xu = now_year - birth_year + 1
    for i, gz in enumerate(dayun):
        lo = start_age + 10 * i
        if lo <= xu < lo + 10:
            return gz, xu
    return None, xu


def _md_blocks(text):
    """批词 md 切块。kind ∈ h2 / h3 / p / p0（独立成段）/ li / ol。"""
    blocks, buf = [], []

    def flush():
        if buf:
            blocks.append(("p", " ".join(buf)))
            del buf[:]

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if line.startswith("## "):
            flush()
            blocks.append(("h2", line[3:].strip()))
        elif line.startswith("### "):
            flush()
            blocks.append(("h3", line[4:].strip()))
        elif line.startswith("> "):
            flush()
            blocks.append(("q", line[2:].strip()))
        elif line.startswith("- "):
            flush()
            blocks.append(("li", line[2:].strip()))
        elif re.match(r"^\d+[.、]\s", line):
            flush()
            blocks.append(("ol", re.sub(r"^\d+[.、]\s*", "", line)))
        elif re.match(r"^[一二三四五六七八九十]、", line):
            # 「一、二、三…」逐条并列者，各成一段，不与上下句连读
            flush()
            blocks.append(("p0", line))
        else:
            buf.append(line.strip())
    flush()
    return blocks


def _items_html(items, blocks=None, now_yun=None):
    """一节之内的段落／列表／大运小目。

    _md_blocks 已按空行切好段落，此处一块即一段，不再合并。
    now_yun：当前所行大运干支；大运小目标题里含此二字者，加「当前所行」徽章。
    """
    out, list_mode, in_yun = [], None, False

    def end_list():
        nonlocal list_mode
        if list_mode:
            out.append("</ul>" if list_mode == "ul" else "</ol>")
            list_mode = None

    for k, v in items:
        if k == "h3":
            end_list()
            if re.match(r"^[一二三四五六七八九十]+、", v):
                if in_yun:
                    out.append("</div>")
                label = _inline(v)
                now_hit = bool(now_yun and now_yun in v)
                if now_hit:
                    label += '<span class="tag now">当前所行</span>'
                out.append('<div class="yun%s"><b>%s</b>'
                           % (" now" if now_hit else "", label))
                in_yun = True
            else:                      # 六亲之「父／母／妻」、全流表之标题
                if in_yun:
                    out.append("</div>")
                    in_yun = False
                out.append("<h3>%s</h3>" % _inline(v))
        elif k in ("li", "ol"):
            want = "ul" if k == "li" else "ol"
            if list_mode != want:
                end_list()
                out.append('<ul class="plain">' if want == "ul" else '<ol class="yao">')
                list_mode = want
            out.append("<li>%s</li>" % _inline(v))
        elif k == "q":
            end_list()
            out.append("<blockquote>%s</blockquote>" % _inline(v))
        else:
            end_list()
            key = v.strip()
            if blocks and key in blocks:
                out.append(blocks[key])
            else:
                out.append("<p>%s</p>" % _inline(v))
    end_list()
    if in_yun:
        out.append("</div>")
    return "\n".join(out)


def _sections(text):
    """→ [(节题, [(kind, 内容)…])]。首个 h2 之前的散句挂在空题下。"""
    secs = []
    for k, v in _md_blocks(text):
        if k == "h2":
            secs.append([v, []])
        else:
            if not secs:
                secs.append(["", []])
            secs[-1][1].append((k, v))
    return secs


def _mingpan_html(a):
    """命式：四柱十神、藏干、长生十二宫、五行、阴阳。纯结构，不带断语。"""
    day = a["pillars"][2][0]
    branches = [r["branch"] for r in a["expanded"]]
    out = []

    out.append("<h2>命式</h2>")
    tags = []
    if a["pillars"][2] in A.KUIGANG:
        tags.append('<span class="tag">魁　罡</span>')
    if a["missing"]:
        tags.append('<span class="tag full">缺　%s</span>'
                    % "、".join(a["missing"]))
    if tags:
        out.append('<p class="flat" style="text-align:center;">%s</p>' % "".join(tags))
    out.append("<table>")
    out.append("<tr><th>柱</th><th>干支</th><th>天干十神</th><th>藏干·十神</th><th>本气</th></tr>")
    for r in a["expanded"]:
        hid = "／".join("%s·%s" % (s, A.ten_god(day, s)) for s in A.HIDDEN[r["branch"]])
        out.append('<tr><td>%s</td><td>%s</td><td>%s</td><td class="l">%s</td><td>%s</td></tr>'
                   % (r["pos"], r["stem"] + r["branch"], r["stem_tg"], hid,
                      A.HIDDEN[r["branch"]][0]))
    out.append("</table>")

    # 长生十二宫：只列各干于四支之气，不判走向。
    # 「自年而时递升／递降」一类的说法须先定一套气的强弱次序，本包无此表，
    # 硬排等于自造口径，故不列；改以临官、帝旺加色，仍是格值本身。
    stems = [day]
    for r in a["expanded"]:
        if r["stem"] not in stems:
            stems.append(r["stem"])
    out.append("<h3>长生十二宫　各干于四支之气</h3>")
    out.append("<table>")
    out.append("<tr><th>干</th>%s</tr>"
               % "".join("<th>%s支 %s</th>" % (r["pos"], r["branch"]) for r in a["expanded"]))
    for st in stems:
        cells = []
        for b in branches:
            s12 = A.stage12(st, b)
            cells.append('<td%s>%s</td>' % (' class="hi"' if s12 in ("临官", "帝旺") else "", s12))
        out.append("<tr><td>%s%s</td>%s</tr>"
                   % (st, "（日主）" if st == day else "", "".join(cells)))
    out.append("</table>")

    wx = "、".join("%s%s" % (k, CN_NO[a["wuxing"][k] - 1])
                   for k in WX_ORDER if 1 <= a["wuxing"].get(k, 0) <= 10)
    out.append("<p><b>五行</b>：%s（天干＋藏干等权计）。<span class=\"hi\">%s。</span></p>"
               % (wx, ("缺" + "、".join(a["missing"])) if a["missing"] else "五行不缺"))
    # 五行条：一眼看强弱多寡，颜色只作区辨，不作吉凶
    mx = max(a["wuxing"].get(k, 0) for k in WX_ORDER) or 1
    WX_COLOR = {"金": "c-jin", "木": "c-mu", "水": "c-shui", "火": "c-huo", "土": "c-tu"}
    out.append('<div style="margin:10px 0 16px;">')
    for k in WX_ORDER:
        n = a["wuxing"].get(k, 0)
        w = max(8, int(round(150.0 * n / mx)))
        out.append('<div class="wx"><span class="lab">%s</span>'
                   '<span class="bar %s" style="width:%dpx"></span>'
                   '<span class="n">%s%s</span></div>'
                   % (k, WX_COLOR[k], w, CN_NO[n - 1] if 1 <= n <= 10 else n,
                      "字（缺）" if n == 0 else "字"))
    out.append("</div>")
    yy = sum(1 for r in a["expanded"]
             for ch in (r["stem"], r["branch"])
             if ch in A.YANG or ch in YANG_BRANCH)
    tot = len(a["expanded"]) * 2
    out.append("<p><b>阴阳</b>：四柱八字之中，阳%s、阴%s，%s。</p>"
               % (CN_NO[yy - 1] if 1 <= yy <= 10 else yy,
                  CN_NO[tot - yy - 1] if 1 <= tot - yy <= 10 else tot - yy,
                  "不偏" if abs(yy - (tot - yy)) <= 2 else "偏于一端"))
    return "\n".join(out)


def _gong_jia(br):
    """拱夹：两支相隔一位，夹出中间一支。中间一支已在四柱者，不算拱。"""
    idx = [ZHI12.index(b) for b in br if b in ZHI12]
    for i, x in enumerate(idx):
        for y in idx[i + 1:]:
            d = (x - y) % 12
            if d == 2:            # x 在 y 之后两位，中间为 y+1
                mid = ZHI12[(y + 1) % 12]
            elif d == 10:         # y 在 x 之后两位，中间为 x+1
                mid = ZHI12[(x + 1) % 12]
            else:
                continue
            if mid not in br:
                return True
    return False


def _yizhiyin_html(a):
    """已知因：只摆结构事实，不带断语。"""
    day = a["pillars"][2][0]
    month = a["pillars"][1][1]
    mh = A.HIDDEN[month]
    xt = a["xingtai"]
    stems = [r["stem"] for r in a["expanded"]]
    items = []

    if xt.get("xiadong"):
        season = "夏" if month in "巳午未" else "冬"
    else:
        season = "非夏冬"
    items.append("日主%s%s，生%s月，%s生。"
                 % (day, A.STEM_ELEM.get(day, ""), month, season))

    mid = ("中气%s为%s" % (mh[1], A.ten_god(day, mh[1]))) if len(mh) > 1 else ""
    tou = "本气透干" if mh[0] in stems else "本气不透干"
    if len(mh) > 1 and mh[1] in stems:
        tou += "，余气%s透%s干" % (mh[1], "年" if mh[1] == a["pillars"][0][0] else "他")
    items.append("月令%s，本气%s为%s%s；%s。"
                 % (month, mh[0], A.ten_god(day, mh[0]), "，" + mid if mid else "", tou))

    items.append("天干：%s。" % "，".join("%s%s（%s）" % (r["pos"], r["stem"], r["stem_tg"])
                                     for r in a["expanded"]))

    gh = gan_he(a)
    if gh:
        items.append("天干五合：%s。阳日主对正财，连克带合。" % "；".join(gh))

    items.append("地支：%s。日支%s本气%s（%s），时支%s本气%s（%s）。"
                 % ("、".join(r["branch"] for r in a["expanded"]),
                    a["pillars"][2][1], A.HIDDEN[a["pillars"][2][1]][0],
                    A.ten_god(day, A.HIDDEN[a["pillars"][2][1]][0]),
                    a["pillars"][3][1], A.HIDDEN[a["pillars"][3][1]][0],
                    A.ten_god(day, A.HIDDEN[a["pillars"][3][1]][0])))

    guan = {}
    for r in a["expanded"]:
        for s in A.HIDDEN[r["branch"]]:
            tg = A.ten_god(day, s)
            if tg in ("正官", "七杀"):
                guan.setdefault(tg, []).append((s, r["branch"]))
    if guan:
        seg = []
        for tg in ("正官", "七杀"):
            if tg not in guan:
                seg.append("%s不见" % tg)
                continue
            same = {}
            for s, b in guan[tg]:
                same.setdefault(s, []).append(b)
            seg.append("%s%s藏于%s，%s"
                       % (tg, "、".join(same),
                          "、".join(sorted({b for _, b in guan[tg]})),
                          "两见而不透" if len(guan[tg]) > 1 else "一见而不透"))
        items.append("官星：天干不透；%s。" % "；".join(seg))
    else:
        items.append("官星：天干与支藏俱无正官、七杀。")

    rels = [r for r in a["relations"] if r.get("kind")]
    if rels:
        pillars = [r["branch"] for r in a["expanded"]]
        txt = []
        for r in rels:
            mem = r.get("members") or []
            wei = "、".join("年月日时"[pillars.index(b)] if b in pillars else "运"
                           for b in mem)
            txt.append("%s%s%s" % ("".join(mem), r["kind"],
                                   "（%s）" % wei if wei else ""))
        extra = ""
        if not any("冲" in (r["kind"] or "") for r in rels):
            extra = "；四柱无冲"
        items.append("刑冲合会：%s%s。" % ("；".join(txt), extra))
    else:
        items.append("刑冲合会：四柱无冲、无合、无刑、无害。")

    items.append("日主根气：%s在%s，%s。"
                 % (day, "、".join("%s%s" % (b, A.stage12(day, b))
                                  for b in [r["branch"] for r in a["expanded"]]),
                    "四柱无临官、无帝旺" if all(
                        A.stage12(day, r["branch"]) not in ("临官", "帝旺") for r in a["expanded"]
                    ) else "有临官或帝旺之地"))

    if a["th"]:
        tv = a["th"][0]["value"]
        if len(tv) > 1 and "、" not in tv and "／" not in tv:
            tv = "、".join(tv)
        # 调候字须挂十神身份：同一味火，丁是正官、丙是七杀，两样口气。
        # 「并列不分正副」这类句式等于未定次序，禁出。
        if len(tv) > 1:
            parts = re.split("[、／]", tv)
            gods = "、".join("%s（%s）" % (ch, A.ten_god(day, ch)) for ch in parts if ch)
            items.append("调候：%s日生%s月，表列%s——同气不同性，各挂其神：%s；用时先分口气，先后次序由批者依原文定。"
                         % (day, month, tv, gods))
        else:
            items.append("调候：%s日生%s月，表列%s（%s）。"
                         % (day, month, tv, A.ten_god(day, tv)))
    else:
        items.append("调候：%s日生%s月，此条我手里没有表可查，不判。" % (day, month))

    # 拱夹：两支相隔一位者夹出中间一支，谓之拱。本造逐对核，无一对相隔一位。
    br = [r["branch"] for r in a["expanded"]]
    if not _gong_jia(br):
        items.append("拱夹：四柱无拱夹。相邻之二支不相隔，相隔者又隔两支以上。")

    if a["pillars"][2] in A.KUIGANG:
        items.append("日柱%s，魁罡。" % a["pillars"][2])
    else:
        items.append("日柱%s，非魁罡名目。" % a["pillars"][2])

    if "戌" in br and "亥" in br:
        items.append("戌亥二字齐，为天罗。")

    out = ["<h2>已知因</h2>", '<ol class="yao">']
    for it in items:
        out.append("<li>%s</li>" % _inline(it))
    out.append("</ol>")
    return "\n".join(out)


HTML_CSS = """
  :root{
    --paper:#fbf9f3; --ink:#1b1a17; --ink2:#4a463f; --red:#8c1c13;
    --line:#c9c1ae; --soft:#efe9db;
  }
  *{box-sizing:border-box;}
  body{
    margin:0; padding:0 0 60px;
    background:#e8e4da;
    font-family:"Songti SC","SimSun","Source Han Serif SC","Noto Serif CJK SC",serif;
    color:var(--ink); line-height:1.9; font-size:15.5px;
  }
  .sheet{
    max-width:820px; margin:28px auto; background:var(--paper);
    padding:48px 52px 64px; box-shadow:0 2px 24px rgba(0,0,0,.14);
    border-top:6px solid var(--red);
  }
  header{text-align:center; margin-bottom:8px;}
  .kicker{font-size:12.5px; letter-spacing:.5em; color:var(--red); margin-bottom:18px;}
  h1{font-size:40px; letter-spacing:.18em; margin:0 0 6px; font-weight:600;}
  .sub{font-size:13px; color:var(--ink2); letter-spacing:.2em;}
  .bazi{
    margin:26px auto 8px; border-collapse:collapse; font-size:22px;
    letter-spacing:.08em;
  }
  .bazi td{border:1px solid var(--line); padding:10px 22px; background:#fff;}
  .bazi td:first-child{background:var(--soft); font-size:13px; letter-spacing:.1em; color:var(--ink2);}
  .meta{text-align:center; font-size:13px; color:var(--ink2); margin-bottom:34px;}
  blockquote{
    margin:0 0 34px; padding:14px 18px; background:#f4efe3;
    border-left:3px solid var(--red); font-size:13.5px; color:var(--ink2);
    line-height:1.85;
  }
  h2{
    font-size:19px; letter-spacing:.14em; margin:0 0 18px; padding-bottom:10px;
    border-bottom:1px solid var(--line); font-weight:600;
    display:flex; align-items:center;
  }
  /* 编号做成朱红胶囊章。两字编号（十一…）用胶囊不用正圆，免得挤变形。 */
  h2 .no{
    background:var(--red); color:#fff; border-radius:14px; min-width:28px; height:26px;
    padding:0 9px; margin-right:.55em; font-size:14px; letter-spacing:.05em;
    display:inline-flex; align-items:center; justify-content:center; flex-shrink:0;
  }
  /* 每节一张卡：白底细边浅影，节与节之间有呼吸，滚动阅读有落点。 */
  .sec{
    background:#fff; border:1px solid var(--line); border-radius:8px;
    padding:28px 32px 20px; margin:0 0 26px; box-shadow:0 1px 8px rgba(0,0,0,.05);
  }
  h3{font-size:15.5px; margin:26px 0 8px; letter-spacing:.1em; color:var(--red); font-weight:600;}
  p{margin:0 0 14px; text-align:justify; text-indent:2em;}
  p.flat{text-indent:0;}
  table{width:100%; border-collapse:collapse; margin:18px 0 22px; font-size:13.5px; line-height:1.7;}
  th,td{border:1px solid var(--line); padding:8px 10px; text-align:center;}
  th{background:var(--soft); font-weight:600; letter-spacing:.06em;}
  td.l{text-align:left;}
  .hi{color:var(--red); font-weight:600;}
  .note{font-size:13px; color:var(--ink2);}
  .yun{border-left:2px solid var(--line); padding:2px 0 2px 20px; margin:0 0 22px;}
  /* 只命中小目标题（.yun 的直接子 b）。若写成 .yun b，正文里的行内强调
     也会变成块级，句子被拦腰截断——参考范文 HTML 亦有此误。 */
  .yun > b{display:block; font-size:15px; letter-spacing:.1em; margin-bottom:6px;}
  .yun p{text-indent:0; margin:0 0 10px;}
  ol.yao{margin:0 0 14px; padding-left:0; list-style:none; counter-reset:y;}
  ol.yao li{position:relative; padding-left:2.4em; margin-bottom:14px; text-align:justify;}
  ol.yao li:before{
    counter-increment:y; content:counter(y,upper-roman);
    position:absolute; left:0; top:0; color:var(--red); font-size:13px; letter-spacing:.05em;
  }
  ul.plain{margin:0 0 14px; padding-left:1.6em;}
  ul.plain li{margin-bottom:8px; text-align:justify;}
  footer{margin-top:52px; padding-top:18px; border-top:1px solid var(--line);
    font-size:12.5px; color:var(--ink2); line-height:1.8; text-align:center; letter-spacing:.2em;}
  /* ── 推广尾注：与正文分隔的独立收尾，正文与推广互不混 ── */
  .promo{margin-top:46px; border:1px solid var(--line); background:#fdf9f0;
    padding:28px 30px 24px; text-align:center;}
  .promo p{font-size:13.5px; line-height:2; color:var(--ink); text-align:center; margin:0 0 10px;}
  .promo img{width:172px; height:172px; background:#fff; border:1px solid var(--line);
    padding:8px; margin:10px 0 6px;}
  .promo .lnk{font-size:13px; letter-spacing:.05em;}
  .promo .disc{font-size:11.5px; color:var(--ink2); margin-top:10px; letter-spacing:.1em;}
  /* ── 视觉借自报告模板：四柱竖牌、五行条、朱印章。仍是宣纸书卷体。 ── */
  .pillars{display:flex; justify-content:center; gap:14px; margin:26px 0 4px; flex-wrap:wrap;}
  .pillar{background:#fff; border:1px solid var(--line); border-top:3px solid var(--red);
    padding:14px 26px 12px; text-align:center; box-shadow:0 1px 6px rgba(0,0,0,.05); min-width:96px;}
  .pillar .pos{font-size:12px; color:var(--ink2); letter-spacing:.3em; margin-bottom:6px;}
  .pillar .gz{font-size:30px; letter-spacing:.1em; font-weight:600;}
  .pillar .tg{font-size:12px; color:var(--red); margin-top:6px; letter-spacing:.12em;}
  .wx{margin:4px 0 2px;}
  .wx .lab{display:inline-block; width:2.4em; font-weight:600;}
  .wx .bar{display:inline-block; height:13px; border-radius:3px; vertical-align:middle; margin:0 10px; min-width:6px;}
  .wx .n{font-size:12.5px; color:var(--ink2);}
  .c-jin{background:#cdb03a;} .c-mu{background:#6da35f;} .c-shui{background:#5f8fb4;}
  .c-huo{background:#bf4536;} .c-tu{background:#b08a5a;}
  .tag{display:inline-block; border:1px solid var(--red); color:var(--red); border-radius:3px;
    padding:1px 9px; font-size:12px; letter-spacing:.18em; margin:0 6px; vertical-align:middle; background:#fdf6ee;}
  .tag.full{border-color:#b08a5a; color:#7a5c33; background:#f8f2e6;}
  /* 大运小目的「当前所行」徽章：实底朱红白字，一眼锁定如今走到哪一步。 */
  .tag.now{background:var(--red); color:#fff; border-color:var(--red); margin-left:.6em;}
  .yun.now{border-left:2px solid var(--red); background:#fdf9f2; padding-left:18px; border-radius:0 4px 4px 0;}
  /* 长表折叠：屏幕上默认收起，点开细看；打印时一律展开（浏览器打印 closed
     details 会整块不渲染，故用 CSS 强制展开）。 */
  details{margin:18px 0 10px; border:1px solid var(--line); border-radius:6px; overflow:hidden; background:#fdfbf5;}
  details summary{cursor:pointer; padding:10px 16px; font-size:13px; letter-spacing:.1em;
    color:var(--red); background:var(--soft); user-select:none;}
  details[open] summary{border-bottom:1px solid var(--line);}
  details table{margin:10px 0;}
  @media (max-width:720px){
    .sheet{padding:24px 14px 48px; margin:0;}
    .sec{padding:20px 16px 14px;}
  }
  @media print{
    body{background:#fff;} .sheet{box-shadow:none; margin:0; max-width:none; padding:24mm 20mm;}
    .sec{box-shadow:none; border:none; padding:0 0 10px; margin:0 0 14px;}
    details > *{display:block !important;}   /* 打印须展开备查表 */
  }
"""


def _struct_blocks(a, dayun, start_age, birth_year):
    """命书里要插的几张表与几段结构说明。全部 E6，不涉判断。"""
    blocks = {}

    # 调候向背：每步大运补不补调候字。补字须挂十神——同一味火，丁是正官、
    # 丙是七杀，两样口气；运干直透的挂运干十神，支藏的挂藏字十神。
    th = dayun_tiaohou(a, dayun)
    want = "、".join(tiaohou_chars(a)) or "（无）"
    rows = ['<table>', '<tr><th>大运</th><th>补调候否</th><th>所补之字十神</th></tr>']
    for gz, got in th:
        if got:
            god_txt = "、".join(
                "%s（%s）" % (c[-1], A.ten_god(a["pillars"][2][0], c[-1])) for c in got)
        else:
            god_txt = "—"
        rows.append('<tr><td>%s</td><td class="l">%s</td><td class="l">%s</td></tr>'
                    % (gz, "、".join(got) if got else "不补", god_txt))
    rows.append('</table>')
    blocks["{{调候向背}}"] = ('<p class="flat">调候所列之字为%s。八步大运补与不补，'
                          '照运干与运支所藏看——所补之字各挂十神，用时分口气：</p>' % want) + "\n".join(rows)

    # 全流冲刑会合：只留冲、刑、三合全、三会全。
    # 七十来行结构表对批者是账本，对来客是负担——默认收起，点开细看；
    # 正文吉凶在各运段里已说，此表只备回查。
    ql = [r for r in quanliu_rows(a, dayun)
          if any(k in r[2] for k in ("冲", "刑", "三合全", "三会全"))]
    rows = ['<table>', '<tr><th>大运</th><th>流年支</th><th>撞出的结构</th></tr>']
    for gz, nb, txt in ql:
        rows.append('<tr><td>%s</td><td>%s</td><td class="l">%s</td></tr>' % (gz, nb, txt))
    rows.append('</table>')
    blocks["{{全流表}}"] = ('<details><summary>全流冲刑会合　共%d行　点开细看</summary>%s</details>'
                        % (len(ql), "\n".join(rows)))

    # 流年表：P2.5 起改用 analyze 的流年引擎（架势／双冲／三合三会／冲运），
    # 只取「主命中」，用命书语（brief），不带 rule_id——命书不许出现工程标记。
    ln = A.liunian_analysis(a, list(range(2026, 2032)), dayun, birth_year, start_age, False)
    if ln:
        rows = ['<table>', '<tr><th>年</th><th>干支</th><th>虚岁</th><th>所行大运</th>'
                '<th>结构</th></tr>']
        for x in ln:
            briefs = []
            for r in x["rows"]:
                if r["main"] and r["brief"] not in briefs:
                    briefs.append(r["brief"])
            rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                        '<td class="l">%s</td></tr>'
                        % (x["year"], x["gz"], x["age"] or "—", x["dayun"] or "—",
                           "；".join(briefs) if briefs else "无大事触发"))
        rows.append('</table>')
        blocks["{{流年表}}"] = "\n".join(rows)

    # 空亡两说
    kw = kongwang(a)
    blocks["{{空亡}}"] = (
        '<p>空亡一说，基准未定。按日柱%s之旬，空在%s%s；按年柱%s之旬，空在%s%s。'
        '两说不同，结论亦不同，此处并列，不代裁。</p>'
        % (a["pillars"][2], kw["日柱旬"][0], kw["日柱旬"][1],
           a["pillars"][0], kw["年柱旬"][0], kw["年柱旬"][1]))

    # 天干五合
    gh = gan_he(a)
    if gh:
        blocks["{{天干五合}}"] = "<p>天干：%s。</p>" % "；".join(gh)

    return blocks


def _promo_html():
    """推广尾注：赞赏二维码＋苍盘命书体验邀请，嵌在「命书终」之后。

    二维码 base64 内嵌（单文件自包含，拷走也能显示）；素材缺失时按三档降级
    只出纯文字——文字是保底，图片是增强，与 references/推广尾注.md 同规。
    """
    txt = ('<p>本命书基于梁湘润先生命理体系批写。若这次解读对你有帮助，'
           '可自愿扫码支持命理技能分享。</p>'
           '<p>另欢迎<b>免费体验盘叔历时半年、以数千现代真人命例打造的苍盘命书</b>'
           '——融合各派，与本篇对照参考。</p>'
           '<p>微信：cpms1988　·　'
           '<a class="lnk" href="https://mp.weixin.qq.com/s/9NFaItizyhEpjDzmTyEcPQ">'
           '苍盘命书体验邀请</a></p>'
           '<p class="disc">以上为独立推广内容，不是命理判断或命盘资料。</p>')
    img = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "references", "assets", "appreciation.jpg")
    qr = ""
    if os.path.exists(img) and os.path.getsize(img) >= 10240:
        import base64
        b64 = base64.b64encode(open(img, "rb").read()).decode("ascii")
        qr = ('<img src="data:image/jpeg;base64,%s" '
              'alt="赞赏二维码（微信：cpms1988）">' % b64)
    return '<div class="promo">%s%s</div>' % (qr, txt)


def render_html(a, start_age, dayun, forward, prose, birth_year=None, now_year=None,
                birth_meta=None):
    """来客看的命书。版式同 example_pijing_gengxu.html，正文由 --prose 供给。

    now_year：公元年，用来在抬头与各运小目标出「如今走到哪」；不给则不标。
    """
    day = a["pillars"][2][0]
    gender = a["gender"] or "未注"
    secs = _sections(prose)
    ny_gz, ny_xu = now_yun_of(start_age, dayun, birth_year, now_year)

    bazi = ['<div class="pillars">']
    for r in a["expanded"]:
        tg = "日主" if r["pos"] == "日" else r["stem_tg"]
        bazi.append('<div class="pillar"><div class="pos">%s柱</div>'
                    '<div class="gz">%s%s</div>'
                    '<div class="tg">%s</div></div>'
                    % (r["pos"], r["stem"], r["branch"], tg))
    bazi.append("</div>")

    meta = "%s造" % ("乾" if gender == "男" else ("坤" if gender == "女" else ""))
    if birth_year:
        meta += "　%s年生（%s年）" % (_cn_year(birth_year), a["pillars"][0])
    meta += "　%s岁起运" % start_age
    if ny_gz and ny_xu:
        meta += "　今年%s（%s），虚岁%s，行%s运" % (
            _cn_year(now_year), year_gz(now_year), cn_num(ny_xu), ny_gz)

    body = ["<!DOCTYPE html>",
            '<html lang="zh-Hans">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>命书　%s</title>" % "　".join(a["pillars"]),
            "<style>%s</style>" % HTML_CSS,
            "</head>",
            "<body>",
            '<div class="sheet">',
            "",
            "<header>",
            '<div class="kicker">细　批　终　身</div>',
            "<h1>命　书</h1>",
            '<div class="sub">依梁湘润批例体例</div>',
            "</header>",
            "",
            "\n".join(bazi),
            '<div class="meta">%s</div>' % meta,
            ('<div class="meta" style="margin-top:-26px;">%s</div>' % _esc(birth_meta))
            if birth_meta else "",
            "",
            '<div class="sec">',
            _mingpan_html(a),
            "</div>",
            "",
            '<div class="sec">',
            _yizhiyin_html(a),
            "</div>",
            ""]

    blocks = _struct_blocks(a, dayun, start_age, birth_year)

    for i, (title, items) in enumerate(secs):
        # 命式、已知因为一、二，正文自三起
        no = cn_no(i + 1)          # 命式、已知因不占编号，正文自「一」起
        if title in ("附言", "附記", "附记"):
            no = "附"
        body.append('<div class="sec">')
        body.append('<h2><span class="no">%s</span>%s</h2>' % (no, _inline(title)))
        body.append(_items_html(items, blocks, ny_gz))
        body.append("</div>")
        body.append("")

    body += ["<footer>命　书　终</footer>",
             "",
             '<div style="text-align:center; font-size:12px; color:var(--ink2); '
             'letter-spacing:.15em; margin-top:14px;">%s年%s月批写</div>' % (
                 _cn_year(datetime.date.today().year), cn_no(datetime.date.today().month)),
             "",
             _promo_html(),
             "",
             "</div>",
             "</body>",
             "</html>"]
    return "\n".join(body)


def main():
    ap = argparse.ArgumentParser(description="梁湘润详批命书生成器（六段体例）")
    ap.add_argument("pillars", nargs="*", help="四个干支，按年 月 日 时")
    ap.add_argument("--gender", choices=["男", "女"])
    ap.add_argument("--start-age", type=int,
                    help="起运虚岁，取 paipan.py 输出的「交运虚岁」；不是「起运折几年几月」那个年数")
    ap.add_argument("--dayun", help="大运干支，逗号分隔；不给则按阳男阴女顺排八步")
    ap.add_argument("--format", choices=["md", "html"], default="md",
                    help="md=工程底稿（含 rule_id／依据表）；html=来客看的命书")
    ap.add_argument("--prose", help="html 用的批词 md；不给则退化为纯结构，不出命书")
    ap.add_argument("--birth-year", type=int, help="出生年（公元），只用于命书抬头")
    ap.add_argument("--now-year", type=int,
                    help="「今年」（公元），用于抬头定位与当前运徽章；不给则取系统当年")
    ap.add_argument("--birth-meta",
                    help="出生信息一行字（公历、时辰、出生地、真太阳时），如"
                         "「1984-11-12 14:45·广东梅州·真太阳时14:44」；给则显示在抬头之下，供复核")
    ap.add_argument("--out", help="输出路径；不给则打印到标准输出")
    ap.add_argument("--from-paipan", metavar="JSON",
                    help="直接读 paipan.py --json 的输出：四柱／性别／大运／交运虚岁一并取来")
    args = ap.parse_args()

    if args.from_paipan:
        src = A.load_paipan(args.from_paipan)
        args.pillars = args.pillars or src["pillars"]
        args.gender = args.gender or src["gender"]
        args.dayun = args.dayun or ",".join(src["dayun"])
        args.birth_year = args.birth_year or src["birth_year"]
        args.start_age = args.start_age or src["start_age"]

    if args.start_age is None:
        ap.error("须给 --start-age（取 paipan 的「交运虚岁」）或 --from-paipan")

    if len(args.pillars) != 4:
        ap.error("须给四个干支，按年 月 日 时")
    if not args.gender:
        ap.error("须给 --gender（六亲与 scope 过滤都靠它）")
    if args.format == "html" and not args.prose:
        ap.error("--format html 须同时给 --prose（断语是判断，工具不替人做）")

    year_stem = args.pillars[0][0]
    forward = (year_stem in A.YANG) == (args.gender == "男")
    if args.dayun:
        dayun = [x.strip() for x in args.dayun.split(",") if x.strip()]
    else:
        dayun = paipai(args.pillars[1], forward, 8)

    a = A.analyze(args.pillars, args.gender, dayun)

    if args.format == "html":
        with io.open(args.prose, encoding="utf-8") as fh:
            prose = fh.read()
        # 入口就拦：--prose 常被误指到底稿（analyze.py 的输出）。底稿满是 rule_id、
        # 证据等级、概率词，灌进命书后 M01「命书不得含工程标记」必 FAIL。
        # 让他先 FAIL 再回来改，不如当场拒收，并指名该拿哪一份。
        _bad = re.findall(r"R-[A-Z]{2}-\d+|E[1-6]\s|证据等级|部分核|已核|待核|未入库", prose)
        if _bad:
            ap.error("--prose 疑似底稿而非批词：检出 %d 处工程标记（%s…）。"
                     "命书是断语体、零标记，须由批者另写；底稿是 C 轨，供复核，不可当命书正文。"
                     % (len(_bad), "、".join(sorted(set(_bad))[:4])))
        now_year = args.now_year or datetime.date.today().year
        text = render_html(a, args.start_age, dayun, forward, prose,
                           args.birth_year, now_year, args.birth_meta)
    else:
        text = render(a, args.start_age, dayun, forward)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        io.open(args.out, "w", encoding="utf-8", newline="\n").write(text + "\n")
        print("已写出 %s（%d 字）" % (args.out, len(text)))
    else:
        print(text)


if __name__ == "__main__":
    main()
