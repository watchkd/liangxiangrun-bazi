#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把分批转录的扫描件片段合并成一份带页锚的全文，并做完整性验收。

扫描件没有文字层，全文靠逐页读图转录。转录是大工程，必须分批做（一批一个
子代理、一个 part 文件）。分批的代价是：漏页、重页、页号写错、页里留空——
这些错在几百页里靠人眼看是看不出来的，所以合并必须由程序做，且必须先把
问题报出来再合并，不允许「先合了再说」。

用法：
    python tools/corpus_merge_parts.py --check  parts/*.txt
    python tools/corpus_merge_parts.py --merge  parts/*.txt -o data/xx_fulltext.txt \
        --book ZG --title "《宰公要诀》梁湘润（行卯版）" --expect 124

页锚格式与包内其余全文一致：`===== pNNN =====`（三位，不足补零）。
下册接着上册编号，不重头来过——否则检索器会把两册的同号页混成一处。
"""
import argparse
import glob
import os
import re
import sys

PAGE_RE = re.compile(r"^=====\s*p(\d{1,4})\s*=====\s*$", re.M)
# 页内正文允许的字符：中日韩、标点、数字、字母、常见符号（含制表符换行）
CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")

MIN_CHARS = 40          # 一页正文低于这个字数，判为可疑（多半是空白页或转录失败）
MAX_CHARS = 4000        # 双页拼版的单页极少超过这个数，超了多半是页界写错


def split_pages(text):
    """把文本切成 [(页号, 正文)]。第一个页锚之前的内容单独返回。"""
    marks = list(PAGE_RE.finditer(text))
    if not marks:
        return [], text
    head = text[:marks[0].start()]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((int(m.group(1)), text[m.end():end]))
    return out, head


def load(paths):
    """读入所有片段，返回 {页号: [(正文, 来源文件)]}，同页多来源即冲突。"""
    pages = {}
    order = []
    for p in paths:
        raw = open(p, encoding="utf-8-sig").read()
        items, head = split_pages(raw)
        if not items:
            print(f"  [!] {os.path.basename(p)} 无页锚，整份被忽略")
            continue
        for num, body in items:
            pages.setdefault(num, []).append((body, os.path.basename(p)))
            if num not in order:
                order.append(num)
    return pages, order


def check(paths, expect, quiet=False):
    pages, order = load(paths)
    if not pages:
        print("FAIL 没有可用的页")
        return False, {}

    nums = sorted(pages)
    dup = [n for n in nums if len(pages[n]) > 1]
    gaps = []
    for a, b in zip(nums, nums[1:]):
        if b - a > 1:
            gaps.extend(range(a + 1, b))

    thin, fat = [], []
    for n in nums:
        body = pages[n][0][0]
        cjk = len(CJK.findall(body))
        if cjk < MIN_CHARS:
            thin.append((n, cjk))
        elif cjk > MAX_CHARS:
            fat.append((n, cjk))

    ok = True
    print(f"页数：{len(nums)}  范围：p{min(nums):03d}–p{max(nums):03d}")
    if dup:
        ok = False
        print(f"FAIL 重复页 {len(dup)} 页：{[f'p{n:03d}' for n in dup[:20]]}")
        for n in dup[:5]:
            srcs = "；".join(s for _, s in pages[n])
            print(f"      p{n:03d} 出现于：{srcs}")
    if gaps:
        ok = False
        print(f"FAIL 缺页 {len(gaps)} 页：{[f'p{n:03d}' for n in gaps[:30]]}")
    if expect:
        missing = [n for n in range(1, expect + 1) if n not in pages]
        extra = [n for n in nums if n > expect]
        if missing:
            ok = False
            print(f"FAIL 与应有页数 {expect} 比，缺 {len(missing)} 页："
                  f"{[f'p{n:03d}' for n in missing[:30]]}")
        if extra:
            ok = False
            print(f"FAIL 超出应有页数 {expect} 的页：{[f'p{n:03d}' for n in extra[:20]]}")
    if thin:
        print(f"WARN 正文少于 {MIN_CHARS} 字的页 {len(thin)} 页（须确认是空白页还是转录失败）：")
        for n, c in thin:
            print(f"      p{n:03d} {c} 字  ← {pages[n][0][1]}")
    if fat:
        print(f"WARN 正文超过 {MAX_CHARS} 字的页 {len(fat)} 页（须确认页界是否写错）：")
        for n, c in fat:
            print(f"      p{n:03d} {c} 字")
    if not quiet:
        total = sum(len(CJK.findall(pages[n][0][0])) for n in nums)
        print(f"正文汉字合计：{total:,}")
    return ok, pages


def merge(pages, out, book, title, source, expect):
    nums = sorted(pages)
    lines = [
        f"# {title}",
        "> 全书逐页转录（扫描无文字层，靠读图逐字转录；无 OCR 引擎可用）。",
        "> 页锚 `===== pNNN =====` 为 PDF 页序，不是书上的印刷页码；",
        ">   印刷页码与 PDF 页序的对应见 `data/{0}_toc.csv`。".format(book.lower()),
        "> 纪律：照录原文，不校勘、不改字、不补字、不删重；辨认不出用 □。",
        ">   原文为繁体竖排，本文件保留繁体字形，未作简繁转换。",
        f"> 来源：{source}",
        f"> 页数：{len(nums)}" + (f"（应有 {expect}）" if expect else ""),
        "",
    ]
    for n in nums:
        body = pages[n][0][0].strip("\n")
        # 统一页内首尾空行，保留页内原样（含原书分栏留下的换行）
        lines.append(f"===== p{n:03d} =====")
        lines.append(body.rstrip())
        lines.append("")
    text = "\n".join(lines)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w", encoding="utf-8").write(text)
    return len(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parts", nargs="+", help="转录片段文件（可含通配符）")
    ap.add_argument("--merge", action="store_true", help="校验通过后合并写出")
    ap.add_argument("--check", action="store_true", help="只校验不写")
    ap.add_argument("-o", "--out")
    ap.add_argument("--book", default="XX", help="书号，用于指向 toc 表")
    ap.add_argument("--title", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--expect", type=int, default=0, help="应有总页数")
    args = ap.parse_args()

    paths = []
    for pat in args.parts:
        paths.extend(sorted(glob.glob(pat)) or ([pat] if os.path.exists(pat) else []))
    if not paths:
        print("FAIL 没有找到任何片段文件")
        return 1
    print(f"片段 {len(paths)} 个：")
    for p in paths:
        print(f"  {os.path.basename(p)}  {os.path.getsize(p):>8,} B")

    ok, pages = check(paths, args.expect)
    if args.merge:
        if not ok:
            print("\n拒绝合并：先修上面的 FAIL。")
            return 2
        if not args.out:
            print("FAIL --merge 需要 -o")
            return 2
        n = merge(pages, args.out, args.book, args.title, args.source, args.expect)
        print(f"\n已写出 {args.out}（{n:,} 字符）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
