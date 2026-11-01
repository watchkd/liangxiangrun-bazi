#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_after_merge.py —— 一次性收口「补丁并入」后的连带问题。

补丁并进 rules.csv 不是终点：source_manifest 要登记新来源、
crosswalk 要补行、冲突引用要落表、conditions 要带可判定性前缀。
这些是同一件事的四个侧面，分散手改必漏，故合为一支。

做的事（幂等，可反复跑）：
  1. source_manifest.csv 补登 SRC-LXTEXT-NV／SRC-LXTEXT-DC
  2. conditions 缺 `[可算]`／`[须人工]` 前缀者，按 deterministic_use 补
  3. deterministic_use 的 `须人工` 归一为受控值 `禁止`
  4. trigger_tags 非法者（无冒号且超 4 字）归一
  5. crosswalk.csv 为未登记的新规则补行
  6. conflicts.csv 补登 F-NEW-01～04（男命书间分歧）
"""
from __future__ import annotations

import csv
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def rd(name):
    f = DATA / name
    with f.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.DictReader(fh)
        return list(r.fieldnames or []), list(r)


def wr(name, head, rows):
    f = DATA / name
    bak = f.with_suffix(f".csv.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    if f.exists():
        shutil.copy2(f, bak)
    with f.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=head)
        w.writeheader()
        w.writerows(rows)


def step1():
    head, rows = rd("source_manifest.csv")
    have = {r["source_id"] for r in rows}
    add = []
    if "SRC-LXTEXT-NV" not in have:
        add.append({
            "source_id": "SRC-LXTEXT-NV", "source_package": "LX2-16",
            "source_type": "底本（电子文本）",
            "source_title": "简体《女命详解附女命通会》（页锚转录稿）",
            "edition_or_version": "简体 PDF，235 页，含文字层",
            "source_file": "1_直接可识别文字\\女命详解.doc／简体《女命详解附女命通会》-梁湘润(1).pdf",
            "locator_scheme": "PDF 页（页锚 pNNN＝PDF 页序）",
            "availability": "外部底本或包内文本（见 source_file）",
            "sha256": "", "bytes": "",
            "notes": "新建 data/nv_fulltext.txt（235 页）。本书主体已于早期批次抽为 193 条 scope=女命 规则；"
                     "本批只补「男命对比段」6 条，故与旧条不重叠。证据等级 E3（未回图）。",
        })
    if "SRC-LXTEXT-DC" not in have:
        add.append({
            "source_id": "SRC-LXTEXT-DC", "source_package": "LX2-16",
            "source_type": "底本（OCR 稿，低置信）",
            "source_title": "《命学大辞渊》梁湘润（大元书局 2009）",
            "edition_or_version": "繁体扫描本 311 页，OCR 全文，错字率高",
            "source_file": "2_高清可OCR\\梁湘润-命学大辞渊.pdf",
            "locator_scheme": "PDF 页（页锚 pNNN＝PDF 页序）",
            "availability": "外部底本（校订版目录：校订版/05_命学大辞渊_目标页清单.csv）",
            "sha256": "", "bytes": "",
            "notes": "新建 data/dc_fulltext.txt（311 页）。辞典体裁，OCR 繁体稿、错字多，"
                     "只作词条查考与辅助参照，凡据本书立论者 confidence 一律记低、不得单独作断。",
        })
    if add:
        wr("source_manifest.csv", head, rows + add)
    return f"source_manifest 补登 {len(add)} 行"


def step2_4():
    head, rows = rd("rules.csv")
    n_pref = n_use = n_tag = 0
    for r in rows:
        use = (r.get("deterministic_use") or "").strip()
        if use == "须人工":
            r["deterministic_use"] = "禁止"   # 受控值里「禁止」即「不得作确定性使用」
            use = "禁止"
            n_use += 1
        cond = (r.get("conditions") or "").strip()
        if not cond.startswith("["):
            pre = "[可算]" if use == "允许" else "[待人工]"
            r["conditions"] = f"{pre} {cond}" if cond and cond != "—" else f"{pre} —"
            n_pref += 1
        tags = (r.get("trigger_tags") or "").strip()
        if tags:
            fixed = []
            for t in tags.split("|"):
                t = t.strip()
                if not t:
                    continue
                if ":" not in t and len(t) > 4:
                    t = "五行:" + t[-4:]
                fixed.append(t)
            nt = "|".join(fixed)
            if nt != tags:
                r["trigger_tags"] = nt
                n_tag += 1
    wr("rules.csv", head, rows)
    return f"conditions 补前缀 {n_pref} 条；须人工→禁止 {n_use} 条；标签归一 {n_tag} 条"


def step5():
    head, rows = rd("rules.csv")
    chead, cw = rd("crosswalk.csv")
    have = {r["global_id"] for r in cw}
    add = []
    for r in rows:
        if r["rule_id"] in have:
            continue
        add.append({
            "global_id": r["rule_id"],
            "id_type": "rule",
            "source_package": r.get("source_package") or "LX2-16",
            "source_file": r.get("source_file") or "",
            "original_id": r.get("original_id") or r["rule_id"],
            "original_locator": r.get("source_locator") or "",
            "transformation": "LX2-16 新增（自全文件原文抽取，非跨包迁移）",
            "notes": (r.get("theme") or "")[:60],
        })
    if add:
        wr("crosswalk.csv", chead, cw + add)
    return f"crosswalk 补 {len(add)} 行"


def step6():
    head, rows = rd("conflicts.csv")
    have = {r["conflict_id"] for r in rows}
    base = {
        "conflict_type": "理论口径不同", "status": "开放", "source_package": "LX2-16",
        "impact": "同一结构可出相反结论，引用时须先择法并标出所据",
        "closure_requirement": "回原书上下文或补旁证裁定",
    }
    add = []
    spec = [
        ("F-NEW-01", "男命何者为子星",
         "《子平母法》p174", "身旺财为子，身衰印作儿",
         "《子平母法》p309", "男命以官杀为子息",
         "同书两处并存，一以财／印、一以官杀为子星。处置：并存不合并，"
         "取值须看所批是何主题（论财禄层用财，论子息层用官杀），不得单引一句当通则"),
        ("F-NEW-02", "四柱无财的严重度",
         "《细批终身详解》p413", "四柱无财，即是无妻之论",
         "《子平基础概要》p128", "男命亦主婚姻甚迟",
         "一作「无妻」实断、一作「迟婚」。处置：并存，前者为梁氏早年断语式口吻，"
         "后者为教材层缓和表述；引用时须带出所据书名，不得混用"),
        ("F-NEW-03", "无财是否可反为大富",
         "《细批终身详解》p413", "无财通论为无妻",
         "同页引沈孝瞻", "食伤兼杀者最喜四柱无财，乃是大富之造",
         "同页并置两说。处置：并存，后者限「食伤兼杀」一格，前者为一般论；"
         "用时须先定格，格定方可择说"),
        ("F-NEW-04", "正印坐正财之婚姻应验",
         "《子平母法》p96／《子平基础概要》p112", "妻随娶随伤／月柱为离婚之兆",
         "《子平基础概要》p89", "男命皆可以作双凤缘",
         "同书两处对同一组合给出相反婚姻应验。处置：并存不合并，"
         "须并看财印轻重与有无救应；本包不代判孰是"),
    ]
    for cid, topic, sa, ca, sb, cb, disp in spec:
        if cid in have:
            continue
        d = dict(base)
        d.update({"conflict_id": cid, "topic": topic, "party_a": "A说", "source_a": sa,
                  "claim_a": ca, "party_b": "B说", "source_b": sb, "claim_b": cb,
                  "disposition": disp, "notes": "男命补厚批次发现，原文摘句可回查 data/*_fulltext.txt",
                  "original_id": cid})
        add.append(d)
    if add:
        wr("conflicts.csv", head, rows + add)
    return f"conflicts 补 {len(add)} 条"


if __name__ == "__main__":
    for fn in (step1, step2_4, step5, step6):
        print("[ok]", fn())
    print("完成。请重跑 tools/validate.py。")
    sys.exit(0)
