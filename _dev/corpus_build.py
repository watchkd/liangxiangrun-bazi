#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""corpus_build.py —— 把语料库原文规范为包内可查的全文件。

用途：G-05「六本书未抽」的地基。原文先进包、再谈抽规则，
否则规则写了也无处回查。

规范格式与包内既有全文件一致：
    ===== p001 =====
    正文……

只做三件事：定位页界、去页眉页脚噪声、写 corpus_manifest.csv 登记。
不改字、不校勘、不做繁简转换——原文什么样就什么样，
校勘是另一条线（data/ocr_corrections.csv），不在这里混。

用法：
    python tools/corpus_build.py --build      # 生成 data/*_fulltext.txt
    python tools/corpus_build.py --check      # 只核对现有全文件页数
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CORPUS = Path("D:/梁湘润/_语料库")

# book_id, 前缀, 书名, 源文件, 页标记正则, 备注
BOOKS = [
    {
        "book_id": "XC",
        "prefix": "XC",
        "title": "《四角方阵刑冲合会透解》梁湘润（简体横排 2024）",
        "src": CORPUS / "LXR-TEXT" / "简体《四角方阵刑冲合会透解》梁湘润2024(1).txt",
        "page_re": r"^\s*(\d{1,3})\s*$",
        "out": "xc_fulltext.txt",
        "note": "页码以独立数字行夹排；正文中偶有孤立数字，按「递增且跨度≤3」认页界",
    },
    {
        "book_id": "NV",
        "prefix": "NV",
        "title": "《女命详解附女命通会》（简体 PDF）",
        "src": CORPUS / "LXR-TEXT" / "简体《女命详解附女命通会》-梁湘润(1).txt",
        "page_re": r"^\s*第\s*(\d{1,3})\s*页\s*$",
        "out": "nv_fulltext.txt",
        "note": "页界为「第N页」独立行；已抽 145 条规则（scope=女命）",
    },
    {
        "book_id": "DC",
        "prefix": "DC",
        "title": "《命学大辞渊》梁湘润（大元书局 2009，OCR）",
        "src": CORPUS / "LXR-MXDCY" / "OCR全文.md",
        "page_re": r"^【PDF第(\d{3})页】\s*$",
        "out": "dc_fulltext.txt",
        "note": "OCR 繁体稿，错字率高，只作辞典查条用，不得据以立断语；辞典体例，按词条首字归部",
    },
]


def split_pages(text: str, page_re: str) -> list[tuple[int, str]]:
    """按页标记切页。返回 [(页号, 正文)]，页号按标记实际值取。"""
    pat = re.compile(page_re, re.M)
    marks = list(pat.finditer(text))
    if not marks:
        return []
    pages: list[tuple[int, str]] = []
    last = 0
    for m in marks:
        if pages:
            prev_no, _ = pages[-1]
            body = text[last:m.start()]
            pages[-1] = (prev_no, body)
        try:
            no = int(m.group(1))
        except (IndexError, ValueError):
            no = (pages[-1][0] + 1) if pages else 1
        pages.append((no, ""))
        last = m.end()
    if pages:
        pages[-1] = (pages[-1][0], text[last:])
    return pages


def split_pages_numeric(text: str) -> list[tuple[int, str]]:
    """独立数字行作页界，要求页码递增且跨度 ≤3，滤掉正文里的孤立数字。"""
    lines = text.splitlines()
    marks: list[tuple[int, int]] = []  # (行号, 页号)
    expect = 1
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.isdigit():
            continue
        n = int(s)
        if n == expect or (0 < n - expect <= 3):
            marks.append((i, n))
            expect = n + 1
    if not marks:
        return []
    pages: list[tuple[int, str]] = []
    for idx, (li, no) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        body = "\n".join(lines[li + 1:end])
        pages.append((no, body))
    return pages


def clean(body: str) -> str:
    """去连续空行与行尾空白；不动字。"""
    body = "\n".join(ln.rstrip() for ln in body.splitlines())
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip("\n")


def build_one(b: dict) -> tuple[bool, str]:
    src: Path = b["src"]
    if not src.exists():
        return False, f"源文件缺失：{src}"
    text = src.read_text(encoding="utf-8", errors="replace")
    if b["book_id"] == "XC":
        pages = split_pages_numeric(text)
    else:
        pages = split_pages(text, b["page_re"])
    if not pages:
        return False, f"{b['book_id']}：切不出页界（正则不匹配）"
    out = DATA / b["out"]
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# {b['title']}\n")
        f.write(f"# 源：{src.name}｜页数：{len(pages)}\n")
        f.write(f"# 用途：规则回查底本。原文照录，未校勘。\n")
        for no, body in pages:
            f.write(f"\n===== p{no:03d} =====\n")
            f.write(clean(body))
            f.write("\n")
    chars = sum(len(clean(bd)) for _, bd in pages)
    return True, f"{b['book_id']} → {b['out']}：{len(pages)} 页／{chars} 字"


def write_manifest(rows: list[dict]) -> None:
    p = DATA / "corpus_manifest.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["book_id", "locator_prefix", "title",
                                          "fulltext_file", "pages", "chars",
                                          "digitized", "note"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="生成全文件")
    ap.add_argument("--check", action="store_true", help="核对已有全文件")
    args = ap.parse_args()

    if not (args.build or args.check):
        ap.print_help()
        return 2

    rows = []
    ok = 0
    for b in BOOKS:
        out = DATA / b["out"]
        if args.build:
            good, msg = build_one(b)
            print(("[ok] " if good else "[!!] ") + msg)
            ok += good
        if out.exists():
            txt = out.read_text(encoding="utf-8")
            pages = len(re.findall(r"^===== p\d{3} =====$", txt, re.M))
            chars = len(re.sub(r"^#.*$|^===== p\d{3} =====$", "", txt, flags=re.M))
            print(f"     现有：{b['out']} {pages} 页／{chars} 字")
            rows.append({
                "book_id": b["book_id"],
                "locator_prefix": b["prefix"],
                "title": b["title"],
                "fulltext_file": f"data/{b['out']}",
                "pages": pages,
                "chars": chars,
                "digitized": "yes",
                "note": b["note"],
            })
        else:
            rows.append({
                "book_id": b["book_id"], "locator_prefix": b["prefix"],
                "title": b["title"], "fulltext_file": "", "pages": 0, "chars": 0,
                "digitized": "no", "note": b["note"],
            })
    write_manifest(rows)
    print(f"\n登记：data/corpus_manifest.csv（{len(rows)} 本）")
    return 0 if (ok == len(BOOKS) or args.check) else 1


if __name__ == "__main__":
    sys.exit(main())
