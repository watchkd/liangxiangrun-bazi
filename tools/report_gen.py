# -*- coding: utf-8 -*-
"""十九板块分析报告骨架生成器（P4）

用途：把「报告怎么写」从口头规格变成可运行的骨架。生成器只做两件事：
  1. 把 E6 结构数据（四柱／十神／藏干／旬空／大运／刑冲合会／神煞／格局／调候／用神）填进对应板块；
  2. 把判断类板块（六亲、建议、学业…总纲）留成显式「〔待批〕」位，并预先挂好本案检索到的条文池。

**它不写断语。** 断语是判断，工具不替人做——这与 `mingshu.py --format html` 拒收无 `--prose`
的理由是同一条。骨架未经人工填写，`report_check.py` 会判 FAIL（B06 待批未清），
这是设计意图：骨架不等于交付件。

用法：
    python tools/report_gen.py 癸巳 戊午 丙午 壬辰 --gender 男 \\
        --dayun 己未,庚申,辛酉,壬戌 --birth-year 1953 --start-age 8 \\
        --liunian 2026,2027,2028 --format md --out 报告.md
        --recent 5 --format md --out 报告.md    # 当前大运近五年

    python tools/report_gen.py --index 报告.md            # 只出「附：证据索引」
    python tools/report_gen.py --index 报告.md --write    # 就地重写索引节

    --lon 116.4  给经度即视为已校正真太阳时；不给则报告中明写「未校正」
"""
import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = A.ROOT
TEMPLATES = os.path.join(ROOT, "references", "templates")

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲"
TITLES = ["基本信息", "四柱排盘", "五行十神", "刑冲合会与神煞", "格局分析", "日主调候",
          "用神全景", "六亲专题", "大运走势", "流年", "人生建议", "学业",
          "事业", "财富", "人际", "健康", "年度行动指南", "风险与禁忌", "总纲"]

# 前须非字母／连字符，否则 TAB-LXR-TH-01-ORIG 里会误抓出「R-TH-01」这条并不存在的规则
RULE_RE = re.compile(r"(?<![A-Z-])R(?:-[A-Z0-9]+)+-\d+|\bR\d{1,3}\b")
CELL_RE = re.compile(r"(?:TB|JS|JB|XJ|TH|T)-[A-Z0-9]+(?:-[A-Z0-9]+)*")

RULE_BY_ID = {r["rule_id"]: r for r in A.RULES}
CELL_BY_ID = {c["cell_id"]: c for c in A.TABLES}


# ────────────────────────── 小工具 ──────────────────────────
def grade_short(g):
    m = re.match(r"(E[1-6])", g or "")
    return m.group(1) if m else "E6"


def xun_kong(gz):
    """旬空：本柱所在旬之两个空亡支。甲子旬空戌亥，甲戌旬空申酉…"""
    i = A.JIAZI.index(gz)
    b = (10 - (i // 10) * 2) % 12
    return A.BRANCHES[b] + A.BRANCHES[(b + 1) % 12]


def pool(a, words, limit=8):
    """从本案命中的规则里按关键词捞条文池。不新造条文，只做过滤。"""
    out = []
    for item in a["rule_hit"]:
        # rule_hit 的元素是 (规则 dict, 命中理由 list) 二元组
        r = item[0] if isinstance(item, tuple) else item
        hay = r["theme"] + r["normalized_statement"]
        if any(w in hay for w in words):
            out.append((r["rule_id"], r["theme"], grade_short(r.get("evidence_grade"))))
            if len(out) >= limit:
                break
    return out


def risk_rule(keyword, limit=3):
    """风险四检查：按关键词回查 rules.csv，取真实条号，不臆造。"""
    out = []
    for r in A.RULES:
        if keyword in r["theme"] or keyword in r["rule_text"]:
            out.append((r["rule_id"], r["theme"], grade_short(r["evidence_grade"]),
                        r["verification_status"]))
            if len(out) >= limit:
                break
    return out


# ────────────────────────── 区块 DSL ──────────────────────────
def p(t):
    return ("p", t)


def note(t):
    return ("note", t)


def h3(t):
    return ("h3", t)


def table(headers, rows):
    return ("table", (headers, rows))


def table_c(headers, rows, cls):
    """带 class 的表格：窄列（状态、运次）不许断字，靠 class 定列宽。"""
    return ("table", (headers, rows, cls))


def ul(items):
    return ("ul", items)


def quote(t):
    return ("quote", t)


def todo(title, items, pool_rows=None):
    return ("todo", (title, items, pool_rows or []))


def _inline_md(t):
    return t


GRADES = [("〔确断〕", "g1", "确断"), ("〔倾向〕", "g2", "倾向"), ("〔存疑〕", "g3", "存疑")]

GRADE_TIP = {
    "g1": "三路以上独立来源同向，且所据条目无一落在未决／冲突开放项内",
    "g2": "两路同向，或三路中有一路方向相反已权衡、或有一路所据条目未定",
    "g3": "仅一路来源，或所据条目 verification_status 非「已核」，只可写「或可」「待验」",
}


def _grades_html(t):
    """判断强度三档 → 角标。两处渲染（块渲染与 md 转版）都要走，故抽出。"""
    for mark, cls, label in GRADES:
        t = t.replace(mark, '<span class="tag %s" title="%s">%s</span>'
                      % (cls, GRADE_TIP[cls], label))
    return t


def _inline_html(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"`([^`]+)`", r'<span class="ev">\1</span>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    return _grades_html(t)


def render_md(blocks):
    out = []
    for kind, val in blocks:
        if kind == "p":
            out.append(val)
        elif kind == "note":
            out.append(val)
        elif kind == "h3":
            out.append("### " + val)
        elif kind == "quote":
            out.append("> " + val)
        elif kind == "ul":
            out.extend("- " + x for x in val)
        elif kind == "table":
            heads, rows = val[0], val[1]
            out.append("| " + " | ".join(heads) + " |")
            out.append("|" + "---|" * len(heads))
            for r in rows:
                out.append("| " + " | ".join(str(x) for x in r) + " |")
        elif kind == "todo":
            title, items, pool_rows = val
            out.append("> **〔待批〕%s**" % title)
            out.append(">")
            for it in items:
                out.append("> - " + it)
            if pool_rows:
                out.append(">")
                out.append("> 本案可引条文池（已按主题过滤，用不用、怎么用由批者定）：")
                for rid, theme, g in pool_rows:
                    out.append("> - `%s`（%s）%s" % (rid, g, theme))
        out.append("")
    return "\n".join(out)


def render_html(blocks):
    out = []
    for kind, val in blocks:
        if kind == "p":
            out.append("<p>%s</p>" % _inline_html(val))
        elif kind == "note":
            out.append('<p class="note">%s</p>' % _inline_html(val))
        elif kind == "h3":
            out.append("<h3>%s</h3>" % _inline_html(val))
        elif kind == "quote":
            out.append("<blockquote>%s</blockquote>" % _inline_html(val))
        elif kind == "ul":
            out.append("<ul>" + "".join("<li>%s</li>" % _inline_html(x) for x in val) + "</ul>")
        elif kind == "table":
            heads, rows = val[0], val[1]
            cls = ' class="%s"' % val[2] if len(val) > 2 and val[2] else ""
            s = ["<table%s>" % cls,
                 "<tr>" + "".join("<th>%s</th>" % _inline_html(h) for h in heads)
                 + "</tr>"]
            for r in rows:
                s.append("<tr>" + "".join('<td class="l">%s</td>' % _inline_html(str(x))
                                          for x in r) + "</tr>")
            s.append("</table>")
            out.append("\n".join(s))
        elif kind == "todo":
            title, items, pool_rows = val
            s = ['<div class="todo">', "<b>〔待批〕%s</b>" % _inline_html(title), "<ul>"]
            s.extend("<li>%s</li>" % _inline_html(x) for x in items)
            if pool_rows:
                s.append("<li>本案可引条文池（已按主题过滤，用不用、怎么用由批者定）："
                         + "、".join('<span class="ev">%s</span>（%s）' % (rid, g)
                                    for rid, _, g in pool_rows) + "</li>")
            s += ["</ul>", "</div>"]
            out.append("\n".join(s))
    return "\n".join(out)


# ──────────────────── 卷首：流程卡与盘面速览（非板块，不计入十九） ────────────────────
def _material_rows(a, opt):
    """材料清点：给了什么、没给什么、没给会怎样。

    读者须先知道「批者手上有什么」，再看断语，才不会把「没算」误读成「没事」。
    """
    lon = opt.lon is not None
    dy = bool(opt.dayun)
    ln = bool(opt.liunian)
    sa = opt.start_age is not None
    by = opt.birth_year is not None
    rows = [
        ("性别", "已给（%s）" % a["gender"], "六亲取用与 scope 过滤据此；未给则女命专章不出"),
        ("四柱", "已给／已由 paipan 排出", "E6 结构计算，年月日时俱全"),
        ("出生经度", "已给（%.1f°E）" % opt.lon if lon else "**未给**",
         "真太阳时已校正" if lon else "真太阳时**未校正**；经度差四度即差一分钟以上，"
                                   "时辰临界之造会因此换柱，本报告不默认已校正"),
        ("起运岁", "已给（虚岁 %d）" % opt.start_age if sa else "**未给**",
         "大运表可标起运虚岁" if sa else "大运只列干支次序，不填岁数——起运须以 `paipan.py` 按生日与节气定"),
        ("生年", "已给（%d）" % opt.birth_year if by else "**未给**",
         "流年可换算虚岁" if by else "流年只出干支关系，不出虚岁"),
        ("大运干支", "已给 %d 步" % len(opt.dayun) if dy else "**未给**",
         "第九节五法逐运可判" if dy else "第九节五法（十干败亡／墓库／空亡／接角／冲提）**无从判**，本节只出结构"),
        ("流年", "已给 %d 年" % len(opt.liunian) if ln else "**未给**",
         "第十节可出应期" if ln else "第十节只出结构，不出应期"),
    ]
    return rows


def front_flow(a, opt):
    """批断流程卡：材料清点 + 六步执行状态 + 本件边界。"""
    gj = a.get("geju") or {}
    wy = a.get("wuyong") or []
    dy = bool(opt.dayun)
    ln = bool(opt.liunian)
    lon = opt.lon is not None
    n_sp = len(a.get("shensha_sp") or [])
    blocks = [
        note("本卡不计入十九板块。读者先看此卡，再看断语：**批者手上有什么、做到哪一步、"
             "哪一步因缺料未做**，都在这里写明。缺料之处，报告标「查不出」而不硬填——"
             "把「没算」读成「没事」，是批命最常见的一种误读。"),
        h3("一、材料清点"),
        table_c(["项", "状态", "对本次批断的影响"], _material_rows(a, opt), "flow"),
        h3("二、六步执行状态"),
        table_c(["步", "内容", "状态", "依据", "未完之由／分寸"],
              [
                  ("1", "定盘：四柱、旬空、真太阳时",
                   "部分" if not lon else "做到", "`tools/paipan.py`（E6）",
                   "真太阳时未校正，时辰临界者可能换柱" if not lon
                   else "已按经度校正，临界者仍须以专业排盘复核"),
                  ("2", "神煞四表实查＋神煞探源起例",
                   "做到", "`JS-SS-01`～`JS-SS-04` 四表；`R-SP-*` 起例 %d 条" % n_sp,
                   "只报见／不见与落点，**不判吉凶**（两说并存，不代裁）"),
                  ("3", "格局裁定：取格→格名→顺逆成败",
                   "做到" if gj.get("name") else "未做", "`R-SS-002`／`R34`／`R73`／`R74`",
                   "格名「%s」；三层皆落算" % gj.get("name") if gj.get("name")
                   else "月令无可取之格，不硬凑"),
                  ("4", "调候：原表取候选，逐字判透藏无",
                   "做到" if a.get("th") else "未做", "`TAB-LXR-TH-01-ORIG`（120 格）",
                   "原表列 1–5 个候选**不分主次**；分了就是替梁氏作主"),
                  ("5", "用神六路：调候／扶抑／通关／十干喜忌／格局需求／忌神复核",
                   "做到" if len(wy) >= 4 else "部分", "六路各挂 rule_id",
                   "**不计票、不排名、不打分**；某路不适用者明写「不适用」"),
                  ("6", "流年应期：运定十年→年定年份→月定月份",
                   "未做" if not ln else "部分", "流年类 rule_id",
                   "未给流年，本节不出应期" if not ln
                   else "流月**无材料**，只到年不到月"),
              ], "flow2"),
        h3("三、本件边界"),
        ul([
            "**不代裁两说。** 同一事而书有两说者（如神煞吉凶、旬空基准），本件并列而不择一。",
            "**不补通行术数。** 梁氏书无者（纳音断语、楼层、星级），本件不写；"
            "引通行说法必另立附录并声明「非梁氏原文」。",
            "**不用分数冒充精度。** 判断只给三档强度（确断／倾向／存疑），不给星级与百分比——"
            "星级不可证，最易「以包准自居」。",
            "**分寸语。** 原书语：能有个七成应验，就算合理合宜。本件不作「必然」「注定」之断。",
        ]),
    ]
    return blocks


def front_glance(a, opt):
    """盘面速览：四柱盒 + 三行速览 + 一句话定调（待批）。"""
    gj = a.get("geju") or {}
    wx = a["wuxing"]
    order = ["木", "火", "土", "金", "水"]
    ss = a.get("shensha") or []
    seen = [x for x in ss if x.get("hits")]
    sp = [x for x in (a.get("shensha_sp") or []) if x.get("status") == "命中"]
    rows = []
    for r in a["expanded"]:
        hid = "／".join("%s%s" % (h["stem"], h["tg"]) for h in r["hidden"])
        rows.append((r["pos"], r["stem"], r["branch"],
                     "日主" if r["pos"] == "日" else r["stem_tg"], hid,
                     xun_kong(r["pillar"])))
    blocks = [
        h3("四柱盘"),
        table(["柱", "干", "支", "十神", "藏干", "旬空"], rows),
        h3("速览四点"),
        ul([
            "**日主与月令**：%s。日主%s，生于%s月，%s。"
            % (a["guo"], a["pillars"][2][0], a["pillars"][1][1],
               "当令" if a.get("xingtai", {}).get("season") else "失令未判"),
            "**格局**：%s。%s" % (gj.get("name", "未定"),
                                 gj.get("grade", "") + ("；" + gj.get("shun", "") if gj.get("shun") else "")),
            "**五行**：%s。%s" % (
                "　".join("%s%d" % (k, wx.get(k, 0)) for k in order),
                "缺" + "、".join(a["missing"]) if a["missing"] else "五行不缺"),
            "**神煞**：四表见 %d 项（只报见否，不判吉凶）；神煞探源起例命中 %d 条。"
            % (len(seen), len(sp)),
        ]),
        h3("一句话定调"),
        todo("一句话定调（一句，不逾四十字；须能概括本造之「格局＋用神＋一生大势」）",
             ["照梁师批命体例，先给定调，再展开；定调不可含糊（如「一生平平」），"
              "亦不可许诺（如「必富贵」）。",
              "定调须与 ⑤ 格局、⑦ 用神、⑲ 总纲三处不冲突；冲突则改定调，不改三处。"],
             [(gj["rule_ids"][0], "格局", "E6")] if gj.get("rule_ids") else []),
    ]
    return blocks


# ──────────────────── 卷末：存疑与反证（由 --audit 重算） ────────────────────
def audit(text):
    """按节统计证据密度与判断强度，指出最薄三节。

    这是「专业」与「热闹」的分界：热闹的报告每句都一样肯定；
    专业的报告知道哪一句是自己最没底的，并把它写出来。
    """
    secs = []
    for m in re.finditer(r"(?m)^##\s*([①-⑲])\s*(.+)$", text):
        secs.append((m.start(), m.group(1), m.group(2).strip()))
    out = []
    for i, (pos, no, title) in enumerate(secs):
        end = secs[i + 1][0] if i + 1 < len(secs) else len(text)
        if i + 1 == len(secs):
            # 末节（⑲ 总纲）后面紧跟附录：不截住就会把附一附二的编号全算进总纲，
            # 于是总纲显示「证据 73 条」，而别节被摊薄——这个错很隐蔽，因为总数看着还像对的。
            m2 = re.search(r"(?m)^##\s*(?:附|卷首)", text[pos:])
            if m2:
                end = pos + m2.start()
        seg = text[pos:end]
        ids = set(RULE_RE.findall(seg)) | set(CELL_RE.findall(seg))
        g1 = seg.count("〔确断〕")
        g2 = seg.count("〔倾向〕")
        g3 = seg.count("〔存疑〕")
        out.append({"no": no, "title": title, "ids": len(ids), "ch": len(re.sub(r"\s+", "", seg)),
                    "g1": g1, "g2": g2, "g3": g3,
                    "grade": g1 + g2 + g3,
                    # 无强度标者即「结构节」：只出结构（四柱、表值、见否），不出判断。
                    # 这类节证据少属正常（排盘不需几十条规则背书），故不列入「最薄」。
                    "kind": "判断" if (g1 + g2 + g3) else "结构",
                    "unres": len(set(re.findall(r"[FU]-[A-Z0-9]+-\d+", seg)))})
    return out


def back_caveat(text):
    """生成「存疑与反证」节：证据强度分布 + 最薄三节 + 未决项牵涉 + 与通行说法差异。"""
    rows = audit(text)
    heads = ["板", "标题", "证据", "正文字数", "确断", "倾向", "存疑", "未决项"]
    body = [(r["no"], r["title"] + ("（结构）" if r["kind"] == "结构" else ""),
             r["ids"], r["ch"], r["g1"], r["g2"], r["g3"], r["unres"]) for r in rows]
    # 薄弱度：证据少、倾向存疑多、字数少者优先
    # 总纲（⑲）是收束节，其证据挂在前面各节，本节无引不出「薄」；排除后才不冤枉它
    judged = [r for r in rows
              if r["kind"] == "判断" and not r["title"].startswith("总纲")] or rows
    rank = sorted(judged, key=lambda r: (r["ids"] / max(r["grade"], 1), -r["g3"], r["ch"]))[:3]
    # 先取「达标薄」者（证据 ≤3 条或有存疑），不足三处再从余下顺位补足——
    # 否则标题写「三处」而正文只列两处，是自我打脸的第一种写法。
    hot = [r for r in rank if r["ids"] <= 3 or r["g3"] > 0]
    picked = hot + [r for r in rank if r not in hot][:max(0, 3 - len(hot))]
    CN = "零一二三四五"
    thin = "、".join("%s %s（证据 %d 条、存疑 %d 处）" % (r["no"], r["title"], r["ids"], r["g3"])
                    for r in picked) or "无"
    L = ["## 附一　存疑与反证", "",
         "本节由 `python tools/report_gen.py --audit 本文件 --write` 重算。"
         "**报告里最该看的不是结论，是这一节**：它写明哪几节证据最薄、哪些判断只到「倾向／存疑」、"
         "哪些结论牵涉未决条目、与通行说法何处不同。读者凭此可分辨哪句硬、哪句软。",
         "", "### 一、证据强度分布", "",
         "| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    L += ["| " + " | ".join(str(x) for x in r) + " |" for r in body]
    L += ["",
          "**读法**：`证据` 为本章去重的 rule_id／cell_id 条数；`确断／倾向／存疑` 为本章判断的强度分布"
          "（口径见卷首第三节）。证据少而确断多，是可疑的——那说明断语跑在依据前面。",
          "", "### 二、本案最薄%s处" % CN[len(picked)] if picked else "### 二、本案最薄之处", "",
          "**只从「判断节」中选**：标「结构」者（四柱、表值、见否）本不需大量规则背书，"
          "证据少属正常；⑲ 总纲为收束节，其证据挂在前节，不重复计。二者皆不列此榜。"
          "按「证据条数÷判断数」低者优先、存疑多者次之，得出"
          "**%s**。这%s处若被追问，本件答不满，须补料或降为「倾向」。"
          % (thin, CN[len(picked)] if picked else "几"),
          "", "### 三、与通行说法不同处（本包定则，非疏漏）", "",
          "| 事 | 通行说法 | 本包所据 | 理由 |", "|---|---|---|---|",
          "| 华盖起法 | 「仅年支起算，日支不参与」 | `JS-SS-04` 表头「日柱地支」 | "
          "《子平基础概要》神煞例表（四）表头明写「日柱地支」，以书为准 |",
          "| 神煞吉凶 | 「某煞主凶」 | 只报见／不见 | `R-MF-044`～`046` 与 p027 命名说两存，不代裁 |",
          "| 调候主次 | 「第一用神、第二用神」 | 只列候选，不排主次 | 原表未分主次，分了就是替梁氏作主 |",
          "| 身强弱 | 打分量化 | 等权计数，不作加权 | 梁氏不以数字量化强弱（`R01`） |",
          "", "### 四、须补何料方能定案", "",
          "| 缺料 | 补后能定什么 |", "|---|---|"]
    miss = []
    if "未校正" in text:
        miss.append(("出生经度", "真太阳时校正后重排；若时辰临界，年日时三柱可能全变，本件须重批"))
    if "起运岁**不详**" in text or "起运" in text and "不详" in text:
        miss.append(("起运岁（`paipan.py` 起运）", "大运表可标虚岁，墓库运与冲提运方能落年"))
    if "未给 `--dayun`" in text or "大运：未给" in text:
        miss.append(("大运干支", "第九节五法逐运可判；否则只出结构"))
    if "流月" in text and "无材料" in text:
        miss.append(("流月材料", "应期可从年降到月"))
    if not miss:
        miss.append(("（无）", "本件材料已足；余下为原书本身的未决条目，非材料问题"))
    L += ["| %s | %s |" % x for x in miss]
    return "\n".join(L), len(rows)


# ────────────────────────── 各板块 ──────────────────────────
def sec1(a, opt):

    day = a["pillars"][2][0]
    gj = a["geju"]
    rows = [("性别", a["gender"] or "未注"),
            ("四柱", "　".join(a["pillars"])),
            ("日主", "%s（%s）" % (day, A.STEM_ELEM[day])),
            ("月令", "%s月（%s）" % (a["pillars"][1][1], A.SEASON[a["pillars"][1][1]])),
            ("格局", "%s·%s（%s）" % (gj["name"], gj["shun"], gj["verdict"].split("（")[0])),
            ("起运", ("虚岁 %d 岁" % opt.start_age) if opt.start_age else "未给（须以 paipan.py 起运为准）")]
    dy = opt.dayun or []
    if dy and opt.start_age:
        rows.append(("现行大运", "须按流年定（见第九、十节）"))
    if opt.liunian:
        rows.append(("流年", "、".join(str(x) for x in opt.liunian)))
    blocks = [table(["项", "值"], rows)]
    if opt.lon:
        blocks.append(note("真太阳时：已按经度 %s° 校正（`paipan.py` E6）。" % opt.lon))
    else:
        blocks.append(note("真太阳时：**未校正**（未给出生经度）。本报告不默认已校正——"
                           "经度差四度即差一分钟以上，时辰临界之造会因此换柱，须补经度后重排。"))
    blocks.append(note("证据：四柱为 E6 结构计算；格局挂 %s。"
                       % "、".join("`%s`" % x for x in gj["rule_ids"][:6])))
    return blocks


def sec2(a, opt):
    heads = ["柱", "干支", "十神", "藏干（本气·中气·余气）", "旬空"]
    rows = []
    for r in a["expanded"]:
        hid = "／".join("%s%s" % (h["stem"], h["tg"]) for h in r["hidden"])
        rows.append((r["pos"], r["pillar"],
                     "日主" if r["pos"] == "日" else r["stem_tg"], hid, xun_kong(r["pillar"])))
    blocks = [table(heads, rows)]
    blocks.append(note("纳音：本包**无纳音规则**（`rules.csv` 检索「纳音」0 命中），"
                       "故本报告不出纳音断语——查不出即写查不出，不拿通行表补。"))
    blocks.append(note("旬空两说并列：按日柱 %s 之旬，空在 %s；按年柱 %s 之旬，空在 %s。"
                       "基准未定，不代裁（`R-SZ-025` 论空亡大运时另有所取）。"
                       % (a["pillars"][2], xun_kong(a["pillars"][2]),
                          a["pillars"][0], xun_kong(a["pillars"][0]))))
    dy = opt.dayun or []
    if dy:
        blocks.append(h3("大运表"))
        if opt.start_age:
            r = [(i + 1, gz, "虚岁 %d 起" % (opt.start_age + 10 * i))
                 for i, gz in enumerate(dy)]
            blocks.append(table(["运次", "干支", "起运"], r))
            blocks.append(note("起运岁由 `paipan.py` 定；本表只承干支次序，不重推节气。"))
        else:
            r = [(i + 1, gz) for i, gz in enumerate(dy)]
            blocks.append(table(["运次", "干支"], r))
            blocks.append(note("起运岁**不详**（未给 `--start-age`），故本表只列干支次序；"
                               "不臆填岁数——起运须以 `paipan.py` 按生日与节气定。"))
    else:
        blocks.append(note("大运：未给 `--dayun`，本报告不出大运表（查不出）。"))
    return blocks


def sec3(a):
    wx = a["wuxing"]
    order = ["木", "火", "土", "金", "水"]
    rows = [(k, wx.get(k, 0)) for k in order]
    rows.append(("合计", sum(wx.get(k, 0) for k in order)))
    blocks = [table(["五行", "计数（含藏干）"], rows)]
    blocks.append(note("缺行：%s。" % ("、".join(a["missing"]) if a["missing"] else "五行不缺")))
    tg = sorted(a["ten_gods"].items(), key=lambda kv: -kv[1])
    blocks.append(h3("十神分布"))
    blocks.append(table(["十神", "计数"], [(k, v) for k, v in tg]))
    blocks.append(note("**等权计数，不作旺衰加权。** 梁氏不以数字量化强弱（`R01` 斥「一上手就讲"
                       "日主强、选用神谈喜忌」之弊）；本节只作分布描述，**不得由计数直推身强身弱**，"
                       "那要另走扶抑一路（第七节）。"))
    return blocks


def sec4(a):
    rel = a["relations"]
    blocks = []
    if rel:
        rows = []
        for r in rel:
            cell = (r.get("cell") or {}).get("cell_id", "")
            rows.append((r["kind"], "、".join(r["members"]),
                         "、".join(r.get("positions") or []), "`%s`" % cell if cell else "—"))
        blocks.append(table(["关系", "成员", "落点", "表值"], rows))
    else:
        blocks.append(p("四柱之间未见冲、合、刑、害、三合、三会（查不出）。"))
    blocks.append(note("刑冲合会按 `TB-XJ*` 系列逐格对读；拱夹另见 `R-JC-01`～`07`"
                       "（《子平基础概要》p154–156），**写「拱得某支」不写「明见某支」**。"))

    ss = a["shensha"]
    blocks.append(h3("神煞（四表实查）"))
    rows = []
    for s in ss:
        cell = (s.get("cell") or {}).get("cell_id", "")
        hits = ["%s柱%s" % (h[0], h[1]) if isinstance(h, tuple) else str(h) for h in s["hits"]]
        rows.append((s["name"], s["table"], "%s→%s" % (s["key"], s["value"]),
                     "见" if hits else "不见", "、".join(hits) if hits else "—",
                     "`%s`" % cell if cell else "—"))
    blocks.append(table(["神煞", "查法（表）", "格值", "见否", "落柱", "表值"], rows))
    blocks.append(note("**只报见／不见与落点，不判吉凶。** 神煞吉凶两说并存"
                       "（`R-MF-044`～`046` 与 p027 命名说），本报告不代裁。"
                       "起法以《子平基础概要》原表四张为准：年支查孤辰寡宿大耗、月支查天月德、"
                       "日干查天乙文昌羊刃干禄红艳、日支查将星华盖驿马劫煞亡神桃花。"))

    sp = a.get("shensha_sp") or []
    if sp:
        from collections import Counter as _C
        cnt = _C(x["status"] for x in sp)
        show = [x for x in sp if x["status"] != "不成立"]
        blocks.append(h3("神煞探源起例（R-SP-001～049）"))
        blocks.append(p("与上表互补：上表是《子平基础概要》的神煞例表，此表是《神煞探源》各条的**起例**。"
                        "总计：" + "、".join(f"{k} {v}" for k, v in cnt.most_common()) + "。"))
        if show:
            rows2 = [(x["rule_id"], x["name"], x["status"], x["detail"], x["anchor"]) for x in show]
            blocks.append(table(["规则", "神煞", "结果", "依据", "锚"], rows2))
        else:
            blocks.append(p("逐条核对，四十九款起例俱不成立（查不出）。"))
        blocks.append(note("起例照原文；原文只给诗诀、或对照表为图版者标「待人工对表」，"
                           "讹字标「原文待核」——**不猜、不以通行术数补**。"
                           "起例成立只说明结构合，不等于应验（原文自陈「不是百分之一百」）；"
                           "神煞本身不判吉凶，须与日主论生克。"))
    return blocks


def sec5(a):
    gj = a["geju"]
    blocks = [p("月令%s，本气%s（%s）。%s，得**%s**，属**%s**（`%s`）。"
                % (a["pillars"][1][1], A.HIDDEN[a["pillars"][1][1]][0],
                   A.ten_god(a["pillars"][2][0], A.HIDDEN[a["pillars"][1][1]][0]),
                   gj["how"], gj["name"], gj["shun"], gj["shun_rule"]))]
    if gj["rows"]:
        rows = []
        for r in gj["rows"]:
            where = "、".join(r["where"][:4]) + (" 等%d处" % len(r["where"])
                                                 if len(r["where"]) > 4 else "") \
                if r["where"] else "—"
            rows.append((r["kind"], r["god"], "见" if r["found"] else "未见", where,
                         "`%s`" % r["rule"]))
        blocks.append(table(["项", "十神", "判定", "落点", "依据"], rows))
    blocks.append(p("结构结论：**%s**。" % gj["verdict"]))
    if gj.get("waige"):
        blocks.append(p("外格：%s。" % gj["waige"]))
    blocks.append(note("本报告**只断结构成立与否，不断吉凶与富贵层次**。"
                       "相神（`R-SS-033`／`034`）、有情有力（`R-SS-028`～`030`）、"
                       "十四制式（`R-SS-036`～`041`）、双格轻重（`R-SS-024`～`026`）未落算，须人工对条文。"))
    blocks.append(note("依据：%s。" % "、".join("`%s`" % x for x in gj["rule_ids"])))
    return blocks


def sec6(a):
    th = a["th"]
    blocks = []
    if not th:
        blocks.append(p("调候原表查无此格（查不出）。`TAB-LXR-TH-01-ORIG` 为 10×12 全表，"
                        "缺格即录入缺口，不自行拟补。"))
        return blocks
    rows = []
    for t in th:
        day = a["pillars"][2][0]
        chars = [c for c in t["value"] if c in A.STEMS]
        sat = []
        stems = [r["stem"] for r in a["expanded"]]
        hidden = [h["stem"] for r in a["expanded"] for h in r["hidden"]]
        for c in chars:
            if c in stems:
                sat.append("%s：透于%s柱" % (c, "、".join(
                    r["pos"] for r in a["expanded"] if r["stem"] == c)))
            elif c in hidden:
                sat.append("%s：藏于%s" % (c, "、".join(
                    r["pos"] for r in a["expanded"]
                    if any(h["stem"] == c for h in r["hidden"]))))
            else:
                sat.append("%s：原局无" % c)
        rows.append((t["cell_id"], t["value"], "；".join(sat)))
    blocks.append(table(["格值出处", "调候字", "原局满足度"],
                        [(("`%s`" % r[0]), r[1], r[2]) for r in rows]))
    blocks.append(note("原表：%s。" % th[0]["table_title"]))
    blocks.append(note("原表一格列 2–5 字，**不分主次**。本报告照列，不排第一第二——"
                       "分了就是替梁氏作主。用神之取捨见第七节各路。"))
    if any(t["cell_id"] == "T-ORIG-TH01-092" for t in th):
        blocks.append(note("此格（辛日主·酉月）格值存疑：原表作「壬申」，「申」非天干，"
                           "疑转录之误（P0 对照查出）。**本格不出调候断语。**"))
    blocks.append(note("依据：%s（E1 原表，119/120 格已核）。"
                       % "、".join("`%s`" % t["cell_id"] for t in th)))
    return blocks


def sec7(a):
    rows = []
    for w in a["wuyong"]:
        rows.append((w["name"], w["by"], w["this"], "适用" if w["use"] else "不适用"))
    blocks = [table(["路", "所据", "本案所取", "状态"], rows)]
    blocks.append(note("上表为**本器落算之五路**；规格所列六路中的「日主十干喜忌」与「忌神复核」"
                       "两路，本器不单列（十干喜忌散在 `R-SZ` 日用条，忌神复核见第五节忌神表），"
                       "须人工对条文，**不得以五路当六路**。"))
    blocks.append(note("各路并列，**不排名、不计票、不打分**。梁氏无「第一用神／第二用神」之说；"
                       "某路不适用须写「不适用」及理由，不得跳过。"))
    blocks.append(note("日主十干喜忌（`R-SZ` 日用）与调候（`R-SZ-011`）孰先，"
                       "F06 未裁；本报告两说并列，不代定次序。"))
    return blocks


def sec8(a):
    return [todo("六亲专题（妻／财／子／禄／寿分列）", [
        "妻星与妻宫：星宫同看，星看十神、宫看日支；婚姻项须 ≥3 路独立来源。",
        "财与事业：财星为用为忌两判，不得只以「财多」断富。",
        "父母：年月柱与印星参看，须与六亲宫位对读。",
        "子女：时柱与官杀／食伤参看；子女项门槛 ≥2 路。",
        "寿：**只判长短，不判年岁**——原书明言不能只凭四柱论亡殁之年。",
        "任一子项不足门槛者写「信号单薄，待大运验证」，不写肯定句。",
    ], pool(a, ["妻", "财", "子", "寿", "六亲", "父母", "婚姻"]))]


def sec9(a):
    dy = a["dayun"]
    if not dy:
        return [p("未给 `--dayun`，本节不出（查不出）。")]
    rows = []
    for d in dy:
        hits = [h for h in d["hits"]]
        rows.append((d["n"], d["gz"], A.ten_god(a["pillars"][2][0], d["gz"][0]),
                     "；".join(hits[:4]) if hits else "无"))
    blocks = [table(["运次", "干支", "运干十神", "五法与冲合"], rows)]
    blocks.append(note("五法：十干败亡（`R-SZ-020`）／墓库（`R-SZ-021`～`023`，**只限辰戌丑未月生人**）／"
                       "空亡（`R-SZ-025`）／接角（`R-SZ-026`）／冲提（`R-SZ-028`）。"
                       "非四库月生人，墓库运直判不适用，不硬套。"))
    blocks.append(note("「夹」之取法原文未给，本包不判（查不出）。"))
    return blocks


def sec10(a, opt):
    if not a["liunian"]:
        return [p("未给 `--liunian`，本节不出（查不出）。应期三段为「运定十年→年定年份→月定月份」，"
                  "缺流年则连第一段都无法落。")]
    rows = []
    for x in a["liunian"]:
        mm = "、".join(sorted({r["kind"] for r in x["rows"] if r["main"]})) or "—"
        aux = "、".join(sorted({r["kind"] for r in x["rows"] if not r["main"]})) or "—"
        rows.append((x["year"], x["gz"], x["age"] or "—", x["dayun"] or "—", mm, aux))
    blocks = [table(["年", "流年", "虚岁", "所行大运", "主命中（可断）", "只记结构（不作断）"], rows)]
    if any(not x["dayun"] for x in a["liunian"]):
        blocks.append(note("「所行大运」为空者，是流年已超出所给大运步数（本报告只给 %d 步），"
                           "非无运。补全八步后重跑，或另以 `paipan.py` 复核起运。" % len(opt.dayun or [])))
    blocks.append(note("**两档纪律**：主命中方可断；刑、单冲、单合、伏吟、反吟只记结构。"
                       "`R135`：流年不是每年都有事可断，一造至多散出二十年可用之流年——"
                       "逐年充数即等于取消门槛。"))
    blocks.append(note("只到结构、不到应事：流年吉凶之轻重与应期先后，本器不排。"))
    return blocks


def sec11(a):
    return [todo("人生建议（一条主线 + 三到四件要做对的事）", [
        "主线一句：本造这一生大体该怎么走，须能回收到第五、七、九节。",
        "三到四件要做对的事：每件须指到具体结构（某格、某运、某忌神），不写通用鸡汤。",
        "**全局配合声明（硬要求，不可省）**：列明哪些结论来自哪几路独立来源；"
        "哪一处存在矛盾（如调候与扶抑相左）及如何权衡。",
    ], pool(a, ["用神", "喜忌", "顺用", "逆用", "取用"]))]


def _topic(words, title, frames):
    return words, title, frames


TOPICS = [
    (["学业", "读书", "考试", "文昌"], "学业说明书",
     ["职业基因：何格何神主读书（印／食伤／文昌），本造见否。",
      "读书运：大运是否补调候、是否冲提，逐运一句。",
      "可执行建议：只在结构允许范围内给，不承诺考运。"]),
    (["事业", "职业", "官", "升迁"], "事业说明书",
     ["职业基因：格与用神定行业属性（官印／财官／食伤生财），须挂证。",
      "财富／权力模式：顺用格看相神，逆用格看制神。",
      "可执行建议：宜何途、忌何途，各指到一条结构。"]),
    (["财", "富", "求财"], "财富说明书",
     ["财富模式：财星为用／为忌，财透／财藏，财坐空亡（`R46`）。",
      "得财之途：食伤生财、官护财、劫夺财三路择一，须挂证。",
      "可执行建议：聚财方式与破财关口。"]),
    (["人际", "兄弟", "朋", "小人", "贵人"], "人际说明书",
     ["比劫与官杀之分布定人际张力。",
      "天乙、贵人、驿马之落点定助力来源（只报落点，不判吉凶）。",
      "可执行建议：宜交何类、忌结何类。"]),
    (["疾病", "健康", "五行偏"], "健康说明书",
     ["体质倾向：五行偏热／偏寒／偏燥／偏湿，须挂证。",
      "**措辞限「偏热／偏寒／偏燥／偏湿」「须注意」，不做疾病诊断。**",
      "无显明症兆者不批——原书：「有显明之症兆，才批出断句」。"]),
]


def sec12to16(a):
    out = []
    for words, title, frames in TOPICS:
        out.append(todo(title, frames, pool(a, words)))
    return out


def sec17(a):
    return [todo("年度行动指南（三到五年，逐年一句）", [
        "逐年一句，标出与流年刑冲合会相关的关口；**只作结构提示，不排月**。",
        "与第十节主命中对齐：无主命中之年写「平年，无大事触发」，不硬凑。",
        "明写「逐年细批须另立流年书」——本节不是流年书。",
    ], pool(a, ["流年", "太岁", "岁运"]))]


def sec18(a, opt):
    """风险四检查：结构实算 + 真实条号回查，不臆造。"""
    br = [r["branch"] for r in a["expanded"]]
    day = a["pillars"][2][0]
    month_b = a["pillars"][1][1]
    checks = []

    tl = any({x, y} <= set(br) for x, y in [("辰", "戌"), ("戌", "亥"), ("辰", "巳")])
    checks.append(("天罗地网", "见" if tl else "不犯",
                   "四支见辰戌／戌亥／辰巳" if tl else "四支未见上述组合",
                   risk_rule("天罗地网")))
    ku = [g for g in (opt.dayun or []) if g[1] in "辰戌丑未"]
    if month_b in "辰戌丑未":
        checks.append(("墓库运", "见（%s）" % "、".join(ku) if ku else "不犯",
                       "本造生于四库月，运入四库须按 R-SZ-021～023 逐条核" if ku
                       else "生于四库月，所行运中无四库", risk_rule("墓库运")))
    else:
        checks.append(("墓库运", "不适用",
                       "月支%s非辰戌丑未，依原书墓库运只限四库月生人" % month_b,
                       risk_rule("墓库运")))
    ct = [g for g in (opt.dayun or []) if {g[1], month_b} in [set(x) for x in A.CHONG]]
    checks.append(("冲提运", "见（%s）" % "、".join(ct) if ct else "不犯",
                   "运支冲月支为冲提" if ct else "所行运未见冲月支", risk_rule("冲提")))
    gong = risk_rule("拱")
    checks.append(("拱合冲边", "须人工核",
                   "拱夹之成立与否看 `R52`／`R53`（拱之条件、暗拱逢冲为大忌），程序只列条件不代判",
                   gong))

    rows = []
    for name, verdict, why, rules in checks:
        ids = "、".join("`%s`" % r[0] for r in rules[:2]) or "查不出"
        rows.append((name, verdict, why, ids))
    blocks = [table(["检查项", "本案", "判据", "依据"], rows)]
    blocks.append(note("**不得写成「必然发生」。** 本节列的是结构风险与须避之事，"
                       "不是预言；原局无此结构者写「不犯」，不硬凑。"))
    return blocks


def sec19(a):
    return [todo("总纲（一段收束，不新增判断）", [
        "只收束前十八节，**不新增判断**；出现新结论即为越界。",
        "回到「这个人这一生大体怎么走」，一句定调。",
        "结尾须有分寸语：切忌以包准自居——原书语「能有个七成应验，就算合理合宜」。",
    ], pool(a, ["总纲", "批命", "应验"]))]


# ────────────────────────── 装配 ──────────────────────────
def build(a, opt):
    secs = [sec1(a, opt), sec2(a, opt), sec3(a), sec4(a), sec5(a), sec6(a), sec7(a),
            sec8(a), sec9(a), sec10(a, opt), sec11(a)]
    t12 = sec12to16(a)
    secs.extend([[t12[i]] for i in range(5)])
    secs.append(sec17(a))
    secs.append(sec18(a, opt))
    secs.append(sec19(a))
    assert len(secs) == 19, len(secs)
    return secs


def doc_md(a, opt, secs):
    head = ["# 分析报告　%s" % "　".join(a["pillars"]), "",
            "> 判断强度分三档（〔确断〕〔倾向〕〔存疑〕），口径见卷首第三节；"
            "一卷之内，硬处与软处须分得开。",
            # 骨架的自我声明也带〔待批〕：填完须改成「已逐节落笔」，否则 B06 拦。
            # 光靠板块内的占位拦不住「把占位删掉、正文留空」的写法，卷首这句是第二道。
            "> 骨架由 `tools/report_gen.py` 生成：结构数据已填，判断类板块留〔待批〕位。", "",
            "## 卷首　批断流程与材料清点", "", render_md(front_flow(a, opt)), "",
            "## 卷首　盘面速览", "", render_md(front_glance(a, opt)), ""]
    body = []
    for i, blocks in enumerate(secs):
        body.append("## %s %s" % (CIRCLED[i], TITLES[i]))
        body.append("")
        body.append(render_md(blocks))
    tail = ["", "---", "", "## 附一　存疑与反证", "",
            "〔本节由 `python tools/report_gen.py --audit 本文件 --write` 生成："
            "逐节证据密度、判断强度分布、最薄三处、与通行说法差异、须补之料。〕", "",
            "## 附二　证据索引", "",
            "〔本节由 `python tools/report_gen.py --index 本文件 --write` 生成："
            "全文 rule_id／cell_id 去重清单，逐条给来源定位与等级。〕"]
    return "\n".join(head + body + tail)


def doc_html(a, opt, secs):
    css_path = os.path.join(TEMPLATES, "report.css")
    css = ""
    if os.path.exists(css_path):
        with io.open(css_path, encoding="utf-8") as f:
            css = f.read()
    toc = [("s1", "批断流程与材料清点", "front"), ("s2", "盘面速览", "front")]
    parts = ['<h2 id="s1" class="front">卷首　批断流程与材料清点</h2>', render_html(front_flow(a, opt)),
             '<h2 id="s2" class="front">卷首　盘面速览</h2>', render_html(front_glance(a, opt))]
    for i, blocks in enumerate(secs):
        aid = "s%d" % (i + 3)
        toc.append((aid, TITLES[i], "sec"))
        parts.append('<h2 id="%s"><span class="no">%s</span>%s</h2>'
                     % (aid, CIRCLED[i], TITLES[i]))
        parts.append(render_html(blocks))
    toc += [("s22", "存疑与反证", "app"), ("s23", "证据索引", "app")]
    parts += ['<h2 id="s22" class="app">附一　存疑与反证</h2>',
              '<div class="todo"><b>〔待生成〕</b>本节由 report_gen.py --audit 生成。</div>',
              '<h2 id="s23" class="app">附二　证据索引</h2>',
              '<div class="todo"><b>〔待生成〕</b>本节由 report_gen.py --index 生成。</div>']
    return wrap_html("\n".join(parts), a["pillars"], css, toc,
                     "骨架　·　判断类板块待批，未经填写不得视为交付件")


# ────────────────────────── md → html（已填报告转版式） ──────────────────────────
def _md_inline(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"`([^`]+)`", r'<span class="ev">\1</span>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    return _grades_html(t)


def _md_table(rows):
    """rows 首行为表头，第二行为分隔线。

    短列自动加 `nw`（不许断字）：某一列所有格都不逾六字者，该列必是序次、
    状态、根气一类标签列，让它在自动布局里被长文本挤成「部／分」两行是排版事故。
    """
    body = rows[2:]
    heads = [c.strip() for c in rows[0].strip("|").split("|")]
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in body]
    ncol = len(heads)

    def _w(s):
        return len(re.sub(r"[`*\[\]（）()　]", "", str(s)))

    widths = []
    for j in range(ncol):
        col = [r[j] for r in cells if j < len(r)] + [heads[j] if j < ncol else ""]
        widths.append(max(_w(x) for x in col))
    nw = {j for j in range(ncol) if widths[j] <= 6}

    s = ["<table>", "<tr>" + "".join("<th>%s</th>" % _md_inline(h) for h in heads) + "</tr>"]
    for r in cells:
        s.append("<tr>" + "".join(
            '<td class="%s">%s</td>' % ("nw" if j in nw else "l", _md_inline(c))
            for j, c in enumerate(r)) + "</tr>")
    s.append("</table>")
    return "\n".join(s)


def md_to_html(text):
    """把 report_gen 自己产出的 md（也兼容人工填写的同体例稿）转成报告版式。

    只支持本包用到的子集：## 标题、### 小标题、表格、- 列表、> 引文、段落、
    行内 `证据` 与 **强调**。不是通用 markdown 转换器——够用即止，复杂排版请直接改 HTML。

    返回 (html, toc)：toc 为 [(锚点, 标题, 类别)]，供侧栏目录用。类别取
    front（卷首）／sec（十九板块）／app（附录），只影响目录的分组与缩进。
    """
    lines = text.splitlines()
    out = []
    toc = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if ln.startswith("### "):
            out.append("<h3>%s</h3>" % _md_inline(ln[4:].strip()))
            i += 1
        elif ln.startswith("## "):
            t = ln[3:].strip()
            m = re.match(r"([%s])\s*[\s　]*(.*)" % CIRCLED, t)
            anchor = "s%d" % (len(toc) + 1)
            if m:
                out.append('<h2 id="%s"><span class="no">%s</span>%s</h2>'
                           % (anchor, m.group(1), _md_inline(m.group(2))))
                toc.append((anchor, m.group(1) + "　" + (m.group(2) or t), "sec"))
            else:
                kind = "front" if t.startswith("卷首") else ("app" if t.startswith("附") else "")
                cls = ' class="%s"' % kind if kind else ""
                # 卷首／附录前缀由 CSS ::before 出「卷首」「附录」标签，正文不再重复
                label = re.sub(r"^卷首[\s　]*", "", t) if kind == "front" else \
                        (re.sub(r"^附[一二]?[\s　]*", "", t) if kind == "app" else t)
                out.append('<h2 id="%s"%s>%s</h2>' % (anchor, cls, _md_inline(label)))
                toc.append((anchor, label, kind or "sec"))
            i += 1
        elif ln.startswith("# "):
            i += 1                      # 大标题已由抬头承担，不重复
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_md_table(rows) if len(rows) >= 2 else "<p>%s</p>" % _md_inline(ln))
        elif ln.startswith("> "):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            inner = " ".join(x for x in buf if x)
            out.append("<blockquote>%s</blockquote>" % _md_inline(inner))
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(lines[i][2:].strip())
                i += 1
            out.append("<ul>" + "".join("<li>%s</li>" % _md_inline(x) for x in items) + "</ul>")
        elif ln.startswith("---"):
            out.append("<hr>")
            i += 1
        else:
            buf = []
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||>|- |---)", lines[i]):
                buf.append(lines[i].strip())
                i += 1
            out.append("<p>%s</p>" % _md_inline(" ".join(buf)))
    return "\n".join(out), toc


def wrap_html(body_html, pillars, css, toc=None, stats=""):
    """整页装配：左侧目录 + 右侧纸页。目录为 sticky，宽屏显示、窄屏收起。"""
    toc = toc or []
    nav = ['<nav class="toc">', '<div class="toc-t">目　录</div>']
    groups = [("front", "卷首"), ("sec", "十九板块"), ("app", "附录")]
    for g, label in groups:
        items = [(a, t) for a, t, k in toc if k == g]
        if not items:
            continue
        nav.append('<div class="toc-g">%s</div><ol class="toc-%s">' % (label, g))
        nav += ['<li><a href="#%s">%s</a></li>' % (a, t) for a, t in items]
        nav.append("</ol>")
    nav.append("</nav>")
    return "\n".join([
        "<!DOCTYPE html>", '<html lang="zh-Hans">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>分析报告　%s</title>" % "　".join(pillars),
        "<style>%s</style>" % css, "</head>", "<body>",
        '<div class="layout">', "\n".join(nav), '<div class="sheet">',
        "<header>", '<div class="kicker">十　九　板　块</div>', "<h1>分析报告</h1>",
        '<div class="sub">依梁湘润批例体例　·　每节挂证　·　判断分三档</div>', "</header>",
        '<div class="meta">%s　·　证据等级 E1–E6　·　查不出即写查不出</div>' % "　".join(pillars),
        "<blockquote>本件为分析件（交付件 B）：逐条挂证，供复核。与命书分轨——"
        "命书是断语体、零工程标记，两件不可混。</blockquote>",
        body_html,
        "<footer>%s分　析　报　告　终</footer>" % (stats + "　·　" if stats else ""),
        "</div>", "</div>", "</body>", "</html>"])


def from_md(src, out_path, pillars=None):
    css_path = os.path.join(TEMPLATES, "report.css")
    if not os.path.exists(css_path):
        raise SystemExit("缺 references/templates/report.css")
    with io.open(css_path, encoding="utf-8") as f:
        css = f.read()
    with io.open(src, encoding="utf-8-sig") as f:
        text = f.read()
    if not pillars:
        m = re.search(r"^#\s*\S*\s*([%s]{2})\s+([%s]{2})\s+([%s]{2})\s+([%s]{2})"
                      % (A.STEMS, A.STEMS, A.STEMS, A.STEMS), text, re.M)
        pillars = m.groups() if m else ["", "", "", ""]
    body, toc = md_to_html(text)
    ids = set(RULE_RE.findall(text)) | set(CELL_RE.findall(text))
    stats = "证据 %d 条　·　正文 %d 字" % (len(ids), len(re.sub(r"\s+", "", text)))
    html = wrap_html(body, pillars, css, toc, stats)
    io.open(out_path, "w", encoding="utf-8", newline="\n").write(html + "\n")
    return html


# ────────────────────────── 证据索引 ──────────────────────────
def ev_index(text):
    """证据索引：全文 rule_id／cell_id 去重，逐条给来源定位与等级。

    只收**真实存在**的编号。文中常出现 `TB-XJ*` 这类通配前缀、或 `T-X11-XJ02` 这类
    表号（非格值），它们不是证据，一律不计入，只报个数——否则索引会混进「查不出」噪音。
    """
    rules = sorted(set(RULE_RE.findall(text)))
    cells = sorted(set(CELL_RE.findall(text)))
    rows = []
    skipped = 0
    for rid in rules:
        r = RULE_BY_ID.get(rid)
        if not r:
            skipped += 1
            continue
        rows.append(("`%s`" % rid, r["theme"],
                     r["source_title"], r["source_locator"],
                     "%s·%s" % (grade_short(r["evidence_grade"]), r["verification_status"])))
    for cid in cells:
        c = CELL_BY_ID.get(cid)
        if not c:
            skipped += 1
            continue
        rows.append(("`%s`" % cid, c["table_title"], c["source_title"], c["source_locator"],
                     "%s·%s" % (grade_short(c["evidence_grade"]), c["verification_status"])))
    out = ["## 附二　证据索引", "",
           "全文去重：规则 %d 条、表值 %d 条，合计 %d 条；"
           "另有 %d 处表号／通配前缀（非格值），不计入。"
           % (len(rules), len(cells), len(rows), skipped),
           "", "| 编号 | 主题 | 来源 | 定位 | 等级 |", "|---|---|---|---|---|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out), len(rows)


def write_index(path, out_path=None):
    with io.open(path, encoding="utf-8-sig") as f:
        text = f.read()
    block, n = ev_index(text)
    new = _replace_section(text, ["## 附二　证据索引", "## 附：证据索引"], block)
    dest = out_path or path
    io.open(dest, "w", encoding="utf-8", newline="\n").write(new)
    return n, dest


def _replace_section(text, markers, block, stops=("## 附二　证据索引", "## 附：证据索引")):
    """把 markers 命中的那一节整体换掉；没有则追加在 stops 之前（或文末）。"""
    hit = next((m for m in markers if m in text), None)
    if hit:
        head = text.split(hit)[0].rstrip()
        rest = text.split(hit, 1)[1]
        # 本节之后若还有别的 h2（如证据索引），保留
        m = re.search(r"(?m)^##\s", rest)
        tail = rest[m.start():].rstrip() if m else ""
        return head + "\n\n" + block + ("\n\n" + tail if tail else "") + "\n"
    for s in stops:
        if s in text:
            head = text.split(s)[0].rstrip()
            tail = s + text.split(s, 1)[1]
            return head + "\n\n" + block + "\n\n" + tail.rstrip() + "\n"
    return text.rstrip() + "\n\n" + block + "\n"


def write_audit(path, out_path=None):
    with io.open(path, encoding="utf-8-sig") as f:
        text = f.read()
    block, n = back_caveat(text)
    new = _replace_section(text, ["## 附一　存疑与反证"], block)
    dest = out_path or path
    io.open(dest, "w", encoding="utf-8", newline="\n").write(new)
    return n, dest


# ────────────────────────── main ──────────────────────────
def main():
    ap = argparse.ArgumentParser(description="十九板块分析报告骨架生成器")
    ap.add_argument("pillars", nargs="*", help="四个干支，按年 月 日 时")
    ap.add_argument("--gender", choices=["男", "女"])
    ap.add_argument("--dayun", help="大运干支，逗号分隔")
    ap.add_argument("--liunian", help="流年：公历年或干支，逗号分隔")
    ap.add_argument("--birth-year", type=int)
    ap.add_argument("--start-age", type=int,
                    help="起运虚岁，取 paipan 输出的「交运虚岁」；不是「起运折几年」那年数")
    ap.add_argument("--base-year", type=int, help="以某年为「今年」（回批旧盘用）")
    ap.add_argument("--from-paipan", metavar="JSON",
                    help="直接读 paipan.py --json 的输出：四柱／性别／大运／交运虚岁一并取来")
    ap.add_argument("--recent", type=int, nargs="?", const=5, metavar="N",
                    help="自动取「最近 N 年」（含今年，默认 5），须配 --dayun --birth-year --start-age")
    ap.add_argument("--lon", type=float, help="出生地经度；给了即视为已校正真太阳时")
    ap.add_argument("--format", choices=["md", "html"], default="md")
    ap.add_argument("--out")
    ap.add_argument("--from-md", metavar="FILE", help="把已填好的 md 报告转成 HTML 版式")
    ap.add_argument("--index", metavar="FILE", help="只重算该文件的证据索引")
    ap.add_argument("--audit", metavar="FILE",
                    help="只重算该文件的「存疑与反证」节（证据密度／强度分布／最薄三处）")
    ap.add_argument("--write", action="store_true", help="与 --index／--audit 同用：就地写回")
    args = ap.parse_args()

    if args.from_md:
        if not args.out:
            ap.error("--from-md 须同时给 --out")
        html = from_md(args.from_md, args.out, args.pillars or None)
        print("已写出 %s（%d 字）" % (args.out, len(html)))
        return

    if args.audit:
        n, dest = write_audit(args.audit, args.audit if args.write else args.out)
        print("存疑节：%d 节统计 → %s" % (n, dest if (args.write or args.out) else "标准输出"))
        if not (args.write or args.out):
            with io.open(args.audit, encoding="utf-8-sig") as f:
                print(back_caveat(f.read())[0])
        return

    if args.index:
        n, dest = write_index(args.index, args.index if args.write else args.out)
        print("证据索引 %d 条 → %s" % (n, dest if (args.write or args.out) else "标准输出"))
        if not (args.write or args.out):
            with io.open(args.index, encoding="utf-8-sig") as f:
                print(ev_index(f.read())[0])
        return

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
        if args.lon is None and src.get("lon") is not None:
            args.lon = src["lon"]

    if len(args.pillars) != 4:
        ap.error("须给四个干支，按年 月 日 时（或给 --from-paipan）")
    if not args.gender:
        ap.error("须给 --gender（六亲与 scope 过滤都靠它）")
    bad = [x for x in args.pillars if x not in A.JIAZI_SET]
    if bad:
        ap.error("非干支：%s" % "、".join(bad))

    dayun = [x.strip() for x in (args.dayun or "").replace("，", ",").split(",") if x.strip()]
    ln = []
    for x in (args.liunian or "").replace("，", ",").split(","):
        x = x.strip()
        if not x:
            continue
        if x.isdigit():
            ln.append(int(x))
        elif x in A.JIAZI_SET:
            ln.append(x)
        else:
            ap.error("流年须为公历年或干支：%s" % x)

    a = A.analyze(args.pillars, args.gender, dayun or None, ln or None,
                  args.birth_year, args.start_age, False,
                  recent=args.recent, base_year=getattr(args, "base_year", None))
    # 各节统一按列表读，避免「字符串当列表用」这类静默错
    args.dayun, args.liunian = dayun, ln
    # --recent 也要算「流年已给」：正文第十节按它出了五年，
    # 卷首若仍写「流年未给」，同一件里前后打架。
    if not args.liunian and args.recent:
        args.liunian = A.recent_years(args.recent, getattr(args, "base_year", None))
    secs = build(a, args)
    text = doc_md(a, args, secs) if args.format == "md" else doc_html(a, args, secs)

    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        os.makedirs(d, exist_ok=True)
        io.open(args.out, "w", encoding="utf-8", newline="\n").write(text + "\n")
        todo_n = text.count("〔待批〕")
        print("已写出 %s（%d 字，待批板块 %d 处）" % (args.out, len(text), todo_n))
    else:
        print(text)


if __name__ == "__main__":
    main()
