# -*- coding: utf-8 -*-
"""梁湘润批八字·证据门控分析器（骨架）

用途：接收用户直接提供的四柱，不排历法、不补四柱；按已核/条件允许的
梁湘润资料做结构化检索，并为每个判断附规则/表格/命例来源。
禁止：用通行术数知识补写梁氏原文；把待核/候选/冲突格值写成定论。
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, OrderedDict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import shensha_calc          # noqa: E402  神煞探源起例判定器（R-SP-001～049）

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
JIAZI = [STEMS[i % 10] + BRANCHES[i % 12] for i in range(60)]
JIAZI_SET = set(JIAZI)
POS = ["年", "月", "日", "时"]

STEM_ELEM = dict(zip(STEMS, "木木火火土土金金水水"))
BRANCH_ELEM = dict(zip(BRANCHES, "水土木木土火火土金金土水"))
YANG = set("甲丙戊庚壬")
GEN = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
HIDDEN = {
    "子": ["癸"], "丑": ["己", "癸", "辛"], "寅": ["甲", "丙", "戊"], "卯": ["乙"],
    "辰": ["戊", "乙", "癸"], "巳": ["丙", "戊", "庚"], "午": ["丁", "己"],
    "未": ["己", "丁", "乙"], "申": ["庚", "壬", "戊"], "酉": ["辛"],
    "戌": ["戊", "辛", "丁"], "亥": ["壬", "甲"],
}
SANHE = [("申", "子", "辰"), ("亥", "卯", "未"), ("寅", "午", "戌"), ("巳", "酉", "丑")]
SANHUI = [("亥", "子", "丑"), ("寅", "卯", "辰"), ("巳", "午", "未"), ("申", "酉", "戌")]
CHONG = [("子", "午"), ("丑", "未"), ("寅", "申"), ("卯", "酉"), ("辰", "戌"), ("巳", "亥")]
HAI = [("子", "未"), ("丑", "午"), ("寅", "巳"), ("卯", "辰"), ("申", "亥"), ("酉", "戌")]
LIUHE = [("子", "丑"), ("寅", "亥"), ("卯", "戌"), ("辰", "酉"), ("巳", "申"), ("午", "未")]
# 十干相冲：戊己土无冲（子平通例，梁氏未另立）
GAN_CHONG = [("甲", "庚"), ("乙", "辛"), ("丙", "壬"), ("丁", "癸")]
XING3 = [("寅", "巳", "申"), ("丑", "戌", "未")]
XING_PAIR = [("子", "卯")]
SELF_XING = set("辰午酉亥")
DAY_GROUP = {"申子辰": "水", "亥卯未": "木", "寅午戌": "火", "巳酉丑": "金",
             "亥子丑": "水", "寅卯辰": "木", "巳午未": "火", "申酉戌": "金"}


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


RULES = load("rules.csv")
CASES = load("cases.csv")
TABLES = load("tables.csv")
CONFLICTS = load("conflicts.csv")
UNRESOLVED = load("unresolved_register.csv")
META = load("table_metadata.csv")

META_BY_ID = {m["table_id"]: m for m in META}
CELLS = OrderedDict()
for c in TABLES:
    CELLS.setdefault(c["table_id"], []).append(c)

# ---------------- 梁氏次序层（Part 29 新增；依据 R-SZ 批次，E3《命理实战》） ----------------
# 以下为**结构计算（E6）**，不是梁氏判断本身；判定规则另有 R-SZ 条号。
STAGE12 = ["长生", "沐浴", "冠带", "临官", "帝旺", "衰", "病", "死", "墓", "绝", "胎", "养"]
CHANGSHENG = {"甲": "亥", "丙": "寅", "戊": "寅", "庚": "巳", "壬": "申",
              "乙": "午", "丁": "酉", "己": "酉", "辛": "子", "癸": "卯"}
SEASON = {"寅": "春", "卯": "春", "辰": "春", "巳": "夏", "午": "夏", "未": "夏",
          "申": "秋", "酉": "秋", "戌": "秋", "亥": "冬", "子": "冬", "丑": "冬"}
# R-SZ-020：十干败亡运。日主 → (所忌之大运支, 四柱须全无之地支)
BAIWANG = {
    "甲": ("申", "寅卯"), "乙": ("酉", "寅卯"),
    "丙": ("子", "巳午"), "丁": ("亥", "巳午"),
    "戊": ("寅", "巳午"), "己": ("卯", "巳午"),
    "庚": ("午", "申酉"), "辛": ("巳", "申酉"),
    "壬": ("辰戌", "亥子"), "癸": ("丑未", "亥子"),
}
# R-SZ-022：月支定墓库运之运干
MUKU_BY_MONTH = {"辰": "癸", "戌": "丁", "丑": "辛", "未": "乙"}
# R-SZ-026：接角运（顺接，逆交则非）
JIEJIAO = {"辰": "巳", "戌": "亥", "丑": "寅", "未": "申"}
# R-SZ-014／R-SZ-017 涉及之名目（只作候选标记，不判成立）
KUIGANG = {"庚辰", "庚戌", "壬辰", "戊戌"}


def ten_god(day, other):
    de, oe = STEM_ELEM[day], STEM_ELEM[other]
    same = (day in YANG) == (other in YANG)
    if de == oe:
        return "比肩" if same else "劫财"
    if GEN[de] == oe:
        return "食神" if same else "伤官"
    if GEN[oe] == de:
        return "偏印" if same else "正印"
    if KE[de] == oe:
        return "偏财" if same else "正财"
    return "七杀" if same else "正官"


def cell_ok(c):
    return c.get("deterministic_use") in ("允许", "条件允许")


def ev_label(c):
    g = c.get("evidence_grade", "")
    st = c.get("deterministic_use", "")
    return f"{g}／{c.get('verification_status','')}／{st}"


def quote(s, n=160):
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s if len(s) <= n else s[:n] + "…"


def find(table_id, **kw):
    out = []
    for c in CELLS.get(table_id, []):
        if all((c.get(k) or "") == v for k, v in kw.items()):
            out.append(c)
    return out


# ---------------- 基础结构 ----------------
def expand(pillars):
    day = pillars[2][0]
    rows = []
    for i, p in enumerate(pillars):
        stem, branch = p[0], p[1]
        rows.append({
            "pos": POS[i], "pillar": p, "stem": stem, "branch": branch,
            "stem_tg": "日主" if i == 2 else ten_god(day, stem),
            "hidden": [{"stem": h, "tg": ten_god(day, h)} for h in HIDDEN[branch]],
        })
    return rows


def wuxing_count(exp):
    cnt = Counter()
    for r in exp:
        cnt[STEM_ELEM[r["stem"]]] += 1
        for h in r["hidden"]:
            cnt[STEM_ELEM[h["stem"]]] += 1
    return cnt


def tg_count(exp):
    cnt = Counter()
    for i, r in enumerate(exp):
        if i != 2:
            cnt[r["stem_tg"]] += 1
        for h in r["hidden"]:
            cnt[h["tg"]] += 1
    return cnt


# ---------------- 关系判定 ----------------
def rel_note(c, kind, caveat=""):
    """只返回格值之外的限定语；证据等级与状态由 ev_label() 单独输出，不重复。"""
    parts = []
    if not c:
        parts.append(f"未检索到{kind}格值，仅作结构登记（E6），不得当梁氏结论")
    elif not cell_ok(c):
        parts.append(f"{kind}格值{ev_label(c)}，不得进入确定性结论")
    elif str(c.get("evidence_grade", "")).startswith("E2"):
        parts.append("异本图版，不得写成同书图证")
    if caveat:
        parts.append(caveat)
    return "；".join(parts)


def relations(pillars):
    br = [p[1] for p in pillars]
    posmap = {}
    for i, b in enumerate(br):
        posmap.setdefault(b, []).append(POS[i])
    out = []

    for group in SANHE:
        if all(b in posmap for b in group):
            row = "".join(group)
            c = next((x for x in CELLS.get("TB-XJ04", []) if x["row_key"] == row), None)
            out.append({"kind": "三合", "members": group,
                        "positions": [f"{b}({'/'.join(posmap[b])})" for b in group],
                        "cell": c, "note": rel_note(c, "三合", "只作组合定义，不单独定吉凶")})

    for group in SANHUI:
        if all(b in posmap for b in group):
            row = "".join(group)
            c = next((x for x in CELLS.get("TB-XJ04", []) if x["row_key"] == row), None)
            out.append({"kind": "三会", "members": group,
                        "positions": [f"{b}({'/'.join(posmap[b])})" for b in group],
                        "cell": c, "note": rel_note(c, "三会", "只作组合定义，不单独定吉凶")})

    for a, b in CHONG:
        if a in posmap and b in posmap:
            c = next((x for x in CELLS.get("TB-XJ04", []) if x["row_key"] == a + b), None)
            out.append({"kind": "六冲", "members": (a, b),
                        "positions": [f"{a}({'/'.join(posmap[a])})", f"{b}({'/'.join(posmap[b])})"],
                        "cell": c, "note": rel_note(c, "六冲")})

    for a, b in HAI:
        if a in posmap and b in posmap:
            c = next((x for x in CELLS.get("TB-XJ04", []) if x["row_key"] == a + b), None)
            out.append({"kind": "六害", "members": (a, b),
                        "positions": [f"{a}({'/'.join(posmap[a])})", f"{b}({'/'.join(posmap[b])})"],
                        "cell": c, "note": rel_note(c, "六害")})

    for a, b in LIUHE:
        if a in posmap and b in posmap:
            c = next((x for x in CELLS.get("TB-XJ05", []) if x["row_key"] == a + b), None)
            out.append({"kind": "六合", "members": (a, b),
                        "positions": [f"{a}({'/'.join(posmap[a])})", f"{b}({'/'.join(posmap[b])})"],
                        "cell": c, "note": rel_note(c, "六合", "只证组合，取用条件未结构化（U-X11-14）")})

    for group in XING3:
        if all(b in posmap for b in group):
            out.append({"kind": "三刑", "members": group,
                        "positions": [f"{b}({'/'.join(posmap[b])})" for b in group],
                        "cell": xing_evidence(group), "note": "三刑成立；各组何时选用原文未明示（U-X11-17）"})
        else:
            present = [b for b in group if b in posmap]
            if len(present) == 2:
                out.append({"kind": "三刑不全", "members": tuple(present),
                            "positions": [f"{b}({'/'.join(posmap[b])})" for b in present],
                            "cell": xing_evidence(tuple(present)), "note": "三刑缺一，仅登记不成三刑"})

    for a, b in XING_PAIR:
        if a in posmap and b in posmap:
            out.append({"kind": "相刑", "members": (a, b),
                        "positions": [f"{a}({'/'.join(posmap[a])})", f"{b}({'/'.join(posmap[b])})"],
                        "cell": xing_evidence((a, b)), "note": "子卯相刑"})

    for b in SELF_XING:
        if len(posmap.get(b, [])) >= 2:
            out.append({"kind": "自刑", "members": (b, b),
                        "positions": [f"{b}({'/'.join(posmap[b])})"],
                        "cell": xing_evidence((b, b)), "note": "同支重见，按自刑登记"})
    return out


def xing_evidence(group):
    key = "、".join(f"{a}刑{b}" for a, b in zip(group, group[1:])) if len(set(group)) > 1 else f"{group[0]}{group[0]}自刑"
    for c in CELLS.get("TB-XJ02", []):
        if c["column_key"] == "七刑条" and all(g in c["value"] for g in set(group)):
            return c
    for c in CELLS.get("TB-XJ02", []):
        if c["column_key"] == "七刑条" and key in c["value"]:
            return c
    return None


# ---------------- 调候/喜忌/神煞 ----------------
def th_lookup(day, month):
    """调候检索：优先行卯版原表（E1 已核），回退整理者复原表（TH-01）。

    ORIG 每格列 1–5 个候选用神，原表未分主次，不得自行指定「正用神」。
    """
    out = [c for c in CELLS.get("TAB-LXR-TH-01-ORIG", [])
           if c.get("day_master") == day and c["column_key"] == month and cell_ok(c)]
    if out:
        return out
    return [c for c in CELLS.get("TAB-LXR-TH-01", [])
            if c["row_key"] == day + "日主" and c["column_key"].startswith(month + "月令")
            and cell_ok(c)]


def female_th(day, month):
    out = []
    for c in CELLS.get("NM-TBL-02", []):
        if c.get("day_master") == day and c["row_key"] == month and (
                c["column_key"] in ("调候", "最佳夫星") or c["column_key"].startswith("注释")):
            out.append(c)
    return out


def rizi_xiji(day):
    out = []
    for tid in ("T19-01", "T30-01"):
        for c in CELLS.get(tid, []):
            if c.get("day_master") == day and "所喜" in c["column_key"]:
                out.append(c)
    return out


def yima(rel):
    out = []
    for r in rel:
        if r["kind"] != "三合":
            continue
        row = "".join(r["members"])
        c = next((x for x in CELLS.get("T02-01", []) if x["row_key"] == row), None)
        if not c:
            for tid in ("T02-02", "T02-03", "T02-04"):
                c = next((x for x in CELLS.get(tid, []) if x["row_key"] == row), None)
                if c:
                    break
        if c:
            out.append(c)
    return out


def taohua(rel):
    for r in rel:
        if r["kind"] == "三合" and "".join(r["members"]) == "寅午戌":
            return next((x for x in CELLS.get("T03-01", []) if x["row_key"] == "寅午戌"), None)
    return None


# 神煞四表查法（R-XJ-01）：(表号, 以何柱查, 查干或支, 该表所载神煞)
SHENSHA_TABLES = (
    ("JS-SS-01", 0, "支", ("孤辰", "寡宿", "大耗")),
    ("JS-SS-02", 1, "支", ("天德", "月德")),
    ("JS-SS-03", 2, "干", ("天乙贵人", "文昌贵人", "羊刃", "干禄", "红艳煞")),
    ("JS-SS-04", 2, "支", ("将星", "华盖", "驿马", "劫煞", "亡神", "桃花")),
)


def shensha(pillars):
    """按《子平基础概要》神煞例表（一）～（四）实查（R-XJ-01）。

    梁氏口径与通行本有两处不同，照原表走，不掺通行本：
      1) 各神煞查不同之柱——年支查孤辰寡宿大耗、月支查天德月德、
         日干查天乙文昌羊刃干禄红艳、日支查将星华盖驿马劫煞亡神桃花；
         通行本多以年支或日支通查。
      2) 羊刃只取阳干（甲卯、丙午、戊午、庚酉、壬子），阴干五格原表留空
         （R-XJ-02）。同表干禄、红艳阴干俱全，可知是有意不列，不是漏抄。
         故阴干日主此处不出羊刃，不以「乙→寅」之类通行说法补。

    格值为空者跳过，不猜。值有多字者（如庚日天乙「未丑」）逐字比对四柱。
    只报「见某支／某干」，不判吉凶——神煞本身无吉凶，须与日主论生克
    （R61／R178／R187）；而 R-YS 系列另有吉凶之说，两说并存，本器不代裁。
    """
    out = []
    for tid, k, kind, names in SHENSHA_TABLES:
        key = pillars[k][1] if kind == "支" else pillars[k][0]
        # 本表之值落干还是落支，由值本身判定：表二为干，表三为支
        for c in CELLS.get(tid, []):
            if c["column_key"] != key or c["row_key"] not in names:
                continue
            val = (c["value"] or "").strip()
            if not val:
                continue
            chars = [x for x in val]
            where = "干" if all(x in STEMS for x in chars) else "支"
            idx = 0 if where == "干" else 1
            hits = [(POS[i], p) for i, p in enumerate(pillars) if p[idx] in chars]
            out.append({"table": tid, "name": c["row_key"], "key": key,
                        "value": val, "where": where, "hits": hits, "cell": c})
    return out


# ---------------- 宰公日时诀（Part 50；日柱×时柱二维定位） ----------------
def zaigong_dayhour(pillars):
    """《宰公要诀》日时诀：按（日柱, 时柱）直查 R-ZG 与此表格值。

    本包唯一以「日柱×时柱」二维定位的一类规则：六十表给结局，提要条给机理。
    表空白照写「原书空白」，不拿提要反推表值；两者极性相反者并列，本器不代裁。
    """
    day, hour = pillars[2], pillars[3]
    want = {"日:" + day, "时:" + hour}
    rules = []
    for r in RULES:
        if not r["rule_id"].startswith("R-ZG-"):
            continue
        if r.get("deterministic_use") == "禁止":
            continue
        tg = {x for x in (r.get("trigger_tags") or "").split("|") if x}
        if want <= tg:
            rules.append(r)
    cells = [c for c in TABLES
             if c["table_id"].startswith("ZG-DT-")
             and c["row_key"] == day and c["column_key"] == hour[1] + "时"
             and c.get("deterministic_use") != "禁止"]
    return rules, cells


# ---------------- 规则检索 ----------------
def relevant_rules(exp, rel, gender, limit=15):
    kws = []
    tgs = tg_count(exp)
    for tg, n in tgs.most_common(6):
        kws.append(tg)
    if any(t in tgs for t in ("正官", "七杀")):
        kws.append("官杀")
    if any(t in tgs for t in ("正财", "偏财")):
        kws.append("财")
    if any(t in tgs for t in ("正印", "偏印")):
        kws.append("印")
    if any(t in tgs for t in ("食神", "伤官")):
        kws.append("食伤")
    kinds = {r["kind"] for r in rel}
    for k, v in (("六冲", "冲"), ("六害", "害"), ("三合", "三合"), ("三会", "三会"), ("三刑", "刑"), ("相刑", "刑"), ("自刑", "刑")):
        if k in kinds:
            kws.append(v)
    kws += [exp[2]["stem"] + "日主", "调候"]
    if gender == "女":
        kws.append("女命")
    kws = list(dict.fromkeys(kws))

    scored = []
    for r in RULES:
        if r["deterministic_use"] == "禁止":
            continue
        if r["scope"] == "女命" and gender != "女":
            continue
        if r["scope"] == "男命" and gender != "男":
            continue
        s = 0
        for k in kws:
            if k in r["theme"]:
                s += 3
            if k in r["rule_text"]:
                s += 1
        if s >= 3:
            scored.append((s, r))
    scored.sort(key=lambda x: (-x[0], x[1]["rule_id"]))
    return kws, scored[:limit]


# ---------------- 条件匹配（三段） ----------------
# 命盘特征只放**结构上确定成立**的事实（E6），不放任何需要判断的结论。
# 凡命盘给不出的维度（根气／格局／调候／流年／流月／用神法），带该标签的规则一律落在
# 「部分满足」并注明缺项——不用关键词相似度硬凑成命中。
UNSUPPLIED = ("根气", "格局", "调候", "流年", "流月", "用神法", "日柱", "火旺")


def _by_dim(tags):
    """「月:寅」→ {月:{寅}}；无冒号的（恒真／大运）记为布尔维度。"""
    d = {}
    for x in tags:
        dim, _, val = x.partition(":")
        d.setdefault(dim, set()).add(val)
    return d


def chart_tags(a):
    t = set()
    if a["gender"] == "女":
        t.add("性别:女")
    elif a["gender"] == "男":
        t.add("性别:男")
    t.add("月:" + a["pillars"][1][1])
    t.add("日主:" + a["pillars"][2][0])
    for tg, n in a["ten_gods"].items():
        if n:
            t.add("十神:" + tg)
    for p in a["pillars"]:
        t.add("支:" + p[1])
    for r in a["relations"]:
        for k in ("冲", "合", "会", "刑", "害", "拱", "夹"):
            if k in r["kind"]:
                t.add("关系:" + k)
    if a["missing"]:
        t.add("五行缺")
    if a["dayun"]:
        t.add("大运")
    if a.get("liunian"):
        t.add("流年")
    t.add("恒真")  # 次序性规定对所有命例恒成立
    return t


def match_rules(tags, gender):
    """把规则按 trigger_tags 与命盘特征比对，分三段返回。

    hit     ：规则标签全部被命盘特征覆盖——条件成立（仍须看证据等级）
    partial ：有交集但不全，附缺项；缺项若属 UNSUPPLIED，说明是命盘未提供而非不成立
    na      ：conditions 未结构化，抽不出标签，不可判定（不用关键词补，另列）
    """
    hit, partial, na = [], [], []
    ct = _by_dim(tags)
    for r in RULES:
        if r.get("deterministic_use") == "禁止":
            continue
        # 宰公日时诀（R-ZG-*）是「日柱×时柱」二维定位，由 zaigong_dayhour() 专节处理；
        # 神煞探源（R-SP-*）的条件是「寅午戌全＋丙丁合计≥5」这类计数式，
        # 单值交集模型表达不了，硬塞进来只会给每个命盘添空 partial。
        # 两类都不进通用匹配——宁可标「本器未落算」，不用相似度凑命中。
        if r["rule_id"].startswith(("R-ZG-", "R-SP-")):
            continue
        if r.get("scope") == "女命" and gender != "女":
            continue
        if r.get("scope") == "男命" and gender != "男":
            continue
        tg = {x for x in (r.get("trigger_tags") or "").split("|") if x}
        if not tg:
            na.append(r)
            continue
        # 同一维度多值取「或」（月支不可能同时是四支），跨维度取「且」
        miss = []
        for dim, vals in _by_dim(tg).items():
            have = ct.get(dim, set())
            if vals == {""}:           # 布尔特征：恒真／大运／五行缺…
                if "" not in have:
                    miss.append(dim)
            elif not (vals & have):
                miss.append(dim + ":" + "/".join(sorted(vals)))
        if miss:
            partial.append((r, sorted(miss)))
        else:
            hit.append((r, []))
    hit.sort(key=lambda x: x[0]["rule_id"])
    partial.sort(key=lambda x: (len(x[1]), x[0]["rule_id"]))
    return hit, partial, na


def match_cases(pillars):
    out = []
    for c in CASES:
        if c["case_completeness"] != "完整四柱":
            continue
        if [c["year_pillar"], c["month_pillar"], c["day_pillar"], c["hour_pillar"]] == pillars:
            out.append(c)
    return out


# ---------------- 冲突/未决 ----------------
def pick_conflicts(rel, gender, th, fth, guo, cases, day, month):
    ids = []
    kinds = {r["kind"] for r in rel}
    if kinds & {"六冲", "六害"}:
        ids.append("F-X11-02")
    if th or fth:
        ids += ["F04", "F06", "F12"]
        for c in CONFLICTS:
            if c["conflict_id"].startswith("F-X12-0") and (day + "日" in c["topic"] and month + "月" in c["topic"]):
                ids.append(c["conflict_id"])
    if guo:
        ids += ["F05", "F06"]
    if fth:
        ids += ["F-X13-001", "F-X13-002", "F-X13-006", "F-X13-008", "F-X13-010", "F-X13-011"]
    for c in cases:
        if c["original_id"] in ("K-02", "K-03"):
            ids += ["F-X12-06", "F-X12-07"]
    by_id = {c["conflict_id"]: c for c in CONFLICTS}
    return [by_id[i] for i in dict.fromkeys(ids) if i in by_id]


def pick_unresolved(rel, th, fth, guo):
    ids = []
    kinds = {r["kind"] for r in rel}
    if kinds & {"六冲", "六害"}:
        ids += ["U-X11-01", "U-X11-02", "U-X11-13"]
    if kinds & {"三刑", "三刑不全", "相刑", "自刑"}:
        ids += ["U-X11-04", "U-X11-11"]
    if any(c["verification_status"] == "待核" for c in th):
        ids += ["U-X12-01", "U-X12-08"]
    if any(c["verification_status"] == "冲突" for c in th):
        ids += ["U-X12-02"]
    if th:
        ids += ["U-X12-07"]
    if fth:
        ids += ["U13-08", "U13-05", "U13-07"]
    by_id = {u["unresolved_id"]: u for u in UNRESOLVED}
    out = []
    for i in dict.fromkeys(ids):
        u = by_id.get(i)
        if not u:
            continue
        if u["status"].startswith("已关闭") or u["status"].startswith("已裁定") or u["status"].startswith("已处置"):
            continue
        out.append(u)
    return out


# ---------------- 报告 ----------------
def stage12(stem, branch):
    """长生十二宫（阳干顺行、阴干逆行）。E6 结构计算，非梁氏判断。"""
    start = BRANCHES.index(CHANGSHENG[stem])
    i = BRANCHES.index(branch)
    d = (i - start) % 12 if stem in YANG else (start - i) % 12
    return STAGE12[d]


def kongwang(pillar):
    """旬空：由干支序号推该旬未及之两支。"""
    i = JIAZI.index(pillar)
    b0 = (i - i % 10) % 12
    return {BRANCHES[(b0 + 10) % 12], BRANCHES[(b0 + 11) % 12]}


def xingtai(pillars, exp, wx, missing):
    """形态判定（R-SZ-001／003／014／016／017）。只报结构，不下断语。"""
    day, month = pillars[2][0], pillars[1][1]
    season = SEASON[month]
    stems = "".join(p[0] for p in pillars)
    branches = [p[1] for p in pillars]

    # R-SZ-017 根气：逐支取十二宫，按临官帝旺／长生／墓库余气三档
    roots = []
    for k, p in enumerate(pillars):
        st = stage12(day, p[1])
        tier = ("重" if st in ("临官", "帝旺") else
                "次" if st == "长生" else
                "轻" if st in ("墓", "绝", "胎", "养") else "未列")
        roots.append({"pos": POS[k], "pillar": p, "branch": p[1], "stage": st, "tier": tier})
    n_heavy = sum(1 for r in roots if r["tier"] == "重")

    return {
        "season": season,
        "month": month,
        "xiadong": season in ("夏", "冬"),
        "missing": missing,
        "all_yang": all(s in YANG for s in stems) and all(b in "子寅辰午申戌" for b in branches),
        "all_yin": all(s not in YANG for s in stems) and all(b in "丑卯巳未酉亥" for b in branches),
        "kuigang": pillars[2] in KUIGANG,
        "roots": roots,
        "heavy_roots": n_heavy,
    }


def wuyong_order(a):
    """用神五级取用次序（R-SZ-010～016）。身强弱压到第五级；夏冬豁免。"""
    day, month = a["pillars"][2][0], a["pillars"][1][1]
    th_val = a["th"][0]["value"] if a["th"] else "（无可用格值）"
    mh = HIDDEN[month][0]
    ge = ten_god(day, mh)
    gj = a.get("geju") or {}
    ge_line = (f"{gj.get('name','（未裁）')}·{gj.get('shun','')}；{gj.get('how','')}"
               if gj else f"月令{mh}透干为{ge}（未裁定）")
    return [
        {"lv": 1, "name": "调候用神", "by": "《栏江网》（R-SZ-011）",
         "this": f"{day}日×{month}月格值：{th_val}", "use": True},
        {"lv": 2, "name": "格局用神", "by": "《子平真诠》（R-SZ-012）",
         "this": ge_line, "use": True},
        {"lv": 3, "name": "病药用神", "by": "R-SZ-013",
         "this": ("五行缺" + "、".join(a["missing"])) if a["missing"] else "五行不缺，未见明显之病",
         "use": bool(a["missing"])},
        {"lv": 4, "name": "专旺用神", "by": "R-SZ-014",
         "this": ("日柱" + a["pillars"][2] + "属魁罡名目，成立要件未入库")
                 if a["pillars"][2] in KUIGANG else "非魁罡名目；从旺从势须另核",
         "use": False},
        {"lv": 5, "name": "扶抑用神", "by": "R-SZ-015（第五级，非第一级）",
         "this": "夏冬生人依 R-SZ-016 不论身强弱" if a["xingtai"]["xiadong"]
                 else "须在前四项排除后，才论身强弱取扶抑",
         "use": not a["xingtai"]["xiadong"]},
    ]


# ---------------- 格局裁定（G-01） ----------------
# 依据：R-SS-002～041（沈氏《子平真诠》系统）、R34／R73／R74／R75（字幕）、R148／R243（建禄·外格）
# 门控：只判「格名／顺逆／结构成败」三事；不判吉凶轻重、不判富贵层次、不代定相神。
LU = {"甲": "寅", "乙": "卯", "丙": "巳", "丁": "午", "戊": "巳",
      "己": "午", "庚": "申", "辛": "酉", "壬": "亥", "癸": "子"}
# R-XJ-02：羊刃只论阳干
YANGREN = {"甲": "卯", "丙": "午", "戊": "午", "庚": "酉", "壬": "子"}
GE_NAME = {"正官": "正官格", "七杀": "七杀格", "正财": "正财格", "偏财": "偏财格",
           "正印": "正印格", "偏印": "偏印格", "食神": "食神格", "伤官": "伤官格"}
# R74／R-SS-017：官印食财（善神）顺用，煞伤劫刃（不善神）逆用
SHUN_GE = {"正官格", "正印格", "食神格", "正财格", "偏财格"}
NI_GE = {"七杀格", "伤官格", "偏印格", "羊刃格", "建禄格", "月劫格"}
# 顺用格之忌神（克格神者）与救应（R-SS-013 二次因、R-SS-019／020／021、R-SS-009）
SHUN_CHECK = {
    "正官格": {"ji": ["伤官", "七杀"],
               "jiu": {"伤官": ["正印", "偏印"], "七杀": ["食神", "伤官"]},
               "ji_rule": "R-SS-014", "jiu_rule": "R-SS-013／020"},
    "正财格": {"ji": ["比肩", "劫财"],
               "jiu": {"比肩": ["食神", "伤官", "正官"], "劫财": ["食神", "伤官", "正官"]},
               "ji_rule": "R-SS-014／019", "jiu_rule": "R-SS-013／027"},
    "偏财格": {"ji": ["比肩", "劫财"],
               "jiu": {"比肩": ["食神", "伤官", "正官"], "劫财": ["食神", "伤官", "正官"]},
               "ji_rule": "R-SS-014／019", "jiu_rule": "R-SS-013／027"},
    "正印格": {"ji": ["正财", "偏财"],
               "jiu": {"正财": ["劫财", "比肩"], "偏财": ["劫财", "比肩"]},
               "ji_rule": "R-SS-014", "jiu_rule": "R-SS-021"},
    "食神格": {"ji": ["偏印"], "jiu": {"偏印": ["正财", "偏财"]},
               "ji_rule": "R-SS-009", "jiu_rule": "R-SS-013"},
}
# 逆用格：须有反克之神，无则「该逆不逆」＝破格（R-SS-022）
# need＝反克／化杀之神；alt＝另途（非反克，须人工另辨，不代判为得逆）
NI_CHECK = {
    "七杀格": {"need": ["食神", "正印", "偏印", "劫财"], "alt": [],
               "note": "食神制杀／印化杀／羊刃驾杀", "rule": "R-SS-022／026"},
    "伤官格": {"need": ["正印", "偏印"], "alt": ["正财", "偏财"],
               "note": "印制伤为反克；伤官生财属另途（R-SS-040／041），非反克",
               "rule": "R-SS-022／040"},
    "偏印格": {"need": ["正财", "偏财"], "alt": [],
               "note": "财制枭", "rule": "R-SS-022"},
    "羊刃格": {"need": ["七杀"], "alt": [],
               "note": "羊刃驾杀（R243 另作外格）", "rule": "R-SS-022／R243"},
    "建禄格": {"need": ["正财", "偏财"], "alt": ["食神", "伤官"],
               "note": "月劫用财须带食伤（R-SS-023）", "rule": "R-SS-023"},
    "月劫格": {"need": ["正财", "偏财"], "alt": ["食神", "伤官"],
               "note": "月劫用财须带食伤（R-SS-023）", "rule": "R-SS-023"},
    "比肩格": {"need": ["正财", "偏财"], "alt": ["食神", "伤官"],
               "note": "月令比肩（非禄位，如戊日辰月），同月劫例用财须带食伤", "rule": "R-SS-023／R148"},
}
TIER = ("本气", "中气", "余气")


def ss_strength(desc):
    """落点强弱：2＝透干或地支本气（有力）；1＝中气／余气（藏而力薄）。"""
    if "（透）" in desc or "·本气" in desc:
        return 2
    return 1


def god_pos_count(exp):
    """十神之「位」与「量」两笔账，分开算。

    位（n）：天干一位、地支本气一位——R09「天干两比肩」、R21「天干地支加起来四个」
    数的都是位，不是重。量（w）：透干／本气各 2，中气余气各 1——同一十神压得多重。
    两个口径混用，会把「四个食神」与「一个食神透干」算成一样，故并列而不合并。
    """
    n, w = {}, {}
    for row in exp:
        if row["stem_tg"] != "日主":
            g = row["stem_tg"]
            n[g] = n.get(g, 0) + 1
            w[g] = w.get(g, 0) + 2
        for j, h in enumerate(row["hidden"]):
            g = h["tg"]
            w[g] = w.get(g, 0) + (2 if j == 0 else 1)
            if j == 0:
                n[g] = n.get(g, 0) + 1
    return n, w


def _rooted(exp, i, gods):
    """第 i 柱天干是否「坐根」：本柱支之藏干中有同组之神。

    梁氏言「天干见财，能坐根者」，坐根即干下之支藏同类——干浮无根者不算。
    """
    return any(h["tg"] in gods for h in exp[i]["hidden"])


def shishen_map(pillars, day):
    """十神落点表：{十神: [位置描述…]}。天干标「透」，地支藏干标本/中/余。"""
    m = {}
    for i, p in enumerate(pillars):
        if i != 2:
            m.setdefault(ten_god(day, p[0]), []).append(f"{POS[i]}干{p[0]}（透）")
        for j, h in enumerate(HIDDEN[p[1]]):
            m.setdefault(ten_god(day, h), []).append(f"{POS[i]}支{p[1]}·{TIER[j]}{h}")
    return m


def ge_name_of(god, day, month_branch):
    if god == "比肩":
        return "建禄格" if month_branch == LU[day] else "比肩格"
    if god == "劫财":
        if YANGREN.get(day) == month_branch:
            return "羊刃格"
        return "月劫格"
    return GE_NAME.get(god, god + "格")


def qu_ge(pillars):
    """取格。R-SS-002（月支优先不论透否）＋R34／R73（月令透干为极限，只许一位）。"""
    day, mb = pillars[2][0], pillars[1][1]
    hid = HIDDEN[mb]
    tian = [(f"{POS[i]}干", pillars[i][0]) for i in (0, 1, 3)]
    tou = []
    for idx, h in enumerate(hid):
        for posname, s in tian:
            if s == h:
                tou.append({"tier": TIER[idx], "idx": idx, "stem": h,
                            "pos": posname, "god": ten_god(day, h)})
    tou.sort(key=lambda x: x["idx"])
    if tou:
        pick = tou[0]
        god, how = pick["god"], f"{pick['tier']}{pick['stem']}透于{pick['pos']}"
        if pick["idx"] == 0:
            grade = "本气透干"
        else:
            grade = f"{pick['tier']}透干（本气不透，格根不正之位）"
    else:
        god = ten_god(day, hid[0])
        how = f"月令{mb}藏干全不透，依 R-SS-002「月支优先、不论透否」取本气{hid[0]}"
        grade = "本气不透"
    name = ge_name_of(god, day, mb)
    return {"name": name, "god": god, "how": how, "grade": grade,
            "tou": tou, "month_branch": mb, "hidden": hid,
            "zaxiang": mb in "辰戌丑未" and not tou}


def geju_judge(pillars):
    day = pillars[2][0]
    g = qu_ge(pillars)
    ss = shishen_map(pillars, day)
    name, god = g["name"], g["god"]
    shun = name in SHUN_GE
    rows, verdict, rule_ids = [], "", ["R-SS-002", "R34", "R73"]

    # 格神自身之根气（R-SS-032 孤旺无依之参照，不作断语）
    roots = [x for x in ss.get(god, []) if "支" in x and "（透）" not in x]

    if shun:
        ck = SHUN_CHECK[name]
        rule_ids.append("R74／R-SS-017")
        for ji in ck["ji"]:
            hits = ss.get(ji, [])
            lv = max((ss_strength(x) for x in hits), default=0)
            rows.append({"kind": "忌神", "god": ji, "found": bool(hits),
                         "where": hits, "lv": lv,
                         "rule": ck["ji_rule"]})
            if lv >= 2:
                jiu_gods = ck["jiu"].get(ji, [])
                jiu_hits = [x for jg in jiu_gods for x in ss.get(jg, [])]
                rows.append({"kind": "救应", "god": "／".join(jiu_gods),
                             "found": bool(jiu_hits), "where": jiu_hits,
                             "lv": max((ss_strength(x) for x in jiu_hits), default=0),
                             "rule": ck["jiu_rule"]})
        rule_ids += [ck["ji_rule"], ck["jiu_rule"]]
        ji_lv = max([r["lv"] for r in rows if r["kind"] == "忌神"], default=0)
        jiu_lv = max([r["lv"] for r in rows if r["kind"] == "救应"], default=0)
        if ji_lv == 0:
            verdict = "结构无破（一次因未见败象）"
        elif ji_lv == 1:
            verdict = "结构无破（忌神仅藏中／余气，力薄，不计为败）"
        elif jiu_lv == 2:
            verdict = "结构有破、见救应（二次因）"
        else:
            verdict = "结构破（忌神见而无救）"
    else:
        ck = NI_CHECK[name]
        rule_ids.append("R-SS-022／R74／R-SS-017")
        need_lv = 0
        for ng in ck["need"]:
            h = ss.get(ng, [])
            lv = max((ss_strength(x) for x in h), default=0)
            need_lv = max(need_lv, lv)
            rows.append({"kind": "反克之神", "god": ng, "found": bool(h),
                         "where": h, "lv": lv, "rule": ck["rule"]})
        alt_found = False
        for ag in ck.get("alt", []):
            h = ss.get(ag, [])
            if h:
                alt_found = True
                rows.append({"kind": "另途（非反克）", "god": ag, "found": True,
                             "where": h, "lv": max(ss_strength(x) for x in h),
                             "rule": ck["rule"]})
        rule_ids.append(ck["rule"])
        if need_lv == 2:
            verdict = "该逆得逆（有反克之神）"
        elif need_lv == 1:
            verdict = "反克之神仅藏中／余气（力薄，须人工看）"
        elif alt_found:
            verdict = "无反克之神，另途见（须人工裁，不代判为得逆）"
        else:
            verdict = "该逆不逆（无反克之神，依 R-SS-022 作破格论）"

    # 外格（R243）：建禄带财官、羊刃带七杀
    waige = ""
    if name == "建禄格" and any(ss.get(x) for x in ("正官", "七杀", "正财", "偏财")):
        waige = "建禄带财官，依 R243 另作外格"
        rule_ids.append("R243")
    if name == "羊刃格" and ss.get("七杀"):
        waige = "羊刃带七杀，依 R243 作外格（羊刃驾杀）"
        rule_ids.append("R243")

    # ── 格的专条：偏印格三依据（R-MF-038）、食神变德（R21）
    # 这两条原先一条也没进引擎，故一致性审计里列为「判据缺口」。
    # 它们不是通行说，是梁氏给某一格、某一变例的整组喜忌，能算，就该算。
    exp = expand(pillars)
    special = []
    if name == "偏印格":
        rule_ids.append("R-MF-038")
        special.append("偏印格属逆用，身强弱是次要之论（R-MF-038①）——本格不必先争强弱")
        cai = [(POS[i], exp[i]["stem_tg"]) for i in range(4)
               if i != 2 and exp[i]["stem_tg"] in ("正财", "偏财")]
        cai_root = [p for p, _g in cai if _rooted(exp, POS.index(p), ("正财", "偏财"))]
        if cai_root:
            special.append("天干见财而能坐根（%s干）——R-MF-038②：即是富裕之命"
                           % "、".join(cai_root))
        elif cai:
            special.append("天干见财而不坐根（%s干）——财浮无根，制枭之力薄；"
                           "R-MF-038②只说「能坐根者」，浮财不作富裕之论"
                           % "、".join(p for p, _g in cai))
        shishang = [g for g in ("食神", "伤官")
                    if any(ss_strength(x) == 2 for x in ss.get(g, []))]
        if shishang:
            special.append("另带%s——R-MF-038③：等同食伤生财，与原造透财同作吉论；"
                           "但以格局言，属渐缓可以成就之命，不是一蹴而至" % "、".join(shishang))

    n, _w = god_pos_count(exp)
    sh_n = n.get("食神", 0) + n.get("伤官", 0)
    if sh_n >= 4:
        rule_ids.append("R21")
        if name == "伤官格":
            special.append("食伤共 %d 位——R21：本已作伤官格，不必再言「变」" % sh_n)
        else:
            special.append("食伤共 %d 位（食神 %d／伤官 %d）——R21「食神变德」：食伤合计四个即"
                           "作伤官格，主先贫贱而后荣华。本器仍以月令取格示原格，变格另记、不代裁"
                           % (sh_n, n.get("食神", 0), n.get("伤官", 0)))

    # 双格（R-SS-024／025）：本气已透而另有藏干透出
    double = [t for t in g["tou"] if t["idx"] > 0] if g["tou"] and g["tou"][0]["idx"] == 0 else []
    return {
        "name": name, "god": god, "how": g["how"], "grade": g["grade"],
        "shun": "顺用" if shun else "逆用",
        "shun_rule": "R74／R-SS-017",
        "rows": rows, "verdict": verdict, "waige": waige, "special": special,
        "double": [f"{t['tier']}{t['stem']}透{t['pos']}（{t['god']}）" for t in double],
        "roots": roots, "zaxiang": g["zaxiang"], "hidden": g["hidden"],
        "rule_ids": sorted(set(rule_ids)),
        "tou_desc": [f"{t['tier']}{t['stem']}→{t['pos']}（{t['god']}）" for t in g["tou"]] or ["无"],
    }


def dayun_analysis(a, dayun):
    """大运五法（R-SZ-019～031）。dayun 为干支列表，按运次顺序。"""
    day, month = a["pillars"][2][0], a["pillars"][1][1]
    pb = [p[1] for p in a["pillars"]]
    kw = kongwang(a["pillars"][2])
    bw_branches, bw_absent = BAIWANG[day]
    has_absent = any(b in bw_absent for b in pb)
    out = []
    for i, gz in enumerate(dayun, 1):
        g, b = gz[0], gz[1]
        hit = []
        # R-SZ-019／020 十干败亡运
        if b in bw_branches and not has_absent:
            hit.append(f"十干败亡运（{day}日入{b}，四柱无{bw_absent}）")
        elif b in bw_branches and has_absent:
            hit.append(f"本入{b}为败亡，但四柱已带{bw_absent}，按 R-SZ-019 不忌")
        # R-SZ-022／023 墓库运
        if MUKU_BY_MONTH.get(month) == g:
            heavy = (gz[0] == gz[1]) or (g == b)
            hit.append("墓库运" + ("·干支同气从重（R-SZ-024）" if heavy else "·动则败守成无咎（R-SZ-023）"))
        # R-SZ-025 空亡
        if b in kw:
            hit.append(f"入空亡（{a['pillars'][2]}旬空{''.join(sorted(kw))}），减半吉凶")
        # R-SZ-026 接角
        if i > 1:
            prev = dayun[i - 2][1]
            if JIEJIAO.get(prev) == b:
                hit.append(f"接角运（{prev}交{b}）")
        # R-SZ-028 冲提（只说地支一层）
        for x, y in CHONG:
            if {x, y} == {b, month}:
                hit.append(f"冲提（{b}冲月支{month}），本身无大碍，重在地支")
        # R-MF-014～017 大运冲柱分级（干支双冲才算，单支冲不升级）
        dc = [k for k, p in enumerate(a["pillars"])
              if any({g, p[0]} == {x, y} for x, y in GAN_CHONG)
              and any({b, p[1]} == {x, y} for x, y in CHONG)]
        if dc:
            pos = [POS[k] for k in dc]
            if 1 in dc:
                hit.append("**双冲月柱（冲提）**——R-MF-014：「大运最忌者，是干支双冲月柱」；"
                           "R-MF-015：「双冲月柱之吉凶，是全面性之凶」。"
                           "**与上条 R-SZ-028「本身无大碍」二说并列，本包不合并、不代裁**")
            if 2 in dc:
                hit.append("**双冲日柱**——R-MF-015：「通常是财务、与是非之间」（非全面性之凶）")
            if dc and not ({1, 2} & set(dc)):
                hit.append(f"双冲{'、'.join(pos)}柱——R-MF-016：不作系统性识别，只作单独一项已知因；"
                           "但该运十年中流年若再逢双冲／双合／三合三会／拱合兼冲，按 R-MF-017 作大凶论"
                           "（**须给流年方可判**，本报告不推）")
        # R-SZ-030 拱（同干、支距二，拱中一字）
        for p in a["pillars"]:
            if p[0] == g:
                d = abs(BRANCHES.index(b) - BRANCHES.index(p[1]))
                if d == 2:
                    mid = BRANCHES[(min(BRANCHES.index(b), BRANCHES.index(p[1])) + 1) % 12]
                    hit.append(f"拱{p[1]}／{b}之中一字{mid}（R-SZ-030：主变动，不论吉凶）")
        out.append({"n": i, "gz": gz, "hits": hit})
    return out


# ---------------- 运年定位（当前大运 · 近若干年） ----------------
# 批命不问「一生逐年如何」，问的是「眼下这步运、这几年」。
# 故先把大运铺成公历年区间，再倒推「今年在第几运、第几年」，流年才有落处。
def cur_year():
    import time
    return time.localtime().tm_year


def dayun_spans(dayun, birth_year, start_age):
    """每步大运覆盖的虚岁与公历年区间。起运岁按**虚岁**计（梁氏与命书通用口径）。

    第 k 运（1-based）覆盖虚岁 [start_age+10(k-1), start_age+10k-1]；
    虚岁 = 公历年 − 出生年 + 1，故公历年自 birth_year+start_age+10(k-1)−1 起，共十年。
    """
    if not (dayun and birth_year and start_age):
        return []
    out = []
    for i, gz in enumerate(dayun, 1):
        age0 = start_age + 10 * (i - 1)
        y0 = birth_year + age0 - 1
        out.append({"n": i, "gz": gz, "age_from": age0, "age_to": age0 + 9,
                    "year_from": y0, "year_to": y0 + 9})
    return out


def now_of(spans, year):
    """当前行运：所行之运、该年在此运内第几年。未起运或已出所给运次者返回 None。"""
    for s in spans:
        if s["year_from"] <= year <= s["year_to"]:
            return {"n": s["n"], "gz": s["gz"], "from": s["year_from"],
                    "to": s["year_to"], "idx": year - s["year_from"] + 1,
                    "age_from": s["age_from"], "age_to": s["age_to"], "year": year}
    return None


def load_paipan(path):
    """读 `paipan.py --json` 的输出，取出四柱、性别、大运、起运虚岁。

    为什么要有这一条：起运岁是**手抄最容易错的一个数**，而 paipan 的输出里
    同时有「虚岁」与「交运虚岁」两个数（本盘 9 与 10），差一岁，抄错就让整条运偏掉。
    这里只认「交运虚岁」——birth_year + 交运虚岁 − 1 = 第 1 运起始年。
    """
    import json as _json
    with open(path, encoding="utf-8") as fh:
        d = _json.load(fh)
    st = d.get("start") or {}
    if st.get("交运虚岁") is None:
        raise ValueError("paipan 输出缺「交运虚岁」，定不出运")
    date = str((d.get("input") or {}).get("date") or "")
    inp = d.get("input") or {}
    return {
        "pillars": list(d.get("pillars") or []),
        "gender": inp.get("gender"),
        "dayun": list(d.get("dayun") or []),
        "start_age": int(st["交运虚岁"]),
        "birth_year": int(date[:4]) if date[:4].isdigit() else None,
        "current": d.get("current"),
        # 真太阳时也得带过来：排盘时校正过，报告里若写「未校正」，
        # 来客会以为时柱是将就排的——同一份材料前后矛盾，比缺一项更坏。
        "lon": inp.get("lon"),
        "bj": inp.get("bj"),
        "tst": inp.get("tst"),
        "date": date,
        "time": inp.get("time"),
    }


def recent_years(n=5, end=None):
    """近 n 年，含今年（默认取系统当前年）。「最近五年」是含今年在内往前数五年。"""
    end = end or cur_year()
    n = max(1, int(n))
    return list(range(end - n + 1, end + 1))


# ---------------- 流年层（G-02） ----------------
# 依据：R97（架势）／R122（双冲旬内旬外）／R126（双六合在大运与在流年）／
#       R135（流年非每年有事）／R164（三合三会流年）／R209（冲大运与冲八字之别）／
#       R220（流年互看）／R-MF-017（运中流年四组）。
# 纪律：只列结构上确定成立的事实与条文；不排吉凶次序，不逐年充数。
GAN_HE = [("甲", "己"), ("乙", "庚"), ("丙", "辛"), ("丁", "壬"), ("戊", "癸")]
JIASHI = [
    ("天罗地网·辰戌", {"辰", "戌"}),
    ("天罗地网·戌亥辰巳", {"戌", "亥", "辰", "巳"}),
    ("四正·子午卯酉", {"子", "午", "卯", "酉"}),
    ("四生·寅申巳亥", {"寅", "申", "巳", "亥"}),
    ("四墓·辰戌丑未", {"辰", "戌", "丑", "未"}),
]
WUHU = {"甲": "丙", "己": "丙", "乙": "戊", "庚": "戊", "丙": "庚",
        "辛": "庚", "丁": "壬", "壬": "壬", "戊": "甲", "癸": "甲"}
# 「可断之年」与「只记结构」之分：R135 明言流年非每年有事，故刑、单冲、单合、伏吟、反吟
# 只作结构记录，不入可断之列；架势、双冲、三合三会、双六合、冲运、岁运并临、运中四组方可断。
MAIN_KINDS = {"架势", "双冲", "三合三会", "双六合", "冲运", "岁运并临",
              "R-MF-017", "冲提年", "临官年"}


def year_gz(y):
    """公历年 → 年柱干支（按立春换年；本函数不校立春，跨春节者须以 paipan.py 复核）。"""
    return STEMS[(y - 4) % 10] + BRANCHES[(y - 4) % 12]


def xun_index(gz):
    return JIAZI.index(gz) // 10


def stage_branch(day, stage):
    """日主某长生阶段所临之地支（阳顺阴逆）。"""
    i, s = STAGE12.index(stage), BRANCHES.index(CHANGSHENG[day])
    return BRANCHES[(s + (i if day in YANG else -i)) % 12]


def wuhu_months(ygz):
    """五虎遁：由年干定寅月干，顺排十二月。"""
    i = STEMS.index(WUHU[ygz[0]])
    return [STEMS[(i + k) % 10] + BRANCHES[(2 + k) % 12] for k in range(12)]


def liunian_analysis(a, years, dayun=None, birth_year=None, start_age=None, liuyue=False,
                     spans=None, now=None):
    """逐年列出流年与四柱／大运撞出的结构（E6 计算＋条文引用，不作吉凶排序）。"""
    pbs = [(POS[i], a["pillars"][i]) for i in range(4)]
    nb = [pg[1] for _, pg in pbs]
    day = a["pillars"][2][0]
    jishi = [nm for nm, s in JIASHI if sum(1 for b in set(nb) if b in s) >= 2]
    jmap = dict(JIASHI)
    out = []
    for item in years:
        y = item if isinstance(item, int) else None
        gz = year_gz(item) if isinstance(item, int) else item
        if gz not in JIAZI_SET:
            raise ValueError("流年干支不合法：" + str(gz))
        b, g = gz[1], gz[0]
        age = (y - birth_year + 1) if (y and birth_year) else None
        dy, dy_n, in_dy = "", None, None
        if spans and y:
            sp = next((s for s in spans if s["year_from"] <= y <= s["year_to"]), None)
            if sp:
                dy, dy_n, in_dy = sp["gz"], sp["n"], y - sp["year_from"] + 1
            elif y < spans[0]["year_from"]:
                dy_n = 0                      # 尚未起运
        elif age is not None and start_age is not None and dayun:
            step = (age - start_age) // 10
            if 0 <= step < len(dayun):
                dy, dy_n = dayun[step], step + 1
                in_dy = age - start_age - 10 * step + 1
        rows, ids = [], []

        def add(kind, text, rid, brief=None):
            # brief 是给命书用的短语（命书不许出现 rule_id 与技术术语）
            rows.append({"kind": kind, "text": text, "rule": rid,
                         "brief": brief or kind})
            ids.append(rid)

        # R97 架势
        hitjs = [nm for nm in jishi if b in jmap[nm]]
        if hitjs:
            add("架势", f"流年支{b}入本造已具之{'／'.join(hitjs)}架势；"
                        "R97：流年吉凶先看架势而非流年本身", "R97",
                f"入{'／'.join(hitjs)}架势")

        # 冲（四柱／大运）
        ch = [(p, pg) for p, pg in pbs if any({b, pg[1]} == {x, yy} for x, yy in CHONG)]
        ch_dy = bool(dy) and any({b, dy[1]} == {x, yy} for x, yy in CHONG)
        if ch_dy:
            add("冲运", f"流年{b}冲运支{dy[1]}——R209：流年冲大运主「新发生之事」", "R209",
                "冲大运（新起之事）")
        for p, pg in ch:
            add("冲柱", f"流年{b}冲{p}支{pg[1]}——R209：流年冲四柱为「旧事重讲」", "R209",
                    f"冲{p}柱（旧事重讲）")

        # R122 双冲及旬内旬外
        nch = len(ch) + (1 if ch_dy else 0)
        if nch >= 2:
            same = all(xun_index(gz) == xun_index(pg) for _, pg in ch) if ch else True
            add("双冲", f"双冲（流年与{nch}处相冲）"
                + ("，与本造同属一旬——R122：身边人、祸起萧墙、立刻发作" if same
                   else "，与本造隔旬——R122：旧事被拉回、间接发作"), "R122", "双冲")

        # 六合／双六合
        he6 = [(p, pg) for p, pg in pbs if any({b, pg[1]} == {x, yy} for x, yy in LIUHE)]
        he6_dy = bool(dy) and any({b, dy[1]} == {x, yy} for x, yy in LIUHE)
        if len(he6) + (1 if he6_dy else 0) >= 2:
            add("双六合", "双六合落在流年——R126：只主一年之事（落在大运才主十年）", "R126",
                "双六合")
        elif he6:
            add("六合", f"流年{b}合{he6[0][0]}支{he6[0][1][1]}", "R126", f"合{he6[0][0]}")

        # R164 三合三会
        pool = list(set(nb) | ({dy[1]} if dy else set()))
        he3 = []
        for kind, groups in (("三合", SANHE), ("三会", SANHUI)):
            for grp in groups:
                have = [x for x in pool if x in grp]
                if len(have) == 2 and b in grp and b not in have:
                    he3.append(kind + "".join(grp))
        for t in he3:
            add("三合三会", f"流年{b}凑成{t}——R164：遇三合三会流年必有变；"
                        "若流年干另透一格，可成双格（本报告只标结构，格须人工定）", "R164",
                f"凑成{t}")

        # 刑（E6 结构；本包三刑取法见 TB-XJ04，流年三刑无专条）
        xg = [p for p, pg in pbs if b == pg[1] and b in SELF_XING]
        for p, pg in pbs:
            if b != pg[1] and any({b, pg[1]} <= set(grp) for grp in XING3) or \
                    (b != pg[1] and {b, pg[1]} == set(XING_PAIR[0])):
                xg.append(p)
        if xg:
            add("刑", f"流年{b}与{'、'.join(sorted(set(xg)))}支相刑"
                + ("（自刑）" if any(b == pg[1] for p, pg in pbs if p in xg) else "")
                + "——E6 结构，本包无流年三刑专条，只记不作断", "E6", "相刑")

        # 伏吟／反吟（E6 结构；R-SZ-045 只论年时二柱之反吟伏吟）
        for p, pg in pbs:
            if gz == pg:
                add("伏吟", f"流年{gz}与{p}柱同干支（伏吟）——E6 结构；"
                          "本包无流年伏吟专条，只记不作断", "E6", f"与{p}柱伏吟")
            elif any({g, pg[0]} == {x, yy} for x, yy in GAN_CHONG) and \
                    any({b, pg[1]} == {x, yy} for x, yy in CHONG):
                add("反吟", f"流年{gz}与{p}柱天克地冲（反吟）——E6 结构；"
                          "本包无流年反吟专条，只记不作断", "E6", f"与{p}柱反吟")

        # 岁运并临（R-SZ-041）
        if dy and gz == dy:
            add("岁运并临", f"流年与所行大运同为{gz}——R-SZ-041：为喜用且不与命局成三刑、"
                         "无刑冲克破者其年有喜；为喜用而成三刑、刑冲命局者家人有灾；"
                         "须并看喜忌与刑冲，本报告只标成立", "R-SZ-041", "岁运并临")

        # R220 流年互看
        if he3 and b == stage_branch(day, "临官") and g == HIDDEN[b][0]:
            add("临官年", f"{gz}为{day}日主临官位且天透地藏——R220：三合三会成局者，"
                       "看临官流年方是真正发动之年", "R220", "临官年")

        # R-MF-017 运中流年四组
        if dy:
            dc = [p for p, pg in pbs
                  if any({dy[0], pg[0]} == {x, yy} for x, yy in GAN_CHONG)
                  and any({dy[1], pg[1]} == {x, yy} for x, yy in CHONG)]
            if set(dc) & {"年", "时"}:
                grp = []
                if ch_dy and any({g, dy[0]} == {x, yy} for x, yy in GAN_CHONG):
                    grp.append("①干支双冲")
                if he6_dy and any({g, dy[0]} == {x, yy} for x, yy in GAN_HE):
                    grp.append("②干支双合")
                if he3:
                    grp.append("③三合或三会")
                gong = [x for x in pool if abs(BRANCHES.index(b) - BRANCHES.index(x)) == 2]
                if gong and (ch or he6 or he3):
                    grp.append("④三合拱／会兼冲合")
                if grp:
                    add("R-MF-017", f"大运{dy}双冲{'／'.join(dc)}柱，本年为运中四组之"
                                f"{'、'.join(grp)}——原文作「大凶」论；本报告只标结构命中",
                        "R-MF-017", "运年四组（原文作大凶论）")

        # R-SZ-028 冲提大运之流年诸忌
        if dy and a.get("dayun"):
            dh = next((d["hits"] for d in a["dayun"] if d["gz"] == dy), [])
            if any("冲提" in h for h in dh):
                trig = []
                if nch >= 2:
                    trig.append("重冲")
                if gz == dy:
                    trig.append("岁运并临")
                for nm, lab in (("四正", "四正"), ("四生", "四生"), ("四墓", "四库会集")):
                    if any(nm in x for x in hitjs):
                        trig.append(lab)
                if trig:
                    add("冲提年", f"本年行冲提大运（{dy}），流年见{'、'.join(trig)}——"
                              "R-SZ-028：冲提本身无大碍，然流年见拱冲／三刑／重冲／岁运并临／"
                              "四正／四生／四库会集则另论", "R-SZ-028", "冲提年诸忌")

        # 流月（R118／R-XP-037～043／R-X13-066／R-X13-068／R-MF-018）
        # 落算五口径，缺一不可：
        #   ① 只对「大运、时柱」为限，不延伸年月日（R-XP-038）
        #   ② 月运同途／月运反吟为「主变」（R118／R-XP-041／R-MF-018）
        #   ③ 单式刑合以「流月＋流年＋大运」三柱核计（R-XP-040）
        #   ④ 与流年之单式冲合「不论」（R-XP-039）——列出但不作断，防止人人都双冲
        #   ⑤ 干五年一循环（R-XP-037）——只提示，不逐月铺陈
        # 调候、格局、喜忌不用于流月（R-X13-068）；不必逐月强断（R-X13-066）。
        months = []
        if liuyue and dy:
            tz = a["pillars"][3]
            for mgz in wuhu_months(gz):
                grade, tag, rid = "", "", ""
                if mgz == dy:
                    grade, tag, rid = "主变", "月运同途（干支全同）", "R118"
                elif (any({mgz[0], dy[0]} == {x, yy} for x, yy in GAN_CHONG)
                      and any({mgz[1], dy[1]} == {x, yy} for x, yy in CHONG)):
                    grade, tag, rid = "主变", "月运反吟（天克地冲）", "R118"
                elif any({mgz[1], dy[1]} == {x, yy} for x, yy in CHONG):
                    grade, tag, rid = "主变", "月运对冲（支冲）", "R-XP-041"
                elif (any({mgz[0], dy[0]} == {x, yy} for x, yy in GAN_HE)
                      and any({mgz[1], dy[1]} == {x, yy} for x, yy in LIUHE)):
                    grade, tag, rid = "主变", "月运双合", "R118"
                if not tag and tz:
                    if mgz == tz:
                        grade, tag, rid = "次", "与时柱伏吟", "R-XP-038"
                    elif any({mgz[1], tz[1]} == {x, yy} for x, yy in CHONG):
                        grade, tag, rid = "次", "与时柱相冲", "R-XP-038"
                trio = [mgz[1], b, dy[1]]
                for grp in XING3:
                    if set(grp) <= set(trio):
                        grade = "主变"
                        tag = "流月／流年／大运凑" + "".join(grp) + "三刑"
                        rid = "R-XP-040"
                        break
                if not tag:
                    # R-XP-039：与流年仅单式冲或单式合者，不论吉凶
                    only_chong = any({mgz[1], b} == {x, yy} for x, yy in CHONG)
                    only_he = any({mgz[1], b} == {x, yy} for x, yy in LIUHE)
                    if only_chong or only_he:
                        grade, tag, rid = "不论", \
                            "与流年单式" + ("冲" if only_chong else "合"), "R-XP-039"
                if tag:
                    months.append({"gz": mgz, "tag": tag,
                                   "grade": grade, "rule": rid})
            if months:
                ids.extend(sorted({m["rule"] for m in months}))

        for r in rows:
            r["main"] = r["kind"] in MAIN_KINDS
        out.append({"year": y, "gz": gz, "age": age, "dayun": dy,
                    "dy_n": dy_n, "in_dy": in_dy,
                    "rows": rows, "n_main": sum(1 for r in rows if r["main"]),
                    "months": months, "rule_ids": sorted(set(ids))})
    return out


def analyze(pillars, gender=None, dayun=None, liunian=None, birth_year=None,
            start_age=None, liuyue=False, recent=None, base_year=None):
    if len(pillars) != 4 or any(p not in JIAZI_SET for p in pillars):
        raise ValueError("四柱须为四个合法干支，例如：戊辰 戊午 甲午 乙丑")
    spans = dayun_spans(dayun, birth_year, start_age)
    now = now_of(spans, base_year or cur_year())
    if not liunian and recent:
        liunian = recent_years(recent, base_year or cur_year())
    exp = expand(pillars)
    day, month = pillars[2][0], pillars[1][1]
    rel = relations(pillars)
    wx = wuxing_count(exp)
    tg = tg_count(exp)
    missing = [e for e in "木火土金水" if wx[e] == 0]

    th = th_lookup(day, month)
    fth = female_th(day, month) if gender == "女" else []
    xiji = rizi_xiji(day)
    ym = yima(rel)
    thua = taohua(rel)
    ss = shensha(pillars)
    guo = day + "日主·" + month + "月令"
    cases = match_cases(pillars)
    kws, rrules = relevant_rules(exp, rel, gender)
    conflicts = pick_conflicts(rel, gender, th, fth, True, cases, day, month)
    unres = pick_unresolved(rel, th, fth, True)

    xt = xingtai(pillars, exp, wx, missing)
    res = {
        "pillars": pillars, "gender": gender, "expanded": exp,
        "wuxing": wx, "missing": missing, "ten_gods": tg,
        "relations": rel, "th": th, "female_th": fth, "xiji": xiji,
        "yima": ym, "taohua": thua, "shensha": ss, "guo": guo,
        "cases": cases, "keywords": kws, "rules": rrules,
        "conflicts": conflicts, "unresolved": unres,
        "xingtai": xt,
    }
    res["geju"] = geju_judge(pillars)
    res["wuyong"] = wuyong_order(res)
    res["dayun"] = dayun_analysis(res, dayun) if dayun else []
    res["dayun_spans"] = spans
    res["now"] = now
    res["liunian"] = (liunian_analysis(res, liunian, dayun, birth_year, start_age, liuyue,
                                       spans=spans, now=now)
                      if liunian else [])
    # 神煞探源起例（R-SP-001～049）：与四表实查互补，起例照原文，无起例者标待人工
    res["shensha_sp"] = shensha_calc.evaluate(
        pillars, gender=gender, dayun=dayun,
        liunian=[x for x in (liunian or []) if isinstance(x, str)],
        shensha_hits=ss)
    tags = chart_tags(res)
    res["chart_tags"] = sorted(tags)
    h, pt, na = match_rules(tags, gender)
    res["rule_hit"] = h
    res["rule_partial"] = pt
    res["rule_na"] = na
    return res


def render_md(a):
    L = []
    P = a["pillars"]
    L.append("# 梁湘润批八字·结构化分析（证据门控版）")
    L.append("")
    L.append("> 本报告只从已核／条件允许的梁湘润资料检索，不排历法、不补四柱、不以通行术数补写原文。"
             "标“待核／冲突／候选／排除”的内容不得当作定论。")
    L.append("")
    L.append("## 一、四柱输入")
    L.append("")
    L.append(f"- 四柱：{'　'.join(P)}（年／月／日／时）")
    L.append(f"- 性别：{a['gender'] or '未提供（女命专章不代入）'}")
    L.append("- 校验：四柱均为六十甲子合法干支；未做历法换算。")
    L.append("")

    L.append("## 二、四柱、藏干与十神（结构展开 E6）")
    L.append("")
    L.append("| 柱 | 干支 | 天干十神 | 藏干（本气→余气） |")
    L.append("|---|---|---|---|")
    for r in a["expanded"]:
        hs = "、".join(f"{h['stem']}·{h['tg']}" for h in r["hidden"])
        L.append(f"| {r['pos']} | {r['pillar']} | {r['stem_tg']} | {hs} |")
    L.append("")
    L.append("> 藏干与十神为结构展开（E6），不是梁氏判断本身；梁氏对支藏强弱的取法见 R64，"
             "本报告不以通用藏干表替代其取用结论。")
    L.append("")
    L.append("五行计数（天干＋藏干，等权计数，不作旺衰加权）：" + "、".join(f"{k}{v}" for k, v in a["wuxing"].items()))
    L.append("缺五行：" + ("、".join(a["missing"]) if a["missing"] else "无"))
    L.append("十神出现（不含日干）：" + "、".join(f"{k}{v}" for k, v in a["ten_gods"].most_common()))
    L.append("")

    L.append("## 三、形态判定（结构 E6 ＋ R-SZ-001／003／014／016／017）")
    L.append("")
    xt = a["xingtai"]
    L.append(f"- 月支：{xt['month']}（{xt['season']}）→ "
             + ("**夏冬生人，以调候为第一，不论身强弱**（R-SZ-016）" if xt["xiadong"]
                else "春秋生人，不在 R-SZ-016 豁免之列，仍须依 R-SZ-015 论扶抑"))
    L.append(f"- 五行缺：{'、'.join(xt['missing']) if xt['missing'] else '不缺'}"
             + ("（缺一者依 R-SZ-001 先看是否为财官、再看是否为调候）"
                if len(xt["missing"]) == 1 else ""))
    L.append(f"- 全阳：{'是' if xt['all_yang'] else '否'}；全阴：{'是' if xt['all_yin'] else '否'}（R-SZ-003）")
    L.append(f"- 日柱 {a['pillars'][2]}：{'属魁罡名目' if xt['kuigang'] else '非魁罡名目'}"
             "（R-SZ-014 只列名目，成立要件未入库，本报告不判成立）")
    L.append("")
    L.append("根气轻重（R-SZ-017：临官帝旺为重、长生次之、墓库余气为轻；十二宫为 E6 结构计算）：")
    L.append("")
    L.append("| 柱 | 干支 | 日主在此支之宫位 | 档 |")
    L.append("|---|---|---|---|")
    for r in xt["roots"]:
        L.append(f"| {r['pos']} | {r['pillar']} | {r['stage']} | {r['tier']} |")
    L.append("")
    L.append(f"> 重根 {xt['heavy_roots']} 处。根气只定「漂浮／扎实」之结构面，不得据此单独断富贵贫贱——"
             "原文另言「若无根……然也未必贫贱」。")
    L.append("")
    if a["pillars"][2][0] in ("戊", "己"):
        L.append("> **戊己土之生旺库有二说，本表只取其一**：上表按阴阳顺逆十二宫（己长生在酉、墓在丑，"
                 "与十干禄「丁己禄在午」自洽）；梁氏《子平母法》p225 另主「丙丁与戊己皆以火之生寅、旺午、库戌」"
                 "（**R-MF-039**，E3／部分核），即己土之生旺库随火而不随水土。**二说未合并**——"
                 "戊己日主的根气须两说并列看，不得只报一档就下断语。")
        L.append("")

    L.append("## 四、用神取用次序（五级，R-SZ-010～016）")
    L.append("")
    L.append("> **次序本身即判断**：同一组四柱，先看调候与先看身强弱，断语相反。"
             "本表按梁氏原次序排，**身强弱在第五级**，不是第一级。")
    L.append("")
    L.append("| 级 | 用神 | 依据 | 本命对应 | 是否取用 |")
    L.append("|---|---|---|---|---|")
    for w in a["wuyong"]:
        L.append(f"| {w['lv']} | {w['name']} | {w['by']} | {w['this']} | "
                 + ("取用" if w["use"] else "不取／待人工") + " |")
    L.append("")
    if xt["xiadong"]:
        L.append(f"**本命判定**：月支 {xt['month']} 属{xt['season']}，依 R-SZ-016「四柱出生于夏、冬之人，"
                 "以调候用神为第一，并没有身强、身弱的问题」，故本命**不套「身弱不能托财官」"
                 "「克泄交加」**，第五级（扶抑）在本命为不适用。")
    else:
        L.append(f"**本命判定**：月支 {xt['month']} 属{xt['season']}，不在 R-SZ-016 豁免之列；"
                 "须先排除调候、格局、病药、专旺四项，才依 R-SZ-015 论身强弱取扶抑。")
    L.append("")

    L.append("## 五、采用的梁氏分析路径")
    L.append("")
    L.append("依 T06-01～03（三步）与 T21-01～05（五步）并置：")
    L.append("")
    L.append("1. 五行全不全（须查支藏天干）——本报告只作结构统计。")
    L.append("2. 刑冲合会（含拱、夹拱）——本报告判已收录的冲、害、三合、三会、六合、刑；"
             "拱夹未收录完整表，不补算。")
    L.append("3. 定格局——已按 R-SS-002／R34／R73 取格、R74 定顺逆、R-SS-012～015 判结构成败，见第七节。")
    L.append("4. 调候——先看有无忌神（T21-04），再列调候格值。")
    if a.get("liunian"):
        L.append("5. 流年架势——已按 R97 判架势，并逐条列双冲（R122）、三合三会（R164）、"
                 "冲运与冲柱之别（R209）、临官年（R220），见第十节。")
    else:
        L.append("5. 流年架势——本次未提供流年（`--liunian`），不分析。")
    L.append("")

    L.append("## 六、刑冲合会判定")
    L.append("")
    if a["relations"]:
        L.append("| 类型 | 成员（位置） | 资料格值 | 证据与状态 |")
        L.append("|---|---|---|---|")
        for r in a["relations"]:
            c = r.get("cell")
            val = f"{c['cell_id']}：{c['value']}" if c else "未检索到格值"
            ev = ev_label(c) if c else "无格值"
            note = (r.get("note") or "").strip()
            tail = f"{ev}；{note}" if note else ev
            L.append(f"| {r['kind']} | {'、'.join(r['positions'])} | {val} | {tail} |")
    else:
        L.append("未检出已收录的六冲、六害、三合、三会、三刑组合。")
    L.append("")
    L.append("> 上表“证据与状态”一律取自 `data/tables.csv` 格值字段，不在此写死等级。"
             "六冲／六害 12 格与六合 6 格已按源书《子平基础概要》行卯版书内10 原页回图升 E1，"
             "但该章与《概论》同源，引用须标“同源章图版”（U-X11-14）；"
             "七刑各组“何时选用”原文未明示（U-X11-17）。拱夹未收录完整表，本报告不补算。")
    L.append("")

    gj = a["geju"]
    L.append("## 七、格局裁定（取格·顺逆·结构成败）")
    L.append("")
    L.append(f"**取格：{gj['name']}**（{gj['how']}）")
    L.append("")
    L.append(f"- 月令：{a['pillars'][1][1]}；藏干：" +
             "、".join(f"{TIER[i]}{h}" for i, h in enumerate(gj["hidden"])) +
             f"；日主：{a['pillars'][2][0]}")
    L.append(f"- 透干明细：{'；'.join(gj['tou_desc'])}；取格依据：{gj['grade']}")
    L.append("- 出处：R34（取格以月令为准，临官位透出只许一位）、R73（月令透出天干是极限）、"
             "R-SS-002（月支优先，不论透否）")
    if gj["double"]:
        L.append(f"- **双格**：另有 {'；'.join(gj['double'])}。依 R-SS-024 以月柱所成之格为第一优先；"
                 "R-SS-025 五组易误认（官印双全／食神生财／食神逢枭／煞印相生／七煞制刃）须另辨，本程序不代辨。")
    if gj["zaxiang"]:
        L.append("- **杂气**：月支属辰戌丑未且藏干全不透。本程序依 R-SS-002 取本气；"
                 "R-SS-035 另有「五行所属由透干与会局定，三不透则随日主」之说，二说未合，须人工裁。")
    L.append("")
    L.append(f"**顺逆：{gj['shun']}**（{gj['shun_rule']}：官印食财为善神须顺用，煞伤劫刃为不善神须逆用）")
    L.append("")
    L.append("**结构成败**（只判「忌神见不见、救应在不在」，不判吉凶轻重）")
    L.append("")
    L.append("| 项 | 十神 | 判定 | 力度 | 落点 | 依据 |")
    L.append("|---|---|---|---|---|---|")
    for r in gj["rows"]:
        ws = sorted(r["where"], key=lambda x: -ss_strength(x))
        where = ("、".join(ws[:4]) + (f" 等{len(ws)}处" if len(ws) > 4 else "")) if ws else "—"
        lv = {2: "有力（透／本气）", 1: "力薄（中余气）", 0: "—"}.get(r.get("lv", 0), "—")
        L.append(f"| {r['kind']} | {r['god']} | {'见' if r['found'] else '未见'} | {lv} | {where} | {r['rule']} |")
    L.append("")
    L.append(f"**结论：{gj['verdict']}**")
    if gj["waige"]:
        L.append("")
        L.append(f"- {gj['waige']}")
    if gj["roots"]:
        L.append(f"- 格神根气（参照 R-SS-032「孤旺无依」，不作断语）：{'、'.join(gj['roots'])}")
    else:
        L.append("- 格神根气：地支无同类，属**孤旺无依**之形态（R-SS-032），须与日主强弱合看。")
    L.append("")
    L.append("> 本节只落算「格名、顺逆、忌神／救应」三层。**相神（R-SS-033／034）、有情有力（R-SS-028～030）、"
             "十四制式（R-SS-036～041）、双格轻重（R-SS-024～026）均须人工对条文**，程序不代判；"
             "吉凶、富贵层次不在此节，亦不在本报告结论之列。")
    L.append("")

    L.append("## 八、调候与日主喜忌")
    L.append("")
    if a["th"]:
        for c in a["th"]:
            orig = c["table_id"].endswith("-ORIG")
            label = "余氏调候原表·行卯版（并陈）" if orig else "整理者复原表 TH-01"
            L.append(f"- 调候（{label}）：{c['value']}　[{c['cell_id']}｜{ev_label(c)}｜{c['source_locator']}]")
            if orig:
                L.append("  - 原表该格并列列示 1–5 个候选用神，未分正／副；不得自行指定主用神，"
                         "亦不得据常法补出原表未列之字。")
            elif c["verification_status"] == "待核":
                L.append("  - 该格为待核（体例不对位），不得作确定性结论（U-X12-01）。")
    else:
        L.append("- 调候表（原表与 TH-01）均未检索到该日主／月令的可条件使用格值。")
    if a["gender"] == "女":
        if a["female_th"]:
            for c in a["female_th"]:
                L.append(f"- 女命调候／最佳夫星（NM-TBL-02）：{c['column_key']}＝{c['value']}　"
                         f"[{c['cell_id']}｜{ev_label(c)}｜{c['source_locator']}]")
        else:
            L.append("- 女命调候表（NM-TBL-02）未检索到该日主／月令格值。")
    elif a["gender"] is None:
        L.append("- 性别未提供：女命调候最佳夫星表（NM-TBL-02）不代入；如需女命专章，请补充性别。")
    for c in a["xiji"]:
        L.append(f"- 日主喜忌：{c['column_key']}＝{c['value']}　[{c['cell_id']}｜{ev_label(c)}｜{c['source_locator']}]")
    L.append("")
    L.append("> 调候与日主喜忌是两套体系（R192，见 F06）；先后次序未裁，故并列而不强行合一。"
             "调候检索优先取行卯版原表（120 格中 119 格 E1 已核，1 格冲突禁用）；"
             "整理者复原表 TH-01 仅 31 格部分核，另 85 格为「原书无明文」，不得按常法补值。")
    L.append("")

    L.append("## 九、大运诸法（十干败亡／墓库／空亡／接角／冲提／拱夹；R-SZ-018～031＋R-MF-014～017）")
    L.append("")
    if a["dayun"]:
        sp_map = {s["n"]: s for s in (a.get("dayun_spans") or [])}
        now = a.get("now")
        if sp_map:
            L.append("| 运次 | 大运 | 公历年（虚岁） | 命中之法 |")
            L.append("|---|---|---|---|")
            for d in a["dayun"]:
                s = sp_map.get(d["n"], {})
                mark = " **←现行**" if now and now["n"] == d["n"] else ""
                L.append(f"| {d['n']} | {d['gz']}{mark} | "
                         f"{s.get('year_from', '—')}–{s.get('year_to', '—')}"
                         f"（{s.get('age_from', '—')}–{s.get('age_to', '—')}） | "
                         + ("；".join(d["hits"]) if d["hits"] else "未触发") + " |")
        else:
            L.append("| 运次 | 大运 | 命中之法 |")
            L.append("|---|---|---|")
            for d in a["dayun"]:
                L.append(f"| {d['n']} | {d['gz']} | "
                         + ("；".join(d["hits"]) if d["hits"] else "未触发") + " |")
        L.append("")
        if now:
            L.append(f"> 当前行第 {now['n']} 运（{now['gz']}，{now['from']}–{now['to']}，"
                     f"虚岁{now['age_from']}–{now['age_to']}），今年为运内第 {now['idx']} 年。")
            L.append("")
        L.append("> 本表只判「法是否成立」，不判吉凶轻重。十干败亡运之「可以不必考虑是什么格局」"
                 "为原文语，故该运一旦成立，不再问格局成败；墓库运只主困滞（动则败、守成无咎），"
                 "不作破败。空亡只减半吉凶。「夹」之取法原文未给，本报告不判。")
    else:
        L.append("未提供大运，故十干败亡运、墓库运、空亡、接角、冲提、拱夹诸法均未判。")
        L.append("")
        L.append("用法：`--dayun 丙子,丁丑,戊寅`（按运次顺序只给干支；本工具不推起运岁）。")
    L.append("")

    L.append("## 十、流年（架势／双冲／三合三会／冲运冲柱；R97／R122／R126／R164／R209／R220／R-MF-017）")
    L.append("")
    if a.get("liunian"):
        L.append("> 流年层只列结构命中与条文出处，不排吉凶次序。R135：「流年不是每年都有事可断」，"
                 "未命中之年即不作断语，不逐年充数。")
        L.append("")
        n_main = sum(1 for ln in a["liunian"] if ln["n_main"])
        L.append(f"共 {len(a['liunian'])} 年，其中 **{n_main} 年见主命中**；"
                 f"余 {len(a['liunian']) - n_main} 年只记结构，依 R135 不作断语。")
        L.append("")
        L.append("| 年 | 流年 | 虚岁 | 所行大运 | 主命中（可断） | 只记结构（不作断） |")
        L.append("|---|---|---|---|---|---|")
        for ln in a["liunian"]:
            mm = "、".join(sorted({r["kind"] for r in ln["rows"] if r["main"]})) or "—"
            aux = "、".join(sorted({r["kind"] for r in ln["rows"] if not r["main"]})) or "—"
            dycell = ln["dayun"] or "—"
            if ln.get("in_dy"):
                dycell += f"·第{ln['in_dy']}年"
            elif ln.get("dy_n") == 0:
                dycell = "未起运"
            L.append(f"| {ln['year'] or '—'} | {ln['gz']} | {ln['age'] or '—'} | "
                     f"{dycell} | {mm} | {aux} |")
        L.append("")
        L.append("### 逐条依据")
        L.append("")
        for ln in a["liunian"]:
            L.append(f"**{ln['year'] or ''} {ln['gz']}**"
                     + (f"（虚岁{ln['age']}）" if ln["age"] else ""))
            L.append("")
            if not ln["rows"]:
                L.append("- 无结构触发。R135：不必逐年批流年，此年不作断语。")
            elif not ln["n_main"]:
                L.append("- 本年只记结构，无主命中。R135：不作断语。")
            for r in ln["rows"]:
                tag = "可断" if r["main"] else "只记"
                L.append(f"- 【{tag}·{r['kind']}】{r['text']}（`{r['rule']}`）")
            mmain = [m for m in ln["months"] if m["grade"] == "主变"]
            msec = [m for m in ln["months"] if m["grade"] == "次"]
            mnon = [m for m in ln["months"] if m["grade"] == "不论"]
            for m in mmain:
                tail = ("；R-MF-018 与月运反吟并为运岁最应验之时段"
                        if ("同途" in m["tag"] or "反吟" in m["tag"]) else "")
                L.append(f"- [流月·主变] {m['gz']}：{m['tag']}（`{m['rule']}`{tail}）")
            for m in msec:
                L.append(f"- [流月·次] {m['gz']}：{m['tag']}（`{m['rule']}`；"
                         "流月只对运与时柱，不延伸年月日三柱）")
            if mnon:
                L.append("- [流月·不论] "
                         + "、".join(f"{m['gz']}（{m['tag']}）" for m in mnon)
                         + "（`R-XP-039`：与流年单式冲合人人皆遇，不作吉凶论）")
            L.append("")
        L.append("> 流月落算：月运同途／月运反吟（`R118`／`R-XP-041`）、月运支冲、月运双合、"
                 "与流月只对之时柱伏吟／相冲（`R-XP-038`）、流月＋流年＋大运三柱凑刑"
                 "（`R-XP-040`）；与流年单式冲合者只列「不论」（`R-XP-039`）。"
                 "不必逐月强断（`R-X13-066`），调候格局喜忌不用于流月（`R-X13-068`）。")
        L.append("> 未落算：暗拱暗夹延伸至流月（`R-XP-043`，须人工认拱夹）；"
                 "流月干五年一循环（`R-XP-037`，只作提示，不逐月铺陈）；"
                 "流年吉凶之轻重次序，本器不排。")
    else:
        L.append("未提供流年，故架势、双冲旬内旬外、三合三会流年、临官年、运中四组均未判。")
        L.append("")
        L.append("用法：`--liunian 2026,2027,2028`（公历年）或 `--liunian 丙午,丁未`（干支）；"
                 "配 `--dayun` 与 `--birth-year`／`--start-age` 方知所行何运；"
                 "只想看「当前大运最近几年」就给 `--recent 5`（含今年，默认 5）；"
                 "加 `--liuyue` 出该年流月与运之伏吟／反吟／双合。")
    L.append("")

    L.append("## 十一、神煞（四表实查）")
    L.append("")
    L.append("> 查法依《子平基础概要》神煞例表（一）～（四）（R-XJ-01）：年支查孤辰／寡宿／大耗，"
             "月支查天德／月德，日干查天乙／文昌／羊刃／干禄／红艳，日支查将星／华盖／驿马／"
             "劫煞／亡神／桃花。**与通行本不同处照原表走**：各神煞查不同之柱，非以年支或日支通查；"
             "羊刃只取阳干，阴干原表留空（R-XJ-02），本器不补。")
    L.append("")
    ss = a.get("shensha") or []
    if not ss:
        L.append("- 四表皆无可查格值。")
    else:
        for x in ss:
            tag = "**见**" if x["hits"] else "不见"
            got = "、".join("%s柱%s" % (p, gz) for p, gz in x["hits"]) if x["hits"] else "四柱无"
            L.append(f"- {x['name']}（{x['table']}，以{x['key']}查）→ {x['value']}　{tag}：{got}"
                     f"　[{x['cell']['cell_id']}｜{ev_label(x['cell'])}]")
    L.append("")
    L.append("> 神煞只报「见／不见」，**不判吉凶**：R61／R178／R187 谓神煞本身无吉凶、须与日主论生克；"
             "而 R-YS 系列另有「某煞主某吉／凶」之说。**两说并存，本器不代裁。**")
    L.append("")

    zg_rules, zg_cells = zaigong_dayhour(a["pillars"])
    L.append("### 宰公日时诀（日柱×时柱：%s日／%s时）" % (a["pillars"][2], a["pillars"][3]))
    L.append("")
    if not zg_rules and not zg_cells:
        L.append("- 本包《宰公要诀》无此日时条目（六十表覆盖 60 日柱 ×12 时支，未及者不补）。")
    else:
        for r in zg_rules:
            L.append("- **%s**（%s｜%s｜%s）：%s"
                     % (r["rule_id"], r["evidence_grade"], r["verification_status"],
                        r["deterministic_use"], r["rule_text"]))
            if r.get("normalized_statement"):
                L.append("  - 归纳：%s" % r["normalized_statement"])
            if r.get("extractor_note"):
                L.append("  - 校记：%s" % r["extractor_note"])
        for c in zg_cells:
            v = (c["value"] or "").strip() or "—"
            L.append("- 六十表 %s（%s）：**%s**　[%s｜%s]%s"
                     % (c["table_id"], c["column_key"], v, c["cell_id"], ev_label(c),
                        "（原书空白）" if v == "—" else ""))
    L.append("")
    L.append("> 日时诀只断该日该时的吉凶取向，**不作整盘结论**；表值与提要两存，"
             "极性相反者（如 F-NEW-07 庚申日乙酉时）本器并列不裁。")
    L.append("")

    sp = a.get("shensha_sp") or []
    if sp:
        from collections import Counter as _C
        cnt = _C(x["status"] for x in sp)
        L.append("### 神煞探源起例（49 条逐条核，SP:s18–s52）")
        L.append("")
        L.append("> 上「四表实查」是《子平基础概要》的神煞例表；此处是《神煞探源》各条的**起例**，两者互补。"
                 "起例一律照原文；原文只给诗诀、或对照表为图版者，标「待人工对表」，"
                 "**不猜、不以通行术数补**。原文有讹字者标「原文待核」，不代改。")
        L.append("")
        L.append("总计：" + "、".join(f"{k} {v}" for k, v in cnt.most_common()) + "。")
        L.append("")
        show = [x for x in sp if x["status"] != shensha_calc.MISS]
        for x in show:
            L.append(f"- [{x['status']}] **{x['rule_id']}** {x['name']}（{x['anchor']}）：{x['detail']}")
        miss = cnt.get(shensha_calc.MISS, 0)
        if miss:
            L.append(f"- （其余 {miss} 条逐条核对不成立，不列。）")
        L.append("")
        L.append("> 起例成立只说明**结构合**，不等于应验：原文自陈此法「不是百分之一百，但总有其或然率存在」。"
                 "神煞本身不判吉凶（R61／R178／R187），吉凶须与日主论生克。")
        L.append("")

    L.append("## 十二、命例对照（只作说明，不作置信度提升）")
    L.append("")
    if a["cases"]:
        for c in a["cases"]:
            L.append(f"- {c['case_id']}（原号 {c['original_id']}）：{c['pillars_raw']}；"
                     f"判断类型 {c['judgment_type']}；证据 {c['evidence_grade']}／{c['verification_status']}")
            L.append(f"  - 梁氏判断：{quote(c['liang_judgment'], 220)}")
            L.append(f"  - 定位：{c['source_locator']}")
            L.append(f"  - 可用于规则验证：{c['suitable_for_rule_validation']}")
    else:
        L.append("- 未找到四柱完全相同的已收录命例。不得以相似命例替代。")
    L.append("")

    L.append("## 十三、规则匹配（条件三段）")
    L.append("")
    L.append("> 判法：把每条规则的 `trigger_tags`（从 conditions 抽出的触发要素）与命盘特征比对——"
             "标签全被覆盖＝**条件成立**；有交集但不全＝**部分满足**（注明缺项）；"
             "conditions 抽不出标签＝**不可判定**。命盘给不出的维度（" + "／".join(UNSUPPLIED) + "）"
             "一律记缺项，**不按关键词相似度补成命中**。")
    L.append("")
    L.append("命盘特征：" + "、".join(a["chart_tags"]))
    L.append("")
    hit, part, na = a["rule_hit"], a["rule_partial"], a["rule_na"]
    always = [(r, m) for r, m in hit if (r.get("trigger_tags") or "") == "恒真"]
    real = [(r, m) for r, m in hit if (r.get("trigger_tags") or "") != "恒真"]

    L.append(f"### 12.1 条件成立（实质判据 {len(real)} 条）")
    L.append("")
    if real:
        L.append("> 条件成立只说明「这条规则的触发条件被满足」，**不说明结论可用**——"
                 "仍须看证据等级、核验状态与冲突。")
        L.append("")
        for r, _ in real[:20]:
            L.append(f"- **{r['rule_id']}｜{r['theme']}**（{r['verification_status']}；"
                     f"{r['evidence_grade']}；{r['deterministic_use']}）")
            L.append(f"  - 原文摘句：{quote(r['rule_text'], 200)}")
            L.append(f"  - 条件：{quote(r['conditions'], 140)}")
            L.append(f"  - 定位：{r['source_locator']}")
        if len(real) > 20:
            rest = "、".join(r["rule_id"] for r, _ in real[20:])
            L.append(f"- 另有 {len(real) - 20} 条同属条件成立，未展开：{rest}")
    else:
        L.append("- 无规则的条件被完整满足。")
    L.append("")

    L.append(f"### 12.2 恒真（次序性规定 {len(always)} 条，不逐条展开）")
    L.append("")
    if always:
        L.append("> 这批规则的条件是「恒真」，对任何命例都成立——它们是**流程规定**（第几步做什么），"
                 "不是判据。列出来只为提醒次序，不能当断语。")
        L.append("")
        L.append("　" + "、".join(r["rule_id"] for r, _ in always))
    L.append("")

    L.append(f"### 12.3 部分满足（{len(part)} 条，按缺项数排序，列前 12）")
    L.append("")
    if part:
        L.append("> 缺项里凡属「" + "／".join(UNSUPPLIED) + "」者，是**本分析器未提供该维度**，"
                 "不等于条件不成立；其余缺项须人工核。")
        L.append("")
        for r, miss in part[:12]:
            L.append(f"- **{r['rule_id']}｜{r['theme']}**｜缺 {'、'.join(miss)}"
                     f"（{r['verification_status']}；{r['evidence_grade']}）")
            L.append(f"  - 条件：{quote(r['conditions'], 140)}")
            L.append(f"  - 定位：{r['source_locator']}")
        if len(part) > 12:
            L.append(f"- 另有 {len(part) - 12} 条未展开。")
    else:
        L.append("- 无部分满足的规则。")
    L.append("")

    L.append(f"### 12.4 不可判定（{len(na)} 条：conditions 未结构化）")
    L.append("")
    L.append("> 这批规则的 conditions 是自然语言叙述，抽不出触发要素，**本分析器不对其判成立与否**。"
             "下列只给关键词线索（旧口径 score），供人工定位，**不是命中**。")
    L.append("")
    if na:
        by_topic = Counter(r.get("topic") or "未分类" for r in na)
        L.append("主题分布：" + "、".join(f"{k} {v}" for k, v in by_topic.most_common()))
        L.append("")
        na_ids = {r["rule_id"] for r in na}
        lead = [(sc, r) for sc, r in a["rules"] if r["rule_id"] in na_ids][:5]
        for sc, r in lead:
            L.append(f"- 线索 **{r['rule_id']}｜{r['theme']}**（score {sc}）｜条件："
                     f"{quote(r['conditions'], 100)}")
        if lead:
            L.append("")
    L.append("")

    L.append("## 十四、冲突、低置信与资料缺口")
    L.append("")
    if a["conflicts"]:
        L.append("| 冲突 | 类型 | 双方／处置 | 状态 |")
        L.append("|---|---|---|---|")
        for c in a["conflicts"]:
            L.append(f"| {c['conflict_id']} | {c['conflict_type']} | {quote(c['topic'], 60)}；"
                     f"处置：{quote(c['disposition'], 80)} | {c['status']} |")
    else:
        L.append("- 本次未触发已登记的冲突项。")
    L.append("")
    if a["unresolved"]:
        for u in a["unresolved"]:
            L.append(f"- {u['unresolved_id']}｜{u['theme']}｜{u['status']}：{quote(u['description'], 160)}")
    L.append("")
    L.append("固定限制：")
    L.append("- LX2-11 六冲／六害／六合同书图版已补（书内10，E1，引用须标“同源章图版”）；"
             "六甲方阵 TB-XJ11 60 格与 TB-XJ13／TB-XJ14 各 60 对已建，取用条件未结构化；")
    L.append("- LX2-12 TH-01 为整理者复原表（85 格「本书未见明文」，不补字）；检索优先取行卯版原表 "
             "TAB-LXR-TH-01-ORIG（120 格、119 已核、1 格冲突禁用）；**43 例命例已全部回图（E1 已核）**，"
             "图版缺口已关闭（U-X12-03）；"
             "余穷通宝鉴逐字校对（U-X12-04）、三版 XLS（U-X12-06）、图版改字权（U-X12-10）未关闭；")
    L.append("- LX2-13 46 格补格已并入基线编号（NM-TBL-02-307..352）；18 条性别口径冲突已处置"
             "（待裁 0：10 条已裁定、8 条转待核）；余 53 格短文证据弱（U13-07）；")
    L.append("- LX2-15 视频帧覆盖 0.284%（193 帧／68,005 帧）、字幕行覆盖 0.108%（120 行／111,523 行），"
             "不得称全系列画面已核；**字幕文件本身 38 集齐全，低的是核对率，不是缺字幕**。")
    L.append("- 视频内容只核到**主题／章目级**：38 集可对《命理传承班笔记》逐页引用（p7–p174），"
             "**32 集只能引到章、不得引页**；第 9 集「论寿夭」两书均无专章。见 "
             "`references/subtitle_content_check.md`；不得据此称「逐字已校」。")
    L.append("")

    L.append("## 十五、本次未能确定")
    L.append("")
    L.append("- 格局**已落算三层**（G-01 结项）：格名（R-SS-002／R34／R73）、顺逆（R74／R-SS-017）、"
             "结构成败的忌神与救应（R-SS-009／012～015／019～023）。**未落算**：相神（R-SS-033／034）、"
             "有情有力（R-SS-028～030）、十四制式（R-SS-036～041，仅第一制与第十三制有条文）、"
             "双格轻重（R-SS-024～026，只标不辨）。")
    L.append("- 六合只证组合（TB-XJ05，E1）；「夹」之取法原文未给，拱夹只判拱、不判夹。")
    L.append("- 起运岁：未推（缺出生日与历法换算），大运只按运次列干支，不标年龄；"
             "故 R-SZ-033／034／036 之年龄界条款无法落算。")
    L.append("- **大运三套体系只落一套**：余氏调候已落算（`--dayun` 出调候喜忌）；"
             "沈氏十四制式**名目全录（R-SS-036）、条文只入第一制与第十三制（R-SS-037～041）**，"
             "其余十二制未抽；金不换**骨架 24 条（R-JB-001～024）＋十日主诗註 120 条"
             "（R-JB-025～144，p39–116，10 日主 × 12 月支）已全入**，"
             "表已抽 p119–165（`JB-TAB-01` 吉凶一览 378 格／`JB-TAB-02` 寿终表 33 格／"
             "`JB-TAB-03` 喜忌表 215 格／`JB-TAB-04` 月建生剋喜忌 120 格／"
             "`JB-TAB-05` 十二月建歌与梁氏註 24 格），"
             "**故「某日主某月支的先决条件／喜／忌／寿终运」与「某月建下某两干组的喜／忌」"
             "均可直接查表**（`tables.csv` 按 `day_master`＋`row_key` 检索；"
             "月建生剋表须先按月支、再按两干组取，且两干合论，不得当单干结论）；"
             "唯 p188–204 子平诗 17 页未抽（梁氏引《三命通会》系统诗，非本书正文），"
             "**故「子平诗断语」查不了**；五家散论四表（`JB-TAB-06`～`09`）与批导体例（R-JB-148～190）均已入库。"
             "`JB-TAB-06`～`09` 那 535 格栏位系依格线推定、未回图核对，`confidence` 记低，"
             "**只能作参照，不得作定论**。"
             "另注：`JB-TAB-01` 与 `JB-TAB-03` 喜忌大面积不合（`F-X16-02`，待核），"
             "`JB-TAB-04` 与 `JB-TAB-01` 口径不同、未互校；查表结果均不得当唯一答案。"
             "本报告的大运判断仍只按 R-SZ-018～031 之五法出；"
             "唯一例外是墓库运——本器 `MUKU_BY_MONTH` 即 R-SZ-022 之表，与 R-JB-016 同表同法，两书互证。")
    L.append("- **流年层已落算七法（G-02 结项）**：架势（R97）、双冲旬内旬外（R122）、"
             "双六合在运与在年之分（R126）、三合三会流年必有变（R164）、冲大运与冲八字之别（R209）、"
             "临官年（R220）、运中流年四组（R-MF-017）。**未落算**：R-MF-006（身强弱在流年层退位，属体例）、"
             "R-XP-027～036 其余条款；流月层已落 R118、R-XP-038、R-XP-039、R-XP-040、"
             "R-XP-041 五法（同途／反吟／支冲／双合／时柱／三柱刑／不论），"
             "未落 R-XP-037（五年一循环，只作提示）与 R-XP-043（暗拱暗夹，须人工认）。")
    L.append("- 流年之吉凶轻重与应期先后，本器不排——R135 明言「流年不是每年都有事可断」，"
             "程序只做结构命中，不作逐年断语。全流冲刑（R-SZ-043）未逐月展开。")
    L.append("- **宰公日时诀已落算**（第十一节末）：按（日柱,时柱）直查 `R-ZG-*` 131 条与六十表 720 格，"
             "表空白照写「原书空白」。")
    L.append("- **神煞探源 49 条（`R-SP-*`）已落算**（第十一节末）：起例照原文，逐条判定命中／不成立／"
             "缺料／待人工／原文待核。其中 4 条原文只给诗诀或对照表为图版（咸池、破字、"
             "明代统计七则、夭年煞），标「待人工对表」；2 条原文有讹字（s21「亥人戌时」、"
             "s22「五十一甲位」）标「原文待核」——均不按己意改写补足。")
    L.append("- 女命专章：性别未提供或未命中白名单规则时，不代判。")
    L.append("- 任何“待核／候选／冲突／排除”格值，均不进入本报告的确定性结论。")
    return "\n".join(L)


def render_json(a):
    out = dict(a)
    out["rules"] = [{"score": s, **r} for s, r in a["rules"]]
    for k in ("expanded",):
        pass
    return json.dumps(out, ensure_ascii=False, indent=2, default=str)


def main():
    ap = argparse.ArgumentParser(description="梁湘润批八字·证据门控分析器")
    ap.add_argument("pillars", nargs="*", help="四个干支，按年 月 日 时")
    ap.add_argument("--year"); ap.add_argument("--month"); ap.add_argument("--day"); ap.add_argument("--hour")
    ap.add_argument("--gender", choices=["男", "女"])
    ap.add_argument("--dayun", help="大运干支，逗号分隔，按运次顺序，如 丙子,丁丑（只给干支，不推起运岁）")
    ap.add_argument("--liunian", help="流年：公历年逗号分隔（2026,2027）或干支（丙午,丁未）")
    ap.add_argument("--birth-year", type=int, help="出生公历年，用于算虚岁与所在大运")
    ap.add_argument("--start-age", type=int,
                    help="起运虚岁，取 paipan.py 输出的「交运虚岁」（如 1993-02 交运、1984 生 → 10）；"
                         "不是「起运折 8 年 2 月」那个年数")
    ap.add_argument("--liuyue", action="store_true", help="附出流月与运／时柱之同途·反吟·支冲·双合·三柱刑（R118 等五法）")
    ap.add_argument("--recent", type=int, nargs="?", const=5, metavar="N",
                    help="自动取「最近 N 年」（含今年，默认 5）；配 --dayun --birth-year --start-age 即知其所行何运、运内第几年")
    ap.add_argument("--base-year", type=int, help="以某年作为「今年」（回批旧盘或复核用；默认系统当前年）")
    ap.add_argument("--from-paipan", metavar="JSON",
                    help="直接读 paipan.py --json 的输出：四柱／性别／大运／交运虚岁一并取来")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.from_paipan:
        src = load_paipan(args.from_paipan)
        args.pillars = args.pillars or src["pillars"]
        args.gender = args.gender or src["gender"]
        args.dayun = args.dayun or ",".join(src["dayun"])
        args.birth_year = args.birth_year or src["birth_year"]
        args.start_age = args.start_age or src["start_age"]
    if args.year:
        ps = [args.year, args.month, args.day, args.hour]
    else:
        ps = args.pillars
    if len(ps) != 4 or any(not p for p in ps):
        ap.error("须提供四个干支：位置参数 或 --year --month --day --hour")
    dy = None
    if args.dayun:
        dy = [x.strip() for x in args.dayun.replace("，", ",").split(",") if x.strip()]
        bad = [x for x in dy if x not in JIAZI_SET]
        if bad:
            ap.error("大运干支不合法：" + "、".join(bad))
    ln = None
    if args.liunian:
        ln = []
        for x in args.liunian.replace("，", ",").split(","):
            x = x.strip()
            if not x:
                continue
            if x.isdigit():
                ln.append(int(x))
            elif x in JIAZI_SET:
                ln.append(x)
            else:
                ap.error("流年须为公历年或干支：" + x)
    try:
        a = analyze(ps, args.gender, dy, ln, args.birth_year, args.start_age, args.liuyue,
                    recent=args.recent, base_year=args.base_year)
    except ValueError as e:
        ap.error(str(e))
    print(render_json(a) if args.json else render_md(a))


if __name__ == "__main__":
    main()
