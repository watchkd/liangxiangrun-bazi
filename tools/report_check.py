# -*- coding: utf-8 -*-
"""交付件验收器（P3）

用途：五轨交付物出厂前的机器验收。`validate.py` 验的是**包结构**，本器验的是
**交付件本身**——板块是否齐、断语是否挂证、命书里有没有漏出工程标记、附录有没有
冒充梁氏原文。

用法：
    python tools/report_check.py 文件 [文件...]         # 自动识别轨别
    python tools/report_check.py 文件 --type report     # 指定轨别
    python tools/report_check.py --self-test           # 自检（好坏样本各一）

轨别与硬规矩（见 references/report_19.md 第三节）：
    mingshu   命书    十四节齐备；零工程标记；字数下限；无乱码
    report    报告    十九板块齐备；每板块挂证或明写查不出；无星级；无乱码
    draft     底稿    挂 rule_id；有依据表；标证据等级
    appendix  附录    声明非梁氏原文；三档宜／平／避；不得出现证据等级与星级
    index     索引    rule_id／cell_id 清单成规模；去重

退出码：0 全通过（可有 WARN）；1 存在 FAIL。
"""
import argparse
import os
import re
import sys
from html import unescape as html_unescape

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲"
CN_NUM = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
          "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九"]

# 前须非字母／连字符，否则 TAB-LXR-TH-01-ORIG 里会误抓出「R-TH-01」这条并不存在的规则
RULE_RE = re.compile(r"(?<![A-Z-])R(?:-[A-Z0-9]+)+-\d+|\bR\d{1,3}\b")
CELL_RE = re.compile(r"(?:TB|JS|JB|XJ|TH|T)-[A-Z0-9]+(?:-[A-Z0-9]+)*")
GARBLED = ["\ufffd", "锟斤拷", "烫烫", "ï¿½", "\\ufffd"]
# 命书不许出现的工程词（与 validate.R09 同表，另加正则）
ENG_WORDS = ["rule_id", "证据等级", "依据表", "部分核", "已核", "待核", "未入库",
             "置信", "附录", "E1 ", "E3 ", "E4 ", "E6 ", "R-JB", "R-MF", "R-SZ",
             "T-ORIG", "T-X11"]
MINGSHU_HEADS_HTML = ["命式", "已知因", "总评", "妻", "财", "子", "禄", "寿", "性情",
                      "父母兄弟", "疾病", "大运批导", "流年举要", "附言"]
MINGSHU_HEADS_MD = ["命序", "一、已知因", "二、总评", "三、妻", "四、财", "五、子",
                    "六、禄", "七、大运分述", "八、提要", "九、边界", "附一、批词依据表"]

REPORT_TITLES = ["基本信息", "四柱排盘", "五行十神", "刑冲合会", "格局", "调候",
                 "用神", "六亲", "大运", "流年", "人生建议", "学业", "事业",
                 "财富", "人际", "健康", "年度行动", "风险", "总纲"]
APPENDIX_HEADS = ["衣", "色", "方位", "起居", "择时", "饰", "食", "总纲"]


class Result:
    def __init__(self, path):
        self.path = path
        self.rows = []

    def add(self, ok, code, msg, warn=False):
        self.rows.append({"ok": ok, "warn": warn and not ok, "code": code, "msg": msg})

    @property
    def fails(self):
        return [r for r in self.rows if not r["ok"] and not r["warn"]]

    @property
    def warns(self):
        return [r for r in self.rows if r["warn"]]

    def report(self):
        for r in self.rows:
            tag = "ok  " if r["ok"] else ("WARN" if r["warn"] else "FAIL")
            print(f"  {tag} {r['code']}  {r['msg']}")
        verdict = "FAIL" if self.fails else ("WARN" if self.warns else "PASS")
        print(f"  → {os.path.basename(self.path)}：{verdict}"
              f"（{len(self.rows) - len(self.fails) - len(self.warns)} 通过／"
              f"{len(self.warns)} 警告／{len(self.fails)} 失败）")
        return verdict


def plain(text):
    """HTML 去标签、去样式，取正文。"""
    t = re.sub(r"<style>.*?</style>", "", text, flags=re.S)
    t = re.sub(r"<script>.*?</script>", "", t, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"</(p|div|h\d|li|tr)>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    return t


def to_md(text):
    """HTML → md 形态，供 md 侧闸门复用。

    HTML 版式件与 md 是同一份稿的两种皮。若只把标签剥掉，`^## 附二` 与「〔确断〕」
    这两类判据就永远匹配不上，报告轨 B09／B11 必然误报 FAIL——
    **不是稿子错，是查法错**。故这里补两件事：标题还原成 `##`，强度角标还原成〔…〕。
    """
    t = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", "", text)

    def _h(m):
        txt = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        return "\n\n" + "#" * int(m.group(1)) + " " + txt + "\n\n"

    t = re.sub(r"(?is)<h([1-6])[^>]*>(.*?)</h\1>", _h, t)
    # <span class="tag g1" title="…">确断</span> → 〔确断〕
    t = re.sub(r'(?is)<span[^>]*class="tag[^"]*"[^>]*>\s*([^<]{1,8}?)\s*</span>', r"〔\1〕", t)
    t = re.sub(r"(?is)<br\s*/?>", "\n", t)
    t = re.sub(r"(?is)</t[hd]>", " | ", t)
    t = re.sub(r"(?is)</tr>", " |\n", t)
    t = re.sub(r"(?is)</(p|div|li)>", "\n", t)
    t = re.sub(r"(?is)<[^>]+>", "", t)
    return html_unescape(t)


def heads(text, html):
    if html:
        hs = re.findall(r"<h[12][^>]*>(?:<span[^>]*>[^<]*</span>)?([^<]*)</h[12]>", text)
    else:
        hs = [ln.lstrip("#").strip() for ln in text.splitlines() if ln.startswith("#")]
    return hs


def detect(text, name):
    """按扩展名与抬头判轨。判错的代价是把命书当报告查（或反之），故先判扩展名。

    注意：md 版「详批命书」自带附一依据表与证据等级，实为 C 轨底稿
    （`references/report_19.md` 第三节：C 底稿＝`_命书/详批_*.md`），
    只有 HTML 才是 A 轨命书。
    """
    ext = os.path.splitext(name)[1].lower()
    head = text[:6000]
    # 文件名带「索引」才是索引轨。不能只看抬头：报告正文会写「证据见附二」，
    # 早先按抬头判，于是整份报告被当索引轨查（只跑 E01–E03，十一项闸门一条没过）——
    # 闸门没报错，是因为它压根没查。
    if "索引" in name:
        return "index"
    if ext in (".html", ".htm"):
        if "<title>命书" in head or "命式" in head:
            return "mingshu"
        if "非梁氏原文" in head or "行动建议" in head:
            return "appendix"
        return "report"
    if "批词" in os.path.basename(name):
        # 批词是命书（A 轨）的正文稿，断语体、零工程标记。它不是底稿：底稿要挂证，批词不许挂证。
        return "prose"
    if "详批命书" in head or "附一、批词依据表" in head:
        return "draft"
    # 底稿的另一形态：analyze.py 的输出。它不带「详批命书」字样，文件名又是 .md，
    # 早先落到末尾默认值 report，于是被按报告的十一项去查（B11 缺附二等），全部查错。
    if "结构化分析" in head or "批者底稿" in head:
        return "draft"
    # 报告优先判：十九板块报告的卷首会提「非梁氏原文」这类字眼，
    # 若先判附录，会把报告误判成附录轨（D 轨），闸门全查错。
    # 卷首是报告独有（索引、附录、底稿皆无），故并列作判据之一。
    if ("十九板块" in head or "卷首" in head
            or len(re.findall(r"(?m)^##\s*[①②③④⑤⑥⑦⑧⑨⑩]", text)) >= 3):
        return "report"
    if "证据索引" in head:
        return "index"
    if "非梁氏原文" in head or "行动建议" in head or "附录" in name:
        return "appendix"
    if "底稿" in name:
        return "draft"
    return "report"


def active(body):
    """剔掉「讲禁令」的行。规格文件里「禁止给星级」不是违规，是规矩本身。"""
    keep = []
    for ln in body.splitlines():
        if re.search(r"不得|禁止|不许|不可|勿|不出现|不给|不用|一律不|严禁|不作|不写|不判", ln):
            continue
        keep.append(ln)
    return "\n".join(keep)


def check_garbled(res, body):
    bad = [g for g in GARBLED if g in body]
    odd = re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", body)
    if bad:
        res.add(False, "X01", "存在乱码字符：" + "、".join(repr(b) for b in bad))
    elif odd:
        res.add(False, "X01", f"存在控制字符 {len(odd)} 处")
    else:
        res.add(True, "X01", "无乱码字符")


def check_mingshu(res, text, body, html):
    hs = heads(text, html)
    need = MINGSHU_HEADS_HTML if html else MINGSHU_HEADS_MD
    lack = [h for h in need if not any(h in x for x in hs)]
    if lack:
        res.add(False, "M02", "缺节：" + "、".join(lack))
    else:
        res.add(True, "M02", f"{len(need)} 节齐备")

    # md 版命书自带「附一、批词依据表」与附二～附五，故「依据表／附录」二字不算脏；
    # HTML 交付件则一律不许出现（与 validate.R09 同表）。
    words = ENG_WORDS if html else [w for w in ENG_WORDS if w not in ("依据表", "附录")]
    dirty = [w for w in words if w in body]
    eng = RULE_RE.findall(body) + CELL_RE.findall(body)
    if dirty or eng:
        res.add(False, "M01", "命书含工程标记："
                + "、".join(dirty + sorted(set(eng))[:6]))
    else:
        res.add(True, "M01", "零工程标记")

    n = len(re.sub(r"\s+", "", body))
    low = 6000 if html else 3000
    if n < low:
        res.add(False, "M03", f"正文仅 {n} 字，低于下限 {low}，疑退化为纯结构")
    else:
        res.add(True, "M03", f"正文 {n} 字（下限 {low}）")


def _blocks(text, marker, html=False):
    """按板块标记切块；marker 为「circled」或「cn」。

    HTML 的圈子编号在 <span class="no"> 里，不在行首，故须单独一条式。
    """
    if marker == "circled":
        if html:
            pat = re.compile(r"<h[12][^>]*>\s*(?:<span[^>]*>\s*)?([%s])" % CIRCLED)
        else:
            pat = re.compile(r"^[#*\s]*([%s])" % CIRCLED, re.M)
    else:
        if html:
            pat = re.compile(r"<h[12][^>]*>\s*(?:<span[^>]*>\s*)?([一二三四五六七八九十]{1,3})、")
        else:
            pat = re.compile(r"^#{1,4}\s*([一二三四五六七八九十]{1,3})、", re.M)
    idx = [(m.start(), m.group(1)) for m in pat.finditer(text)]
    out = {}
    for i, (s, k) in enumerate(idx):
        e = idx[i + 1][0] if i + 1 < len(idx) else len(text)
        out.setdefault(k, []).append(text[s:e])
    return out


def check_report(res, text, body, html):
    blk = _blocks(text, "circled", html)
    marker = "circled"
    if len(blk) < 19:
        alt = _blocks(text, "cn", html)
        if len(alt) > len(blk):
            blk, marker = alt, "cn"
    n = len(blk)
    if n < 19:
        res.add(False, "B01", f"板块仅 {n} 个，十九板块不全（识别方式：{marker}）")
    else:
        res.add(True, "B01", f"十九板块齐备（识别方式：{marker}）")

    # 一个板块算「落地」有三条路：挂编号（详版）／明写查不出／给了带强度的判断（简版）。
    # 报告有两型：详版给复核者看编号，简版给来客看判断。只要不是空话，两型都收。
    JUDGE_RE = re.compile(r"〔确断〕|〔倾向〕|〔存疑〕|照结构看|多半是|须看运|不作断")
    missing = []
    for k, segs in blk.items():
        seg = "".join(segs)
        if not (RULE_RE.search(seg) or CELL_RE.search(seg) or JUDGE_RE.search(seg)
                or re.search(r"查不出|不适用|无据|本包无|未入库", seg)):
            missing.append(k)
    if missing:
        res.add(False, "B02", "板块既未挂证、无判断、也未写「查不出」：" + "、".join(missing))
    elif n:
        res.add(True, "B02", "各板块均有判断或明写查不出")

    star = re.findall(r"[★☆]|五星|评分|打分为|指数\s*\d", active(body))
    if star:
        res.add(False, "B03", f"出现星级／评分表述 {len(star)} 处（本包已撤星级）")
    else:
        res.add(True, "B03", "无星级／评分")

    todo = body.count("〔待批〕") + body.count("〔待生成〕")
    if todo:
        res.add(False, "B06", f"仍有 {todo} 处「待批」未填——骨架不是交付件")
    else:
        res.add(True, "B06", "无待批占位")

    ids = set(RULE_RE.findall(body)) | set(CELL_RE.findall(body))
    has_idx = bool(re.search(r"(?m)^#{2,}\s*(附二[　 ]*)?证据索引[　 ]*$", body))
    if not ids and not has_idx:
        res.add(True, "B04", "简版报告：正文不挂编号（判断为主，出处另存底稿）")
    elif len(ids) < 12:
        res.add(False, "B04", f"全文仅 {len(ids)} 个编号却附了索引，疑索引与正文不配", warn=True)
    else:
        res.add(True, "B04", f"去重证据 {len(ids)} 条")

    nch = len(re.sub(r"\s+", "", body))
    if nch < 8000:
        res.add(False, "B05", f"正文 {nch} 字，低于 8000，十九板块多半写空", warn=True)
    else:
        res.add(True, "B05", f"正文 {nch} 字")

    check_front(res, body)
    check_caveat(res, body)
    check_grades(res, blk, marker)
    check_absolutes(res, body)
    check_ev_consistency(res, body)


def check_front(res, body):
    """B07 卷首流程卡：读者须先知道「手上有什么、做到哪一步」。

    只认实质，不认标题：材料表须有「已给／未给」，六步表须有「做到／部分／未做」。
    标题写了而表是空的，等于没写——这条专门拦那种。
    """
    if "批断流程" not in body:
        res.add(False, "B07", "缺卷首「批断流程与材料清点」——读者无从判断哪一步因缺料未做")
        return
    has_mat = ("材料清点" in body) and re.search(r"已给|未给", body)
    has_step = ("六步执行状态" in body or "执行状态" in body) and \
        len(re.findall(r"做到|部分|未做", body)) >= 4
    if has_mat and has_step:
        res.add(True, "B07", "卷首齐备：材料清点＋六步执行状态")
    else:
        miss = []
        if not has_mat:
            miss.append("材料清点（已给／未给）")
        if not has_step:
            miss.append("六步执行状态（做到／部分／未做）")
        res.add(False, "B07", "卷首有标题而缺实质：" + "、".join(miss))


def check_caveat(res, body):
    """B08 附一存疑与反证：报告最该被看的一节。

    要求两样：证据强度分布表（逐节）＋最薄之处的点明。
    这一节缺了，整份报告就是「每句一样硬」——那正是本包要区别于网友版的地方。
    """
    if "存疑与反证" not in body:
        res.add(False, "B08", "缺「存疑与反证」节：无法分辨哪句硬、哪句软")
        return
    dist = ("证据强度分布" in body) and re.search(r"证据[\s\S]{0,80}确断", body)
    thin = "最薄" in body
    if dist and thin:
        res.add(True, "B08", "存疑节齐备：强度分布＋最薄指出")
    else:
        miss = []
        if not dist:
            miss.append("证据强度分布表")
        if not thin:
            miss.append("最薄之处")
        res.add(False, "B08", "存疑节缺：" + "、".join(miss))


def check_grades(res, blk, marker="circled"):
    """B09 下篇五节（⑫–⑯）须有判断强度标记。

    下篇最容易写成「一通建议」——每句都像真的。要求每节至少一处
    〔确断〕〔倾向〕〔存疑〕，或明写「不适用／查不出」。
    """
    if not blk:
        return
    if marker == "circled":
        keys = list("⑫⑬⑭⑮⑯")
    else:
        keys = ["十二", "十三", "十四", "十五", "十六"]
    lack = []
    for k in keys:
        seg = "".join(blk.get(k, []))
        if not seg:
            continue
        if not (re.search(r"〔(确断|倾向|存疑)〕", seg) or re.search(r"不适用|查不出", seg)):
            lack.append(k)
    if lack:
        res.add(False, "B09", "下篇未标判断强度：" + "、".join(lack)
                + "（每节至少一处确断／倾向／存疑，或明写不适用）")
    else:
        res.add(True, "B09", "下篇五节均标强度或不适用")


ABSOLUTE = [
    (r"(?<![不非勿「])必然(?![之」])", "必然"),
    (r"(?<![「])注定(?!」)", "注定"),
    (r"百分百|100%", "百分百"),
    (r"铁定", "铁定"),
    (r"绝对会|绝对能|绝对有", "绝对会"),
]


def check_absolutes(res, body):
    """B10 绝对断言：梁氏分寸语是「七成应验即合理合宜」，不作必中之断。"""
    hits = []
    for pat, label in ABSOLUTE:
        n = len(re.findall(pat, active(body)))
        if n:
            hits.append("%s×%d" % (label, n))
    if hits:
        res.add(False, "B10", "出现绝对断言：" + "、".join(hits)
                + "（本包不作必中之断，改「多主」「宜」「偏向」）")
    else:
        res.add(True, "B10", "无绝对断言")


def _real_ids(text):
    """只取「真实编码」：规则 id 全收；格值须四段以上，且排除 `TAB-` 表号与通配前缀。

    正文常写表级引用（`JS-SS-02` 指整张表）与通配（`TB-XJ*`），它们不是格值证据；
    索引按格值收（`JS-SS-02-048`），两者本不必对齐，混在一起算会把好报告判坏。
    """
    ids = set(RULE_RE.findall(text))
    for c in CELL_RE.findall(text):
        if len(c.split("-")) >= 4 and not c.startswith("TAB-"):
            ids.add(c)
    return ids


def check_ev_consistency(res, body):
    """B11 证据索引与正文对账：索引须覆盖正文全部编号，防「索引是写的、正文是凑的」。

    切分必须认**标题**，不能认词。早先用 `body.partition("证据索引")`，卷首一句
    「证据索引见附二」就把正文拦在外面，于是正文编号算 0 条、索引算全篇，两边都空，
    闸门「一致（0 条）」通过——**查空即过，是最坏的一种闸门**。
    """
    m = (re.search(r"(?m)^#{2,}\s*附二[　 ]*证据索引[　 ]*$", body)
         or re.search(r"(?m)^#{2,}\s*证据索引[　 ]*$", body))
    if not m:
        # 简版报告不附索引，是正体，不是缺件。但正文若挂了编号又不给索引，就是半截——
        # 读者拿着编号无处对，不如不挂。
        ids = _real_ids(body)
        if ids:
            res.add(False, "B11",
                    "正文挂了 %d 条编号却无索引：要么删编号走简版，要么补「## 附二　证据索引」"
                    % len(ids))
        else:
            res.add(True, "B11", "简版报告：正文不挂编号，无须索引")
        return
    head, idx = body[:m.start()], body[m.end():]
    if "待生成" in idx:
        res.add(False, "B11", "证据索引未生成（仍是占位）", warn=True)
        return
    in_text = _real_ids(head)
    in_idx = _real_ids(idx)
    if not in_text:
        # 正文一条编号都没有，多半不是「真的没证据」，是切分又错了——须报，不可静默通过
        res.add(False, "B11", "正文未检出任何编号（切分或格式可疑，不可视为一致）")
        return
    miss = sorted(in_text - in_idx)
    if miss:
        res.add(False, "B11", "索引漏收正文编号 %d 条：%s" % (len(miss), "、".join(miss[:6])),
                warn=True)
    else:
        res.add(True, "B11", "索引与正文一致（%d 条）" % len(in_text))


def check_appendix(res, text, body, html):
    if "非梁氏原文" not in body and "通行" not in body:
        res.add(False, "D01", "缺「非梁氏原文／通行引申」声明")
    else:
        res.add(True, "D01", "已声明非梁氏原文")

    if not all(k in body for k in ("宜", "平", "避")):
        res.add(False, "D02", "未用三档「宜／平／避」")
    else:
        res.add(True, "D02", "三档宜／平／避齐备")

    star = re.findall(r"[★☆]|五星|评分|分数|评级", active(body))
    if star:
        res.add(False, "D03", f"出现星级／评分 {len(star)} 处（附录亦不得给分）")
    else:
        res.add(True, "D03", "无星级／评分")

    act = active(body)
    eng = RULE_RE.findall(act) + [w for w in ("证据等级", "E1", "E3", "E4", "E6")
                                  if w in act]
    if eng:
        res.add(False, "D04", "附录不得标证据等级，实含：" + "、".join(sorted(set(eng))[:6]))
    else:
        res.add(True, "D04", "未标证据等级")

    hs = heads(text, html)
    hit = [h for h in APPENDIX_HEADS if any(h in x for x in hs)]
    if len(hs) < 6:
        res.add(False, "D05", f"板块仅 {len(hs)} 节，附录八板块不全", warn=True)
    else:
        res.add(True, "D05", f"{len(hs)} 节（命中主题 {len(hit)}）")


def check_prose(res, text, body, html):
    """批词轨：命书（A 轨）的正文稿。

    与底稿（C 轨）正好相反——底稿必须挂证挂等级，批词一个标记都不许有。
    这一轨以前没有，于是批词被按报告去查（缺卷首、缺附二、板块不足十九），
    全是误判；作者会以为稿子错了，其实是没有尺子。
    """
    eng = re.findall(r"R-[A-Z]{2}-\d+|E[1-6]\s|证据等级|部分核|已核|待核|未入库|置信", body)
    if eng:
        res.add(False, "P01", "批词含工程标记 %d 处（%s）：命书是断语体，标记留底稿"
                % (len(eng), "、".join(sorted(set(eng))[:4])))
    else:
        res.add(True, "P01", "无工程标记")

    secs = len(re.findall(r"(?m)^#{2,3}\s*\S", body)) or \
        len(re.findall(r"(?m)^[一二三四五六七八九十]{1,3}、", body))
    if secs < 3:
        res.add(False, "P02", "仅 %d 节，批词须分节（总评／格局／六亲…至少三节）" % secs)
    else:
        res.add(True, "P02", "分 %d 节" % secs)

    nch = len(re.sub(r"\s+", "", body))
    if nch < 3000:
        res.add(False, "P03", "正文 %d 字，低于 3000，疑未成篇" % nch)
    else:
        res.add(True, "P03", "正文 %d 字" % nch)

    star = re.findall(r"[★☆]|五星|评分|分数|评级", active(body))
    if star:
        res.add(False, "P04", "出现星级／评分 %d 处" % len(star))
    else:
        res.add(True, "P04", "无星级／评分")

    ab = [w for pat, w in ABSOLUTE if re.search(pat, active(body))]
    if ab:
        res.add(False, "P05", "绝对断言：" + "、".join(sorted(set(ab))[:4]))
    else:
        res.add(True, "P05", "无绝对断言")


def check_draft(res, text, body, html):
    ids = set(RULE_RE.findall(body))
    if len(ids) < 20:
        res.add(False, "C01", f"底稿仅挂 {len(ids)} 个 rule_id，少于 20")
    else:
        res.add(True, "C01", f"挂 rule_id {len(ids)} 条")

    if not re.search(r"依据|出处|来源", body):
        res.add(False, "C02", "无依据／出处分节")
    else:
        res.add(True, "C02", "有依据节")

    if not re.search(r"E[1-6]|已核|待核|部分核", body):
        res.add(False, "C03", "未标证据等级")
    else:
        res.add(True, "C03", "标证据等级")

    if RULE_RE.search(re.sub(r"\|[^\n]*", "", body)) and False:
        pass


def check_index(res, text, body, html):
    ids = RULE_RE.findall(body) + CELL_RE.findall(body)
    uniq = set(ids)
    if len(uniq) < 20:
        res.add(False, "E01", f"索引仅 {len(uniq)} 条，规模不足")
    else:
        res.add(True, "E01", f"索引 {len(uniq)} 条")
    dup = len(ids) - len(uniq)
    if dup > max(3, len(uniq) // 20):
        res.add(False, "E02", f"重复条目 {dup} 条，索引未去重", warn=True)
    else:
        res.add(True, "E02", f"重复 {dup} 条")
    if not re.search(r"已核|待核|部分核|E[1-6]", body):
        res.add(False, "E03", "索引未标来源等级", warn=True)
    else:
        res.add(True, "E03", "标来源等级")


def check_file(path, kind=None):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    html = path.lower().endswith((".html", ".htm"))
    # HTML 版式件先还原成 md 形态再查：否则 `^## 附二` 与「〔确断〕」两类判据永远不匹配，
    # 报告轨 B09／B11 会对着一份合格的 HTML 报 FAIL。
    body = to_md(text) if html else text
    kind = kind or detect(text, os.path.basename(path))
    if kind == "report" and html:
        # 报告轨的判据全是 md 形态（## 附二、〔确断〕、^## ①）。HTML 版式件统一还原后再查，
        # 且必须连 text 一起换——只换 body 会让 _blocks 在原文上切、在译文上找，切出来的段落对不上。
        text = body = to_md(text)
        html = False
    res = Result(path)
    check_garbled(res, body)
    {"mingshu": check_mingshu, "report": check_report, "appendix": check_appendix,
     "draft": check_draft, "index": check_index,
     "prose": check_prose}[kind](res, text, body, html)
    print(f"[{kind}] {path}")
    return res


def self_test():
    """自检：好坏样本各一，验本器真的会拦。"""
    import tempfile

    good_ms = "\n".join(["# 详批命书", ""] + [f"## {h}\n\n正文一段。" for h in MINGSHU_HEADS_MD]
                        + ["\n" + "文" * 3200])
    bad_ms = good_ms + "\n见 R-SZ-019 与证据等级 E3。\n"

    # 好样例须把 P8 新增的四件一并备齐：卷首流程卡、下篇强度、存疑节、证据索引。
    # 缺一样就 FAIL，正是这几条闸门要的效果，故样例也得跟着长。
    front = "\n".join([
        "## 卷首　批断流程与材料清点", "",
        # 诱饵：正文先提一次词，验 B11 是按标题切、不是按词切（曾经切错还静默通过）
        "> 证据索引见附二，薄弱处见附一。", "",
        "### 一、材料清点", "", "| 项 | 状态 | 影响 |", "|---|---|---|",
        "| 性别 | 已给（男） | 六亲据此 |", "| 经度 | 未给 | 真太阳时未校正 |", "",
        "### 二、六步执行状态", "", "| 步 | 内容 | 状态 |", "|---|---|---|",
        "| 1 | 定盘 | 做到 |", "| 2 | 神煞 | 做到 |", "| 3 | 格局 | 做到 |",
        "| 4 | 调候 | 做到 |", "| 5 | 用神 | 部分 |", "| 6 | 流年 | 未做 |", ""])
    body = []
    for i in range(19):
        grade = "〔确断〕" if 11 <= i <= 15 else ""
        body.append(f"## {CIRCLED[i]} {REPORT_TITLES[i]}\n\n{grade}据 R-SZ-019 与 TB-XJ04 论之。")
    tail = "\n".join([
        "", "## 附一　存疑与反证", "", "### 一、证据强度分布", "",
        "| 板 | 标题 | 证据 | 确断 |", "|---|---|---|---|", "| ① | 基本信息 | 1 | 1 |", "",
        "### 二、本案最薄三处", "", "按证据条数排序，**① 基本信息（证据 1 条）**。", "",
        "## 附二　证据索引", "", "| 编号 | 主题 | 来源 | 定位 | 等级 |", "|---|---|---|---|---|",
        "| `R-SZ-019` | 败亡 | 书 | p1 | E3 |", ""])
    good_rep = front + "\n".join(body) + "\n" + tail + "\n" + "文" * 8100
    bad_rep = "\n".join([f"## {CIRCLED[i]} {REPORT_TITLES[i]}\n\n此格大吉。"
                         for i in range(18)]) + "\n★五星"
    # 索引仅以正文提到、附二标题缺失：须拦。若 B11 按词切分，这种稿子会「一致（0 条）」通过
    bad_rep2 = good_rep.replace("## 附二　证据索引", "**附二**证据索引如下：")
    good_prose = ("## 总评\n\n" + "此造庚金生于亥月，冬令金寒。" * 260
                  + "\n\n## 格局\n\n月令亥，格取偏财。\n\n## 六亲\n\n母缘厚。\n")
    bad_prose = good_prose.replace("月令亥，格取偏财。", "月令亥，格取偏财（见 R-SZ-019，E3 已核）。")

    good_app = "# 行动建议\n\n非梁氏原文，通行引申。\n\n## 一、衣\n宜青\n## 二、色\n平\n## 三、方位\n避西\n## 四、起居\n宜早\n## 五、择时\n平\n## 六、总纲\n避争\n" + "文" * 200
    bad_app = good_app + "\n★★★★★ 评分 95\n（E3 已核）"

    cases = [("命书·好", {"ms.md": good_ms}, "mingshu", 0),
             ("命书·坏（漏工程标记）", {"ms.md": bad_ms}, "mingshu", 1),
             ("报告·好", {"rp.md": good_rep}, "report", 0),
             ("报告·坏（缺板块＋星级）", {"rp.md": bad_rep}, "report", 1),
             ("报告·坏（索引无标题）", {"rp.md": bad_rep2}, "report", 1),
             ("批词·好", {"批词_x.md": good_prose}, "prose", 0),
             ("批词·坏（混入 rule_id）", {"批词_x.md": bad_prose}, "prose", 1),
             ("附录·好", {"ap.md": good_app}, "appendix", 0),
             ("附录·坏（星级＋证据等级）", {"ap.md": bad_app}, "appendix", 1)]
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        for name, files, kind, want in cases:
            for fn, content in files.items():
                fp = os.path.join(d, fn)
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(content)
                res = check_file(fp, kind)
                got = 1 if res.fails else 0
                ok = got == want
                bad += 0 if ok else 1
                print(f"  {'ok' if ok else 'FAIL'} 自检「{name}」期望退出 {want}，实得 {got}")
    print(f"自检结果：{'PASS' if not bad else 'FAIL'}（{len(cases)} 组）")
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(description="交付件验收器：命书／报告／底稿／附录／索引")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--type", choices=["auto", "mingshu", "report", "draft", "prose",
                                       "appendix", "index"], default="auto")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if not args.files:
        ap.error("须给至少一个文件；或 --self-test")
    verdicts = []
    for p in args.files:
        if not os.path.exists(p):
            print(f"  缺文件：{p}")
            verdicts.append("FAIL")
            continue
        res = check_file(p, None if args.type == "auto" else args.type)
        verdicts.append(res.report())
    sys.exit(1 if "FAIL" in verdicts else 0)


if __name__ == "__main__":
    main()
