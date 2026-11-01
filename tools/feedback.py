#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反馈与纠偏：问单 → 命主反馈 → 校准 → 复核版。

三步：
  --quiz     出问单：把可核断语逐条列给命主，命主填「符／偏／说不清」＋补充事实。
  --recv     收填好的问单，出校准回执（确认／偏差／未核，疑盘检查在此触发）。
  --recheck  出复核版命书：原断语一字不动＋状态标记＋批者注记，末附校准依据。

底线（代码层写死，不许绕）：
  1. 反馈只用于三件事——核盘（疑盘检查）、定侧重、标个案；
  2. 复核版引用的「原断」必须逐字来自判断器输出，本工具不重写断语；
  3. 疑盘成立（偏差≥3 条，或婚姻与父母同偏）时不出终稿，先重核时辰、经度、性别——
     大面积偏差的第一嫌疑是盘错了，不是断语错了；
  4. 反馈不得用于把断语改成命主爱听的：那是算命先生行为，不是梁氏路数。
"""

import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyze as A  # noqa: E402
import panduan as PD  # noqa: E402

# 可核点：pid → (节名, 给命主的问法)
QUIZ_POINTS = [
    ("item5", "六亲大略", "命书「总评／六亲」里关于妻星、六亲的那几句"),
    ("item9", "自身根基", "说你立不立得住、扎不扎实的那一句"),
    ("marriage", "婚姻", "关于婚姻、配偶的那几句"),
    ("wealth", "财与事业", "关于财路、事业路数的那几句"),
    ("child", "子息", "关于子女的那几句"),
    ("parent", "父母兄弟", "关于出身、父母、兄弟的那几句"),
    ("xingqing", "性情", "说你性子、脾气、为人处世的那些"),
    ("health", "寿元疾病", "关于身体、健康底子的那句（若留白则无须填）"),
    ("dayun", "大运要步", "点名的某几步大运（尤其要预先布置的那一步）"),
]

VERDICTS = {
    "符": "OK", "准": "OK", "对": "OK", "是": "OK", "符合": "OK", "ok": "OK", "y": "OK",
    "偏": "DEV", "偏差": "DEV", "不符": "DEV", "不对": "DEV", "不是": "DEV", "错": "DEV",
    "n": "DEV",
    "说不清": "UNK", "不知道": "UNK", "未核": "UNK", "待核": "UNK", "": "UNK",
}

QUIZ_INTRO = """# 命书回执问单

命书交出去了，这一步是回访：**请对照命书，逐条告诉我哪些对、哪些有偏差。**

填法（就改这张表）：

- 「命主判断」一列只填三个词之一：**符**（对）、**偏**（有偏差）、**说不清**；
- 「补充」一列写实际情形，有多少写多少——一条年份、一句实情，比十句评价有用；
- 填完把文件发回来。

一句丑话：偏差多的第一嫌疑是**时辰报错了**，不是命书胡说。所以偏得多的，我要回头
先问你时辰——请体谅这一问，不是推责。

| 编号 | 问什么 | 命主判断 | 补充 |
|---|---|---|---|
"""


def _clean_claim(s):
    """给命主看的断语：去编号、去内部标记，断语本身一字不动。"""
    s = s or ""
    s = re.sub(r"`", "", s)
    s = re.sub(r"\*", "", s)
    s = re.sub(r"R[-A-Za-z0-9]+[：:]", "", s)   # 前缀引用：R38：／R-XP-045：
    s = re.sub(r"\s?R[-A-Za-z0-9]+\b", "", s)   # 行文引用：按 R-MF-017 作 → 按作
    s = re.sub(r"([按依照据])\s+", r"\1", s)     # 收掉删号后的悬空空格
    s = s.replace("。；", "；").replace("；；", "；")
    return s.replace("|", "；").strip()


def build(a):
    """跑判断层，返回 trace。"""
    a["where"] = PD._where_of(a)
    return PD.build_trace(a)


def quiz(pan_path, recent, out):
    src = A.load_paipan(pan_path)
    dyn = [d for d in (src.get("dayun") or []) if isinstance(d, str) and d]
    a = A.analyze(src["pillars"], gender=src["gender"], dayun=dyn,
                  birth_year=src["birth_year"], start_age=src["start_age"],
                  recent=recent)
    tr = build(a)
    by_pid = {p["pid"]: p for p in tr["points"]}
    rows = []
    for pid, name, ask in QUIZ_POINTS:
        p = by_pid.get(pid)
        if not p or not p["fired"] or not p["sent"]:
            continue
        claim = _clean_claim(p["say"])
        if len(claim) > 110:
            claim = claim[:109] + "…"
        rows.append((pid, name, ask, claim))
    lines = [QUIZ_INTRO]
    for i, (pid, name, ask, claim) in enumerate(rows, 1):
        lines.append("| q%02d | **%s**——%s。原断：%s | | |\n"
                     % (i, name, ask, claim))
    lines.append("\n---\n\n*（批者存档：本问单由 `feedback.py --quiz` 生成，"
                 "断语取自 `panduan.py` 判断器，逐字未改。）*\n")
    io.open(out, "w", encoding="utf-8", newline="\n").write("".join(lines))
    print("→ %s（%d 条可核）" % (out, len(rows)))
    return len(rows)


def _verdict(txt):
    t = (txt or "").strip().lower()
    if t in VERDICTS:
        return VERDICTS[t]
    for k, v in VERDICTS.items():
        if k and k in t:
            return v
    return "UNK"


def recv(filled, out_json):
    rows = []
    for ln in io.open(filled, encoding="utf-8"):
        m = re.match(r"^\|\s*(q\d+)\s*\|(.+?)\|(.+?)\|(.*)\|\s*$", ln.rstrip())
        if not m:
            continue
        qid, ask, judge, note = m.group(1), m.group(2), m.group(3), m.group(4)
        v = _verdict(judge)
        if v == "UNK" and "|" in ask and "原断" in ask:
            # 判断列整列为空也算 UNK；仅在填了无关内容时提示
            pass
        rows.append({"qid": qid, "ask": ask.strip(),
                     "verdict": v, "note": note.strip()})
    n = {"OK": 0, "DEV": 0, "UNK": 0}
    for r in rows:
        n[r["verdict"]] += 1
    dev_pids = [r["qid"] for r in rows if r["verdict"] == "DEV"]
    # 疑盘：偏差≥3，或婚姻＋父母同偏
    doupan = len(dev_pids) >= 3 or ("marriage" in str(dev_pids) and "parent" in str(dev_pids))
    res = {"rows": rows, "counts": n, "doupan": bool(doupan),
           "dev_n": n["DEV"]}
    with io.open(out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print("→ %s（符 %d／偏 %d／未核 %d；疑盘=%s）"
          % (out_json, n["OK"], n["DEV"], n["UNK"], "是" if doupan else "否"))
    if doupan:
        print("!! 疑盘成立：先重核时辰、出生地经度、性别，疑盘期间不出终稿。")
    return res


def recheck(pan_path, recent, filled, out, pan_verified=False):
    src = A.load_paipan(pan_path)
    dyn = [d for d in (src.get("dayun") or []) if isinstance(d, str) and d]
    a = A.analyze(src["pillars"], gender=src["gender"], dayun=dyn,
                  birth_year=src["birth_year"], start_age=src["start_age"],
                  recent=recent)
    tr = build(a)
    by_pid = {p["pid"]: p for p in tr["points"]}
    # 收反馈
    feed = {}
    for ln in io.open(filled, encoding="utf-8"):
        m = re.match(r"^\|\s*(q\d+)\s*\|(.+?)\|(.+?)\|(.*)\|\s*$", ln.rstrip())
        if not m:
            continue
        feed[m.group(1)] = {"verdict": _verdict(m.group(3)),
                            "note": m.group(4).strip()}
    # 组装复核版
    L = []
    ap = L.append
    gz = "　".join(src["pillars"])
    ap("# 复核版命书（%s　%s）\n\n" % (gz, src.get("gender") or ""))
    ap("> 这是按你的反馈出的**复核版**。三条规矩：\n>\n"
       "> 一、原断语**一字未改**——对的就是对的，错的就是错的，我不改字；\n"
       "> 二、每条后面标了状态：**已核·符**／**反馈·偏差**／**未核**；\n"
       "> 三、偏差的第一嫌疑是时辰，不是命理。偏得多的，先重核盘，再谈断语。\n\n")
    ok = [r for r in feed.values() if r["verdict"] == "OK"]
    dev = [r for r in feed.values() if r["verdict"] == "DEV"]
    unk = [r for r in feed.values() if r["verdict"] == "UNK"]
    doupan = (len(dev) >= 3 or _doupan_pairs(feed)) and not pan_verified
    ap("## 回执\n\n")
    ap("- 已核·符 %d 条；反馈·偏差 %d 条；未核 %d 条。\n" % (len(ok), len(dev), len(unk)))
    if doupan:
        ap("- **疑盘成立**——偏差达三条，或婚姻与父母同偏。疑盘期间**不出终稿**，先办三件事：\n"
           "  1. 时辰：问家里人确切到几分；两点多与两点五十是两个时辰的事；\n"
           "  2. 出生地：报到我经度那一位数，真太阳时差几分钟有时就差一个时辰；\n"
           "  3. 性别与公历/农历：生日是否身份证上的公历日。\n"
           "- 三件核完重排。若时辰变了，命书整本重来——那不叫改口，叫盘本来就不是这一个。\n")
    elif pan_verified and (len(dev) >= 3 or _doupan_pairs(feed)):
        ap("- **疑盘已撤**——时辰、出生地、公历三项经命主当面核实，盘无误。偏差照记，\n"
           "  一条一条按个案论（见下），不改断语、不改通则。\n")
    else:
        ap("- 核盘结论：**通过**，继续以本盘为据。\n")
    ap("\n## 逐节复核\n\n")
    basis = []
    qi = 0
    for pid, name, _ask in QUIZ_POINTS:
        p = by_pid.get(pid)
        if not p or not p["fired"] or not p["sent"]:
            continue
        qi += 1
        qid = "q%02d" % qi
        f = feed.get(qid, {"verdict": "UNK", "note": ""})
        tag = {"OK": "已核·符", "DEV": "反馈·偏差", "UNK": "未核"}[f["verdict"]]
        ap("### %s（%s）\n\n" % (name, tag))
        ap("- **原断**：%s\n" % _clean_claim(p["say"]))
        if f["verdict"] == "OK":
            ap("- 命主已核，属实。此条此后作定盘之锚——命书里的话以它为准。\n")
        elif f["verdict"] == "DEV":
            ap("- 命主反馈有偏差。")
            if f["note"]:
                ap("实情：「%s」。" % f["note"])
            ap("\n")
            ap("- **批者注记**：记个案，**不改通则**。此点或须看运——同一句话在另一步运里\n"
               "  应法不同；若命主所补实情正落在某步运内，下回访时按运细分。此条不作\n"
               "  总断依据，**也不因此改命书别处的话**。\n")
            basis.append((qid, name, p.get("ids") or []))
        else:
            ap("- 未核。此条暂以结构论，不作定盘之锚。\n")
        ap("\n")
    ap("## 校准后的要紧话\n\n")
    if doupan:
        ap("疑盘未解，先不给「要紧三处」——盘未定，话都是虚的。先核三件事，回来重排。\n")
    else:
        ap("命主确认过的条目里，以婚姻、财、性情为据；偏差条目以个案论。"
           "原命书通篇断语的**次序不变、字句不变**，只在此处标明哪些经你核实——"
           "经你核实的那几条，可信度高于其余，读命书时先读它们。\n")
    if basis:
        ap("\n## 校准依据（附，批者存档）\n\n")
        for qid, name, ids in basis:
            ap("- %s %s：原断所依 `%s`。\n" % (qid, name, "`、`".join(ids)))
    ap("\n---\n\n*（本复核版由 `feedback.py --recheck` 生成；"
       "「原断」逐字取自判断器输出，未作改写。）*\n")
    io.open(out, "w", encoding="utf-8", newline="\n").write("".join(L))
    print("→ %s（疑盘=%s）" % (out, "是" if doupan else "否"))


def _doupan_pairs(feed):
    pids = []
    qi = 0
    for pid, _n, _a in QUIZ_POINTS:
        qi += 1
        f = feed.get("q%02d" % qi)
        if f and f["verdict"] == "DEV":
            pids.append(pid)
    return "marriage" in pids and "parent" in pids


def _name_of(by_pid, pid):
    p = by_pid.get(pid)
    return (p or {}).get("name") or pid


def _self_test():
    ok = True
    for k, v in VERDICTS.items():
        assert v in ("OK", "DEV", "UNK")
    assert _verdict("符") == "OK" and _verdict("偏差") == "DEV" and _verdict("") == "UNK"
    assert _verdict("基本符合，就差一点") == "OK"
    print("feedback 自检：通过")
    return ok


def main():
    ap = argparse.ArgumentParser(description="反馈与纠偏：问单→校准→复核版")
    ap.add_argument("--pan", metavar="JSON", help="paipan.py --json 的输出文件")
    ap.add_argument("--recent", type=int, default=5)
    ap.add_argument("--quiz", metavar="MD", help="出问单")
    ap.add_argument("--recv", metavar="MD", help="收填好的问单，须配 --out-json")
    ap.add_argument("--out-json", metavar="JSON", default="/tmp/calibrated.json")
    ap.add_argument("--filled", metavar="MD", help="填好的问单，配 --recheck")
    ap.add_argument("--recheck", metavar="MD", help="出复核版命书")
    ap.add_argument("--pan-verified", action="store_true",
                    help="盘已经当面复核（时辰、出生地、公历三项核过）——疑盘撤，偏差按个案论")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(0 if _self_test() else 1)
    if args.quiz:
        if not args.pan:
            ap.error("--quiz 须配 --pan")
        quiz(args.pan, args.recent, args.quiz)
    elif args.recv:
        recv(args.recv, args.out_json)
    elif args.recheck:
        if not (args.pan and args.filled):
            ap.error("--recheck 须配 --pan 与 --filled")
        recheck(args.pan, args.recent, args.filled, args.recheck,
                pan_verified=args.pan_verified)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
