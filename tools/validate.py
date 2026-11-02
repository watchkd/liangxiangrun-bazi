#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""梁湘润批八字·总装校验器（validate.py）

只做结构与自洽校验，不重读图版、不重判内容、不改任何数据文件。
退出码：0 = 无 FAIL（可有 WARN）；1 = 有 FAIL。

用法：
    python tools/validate.py
    python tools/validate.py --json
    python tools/validate.py --quiet
    python tools/validate.py --skip-smoke     # 跳过 analyze.py 冒烟

检查分组：
    S 结构    文件齐备、表头、必填字段
    K 主键    各表 ID 唯一
    F 外键    表间引用、crosswalk 覆盖、源清单覆盖
    V 取值域  证据等级／核验状态／确定性使用／四柱干支
    G 门控    待核/冲突/候选/排除 不得放行；字幕不得升已核
    C 计数    与 _integration_stats.json 及文档声明对账
    R 运行    分析器冒烟与非法输入拒绝
"""
import argparse
import csv
import glob
import io
import json
import os
import re
import subprocess
import sys
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TOOLS = os.path.join(ROOT, "tools")

# ---------- 词表（与 references/evidence_policy.md 一致，改词表须同步该文件） ----------
EV_OK = {"E1_同书图版", "E2_异本图版", "E3_电子文本", "E4_字幕", "E4b_视频帧",
         "E5_整理者推论", "E6_结构计算"}
ST_OK = {"已核", "部分核", "待核", "冲突", "候选", "排除"}
USE_OK = {"允许", "条件允许", "禁止"}
BLOCK_ST = {"待核", "冲突", "候选", "排除"}
COMP_OK = {"完整四柱", "不完整（3/4柱）", "不完整（2/4柱）", "非四柱"}

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
JIAZI = {STEMS[i % 10] + BRANCHES[i % 12] for i in range(60)}

REQUIRED_FILES = [
    "SKILL.md", "README.md", "INTEGRATION_STATUS.md", "CHANGELOG.md", "QA.md", "PATCH_SUMMARY.md",
    "references/analysis_workflow.md", "references/evidence_policy.md",
    "references/interaction_flow.md", "references/demo_session.md",
    "tools/feedback.py", "_命书/回执问单_甲子乙亥庚戌癸未.md", "_命书/复核_甲子乙亥庚戌癸未.md",
    "references/conflicts.md", "references/unresolved.md", "references/terminology.md",
    "references/rules/index_by_theme.md", "references/rules/index_by_scope.md",
    "references/tables/index.md", "references/cases/index.md",
    "data/rules.csv", "data/cases.csv", "data/tables.csv", "data/table_metadata.csv",
    "data/conflicts.csv", "data/unresolved_register.csv", "data/crosswalk.csv",
    "data/source_manifest.csv", "data/glossary.csv", "data/ocr_corrections.csv",
    "data/coverage_audit.csv", "data/video_episode_map.csv", "data/_integration_stats.json",
    "data/corpus_digest.csv", "data/xingqing.csv", "data/liuqin.csv",
    "data/point_rules.csv", "tools/trace_audit.py", "_命书/一致率报告.md",
    "data/jinbuhuan_ocr_notes.csv",
    "tools/analyze.py", "tools/validate.py",
    "references/推广尾注.md", "references/assets/appreciation.jpg",
]

RESULTS = []  # (group, code, level, message)


def rec(group, code, ok, msg, warn_only=False):
    level = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    RESULTS.append((group, code, level, msg))
    return ok


def load(name):
    path = os.path.join(DATA, name)
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        return rd.fieldnames or [], list(rd)


def g(r, k):
    return (r.get(k) or "").strip()


def parse_agg(s):
    """解析表级聚合串，如「已核 357；部分核 3」→ {已核:357, 部分核:3}。
    无数字的多值串（如「E1_同书图版；E3_电子文本」）返回 {值: None}。"""
    out = OrderedDict()
    for part in re.split(r"[；;]", s or ""):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.+?)\s+(\d+)$", part)
        if m:
            out[m.group(1).strip()] = int(m.group(2))
        else:
            out[part] = None
    return out


# ---------------- S 结构 ----------------
def check_structure():
    missing = [p for p in REQUIRED_FILES if not os.path.exists(os.path.join(ROOT, p))]
    rec("S", "S01", not missing, "必需文件齐备" if not missing else f"缺文件：{missing}")

    tables = ["rules", "cases", "tables", "table_metadata", "conflicts",
              "unresolved_register", "crosswalk", "source_manifest", "glossary",
              "ocr_corrections", "coverage_audit", "video_episode_map"]
    bad_hdr = []
    empty = []
    for t in tables:
        try:
            hdr, rows = load(t + ".csv")
        except Exception as e:
            bad_hdr.append(f"{t}: {e}")
            continue
        if not hdr:
            empty.append(t)
        elif len(hdr) != len(set(hdr)):
            dup = [x for x, n in Counter(hdr).items() if n > 1]
            bad_hdr.append(f"{t}: 重复列 {dup}")
        if not rows:
            empty.append(t)
    rec("S", "S02", not bad_hdr, "表头无重复列" if not bad_hdr else f"表头异常：{bad_hdr}")
    rec("S", "S03", not empty, "各表均有数据行" if not empty else f"空表：{empty}")

    # 必填字段
    need = {
        "rules": ["rule_id", "theme", "rule_text", "source_id", "source_locator",
                  "evidence_grade", "verification_status", "deterministic_use"],
        "cases": ["case_id", "case_completeness", "source_id", "source_locator",
                  "evidence_grade", "verification_status", "deterministic_use"],
        "tables": ["cell_id", "table_id", "row_key", "value", "source_id",
                   "source_locator", "evidence_grade", "verification_status",
                   "deterministic_use"],
        "table_metadata": ["table_id", "table_title", "source_id", "evidence_grade",
                           "verification_status", "deterministic_use"],
        "conflicts": ["conflict_id", "topic", "status"],
        "unresolved_register": ["unresolved_id", "theme", "description", "status"],
        "crosswalk": ["global_id", "id_type", "source_package"],
        "source_manifest": ["source_id", "source_package", "source_type", "source_title"],
        "glossary": ["term_id", "term", "source_id", "evidence_grade"],
    }
    holes = []
    for t, cols in need.items():
        _, rows = load(t + ".csv")
        for r in rows:
            for c in cols:
                if not g(r, c):
                    holes.append(f"{t}.{c}@{g(r, cols[0])}")
    rec("S", "S04", not holes,
        "必填字段无空值" if not holes else f"空值 {len(holes)} 处（前 5：{holes[:5]}）")


# ---------------- K 主键 ----------------
def check_keys():
    keys = {
        "rules": "rule_id", "cases": "case_id", "tables": "cell_id",
        "table_metadata": "table_id", "conflicts": "conflict_id",
        "unresolved_register": "unresolved_id", "crosswalk": "global_id",
        "source_manifest": "source_id", "glossary": "term_id",
    }
    dup_all = []
    for t, k in keys.items():
        _, rows = load(t + ".csv")
        c = Counter(g(r, k) for r in rows)
        dup = {x: n for x, n in c.items() if n > 1}
        if dup:
            dup_all.append(f"{t}.{k}: {list(dup.items())[:5]}")
        rec("K", "K01", not dup, f"{t}.{k} 唯一（{len(rows)} 条）" if not dup
            else f"{t}.{k} 重复：{list(dup.items())[:5]}")
    return dup_all


# ---------------- F 外键 ----------------
def check_refs():
    _, rules = load("rules.csv")
    _, cases = load("cases.csv")
    _, cells = load("tables.csv")
    _, meta = load("table_metadata.csv")
    _, conf = load("conflicts.csv")
    _, unres = load("unresolved_register.csv")
    _, cw = load("crosswalk.csv")
    _, src = load("source_manifest.csv")
    _, glo = load("glossary.csv")

    tids = {g(r, "table_id") for r in meta}
    bad = sorted({g(r, "table_id") for r in cells} - tids)
    rec("F", "F01", not bad, "格值 table_id 均在表级元数据内" if not bad
        else f"格值引用未登记表：{bad[:5]}")

    sids = {g(r, "source_id") for r in src}
    miss = []
    for t, rows in (("rules", rules), ("cases", cases), ("tables", cells),
                    ("glossary", glo), ("table_metadata", meta)):
        for r in rows:
            if g(r, "source_id") not in sids:
                miss.append(f"{t}:{g(r, 'rule_id') or g(r, 'case_id') or g(r, 'cell_id') or g(r, 'term_id') or g(r, 'table_id')}")
    rec("F", "F02", not miss, "source_id 均在 source_manifest" if not miss
        else f"未登记来源 {len(miss)} 处（前 5：{miss[:5]}）")

    rids = {g(r, "rule_id") for r in rules}
    bad_case_rule = []
    for r in cases:
        for x in re.split(r"[;,、\s]+", g(r, "linked_rule_ids")):
            x = x.strip()
            if x and x.startswith("R") and x not in rids:
                bad_case_rule.append(f"{g(r, 'case_id')}->{x}")
    rec("F", "F03", not bad_case_rule, "命例 linked_rule_ids 可解析" if not bad_case_rule
        else f"命例引用未登记规则 {len(bad_case_rule)} 处（前 5：{bad_case_rule[:5]}）",
        warn_only=True)

    bad_rule_tab = []
    for r in rules:
        for x in re.split(r"[;,、\s]+", g(r, "related_table_ids")):
            x = x.strip()
            if x and x not in tids and not x.startswith("TH-01"):
                bad_rule_tab.append(f"{g(r, 'rule_id')}->{x}")
    rec("F", "F04", not bad_rule_tab, "规则 related_table_ids 可解析" if not bad_rule_tab
        else f"规则引用未登记表 {len(bad_rule_tab)} 处（前 5：{bad_rule_tab[:5]}）",
        warn_only=True)

    cids = {g(r, "conflict_id") for r in conf}
    bad_rule_conf = []
    for r in rules:
        for x in re.split(r"[;,、\s]+", g(r, "conflict_ids")):
            x = x.strip()
            if x and x not in cids:
                bad_rule_conf.append(f"{g(r, 'rule_id')}->{x}")
    rec("F", "F05", not bad_rule_conf, "规则 conflict_ids 可解析" if not bad_rule_conf
        else f"规则引用未登记冲突 {len(bad_rule_conf)} 处（前 5：{bad_rule_conf[:5]}）",
        warn_only=True)

    # crosswalk 双向覆盖
    expect = {
        "rule": {g(r, "rule_id") for r in rules},
        "case": {g(r, "case_id") for r in cases},
        "table_cell": {g(r, "cell_id") for r in cells},
        "table": tids,
        "conflict": cids,
        "unresolved": {g(r, "unresolved_id") for r in unres},
        "term": {g(r, "term_id") for r in glo},
    }
    gaps = []
    for typ, ids in expect.items():
        have = {g(r, "global_id") for r in cw if g(r, "id_type") == typ}
        miss = ids - have
        extra = have - ids
        if miss:
            gaps.append(f"{typ} 缺 {len(miss)}（如 {sorted(miss)[:2]}）")
        if extra:
            gaps.append(f"{typ} 多 {len(extra)}（如 {sorted(extra)[:2]}）")
    rec("F", "F06", not gaps, "crosswalk 与各表 ID 双向覆盖一致" if not gaps
        else f"crosswalk 覆盖缺口：{gaps}")

    # cell_count 对账
    cnt = Counter(g(r, "table_id") for r in cells)
    bad_cnt = [f"{g(m, 'table_id')}: 声明 {g(m, 'cell_count')} 实载 {cnt.get(g(m, 'table_id'), 0)}"
               for m in meta
               if g(m, "cell_count").isdigit() and int(g(m, "cell_count")) != cnt.get(g(m, "table_id"), 0)]
    rec("F", "F07", not bad_cnt, "表级 cell_count 与实载格数一致" if not bad_cnt
        else f"格数不符 {len(bad_cnt)} 表（前 5：{bad_cnt[:5]}）")

    # 无孤立表：元数据里有、格值里没有（空表须显式说明）
    _, meta2 = load("table_metadata.csv")
    orphan = []
    for m in meta2:
        tid = g(m, "table_id")
        if tid in cnt:
            continue
        zero = g(m, "cell_count") in ("0", "")
        structural = g(m, "table_type") in ("结构表", "章节表")
        if not (zero and structural):
            orphan.append(tid)
    rec("F", "F08", not orphan, "无未说明的空表级登记" if not orphan
        else f"表级登记但无格值：{orphan[:5]}")


# ---------------- V 取值域 ----------------
def check_vocab():
    for t in ("rules", "cases", "tables", "glossary"):
        _, rows = load(t + ".csv")
        bad_ev = sorted({g(r, "evidence_grade") for r in rows} - EV_OK)
        bad_st = sorted({g(r, "verification_status") for r in rows} - ST_OK)
        bad_us = sorted({g(r, "deterministic_use") for r in rows} - USE_OK)
        rec("V", "V01", not bad_ev, f"{t} evidence_grade 合法" if not bad_ev
            else f"{t} 非法证据等级：{bad_ev}")
        rec("V", "V02", not bad_st, f"{t} verification_status 合法" if not bad_st
            else f"{t} 非法核验状态：{bad_st}")
        rec("V", "V03", not bad_us, f"{t} deterministic_use 合法" if not bad_us
            else f"{t} 非法确定性使用：{bad_us}")

    _, cases = load("cases.csv")
    bad_comp = sorted({g(r, "case_completeness") for r in cases} - COMP_OK)
    rec("V", "V04", not bad_comp, "命例完整度取值合法" if not bad_comp
        else f"非法完整度：{bad_comp}")

    # 命例四柱：完整四柱须为合法六十甲子
    bad_p = []
    for r in cases:
        if g(r, "case_completeness") != "完整四柱":
            continue
        ps = [g(r, "year_pillar"), g(r, "month_pillar"), g(r, "day_pillar"), g(r, "hour_pillar")]
        for p in ps:
            if p and p not in JIAZI:
                bad_p.append(f"{g(r, 'case_id')}:{p}")
    rec("V", "V05", not bad_p, "完整四柱命例干支合法" if not bad_p
        else f"非法干支 {len(bad_p)} 处（前 5：{bad_p[:5]}）", warn_only=True)

    _, conf = load("conflicts.csv")
    _, unres = load("unresolved_register.csv")
    rec("V", "V06", all(g(r, "status") for r in conf), "冲突项均有状态")
    rec("V", "V07", all(g(r, "status") for r in unres), "未决项均有状态")

    CF_ST_OK = {"开放", "待裁", "待核", "已关闭", "开放（待批）",
                "已裁定（并列保留）", "已裁定（占位）"}
    bad_cf = sorted({g(r, "status") for r in conf} - CF_ST_OK)
    rec("V", "V11", not bad_cf, "冲突状态取值合法" if not bad_cf
        else f"非法冲突状态：{bad_cf}")

    # 冲突双方主张不得为占位符（Part 16 曾出现「见 topic 所述前一说」18 条）
    ph = re.compile(r"见\s*topic|见上文|见前说|同上|TBD|待补|^—*$")
    placeholder = [g(r, "conflict_id") for r in conf
                   if ph.search(g(r, "claim_a")) or ph.search(g(r, "claim_b"))]
    rec("V", "V12", not placeholder, "冲突双方主张均为实际文本" if not placeholder
        else f"冲突主张为占位符 {len(placeholder)} 条：{placeholder[:5]}")

    # 冲突 source 不得标「待定位」而无页码
    unlocated = [g(r, "conflict_id") for r in conf
                 if "待定位" in g(r, "source_a") + g(r, "source_b")]
    rec("V", "V13", not unlocated, "冲突双方来源均已定位" if not unlocated
        else f"来源未定位 {len(unlocated)} 条：{unlocated[:5]}")

    # 规则分类与触发标签（Part 40）：topic 须在受控词表内；trigger_tags 须为「维度:值」或布尔词
    _, rules = load("rules.csv")
    TOPIC_OK = {"体例次第", "用神", "格局", "刑冲合害", "刑冲合会", "神煞", "大运",
                "岁运流年", "六亲", "婚姻", "疾病寿元", "命书体例", "术语考据",
                "十神", "实务杂项", "财官", "子息"}
    bad_topic = sorted({g(r, "topic") for r in rules} - TOPIC_OK)
    rec("V", "V14", not bad_topic, "rules.topic 均在受控词表内" if not bad_topic
        else f"非法 topic：{bad_topic}")

    tag_pat = re.compile(r"^[\u4e00-\u9fa5]{1,4}(:[\u4e00-\u9fa5/]{1,12})?$")
    bad_tag = []
    for r in rules:
        for x in (g(r, "trigger_tags") or "").split("|"):
            if x and not tag_pat.match(x):
                bad_tag.append(f"{g(r, 'rule_id')}:{x}")
    rec("V", "V15", not bad_tag, "rules.trigger_tags 格式合法" if not bad_tag
        else f"非法触发标签 {len(bad_tag)} 处（前 5：{bad_tag[:5]}）")

    # 表级三个字段为聚合统计串，单独按聚合规则校验
    _, meta = load("table_metadata.csv")
    bad_agg, mismatch = [], []
    for m in meta:
        tid = g(m, "table_id")
        n = int(g(m, "cell_count") or 0)
        for field, vocab in (("evidence_grade", EV_OK), ("verification_status", ST_OK),
                             ("deterministic_use", USE_OK)):
            agg = parse_agg(g(m, field))
            if not agg:
                bad_agg.append(f"{tid}.{field} 空")
                continue
            for k, v in agg.items():
                if k not in vocab:
                    bad_agg.append(f"{tid}.{field}={k}")
                elif v is None and field != "evidence_grade" and n > 0:
                    # evidence_grade 允许「E1_同书图版；E3_电子文本」这类多值不计数；
                    # cell_count=0 的结构表级登记允许用单值状态
                    bad_agg.append(f"{tid}.{field} 缺计数：{k}")
            vals = [v for v in agg.values() if v is not None]
            if vals and sum(vals) != n:
                mismatch.append(f"{tid}.{field} Σ{sum(vals)}≠{n}")
    rec("V", "V08", not bad_agg, "表级聚合串取值合法" if not bad_agg
        else f"表级聚合串非法 {len(bad_agg)} 处（前 5：{bad_agg[:5]}）")
    rec("V", "V09", not mismatch, "表级聚合计数之和等于 cell_count" if not mismatch
        else f"聚合不闭合 {len(mismatch)} 处（前 5：{mismatch[:5]}）")

    # 表级聚合数须与格值实算一致（表级汇总不得虚增）
    _, cells = load("tables.csv")
    by_tab = {}
    for c in cells:
        by_tab.setdefault(g(c, "table_id"), []).append(c)
    drift = []
    for m in meta:
        tid = g(m, "table_id")
        rows = by_tab.get(tid, [])
        if not rows:
            continue
        for field in ("verification_status", "deterministic_use", "evidence_grade"):
            agg = parse_agg(g(m, field))
            real = Counter(g(r, field) for r in rows)
            for k, v in agg.items():
                if v is not None and v != real.get(k, 0):
                    drift.append(f"{tid}.{field}:{k} 表级{v} 实算{real.get(k, 0)}")
    rec("V", "V10", not drift, "表级聚合数与格值实算一致" if not drift
        else f"表级汇总与格值不符 {len(drift)} 处（前 5：{drift[:5]}）")


# ---------------- G 门控 ----------------
def check_gate():
    leaks = []
    for t, key in (("rules", "rule_id"), ("cases", "case_id"), ("tables", "cell_id"),
                   ("glossary", "term_id")):
        _, rows = load(t + ".csv")
        for r in rows:
            if g(r, "verification_status") in BLOCK_ST and g(r, "deterministic_use") != "禁止":
                leaks.append(f"{t}:{g(r, key)}（{g(r, 'verification_status')}/{g(r, 'deterministic_use')}）")
    rec("G", "G01", not leaks, "门控无泄漏：待核／冲突／候选／排除 一律禁止" if not leaks
        else f"门控泄漏 {len(leaks)} 处（前 5：{leaks[:5]}）")

    over = []
    for t, key in (("rules", "rule_id"), ("tables", "cell_id"), ("cases", "case_id")):
        _, rows = load(t + ".csv")
        for r in rows:
            if g(r, "deterministic_use") == "允许" and g(r, "evidence_grade") in (
                    "E5_整理者推论", "E6_结构计算", "E4_字幕", "E4b_视频帧"):
                over.append(f"{t}:{g(r, key)}（{g(r, 'evidence_grade')} 标允许）")
    rec("G", "G02", not over, "字幕／推论／结构计算未越级标“允许”" if not over
        else f"越级放行 {len(over)} 处（前 5：{over[:5]}）")

    # 字幕证据不得升“已核”（只证明说过，不证明说对）
    sub = []
    for t, key in (("rules", "rule_id"), ("tables", "cell_id"), ("cases", "case_id")):
        _, rows = load(t + ".csv")
        for r in rows:
            if g(r, "evidence_grade") == "E4_字幕" and g(r, "verification_status") == "已核":
                sub.append(f"{t}:{g(r, key)}")
    rec("G", "G03", not sub, "E4 字幕证据未标“已核”" if not sub
        else f"字幕证据越级已核 {len(sub)} 处（前 5：{sub[:5]}）")

    _, cases = load("cases.csv")
    bad_suit = [g(r, "case_id") for r in cases
                if g(r, "case_completeness") != "完整四柱"
                and g(r, "suitable_for_rule_validation").startswith("是")]
    rec("G", "G04", not bad_suit, "不完整命例未标“可用于规则验证”" if not bad_suit
        else f"不完整命例被标可用：{bad_suit[:5]}")

    # 六冲／六害／六合不得回落 E2（Part 9 已升 E1）
    _, cells = load("tables.csv")
    regress = [g(r, "cell_id") for r in cells
               if g(r, "table_id") in ("TB-XJ04", "TB-XJ05") and g(r, "evidence_grade") != "E1_同书图版"]
    rec("G", "G05", not regress, "六冲／六害／六合格值维持 E1" if not regress
        else f"XJ04／XJ05 证据等级回落：{regress[:5]}")

    # 表级门控：聚合串里「禁止」数须等于被阻断状态的实算之和
    _, meta = load("table_metadata.csv")
    by_tab = {}
    for c in cells:
        by_tab.setdefault(g(c, "table_id"), []).append(c)
    bad = []
    for m in meta:
        tid = g(m, "table_id")
        rows = by_tab.get(tid, [])
        if not rows:
            continue
        blocked = sum(1 for r in rows if g(r, "verification_status") in BLOCK_ST)
        verified = sum(1 for r in rows if g(r, "verification_status") == "已核")
        use = parse_agg(g(m, "deterministic_use"))
        ban = use.get("禁止", 0) or 0
        allow = use.get("允许", 0) or 0
        # 表级聚合按格统计：禁止数须覆盖全部阻断项；「允许」数不得超过已核格数
        if ban < blocked:
            bad.append(f"{tid}: 阻断{blocked} > 表级禁止{ban}")
        if allow > verified:
            bad.append(f"{tid}: 允许{allow} > 已核{verified}")
    rec("G", "G06", not bad, "表级“禁止”覆盖阻断项且“允许”不超已核格数" if not bad
        else f"表级门控不符 {len(bad)} 表（前 5：{bad[:5]}）")


# ---------------- C 计数 ----------------
def check_counts():
    _, rules = load("rules.csv")
    _, cases = load("cases.csv")
    _, cells = load("tables.csv")
    _, meta = load("table_metadata.csv")
    _, conf = load("conflicts.csv")
    _, unres = load("unresolved_register.csv")
    _, cw = load("crosswalk.csv")

    actual = {"rules": len(rules), "cases": len(cases), "cells": len(cells),
              "tables": len(meta), "conflicts": len(conf), "unresolved": len(unres),
              "crosswalk": len(cw)}

    with io.open(os.path.join(DATA, "_integration_stats.json"), encoding="utf-8") as f:
        st = json.load(f)
    pairs = [("rules", st["rules"]["total"]), ("cases", st["cases"]["total"]),
             ("cells", st["tables"]["total_cells"]), ("tables", st["tables"]["table_count"]),
             ("conflicts", st["conflicts"]["total"]),
             ("unresolved", st["unresolved"]["total"]),
             ("crosswalk", st["crosswalk"]["total"])]
    diff = [f"{k}: stats={v} 实载={actual[k]}" for k, v in pairs if v != actual[k]]
    rec("C", "C01", not diff, "各表行数与 _integration_stats.json 一致" if not diff
        else f"计数不符：{diff}")

    # stats 分项之和 == total
    sums = []
    for sect, field in (("rules", "by_status"), ("rules", "by_evidence"), ("rules", "by_allow"),
                        ("cases", "by_status"), ("cases", "by_completeness"),
                        ("tables", "by_status"), ("tables", "by_evidence"), ("tables", "by_allow"),
                        ("conflicts", "by_status"), ("unresolved", "by_status"),
                        ("crosswalk", "by_type")):
        total_key = "total_cells" if sect == "tables" else "total"
        s = sum(st[sect][field].values())
        if s != st[sect][total_key]:
            sums.append(f"{sect}.{field}: Σ={s} != {st[sect][total_key]}")
    rec("C", "C02", not sums, "stats 各分项之和等于总数" if not sums else f"分项不闭合：{sums}")

    # crosswalk 分类型计数与源表一致
    typ = Counter(g(r, "id_type") for r in cw)
    bad = [f"{k}: crosswalk={v} 实载={actual.get(m, '?')}"
           for k, m, v in (("rule", "rules", typ["rule"]), ("case", "cases", typ["case"]),
                           ("table_cell", "cells", typ["table_cell"]),
                           ("table", "tables", typ["table"]),
                           ("conflict", "conflicts", typ["conflict"]),
                           ("unresolved", "unresolved", typ["unresolved"]))
           if v != actual[m]]
    rec("C", "C03", not bad, "crosswalk 分类型计数与源表一致" if not bad else f"分类型不符：{bad}")

    # 文档声明数对账（INTEGRATION_STATUS 第四节 + QA 第二节）
    want = {"规则": actual["rules"], "命例": actual["cases"], "表格格值": actual["cells"],
            "冲突": actual["conflicts"], "未决项": actual["unresolved"],
            "crosswalk": actual["crosswalk"]}
    for doc_name, code in (("INTEGRATION_STATUS.md", "C04"), ("QA.md", "C06")):
        path = os.path.join(ROOT, doc_name)
        if not os.path.exists(path):
            rec("C", code, False, f"{doc_name} 不存在")
            continue
        doc = io.open(path, encoding="utf-8").read()
        bad_doc = []
        for label, val in want.items():
            m = re.search(r"\|\s*" + re.escape(label) + r"\s*\|\s*([\d,]+)\s*\|", doc)
            if not m:
                bad_doc.append(f"{label} 未声明")
            elif int(m.group(1).replace(",", "")) != val:
                bad_doc.append(f"{label} 文档 {m.group(1)} vs 实载 {val}")
        rec("C", code, not bad_doc, f"{doc_name} 规模／分母表与实载一致" if not bad_doc
            else f"{doc_name} 计数不符：{bad_doc}")

    # 根级副本一致
    dup = []
    for a, b in (("UNRESOLVED_REGISTER.csv", "data/unresolved_register.csv"),
                 ("SOURCE_MANIFEST.csv", "data/source_manifest.csv")):
        pa, pb = os.path.join(ROOT, a), os.path.join(ROOT, b)
        if not os.path.exists(pa):
            dup.append(f"{a} 不存在")
        elif io.open(pa, "rb").read() != io.open(pb, "rb").read():
            dup.append(f"{a} 与 {b} 字节不一致")
    rec("C", "C05", not dup, "根级登记副本与 data 正本一致" if not dup else f"副本不一致：{dup}")

    return actual


# ---------------- R 运行 ----------------
SMOKE = ["戊辰 戊午 甲午 乙丑 --gender 男",
         "庚午 庚寅 甲戌 丁卯 --gender 男",
         "乙丑 庚午 甲申 癸酉 --gender 男",
         "壬辰 壬子 丙午 癸巳 --gender 女"]
SECTIONS = ["## 一、四柱输入", "## 二、四柱、藏干与十神", "## 三、形态判定",
            "## 四、用神取用次序", "## 五、采用的梁氏分析路径",
            "## 六、刑冲合会判定", "## 七、格局裁定", "## 八、调候与日主喜忌",
            "## 十、流年", "## 十一、神煞",
            "## 十四、冲突、低置信与资料缺口", "## 十五、本次未能确定"]


def check_golden(skip):
    """R07：回归测试。结构校验全绿也可能输出漂移，本项守这一处。"""
    if skip:
        rec("R", "R07", True, "已按参数跳过回归测试", warn_only=True)
        return
    ap = os.path.join(TOOLS, "test_golden.py")
    if not os.path.exists(ap):
        rec("R", "R07", False, "tools/test_golden.py 不存在")
        return
    p = subprocess.run([sys.executable, ap], capture_output=True, text=True,
                       encoding="utf-8", cwd=ROOT)
    ok = p.returncode == 0
    tail = (p.stdout or "").strip().split("\n")[-1] if p.stdout else p.stderr[:120]
    rec("R", "R07", ok, f"回归测试：{tail}" if ok else f"回归测试失败：{tail}")


def check_mingshu(skip):
    """R08：命书生成器。底稿不等于命书，本项守「六段体例真的出得来」这一处。

    不只验退出码，还验六段标题齐备、附四剔除表非空——因为生成器最容易坏的地方
    不是崩掉，是静默退化成「只有结构、没有断语」的底稿。
    """
    if skip:
        rec("R", "R08", True, "已按参数跳过命书生成", warn_only=True)
        return
    ap = os.path.join(TOOLS, "mingshu.py")
    if not os.path.exists(ap):
        rec("R", "R08", False, "tools/mingshu.py 不存在")
        return
    p = subprocess.run([sys.executable, ap, "甲子", "乙亥", "庚戌", "癸未",
                        "--gender", "男", "--start-age", "10"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if p.returncode != 0:
        rec("R", "R08", False, f"命书生成失败：{p.stderr.strip()[:160]}")
        return
    out = p.stdout or ""
    need = ["## 命序", "## 一、已知因", "## 二、总评", "## 三、妻", "## 四、财",
            "## 五、子", "## 六、禄", "## 七、大运分述", "## 八、提要", "## 九、边界",
            "## 附一、批词依据表", "## 附四、已剔除的误命中"]
    miss = [x for x in need if x not in out]
    rows = out.count("\n| R-") + out.count("\n| R1") + out.count("\n| R2") + out.count("\n| R3")
    if miss:
        rec("R", "R08", False, "命书六段缺项：" + "、".join(miss))
    elif rows < 5:
        rec("R", "R08", False, f"命书依据表过少（{rows} 行），疑退化为纯结构")
    else:
        rec("R", "R08", True, f"命书六段齐备，依据表 {rows} 行，{len(out)} 字")


def check_mingshu_html(skip):
    """R09：命书交付件。守的是「交来客的那一份，里面没有一个工程标记」。

    底稿可以挂 rule_id，命书不行——这是两轨的分界。本项把 HTML 再生成一遍，
    去 style 与标签后逐词扫描：出现 rule_id、证据等级、依据表、附录一类即判失败。
    同时验九节齐备，防静默退化成只有表格没有正文。
    """
    if skip:
        rec("R", "R09", True, "已按参数跳过命书交付件", warn_only=True)
        return
    ap = os.path.join(TOOLS, "mingshu.py")
    prose = os.path.join(ROOT, "_命书", "批词_甲子乙亥庚戌癸未.md")
    if not (os.path.exists(ap) and os.path.exists(prose)):
        rec("R", "R09", False, "tools/mingshu.py 或 批词样例不存在")
        return
    p = subprocess.run([sys.executable, ap, "甲子", "乙亥", "庚戌", "癸未",
                        "--gender", "男", "--start-age", "10", "--birth-year", "1984",
                        "--format", "html", "--prose", prose],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if p.returncode != 0:
        rec("R", "R09", False, f"命书 HTML 生成失败：{p.stderr.strip()[:160]}")
        return
    out = p.stdout or ""
    body = re.sub(r"<style>.*?</style>", "", out, flags=re.S)
    body = re.sub(r"<[^>]+>", "", body)
    dirty = [w for w in ("rule_id", "证据等级", "依据表", "附录", "部分核", "已核",
                         "待核", "未入库", "口径", "R-JB", "R-MF", "R-SZ", "R-X11",
                         "T-ORIG", "T-X11", "E1 ", "E3 ") if w in body]
    heads = ["命式", "已知因", "排盘所据", "总评", "妻", "财", "子", "禄", "寿", "性情",
             "父母兄弟", "疾病", "大运批导", "流年举要", "人生指要", "待验问事", "附言"]
    # 按 <h2> 标题逐个比对，不用「正文含某字」——「子」「财」这类单字满篇皆是，
    # 用子串查等于没查（Part 45 改）。
    titles = re.findall(r"<h2>(?:<span class=\"no\">[^<]*</span>)?([^<]*)</h2>", out)
    lack = [h for h in heads if h not in titles]
    if dirty:
        rec("R", "R09", False, "命书含工程标记：" + "、".join(dirty))
    elif lack:
        rec("R", "R09", False, "命书缺节：" + "、".join(lack))
    else:
        rec("R", "R09", True, f"命书{len(heads)}节齐备，正文 {len(body)} 字，无工程标记")


def check_mingshu_thick(skip):
    """R10：命书厚度。防的不是脏，是空。

    R09 只查「有没有工程词」，查不出「该有的整段没了」。Part 42 首版即栽在此：
    零工程标记，可性情、格局、六亲、流年、全流表五样全缺，正文只剩三千余字。
    本项把节数、段数、表行、大运块、正文字数五项一并设下限，退一步即 FAIL。
    """
    if skip:
        rec("R", "R10", True, "已按参数跳过命书厚度", warn_only=True)
        return
    ap = os.path.join(TOOLS, "mingshu.py")
    prose = os.path.join(ROOT, "_命书", "批词_甲子乙亥庚戌癸未.md")
    if not (os.path.exists(ap) and os.path.exists(prose)):
        rec("R", "R10", False, "tools/mingshu.py 或 批词样例不存在")
        return
    p = subprocess.run([sys.executable, ap, "甲子", "乙亥", "庚戌", "癸未",
                        "--gender", "男", "--start-age", "10", "--birth-year", "1984",
                        "--format", "html", "--prose", prose],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if p.returncode != 0:
        rec("R", "R10", False, f"命书 HTML 生成失败：{p.stderr.strip()[:160]}")
        return
    out = p.stdout or ""
    body = re.sub(r"<style>.*?</style>", "", out, flags=re.S)
    body = re.sub(r"<[^>]+>", "", body)
    body = re.sub(r"\s+", "", body)
    got = {
        "节数": out.count("<h2>"),
        "段数": out.count("<p>") + out.count("<p class"),
        "表行": out.count("<tr>"),
        "大运块": out.count('<div class="yun'),
        "正文字数": len(body),
    }
    floor = {"节数": 17, "段数": 70, "表行": 80, "大运块": 8, "正文字数": 6000}
    short = ["%s %d<%d" % (k, got[k], floor[k]) for k in floor if got[k] < floor[k]]
    if short:
        rec("R", "R10", False, "命书过薄：" + "、".join(short))
    else:
        rec("R", "R10", True, "命书厚度足：%d 节／%d 段／%d 表行／%d 运块／正文 %d 字"
            % (got["节数"], got["段数"], got["表行"], got["大运块"], got["正文字数"]))


def check_mingshu_quotes(skip):
    """R11：命书所引原文，须在底本全文里逐字可寻。

    R09 查脏、R10 查空，都不管「引文对不对」。命书里凡加引用块的，都是拿原书的话
    给来客作凭据；错一个字，凭据就不成立。本项把 HTML 的 <blockquote> 逐条取出，
    去标签、去空白后到底本（data/*.txt）里找，找不到即 FAIL。

    去空白是必要的：底本按行折行，一句原文常跨两三行；去页锚是因为
    「===== p028 =====」会插在句子中间。
    """
    if skip:
        rec("R", "R11", True, "已按参数跳过命书引文回溯", warn_only=True)
        return
    ap = os.path.join(TOOLS, "mingshu.py")
    prose = os.path.join(ROOT, "_命书", "批词_甲子乙亥庚戌癸未.md")
    if not (os.path.exists(ap) and os.path.exists(prose)):
        rec("R", "R11", False, "tools/mingshu.py 或 批词样例不存在")
        return
    p = subprocess.run([sys.executable, ap, "甲子", "乙亥", "庚戌", "癸未",
                        "--gender", "男", "--start-age", "10", "--birth-year", "1984",
                        "--format", "html", "--prose", prose],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if p.returncode != 0:
        rec("R", "R11", False, f"命书 HTML 生成失败：{p.stderr.strip()[:160]}")
        return

    corpus = ""
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "*.txt"))):
        with io.open(f, encoding="utf-8", errors="ignore") as fh:
            corpus += fh.read()
    corpus = re.sub(r"=====\s*p\d+\s*=====", "", corpus)
    corpus = re.sub(r"\s+", "", corpus)

    quotes = re.findall(r"<blockquote>(.*?)</blockquote>", p.stdout or "", re.S)
    if not quotes:
        rec("R", "R11", True, "命书未用引用块，无引文须校")
        return
    miss = []
    for q in quotes:
        t = re.sub(r"<[^>]+>", "", q)
        t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        t = re.sub(r"\s+", "", t)
        if t and t not in corpus:
            miss.append(t[:28])
    if miss:
        rec("R", "R11", False, "命书引文在底本中找不到：" + "；".join(miss))
    else:
        rec("R", "R11", True, f"命书 {len(quotes)} 处引文均可逐字回溯")


def check_runtime(skip):
    if skip:
        rec("R", "R01", True, "已按参数跳过冒烟", warn_only=True)
        return
    ap = os.path.join(TOOLS, "analyze.py")
    fails = []
    outs = []
    for args in SMOKE:
        p = subprocess.run([sys.executable, ap] + args.split(),
                           capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        if p.returncode != 0:
            fails.append(f"{args}: exit {p.returncode} {p.stderr.strip()[:120]}")
            continue
        out = p.stdout
        outs.append(out)
        lack = [s for s in SECTIONS if s not in out]
        if lack:
            fails.append(f"{args}: 缺章节 {lack}")
        # 六冲／六害／六合行不得再出现 E2 旧文案
        for line in out.splitlines():
            if line.startswith("| 六冲") or line.startswith("| 六害") or line.startswith("| 六合"):
                if "E2" in line:
                    fails.append(f"{args}: 关系行仍标 E2 → {line[:60]}")
    rec("R", "R01", not fails, "四组冒烟通过且无 E2 旧文案" if not fails else f"冒烟失败：{fails[:3]}")

    # R05：分析器面向用户的「固定限制」段不得停留在旧状态
    # （Part 15 那次缺陷就是工具文案与数据打架：数据已升 E1，工具仍写 E2。）
    STALE = ["35 例命例图版缺口", "18 条性别口径冲突待裁", "46 格补格未并入",
             "TH-01 仅 31 格条件可用", "85 格待核"]
    stale = []
    for out in outs:
        seg = out.split("固定限制：")[-1].split("## 十五")[0] if "固定限制：" in out else ""
        for ph in STALE:
            if ph in seg:
                stale.append(ph)
    rec("R", "R05", not stale,
        "分析器限制说明与当前状态一致" if not stale else f"限制说明含过时断言：{sorted(set(stale))}")

    # R06：大运诸法在已知例上必须命中——乾造 甲子 乙亥 庚戌 癸未，庚日四柱无申酉，
    # 第七运壬午按 R-SZ-019／020 必为十干败亡运。这条把命书里的关键判断钉成回归。
    dy = ("甲子 乙亥 庚戌 癸未 --gender 男 "
          "--dayun 丙子,丁丑,戊寅,己卯,庚辰,辛巳,壬午,癸未")
    q = subprocess.run([sys.executable, ap] + dy.split(),
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    row = [l for l in q.stdout.splitlines() if l.startswith("| 7 | 壬午")]
    ok = bool(row) and "十干败亡运" in row[0]
    rec("R", "R06", ok,
        "大运诸法在已知例上命中壬午十干败亡运" if ok
        else f"大运诸法未命中预期（exit {q.returncode}，行={row[:1]}）")

    # 非法四柱须拒绝
    bad = subprocess.run([sys.executable, ap, "甲子", "乙丑", "丙寅", "丁卯X"],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    rec("R", "R02", bad.returncode != 0, "非法干支被拒绝" if bad.returncode != 0
        else "非法干支未被拒绝")

    # 三柱须拒绝（不补柱）
    short = subprocess.run([sys.executable, ap, "甲子", "乙丑", "丙寅"],
                           capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    rec("R", "R03", short.returncode != 0, "缺柱输入被拒绝（不补柱）" if short.returncode != 0
        else "缺柱输入未被拒绝")

    # JSON 输出可解析
    p = subprocess.run([sys.executable, ap, "戊辰", "戊午", "甲午", "乙丑", "--json"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    ok = False
    try:
        json.loads(p.stdout)
        ok = True
    except Exception:
        pass
    rec("R", "R04", ok, "--json 输出可解析" if ok else "--json 输出不可解析")


# ---------------- 主流程 ----------------

# ---------------- 排盘与交叉验证（Part 47 新增） ----------------
def check_paipan(skip):
    """R12／R13：排盘器自检与已知盘比对。

    排盘是历法，不是命理，但它一旦错，后面全错。故两项：
      R12 跑 --self-test（日柱双锚点、已知盘、节气落点、顺逆排）；
      R13 拿 1984-11-12 14:00 男 这个已知盘比对四柱与起运，
          该盘四柱（甲子 乙亥 庚戌 癸未）与起运（折 8 年 2 月、1993-02 交运）
          另有独立来源可核，故可作回归锚点。
    """
    if skip:
        rec("R", "R12", True, "已按参数跳过排盘自检", warn_only=True)
        rec("R", "R13", True, "已按参数跳过排盘回归", warn_only=True)
        return
    ap = os.path.join(TOOLS, "paipan.py")
    if not os.path.exists(ap):
        rec("R", "R12", False, "tools/paipan.py 不存在")
        rec("R", "R13", False, "tools/paipan.py 不存在")
        return
    p = subprocess.run([sys.executable, ap, "--self-test"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    ok = p.returncode == 0 and "自检 PASS" in (p.stdout or "")
    rec("R", "R12", ok, "排盘器自检通过（日柱双锚点／已知盘／节气落点／顺逆排）"
        if ok else "排盘器自检失败：%s" % ((p.stdout or "") + (p.stderr or ""))[:200])

    p2 = subprocess.run([sys.executable, ap, "--date", "1984-11-12", "--time", "14:00",
                         "--gender", "男", "--json"],
                        capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    try:
        d = json.loads(p2.stdout)
    except Exception:
        rec("R", "R13", False, "排盘 --json 输出不可解析")
        return
    want = ["甲子", "乙亥", "庚戌", "癸未"]
    bad = []
    if d.get("pillars") != want:
        bad.append("四柱 %s ≠ %s" % (d.get("pillars"), want))
    st = d.get("start") or {}
    if st.get("年") != 8 or not str(st.get("起运日", "")).startswith("1993-02"):
        bad.append("起运 %s 年 / %s 日，应为 8 年 / 1993-02" % (st.get("年"), st.get("起运日")))
    if not d.get("all_pass"):
        bad.append("自检有 FAIL 项")
    rec("R", "R13", not bad, "排盘回归：1984-11-12 14:00 男 → 甲子 乙亥 庚戌 癸未，起运 8 年 1993-02"
        if not bad else "排盘回归不符：%s" % bad)


def check_crosscheck(skip):
    """R14：多因子交叉引擎能出八个判断点，且门槛判定生效。

    这一项守的是「不拿一个信号下结论」这条规矩真的落到了工具上，
    而不是只写在 SKILL.md 里。判据两条：
      ①八个判断点齐出；②每点都有来源数与门槛，
        来源不足门槛者必须出现「信号单薄」字样（否则门槛形同虚设）。
    """
    if skip:
        rec("R", "R14", True, "已按参数跳过交叉验证检查", warn_only=True)
        return
    cp = os.path.join(TOOLS, "crosscheck.py")
    if not os.path.exists(cp):
        rec("R", "R14", False, "tools/crosscheck.py 不存在")
        return
    p = subprocess.run([sys.executable, cp, "甲子", "乙亥", "庚戌", "癸未",
                        "--gender", "男", "--json"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    try:
        rows = json.loads(p.stdout)
    except Exception:
        rec("R", "R14", False, "crosscheck --json 输出不可解析：%s" % (p.stderr or "")[:160])
        return
    want = ["格局", "用神", "婚姻", "子女", "父母", "财富", "健康", "事业学业"]
    got = [r["point"] for r in rows]
    bad = []
    lack = [w for w in want if w not in got]
    if lack:
        bad.append("缺点：%s" % lack)
    for r in rows:
        if not isinstance(r.get("n"), int) or not isinstance(r.get("floor"), int):
            bad.append("%s 无来源数／门槛" % r.get("point"))
        elif r["n"] < r["floor"] and not any("信号单薄" in v for v in r.get("verdict", [])):
            bad.append("%s 来源 %d < 门槛 %d 却未标信号单薄" % (r["point"], r["n"], r["floor"]))
    rec("R", "R14", not bad, "交叉验证：八点齐出，门槛判定生效"
        if not bad else "交叉验证不成立：%s" % bad[:4])


def check_report_check(skip):
    """R15：交付件验收器。守的是「五轨真的能验」，不是「有个文件叫 report_check.py」。

    先跑自检（好坏样本各一，须真的拦得住），再拿真生成的底稿按 C 轨验一遍。
    """
    if skip:
        rec("R", "R15", True, "已按参数跳过交付件验收", warn_only=True)
        return
    rc = os.path.join(TOOLS, "report_check.py")
    ms = os.path.join(TOOLS, "mingshu.py")
    if not (os.path.exists(rc) and os.path.exists(ms)):
        rec("R", "R15", False, "tools/report_check.py 或 mingshu.py 不存在")
        return
    p = subprocess.run([sys.executable, rc, "--self-test"], capture_output=True,
                       text=True, encoding="utf-8", cwd=ROOT)
    if p.returncode != 0:
        rec("R", "R15", False, "验收器自检未过：" + (p.stdout or p.stderr or "").strip()[-160:])
        return
    g = subprocess.run([sys.executable, ms, "甲子", "乙亥", "庚戌", "癸未",
                        "--gender", "男", "--start-age", "10"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if g.returncode != 0:
        rec("R", "R15", False, "命书生成失败，无法验收")
        return
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        fp = os.path.join(d, "详批_甲子乙亥庚戌癸未.md")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(g.stdout or "")
        q = subprocess.run([sys.executable, rc, fp], capture_output=True,
                           text=True, encoding="utf-8", cwd=ROOT)
    if q.returncode != 0:
        rec("R", "R15", False, "底稿按 C 轨验收未过：" + (q.stdout or "").strip()[-200:])
    else:
        rec("R", "R15", True, "验收器自检 6 组通过；命书底稿按 C 轨验收通过")


def check_liunian(skip):
    """R16：流年层。守的是「流年真的落算」，不是「有这一节」。

    用 C01 造（癸巳 戊午 丙午 壬辰）：2027 丁未 须凑成三会巳午未＋双六合；
    2026 丙午 与日柱伏吟、午午自刑，按纪律只记不作断。
    """
    if skip:
        rec("R", "R16", True, "已按参数跳过流年层", warn_only=True)
        return
    ap = os.path.join(TOOLS, "analyze.py")
    if not os.path.exists(ap):
        rec("R", "R16", False, "tools/analyze.py 不存在")
        return
    p = subprocess.run([sys.executable, ap, "癸巳", "戊午", "丙午", "壬辰",
                        "--gender", "男", "--dayun", "己未,庚申,辛酉,壬戌",
                        "--birth-year", "1953", "--start-age", "10",
                        "--liunian", "2026,2027,2028"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if p.returncode != 0:
        rec("R", "R16", False, "流年层运行失败：" + (p.stderr or "").strip()[:160])
        return
    out = p.stdout or ""
    miss = [x for x in ("## 十、流年", "三会巳午未", "双六合", "R164", "R126",
                        "只记不作断") if x not in out]
    if miss:
        rec("R", "R16", False, "流年层缺项：" + "、".join(miss))
    else:
        rec("R", "R16", True, "流年层：丁未凑三会＋双六合，丙午伏吟自刑只记不断")


def check_report_templates(skip):
    """R17：报告模板与生成器。守的是「十九板块能真跑」，不是「有一份规格文档」。

    三步，缺一不可：
      1. 模板文件在（CSS 与生成器）；
      2. 骨架能生成，且**必须**被判不合格（B01 齐备、B06 待批未清）——
         骨架若也能过，验收器就等于没有；
      3. 已填好的范文必须过（B01～B06 全绿）。
    """
    if skip:
        rec("R", "R17", True, "已按参数跳过报告模板", warn_only=True)
        return
    css = os.path.join(ROOT, "references", "templates", "report.css")
    gen = os.path.join(TOOLS, "report_gen.py")
    rc = os.path.join(TOOLS, "report_check.py")
    if not os.path.exists(css):
        rec("R", "R17", False, "references/templates/report.css 不存在")
        return
    if not (os.path.exists(gen) and os.path.exists(rc)):
        rec("R", "R17", False, "tools/report_gen.py 或 report_check.py 不存在")
        return

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sk = os.path.join(d, "骨架.md")
        g = subprocess.run([sys.executable, gen, "癸巳", "戊午", "丙午", "壬辰",
                            "--gender", "男", "--dayun", "己未,庚申,辛酉,壬戌",
                            "--birth-year", "1953", "--start-age", "10",
                            "--liunian", "2026,2027", "--out", sk],
                           capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        if g.returncode != 0:
            rec("R", "R17", False, "报告骨架生成失败：" + (g.stderr or "").strip()[-160:])
            return
        q = subprocess.run([sys.executable, rc, sk, "--type", "report"],
                           capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        out = (q.stdout or "") + (q.stderr or "")
        if q.returncode == 0:
            rec("R", "R17", False, "骨架未填却通过验收——B06 未生效，验收形同虚设")
            return
        if "B01" not in out or "FAIL B06" not in out:
            rec("R", "R17", False, "骨架验收未见 B01 通过＋B06 拦截")
            return

    sample = os.path.join(ROOT, "_命书", "报告_癸巳戊午丙午壬辰.md")
    if not os.path.exists(sample):
        rec("R", "R17", False, "填写范例 _命书/报告_癸巳戊午丙午壬辰.md 不存在")
        return
    q2 = subprocess.run([sys.executable, rc, sample, "--type", "report"],
                        capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if q2.returncode != 0:
        rec("R", "R17", False, "填写范例未过 B 轨：" + (q2.stdout or "").strip()[-200:])
    else:
        rec("R", "R17", True, "模板在；骨架生成即被 B06 拦住；填写范例 B 轨全过")


# 书号 → source_manifest 里的来源编号。书号是给人看的（JC＝基础概要），
# 来源编号是给台账对账的（30），两套编号不同源，须显式映射，不能拼字符串硬凑。
SRC_OF_BOOK = {
    "XC": "SRC-LXTEXT-XC", "NV": "SRC-LXTEXT-NV", "DC": "SRC-LXTEXT-DC",
    "JC": "SRC-LXTEXT-30", "MF": "SRC-LXTEXT-02", "XP": "SRC-LXTEXT-01",
    "SS": "SRC-LXTEXT-12", "JB": "SRC-LXTEXT-23", "YH": "SRC-LXTEXT-09",
    "SZ": "SRC-LXTEXT-20",
}


def check_corpus(skip):
    """R18／R19：六书台账与检索器。

    R18 守的是「台账不许说过头」：INDEX.md 里写了哪本书已全文入库、多少页，
          那么全文文件必须在、页数必须对得上、检索器必须认这个书号、
          source_manifest 必须有对应来源行。四处缺一，台账就是虚的。
    R19 守的是「检索器真能查」：实跑一次 --list 与一次命中检索，
          命中行必须带得出 `书号:p页码` 形式的 locator——
          这是本包「断语可回查」的唯一通路，坏了整条证据链就断了。
    """
    if skip:
        rec("R", "R18", True, "已按参数跳过六书台账", warn_only=True)
        rec("R", "R19", True, "已按参数跳过检索器", warn_only=True)
        return
    if not os.path.exists(VERIFY_DB):
        # 全文类底本不随包分发（版权）：公开仓克隆环境无核验库，
        # 台账与检索器都以其为底，两项记 skip——本地全量环境照常跑。
        rec("R", "R18", True, "引文核验库未随包分发（版权），六书台账跳过", warn_only=True)
        rec("R", "R19", True, "引文核验库未随包分发（版权），检索器跳过", warn_only=True)
        return
    idx = os.path.join(ROOT, "references", "corpus", "INDEX.md")
    if not os.path.exists(idx):
        rec("R", "R18", False, "references/corpus/INDEX.md 不存在（六书台账缺失）")
        rec("R", "R19", False, "六书台账缺失，检索器无从对账")
        return
    text = io.open(idx, encoding="utf-8").read()

    # 台账「已全文入库」表：| 书号 | 书 | 版本／页数 | 全文文件 | 已抽规则 | 证据级 |
    src_ids = {g(r, "source_id") for r in load("source_manifest.csv")[1]}
    searcher = io.open(os.path.join(TOOLS, "corpus_search.py"), encoding="utf-8").read()
    bad = []
    seen = 0
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cell = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cell) < 4:
            continue
        bid, ver, ftxt = cell[0], cell[2], cell[3]
        if not re.fullmatch(r"[A-Z]{2}", bid or ""):
            continue
        if "data/" not in ftxt:
            continue
        seen += 1
        m = re.search(r"(\d+)\s*页", ver)
        pages_claim = int(m.group(1)) if m else None
        fpath = re.match(r"`([^`]+)`", ftxt)
        fname = fpath.group(1) if fpath else ftxt.strip("`").split("（")[0]
        fp = os.path.join(ROOT, fname)
        if not os.path.exists(fp):
            bad.append(f"{bid} 核验库文件不存在：{fname}")
            continue
        # 页数按**该书段**计：核验库并置十二书、页号各自从 1 起，
        # 全库页标总数与任何一本书的页数都不相干。
        bpages, _h = _load_book(bid)
        n = len(bpages)
        if pages_claim and n != pages_claim:
            bad.append(f"{bid} 台账称 {pages_claim} 页、核验库实载 {n} 页")
        if f'"{bid}"' not in searcher:
            bad.append(f"{bid} 未登记进 corpus_search.py")
        sid = SRC_OF_BOOK.get(bid, f"SRC-LXTEXT-{bid}")
        if sid not in src_ids:
            bad.append(f"{bid} 未登记 source_manifest（应为 {sid}）")
    if seen == 0:
        rec("R", "R18", False, "台账里读不出任何「已入核验库」行（表格格式变了？）")
    else:
        rec("R", "R18", not bad,
            f"六书台账 {seen} 本与核验库／检索器／来源登记四方一致" if not bad
            else "台账与实际不符：" + "；".join(bad[:4]))

    q = subprocess.run([sys.executable, os.path.join(TOOLS, "corpus_search.py"), "--list"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if q.returncode != 0:
        rec("R", "R19", False, "corpus_search --list 失败：" + (q.stderr or "").strip()[:120])
        return
    listed = len(re.findall(r"^\s+[A-Z]{2}\s+《", q.stdout or "", re.M))
    q2 = subprocess.run([sys.executable, os.path.join(TOOLS, "corpus_search.py"),
                         "四角方阵", "--limit", "3"],
                        capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    hit_ok = bool(re.search(r"XC:p\d{2,4}\s", q2.stdout or ""))
    rec("R", "R19", listed >= 6 and hit_ok,
        f"检索器可用：{listed} 本可查，命中行带 XC:pNNN 型 locator" if (listed >= 6 and hit_ok)
        else f"检索器异常：书目 {listed} 本、locator 判定 {'通过' if hit_ok else '未命中'}")


def check_shensha_sp(skip):
    """R20：神煞探源起例器（R-SP-001～049）。

    守两件事：
      ① **账实相符**——`rules.csv` 里的 `R-SP-*` 与`起例器里的条数、ID 必须一一对齐。
         库里有而器里无，是死规则（能查不能用）；器里有而库里无，是野规则（没出处）。
      ② **自检真跑得过**——起例表抄错一个字、错一个地支，自检当场炸。
         五见门槛、旬空、纳音、阴阳男女前后一位这几处最易错，均有断言覆盖。
    另查状态值域：判定结果只许落在这六种之内，防止出现「模糊通过」。
    """
    path = os.path.join(TOOLS, "shensha_calc.py")
    if not os.path.exists(path):
        rec("R", "R20", False, "tools/shensha_calc.py 不存在（神煞探源起例器缺失）")
        return

    sys.path.insert(0, TOOLS)
    try:
        import shensha_calc as SC
    except Exception as e:                                    # noqa: BLE001
        rec("R", "R20", False, f"shensha_calc 导入失败：{e}")
        return

    db_ids = {r["rule_id"] for r in load("rules.csv")[1] if r["rule_id"].startswith("R-SP-")}
    sp_ids = {x[0] for x in SC.SPECS}
    lost, ghost = sorted(db_ids - sp_ids), sorted(sp_ids - db_ids)
    ok_align = not lost and not ghost and len(sp_ids) == 49
    msg = (f"49 条 R-SP 与 rules.csv 一一对齐" if ok_align
           else "起例器与规则库不符："
                + "；".join(x for x in (
                    f"器里缺 {len(lost)} 条（{','.join(lost[:3])}）" if lost else "",
                    f"器里多 {len(ghost)} 条（{','.join(ghost[:3])}）" if ghost else "",
                    f"实有 {len(sp_ids)} 条" if len(sp_ids) != 49 else "") if x))

    allowed = {SC.HIT, SC.MISS, SC.NA, SC.MANUAL, SC.TEXT, SC.NOTE}
    res = SC.evaluate(("甲子", "乙亥", "庚戌", "癸未"), gender="男")
    badst = sorted({r["status"] for r in res} - allowed)
    ok_status = (len(res) == 49 and not badst)
    if not ok_status:
        msg += f"；状态值域异常（{'、'.join(badst) or '条数不足'}）"

    if skip:
        rec("R", "R20", ok_align and ok_status, msg, warn_only=True)
        return
    q = subprocess.run([sys.executable, path, "--self-test"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    ok_self = q.returncode == 0 and "PASS" in (q.stdout or "")
    if not ok_self:
        tail = ((q.stdout or "") + (q.stderr or "")).strip().splitlines()[-2:]
        msg += "；自检失败：" + "／".join(tail)[:160]
    rec("R", "R20", ok_align and ok_status and ok_self, msg)


def check_report_gate():
    """R21：交付闸的十一项不得被删。

    B01–B11 是「报告能不能算交付件」的判据：板块齐、逐节挂证、无星级、
    证据成数、字数底线、无待批、卷首流程卡、存疑与反证、下篇强度、无绝对断言、
    索引与正文对账。任何一项被悄悄摘掉，闸门就会变松而表面仍报 PASS——
    这一条专门盯这种「越改越松」。另验自检真跑得过：好坏样本各一，好必过、坏必拦。
    """
    path = os.path.join(TOOLS, "report_check.py")
    if not os.path.exists(path):
        rec("R", "R21", False, "tools/report_check.py 不存在")
        return
    src = io.open(path, encoding="utf-8").read()
    need = ["B0%d" % i for i in range(1, 10)] + ["B10", "B11"]
    lack = [x for x in need if ('"%s"' % x) not in src]
    if lack:
        rec("R", "R21", False, "交付闸缺项：" + "、".join(lack))
        return
    p = subprocess.run([sys.executable, path, "--self-test"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = p.returncode == 0 and "PASS" in (p.stdout or "")
    rec("R", "R21", ok, "交付闸十一项齐备，自检好必过／坏必拦" if ok
        else "交付闸自检未过：" + (p.stdout or p.stderr or "")[-160:])

def check_panduan():
    """R22：批命推演器（panduan.py）——推演稿得真出得来，且不许掉回台账。

    analyze.py 以资料为纲，panduan.py 以判断为纲。这一条守三件事：
    ① 自检跑得过（男女两盘都要出）；
    ② 十项优先一项不缺——次序是梁氏批命的生死线，少一项就退回「检索拼装」；
    ③ 非 trace 输出不许出现 rule_id——对客看的是理，编号归底稿。
    """
    path = os.path.join(TOOLS, "panduan.py")
    if not os.path.exists(path):
        rec("R", "R22", False, "tools/panduan.py 不存在（批命推演器缺失）")
        return
    src = io.open(path, encoding="utf-8").read()
    need = ["十项优先", "星宫合参", "用神落定", "落笔须知", "_strip_ids", "core_conflict",
            "from-paipan"]
    lack = [x for x in need if x not in src]
    if lack:
        rec("R", "R22", False, "推演器缺构件：" + "、".join(lack))
        return
    p2 = subprocess.run([sys.executable, path, "--self-test"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = p2.returncode == 0 and "全部通过" in (p2.stdout or "")
    rec("R", "R22", ok, "推演器自检全过：十项不缺、男女两盘、近五年定位、无编号外泄" if ok
        else "推演器自检未过：" + (p2.stdout or p2.stderr or "")[-200:])


def check_trace_audit():
    """R25：判断点→条文的「边」——一致率算得出来，且点表与推演器不脱节。

    这一条守的是「可复核」三个字：panduan 说每点「依什么理」，那是散文；
    point_rules.csv 把散文变成编号边，trace_audit 再把它算成数。
    ① 点表与 build_trace 的 pid 集合必须一致——点表多出的是死边，推演器多出的是无据之点；
    ② 每点须有依据说明（basis_note），否则「凭什么算依据」无从复核；
    ③ 审计器得跑得通，且接线率不得低于九成（掉下来说明边被删了）。
    """
    tool = os.path.join(TOOLS, "trace_audit.py")
    pr = os.path.join(ROOT, "data", "point_rules.csv")
    if not os.path.exists(tool) or not os.path.exists(pr):
        rec("R", "R25", False, "缺 trace_audit.py 或 point_rules.csv（一致率无从计算）")
        return
    p2 = subprocess.run([sys.executable, tool, "--limit", "1", "--json"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p2.returncode != 0:
        rec("R", "R25", False, "审计器跑不通：" + (p2.stderr or "")[-200:])
        return
    try:
        lived = {x["pid"] for x in json.loads(p2.stdout)["cases"][0]["points"]}
    except Exception as e:                                   # noqa: BLE001
        rec("R", "R25", False, "审计器输出不可解析：%s" % e)
        return
    w = list(csv.DictReader(io.open(pr, encoding="utf-8-sig")))
    tabled = {r["pid"] for r in w}
    lack_note = [r["pid"] for r in w if not (r.get("basis_note") or "").strip()
                 and (r.get("rule_ids") or "").strip()]
    bad = []
    if tabled - lived:
        bad.append("点表多出死边：" + "、".join(sorted(tabled - lived)))
    if lived - tabled:
        bad.append("推演器有无据之点：" + "、".join(sorted(lived - tabled)))
    if lack_note:
        bad.append("无边据说明：" + "、".join(lack_note))
    if bad:
        rec("R", "R25", False, "；".join(bad))
        return
    p3 = subprocess.run([sys.executable, tool], capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    m = re.search(r"接线 ([\d.]+)%", p3.stdout or "")
    rate = float(m.group(1)) if m else 0.0
    rec("R", "R25", rate >= 90.0,
        "点表与推演器一致（%d 点），接线率 %.1f%%" % (len(tabled), rate)
        if rate >= 90.0 else "接线率跌到 %.1f%%，低于九成——边被删了" % rate)


def check_feedback():
    """R27：复核版命书的结构守护——纠偏机制不许走样。

    三处死守：① 每个复核节必须引用「原断」（复核版不许无断语空转）；
    ② 「反馈·偏差」节必须有批者注记且含「不改通则」（个案不得偷改通则）；
    ③ 给命主的文本（问单／复核版）不得出现工程编号 Rxxxx（编号只在批者存档节）。
    """
    fp = os.path.join(ROOT, "_命书", "复核_甲子乙亥庚戌癸未.md")
    fq = os.path.join(ROOT, "_命书", "回执问单_甲子乙亥庚戌癸未.md")
    if not (os.path.exists(fp) and os.path.exists(fq)):
        rec("R", "R27", False, "缺复核样例或问单样例")
        return
    bad = []
    txt = io.open(fp, encoding="utf-8").read()
    secs = re.split(r"\n### ", txt)[1:]
    n_dev = 0
    for sec in secs:
        name = sec.split("\n", 1)[0]
        if "原断" not in sec:
            bad.append("复核节「%s」没有原断引用" % name)
        if "反馈·偏差" in name:
            n_dev += 1
            if "批者注记" not in sec:
                bad.append("偏差节「%s」缺批者注记" % name)
            elif "不改通则" not in sec:
                bad.append("偏差节「%s」注记未写明不改通则" % name)
    if "校准依据" not in txt:
        bad.append("复核版末尾缺「校准依据」存档节")
    # 正文给命主的部分（### 节与回执）不得带工程编号；存档节除外
    body = txt.split("## 校准依据")[0]
    for m in re.finditer(r"R-[A-Z]{2,}-\d+|R\d{2,}", body):
        bad.append("复核版正文出现工程编号 %s（编号只许在存档节）" % m.group(0))
        break
    qtxt = io.open(fq, encoding="utf-8").read()
    if "命主判断" not in qtxt or "| q01 |" not in qtxt:
        bad.append("问单样例缺表头或编号行")
    for m in re.finditer(r"R-[A-Z]{2,}-\d+|R\d{2,}", qtxt):
        bad.append("问单出现工程编号 %s" % m.group(0))
        break
    if bad:
        rec("R", "R27", False, "回访纠偏走样：" + "; ".join(bad))
    else:
        rec("R", "R27", True, "回访纠偏：复核 %d 节（偏差 %d）、问单编号 %d 行" % (
            len(secs), n_dev, len(re.findall(r"\| q\d+ \|", qtxt))))


def check_yun_spans():
    """R26：命书与批词的「运界岁数」必须连号——抓「改了七处漏一处」。

    为什么单列一条：起运虚岁与「起运折几年几月」差一两年，是这包最容易犯、
    也最会直接批错的错（v1.8 就栽在这里）。改岁数时最常出的不是算错，是**漏改**——
    八运改了七运，来客一对照自己的年龄就发现。此条只查算术与连号，不查真值：
    「N岁至M岁」须 M−N=9，且下一运的 N 须等于上一运的 M+1；文首「N岁起运」须等于首运 N。
    """
    import glob
    files = sorted(glob.glob(os.path.join(ROOT, "_命书", "批词_*.md")))
    files += sorted(glob.glob(os.path.join(ROOT, "_命书", "命书_*.html")))
    if not files:
        rec("R", "R26", False, "找不到批词或命书，运界无从核")
        return
    def cn(s):
        """中文数词转整数：十、十九、二十、二十九、一百。「十」单用作十。"""
        d = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}
        if s == "十":
            return 10
        if "十" in s:
            a, _, b = s.partition("十")
            return (d.get(a, 1) if a else 1) * 10 + (d.get(b, 0) if b else 0)
        return d.get(s, 0)

    bad, seen = [], 0
    for fp in files:
        name = os.path.basename(fp)
        txt = io.open(fp, encoding="utf-8", errors="replace").read()
        spans = []
        for a, b in re.findall(r"[（(]([一二三四五六七八九十]+)岁至([一二三四五六七八九十]+)岁[)）]", txt):
            spans.append((cn(a), cn(b)))
        if not spans:
            continue
        seen += 1
        for a, b in spans:
            if b - a != 9:
                bad.append("%s 运界「%d至%d」不是十年" % (name, a, b))
        for i in range(1, len(spans)):
            if spans[i][0] != spans[i - 1][1] + 1:
                bad.append("%s 第%d运起于%d岁，应接上一运的%d岁"
                           % (name, i + 1, spans[i][0], spans[i - 1][1] + 1))
        m = re.search(r"([一二三四五六七八九十]+)岁起运", txt)
        if m and cn(m.group(1)) != spans[0][0]:
            bad.append("%s 文首称%s岁起运，首个运界却是%d岁"
                       % (name, m.group(1), spans[0][0]))
    if not seen:
        rec("R", "R26", False, "批词与命书里一处运界岁数都没有——查不到即不算过")
        return
    rec("R", "R26", not bad,
        "%d 件运界连号（每运十年、首尾相接、与文首起运岁相符）" % seen
        if not bad else "；".join(bad))


def check_deliver_guard():
    """R28：交付件动态层守护——抓批运时的三类硬错。

    一次真实复核（2026-11，甲子乙亥庚戌癸未盘）量出的错漏全在岁运动态层，
    原局层几乎无错。本项抓三类最容易出硬错的位置：
    ① 否定断语 guard——「无涉／不相干／互不相犯」这类句子，若三层关系矩阵
      （原局×原局、运×原局、运×流年）跑全了就不会写出来：原局两支作势、
      运年补第三支即成局成刑，不得降级为「不相涉」。旧稿写「丑与月支亥无涉」，
      而亥子＋丑正成北方三会——本项即为此设。
    ② 调候次序 guard——「并列不分正副」等于未定次序；调候字须挂十神身份
      （丁是正官、丙是七杀），不得按五行当一个字用。
    ③ 表文对应——流年举要表里出现的每个年份，正文须有对应批语；只给结构
      标签不给正文，等于让来客自己猜。
    """
    prose_dir = os.path.join(ROOT, "_命书")
    files = sorted(glob.glob(os.path.join(prose_dir, "批词_*.md")))
    if not files:
        rec("R", "R28", False, "_命书/ 下无批词样例，动态层守护无从查")
        return
    bad = []
    for prose in files:
        txt = io.open(prose, encoding="utf-8", errors="replace").read()
        tag = os.path.basename(prose)
        for w in ("无涉", "不相干", "互不相犯", "并列不分正副"):
            if w in txt:
                bad.append("%s 出现禁句「%s」" % (tag, w))
        # 流年表年份（二〇三〇、二〇三一等）须在正文有对应批语段
        for y in range(2026, 2032):
            cn_y = "".join("〇一二三四五六七八九"[int(c)] for c in str(y))
            if ("{{流年表}}" in txt) and (cn_y not in txt):
                bad.append("%s 流年表含 %d 年，正文无对应批语" % (tag, y))
    rec("R", "R28", not bad,
        "动态层守护过（%d 份批词）：无否定断语禁句、调候字挂十神、流年逐年有批语"
        % len(files) if not bad else "；".join(bad))


def check_promo_tail():
    """R29：赞赏尾注守护——机制参考徐子平BOT v0.10.3。

    每个命盘一次的赞赏二维码＋苍盘体验邀请。查四件事：素材图在位且非空；
    规则文档含纯文字保底（微信号）、体验链接、同盘一次、三档降级四要素；
    交互文档挂了尾注节；实录里有尾注演示。
    """
    bad = []
    img = os.path.join(ROOT, "references", "assets", "appreciation.jpg")
    if not os.path.exists(img) or os.path.getsize(img) < 10240:
        bad.append("赞赏二维码素材缺失或过小（%s）" % img)
    doc = os.path.join(ROOT, "references", "推广尾注.md")
    if os.path.exists(doc):
        txt = io.open(doc, encoding="utf-8", errors="replace").read()
        for k, kw in (("微信号保底", "cpms1988"), ("体验链接", "mp.weixin.qq.com"),
                      ("同盘一次", "每个命盘一次"), ("三档降级", "三档降级")):
            if kw not in txt:
                bad.append("推广尾注规则缺「%s」（%s）" % (k, kw))
    else:
        bad.append("references/推广尾注.md 不存在")
    flow = io.open(os.path.join(ROOT, "references", "interaction_flow.md"),
                   encoding="utf-8", errors="replace").read()
    if "赞赏尾注" not in flow:
        bad.append("interaction_flow.md 未挂赞赏尾注节")
    demo = io.open(os.path.join(ROOT, "references", "demo_session.md"),
                   encoding="utf-8", errors="replace").read()
    if "赞赏尾注" not in demo:
        bad.append("demo_session.md 无尾注演示")
    # 执行顺序硬步骤：SKILL.md 是任何 agent 的必读入口——尾注若只躺在参考
    # 文档里，外部 agent 跑管线不出参考文档就永远不会出尾注（2026-11-02 实测）。
    sk = io.open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8", errors="replace").read()
    if "交付尾注（硬步骤" not in sk or "禁止编造二维码" not in sk:
        bad.append("SKILL.md 执行顺序缺「交付尾注」硬步骤")
    # 命书嵌入：mingshu.py 须含内嵌逻辑，命书样例 HTML 须真嵌了推广块
    ms = io.open(os.path.join(ROOT, "tools", "mingshu.py"),
                 encoding="utf-8", errors="replace").read()
    for kw in ("_promo_html", "appreciation.jpg", "data:image/jpeg;base64", "苍盘",
               "梁湘润体系分析结果"):
        if kw not in ms:
            bad.append("mingshu.py 缺命书嵌入要素「%s」" % kw)
    ms_htmls = sorted(glob.glob(os.path.join(ROOT, "_命书", "命书_*.html")))
    if ms_htmls:
        h = io.open(ms_htmls[0], encoding="utf-8", errors="replace").read()
        if 'class="promo"' not in h or "数千现代真人命例" not in h:
            bad.append("%s 未嵌推广块或苍盘介绍" % os.path.basename(ms_htmls[0]))
        elif "data:image/jpeg;base64" not in h:
            bad.append("%s 二维码未内嵌（base64 缺失）" % os.path.basename(ms_htmls[0]))
    rec("R", "R29", not bad,
        "赞赏尾注守护过：素材在位、四要素齐、交互与实录已挂、命书已嵌"
        if not bad else "；".join(bad))


def check_xingqing():
    """R23：心性库——十神心性得真出得来，且不许讲原书没讲的话。

    这一条守四件事：
    ① 库齐十神，一个不缺；每神至少两条（一条泛说、一条专说）；
    ② 自检跑得过（四盘男女老少皆出）；
    ③ 总断不夹编号、不留空；
    ④ 条目须落在「人如何」上，凡讲某位六亲如何者，一律不该在这张表里。
    """
    path = os.path.join(ROOT, "data", "xingqing.csv")
    if not os.path.exists(path):
        rec("R", "R23", False, "缺 data/xingqing.csv（十神心性库）")
        return
    rows = list(csv.DictReader(io.open(path, encoding="utf-8-sig")))
    gods = ["比肩", "劫财", "食神", "伤官", "偏财", "正财", "七杀", "正官", "偏印", "正印"]
    cnt = {}
    for r in rows:
        cnt[(r.get("god") or "").strip()] = cnt.get((r.get("god") or "").strip(), 0) + 1
    lack = [g for g in gods if cnt.get(g, 0) < 2]
    if lack:
        rec("R", "R23", False, "心性库条目不足（每神须≥2 条）：" + "、".join(lack))
        return
    # 六亲类断语不得混入性情库
    leak = []
    for r in rows:
        t = (r.get("text") or "")
        if any(k in t for k in ("离婚", "分居", "克子", "伤夫", "头胎", "再婚", "祖产")):
            leak.append((r.get("xq_id") or "?"))
    if leak:
        rec("R", "R23", False, "心性库混入六亲断语（应归六亲节）：" + "、".join(leak[:5]))
        return
    p2 = subprocess.run([sys.executable, os.path.join(TOOLS, "xingqing.py")],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = p2.returncode == 0 and "全部通过" in (p2.stdout or "")
    rec("R", "R23", ok,
        "心性库 %d 条，十神齐备，四盘自检全过" % len(rows) if ok
        else "心性库自检未过：" + (p2.stdout or p2.stderr or "")[-200:])


def check_liuqin():
    """R24：六亲库——出身／父母／兄弟三段得真出得来，且不许拿泛论充数。

    守三件事：
    ① 旬空算得对（甲子旬空戌亥、甲辰旬空寅卯这类定点要对）；
    ② 库中不得混入「先丧母／先丧父」那组清代泛论断语——它们只作提示，不进命书；
    ③ 自检跑得过。
    """
    path = os.path.join(ROOT, "data", "liuqin.csv")
    if not os.path.exists(path):
        rec("R", "R24", False, "缺 data/liuqin.csv（六亲库）")
        return
    rows = list(csv.DictReader(io.open(path, encoding="utf-8-sig")))
    if len(rows) < 12:
        rec("R", "R24", False, "六亲库条目过少（%d，须≥12）" % len(rows))
        return
    # 清代泛论不得进库
    bad = [r.get("xq_id", "?") for r in rows
           if any(k in (r.get("text") or "") for k in ("先丧母", "先丧父", "庶出传人", "骨肉分离"))]
    if bad:
        rec("R", "R24", False, "六亲库混入清代泛论断语（只作提示，不进命书）：" + "、".join(bad[:5]))
        return
    p2 = subprocess.run([sys.executable, os.path.join(TOOLS, "liuqin.py")],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = p2.returncode == 0 and "全部通过" in (p2.stdout or "")
    rec("R", "R24", ok,
        "六亲库 %d 条，旬空定点准，四盘自检全过" % len(rows) if ok
        else "六亲库自检未过：" + (p2.stdout or p2.stderr or "")[-200:])


def check_doc_claims(counts):
    """C07：散见断言对账。

    C04／C06 只查「规模／分母表」那种 `| 标签 | 数字 |` 的行，正文里的
    「7 组 59 项」「PASS 59」「conflicts=55」「crosswalk 2,936 条」却查不到——
    Part 18 把 conflicts 54→55、crosswalk 2935→2936 之后，README／QA／
    INTEGRATION_STATUS 的正文断言就各自漂了一版。本项把这类断言纳入复跑范围。

    只查「当前状态」文档；CHANGELOG／PATCH_SUMMARY／TOTAL_ASSEMBLY 属历史记录，
    允许保留当时的数字。
    """
    if not os.path.exists(VERIFY_DB):
        # 公开仓克隆环境（引文核验库未随包分发）少两项 R 记录，数字天然对不上
        # 本地全量环境——非全量环境跳过对账，不算漂移。
        rec("C", "C07", True, "非全量环境（核验库未随包分发），数字对账跳过", warn_only=True)
        return
    # C07 自身尚未入 RESULTS，故总数与 PASS 数各 +1
    total = len(RESULTS) + 1
    n_pass = sum(1 for x in RESULTS if x[2] == "PASS") + 1
    docs = ["SKILL.md", "README.md", "INTEGRATION_STATUS.md", "QA.md"]
    bad = []
    n_xq = n_lq = 0
    for fn, key in (("xingqing.csv", "xq"), ("liuqin.csv", "lq")):
        fp = os.path.join(ROOT, "data", fn)
        if os.path.exists(fp):
            k = sum(1 for _ in csv.DictReader(io.open(fp, encoding="utf-8-sig")))
            if key == "xq":
                n_xq = k
            else:
                n_lq = k
    for name in docs:
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        doc = io.open(path, encoding="utf-8").read()
        # 历史快照行（含「当轮」）保留当时数字，不参与对账。
        # 否则 Part 50 把 conflicts 62→63 之后，上一轮的「当轮 PASS 76…conflicts=62」
        # 会被判成漂移——它记录的本来就不是当前值。
        doc = "\n".join(ln for ln in doc.split("\n") if "当轮" not in ln)
        for m in re.finditer(r"组\s*(\d+)\s*项", doc):
            if int(m.group(1)) != total:
                bad.append(f"{name} 称 {m.group(1)} 项，实为 {total}")
        for m in re.finditer(r"PASS\s*(\d+)\s*[｜|/／]", doc):
            if int(m.group(1)) != n_pass:
                bad.append(f"{name} 称 PASS {m.group(1)}，实为 {n_pass}")
        for m in re.finditer(r"conflicts=(\d+)", doc):
            if int(m.group(1)) != counts["conflicts"]:
                bad.append(f"{name} 称 conflicts={m.group(1)}，实为 {counts['conflicts']}")
        for m in re.finditer(r"crosswalk=([\d,]+)", doc):
            if int(m.group(1).replace(",", "")) != counts["crosswalk"]:
                bad.append(f"{name} 称 crosswalk={m.group(1)}，实为 {counts['crosswalk']}")
        # ③ 条数／轨数（P13 加）。P13 复核时手抓到三类漂移：状态行仍写 v1.7、
        #    心性库写 69 而实载 68、「交付分五轨」与「交付六轨」并存。
        #    数字类断言此前只覆盖组／PASS／conflicts／crosswalk，故抓不到。
        for pat, real, what in (
                (r"(\d+)\s*心性条", n_xq, "心性条"),
                (r"十神心性库（(\d+) 条", n_xq, "心性库条数"),
                (r"六亲库（(\d+) 条", n_lq, "六亲库条数")):
            for m in re.finditer(pat, doc):
                if int(m.group(1)) != real:
                    bad.append(f"{name} 称 {m.group(1)} {what}，实载 {real}")
        if re.search(r"交付分?五轨", doc):
            bad.append(f"{name} 仍称「交付五轨」，现行为六轨（P11／v1.6 起）")
        # ④ 判断点数与一致率四数（P15 加）。这类数字最易漂：改一条边就动一格，
        #    而文档里的百分比是手抄的。故与 point_rules 实载、trace_audit 实跑对账。
        for m in re.finditer(r"(\d+)\s*点[、，]", doc):
            n_pt = len(list(csv.DictReader(io.open(os.path.join(ROOT, "data", "point_rules.csv"),
                                                  encoding="utf-8-sig"))))
            if int(m.group(1)) not in (n_pt, n_pt - 1, n_pt + 1):
                bad.append(f"{name} 称 {m.group(1)} 点，点表实载 {n_pt}")
    # 一致率四数只查一次（全量审计约 2 秒，不必每份文档跑一遍）
    ta = os.path.join(TOOLS, "trace_audit.py")
    if os.path.exists(ta):
        p4 = subprocess.run([sys.executable, ta, "--json"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        try:
            sm = json.loads(p4.stdout)["summary"]
        except Exception:                                     # noqa: BLE001
            sm = None
        if sm:
            want = (("接线率", 100 * sm["basis_rate"]),
                    ("落地率", 100 * sm["sent_rate"]),
                    ("梁氏召回", 100 * (sm["recall"] or 0)),
                    ("主题呼应", 100 * (sm["topic_recall"] or 0)))
            for name in docs:
                path = os.path.join(ROOT, name)
                if not os.path.exists(path):
                    continue
                doc = io.open(path, encoding="utf-8").read()
                doc = "\n".join(ln for ln in doc.split("\n") if "当轮" not in ln)
                for k, v in want:
                    # 只认「接线率 92.0%」这种实值；「≥90%」是门槛，不是断言
                    for m in re.finditer(k + r"[^\n]{0,14}?(?<![≥＞>\d.])([\d.]+)%", doc):
                        if abs(float(m.group(1)) - v) > 0.15:
                            bad.append("%s 称%s %s%%，实为 %.1f%%"
                                       % (name, k, m.group(1), v))
    rec("C", "C07", not bad,
        "当前状态文档的正文断言与实载一致" if not bad else "正文断言漂移：" + "；".join(bad))
    return not bad


def check_indices(counts):
    """S05：索引文档与元数据一致。

    Part 15 修过「NM-TBL-09 表题空缺」，但 references/tables/index.md 是修前生成的，
    修完后索引仍印「｜｜27格」——数据补了、检索面没补。本项守这一处回归。
    """
    bad = []
    tp = os.path.join(ROOT, "references", "tables", "index.md")
    cp = os.path.join(ROOT, "references", "cases", "index.md")
    if os.path.exists(tp):
        lines = [l for l in io.open(tp, encoding="utf-8").read().split("\n") if l.startswith("- **")]
        empty = [l[:40] for l in lines if "｜｜" in l]
        if empty:
            bad.append(f"tables/index.md 表题空缺 {len(empty)} 行：{empty[:3]}")
        if len(lines) != counts["tables"]:
            bad.append(f"tables/index.md 行数 {len(lines)} != 表级 {counts['tables']}")
    else:
        bad.append("tables/index.md 不存在")
    if os.path.exists(cp):
        lines = [l for l in io.open(cp, encoding="utf-8").read().split("\n") if l.startswith("- **")]
        if len(lines) != counts["cases"]:
            bad.append(f"cases/index.md 行数 {len(lines)} != 命例 {counts['cases']}")
    else:
        bad.append("cases/index.md 不存在")
    rec("S", "S05", not bad,
        "索引文档与元数据一致" if not bad else "索引与数据不一致：" + "；".join(bad))
    return not bad


def check_subtitle_check(counts):
    """C08：字幕内容核对表与规则表／集数表对账。

    新加的 `data/subtitle_content_check.csv`（32 集）与
    `data/subtitle_episode_coverage.csv`（38 集）是「知识点 ↔ 内容核心」核对的结果面。
    这两张表若与 `rules.csv` 的 LX38 定位数、或与 `video_episode_map.csv` 的集数
    对不上，说明核对表是旧版／手改过的，检索面会给出错的结论。
    """
    bad = []
    p1 = os.path.join(DATA, "subtitle_content_check.csv")
    p2 = os.path.join(DATA, "subtitle_episode_coverage.csv")
    ok_verdicts = {"一致", "一致（转述）", "部分一致", "待核", "缺字幕"}
    rows1 = rows2 = []
    if os.path.exists(p1):
        rows1 = list(csv.DictReader(io.open(p1, encoding="utf-8-sig")))
    else:
        bad.append("subtitle_content_check.csv 不存在")
    if os.path.exists(p2):
        rows2 = list(csv.DictReader(io.open(p2, encoding="utf-8-sig")))
    else:
        bad.append("subtitle_episode_coverage.csv 不存在")

    if rows1:
        if len(rows1) != 32:
            bad.append(f"32 集核对表 {len(rows1)} 行，应为 32")
        weird = [r["episode"] for r in rows1 if r["verdict"] not in ok_verdicts]
        if weird:
            bad.append(f"32 集核对表出现未定义判定：{weird[:5]}")
        if any(not r["verdict"] for r in rows1):
            bad.append("32 集核对表有行缺判定")
    if rows2:
        if len(rows2) != 38:
            bad.append(f"38 集核对表 {len(rows2)} 行，应为 38")
        n_rule = sum(int(r["rules"] or 0) for r in rows2)
        n_ok = sum(int(r["locator_ok"] or 0) for r in rows2)
        with io.open(os.path.join(DATA, "rules.csv"), encoding="utf-8-sig") as f:
            n_loc = sum(1 for r in csv.DictReader(f)
                        if (r.get("source_locator") or "").startswith("LX38-E"))
        if n_rule != n_loc:
            bad.append(f"38 集核对表规则合计 {n_rule} != rules.csv 带 LX38 定位 {n_loc} 条")
        if n_ok != n_rule:
            bad.append(f"38 集核对表定位命中 {n_ok} != 规则数 {n_rule}（有定位未通过）")
    if rows1 and rows2:
        eps = {("32", r["episode"]) for r in rows1} | {("38", r["episode"]) for r in rows2}
        mp = os.path.join(DATA, "video_episode_map.csv")
        with io.open(mp, encoding="utf-8-sig") as f:
            n_map = sum(1 for _ in csv.DictReader(f))
        if len(eps) != n_map:
            bad.append(f"核对表覆盖 {len(eps)} 集 != video_episode_map.csv {n_map} 集")
    # note_crosswalk.csv：集 ↔ 笔记章节（70 行，32＋38）
    p3 = os.path.join(DATA, "note_crosswalk.csv")
    if os.path.exists(p3):
        rows3 = list(csv.DictReader(io.open(p3, encoding="utf-8-sig")))
        if len(rows3) != 70:
            bad.append(f"note_crosswalk.csv {len(rows3)} 行，应为 70")
        n32 = sum(1 for r in rows3 if r["series"] == "32")
        n38 = sum(1 for r in rows3 if r["series"] == "38")
        if (n32, n38) != (32, 38):
            bad.append(f"note_crosswalk.csv 分系列 {n32}／{n38}，应为 32／38")
        empty = [r["episode"] for r in rows3
                 if r["series"] == "32" and not r["note_section"]]
        if empty:
            bad.append(f"32 集有集未指派笔记章节：{empty}")
        no38 = [r["episode"] for r in rows3
                if r["series"] == "38" and not r["note_page"]]
        if no38:
            bad.append(f"38 集有集未对齐页：{no38}")
    else:
        bad.append("note_crosswalk.csv 不存在")

    md = os.path.join(ROOT, "references", "subtitle_content_check.md")
    if not os.path.exists(md):
        bad.append("references/subtitle_content_check.md 不存在")
    rec("C", "C08", not bad,
        "字幕内容核对表与规则表／集数表对账一致" if not bad else "核对表对账不一致：" + "；".join(bad))
    return not bad


def check_pijing_refs(counts):
    """C09：命书范文里的规则／表格编号，必须在库里查得到。

    这类文档最容易出的错，是「行文时顺手写一个 R 编号或格 id」，
    而那个编号在库里根本不存在——读者按号去查，查不到，整段判断就悬空。
    本项只核「编号存在」，不核「编号是否被正确使用」——后者仍须人工。
    """
    bad = []
    files = ["pijing_method.md", "example_pijing_gengxu.md", "example_pijing_gengxu.html"]
    for fn in files:
        if not os.path.exists(os.path.join(ROOT, "references", fn)):
            bad.append(f"references/{fn} 不存在")
    if bad:
        rec("C", "C09", False, "命书文档缺失：" + "；".join(bad))
        return False

    rule_ids = {r["rule_id"] for r in
                csv.DictReader(io.open(os.path.join(DATA, "rules.csv"), encoding="utf-8-sig"))}
    cells = list(csv.DictReader(io.open(os.path.join(DATA, "tables.csv"), encoding="utf-8-sig")))
    cell_ids = {c["cell_id"] for c in cells}
    table_ids = {c["table_id"] for c in cells}

    # 体例三段：缺一段即不是梁氏批例体例
    body = io.open(os.path.join(ROOT, "references", "example_pijing_gengxu.md"),
                   encoding="utf-8").read()
    for seg in ("已知因", "总评", "提要"):
        if seg not in body:
            bad.append(f"范文缺体例段「{seg}」")

    missing = []
    for fn in files:
        if not fn.endswith(".md"):
            continue
        txt = io.open(os.path.join(ROOT, "references", fn), encoding="utf-8").read()
        for rid in set(re.findall(r"\bR\d+\b", txt)):
            if rid not in rule_ids:
                missing.append((fn, rid))
        for tid in set(re.findall(r"\bT(?:B)?-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}\b", txt)):
            if tid not in cell_ids and tid not in table_ids:
                missing.append((fn, tid))
        for tid in set(re.findall(r"\bTB-XJ\d+\b", txt)):
            if tid not in table_ids:
                missing.append((fn, tid))
    if missing:
        bad.append("引用编号在库中不存在：" +
                   "、".join(f"{a}→{b}" for a, b in sorted(set(missing))[:8]))

    rec("C", "C09", not bad,
        "命书范文引用编号全部可查、体例三段齐备" if not bad else "命书范文对账失败：" + "；".join(bad))
    return not bad


# 引文保真的来源表：(source_id, 全文文件, locator 正则, 定位模式, 书名)
#   lines 模式 —— rule_text 必须等于「所标行号切片」的拼接（整段引文即若干整行）
#   pages 模式 —— rule_text 必须落在「所标页范围」之内（引文是页内的一段连续原文）
QUOTE_SOURCES = [
    ("SRC-LXTEXT-20", "SZ", r"^SZ:L[\d,\-L]+$", "lines", "《命理实战》"),
    ("SRC-LXTEXT-02", "MF", r"^MF:p\d+(?:-\d+)?$", "pages", "《子平母法》"),
    ("SRC-LXTEXT-01", "XP", r"^XP:p\d+(?:-\d+)?$", "pages", "《细批终身详解》"),
    ("SRC-LXTEXT-12", "SS", r"^SS:p\d+(?:-\d+)?$", "pages", "《沈氏用神例解》"),
    ("SRC-LXTEXT-23", "JB", r"^JB:p\d+(?:-\d+)?$", "pages", "《金不换大运详解》"),
    ("SRC-LXTEXT-09", "YH", r"^YH:p\d+(?:-\d+)?$", "pages", "《渊海喜忌随笔》"),
    ("SRC-LXTEXT-30", "JC", r"^JC:p\d+(?:-\d+)?$", "pages", "《子平基础概要》"),
]


def _squeeze(s):
    """去掉全部空白，用于跨行比对。"""
    return re.sub(r"\s+", "", s or "")


VERIFY_DB = os.path.join(DATA, "quotes_verify.txt")


def _load_pages(path):
    """把「===== pNNN =====」切页格式读成 {页号: 去空白页文本}。"""
    pages, cur = {}, None
    for line in io.open(path, encoding="utf-8").read().split("\n"):
        m = re.match(r"^===== p(\d+) =====$", line)
        if m:
            cur = int(m.group(1))
            pages[cur] = []
        elif cur is not None:
            pages[cur].append(line)
    return {k: _squeeze("".join(v)) for k, v in pages.items()}


def _load_book(bid):
    """从 `data/quotes_verify.txt` 取某书段落 → ({页号: 去空白页文本}, 段头行)。

    核验库把十二本书并置，各书页号自 1 起，故不能整篇切页——必须先按
    `##### 书号 | 书名 | mode | keep=a/b #####` 分段，再在段内切页。
    段内未被引的页只有页标、没有正文（见 `_dev/distill_corpus.py`），
    页标仍在，所以「台账称 N 页」的页数校验照旧成立。
    """
    if not os.path.exists(VERIFY_DB):
        return {}, ""
    pages, cur, head, inside = {}, None, None, False
    for line in io.open(VERIFY_DB, encoding="utf-8").read().split("\n"):
        m = re.match(r"^#####\s*([A-Z]{2})\s*\|", line)
        if m:
            inside = (m.group(1) == bid)
            if inside:
                head = line
            cur = None
            continue
        if not inside:
            continue
        m = re.match(r"^===== p(\d+) =====$", line)
        if m:
            cur = int(m.group(1))
            pages[cur] = []
        elif cur is not None:
            pages[cur].append(line)
    return {k: _squeeze("".join(v)) for k, v in pages.items()}, (head or "")


def _book_lines(bid):
    """取某书段的原始行（含空行占位）。行锚书的行号靠它对齐。"""
    if not os.path.exists(VERIFY_DB):
        return []
    out, inside = [], False
    for line in io.open(VERIFY_DB, encoding="utf-8").read().split("\n"):
        m = re.match(r"^#####\s*([A-Z]{2})\s*\|", line)
        if m:
            inside = (m.group(1) == bid)
            continue
        if inside:
            out.append(line)
    return out


def _loc_range(loc, npages):
    """MF:p111 / MF:p111-115 / XP:p435 / XP:p437-440 → (起页, 止页)；越界或不合格式返回 None。"""
    m = re.match(r"^(?:MF|XP|SS|JB|YH|JC):p(\d+)(?:-(\d+))?$", loc)
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2) or m.group(1))
    if not (1 <= a <= b <= npages):
        return None
    return a, b


def check_quote_fidelity(counts):
    """C10：从电子文本抽出的引文，必须能在全文里逐字找到。

    Part 29 从《命理实战》抽了 50 条规则（行锚 SZ:Lnnn，rule_text 按行切片）；
    Part 30 从《子平母法》抽了 40 条规则＋6 例判例（页锚 MF:pNNN，引文为页内片段）。
    Part 40 从《渊海喜忌随笔》抽了 23 条规则（页锚 YH:pNNN，引文为页内片段）。
    两种锚法的比对方式不同，故本项做成来源表驱动：

      lines 模式：rule_text == 所标行号切片的拼接（严格相等）
      pages 模式：rule_text ⊆ 所标页范围（连续子串）

    只要有人手改引文（补字、改讹字、缩略、并页），这条就会响——引文漂移是本包最不能
    容忍的一种错，因为它会让「原文摘句」不再是原文。判例的 known_facts／liang_judgment
    同样要能在所标页范围内找到，否则「照录原文」这句话就是空的。

    同时检查 conditions 的可判定性前缀，以及全文文件本身在不在。
    """
    bad = []
    skipped = []
    tally = []
    _, rules = load("rules.csv")
    _, cases = load("cases.csv")

    for sid, bid, pat, mode, book in QUOTE_SOURCES:
        if not os.path.exists(VERIFY_DB):
            # 全文类底本不随包分发（版权）：公开仓无此件，本地研究环境有。
            # 缺件时本项记 skip，不算 FAIL——结构与自洽不受影响。
            skipped.append(book)
            continue
        # 全书已改为「引文核验库」：只收被引处及其上下文，未引之处不留一字。
        # 故本项由「引文能在全书中找到」变为「引文能在核验库中找到」——
        # 标准未降：核验库由 `_dev/distill_corpus.py` 从原书机械抽取，未改一字。
        lines = _book_lines(bid)
        pages = {}
        if mode == "pages":
            pages, _head = _load_book(bid)
            if not pages:
                bad.append(f"{book}（{bid}）在核验库中无对应段落")
                continue
        if not lines:
            bad.append(f"{book}（{bid}）在核验库中无可读行")
            continue
        npages = max(pages) if pages else 0

        n = 0
        for r in rules:
            if g(r, "source_id") != sid:
                continue
            n += 1
            rid = g(r, "rule_id")
            loc = g(r, "source_locator")
            if not re.match(pat, loc):
                bad.append(f"{rid} locator 不合格式：{loc}")
                continue

            if mode == "lines":
                segs, okseg = [], True
                for part in loc[4:].split(","):
                    part = part.lstrip("L")
                    mm = re.match(r"^(\d+)(?:-(\d+))?$", part)
                    if not mm:
                        bad.append(f"{rid} locator 段不合格式：{part}")
                        okseg = False
                        break
                    a = int(mm.group(1))
                    b = int(mm.group(2) or mm.group(1))
                    if not (1 <= a <= b <= len(lines)):
                        bad.append(f"{rid} locator 越界：{loc}（全文 {len(lines)} 行）")
                        okseg = False
                        break
                    segs.extend(range(a, b + 1))
                if not okseg:
                    continue
                expect = "".join(lines[i - 1].strip() for i in segs if lines[i - 1].strip())
                if g(r, "rule_text") != expect:
                    bad.append(f"{rid} 引文与全文不一致（{loc}）")
            else:
                rng = _loc_range(loc, npages)
                if not rng:
                    bad.append(f"{rid} locator 越界或不合格式：{loc}（全文 {npages} 页）")
                    continue
                span = "".join(pages.get(i, "") for i in range(rng[0], rng[1] + 1))
                if _squeeze(g(r, "rule_text")) not in span:
                    bad.append(f"{rid} 引文不在 {loc} 页范围内")

            cond = g(r, "conditions")
            if not (cond.startswith("[可算]") or cond.startswith("[待人工]")):
                bad.append(f"{rid} conditions 缺可判定性前缀")

        if n == 0:
            bad.append(f"未找到 {sid} 来源的规则")
        tally.append(f"{book}{n} 条")

        # 判例字段回溯：只对页锚来源做（行锚来源的判例不入 cases.csv）
        if mode == "pages":
            k = 0
            for c in cases:
                if g(c, "source_id") != sid:
                    continue
                k += 1
                cid = g(c, "case_id")
                loc = g(c, "source_locator")
                rng = _loc_range(loc, npages)
                if not rng:
                    bad.append(f"{cid} locator 越界或不合格式：{loc}（全文 {npages} 页）")
                    continue
                span = "".join(pages.get(i, "") for i in range(rng[0], rng[1] + 1))
                for field in ("known_facts", "liang_judgment"):
                    v = _squeeze(g(c, field))
                    if v and v not in span:
                        bad.append(f"{cid} 的 {field} 不在 {loc} 页范围内")
            if k:
                tally.append(f"{book}判例 {k} 例")

    rec("C", "C10", not bad,
        ("、".join(tally) + "：引文与全文逐字一致、判例字段可回溯、条件前缀齐备")
        if not bad and not skipped else
        ("引文核验库未随包分发（版权），逐字比对本地执行时再跑" if not bad and skipped
         else "引文保真失败：" + "；".join(bad[:6])))
    return not bad


def main():
    ap = argparse.ArgumentParser(description="梁湘润批八字·总装校验器")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总与失败项")
    ap.add_argument("--skip-smoke", action="store_true", help="跳过分析器冒烟")
    args = ap.parse_args()

    check_structure()
    check_keys()
    check_refs()
    check_vocab()
    check_gate()
    counts = check_counts()
    check_indices(counts)
    check_runtime(args.skip_smoke)
    check_golden(args.skip_smoke)
    check_mingshu(args.skip_smoke)
    check_mingshu_html(args.skip_smoke)
    check_mingshu_thick(args.skip_smoke)
    check_mingshu_quotes(args.skip_smoke)
    check_subtitle_check(counts)   # 须在 C07 之前：C07 用 len(RESULTS)+1 数总项数
    check_pijing_refs(counts)      # 同上，须在 C07 之前
    check_quote_fidelity(counts)   # 同上，须在 C07 之前
    check_paipan(args.skip_smoke)      # 同上，须在 C07 之前
    check_crosscheck(args.skip_smoke)  # 同上，须在 C07 之前
    check_liunian(args.skip_smoke)     # 同上，须在 C07 之前
    check_report_check(args.skip_smoke)  # 同上，须在 C07 之前
    check_report_templates(args.skip_smoke)  # 同上，须在 C07 之前
    check_corpus(args.skip_smoke)      # 同上，须在 C07 之前
    check_shensha_sp(args.skip_smoke)  # 同上，须在 C07 之前
    check_report_gate()
    check_panduan()
    check_trace_audit()
    check_yun_spans()
    check_deliver_guard()
    check_feedback()
    check_promo_tail()
    check_xingqing()
    check_liuqin()
    check_doc_claims(counts)

    n_pass = sum(1 for x in RESULTS if x[2] == "PASS")
    n_warn = sum(1 for x in RESULTS if x[2] == "WARN")
    n_fail = sum(1 for x in RESULTS if x[2] == "FAIL")

    if args.json:
        print(json.dumps({
            "counts": counts,
            "summary": {"pass": n_pass, "warn": n_warn, "fail": n_fail},
            "results": [{"group": a, "code": b, "level": c, "message": d}
                        for a, b, c, d in RESULTS],
        }, ensure_ascii=False, indent=2))
    else:
        cur = None
        for grp, code, level, msg in RESULTS:
            if not args.quiet:
                if grp != cur:
                    print(f"\n[{grp}]")
                    cur = grp
                mark = {"PASS": "ok  ", "WARN": "WARN", "FAIL": "FAIL"}[level]
                print(f"  {mark} {code}  {msg}")
            elif level == "FAIL":
                print(f"  FAIL {code}  {msg}")
        print("\n计数：" + "、".join(f"{k}={v}" for k, v in counts.items()))
        print(f"结果：PASS {n_pass}｜WARN {n_warn}｜FAIL {n_fail}")
        if n_fail == 0:
            print("结论：结构自洽通过（不等于内容已验真）")
        else:
            print("结论：存在 FAIL，须修复后重跑")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
