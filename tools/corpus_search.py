#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""corpus_search.py —— 跨书引文检索。

为什么要有这个：本包所有断语都要求「可回查」。规则表里写了 XC:p041，
读者就要能一秒钟翻到那一处引文。没有检索器，引文库只是躺在 data/ 里的死文件。

**检索的是「引文核验库」，不是原书全文。**
`data/quotes_verify.txt` 只收被规则引用之处及其邻近上下文（由 `_dev/distill_corpus.py`
从原书机械抽取，未改一字），未被任何规则引用的页不留一字。故：

  命中了  → 直接给你原文片段，这就是「引文可回查」。
  没命中  → 不代表书里没有，只代表**本包没引过**。此时用 `--digest 词` 查页级索引，
            它会告诉你在哪本书哪几页讨论过这个词（只给页号，不给正文）——
            要读原文，请翻原书。

这个区分是本包的法律边界：给的是**引文**与**指路**，不是原书的替代阅读件。

用法：
    python tools/corpus_search.py 四角方阵
    python tools/corpus_search.py 天乙贵人 --book XC
    python tools/corpus_search.py "三刑.*自刑" --re --ctx 2
    python tools/corpus_search.py --digest 羊刃        # 只查页级索引，给页号指路
    python tools/corpus_search.py --list

输出每行一条命中：书号:页  locator  片段
locator 形如 XC:p041，可直接抄进 rules.csv 的 source_locator。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

# 控制台编码：Windows 中文环境默认 cp936，原文含大量 GBK 之外的字（如 ✅、—、□），
# 不改编码会在打印第一条命中时崩。见 paipan.py 同段说明。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VERIFY = DATA / "quotes_verify.txt"
DIGEST = DATA / "corpus_digest.csv"

# 书号 → 书名。与 data/corpus_manifest.csv、references/corpus/INDEX.md 三处对齐。
BOOKS = {
    "XC": "《四角方阵刑冲合会透解》",
    "NV": "《女命详解附女命通会》",
    "DC": "《命学大辞渊》",
    "JC": "《子平基础概要》",
    "MF": "《子平母法—大流年判例》",
    "XP": "《细批终身详解》",
    "SS": "《沈氏用神例解》",
    "JB": "《金不换大运详解》",
    "YH": "《渊海喜忌随笔》",
    "SZ": "《命理实战》",
    "ZG": "《宰公要诀》",
    "SP": "《神煞探源》",
}

# 行锚书：定位单位是行号（SZ:Lnnn），不是页码。
LINE_BOOKS = {"SZ"}

# 在架但未数字化的（无 OCR 引擎，只有扫描件）——检索时应明确告知，而不是静默无结果
NOT_DIGITIZED = [
    ("ML", "《命略本纪》上/下册", "扫描件", 370),
]


def load_book(bid: str) -> list[tuple[int, str]]:
    """从核验库取某书段落 → [(页号或行号, 正文)]；段内无页标则按行切（行锚书）。"""
    if not VERIFY.exists():
        return []
    txt = VERIFY.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?m)^#####\s*([A-Z]{2})\s*\|", txt)
    body = None
    for i in range(1, len(blocks) - 1, 2):
        if blocks[i] == bid:
            body = blocks[i + 1]
            break
    if body is None:
        return []
    marks = list(re.finditer(r"(?m)^===== p(\d{1,4}) =====$", body))
    if marks:
        out = []
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
            seg = body[m.end():end].strip("\n")
            if seg.strip():
                out.append((int(m.group(1)), seg))
        return out
    # 行锚书：行号即 locator，空行是占位（保持行号不漂移），跳过但不打乱计数
    return [(i + 1, ln) for i, ln in enumerate(body.split("\n")) if ln.strip()]


def snippet(body: str, pos: int, width: int = 46) -> str:
    s = max(0, pos - width)
    e = min(len(body), pos + width)
    t = body[s:e].replace("\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return ("…" if s > 0 else "") + t + ("…" if e < len(body) else "")


def search(term: str, books: list[str], is_re: bool, limit: int):
    pat = re.compile(term if is_re else re.escape(term))
    hits = []
    for bid in books:
        for no, body in load_book(bid):
            for m in pat.finditer(body):
                hits.append((bid, no, snippet(body, m.start())))
                if len(hits) >= limit:
                    return hits
    return hits


def digest(term: str, books: list[str], limit: int):
    """页级索引检索：只给「哪本书、哪几页」，不给正文。"""
    if not DIGEST.exists():
        return []
    out = []
    for r in csv.DictReader(DIGEST.open(encoding="utf-8-sig")):
        if books and r["book"] not in books:
            continue
        if term in (r.get("terms") or ""):
            out.append(r)
            if len(out) >= limit:
                break
    return out


def stat():
    """每书：核验库收录页数 / 原书页数、收录字数。"""
    rows = []
    if not DIGEST.exists():
        return rows
    agg = {}
    for r in csv.DictReader(DIGEST.open(encoding="utf-8-sig")):
        b = r["book"]
        a = agg.setdefault(b, {"pages": 0, "cited": 0, "kept": 0, "orig": 0})
        a["pages"] += 1
        a["kept"] += int(r["kept_chars"] or 0)
        a["orig"] += int(r["orig_chars"] or 0)
        if r["cited"] == "yes":
            a["cited"] += 1
    for b in BOOKS:
        if b in agg:
            rows.append((b, BOOKS[b], agg[b]["pages"], agg[b]["cited"],
                         agg[b]["kept"], agg[b]["orig"]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="跨书引文检索（检索对象为引文核验库）")
    ap.add_argument("term", nargs="?", help="检索词或正则")
    ap.add_argument("--book", action="append", default=[],
                    help="限定书号，可重复：--book XC --book NV")
    ap.add_argument("--re", action="store_true", help="按正则解释检索词")
    ap.add_argument("--ctx", type=int, default=0, help="额外上下文行数（暂留）")
    ap.add_argument("--limit", type=int, default=20, help="最多命中数，默认 20")
    ap.add_argument("--digest", action="store_true", help="改查页级索引：只回页号，不回正文")
    ap.add_argument("--list", action="store_true", help="列出可检索书目与收录情况")
    args = ap.parse_args()

    if args.list:
        print("可检索（引文核验库）：")
        print("  %-4s %-26s %8s %8s %10s" % ("书号", "书名", "收录页", "被引页", "收录字数"))
        for b, t, pg, cd, kept, orig in stat():
            print("  %-4s %-26s %8d %8d %10d" % (b, t[:24], pg, cd, kept))
        print("\n在架未数字化（需 OCR 引擎，本机缺）：")
        for bid, title, src, pages in NOT_DIGITIZED:
            print(f"  {bid}  {title:<26} {pages:>4} 页  扫描件，未入库")
        print("\n提示：locator 写法为 书号:p页码（行锚书为 书号:L行号），例如 XC:p041、SZ:L53。")
        print("      核验库只收被规则引用之处；未被引的页，用 --digest 查页号后翻原书。")
        return 0

    if not args.term:
        ap.print_help()
        return 2

    books = args.book or list(BOOKS)
    bad = [b for b in books if b not in BOOKS]
    if bad:
        print(f"未知书号：{','.join(bad)}；用 --list 看书号", file=sys.stderr)
        return 2

    if args.digest:
        rows = digest(args.term, books, args.limit)
        if not rows:
            print(f"「{args.term}」不在页级索引中。")
            return 1
        for r in rows:
            print("%s:p%03d  %s  该页 %s 字，核验库收 %s 字%s"
                  % (r["book"], int(r["page"]), r["title"][:20],
                     r["orig_chars"], r["kept_chars"],
                     "" if r["cited"] == "yes" else "（本包未引此页，仅指路）"))
        print(f"\n共 {len(rows)} 页。此为索引，不含正文；要读原文请翻原书。")
        return 0

    hits = search(args.term, books, args.re, args.limit)
    if not hits:
        print(f"「{args.term}」在核验库的 {len(books)} 本书中无命中。")
        print("这不等于书里没有——核验库只收被规则引用之处。"
              "可试 `--digest %s` 查页级索引。" % args.term)
        return 1
    for bid, no, snip in hits:
        loc = "%s:L%d" % (bid, no) if bid in LINE_BOOKS else "%s:p%03d" % (bid, no)
        print("%-9s %-22s %s" % (loc, BOOKS[bid], snip))
    print(f"\n共 {len(hits)} 条命中（上限 {args.limit}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
