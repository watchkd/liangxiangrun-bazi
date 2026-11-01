# -*- coding: utf-8 -*-
"""神煞探源起例判定器（R-SP-001～049）

依据：`data/quotes_verify.txt` 的 SP 段（《神煞探源》章节锚 SP:s18–s52；原文已蒸馏为引文核验库，只收被引处及邻近上下文）。

三条硬规矩
  1. **起例照原文。** 原文给出可执行起例（诀曰、法诀、对表句）者，逐字落到代码；
     原文只给诗诀或对照表为图版者，标「待人工对表」，**不猜、不以通行术数补**。
  2. **讹字不代改。** 已知两处体例不合：s21「亥人戌时」（戌为支，与「时干」体例不合）、
     s22「五十一甲位」（甲为干，与「时支」体例不合）。遇此标「原文待核」，不按己意改写。
  3. **只算成立与否，不判吉凶。** 神煞本身无吉凶（R61／R178／R187），吉凶须与日主论生克；
     R-YS 系列另有「某煞主某吉凶」之说，两说并存，本器不代裁。

用法
    python tools/shensha_calc.py 甲子 乙亥 庚戌 癸未 --gender 男
    python tools/shensha_calc.py --self-test
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
JIAZI = [STEMS[i % 10] + BRANCHES[i % 12] for i in range(60)]

STEM_ELEM = dict(zip(STEMS, "木木火火土土金金水水"))
BRANCH_ELEM = dict(zip(BRANCHES, "水土木木土火火土金金土水"))
HIDDEN = {
    "子": ["癸"], "丑": ["己", "癸", "辛"], "寅": ["甲", "丙", "戊"], "卯": ["乙"],
    "辰": ["戊", "乙", "癸"], "巳": ["丙", "戊", "庚"], "午": ["丁", "己"],
    "未": ["己", "丁", "乙"], "申": ["庚", "壬", "戊"], "酉": ["辛"],
    "戌": ["戊", "辛", "丁"], "亥": ["壬", "甲"],
}
GEN = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
YANG_STEM = set("甲丙戊庚壬")

SANHE = [("申", "子", "辰"), ("亥", "卯", "未"), ("寅", "午", "戌"), ("巳", "酉", "丑")]
SANHE_OF = {}
for _g in SANHE:
    for _b in _g:
        SANHE_OF[_b] = _g

NAYIN = [
    "海中金", "炉中火", "大林木", "路旁土", "剑锋金", "山头火",
    "涧下水", "城头土", "白蜡金", "杨柳木", "泉中水", "屋上土",
    "霹雳火", "松柏木", "长流水", "沙中金", "山下火", "平地木",
    "壁上土", "金箔金", "覆灯火", "天河水", "大驿土", "钗钏金",
    "桑柘木", "大溪水", "沙中土", "天上火", "石榴木", "大海水",
]

# 状态
HIT = "命中"
MISS = "不成立"
NA = "缺料"
MANUAL = "待人工"
TEXT = "原文待核"
NOTE = "仅记录"


def _i(b):
    return BRANCHES.index(b)


def _step(b, n):
    return BRANCHES[(_i(b) + n) % 12]


def _chong(b):
    return BRANCHES[(_i(b) + 6) % 12]


def _order(chars):
    """地支按子丑寅卯…之序输出，不用字码序。"""
    s = set(chars)
    return "".join(b for b in BRANCHES if b in s)


def _cnt(text, chars):
    return sum(1 for c in text if c in chars)


def nayin(gz):
    return NAYIN[JIAZI.index(gz) // 2]


def nayin_elem(gz):
    return NAYIN[JIAZI.index(gz) // 2][-1]


def kong(gz):
    """旬空：该旬未及之两支。"""
    i = JIAZI.index(gz)
    b0 = (i - i % 10) % 12
    return {BRANCHES[(b0 + 10) % 12], BRANCHES[(b0 + 11) % 12]}


def xun_head(gz):
    i = JIAZI.index(gz)
    return JIAZI[i - i % 10]


class Chart:
    def __init__(self, pillars, gender=None, dayun=None, liunian=None, shensha_hits=None):
        self.p = list(pillars)
        self.st = [x[0] for x in self.p]
        self.br = [x[1] for x in self.p]
        self.gender = gender
        self.dayun = [x for x in (dayun or []) if isinstance(x, str) and x in JIAZI]
        # 流年可给公历年（int）或干支；起例只认干支，公历年在此忽略
        self.liunian = [x for x in (liunian or []) if isinstance(x, str) and x in JIAZI]
        self.ss = shensha_hits or []

    # 位置
    @property
    def y_gz(self):
        return self.p[0]

    @property
    def m_gz(self):
        return self.p[1]

    @property
    def d_gz(self):
        return self.p[2]

    @property
    def h_gz(self):
        return self.p[3]

    def all_br(self, with_yun=False):
        out = list(self.br)
        if with_yun:
            out += [x[1] for x in self.dayun] + [x[1] for x in self.liunian]
        return out

    def all_gz(self, with_yun=False):
        out = list(self.p)
        if with_yun:
            out += self.dayun + self.liunian
        return out

    def has_elem(self, elem, with_hidden=True):
        for s in self.st:
            if STEM_ELEM[s] == elem:
                return True
        for b in self.br:
            if BRANCH_ELEM[b] == elem:
                return True
            if with_hidden:
                for h in HIDDEN[b]:
                    if STEM_ELEM[h] == elem:
                        return True
        return False

    def yun_text(self):
        parts = []
        if self.dayun:
            parts.append("运 " + "／".join(self.dayun))
        if self.liunian:
            parts.append("岁 " + "／".join(self.liunian))
        return "，".join(parts)


# ======================= 起例表（逐字照原文） =======================
# SP:s19 诀曰：正月甲，二月乙，三月戊，四月丙，五月丁，六月己，
#              七月庚，八月辛，九月戊，十月壬，十一月癸，十二月己
JIFENG_MONTH = {"寅": "甲", "卯": "乙", "辰": "戊", "巳": "丙", "午": "丁", "未": "己",
                "申": "庚", "酉": "辛", "戌": "戊", "亥": "壬", "子": "癸", "丑": "己"}

# SP:s20 诀曰：卯与午、丑与辰、子与酉、未与戌（年→时）
POSHA = {"卯": "午", "丑": "辰", "子": "酉", "未": "戌"}

# SP:s21 诀曰：子丑人乙时，寅人庚时，卯辰人辛时，巳人壬时，午未人癸时，
#              申人丙时，酉戌人丁时，亥人「戌」时  ← 戌为支，体例不合，标待核
TIANXING = {"子": "乙", "丑": "乙", "寅": "庚", "卯": "辛", "辰": "辛", "巳": "壬",
            "午": "癸", "未": "癸", "申": "丙", "酉": "丁", "戌": "丁"}

# SP:s22 诀曰：正七下加子，二八在寅方，三九居辰上。四十午位伤，五十一「甲」位，六十二戌方
LEITING = {1: "子", 7: "子", 2: "寅", 8: "寅", 3: "辰", 9: "辰",
           4: "午", 10: "午", 6: "戌", 12: "戌"}   # 5／11 原文作「甲位」，待核

# SP:s27 法诀：戌人巳、巳人戌；辰人亥、亥人辰；寅人未、未人寅；
#              卯人申、申人卯；午人丑、丑人午；子人酉、酉人子
ZIYI_PAIRS = {("戌", "巳"), ("辰", "亥"), ("寅", "未"), ("卯", "申"), ("午", "丑"), ("子", "酉")}

# SP:s31 狭害杀：申日亥时，巳日寅时
XIAHAI = {("申", "亥"), ("巳", "寅")}

# SP:s32 甲：子平关（日干→所忌之干）
ZIPING = {"甲": "庚", "丁": "癸", "戊": "甲", "丙": "壬", "壬": "戊", "癸": "己"}

# SP:s33 鬼限（年纳音五行→忌时干支）
GUIXIAN = {"火": ("甲申", "乙酉", "癸亥"), "金": ("乙亥", "戊子", "己丑"),
           "水": ("戊寅", "己卯", "丁巳"), "土": ("庚寅", "辛卯", "丁巳"),
           "木": ("辛巳", "甲午", "壬申")}

# SP:s34 三组：生 寅申巳亥／旺 子午卯酉／库 辰戌丑未
GROUP3 = {}
for _n, _bs in (("生", "寅申巳亥"), ("旺", "子午卯酉"), ("库", "辰戌丑未")):
    for _b in _bs:
        GROUP3[_b] = _n

# SP:s36 急脚煞（日干→忌运支）
JIJIAO = {"甲": "申", "乙": "酉", "丙": "子", "丁": "亥", "庚": "午", "辛": "巳",
          "戊": "寅", "己": "卯", "壬": "辰戌", "癸": "丑未"}

# SP:s40 十恶大败十日
SHIE = {"甲辰", "乙巳", "丙申", "丁亥", "庚辰", "戊戌", "癸亥", "辛巳", "壬申", "己丑"}

# SP:s42 寡宿四组（日→时）／血光四组
GUASU = {("寅", "丑"), ("巳", "辰"), ("申", "未"), ("亥", "戌")}
XUEGUANG = {("子", "戌"), ("丑", "卯"), ("辰", "午"), ("未", "酉")}

# SP:s44 白虎杀（三合全→所忌之冲支）
BAIHU = {("申", "子", "辰"): "午", ("巳", "酉", "丑"): "卯",
         ("寅", "午", "戌"): "子", ("亥", "卯", "未"): "酉"}

# SP:s45 暗金的杀（年支组→时支）
ANJIN = {"子午卯酉": "巳", "寅申巳亥": "酉", "辰戌丑未": "丑"}

# SP:s49 曲脚杀明代异说四组
QUJIAO_MING = {"乙巳", "乙丑", "己巳", "己丑"}

# SP:s52 驿马（三合局→马位）
YIMA = {("寅", "午", "戌"): "申", ("亥", "卯", "未"): "巳",
        ("申", "子", "辰"): "寅", ("巳", "酉", "丑"): "亥"}


# ======================= 逐条判定 =======================
def r001(c):
    """天火杀／火灾起例：寅午戌全＋干见丙或丁＋该字五见＋四柱无水。"""
    if not {"寅", "午", "戌"} <= set(c.br):
        return MISS, "四柱支未见寅午戌全"
    if not any(s in "丙丁" for s in c.st):
        return MISS, "四柱天干无丙、丁"
    n = _cnt("".join(c.st) + "".join(c.br), "丙丁寅午戌")
    if n < 5:
        return MISS, f"丙丁寅午戌合计 {n} 字，未及五见"
    if c.has_elem("水"):
        return NA, f"合计 {n} 字，但四柱有水——原文「有水者，流年行至火旺之处」，须转看运岁"
    return HIT, f"寅午戌全＋干见{'丙' if '丙' in c.st else '丁'}＋合计 {n} 字＋四柱无水"


def r002(c):
    """五见之界定：寅午戌＋丙丁合计字数 ≥5。"""
    n = _cnt("".join(c.st) + "".join(c.br), "丙丁寅午戌")
    return (HIT if n >= 5 else MISS), f"寅午戌＋丙丁合计 {n} 字（门槛 5）"


def r003(c):
    """戟锋杀：月支当值之干，日干＝时干＝该干。地支尤忌申支。"""
    want = JIFENG_MONTH[c.br[1]]
    extra = "；四柱见申支（原文：地支尤忌申支）" if "申" in c.br else ""
    if c.st[2] == c.st[3] == want:
        return HIT, f"月支{c.br[1]}当值之干为{want}，日干＝时干＝{want}{extra}"
    return MISS, f"月支{c.br[1]}当值之干为{want}，日干{c.st[2]}、时干{c.st[3]}未俱为{want}"


def r004(c):
    """破杀：卯年午时、丑年辰时、子年酉时、未年戌时。"""
    want = POSHA.get(c.br[0])
    if not want:
        return MISS, f"年支{c.br[0]}不在破杀四组（仅卯／丑／子／未）"
    if c.br[3] == want:
        return HIT, f"年支{c.br[0]}见时支{want}"
    return MISS, f"年支{c.br[0]}须见时支{want}，实见{c.br[3]}"


def r005(c):
    """天刑杀：年支当值之干＝时干。时干甲／己者不论（R-SP-006）。"""
    if c.br[0] == "亥":
        return TEXT, "原文「亥人戌时」——戌为地支，与「时干」体例不合，疑「戊」之讹，待核，本器不落算"
    want = TIANXING[c.br[0]]
    if c.st[3] in "甲己":
        return MISS, f"时干{c.st[3]}为甲／己，依 R-SP-006 原文明言不论"
    if c.st[3] == want:
        return HIT, f"年支{c.br[0]}当值之干为{want}，时干亦{want}"
    return MISS, f"年支{c.br[0]}当值之干为{want}，时干为{c.st[3]}"


def r006(c):
    """天刑杀之排除：时干为甲、己者不论。"""
    if c.st[3] in "甲己":
        return HIT, f"时干{c.st[3]}，天刑杀依原文排除，不再论"
    return MISS, f"时干{c.st[3]}，不在甲／己之排除列"


def r007(c):
    """雷霆杀：出生月对时辰。正月／七月子，二月／八月寅，三月／九月辰，
    四月／十月午，五月／十一月（原文作「甲位」，待核），六月／十二月戌。"""
    mi = (_i(c.br[1]) - _i("寅")) % 12 + 1
    if mi in LEITING:
        want = LEITING[mi]
        if c.br[3] == want:
            return HIT, f"{mi}月生，当值之时支为{want}，时支亦{want}"
        return MISS, f"{mi}月生，当值之时支为{want}，时支为{c.br[3]}"
    return TEXT, f"{mi}月生，原文作「{'五十一' if mi == 5 else '十一'}甲位」——甲为天干，与「时支」体例不合，待核"


def r008(c):
    """死病符：岁后一辰，带冲者是。"""
    prev = _step(c.br[0], -1)
    want = _chong(prev)
    where = [("年月日时"[i], c.p[i]) for i in range(4) if c.br[i] == want]
    if where:
        pos = "、".join(POS_NAME[i] for i, _ in where)
        return HIT, f"年支{c.br[0]}后一辰为{prev}，其冲{want}见于{pos}"
    return MISS, f"年支{c.br[0]}后一辰为{prev}，其冲{want}未见"


POS_NAME = {"年": "年支", "月": "月支", "日": "日支", "时": "时支"}


def r009(c):
    """官符杀：太岁前五辰，落在日时。"""
    want = _step(c.br[0], 5)
    hit = [n for n, b in (("日支", c.br[2]), ("时支", c.br[3])) if b == want]
    if hit:
        want_stem = STEMS[(STEMS.index(c.st[0]) + 5) % 10]
        extra = (f"；日干{c.st[2]}亦为年干前五，干支俱过者更重"
                 if c.st[2] == want_stem else "；干支未俱过（原文：干支顺行五辰在日柱，多为妄言招非）")
        return HIT, f"年支{c.br[0]}前五辰为{want}，落在{'、'.join(hit)}{extra}"
    return MISS, f"年支{c.br[0]}前五辰为{want}，日支{c.br[2]}／时支{c.br[3]}俱非"


def r010(c):
    """挂剑杀：四柱巳酉丑申全；或四柱有申并带巳酉丑之一，而运岁会齐巳酉丑。"""
    if {"巳", "酉", "丑", "申"} <= set(c.br):
        return HIT, "四柱申巳酉丑四字皆全"
    if "申" not in c.br or not ({"巳", "酉", "丑"} & set(c.br)):
        return MISS, "四柱不同时具备「申」与「巳酉丑」之一"
    have = {"巳", "酉", "丑"} & set(c.br)
    yun_br = set(c.all_br(with_yun=True))
    if {"巳", "酉", "丑"} <= yun_br:
        return HIT, f"四柱有申＋{_order(have)}，运岁会齐巳酉丑"
    lack = {"巳", "酉", "丑"} - yun_br
    return NA, f"四柱有申＋{_order(have)}，运岁未会齐巳酉丑（缺{_order(lack)}）"


def r011(c):
    """天屠杀：日支与时支相冲（子午／丑亥／寅戌／卯酉／辰申／巳未）。"""
    if _chong(c.br[2]) == c.br[3]:
        return HIT, f"日支{c.br[2]}与时支{c.br[3]}相冲"
    return MISS, f"日支{c.br[2]}与时支{c.br[3]}不相冲"


def r012(c):
    """自缢杀：年支与时支成六组之一。"""
    if (c.br[0], c.br[3]) in ZIYI_PAIRS or (c.br[3], c.br[0]) in ZIYI_PAIRS:
        return HIT, f"年支{c.br[0]}与时支{c.br[3]}成组"
    return MISS, f"年支{c.br[0]}与时支{c.br[3]}不成组"


def r013(c):
    """破碎杀：丑年见辰戌丑未日时；酉年见寅申巳亥日时。"""
    y = c.br[0]
    if y == "丑":
        want, name = set("辰戌丑未"), "辰戌丑未"
    elif y == "酉":
        want, name = set("寅申巳亥"), "寅申巳亥"
    else:
        return MISS, f"年支{y}，破碎杀只取丑、酉二年支"
    hit = [n for n, b in (("日支", c.br[2]), ("时支", c.br[3])) if b in want]
    if hit:
        return HIT, f"{y}年见{'、'.join(hit)}在{name}"
    return MISS, f"{y}年须见{name}于日时，实见{c.br[2]}／{c.br[3]}"


def r014(c):
    """咸池：原文只出诗（旺宫／衰宫＋空亡＋七杀），无硬性起例。"""
    return MANUAL, "原文以「旺宫／衰宫＋坐空亡＋带七杀」合参，无字数式起例，本器不落算"


def r015(c):
    """平头杀：甲丙丁壬三四个，又见两个以上空亡。"""
    n = _cnt("".join(c.st) + "".join(c.br), "甲丙丁壬")
    if n < 3:
        return MISS, f"平头字（甲丙丁壬）计 {n} 个，未及三个"
    kw = kong(c.d_gz)
    k = sum(1 for i in (0, 1, 3) if c.br[i] in kw)
    if c.br[2] in kong(c.y_gz):
        k += 1
    if k >= 2:
        return HIT, f"平头字 {n} 个＋空亡 {k} 处（日柱旬空{_order(kw)}）"
    return MISS, f"平头字 {n} 个，空亡仅 {k} 处"


def r016(c):
    """曲脚杀（古法）：己巳日，地支带巳酉丑全。"""
    if c.d_gz != "己巳":
        return MISS, f"日柱为{c.d_gz}，非己巳"
    if {"巳", "酉", "丑"} <= set(c.br):
        return HIT, "己巳日＋支见巳酉丑全"
    lack = {"巳", "酉", "丑"} - set(c.br)
    return MISS, f"己巳日，但支缺{''.join(sorted(lack))}"


def r017(c):
    """曲脚杀（明代异说）：乙巳／乙丑／己巳／己丑有两组以上。"""
    hit = [p for p in c.p if p in QUJIAO_MING]
    if len(hit) >= 2:
        return HIT, f"四柱见{'、'.join(hit)}，共 {len(hit)} 组"
    return MISS, f"四柱见{'、'.join(hit) if hit else '无'}，不足二组"


def r018(c):
    """悬针杀：甲辛卯午申三四个。"""
    n = _cnt("".join(c.st) + "".join(c.br), "甲辛卯午申")
    return (HIT if n >= 3 else MISS), f"悬针字（甲辛卯午申）计 {n} 个（门槛 3）"


def r019(c):
    """破字：甲癸未申酉，会聚多者。原文未给字数门槛。"""
    n = _cnt("".join(c.st) + "".join(c.br), "甲癸未申酉")
    return MANUAL, f"破字（甲癸未申酉）计 {n} 个；原文作「会聚多」，未给门槛，本器只报计数不判"


def r020(c):
    """明代统计七则：逐条核字面组合，原文未列可算起例。"""
    return MANUAL, "原文为七则统计性观察，未列可执行起例，本器不落算"


def r021(c):
    """狭害杀：申日亥时、巳日寅时。"""
    if (c.br[2], c.br[3]) in XIAHAI:
        return HIT, f"日支{c.br[2]}见时支{c.br[3]}"
    return MISS, f"日支{c.br[2]}／时支{c.br[3]}不在（申亥、巳寅）二组"


def r022(c):
    """子平关：甲日见庚（九岁）、丁日见癸（六岁）、戊日见甲（三岁）、
    丙日见壬（一岁）、壬日见戊（五岁）、癸日见己（半岁）。"""
    want = ZIPING.get(c.st[2])
    if not want:
        return MISS, f"日干{c.st[2]}不在子平关六干"
    where = [POS_FULL[i] for i in range(4) if i != 2 and c.st[i] == want]
    if where:
        return HIT, f"{c.st[2]}日见{want}，见于{'、'.join(where)}"
    return MISS, f"{c.st[2]}日须见{want}，四柱天干无之"


POS_FULL = ["年干", "月干", "日干", "时干"]


def r023(c):
    """三关煞：年柱纳音对时支——金木忌巳酉，火忌辰申，水土忌午戌。"""
    e = nayin_elem(c.y_gz)
    want = {"金": set("巳酉"), "木": set("巳酉"), "火": set("辰申"),
            "水": set("午戌"), "土": set("午戌")}[e]
    if c.br[3] in want:
        return HIT, f"年柱纳音{e}（{nayin(c.y_gz)}），时支{c.br[3]}正犯"
    return MISS, f"年柱纳音{e}，忌{''.join(sorted(want))}时，实为{c.br[3]}"


def r024(c):
    """鬼限：年柱纳音五行，对时干支（四柱带／运岁见）。"""
    e = nayin_elem(c.y_gz)
    want = GUIXIAN[e]
    if c.h_gz in want:
        return HIT, f"年纳音{e}（{nayin(c.y_gz)}），时柱{c.h_gz}正犯"
    yun = [gz for gz in c.dayun + c.liunian if gz in want]
    if yun:
        return HIT, f"年纳音{e}，运岁见{'、'.join(yun)}"
    return MISS, f"年纳音{e}，忌{'／'.join(want)}，时柱{c.h_gz}非"


def r025(c):
    """冲夭煞：年月支冲 且 日时支冲。"""
    a = _chong(c.br[0]) == c.br[1]
    b = _chong(c.br[2]) == c.br[3]
    if a and b:
        return HIT, f"年月{c.br[0]}{c.br[1]}冲＋日时{c.br[2]}{c.br[3]}冲"
    return MISS, f"年月冲{'' if a else '不'}成立、日时冲{'' if b else '不'}成立"


def r026(c):
    """冲夭煞须不同组：年月冲所在组 ≠ 日时冲所在组。"""
    if not (_chong(c.br[0]) == c.br[1] and _chong(c.br[2]) == c.br[3]):
        return MISS, "双冲未成立，无论同组异组"
    g1, g2 = GROUP3[c.br[0]], GROUP3[c.br[2]]
    if g1 != g2:
        return HIT, f"年月冲在{g1}组、日时冲在{g2}组，异组"
    return MISS, f"两组同属{g1}组，依原文只作一般刑冲"


def r027(c):
    """冲夭煞第三条件：时柱纳音克年柱纳音。"""
    ey, eh = nayin_elem(c.y_gz), nayin_elem(c.h_gz)
    if KE[eh] == ey:
        return HIT, f"时{nayin(c.h_gz)}（{eh}）克年{nayin(c.y_gz)}（{ey}）"
    return MISS, f"时纳音{eh}、年纳音{ey}，不相克"


def r028(c):
    """夭年煞：诗诀用生肖，原书对照表为图版，未转录。"""
    return MANUAL, "诗诀「猪鼠无良犬战牛…」须先由生肖转支，原书对照表为图版，未转录，本器不落算"


def r029(c):
    """急脚煞：日干入某运支（论运，不论四柱）。"""
    want = JIJIAO[c.st[2]]
    if not c.dayun:
        return NA, f"日干{c.st[2]}忌{want}运；未提供大运，无法判"
    hit = [gz for gz in c.dayun if gz[1] in want]
    if hit:
        return HIT, f"日干{c.st[2]}，运见{'、'.join(hit)}"
    return MISS, f"日干{c.st[2]}忌{want}运，所给运程未见"


def r030(c):
    """截命煞：年月时支＝日支前一位，计见数（三见大凶、二见血光）。"""
    want = _step(c.br[2], 1)
    n = sum(1 for b in (c.br[0], c.br[1], c.br[3]) if b == want)
    if n >= 2:
        return HIT, f"日支{c.br[2]}前一位为{want}，年月时见 {n} 重（{'三见' if n == 3 else '二见'}）"
    return MISS, f"日支{c.br[2]}前一位为{want}，年月时仅见 {n} 重（门槛 2）"


def r031(c):
    """推命煞：年月时支＝日支后一位，计见数。"""
    want = _step(c.br[2], -1)
    n = sum(1 for b in (c.br[0], c.br[1], c.br[3]) if b == want)
    if n >= 2:
        return HIT, f"日支{c.br[2]}后一位为{want}，年月时见 {n} 重（{'三见' if n == 3 else '二见'}）"
    return MISS, f"日支{c.br[2]}后一位为{want}，年月时仅见 {n} 重（门槛 2）"


def r032(c):
    """头重尾轻：年月支相同，四支一连气（子子丑寅式）。"""
    if c.br[0] != c.br[1]:
        return MISS, f"年月支为{c.br[0]}／{c.br[1]}，不相同"
    if c.br[2] == _step(c.br[0], 1) and c.br[3] == _step(c.br[0], 2):
        return HIT, f"{c.br[0]}{c.br[1]}{c.br[2]}{c.br[3]}，年月重复而成一连气"
    return MISS, f"年月同为{c.br[0]}，但日时{c.br[2]}{c.br[3]}不成连气"


def r033(c):
    """十恶大败：日柱在十日之内。"""
    if c.d_gz in SHIE:
        return HIT, f"日柱{c.d_gz}为十恶大败"
    return MISS, f"日柱{c.d_gz}不在十日（{'、'.join(sorted(SHIE))}）"


def r034(c):
    """十恶大败（元白经）：日柱在十日 且 日支冲年支。"""
    if c.d_gz not in SHIE:
        return MISS, f"日柱{c.d_gz}非十恶大败"
    if _chong(c.br[2]) == c.br[0]:
        return HIT, f"日柱{c.d_gz}为十恶大败，且日支{c.br[2]}冲年支{c.br[0]}（元白经）"
    return NOTE, f"日柱{c.d_gz}虽在十日，日支未冲年支——依元白经不作凶论；元黄经另有年干月日之说"


def r035(c):
    """天罗地网（定义）：支见戌亥为天罗，见辰巳为地网。"""
    luo = {"戌", "亥"} <= set(c.br)
    wang = {"辰", "巳"} <= set(c.br)
    got = [n for n, ok in (("天罗戌亥", luo), ("地网辰巳", wang)) if ok]
    return (HIT if got else MISS), ("四柱见" + "、".join(got)) if got else "四柱未见戌亥，亦未见辰巳"


def r036(c):
    """天罗地网之男女分看：男看日时戌亥，女看日时辰巳。"""
    if not c.gender:
        return NA, "未提供性别，男女分看无从判"
    want = "戌亥" if c.gender == "男" else "辰巳"
    dh = {c.br[2], c.br[3]}
    if set(want) <= dh:
        return HIT, f"{c.gender}命，日时{''.join(sorted(dh))}并见{want}"
    return MISS, f"{c.gender}命须日时并见{want}，实见{''.join(sorted(dh))}"


def r037(c):
    """天罗地网会齐：四柱／大运／流年齐见戌亥与辰巳。"""
    br = set(c.all_br(with_yun=True))
    if {"戌", "亥"} <= br and {"辰", "巳"} <= br:
        src = "四柱" if {"戌", "亥", "辰", "巳"} <= set(c.br) else "四柱＋" + (c.yun_text() or "运岁")
        return HIT, f"{src}会齐戌亥、辰巳"
    return MISS, f"所给范围未会齐戌亥与辰巳（现有{_order(br & set('戌亥辰巳')) or '无'}）"


def r038(c):
    """惆怅杀（寡宿组）：寅日丑时、巳日辰时、申日未时、亥日戌时。"""
    if (c.br[2], c.br[3]) in GUASU:
        return HIT, f"日支{c.br[2]}见时支{c.br[3]}"
    return MISS, f"日支{c.br[2]}／时支{c.br[3]}不在寡宿四组"


def r039(c):
    """孤辰寡宿·血光四组：子日戌时、丑日卯时、辰日午时、未日酉时（日时互换亦同）。"""
    a = (c.br[2], c.br[3]) in XUEGUANG
    b = (c.br[3], c.br[2]) in XUEGUANG
    if a or b:
        return HIT, f"日支{c.br[2]}／时支{c.br[3]}成血光组{'（互换）' if b and not a else ''}"
    return MISS, f"日支{c.br[2]}／时支{c.br[3]}不在血光四组"


def r040(c):
    """勾绞：阳男阴女命前三辰为勾、后三辰为绞；阴男阳女反之。"""
    if not c.gender:
        return NA, "未提供性别，勾绞取法无从定"
    yang = c.st[0] in YANG_STEM
    shun = (yang and c.gender == "男") or (not yang and c.gender == "女")
    gou, jiao = _step(c.br[0], 3), _step(c.br[0], -3)
    if not shun:
        gou, jiao = jiao, gou
    seen = []
    if gou in c.br:
        seen.append(f"勾{gou}")
    if jiao in c.br:
        seen.append(f"绞{jiao}")
    who = "阳男阴女" if shun else "阴男阳女"
    return (HIT if seen else MISS), f"{who}：勾{gou}／绞{jiao}；四柱见{'、'.join(seen) if seen else '俱无'}"


def r041(c):
    """白虎杀：三合三字全，方论；再带对应之冲支。"""
    for grp, chong_b in BAIHU.items():
        if not set(grp) <= set(c.br):
            continue
        if chong_b in set(c.all_br(with_yun=True)):
            src = "四柱" if chong_b in c.br else (c.yun_text() or "运岁")
            return HIT, f"{''.join(grp)}三合全，{src}见冲支{chong_b}"
        return NA, f"{''.join(grp)}三合全，但未见冲支{chong_b}（原文须「见对应之冲支」方论）"
    return MISS, "四柱无三合三字全者"


def r042(c):
    """暗金的杀（禄命法）：子午卯酉年取巳时，寅申巳亥年取酉时，辰戌丑未年取丑时。"""
    y = c.br[0]
    want = next(v for k, v in ANJIN.items() if y in k)
    if c.br[3] == want:
        return HIT, f"年支{y}，当取{want}时，时支亦{want}（无贵人压、遇冲刑则准）"
    return MISS, f"年支{y}，当取{want}时，实为{c.br[3]}"


_GAN_CHONG = {"甲": "庚", "庚": "甲", "乙": "辛", "辛": "乙",
              "丙": "壬", "壬": "丙", "丁": "癸", "癸": "丁"}


def r043(c):
    """元辰（大耗）：年柱→干支双冲→阳男阴女取后一位、阴男阳女取前一位。"""
    sc_stem = _GAN_CHONG.get(c.st[0])
    if not sc_stem:
        return TEXT, f"年干{c.st[0]}无冲（戊己土不冲），双冲不成立，元辰无从取"
    sc = sc_stem + _chong(c.br[0])
    idx = JIAZI.index(sc)
    if not c.gender:
        return NA, f"年柱{c.y_gz}双冲为{sc}；未提供性别，前后一位无从定"
    yang = c.st[0] in YANG_STEM
    hou = (yang and c.gender == "男") or (not yang and c.gender == "女")
    target = JIAZI[(idx + 1) % 60] if hou else JIAZI[(idx - 1) % 60]
    who = "阳男阴女取后一位" if hou else "阴男阳女取前一位"
    where = [POS_FULL[i] for i in range(1, 4) if c.p[i] == target]
    yun = [gz for gz in c.dayun + c.liunian if gz == target]
    if where:
        return HIT, f"年柱{c.y_gz}双冲{sc}，{who}→{target}，见于{'、'.join(where)}"
    if yun:
        return HIT, f"年柱{c.y_gz}双冲{sc}，{who}→{target}，运岁见之"
    return MISS, f"年柱{c.y_gz}双冲{sc}，{who}→{target}，四柱运岁未见"


def r044(c):
    """空亡：坐入旬空者，吉减半吉、凶减半凶。"""
    kw = kong(c.d_gz)
    hit = [POS_NAME[POS_KEY[i]] for i in (0, 1, 3) if c.br[i] in kw]
    swap = c.br[2] in kong(c.y_gz)
    if hit or swap:
        parts = []
        if hit:
            parts.append(f"日柱{c.d_gz}旬空{_order(kw)}，{'、'.join(hit)}坐入")
        if swap:
            parts.append(f"年柱{c.y_gz}旬空{_order(kong(c.y_gz))}而日支{c.br[2]}在其中（年日互换空亡，原文所忌）")
        return HIT, "；".join(parts)
    return MISS, f"日柱{c.d_gz}旬空{_order(kw)}，年月时支俱不坐入"


POS_KEY = ["年", "月", "日", "时"]


def r045(c):
    """四大空亡：甲子甲午旬生而四柱无水；甲寅甲申旬生而四柱无金。"""
    head = xun_head(c.d_gz)
    if head in ("甲子", "甲午"):
        if not c.has_elem("水"):
            return HIT, f"日柱{c.d_gz}属{head}旬，四柱（含藏干）无水"
        return MISS, f"日柱{c.d_gz}属{head}旬，四柱有水"
    if head in ("甲寅", "甲申"):
        if not c.has_elem("金"):
            return HIT, f"日柱{c.d_gz}属{head}旬，四柱（含藏干）无金"
        return MISS, f"日柱{c.d_gz}属{head}旬，四柱有金"
    return MISS, f"日柱{c.d_gz}属{head}旬，不在四旬之内"


def r046(c):
    """羊刃必带官印：命带羊刃者，须查有无官、印；否则一生是非甚多。"""
    ren = [e for e in c.ss if e["name"] == "羊刃" and e.get("hits")]
    if not ren:
        de = STEM_ELEM[c.st[2]]
        if c.st[2] not in YANG_STEM:
            return NA, f"日干{c.st[2]}为阴干，原表（JS-SS-03）阴干不列羊刃（R-XJ-02），不以通行说法补"
        return MISS, f"日干{c.st[2]}之刃支未见"
    guan = KE[STEM_ELEM[c.st[2]]]      # 克我者为官杀
    yin = next(k for k, v in GEN.items() if v == STEM_ELEM[c.st[2]])   # 生我者为印
    g_ok = c.has_elem(guan)
    y_ok = c.has_elem(yin)
    if g_ok and y_ok:
        return HIT, f"命带羊刃（{'、'.join(sorted({h[0] for e in ren for h in e['hits']}))}），官（{guan}）印（{yin}）俱见"
    lack = "、".join([x for x, ok in ((f"官{guan}", g_ok), (f"印{yin}", y_ok)) if not ok])
    return HIT, f"命带羊刃，然{lack}不见——「羊刃必带官印方可，否则一生是非甚多」"


def r047(c):
    """羊刃叠位与残疾：①甲日见乙卯或丁卯二重；②日支叠位又见该日之刃。"""
    outs = []
    if c.st[2] == "甲":
        n = sum(1 for p in c.p if p in ("乙卯", "丁卯"))
        if n >= 2:
            outs.append(f"甲日见乙卯／丁卯 {n} 重")
    ren = [e for e in c.ss if e["name"] == "羊刃" and e.get("hits")]
    if ren:
        ren_br = {h[1][1] for e in ren for h in e["hits"]}
        dup = c.br.count(c.br[2])
        if dup >= 2 and ren_br:
            outs.append(f"日支{c.br[2]}叠见 {dup} 位，又见刃{_order(ren_br)}（羊刃相蚀）")
    return (HIT if outs else MISS), ("；".join(outs) if outs else "甲日无乙卯／丁卯二重，日支亦未叠见逢刃")


def r048(c):
    """亡神与劫煞之辨：劫煞之凶来自外，亡神之凶来自内。"""
    got = {}
    for e in c.ss:
        if e["name"] in ("劫煞", "亡神") and e.get("hits"):
            got.setdefault(e["name"], []).extend(f"{h[0]}{h[1]}" for h in e["hits"])
    if not got:
        return MISS, "四表未见劫煞、亡神"
    parts = []
    if "劫煞" in got:
        parts.append(f"劫煞（{'、'.join(got['劫煞'])}）——凶来自外")
    if "亡神" in got:
        parts.append(f"亡神（{'、'.join(got['亡神'])}）——凶来自内")
    return HIT, "；".join(parts)


def r049(c):
    """驿马：寅午戌马在申、亥卯未马在巳、申子辰马在寅、巳酉丑马在亥；年取或日取。"""
    outs = []
    for label, b in (("年支", c.br[0]), ("日支", c.br[2])):
        want = YIMA[SANHE_OF[b]]
        others = [x for i, x in enumerate(c.br) if x == want]
        if others:
            outs.append(f"{label}{b}之马在{want}，四柱见之")
    if outs:
        return HIT, "；".join(outs)
    return MISS, f"年支{c.br[0]}、日支{c.br[2]}所取之马位俱不见"


SPECS = [
    ("R-SP-001", "天火杀／火灾起例", "SP:s18", r001),
    ("R-SP-002", "天火杀／五见之界定", "SP:s18", r002),
    ("R-SP-003", "戟锋杀／后天伤残", "SP:s19", r003),
    ("R-SP-004", "破杀／少年多灾", "SP:s20", r004),
    ("R-SP-005", "天刑杀／体弱多病", "SP:s21", r005),
    ("R-SP-006", "天刑杀／甲己时不论", "SP:s21", r006),
    ("R-SP-007", "雷霆杀／猝然临难", "SP:s22", r007),
    ("R-SP-008", "死病符／痼疾", "SP:s23", r008),
    ("R-SP-009", "官符杀／官讼", "SP:s24", r009),
    ("R-SP-010", "挂剑杀／刀刃血光", "SP:s25", r010),
    ("R-SP-011", "天屠杀／疑难杂症", "SP:s26", r011),
    ("R-SP-012", "自缢杀／自杀倾向", "SP:s27", r012),
    ("R-SP-013", "破碎杀／三十岁前有难", "SP:s28", r013),
    ("R-SP-014", "咸池／艺术性格", "SP:s29", r014),
    ("R-SP-015", "平头杀／字形", "SP:s30", r015),
    ("R-SP-016", "曲脚杀／唇齿肢体（古法）", "SP:s30", r016),
    ("R-SP-017", "曲脚杀／明代异说", "SP:s30", r017),
    ("R-SP-018", "悬针杀／眼疾", "SP:s30", r018),
    ("R-SP-019", "破字／身体", "SP:s30", r019),
    ("R-SP-020", "明代统计七则", "SP:s30", r020),
    ("R-SP-021", "狭害杀／无子", "SP:s31", r021),
    ("R-SP-022", "子平关／小儿关", "SP:s32", r022),
    ("R-SP-023", "三关煞／纳音对时支", "SP:s32", r023),
    ("R-SP-024", "鬼限／寿限", "SP:s33", r024),
    ("R-SP-025", "冲夭煞／双冲成立", "SP:s34", r025),
    ("R-SP-026", "冲夭煞／须不同组", "SP:s34", r026),
    ("R-SP-027", "冲夭煞／时纳音克年纳音", "SP:s34", r027),
    ("R-SP-028", "夭年煞／年时相对", "SP:s35", r028),
    ("R-SP-029", "急脚煞／运程", "SP:s36", r029),
    ("R-SP-030", "截命煞／日支后一位重见", "SP:s37", r030),
    ("R-SP-031", "推命煞／日支前一位重见", "SP:s38", r031),
    ("R-SP-032", "头重尾轻／年月重复", "SP:s39", r032),
    ("R-SP-033", "十恶大败／十日", "SP:s40", r033),
    ("R-SP-034", "十恶大败／须冲年", "SP:s40", r034),
    ("R-SP-035", "天罗地网／定义", "SP:s41", r035),
    ("R-SP-036", "天罗地网／男女分看", "SP:s41", r036),
    ("R-SP-037", "天罗地网／会齐即论", "SP:s41", r037),
    ("R-SP-038", "孤辰寡宿／惆怅杀", "SP:s42", r038),
    ("R-SP-039", "孤辰寡宿／血光四组", "SP:s42", r039),
    ("R-SP-040", "勾绞／起例", "SP:s43", r040),
    ("R-SP-041", "白虎杀／三合全", "SP:s44", r041),
    ("R-SP-042", "暗金的杀／禄命取时", "SP:s45", r042),
    ("R-SP-043", "元辰／须取干支", "SP:s46", r043),
    ("R-SP-044", "空亡／减半之义", "SP:s47", r044),
    ("R-SP-045", "四大空亡／五行缺一", "SP:s48", r045),
    ("R-SP-046", "羊刃／必带官印", "SP:s49", r046),
    ("R-SP-047", "羊刃／叠位与残疾", "SP:s49", r047),
    ("R-SP-048", "亡神与劫煞／内外之别", "SP:s51", r048),
    ("R-SP-049", "驿马／起例", "SP:s52", r049),
]


def evaluate(pillars, gender=None, dayun=None, liunian=None, shensha_hits=None):
    c = Chart(pillars, gender=gender, dayun=dayun, liunian=liunian, shensha_hits=shensha_hits)
    out = []
    for rid, name, anchor, fn in SPECS:
        try:
            status, detail = fn(c)
        except Exception as e:                      # 单条出错不拖垮整盘
            status, detail = NA, f"判定器异常：{e}"
        out.append({"rule_id": rid, "name": name, "anchor": anchor,
                    "status": status, "detail": detail})
    return out


def summarize(results):
    from collections import Counter
    return Counter(r["status"] for r in results)


# ======================= 自检 =======================
SELF_CASES = [
    # (四柱, 性别, 大运, 流年, {rule_id: 期望状态})
    # ① 破杀卯年午时、天屠子日午时
    (("丁卯", "壬寅", "甲子", "丙午"), "男", None, None,
     {"R-SP-004": HIT, "R-SP-011": HIT}),
    # ② 破碎杀只取丑酉：年申者不成立；戊戌日为十恶大败
    (("丙申", "庚寅", "戊戌", "己未"), "男", None, None,
     {"R-SP-013": MISS, "R-SP-033": HIT, "R-SP-034": NOTE}),
    # ③ 甲辰日十恶大败，年支丑不冲日支辰 → 元白经不成立（NOTE）
    (("己丑", "丙寅", "甲辰", "戊辰"), "男", None, None,
     {"R-SP-033": HIT, "R-SP-034": NOTE}),
    # ④ 申子辰三合全而无冲支午 → 白虎杀缺料；壬申年纳音金，戊子时正犯鬼限；
    #    时纳音霹雳火克年纳音剑锋金
    (("壬申", "壬子", "丙辰", "戊子"), "男", None, None,
     {"R-SP-041": NA, "R-SP-024": HIT, "R-SP-027": HIT}),
    # ⑤ 曲脚杀明代异说：乙巳／己丑／己巳三组
    (("乙巳", "己丑", "己巳", "乙亥"), "女", None, None,
     {"R-SP-017": HIT}),
    # ⑥ 戟锋杀：寅月当值之干为甲，日干＝时干＝甲
    (("甲子", "丙寅", "甲午", "甲子"), "男", None, None,
     {"R-SP-003": HIT}),
    # ⑦ 官符：甲子年前五辰为巳，落己巳日；暗金：子年取巳时；
    #    三关：甲子年纳音海中金，忌巳酉时
    (("甲子", "丙寅", "己巳", "丁巳"), "男", None, None,
     {"R-SP-009": HIT, "R-SP-042": HIT, "R-SP-023": HIT}),
    # ⑧ 元辰：甲子年双冲庚午，阳男取后一位辛未
    (("甲子", "丙寅", "戊辰", "辛未"), "男", None, None,
     {"R-SP-043": HIT}),
    # ⑨ 讹字：年支亥，原文「亥人戌时」体例不合 → 待核，不落算
    (("乙亥", "戊寅", "甲子", "丙寅"), "男", None, None,
     {"R-SP-005": TEXT}),
    # ⑩ 讹字：五月／十一月原文作「甲位」，与「时支」体例不合 → 待核
    (("甲子", "庚午", "丙寅", "戊子"), "男", None, None,
     {"R-SP-007": TEXT}),
    # ⑪ 急脚煞不提供大运 → 缺料，不猜
    (("甲子", "丙寅", "甲午", "甲子"), "男", None, None,
     {"R-SP-029": NA}),
    # ⑫ 黄金命例 C01：庚戌日属甲辰旬，旬空寅卯；年柱甲子旬空戌亥而日支戌在其中，
    #    为年日互换空亡
    (("甲子", "乙亥", "庚戌", "癸未"), "男", None, None,
     {"R-SP-044": HIT, "R-SP-015": MISS, "R-SP-041": MISS}),
]


def self_test():
    ok = total = 0
    for pillars, gender, dayun, liunian, want in SELF_CASES:
        res = {r["rule_id"]: r["status"] for r in
               evaluate(pillars, gender=gender, dayun=dayun, liunian=liunian)}
        bad = [(k, v, res.get(k)) for k, v in want.items() if res.get(k) != v]
        total += 1
        if bad:
            tag = f"{' '.join(pillars)} {gender or ''}".strip()
            print(f"  FAIL {tag}：" + "；".join(f"{k} 期望 {v} 实得 {g}" for k, v, g in bad))
        else:
            ok += 1
            print(f"  ok   {' '.join(pillars)} → {len(want)} 条断言全过")
    res = evaluate(("甲子", "乙亥", "庚戌", "癸未"), gender="男")
    assert len(res) == 49, f"应有 49 条，实得 {len(res)}"
    assert len({r["rule_id"] for r in res}) == 49
    assert all(r["detail"] for r in res), "有规则未给说明"
    print(f"\n49 条状态齐备；本例分布：{dict(summarize(res))}")
    print(f"自检结果：{'PASS' if ok == total else 'FAIL'}（{ok}/{total} 例）")
    return 0 if ok == total else 1


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="神煞探源起例判定器（R-SP-001～049）")
    ap.add_argument("pillars", nargs="*", help="四个干支，按年 月 日 时")
    ap.add_argument("--gender", choices=["男", "女"])
    ap.add_argument("--dayun", help="大运干支，逗号分隔")
    ap.add_argument("--liunian", help="流年干支，逗号分隔")
    ap.add_argument("--all", action="store_true", help="连「不成立」一并列出")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return self_test()
    if len(a.pillars) != 4:
        ap.error("须给四个干支：年 月 日 时")

    dy = [x.strip() for x in a.dayun.split(",")] if a.dayun else None
    ln = [x.strip() for x in a.liunian.split(",")] if a.liunian else None
    res = evaluate(a.pillars, gender=a.gender, dayun=dy, liunian=ln)
    cnt = summarize(res)
    print(f"# 神煞探源起例（{' '.join(a.pillars)}；{a.gender or '性别未给'}）\n")
    print(f"总计 49 条：{'、'.join(f'{k} {v}' for k, v in cnt.most_common())}\n")
    for r in res:
        if not a.all and r["status"] in (MISS,):
            continue
        print(f"- [{r['status']}] {r['rule_id']} {r['name']}（{r['anchor']}）：{r['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
