#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规则分类与触发标签生成器（rule_tags.py）

给 data/rules.csv 补两个字段：

  topic         受控词表（14 类），由 theme 关键词映射而来。theme 是「标题」，
                775 条规则有 774 个 theme，按 theme 做索引等于一条一节；topic 才是分类。
  trigger_tags  从 conditions 抽出的触发要素，形如「月:寅|十神:正官|关系:冲」。
                analyze.py 用命盘特征去匹配它，据此判「命中／相关／不可判定」。

设计原则：
  1. **只抽条件里写明的，不推断。** conditions 没写月支，就不给「月:」标签。
  2. **抽不到就留空，不猜。** 空标签的规则在分析器里归入「条件未结构化」，
     明确列出，不用关键词打分硬凑成「相关」。
  3. topic 是粗分类，允许一条规则只属一类；不追求多标签。

用法：
    python tools/rule_tags.py --stat     # 只看分布，不写文件
    python tools/rule_tags.py --update   # 写回 rules.csv（加两列）
    python tools/rule_tags.py --list NA  # 列出无标签规则
"""
import argparse
import csv
import io
import os
import re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

BRANCH = "子丑寅卯辰巳午未申酉戌亥"
STEM = "甲乙丙丁戊己庚辛壬癸"

# ---- topic 受控词表：14 类，顺序即匹配优先级 ----
TOPICS = [
    ("体例次第", ["次序", "学前", "学理", "总纲", "看命", "断命秩序", "十项优先", "接案", "禁忌",
                  "不算之列", "权重", "古今差别", "优先权"]),
    ("用神", ["用神", "调候", "病药", "专旺", "扶抑", "取用", "日主喜忌", "喜忌"]),
    ("格局", ["格局", "格", "成格", "败格", "救应", "顺用", "逆用", "制式", "双格", "取格", "成败"]),
    ("刑冲合会", ["六冲", "六合", "三合", "三会", "相刑", "自刑", "六害", "拱夹", "方阵",
                    "冲提", "双冲", "刑冲", "合会", "透干"]),
    ("神煞", ["神煞", "驿马", "桃花", "空亡", "墓库", "天乙", "羊刃", "禄", "华盖", "将星"]),
    ("大运", ["大运", "运法", "起运", "败亡", "冲提", "接角", "行运", "运程"]),
    ("岁运流年", ["流年", "流月", "岁运", "太岁"]),
    ("六亲", ["六亲", "父母", "兄弟", "妻财", "子女", "夫星", "妻星", "亲属"]),
    ("婚姻女命", ["婚姻", "合官", "夫星", "妻星", "桃花煞", "多妻"]),
    ("疾病寿元", ["疾病", "寿元", "夭折", "伤残", "寿夭", "病", "亡"]),
    ("命书体例", ["命書", "命书", "批导", "体例", "行文", "交付", "细批", "简批", "大批", "中批", "小批"]),
    ("术语考据", ["术语", "考据", "书名", "玉照", "滴天髓", "栏江", "三命通会", "神峯", "子平真诠"]),
    ("十神", ["比肩", "劫财", "食神", "伤官", "正财", "偏财", "正官", "七杀", "正印", "偏印",
              "十神", "定位", "取象", "变德"]),
]
TOPIC_FALLBACK = "实务杂项"
TOPIC_SET = {t for t, _ in TOPICS} | {TOPIC_FALLBACK}

TEN_GODS = ["正官", "七杀", "正财", "偏财", "正印", "偏印",
            "食神", "伤官", "比肩", "劫财", "羊刃", "禄神"]


# 书名级硬规则：theme 形如「金不换·甲日主」「沈氏·取格」，先按书与段定类
HARD = [
    (r"·[" + STEM + r"]日主", "用神"),        # 十日主诗註＝日主在各月的喜忌
    (r"金不换·(五家散論|读法|命書體例)", "体例次第"),
    (r"金不换·大運批導", "命书体例"),
    (r"金不换·別法", "十神"),
    (r"沈氏·", "格局"),
]


def classify_topic(theme, rule_text=""):
    """硬规则 → theme 关键词 → rule_text 前 40 字 → 女命兜底 → 杂项。"""
    for pat, name in HARD:
        if re.search(pat, theme):
            return name
    for name, kws in TOPICS:
        for k in kws:
            if k in theme:
                return name
    head = (rule_text or "")[:40]
    for name, kws in TOPICS:
        for k in kws:
            if k in head:
                return name
    if "女命" in theme or "女命" in head:
        return "婚姻女命"
    return TOPIC_FALLBACK


def _strip_prefix(cond):
    return re.sub(r"^\[(可算|待人工)\]\s*", "", cond or "").strip()


def extract_tags(cond):
    """从 conditions 抽触发要素。抽不到返回空集——不猜。"""
    c = _strip_prefix(cond)
    t = set()
    if not c:
        return t
    if "恒真" in c:
        t.add("恒真")
    # 性别不抽成触发标签：它已由 rules.csv 的 scope 字段承担，
    # 若再抽成标签，则女命专章 193 条会因「性别:女」而无条件全部命中。

    # 月支
    for g in re.findall(r"月支\s*[∈=＝]\s*\{([^}]*)\}", c):
        for ch in re.findall("[" + BRANCH + "]", g):
            t.add("月:" + ch)
    for g in re.findall(r"月支\s*[∈=＝]\s*([" + BRANCH + r"]{1,3})", c):
        for ch in g:
            t.add("月:" + ch)
    for g in re.findall(r"生[于月]?\s*([" + BRANCH + r"]{1,3})\s*月", c):
        for ch in g:
            t.add("月:" + ch)
    for g in re.findall(r"月令(?:为|是|在)?\s*([" + BRANCH + "])", c):
        t.add("月:" + g)
    for g in re.findall(r"生月(?:为|是)?\s*([" + BRANCH + "])", c):
        t.add("月:" + g)
    for g in re.findall(r"四柱(?:地支)?见([" + BRANCH + r"]{2,4})", c):
        for ch in g:
            t.add("支:" + ch)

    # 日主
    for g in re.findall(r"日主\s*[∈=＝]\s*\{([^}]*)\}", c):
        for ch in re.findall("[" + STEM + "]", g):
            t.add("日主:" + ch)
    for g in re.findall(r"日主\s*(?:为|是)\s*([" + STEM + "])", c):
        t.add("日主:" + g)
    for g in re.findall(r"([" + STEM + "])日主", c):
        t.add("日主:" + g)
    for g in re.findall(r"日干\s*[＝=]\s*([" + STEM + "])", c):
        t.add("日主:" + g)

    # 十神
    for x in TEN_GODS:
        if x in c:
            t.add("十神:" + x)
    if "日主同干" in c:
        t.add("十神:比肩")

    # 五行缺
    if re.search(r"五行有?缺|缺一|缺行|不见[金木水火土]", c):
        t.add("五行缺")

    # 关系
    for k in ("冲", "合", "会", "刑", "害", "拱", "夹"):
        if k in c:
            t.add("关系:" + k)

    # 根气
    if re.search(r"无根|根气|根重|根深|有根|坐禄|通根", c):
        t.add("根气")

    # 时序
    if "大运" in c or "运支" in c or "运干" in c or "行运" in c:
        t.add("大运")
    if "流年" in c:
        t.add("流年")
    if "流月" in c:
        t.add("流月")

    # 前置判断
    if re.search(r"格(局)?(已|为|成|定)|成格|已立", c):
        t.add("格局")
    if "调候" in c:
        t.add("调候")
    return t


def load_rules():
    with io.open(os.path.join(DATA, "rules.csv"), encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        return rd.fieldnames, list(rd)


def dump_stat(rows):
    tp = Counter(classify_topic(r["theme"], r.get("rule_text", "")) for r in rows)
    tagc = Counter()
    na, manual = [], []
    for r in rows:
        auto = extract_tags(r["conditions"])
        stored = [x for x in (r.get("trigger_tags") or "").split("|") if x]
        # 已落库的 trigger_tags 优先：conditions 抽不出而人工标了的（如「月令六神受某干克」
        # 这类句式），不得因为自动抽不出就计入「未结构化」。
        t = stored or auto
        if stored and not auto:
            manual.append(r["rule_id"])
        if not t:
            na.append(r["rule_id"])
        for x in t:
            tagc[x.split(":")[0]] += 1
    print("规则总数", len(rows))
    print("\n[topic 分布]")
    for k, v in tp.most_common():
        print("  %-8s %4d" % (k, v))
    print("\n[触发标签维度覆盖]")
    for k, v in tagc.most_common():
        print("  %-6s %4d" % (k, v))
    print("\nconditions 可自动抽 %d 条；其中 %d 条由人工标注补入（%s）"
          % (len(rows) - len(na) - len(manual), len(manual),
             "、".join(manual) if manual else "无"))
    print("无标签 %d 条（%.1f%%），归入「条件未结构化」" % (len(na), 100.0 * len(na) / len(rows)))
    return na


def write_index(rows):
    """按 topic 出索引：14 节，每节列规则 ID／theme／证据／状态／触发标签。"""
    out = [u"# 规则索引·按主题（topic）", "",
           u"> 由 `tools/rule_tags.py --index` 生成。topic 是受控词表（14 类），"
           u"由 theme 关键词映射而来；theme 保留原标题，775 条有 774 个 theme，按 theme 索引等于一条一节。",
           u"> 触发标签（trigger_tags）是从 conditions 抽出的判据要素，空者表示 conditions 未结构化。", ""]
    order = [t for t, _ in TOPICS] + [TOPIC_FALLBACK]
    groups = {}
    for r in rows:
        groups.setdefault(r["topic"], []).append(r)
    out.append(u"| 主题 | 条数 |")
    out.append(u"|---|---:|")
    for t in order:
        if t in groups:
            out.append(u"| %s | %d |" % (t, len(groups[t])))
    out.append(u"| **合计** | **%d** |" % len(rows))
    out.append("")
    for t in order:
        if t not in groups:
            continue
        out.append(u"## %s（%d 条）" % (t, len(groups[t])))
        out.append("")
        for r in sorted(groups[t], key=lambda x: x["rule_id"]):
            tg = r["trigger_tags"] or u"—（未结构化）"
            out.append(u"- **%s**｜%s｜%s／%s｜%s" % (
                r["rule_id"], r["theme"], r["verification_status"],
                r["evidence_grade"].split("_")[0], tg))
        out.append("")
    path = os.path.join(ROOT, "references", "rules", "index_by_topic.md")
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(out) + "\r\n")
    print("已生成 references/rules/index_by_topic.md（%d 条，%d 节）" % (len(rows), len(groups)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stat", action="store_true")
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--list", choices=["NA"], help="列出无触发标签的规则")
    a = ap.parse_args()

    fields, rows = load_rules()
    na = dump_stat(rows)

    if a.list == "NA":
        for r in rows:
            if r["rule_id"] in na:
                print("%-10s %-28s %s" % (r["rule_id"], r["theme"][:26],
                                          _strip_prefix(r["conditions"])[:60]))
    if a.index:
        for r in rows:
            r["topic"] = r.get("topic") or classify_topic(r["theme"], r.get("rule_text", ""))
            r["trigger_tags"] = r.get("trigger_tags") if "trigger_tags" in r else ""
        write_index(rows)
    if not a.update:
        return

    for c in ("topic", "trigger_tags"):
        if c not in fields:
            fields = fields + [c]
    for r in rows:
        r["topic"] = classify_topic(r["theme"], r.get("rule_text", ""))
        r["trigger_tags"] = "|".join(sorted(extract_tags(r["conditions"])))
    out = os.path.join(DATA, "rules.csv")
    with io.open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)
    print("\n已写回 rules.csv（新增列：topic／trigger_tags）")


if __name__ == "__main__":
    main()
