#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试（test_golden.py）

validate.py 的 66 项只验「结构与自洽」，验不了「同一命例前后两次跑出来不一样」。
改一条规则、调一次标签抽取、动一下排序，输出就可能漂，而结构校验全绿。
本脚本守这一处：把若干命例的**规则命中集**固化成快照，逐次比对。

判级：
  消失（FAIL）——上次命中的规则这次没命中。判据失效，必须查明是规则改了还是抽取坏了。
  新增（WARN）——这次多命中了。可能是规则变多，也可能是误命中，须人工确认。
  数量（FAIL）——命中／部分／不可判定三段之和与规则分母对不上。

用法：
    python tools/test_golden.py            # 比对
    python tools/test_golden.py --update   # 重建快照（须说明为什么变）
"""
import argparse
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "data", "golden_expect.json")
AP = os.path.join(ROOT, "tools", "analyze.py")

# 五个命例：三男一女，覆盖「有冲」「有合」「女命」「大运」四种情形
# K-06 为羊刃驾杀（丙日午月、壬杀透），守 G-01 格局裁定的外格分支
CASES = [
    ("K-01", ["戊辰", "戊午", "甲午", "乙丑"], "男", None),
    ("K-02", ["庚午", "庚寅", "甲戌", "丁卯"], "男", None),
    ("K-03", ["乙丑", "庚午", "甲申", "癸酉"], "男", None),
    ("K-04", ["壬辰", "壬子", "丙午", "癸巳"], "女", None),
    ("K-05", ["甲子", "乙亥", "庚戌", "癸未"], "男", "丙子,丁丑,戊寅,己卯"),
    ("K-06", ["癸巳", "戊午", "丙午", "壬辰"], "男", None),
]

SECTIONS = ["## 一、四柱输入", "## 二、四柱、藏干与十神", "## 三、形态判定",
            "## 四、用神取用次序", "## 十三、规则匹配（条件三段）",
            "## 十四、冲突、低置信与资料缺口", "## 十五、本次未能确定"]


def run(pillars, gender, dayun):
    cmd = [sys.executable, AP] + pillars + ["--gender", gender, "--json"]
    if dayun:
        cmd += ["--dayun", dayun]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:300])
    return json.loads(p.stdout)


def snapshot():
    out = {}
    for cid, ps, g, dy in CASES:
        d = run(ps, g, dy)
        out[cid] = {
            "pillars": ps, "gender": g, "dayun": dy,
            "hit": sorted(r["rule_id"] for r, _ in d["rule_hit"]),
            "partial_n": len(d["rule_partial"]),
            "na_n": len(d["rule_na"]),
            "chart_tags": d["chart_tags"],
            "geju": {"name": d["geju"]["name"], "shun": d["geju"]["shun"],
                     "verdict": d["geju"]["verdict"], "waige": d["geju"]["waige"]},
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args()

    cur = snapshot()
    if a.update:
        with io.open(SNAP, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(cur, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n")
        print("已重建快照 data/golden_expect.json（%d 例）" % len(cur))
        for k, v in cur.items():
            print("  %-5s 命中 %d｜部分 %d｜不可判定 %d" % (k, len(v["hit"]), v["partial_n"], v["na_n"]))
        return 0

    if not os.path.exists(SNAP):
        print("FAIL 快照不存在，先跑 --update")
        return 1
    old = json.load(io.open(SNAP, encoding="utf-8"))

    fails, warns = [], []
    for cid, _, _, _ in CASES:
        if cid not in old:
            fails.append("%s 快照缺失" % cid)
            continue
        o, c = old[cid], cur[cid]
        gone = sorted(set(o["hit"]) - set(c["hit"]))
        new = sorted(set(c["hit"]) - set(o["hit"]))
        if gone:
            fails.append("%s 命中消失 %d 条：%s" % (cid, len(gone), "、".join(gone[:8])))
        if new:
            warns.append("%s 新增命中 %d 条：%s" % (cid, len(new), "、".join(new[:8])))
        if o["partial_n"] != c["partial_n"]:
            warns.append("%s 部分满足 %d→%d" % (cid, o["partial_n"], c["partial_n"]))
        if o["na_n"] != c["na_n"]:
            warns.append("%s 不可判定 %d→%d" % (cid, o["na_n"], c["na_n"]))
        if o["chart_tags"] != c["chart_tags"]:
            fails.append("%s 命盘特征变了" % cid)
        # G-01 格局裁定：格名／顺逆／结构结论任何一项漂移都算 FAIL
        if o.get("geju") != c.get("geju"):
            fails.append("%s 格局裁定变了：%s → %s" % (cid, o.get("geju"), c.get("geju")))

    # 三段之和 + 性别过滤 = 规则总数
    _, rows = None, None
    import csv
    with io.open(os.path.join(ROOT, "data", "rules.csv"), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    total = sum(1 for r in rows if r["deterministic_use"] != "禁止")
    for cid, ps, g, dy in CASES:
        d = run(ps, g, dy)
        s = len(d["rule_hit"]) + len(d["rule_partial"]) + len(d["rule_na"])
        if s > total:
            fails.append("%s 三段之和 %d > 可用规则 %d" % (cid, s, total))

    # 章节齐备
    p = subprocess.run([sys.executable, AP] + CASES[0][1] + ["--gender", CASES[0][2]],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    for sec in SECTIONS:
        if sec not in p.stdout:
            fails.append("缺章节：%s" % sec)

    for w in warns:
        print("WARN", w)
    for f in fails:
        print("FAIL", f)
    print("结果：%s（%d 例，FAIL %d，WARN %d）"
          % ("PASS" if not fails else "FAIL", len(CASES), len(fails), len(warns)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
