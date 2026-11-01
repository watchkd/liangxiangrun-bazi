#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一致率审计（trace_audit）：把「断得像不像梁师」变成可复核的数。

为什么要有这一件

  P11 之后本包能断命了，但「像不像」一直是形容词。批者自陈「与梁氏相合」，
  别人无法复核，也无法知道哪一盘合、哪一盘不合。没有这个数，
  「包准」就只能靠嘴说；有了这个数，才知道该往哪儿补。

本器只量四件事，一件事都不多量

  一、**接线率**：每个判断点有没有压到条文上（静态，看 data/point_rules.csv）。
  二、**落地率**：该点在本盘实际落了字没有（有断／不作断两分，不充数）。
  三、**梁氏召回**：梁氏在这一盘引过的条文，我们覆盖了几条（只对有挂条的例算）。
  四、**主题呼应**：梁氏断了的主题，我们是不是也断了（关键词粗判，是代理指标）。

刻意不做的事

  · 不判「断得对不对」——那不是一致率，是命中率，要有事实标注才谈得上（L2 未建）。
  · 不给总分。四个数分开看；合成一个数就一定会被拿来说「本包九十分」。

用法
    python tools/trace_audit.py                 # 全量 59 例
    python tools/trace_audit.py --limit 10
    python tools/trace_audit.py --out _命书/一致率报告.md
    python tools/trace_audit.py --json
"""
import argparse
import csv
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A          # noqa: E402
import panduan as PD         # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 主题词表（粗判用，宁可漏判不可乱判：一律用两字以上词）
LEX = {
    "婚姻": ("婚姻", "结婚", "离婚", "夫星", "妻星", "早婚", "再婚", "配偶", "夫妻",
             "老公", "太太", "嫁人", "娶", "感情"),
    "子息": ("子女", "子息", "生子", "生儿", "孩子", "无子", "怀孕", "儿子", "女儿", "子嗣"),
    "财富": ("发财", "钱财", "财富", "破财", "负债", "求财", "财源", "得财", "有钱", "贫穷"),
    "事业": ("事业", "工作", "职业", "升迁", "功名", "读书", "考试", "失业", "生意", "公职"),
    "六亲": ("父母", "父亲", "母亲", "兄弟", "姐妹", "六亲", "家人", "祖产", "祖业"),
    "寿元": ("寿元", "夭寿", "疾病", "健康", "血光", "开刀", "住院", "短命", "大限"),
    "性情": ("性情", "性格", "脾气", "个性", "为人"),
}
STRUCT_KW = ("格局", "用神", "调候", "身强", "身弱", "五行", "刑冲", "神煞")

# panduan 判断点 → 客户主题（只有落到具体人事的才算）
POINT_TOPIC = {"marriage": {"婚姻"}, "child": {"子息"}, "wealth": {"财富", "事业"},
               "parent": {"六亲"}, "xingqing": {"性情"}, "health": {"寿元"}}

# 未召回条文分类：不分类的召回率没有意义——把评注、起例、体例算作「漏」，
# 只会逼着后来者往推演稿里塞不该塞的话。
MISS_CLASS = (
    ("非判据·体例", ("体例", "次序", "总目", "定义", "名目", "读法", "取向", "方法论",
                    "考据", "序言", "学命", "自省", "缘起", "互看", "简批", "小批",
                    "中批", "大批", "细批", "出处")),
    ("非判据·评注", ("批评", "纠误", "辨", "按", "问命")),
    ("起例", ("起法", "起例", "取法", "口诀")),
    ("时效", ("时效", "年限", "迟速", "先到")),
)

# 查表层：按日主＋月支／时柱定位的规则族（点名列而实为查表）
LOOKUP_PAT = re.compile(r"^(宰公要诀·(.+?日)/(.+?时)|金不换·(.+?)日主/(.+?)月)")


def topics_of(text):
    t = text or ""
    out = set()
    for k, kws in LEX.items():
        if any(w in t for w in kws):
            out.add(k)
    if any(w in t for w in STRUCT_KW):
        out.add("结构")
    return out


def load_cases():
    fp = os.path.join(ROOT, "data", "cases.csv")
    rows = list(csv.DictReader(io.open(fp, encoding="utf-8-sig")))
    ok = []
    for r in rows:
        if r.get("case_completeness") != "完整四柱":
            continue
        ps = [r["year_pillar"], r["month_pillar"], r["day_pillar"], r["hour_pillar"]]
        if any(p not in A.JIAZI_SET for p in ps):
            continue
        ok.append(r)
    return ok


def load_rules():
    fp = os.path.join(ROOT, "data", "rules.csv")
    return {r["rule_id"]: r for r in csv.DictReader(io.open(fp, encoding="utf-8-sig"))}


def lookup_hits(a, rules):
    """查表层：这一盘按日主／月支／时柱可直接命中的条文（宰公要诀、金不换月令）。

    「可直接命中」的意思是可机械定位，不是说我们要照抄——但定位得到而一条没用，
    就是明摆着的缺口。故单列一栏，不混进接线率。
    """
    day, month = a["pillars"][2][0], a["pillars"][1][1]
    hour = a["pillars"][3]
    hit = []
    for rid, r in rules.items():
        m = LOOKUP_PAT.match(r.get("theme") or "")
        if not m:
            continue
        if m.group(2):                      # 宰公要诀·X日/Y时
            if m.group(2)[0] == day and m.group(3) == hour:
                hit.append(rid)
        else:                               # 金不换·X日主/Y月
            if m.group(4) == day and m.group(5) == month:
                hit.append(rid)
    return hit


def miss_class(theme, cond=""):
    """未召回之条的类别。恒真之条先剔出去。

    rules.csv 里 `conditions` 标「[可算] 恒真」者，是**方法、程序、分寸、分类、推荐**
    ——它规定「怎么批」，不规定「这一盘断什么」。拿它当判据缺口，就会逼着后来者
    往推演稿里塞「批命须分两套层次」这类话，那是体例，不是断语。
    故这一类单列，且不以主题词猜，直接看 conditions 字段。
    """
    if "恒真" in (cond or ""):
        return "非判据·批法"
    th = theme or ""
    for name, kws in MISS_CLASS:
        if any(k in th for k in kws):
            return name
    return "判据缺口"


def audit_case(r, rules):
    ps = [r["year_pillar"], r["month_pillar"], r["day_pillar"], r["hour_pillar"]]
    g = "女" if "女" in (r.get("gender") or "") else "男"
    a = A.analyze(ps, gender=g)
    a["where"] = PD._where_of(a)
    tr = PD.build_trace(a)
    pts = tr["points"]

    cited = []
    for p in pts:
        for i in p["ids"]:
            if i not in cited:
                cited.append(i)

    for p in pts:
        if not p["fired"]:
            p["sent"] = False        # 不适用者不得算「已落字」，否则比例会过百

    linked = [x.strip() for x in re.split(r"[,，]", r.get("linked_rule_ids") or "")
              if x.strip()]
    liang_t = topics_of((r.get("question") or "") + " " + (r.get("liang_judgment") or "")
                        + " " + (r.get("liang_reasoning") or ""))
    got_t = set()
    for p in pts:
        if p["sent"]:
            got_t |= POINT_TOPIC.get(p["pid"], set())
            # 十神定位（乙轨）不预挂主题：它出什么算什么，按原文判，不按点名判
            if p["pid"] == "shishen":
                got_t |= topics_of(p.get("raw") or p.get("say") or "") - {"结构"}

    lk = lookup_hits(a, rules)
    lk_linked = [x for x in linked if LOOKUP_PAT.match((rules.get(x) or {}).get("theme") or "")]
    return {
        "case_id": r["case_id"],
        "pillars": "".join(ps),
        "n_point": len(pts),
        "n_basis": sum(1 for p in pts if p["ids"]),
        "n_fired": sum(1 for p in pts if p["fired"]),
        "n_sent": sum(1 for p in pts if p["sent"]),
        "points": [{"pid": p["pid"], "fired": p["fired"], "sent": p["sent"]} for p in pts],
        "cited": cited,
        "linked": linked,
        "hit_linked": [x for x in linked if x in cited],
        "linked_lookup": lk_linked,
        "linked_plain": [x for x in linked if x not in lk_linked],
        "hit_plain": [x for x in linked if x not in lk_linked and x in cited],
        "lookup": len(lk),
        "liang_topics": sorted(liang_t - {"结构"}),
        "got_topics": sorted(got_t),
        "topic_hit": sorted((liang_t - {"结构"}) & got_t),
        "topic_miss": sorted((liang_t - {"结构"}) - got_t),
        "struct_liang": "结构" in liang_t,
    }


def collect_miss(rows, rules):
    """未召回之条，分三类：真缺口、本例旁引、需运年。

    为什么要三分：案例的 `linked_rule_ids` 记的是「梁氏在这一例中提到过的条」，
    其中混着旁引——梁氏拿某条作反例、作排除、作旁证，该盘条件并不成立。
    一律算「我们漏了」，只会逼着后来者把不该引的条硬塞进推演稿。
    故以「该条是否在别的盘上真出得来」为判：出得来而此盘不出，是旁引；
    从无一面出得来，才算实现缺口。
    """
    fired_all = set()
    for r in rows:
        fired_all |= set(r["cited"])
    out = {}
    for r in rows:
        for x in r["linked"]:
            if x in r["cited"]:
                continue
            rule = rules.get(x) or {}
            d = out.setdefault(x, {"id": x, "n": 0,
                                   "theme": rule.get("theme") or "",
                                   "cond": rule.get("conditions") or "",
                                   "topic": rule.get("topic") or "",
                                   "txt": rule.get("normalized_statement") or ""})
            d["n"] += 1
    for x in out.values():
        x["cls"] = miss_class(x["theme"], x["cond"])
        x["ever"] = x["id"] in fired_all
        need_yun = (x["topic"] in ("岁运流年", "大运")
                    or "大运" in (x["cond"] or "") or "流月" in (x["cond"] or ""))
        if x["cls"] == "判据缺口" and x["ever"]:
            x["cls"] = "本例旁引"
        elif x["cls"] == "判据缺口" and need_yun:
            # 案例表只给四柱，不给大运与流年；运年层不跑，这一类无从判
            x["cls"] = "需运年方能判"
    return sorted(out.values(), key=lambda d: (-d["n"], d["id"]))


def summarize(rows):
    n = len(rows)
    tot_pt = sum(r["n_point"] for r in rows)
    s = {
        "cases": n,
        "point_total": tot_pt,
        "basis_rate": sum(r["n_basis"] for r in rows) / max(1, tot_pt),
        "sent_rate": sum(r["n_sent"] for r in rows) / max(1, sum(r["n_fired"] for r in rows)),
        "avg_cited": sum(len(r["cited"]) for r in rows) / max(1, n),
        "avg_lookup": sum(r["lookup"] for r in rows) / max(1, n),
    }
    with_l = [r for r in rows if r["linked"]]
    s["linked_cases"] = len(with_l)
    s["linked_rules"] = sum(len(r["linked"]) for r in with_l)
    s["linked_hit"] = sum(len(r["hit_linked"]) for r in with_l)
    s["recall"] = (s["linked_hit"] / s["linked_rules"]) if s["linked_rules"] else None
    pl = [r for r in with_l if r["linked_plain"]]
    s["plain_cases"] = len(pl)
    s["plain_rules"] = sum(len(r["linked_plain"]) for r in pl)
    s["plain_hit"] = sum(len(r["hit_plain"]) for r in pl)
    s["recall_plain"] = (s["plain_hit"] / s["plain_rules"]) if s["plain_rules"] else None
    s["linked_in_lookup"] = sum(len(r["linked_lookup"]) for r in with_l)
    tc = [r for r in rows if r["liang_topics"]]
    s["topic_cases"] = len(tc)
    s["topic_total"] = sum(len(r["liang_topics"]) for r in tc)
    s["topic_hit"] = sum(len(r["topic_hit"]) for r in tc)
    s["topic_recall"] = (s["topic_hit"] / s["topic_total"]) if s["topic_total"] else None
    per = {}
    for r in tc:
        for t in r["liang_topics"]:
            d = per.setdefault(t, [0, 0])
            d[0] += 1
            if t in r["got_topics"]:
                d[1] += 1
    s["per_topic"] = {k: (v[1], v[0]) for k, v in per.items()}
    # 各节出料率：分主题为 0% 时，要能一眼看出是「不肯断」还是「没料可断」
    fb = {}
    for r in rows:
        for p in r.get("points", []):
            d = fb.setdefault(p["pid"], [0, 0])
            d[0] += 1
            if p["fired"]:
                d[1] += 1
    s["fired_by_pid"] = {k: (v[1], v[0]) for k, v in fb.items()}
    return s


def render_md(rows, s, miss=()):
    L = []
    P = L.append
    P("# 一致率报告（A 轨：断得像不像梁师）")
    P("")
    P("> 本报告只量一致率，不量命中率。命中要等事实标注集（L2）建成，"
      "现在任何「准不准」的说法都无据。")
    P("")
    P("## 一、四组数")
    P("")
    P("| 指标 | 值 | 含义 |")
    P("|---|---|---|")
    P("| 接线率 | %.1f%% | 判断点压到条文上的比例（静态，看 `point_rules.csv`） |"
      % (100 * s["basis_rate"]))
    P("| 落地率 | %.1f%% | 该点在本盘实际落了字、未以「不作断」收场的比例 |"
      % (100 * s["sent_rate"]))
    P("| 梁氏召回（全量） | %s | 梁氏所引条文中被本器覆盖的比例（仅 %d 例有挂条；"
      "其中 %d 条属查表族） |"
      % (("%.1f%%" % (100 * s["recall"])) if s["recall"] is not None else "样本不足",
         s["linked_cases"], s["linked_in_lookup"]))
    P("| 梁氏召回（原理层） | %s | 去掉宰公要诀／金不换查表族后的召回（%d 例、%d 条） |"
      % (("%.1f%%" % (100 * s["recall_plain"])) if s["recall_plain"] is not None else "样本不足",
         s["plain_cases"], s["plain_rules"]))
    P("| 主题呼应 | %s | 梁氏断过的主题中本器也出了断的比例（关键词粗判） |"
      % (("%.1f%%" % (100 * s["topic_recall"])) if s["topic_recall"] is not None else "—"))
    P("")
    P("样本：%d 盘（四柱完整的命例）；平均每盘点 %d 个判断点、引 %.1f 条编号；"
      "按日主／月支／时柱可机械命中的查表条文平均 %.1f 条。"
      % (s["cases"], s["point_total"] // max(1, s["cases"]), s["avg_cited"], s["avg_lookup"]))
    P("")
    P("## 二、分主题")
    P("")
    P("| 主题 | 梁氏断过 | 本器同断 | 呼应 |")
    P("|---|---|---|---|")
    for k in sorted(s["per_topic"], key=lambda x: -s["per_topic"][x][1]):
        h, t = s["per_topic"][k]
        P("| %s | %d | %d | %.0f%% |" % (k, t, h, 100 * h / max(1, t)))
    P("")
    zero = [k for k, (h, _t) in s["per_topic"].items() if h == 0]
    if zero:
        P("> %s为 0%%。先看下节「各节出料率」：出料为 0 者是**这一节没料可出**"
          "（条文库薄、或该节未接进检索），不是推演器不肯断；出料不低而呼应仍低者，"
          "是关键词判读的误差，须核第三节逐盘。" % "／".join(sorted(zero)))
    P("")
    P("### 各节出料率（本盘有料／全部盘）")
    P("")
    P("| 节 | 出料 | 率 |")
    P("|---|---|---|")
    for pid, nm in (("marriage", "4.2 婚姻"), ("wealth", "4.3 财与事业"),
                    ("child", "4.4 子息"), ("parent", "4.5 父母兄弟"),
                    ("xingqing", "4.6 性情"), ("health", "4.7 寿元疾病"),
                    ("shishen", "3.2 十神定位（乙轨）")):
        h, n = s["fired_by_pid"].get(pid, (0, 0))
        P("| %s | %d/%d | %.0f%% |" % (nm, h, n, 100 * h / max(1, n)))
    P("")
    P("## 三、逐盘")
    P("")
    P("| 例 | 四柱 | 点 | 有据 | 落字 | 引条 | 梁引 | 覆盖 | 主题（梁→本） |")
    P("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        P("| %s | %s | %d | %d | %d | %d | %d | %d | %s |"
          % (r["case_id"], r["pillars"], r["n_point"], r["n_basis"], r["n_sent"],
             len(r["cited"]), len(r["linked"]), len(r["hit_linked"]),
             ("、".join(r["liang_topics"]) or "—")
             + ("→" + ("、".join(r["topic_hit"]) or "无") if r["liang_topics"] else "")))
    P("")
    if miss:
        from collections import Counter
        c = Counter(m["cls"] for m in miss)
        P("## 四、梁氏引了而我们没接的条文（%d 条）" % len(miss))
        P("")
        P("| 类别 | 条数 | 意思 |")
        P("|---|---|---|")
        note = {"判据缺口": "该引而没引——这是要补的",
                "本例旁引": "该条在别的盘已能出，本盘条件不成立；梁氏多作反例或旁证",
                "需运年方能判": "案例只给四柱、不给大运流年；运年层不跑，此类无从判",
                "非判据·体例": "次序、体例、读法，本就不该进推演稿",
                "非判据·评注": "梁氏对某说的批评与纠误，属评注不属判据",
                "非判据·批法": "恒真之条：规定批法而非断语。004／006／008 已落在节次与声明里，"
                              "024／026 落在「不作断／不写数字」的纪律里",
                "起例": "起法口诀，analyze 已算，推演稿不重复引",
                "时效": "交运与五行迟速，本器未实现"}
        for k, v in c.most_common():
            P("| %s | %d | %s |" % (k, v, note.get(k, "")))
        P("")
        P("**判据缺口逐条**：")
        P("")
        gap = [m for m in miss if m["cls"] == "判据缺口"]
        if not gap:
            P("（无。判据类十一条已全部接进引擎；其余未召回者见上表分类——"
              "旁引、需运年、批法三类都不是「该引而没引」。）")
        for m in gap:
            P("- `%s` ×%d　%s——%s" % (m["id"], m["n"], m["theme"] or "（无题）",
                                       (m["txt"] or "")[:46]))
        P("")
        P("**其余未召回之条（逐条，供核）**：")
        P("")
        P("| 条 | 次数 | 类别 | 原文条件 |")
        P("|---|---|---|---|")
        for m in miss:
            if m["cls"] == "判据缺口":
                continue
            cond = (m["cond"] or "—").replace("[可算] ", "")
            P("| `%s` | %d | %s | %s |" % (m["id"], m["n"], m["cls"], cond[:44]))
        P("")
    P("## 五、这张表没量到的")
    P("")
    P("- **方向对不对**。本表只比「有没有断到同一主题」，不比吉凶方向。"
      "同断「婚姻」，一个断必败一个断和美，在表里都算命中。")
    P("- **4.3 财与事业，此前 59 盘全空，本轮改由乙轨出料。** 根因不是推演逻辑："
      "`topic=财官` 全库仅 8 条且全为男命妻妾论，而本节 deny 掉妻妾婚夫，故必空。"
      "放宽主题能捞出四条通用话（自坐偏财、伤官生财、喜神指财官印），那是「有料」的假象，故不改。"
      "真正的补救不是放宽主题，是补乙轨：财星之明暗、通根、盖财三处本就算得出来"
      "（R38／R7／R234），已并入 4.3。")
    P("- **查表层没接线，但本表量不出它的代价**。宰公要诀、金不换月令两族可按日主／月支／时柱"
      "机械定位，本器一条也没接进推演稿；然而命例里梁氏从未引过这两族（查表族计 0 条），"
      "故本表对这块是盲的——不能拿它证明「接不接无所谓」。")
    P("- **关键词粗判会错**。梁氏原文的「财」「官」多处是术语而非人事，"
      "主题判读因此有噪声；要看单盘请核第三节。")
    P("- **乙轨只接了四类**。十神定位按柱位取象、坐、数量、通根四类可算者接入（3.2 节）；"
      "「谁合谁」「谁克谁」（R146／R156／R161）尚未接——那要把十神之间的合克逐对算出来，"
      "不是加几条边就能了，留作下一步。")
    P("- **子息一项的 0% 是误判**。唯一一例梁氏原话为「在清朝你是娘娘子女」——"
      "那是话术里的比喻，不是断子息；本表按关键词算作「梁氏断过」，故此 0% 不作真缺口看。")
    P("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="一致率审计")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", metavar="FILE")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rules = load_rules()
    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]
    rows = [audit_case(r, rules) for r in cases]
    s = summarize(rows)

    if args.json:
        print(json.dumps({"summary": s, "cases": rows}, ensure_ascii=False, indent=1))
        return 0

    md = render_md(rows, s, collect_miss(rows, rules))
    if args.out:
        io.open(args.out, "w", encoding="utf-8").write(md + "\n")
        print("已写 %s" % args.out)
    else:
        print(md)
    print("接线 %.1f%%｜落地 %.1f%%｜召回 %s｜主题 %s"
          % (100 * s["basis_rate"], 100 * s["sent_rate"],
             ("%.1f%%" % (100 * s["recall"])) if s["recall"] is not None else "样本不足",
             ("%.1f%%" % (100 * s["topic_recall"])) if s["topic_recall"] is not None else "—"))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
