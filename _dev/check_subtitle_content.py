# -*- coding: utf-8 -*-
"""字幕「知识点 ↔ 内容核心」一致性核对（不做逐字校对）

背景
----
用户要求「不必逐字核对，改为核对每集的知识点与内容核心是否一致」。

注意：Part 24 曾在此写「资料库中不存在每集笔记文件」——**该结论已更正（Part 25）**。
真笔记在 `1_直接可识别文字/`，逐集对照请用 `tools/check_note_coverage.py`。
本脚本保留为**不依赖笔记的旁证**，用两个替代锚点：

  1. 32 集系列（LX2-15）：`data/video_episode_map.csv` 的 `title_join` 为标题锚点，
     测「标题词是否在本集正文里高频且早出现」。
  2. 38 集系列（LX2-14）：**没有标题**（`梁湘润【八字传承班】（字幕）01` 之类），
     改用 `data/rules.csv` 的 `source_locator`（形如 `LX38-E11:L441-720`）作锚点，
     测「规则引文能否在所指集、所指行找到原文」。

两个锚点都只证明**主题级一致**，不证明逐字保真；不替代 E1 图版核对。

用法
----
    python tools/check_subtitle_content.py [--lib D:/梁湘润] [--write]

依赖：仅标准库。**不需要 opencc**——词表同时写了简／繁两种写法。
需要本机资料库（包外）：32 集字幕在 `梁湘润 32级视频任务/**/*.zip`，
38 集字幕在 `梁湘润 38集视频教程/P*_字幕全文*.txt`。
"""
import argparse
import csv
import difflib
import io
import os
import re
import sys
import zipfile
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# ---------------------------------------------------------------- 标题词表
# 每集一条：第一个词是「标题中心词」（判定主依据），其余为同义／上位／口语转述词。
# 每条写成元组，同时给简体与繁体写法，避免依赖 opencc。
# basis 一列写「为什么这个词可以代表该标题」，便于复核。
LEXICON = {
    1: ([("十神",), ("定位",), ("六亲", "六親"), ("妻财子禄", "妻財子祿")],
        "标题为『十神定位法』；本集实测前段讲学理次第（神煞→刑冲合会→十神定位→格局→喜忌），十神定位在后段展开"),
    2: ([("比肩",), ("劫财", "劫財")], "标题两篇，正文两词均高频"),
    3: ([("偏印",), ("枭神", "梟神")], "偏印格；枭神为偏印别名，正文未用别名"),
    4: ([("正印",), ("印格",)], "正印格"),
    5: ([("偏财", "偏財")], "偏财格"),
    6: ([("正财", "正財"), ("正官",)], "标题两格，正文两词均高频"),
    7: ([("七杀", "七殺"), ("偏官",)], "七杀格；偏官为别名，正文未用别名"),
    8: ([("食神",), ("伤官", "傷官")], "标题两格"),
    9: ([("寿", "壽"), ("夭",), ("短命",), ("意外",), ("死亡",)],
        "标题『論壽夭』为文言；正文不用『寿夭』二字，而以『意外』『短命』『死亡』『病』等口语讲同一主题"),
    10: ([("神煞",), ("桃花",), ("驿马", "驛馬")], "神煞概念（一）"),
    11: ([("神煞",), ("桃花",), ("驿马", "驛馬")], "神煞概念（二）"),
    12: ([("格局",), ("月令",), ("天透地藏",)], "取格局；月令／天透地藏为取格术语"),
    13: ([("八格",), ("正官格",), ("喜忌",)], "八格喜忌（一）；以正官格为例展开"),
    14: ([("八格",), ("七杀格", "七殺格"), ("羊刃格",), ("正官格",), ("喜忌",)],
         "八格喜忌（二）；正文讲七杀格、羊刃格、特别格、正官格，即『八格』之实"),
    15: ([("女命",), ("夫星",)], "女命（一）"),
    16: ([("女命",), ("夫星",)], "女命（二）"),
    17: ([("女命",), ("夫星",)], "女命（三）"),
    18: ([("女命",), ("夫星",)], "女命（四）"),
    19: ([("女命",), ("夫星",)], "女命（五）"),
    20: ([("天干",), ("喜忌",)], "十天干喜忌（一）"),
    21: ([("天干",), ("喜忌",)], "十天干喜忌（二）"),
    22: ([("天干",), ("喜忌",)], "十天干喜忌（三）"),
    23: ([("五行",), ("喜忌",)], "五行喜忌（一）"),
    24: ([("五行",), ("喜忌",)], "五行喜忌（二）"),
    25: ([("用神",), ("强弱", "強弱")], "用神、强弱（一）"),
    26: ([("用神",), ("强弱", "強弱")], "用神、强弱（二）"),
    27: ([("大运", "大運"), ("流年",)], "大运流年（一）"),
    28: ([("大运", "大運"), ("流年",)], "大运流年（二）"),
    29: ([("大运", "大運"), ("流年",)], "大运流年（三）"),
    30: ([("流月",), ("月令",)], "流月（一）"),
    31: ([("流月",), ("月令",)], "流月（二）"),
    32: ([("批八字",), ("实例", "實例"), ("个八字", "個八字")], "实务批命；正文为现场批例"),
}

# 判定门槛（与 references/subtitle_content_check.md 一致）
MIN_COUNT = 3          # 词至少出现 3 次，排除偶发
EARLY_FRAC = 0.40      # 首次出现须在前 40%，排除「标题词只在末尾提一句」


def norm(s):
    """只留汉字，去掉标点／数字／空白。"""
    return re.sub(r"[^\u4e00-\u9fff]", "", s or "")


def find_any(text, variants):
    """variants 为同一词的简／繁写法元组；返回 (命中写法, 次数, 首现位置百分比)。"""
    best = (None, 0, -1)
    for v in variants:
        c = text.count(v)
        if c > best[1]:
            i = text.find(v)
            best = (v, c, (i * 100.0 / len(text)) if i >= 0 and text else -1)
    return best


def dup_line_pct(raw, thr=0.75, minlen=6):
    """相邻两行相似度 ≥ thr 记一次『近重复』。

    这套字幕里存在「同一句被转写两三遍、每次错字略不同」的现象
    （如 P09 开头「那当我們對／那鹰当我們對」「一种基碰理懂了之后×3」）。
    纯查重（最长重复子串）抓不到它，因为每次都有字差；用行级相似度才抓得到。
    """
    lines = [norm(x) for x in raw.splitlines()]
    lines = [x for x in lines if len(x) >= minlen]
    if len(lines) < 2:
        return 0.0
    hit = sum(1 for i in range(1, len(lines))
              if difflib.SequenceMatcher(None, lines[i - 1], lines[i]).ratio() >= thr)
    return hit * 100.0 / len(lines)


# ---------------------------------------------------------------- 读取字幕
def load_series32(lib):
    """32 集（LX2-15）：字幕一部分在 梁湘润 32级视频任务/**/*.zip 内（读 zip 成员，不解压），
    另一部分（B6 任务＝16–18 集、B8 任务＝22–24 集）是解压好的平铺 txt，两种都要读。"""
    base = os.path.join(lib, "梁湘润 32级视频任务")
    out = {}
    if not os.path.isdir(base):
        return out
    for dirpath, _dirnames, filenames in os.walk(base):
        for fn in filenames:
            if fn.lower().endswith(".txt"):
                m = re.search(r"P(\d+)_字幕全文.*\.txt$", fn)
                if not m:
                    continue
                ep = int(m.group(1))
                if ep in out:
                    continue
                with open(os.path.join(dirpath, fn), encoding="utf-8-sig",
                          errors="replace") as f:
                    out[ep] = (f.read(), fn)
            elif fn.lower().endswith(".zip"):
                zp = os.path.join(dirpath, fn)
                try:
                    with zipfile.ZipFile(zp) as z:
                        for name in z.namelist():
                            m = re.search(r"P(\d+)_字幕全文.*\.txt$", name)
                            if not m:
                                continue
                            ep = int(m.group(1))
                            if ep in out:
                                continue
                            raw = z.read(name).decode("utf-8-sig", errors="replace")
                            out[ep] = (raw, "%s > %s" % (fn, os.path.basename(name)))
                except zipfile.BadZipFile:
                    continue
    return out


def load_series38(lib):
    """38 集（LX2-14）：字幕在 梁湘润 38集视频教程/ 平铺，文件名有 P1 与 P01 两种，部分带 _干支校正。"""
    base = os.path.join(lib, "梁湘润 38集视频教程")
    out = {}
    if not os.path.isdir(base):
        return out
    for fn in os.listdir(base):
        m = re.search(r"^P(\d+)_字幕全文(.*)\.txt$", fn)
        if not m:
            continue
        ep = int(m.group(1))
        # 干支校正版优先（同集若两版并存，取校正版）
        if ep in out and "校正" not in fn:
            continue
        with open(os.path.join(base, fn), encoding="utf-8-sig", errors="replace") as f:
            out[ep] = (f.read(), fn)
    return out


# ---------------------------------------------------------------- 核对一：32 集标题
def check_titles(lib):
    subs = load_series32(lib)
    rows = []
    with open(os.path.join(DATA, "video_episode_map.csv"), encoding="utf-8-sig") as f:
        mp = [r for r in csv.DictReader(f) if r["series"] == "32"]
    for r in mp:
        ep = int(r["episode"])
        title = r["title_join"]
        dur = int(r["duration_s"])
        if ep not in subs:
            rows.append(dict(series="32", episode=ep, title=title, hanzi=0,
                             minutes=round(dur / 60.0, 1), chars_per_min=0,
                             dup_line_pct="", head_term="", head_count="",
                             head_first_pct="", best_term="", best_count="",
                             best_first_pct="", verdict="缺字幕",
                             note="zip 内未找到 P%02d_字幕全文.txt" % ep))
            continue
        raw, src = subs[ep]
        t = norm(raw)
        terms, basis = LEXICON.get(ep, ([], ""))
        head = find_any(t, terms[0]) if terms else (None, 0, -1)
        # 在全部词里找「次数最多且够早」的那一个，作为证据词
        best = (None, 0, -1)
        for variants in terms:
            hit = find_any(t, variants)
            if hit[1] > best[1]:
                best = hit
        head_ok = head[1] >= MIN_COUNT and 0 <= head[2] < EARLY_FRAC * 100
        best_ok = best[1] >= MIN_COUNT and 0 <= best[2] < EARLY_FRAC * 100
        if head_ok:
            verdict = "一致"
            note = basis
        elif best_ok:
            verdict = "一致（转述）"
            note = basis + "；标题中心词未达门槛，由同义／上位词命中"
        elif best[1] >= MIN_COUNT:
            verdict = "部分一致"
            note = basis + "；标题词出现但首现晚于 40%，只在后段展开"
        else:
            verdict = "待核"
            note = basis + "；词表内无词达门槛，须人读判定"
        rows.append(dict(series="32", episode=ep, title=title, hanzi=len(t),
                         minutes=round(dur / 60.0, 1),
                         chars_per_min=round(len(t) / (dur / 60.0), 1),
                         dup_line_pct=round(dup_line_pct(raw), 1),
                         head_term=head[0] or "", head_count=head[1],
                         head_first_pct=round(head[2], 0) if head[2] >= 0 else "",
                         best_term=best[0] or "", best_count=best[1],
                         best_first_pct=round(best[2], 0) if best[2] >= 0 else "",
                         verdict=verdict, note=note))
    rows.sort(key=lambda x: x["episode"])
    return rows


# ---------------------------------------------------------------- 核对二：38 集规则定位
def check_locators(lib):
    subs = load_series38(lib)
    with open(os.path.join(DATA, "rules.csv"), encoding="utf-8-sig") as f:
        rules = list(csv.DictReader(f))
    per_ep = {}
    for r in rules:
        loc = r.get("source_locator") or ""
        m = re.match(r"LX38-E(\d+):(.*)$", loc)
        if not m:
            continue
        ep = int(m.group(1))
        segs = [(int(a), int(b)) for a, b in re.findall(r"L(\d+)-(\d+)", m.group(2))]
        rec = per_ep.setdefault(ep, dict(total=0, ok=0, bad=[], locs=[]))
        rec["total"] += 1
        if ep not in subs:
            rec["bad"].append((r["rule_id"], "无字幕文件"))
            continue
        lines = subs[ep][0].splitlines()
        if not segs:
            rec["bad"].append((r["rule_id"], "行号不可解析"))
            continue
        if any(b > len(lines) or a < 1 or a > b for a, b in segs):
            rec["bad"].append((r["rule_id"], "行号越界 %s / 共 %d 行" % (segs, len(lines))))
            continue
        seg = norm("".join("".join(lines[a - 1:b]) for a, b in segs))
        txt = norm(r["rule_text"])
        # 在引文里取最长能在该行段内原样找到的窗口；≥6 字即认定「引文确实出自这里」
        k_best = 0
        for k in range(min(14, len(txt)), 3, -1):
            if any(txt[i:i + k] in seg for i in range(0, len(txt) - k + 1)):
                k_best = k
                break
        if k_best >= 6:
            rec["ok"] += 1
        else:
            rec["bad"].append((r["rule_id"], "引文未命中（最长共同窗口 %d 字）" % k_best))
    rows = []
    for ep in range(1, 39):
        raw, src = subs.get(ep, ("", ""))
        rec = per_ep.get(ep, dict(total=0, ok=0, bad=[]))
        if not rec["total"]:
            # 不能直接说「本集无学理」——先探一下命理术语密度再下结论
            probe = ["食伤生财", "暗财", "寅午", "日主", "用神", "格局", "十神",
                     "冲合会", "大运", "流年", "月令", "天干", "地支"]
            hits = [(w, raw.count(w)) for w in probe if raw.count(w)]
            hits.sort(key=lambda x: -x[1])
            if hits:
                verdict = "未沉淀"
                note = ("本集未沉淀规则，但正文含命理术语 %s，属抽取缺口（待补），"
                        "不得据此称该集无学理内容" % "、".join("%s×%d" % h for h in hits[:5]))
            else:
                verdict = "无规则"
                note = "本集未沉淀规则，术语探针亦无命中；仍须人读确认"
        elif rec["bad"]:
            verdict = "定位有误"
            note = "；".join("%s %s" % (rid, why) for rid, why in rec["bad"])
        else:
            verdict = "定位核"
            note = "%d 条规则引文全部在所指行段原样命中" % rec["ok"]
        rows.append(dict(series="38", episode=ep,
                         title="（无标题，仅编号）", hanzi=len(norm(raw)),
                         lines=len(raw.splitlines()),
                         dup_line_pct=round(dup_line_pct(raw), 1) if raw else "",
                         rules=rec["total"], locator_ok=rec["ok"],
                         locator_bad=len(rec["bad"]), verdict=verdict, note=note))
    return rows


# ---------------------------------------------------------------- 输出
def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\r\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default="D:/梁湘润", help="资料库根目录（包外）")
    ap.add_argument("--write", action="store_true", help="写入 data/ 下两个 CSV")
    a = ap.parse_args()

    t32 = check_titles(a.lib)
    c38 = check_locators(a.lib)

    if not any(r["hanzi"] for r in t32) or not any(r["hanzi"] for r in c38):
        print("找不到字幕目录，检查 --lib：%s" % a.lib)
        print("  期望 %s/梁湘润 32级视频任务/**/*.zip" % a.lib)
        print("  期望 %s/梁湘润 38集视频教程/P*_字幕全文*.txt" % a.lib)
        return 2

    cnt = Counter(r["verdict"] for r in t32)
    print("== 32 集：标题 ↔ 正文核心")
    for k in ("一致", "一致（转述）", "部分一致", "待核", "缺字幕"):
        if cnt.get(k):
            eps = [r["episode"] for r in t32 if r["verdict"] == k]
            print("  %-8s %2d 集  %s" % (k, cnt[k], eps if len(eps) <= 8 else "%d–%d" % (min(eps), max(eps))))
    bad = [r for r in t32 if r["verdict"] in ("待核", "缺字幕")]
    for r in bad:
        print("    ! E%02d %s：%s" % (r["episode"], r["title"], r["note"]))

    cnt2 = Counter(r["verdict"] for r in c38)
    tot = sum(r["rules"] for r in c38)
    ok = sum(r["locator_ok"] for r in c38)
    print("== 38 集：规则引文 ↔ 所指行段")
    for k, v in cnt2.items():
        print("  %-6s %2d 集" % (k, v))
    print("  带 LX38 定位的规则 %d 条，引文原样命中 %d 条（%.2f%%）" % (tot, ok, ok * 100.0 / max(1, tot)))
    for r in c38:
        if r["verdict"] not in ("定位核",):
            print("    ! E%02d %s：%s" % (r["episode"], r["verdict"], r["note"]))

    if a.write:
        f1 = os.path.join(DATA, "subtitle_content_check.csv")
        write_csv(f1, t32, ["series", "episode", "title", "hanzi", "minutes", "chars_per_min",
                            "dup_line_pct", "head_term", "head_count", "head_first_pct",
                            "best_term", "best_count", "best_first_pct", "verdict", "note"])
        f2 = os.path.join(DATA, "subtitle_episode_coverage.csv")
        write_csv(f2, c38, ["series", "episode", "title", "hanzi", "lines", "dup_line_pct",
                            "rules", "locator_ok", "locator_bad", "verdict", "note"])
        print("已写入：\n  %s\n  %s" % (f1, f2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
