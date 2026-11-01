#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_patch.py —— 把补丁 CSV 并进 data/rules.csv。

为什么要单独一支脚本，而不是手工贴：补丁是多人（多轮）分批产出的，
列序、BOM、rule_id 冲突、重复条、非法 topic 每一项都可能把库弄脏，
而 rules.csv 是全部断语的源头，脏一次要回滚整个包。

规矩：
  · 列名必须与主库逐字一致，顺序不同也按列名对齐（不按位置）
  · rule_id 重复一律拒绝，不做「后者覆盖」
  · rule_text 归一化后完全相同的视为重复条，跳过并报出
  · scope／topic／evidence_grade 走受控词表，不在表内即拒绝
  · 写入前自动备份为 rules.csv.bak-YYYYmmdd-HHMMSS

用法：
    python tools/merge_patch.py data/_patch_male.csv --dry-run
    python tools/merge_patch.py data/_patch_male.csv data/_patch_ss14.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "data" / "rules.csv"

SCOPE_OK = {"通用", "女命", "男命"}
TOPIC_OK = {"体例次第", "用神", "格局", "刑冲合害", "刑冲合会", "神煞", "大运",
            "岁运流年", "六亲", "婚姻", "疾病寿元", "命书体例", "术语考据",
            "十神", "实务杂项", "财官", "子息"}
# 补丁里常见的旧写法／口语写法，并入前先归一到受控值
TOPIC_ALIAS = {"婚姻女命": "婚姻", "寿元": "疾病寿元", "病灾": "疾病寿元"}
GRADE_OK = {"E1_原书影印", "E2_原书录文", "E3_电子文本", "E4_字幕", "E5_整理者摘要", "E6_计算"}


def norm(s: str) -> str:
    return re.sub(r"[\s「」『』（）()、，。：；,.]+", "", s or "")


def load(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("patches", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    head, main_rows = load(RULES)
    have_ids = {r["rule_id"] for r in main_rows}
    have_txt = {norm(r["rule_text"]) for r in main_rows}

    added, skipped, rejected = [], [], []
    for p in a.patches:
        pth = ROOT / p if not Path(p).is_absolute() else Path(p)
        if not pth.exists():
            print(f"[!!] 补丁不存在：{p}")
            return 2
        ph, rows = load(pth)
        if ph != head:
            miss = set(head) - set(ph)
            extra = set(ph) - set(head)
            print(f"[!!] {p} 列不符主库。缺列={sorted(miss)} 多列={sorted(extra)}")
            return 2
        for r in rows:
            if r.get("topic") in TOPIC_ALIAS:
                r["topic"] = TOPIC_ALIAS[r["topic"]]
            rid = (r["rule_id"] or "").strip()
            why = None
            if not rid:
                why = "空 rule_id"
            elif rid in have_ids:
                why = "rule_id 重复"
            elif norm(r["rule_text"]) in have_txt:
                why = "rule_text 与既有条重复"
            elif r["scope"] not in SCOPE_OK:
                why = f"非法 scope：{r['scope']}"
            elif r["topic"] not in TOPIC_OK:
                why = f"非法 topic：{r['topic']}"
            elif r["evidence_grade"] not in GRADE_OK:
                why = f"非法 evidence_grade：{r['evidence_grade']}"
            elif not (r["source_locator"] or "").strip():
                why = "缺 source_locator（无法回查）"
            if why:
                (skipped if why.endswith("重复") else rejected).append((rid, why))
                continue
            have_ids.add(rid)
            have_txt.add(norm(r["rule_text"]))
            added.append(r)

    print(f"主库现 {len(main_rows)} 条；本次可并入 {len(added)} 条")
    if skipped:
        print(f"跳过（重复）{len(skipped)} 条：" + "；".join(f"{i}({w})" for i, w in skipped[:8]))
    if rejected:
        print(f"拒绝 {len(rejected)} 条：")
        for i, w in rejected:
            print(f"  - {i or '(无号)'}：{w}")

    if a.dry_run:
        if added:
            print("\n前 3 条预览：")
            for r in added[:3]:
                print(f"  {r['rule_id']}｜{r['scope']}｜{r['topic']}｜{r['source_locator']}｜"
                      f"{r['rule_text'][:50]}")
        print("\n干跑结束，未写盘。")
        return 0
    if not added:
        print("无可并入条目，未写盘。")
        return 0

    bak = RULES.with_suffix(f".csv.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(RULES, bak)
    with RULES.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=head)
        w.writeheader()
        for r in main_rows + added:
            w.writerow(r)
    print(f"已写入 {RULES.name}：{len(main_rows)} → {len(main_rows) + len(added)} 条")
    print(f"备份：{bak.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
