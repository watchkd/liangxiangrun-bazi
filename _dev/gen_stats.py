#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_stats.py —— 从 data/ 实载重算 _integration_stats.json。

这份统计文件被 validate.py 的 C01 与文档正文（C04／C06）双向核对：
统计说 816、CSV 里 925，就判「计数不符」。手工改一处必漏另一处，
所以统计只许从数据算出来，不许手写。

用法：python tools/gen_stats.py [--check]
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "_integration_stats.json"


def rd(name: str) -> list[dict]:
    p = DATA / name
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def cnt(rows, key):
    return dict(Counter(r.get(key, "") for r in rows).most_common())


def build() -> dict:
    rules = rd("rules.csv")
    cases = rd("cases.csv")
    cells = rd("tables.csv")
    meta = rd("table_metadata.csv")
    conflicts = rd("conflicts.csv")
    unresolved = rd("unresolved_register.csv")
    cross = rd("crosswalk.csv")
    ocr = rd("ocr_corrections.csv")
    cov = rd("coverage_audit.csv")
    return {
        "generated_at": "2026-10-30",
        "rules": {
            "total": len(rules),
            "by_status": cnt(rules, "verification_status"),
            "by_evidence": cnt(rules, "evidence_grade"),
            "by_allow": cnt(rules, "deterministic_use"),
            "by_package": cnt(rules, "source_package"),
            "by_scope": cnt(rules, "scope"),
        },
        "cases": {
            "total": len(cases),
            "by_status": cnt(cases, "verification_status"),
            "by_evidence": cnt(cases, "evidence_grade"),
            "by_completeness": cnt(cases, "case_completeness"),
            "by_suitable": cnt(cases, "suitable_for_analysis"),
            "by_package": cnt(cases, "source_package"),
        },
        "tables": {
            "total_cells": len(cells),
            "table_count": len(meta),
            "by_status": cnt(cells, "verification_status"),
            "by_evidence": cnt(cells, "evidence_grade"),
            "by_allow": cnt(cells, "deterministic_use"),
            "by_package": cnt(cells, "source_package"),
        },
        "conflicts": {
            "total": len(conflicts),
            "by_status": cnt(conflicts, "status"),
            "by_package": cnt(conflicts, "source_package"),
        },
        "unresolved": {
            "total": len(unresolved),
            "by_status": cnt(unresolved, "status"),
            "by_package": cnt(unresolved, "source_package"),
        },
        "crosswalk": {
            "total": len(cross),
            "by_type": cnt(cross, "id_type"),
        },
        "ocr": {"corrections": len(ocr), "coverage_rows": len(cov)},
    }


def main() -> int:
    new = build()
    if "--check" in sys.argv:
        old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
        same = old == new
        print("统计与实载" + ("一致" if same else "不一致"))
        if not same:
            for k in new:
                if old.get(k) != new[k]:
                    print(f"  差异段：{k}")
        return 0 if same else 1
    OUT.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已重算 {OUT.name}：rules={new['rules']['total']}、cases={new['cases']['total']}、"
          f"cells={new['tables']['total_cells']}、tables={new['tables']['table_count']}、"
          f"conflicts={new['conflicts']['total']}、unresolved={new['unresolved']['total']}、"
          f"crosswalk={new['crosswalk']['total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
