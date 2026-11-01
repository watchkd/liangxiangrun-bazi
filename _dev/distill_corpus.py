#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""distill_corpus.py —— 把逐页全文蒸馏成「引文核验库」。

为什么要有这一步
----------------
原包 `data/*_fulltext.txt` 是十七本书的**逐页连续全文**，合计 4.5 MB。它让「断语可回查」
成立，但也带来一个法律问题：整本书随包分发，等于提供原书的替代阅读件。加免责声明盖不住——
声明里写着「不构成原书替代阅读」，而包里正躺着可以替代阅读的东西，这句话就是空的。

蒸馏的口径（不是删，是缩到「只够核验」）
--------------------------------------
一句话：**只留被引用处，加一层上下文窗口；页号与行号一律不动。**

  页锚书（MF/XP/SS/JB/YH/JC/SZ 之外的六本）
      页号 `===== pNNN =====` 原样保留，页内只留每个被引句前后各 ±W 字符的片段，
      同一页的多条引文窗口合并。未含任何引文的页，整页清空（页标仍在）。

  行锚书（SZ）
      行号即定位，故**行数不动**：被引行区间保留原文，其余行替换为空行。
      这样 `lines[a-1:b]` 切片仍逐字等于原引文，C10 的行锚校验不受影响。

  未被任何规则引用的书
      整本不入包（DC／XC／NV 等仅零星引用者，只留被引页）。

产物
----
  data/quotes_verify.txt   引文核验库（多书并置，各书页标独立编号，以 `##### BOOK #####` 分隔）
  data/corpus_digest.csv   页级索引：书号、页号、该页术语、字数、是否被引

校验口径随之改：C10 由「引文能在全书中找到」变为「引文能在核验库中找到」。
**这不降低标准**——核验库是从原书机械抽取的，未改一字；只是不再把整本书带着走。

用法
----
    python _dev/distill_corpus.py --report          # 只统计，不落盘
    python _dev/distill_corpus.py --write           # 生成核验库与索引
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

W = 130          # 每条引文前后保留的上下文字符数（C10 实校之书）
W_TIGHT = 40     # 仅作追溯、C10 不校之书：只留引文近旁

# C10（引文保真）实际校验的七本——它们的窗口必须够宽，否则引文被切、校验当场响。
# 其余书只作「读者想追一句时能查到页」之用，留窄窗即可。
C10_BOOKS = {"MF", "XP", "SS", "JB", "YH", "JC", "SZ"}
BOOKS = {        # 书号 → (全文文件, 书名, 定位模式)
    "XC": ("xc_fulltext.txt", "四角方阵刑冲合会透解", "pages"),
    "NV": ("nv_fulltext.txt", "女命详解附女命通会", "pages"),
    "DC": ("dc_fulltext.txt", "命学大辞渊", "pages"),
    "JC": ("jichu_fulltext.txt", "子平基础概要", "pages"),
    "MF": ("mufa_fulltext.txt", "子平母法—大流年判例", "pages"),
    "XP": ("xipi_fulltext.txt", "细批终身详解", "pages"),
    "SS": ("shenshi_fulltext.txt", "沈氏用神例解", "pages"),
    "JB": ("jinbuhuan_fulltext.txt", "金不换大运详解", "pages"),
    "YH": ("yuanhai_fulltext.txt", "渊海喜忌随笔", "pages"),
    "SZ": ("shizhan_fulltext.txt", "命理实战", "lines"),
    "ZG": ("zg_fulltext.txt", "宰公要诀", "pages"),
    "SP": ("sp_fulltext.txt", "神煞探源", "pages"),  # 锚为 sNN 章节号，见下
}

# 术语表：用于给每页打标签（检索时按术语回落到页）
TERMS = [
    "天乙贵人", "太极贵人", "天德", "月德", "文昌", "国印", "将星", "华盖", "驿马", "桃花",
    "羊刃", "禄神", "空亡", "旬空", "纳音", "孤辰", "寡宿", "红艳", "金舆", "天罗地网",
    "正官", "七杀", "正财", "偏财", "食神", "伤官", "正印", "偏印", "比肩", "劫财",
    "月令", "格局", "用神", "喜忌", "调候", "通关", "扶抑", "病药", "专旺", "从格",
    "大运", "流年", "小限", "太岁", "起运", "交运", "胎元", "命宫", "身宫",
    "三合", "三会", "六合", "六冲", "三刑", "自刑", "相害", "半合", "拱合",
    "女命", "夫妻", "子女", "父母", "兄弟", "六亲", "寿元", "疾病", "财官",
]


# 页脚水印：原电子本（扫描／转换本）每页都压了一行来源标记。
# 它不是原文，留着有两个坏处：一是把「来源为网络转售件」写在脸上，
# 二是检索命中时混进片段里，读者以为那是梁氏的话。蒸馏时一并剔掉。
WATERMARK = [
    r"来自闲鱼十年打渔",
    r"〔?本电子书由[^〕\n]{0,30}〔?",
]


def strip_marks(t):
    n = 0
    for pat in WATERMARK:
        t, k = re.subn(pat, "", t)
        n += k
    return t, n


def squeeze(s):
    return re.sub(r"\s+", "", s or "")


PAGE_RE = re.compile(r"^=====\s*([ps])(\d+)\s*=====$")


def load_pages(path):
    """`===== pNNN =====`／`===== sNN =====` 切块 → {页号: [行]}；无标则整篇作 1。"""
    pages, cur = {}, None
    for line in io.open(path, encoding="utf-8", errors="replace").read().split("\n"):
        m = PAGE_RE.match(line.strip())
        if m:
            cur = int(m.group(2))
            pages[cur] = []
        elif cur is not None:
            pages[cur].append(line)
    if not pages:
        pages[1] = io.open(path, encoding="utf-8", errors="replace").read().split("\n")
    return pages


def load_rules():
    return list(csv.DictReader(io.open(os.path.join(DATA, "rules.csv"), encoding="utf-8-sig")))


def collect(rules, cases=()):
    """规则＋判例 → {书号: {页号: [待覆盖引文]}} 与 {书号: set(被引行号)}。

    判例的 known_facts／liang_judgment 也要落在页内（C10 后半段），故一并纳入窗口计算；
    漏了这两列，蒸馏出来的库过不了 C10。
    """
    by_page = collections.defaultdict(lambda: collections.defaultdict(list))
    by_line = collections.defaultdict(set)
    cross = collections.defaultdict(set)   # 跨页 locator 涉及的页：一律整页留，裁剪必断
    missed = []
    for r in list(rules) + list(cases):
        loc = (r.get("source_locator") or "").strip()
        m = re.match(r"^([A-Z]{2}):p(\d+)(?:-(\d+))?$", loc)
        if m:
            b, a, z = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
            if b in BOOKS:
                txts = [r.get("rule_text") or r.get("known_facts") or "",
                        r.get("known_facts") or "", r.get("liang_judgment") or ""]
                if a != z:
                    cross[b].update(range(a, z + 1))
                for p in range(a, z + 1):
                    by_page[b][p].extend(t for t in txts if t.strip())
            continue
        m = re.match(r"^[A-Z]{2}:s(\d+)$", loc)          # 章节锚（SP:s18）
        if m:
            b = loc.split(":")[0]
            if b in BOOKS:
                by_page[b][int(m.group(1))].append(r["rule_text"])
            continue
        m = re.match(r"^SZ:L([\d,\-L]+)$", loc)
        if m:
            for part in m.group(1).split(","):
                mm = re.match(r"^L?(\d+)(?:-L?(\d+))?$", part.strip())
                if mm:
                    a = int(mm.group(1)); z = int(mm.group(2) or mm.group(1))
                    by_line["SZ"].update(range(a, z + 1))
            continue
        if loc:
            missed.append((r.get("rule_id") or r.get("case_id"), loc))
    return by_page, by_line, cross, missed


def window_of(page_text, quotes, w=W):
    """在一页里定位所有引文，取 ±w 窗口并合并 → 保留区间列表。"""
    flat = squeeze(page_text)
    idx = []
    for q in quotes:
        qs = squeeze(q)
        if len(qs) < 6:
            continue
        i = flat.find(qs)
        if i < 0:                       # 引文含省略号或经整理，退化为前八字定位
            i = flat.find(qs[:8]) if len(qs) >= 8 else -1
        if i >= 0:
            idx.append((max(0, i - w), min(len(flat), i + len(qs) + w)))
    if not idx:
        return None, False
    idx.sort()
    merged = [list(idx[0])]
    for a, b in idx[1:]:
        if a <= merged[-1][1] + 40:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged, True


def distill(report_only=False, w=W):
    rules = load_rules()
    cases = list(csv.DictReader(io.open(os.path.join(DATA, "cases.csv"), encoding="utf-8-sig")))
    by_page, by_line, cross, missed = collect(rules, cases)
    out_parts, digest = [], []
    stat = []
    n_wm = 0

    for bid, (fname, title, mode) in BOOKS.items():
        path = os.path.join(DATA, fname)
        if not os.path.exists(path):
            stat.append((bid, title, 0, 0, 0, "缺文件"))
            continue
        if mode == "lines":
            lines = io.open(path, encoding="utf-8", errors="replace").read().split("\n")
            keep = by_line.get(bid, set())
            kept = [l if (i + 1) in keep else "" for i, l in enumerate(lines)]
            body = "\n".join(kept)
            orig = len(squeeze("\n".join(lines)))
            new = len(squeeze(body))
            out_parts.append("##### %s | %s | lines | keep=%d/%d #####" %
                             (bid, title, len(keep), len(lines)))
            out_parts.append(body)
            digest.append({
                "book": bid, "page": 0, "title": title,
                "terms": "、".join(sorted({t for t in TERMS if t in body})),
                "quote_n": len(keep), "orig_chars": orig,
                "kept_chars": new, "cited": "yes",
            })
            stat.append((bid, title, 0, orig, new, "行锚 %d 行" % len(keep)))
            continue

        pages = load_pages(path)
        want = by_page.get(bid, {})
        kept_pages = 0
        chunks = []
        for pno in sorted(pages):
            raw, wm = strip_marks("\n".join(pages[pno]))
            n_wm += wm
            orig = len(squeeze(raw))
            if pno in want:
                # 跨页引文（MF:p197-198）天然无法单页裁剪：任何窗口都会把中间那段删掉，
                # 而 C10 是把两页拼起来比对的。故跨页所涉之页一律整页留。
                if pno in cross.get(bid, ()):
                    kept_pages += 1
                    chunks.append("===== p%d =====\n%s" % (pno, squeeze(raw)))
                    digest.append({
                        "book": bid, "page": pno, "title": title,
                        "terms": "、".join(sorted({t for t in TERMS if t in raw})),
                        "quote_n": len(want[pno]), "orig_chars": orig,
                        "kept_chars": orig, "cited": "yes",
                    })
                    continue
                merged, ok = window_of(raw, want[pno], w if bid in C10_BOOKS else min(w, W_TIGHT))
                if ok:
                    kept_pages += 1
                    seg = "\n⋯\n".join(squeeze(raw)[a:b] for a, b in merged)
                    chunks.append("===== p%d =====\n%s" % (pno, seg))
                    digest.append({
                        "book": bid, "page": pno, "title": title,
                        "terms": "、".join(sorted({t for t in TERMS if t in raw})),
                        "quote_n": len(want[pno]), "orig_chars": orig,
                        "kept_chars": len(squeeze(seg)), "cited": "yes",
                    })
                    continue
                # 保险丝：一条引文都定位不到（跨页断开、含省略号、异体字），
                # 说明裁剪会切掉证据。此处**整页原样保留**——宁可多留一页，
                # 不可让「引文能在原文中找到」这句断言变成假的。
                kept_pages += 1
                chunks.append("===== p%d =====\n%s" % (pno, squeeze(raw)))
                digest.append({
                    "book": bid, "page": pno, "title": title,
                    "terms": "、".join(sorted({t for t in TERMS if t in raw})),
                    "quote_n": len(want[pno]), "orig_chars": orig,
                    "kept_chars": orig, "cited": "yes",
                })
                continue
            # 未被引：页标保留、内容清空（页号连续性不能断，locator 靠它）
            chunks.append("===== p%d =====" % pno)
            digest.append({
                "book": bid, "page": pno, "title": title,
                "terms": "、".join(sorted({t for t in TERMS if t in raw})),
                "quote_n": 0, "orig_chars": orig, "kept_chars": 0, "cited": "no",
            })
        body = "\n".join(chunks)
        orig_total = sum(len(squeeze("\n".join(v))) for v in pages.values())
        new_total = len(squeeze(body))
        out_parts.append("##### %s | %s | pages | keep=%d/%d #####" %
                         (bid, title, kept_pages, len(pages)))
        out_parts.append(body)
        stat.append((bid, title, kept_pages, orig_total, new_total,
                     "页锚 %d/%d 页" % (kept_pages, len(pages))))

    blob = "\n".join(out_parts)
    if report_only:
        return stat, digest, blob, missed, n_wm
    with io.open(os.path.join(DATA, "quotes_verify.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(blob)
    with io.open(os.path.join(DATA, "corpus_digest.csv"), "w", encoding="utf-8-sig", newline="") as f:
        wri = csv.DictWriter(f, fieldnames=["book", "page", "title", "terms", "quote_n",
                                            "orig_chars", "kept_chars", "cited"])
        wri.writeheader()
        wri.writerows(digest)
    return stat, digest, blob, missed, n_wm


def main():
    ap = argparse.ArgumentParser(description="把逐页全文蒸馏为引文核验库")
    ap.add_argument("--report", action="store_true", help="只统计，不落盘")
    ap.add_argument("--write", action="store_true", help="生成 quotes_verify.txt 与 corpus_digest.csv")
    ap.add_argument("--window", type=int, default=W, help="上下文窗口字符数（默认 %d）" % W)
    a = ap.parse_args()
    if not (a.report or a.write):
        ap.error("须给 --report 或 --write")

    stat, digest, blob, missed, n_wm = distill(not a.write, a.window)
    to = tn = 0
    print("%-4s %-24s %-12s %10s %10s %6s" % ("书", "书名", "保留", "原字数", "留字数", "占比"))
    for bid, title, kp, o, n, note in stat:
        to += o; tn += n
        pct = ("%.1f%%" % (100.0 * n / o)) if o else "—"
        print("%-4s %-24s %-12s %10d %10d %6s" % (bid, title[:22], note, o, n, pct))
    print("-" * 74)
    print("%-4s %-24s %-12s %10d %10d %6s" % ("合计", "", "", to, tn,
                                              "%.1f%%" % (100.0 * tn / to) if to else "—"))
    print("核验库体积：%.2f MB → %.2f MB" % (to * 3 / 1048576.0, len(blob.encode("utf-8")) / 1048576.0))
    print("清除页脚水印 %d 处（「来自闲鱼十年打渔」一类来源标记，非原文）" % n_wm)
    if missed:
        print("\nlocator 非页锚/行锚、未纳入者 %d 条（多为字幕与表锚）：" % len(missed))
        for rid, loc in missed[:6]:
            print("   ", rid, loc)
    if a.write:
        print("\n已写：data/quotes_verify.txt（%d 页索引）、data/corpus_digest.csv" % len(digest))


if __name__ == "__main__":
    main()
