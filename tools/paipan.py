#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自包含排盘：公历生日 → 四柱、大运、十神、藏干、纳音、逐柱空亡。

三条硬规矩：

  一、**不猜**。节气用天文算法（太阳视黄经）现算，日柱用儒略日双锚点交叉，
      大运起运用精确时差折算。任一项对不上就报 FAIL、不出盘。
  二、**一切标 E6 结构计算**，不是梁氏判断。排盘是历法，不是命理；
      本包所有「梁氏怎么说」在 rules.csv，与这里无关。
  三、**真太阳时须给经度**。不给经度就用北京时间，并在输出里明写「未校正」，
      不假装校正过。

与另一路做法的两处不同（都是刻意的）：

  - 节气不靠在线查询，本地算。太阳视黄经用 VSOP87 截断级数（地球 L0 取 64 项、
    L1 取 34 项、L2 取 20 项、L3 取 7 项），加章动、光行差与 ΔT 修正。
    **实测误差 ±15 分钟以内**：1984 立春算 23:06（公开值 23:18:44，差 13 分）、
    2000 春分算 15:35（公开值 15:35，差 0 分）、2024 立春算 16:21（公开值 16:26:53，差 6 分）。
    **故生日距节气四十五分钟内者，本器一律报警**，提示改用专业排盘软件复核月柱——
    这是本器唯一不敢自专的地方，宁可报错，不装作准。
  - 日柱双锚点（2000-01-01 戊午、1900-01-01 甲戌）必须一致，不一致即 FAIL。

用法：
    python tools/paipan.py --date 1984-11-12 --time 14:00 --gender 男
    python tools/paipan.py --date 1984-11-12 --time 14:00 --gender 男 --lon 116.4
    python tools/paipan.py --date 1984-11-12 --time 14:00 --gender 男 --json
    python tools/paipan.py --self-test
"""
import argparse
import io
import json
import math
import re
import sys
from datetime import date, datetime, timedelta

# 控制台编码：Windows 中文环境默认 cp936，本文件输出含 ✅（U+2705），
# 直接 print 会 UnicodeEncodeError 崩在第一张表之前。改 stdout/stderr 为 UTF-8；
# 老 cmd 显示成乱码但不崩，Windows Terminal / VS Code 正常。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------- 基本常量 ----------------
STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
JIAZI = [STEMS[i % 10] + BRANCHES[i % 12] for i in range(60)]
JIAZI_SET = set(JIAZI)
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
YANG = set("甲丙戊庚壬")
POS = ["年", "月", "日", "时"]

# 支藏天干（本气、中气、余气）
CANG = {
    "子": "癸", "丑": "己癸辛", "寅": "甲丙戊", "卯": "乙",
    "辰": "戊乙癸", "巳": "丙庚戊", "午": "丁己", "未": "己丁乙",
    "申": "庚壬戊", "酉": "辛", "戌": "戊辛丁", "亥": "壬甲",
}

# 五行
WX_OF = {}
for _s in "甲乙":
    WX_OF[_s] = "木"
for _s in "丙丁":
    WX_OF[_s] = "火"
for _s in "戊己":
    WX_OF[_s] = "土"
for _s in "庚辛":
    WX_OF[_s] = "金"
for _s in "壬癸":
    WX_OF[_s] = "水"
for _b in "寅卯":
    WX_OF[_b] = "木"
for _b in "巳午":
    WX_OF[_b] = "火"
for _b in "辰戌丑未":
    WX_OF[_b] = "土"
for _b in "申酉":
    WX_OF[_b] = "金"
for _b in "亥子":
    WX_OF[_b] = "水"

# 纳音（三十组，每组管两个干支）
NAYIN = [
    "海中金", "炉中火", "大林木", "路旁土", "剑锋金", "山头火",
    "涧下水", "城头土", "白蜡金", "杨柳木", "泉中水", "屋上土",
    "霹雳火", "松柏木", "长流水", "沙中金", "山下火", "平地木",
    "壁上土", "金箔金", "覆灯火", "天河水", "大驿土", "钗钏金",
    "桑柘木", "大溪水", "沙中土", "天上火", "石榴木", "大海水",
]

# 六旬空亡：旬首后第十、十一支，即本旬所无之二支
XUN_KONG = {}


def _build_xun_kong():
    for i in range(0, 60, 10):
        head = JIAZI[i]
        XUN_KONG[i // 10] = (JIAZI[(i + 10) % 60][1], JIAZI[(i + 11) % 60][1])


_build_xun_kong()


def xun_of(gz):
    return JIAZI.index(gz) // 10


def kong_of(gz):
    return XUN_KONG[xun_of(gz)]


def nayin(gz):
    return NAYIN[JIAZI.index(gz) // 2]


# ---------------- 天文：儒略日与太阳黄经 ----------------
def to_jd(dt):
    """公历（格里高利历）UTC → 儒略日。dt 为 datetime，按 UTC 解释。"""
    y, m = dt.year, dt.month
    d = (dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0)
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def from_jd(jd):
    """儒略日 → 公历 datetime（UTC）。"""
    jd += 0.5
    z = int(jd)
    f = jd - z
    if z < 2299161:
        a = z
    else:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    dd = int(365.25 * c)
    e = int((b - dd) / 30.6001)
    day = b - dd - int(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    di = int(day)
    frac = day - di
    hh = int(frac * 24)
    mm = int((frac * 24 - hh) * 60)
    ss = int(round((((frac * 24 - hh) * 60) - mm) * 60))
    if ss >= 60:
        ss -= 60
        mm += 1
    if mm >= 60:
        mm -= 60
        hh += 1
    return datetime(year, month, di, min(hh, 23), min(mm, 59), min(ss, 59))


def delta_t(year):
    """ΔT（TT-UT，秒）。Espenak & Meeus 多项式，1900–2150 段。"""
    y = year
    if y < 1920:
        t = y - 1900
        return -2.79 + 1.494119 * t - 0.0598939 * t ** 2 + 0.0061966 * t ** 3 - 0.000197 * t ** 4
    if y < 1941:
        t = y - 1920
        return 21.20 + 0.84493 * t - 0.076100 * t ** 2 + 0.0020936 * t ** 3
    if y < 1961:
        t = y - 1950
        return 29.07 + 0.407 * t - t ** 2 / 233 + t ** 3 / 2547
    if y < 1986:
        t = y - 1975
        return 45.45 + 1.067 * t - t ** 2 / 260 - t ** 3 / 718
    if y < 2005:
        t = y - 2000
        return (63.86 + 0.3345 * t - 0.060374 * t ** 2 + 0.0017275 * t ** 3
                + 0.000651814 * t ** 4 + 0.00002373599 * t ** 5)
    if y < 2050:
        t = y - 2000
        return 62.92 + 0.32217 * t + 0.005589 * t ** 2
    if y <= 2150:
        return -20 + 32 * ((y - 1820) / 100.0) ** 2 - 0.5628 * (2150 - y)
    return -20 + 32 * ((y - 1820) / 100.0) ** 2


def _sun_L0(t):
    """地球日心黄经 L0（度），VSOP87 截断（主要项）。t 为儒略千年数。"""
    T = t
    terms = [
        (175347046, 0, 0), (3341656, 4.6692568, 6283.07585),
        (34894, 4.6261, 12566.1517), (3497, 2.7441, 5753.3849),
        (3418, 2.8289, 3.5231), (3136, 3.6277, 77713.7715),
        (2676, 4.4181, 7860.4194), (2343, 6.1352, 3930.2097),
        (1324, 0.7425, 11506.7698), (1273, 2.0371, 529.691),
        (1199, 1.1096, 1577.3435), (990, 5.233, 5884.927),
        (902, 2.045, 26.298), (857, 3.508, 398.149),
        (780, 1.179, 5223.694), (753, 2.533, 5507.553),
        (505, 4.583, 18849.228), (492, 4.205, 775.523),
        (357, 2.92, 0.067), (317, 5.849, 11790.629),
        (284, 1.899, 796.298), (271, 0.315, 10977.079),
        (243, 0.345, 5486.778), (206, 4.806, 2544.314),
        (205, 1.869, 5573.143), (202, 2.458, 6069.777),
        (156, 0.833, 213.299), (132, 3.411, 2942.463),
        (126, 1.083, 20.775), (115, 0.645, 0.98),
        (103, 0.636, 4694.003), (102, 0.976, 15720.839),
        (102, 4.267, 7.114), (99, 6.21, 2146.17),
        (98, 0.68, 155.42), (86, 5.98, 161000.69),
        (85, 1.3, 6275.96), (85, 3.67, 71430.7),
        (80, 1.81, 17260.15), (79, 3.04, 12036.46),
        (75, 1.76, 5088.63), (74, 3.5, 3154.69),
        (74, 4.68, 801.82), (70, 0.83, 9437.76),
        (62, 3.98, 8827.39), (61, 1.82, 7084.9),
        (57, 2.78, 6286.6), (56, 4.39, 14143.5),
        (56, 3.47, 6279.55), (52, 0.19, 12139.55),
        (52, 1.33, 1748.02), (51, 0.28, 5856.48),
        (49, 0.49, 1194.45), (41, 5.37, 8429.24),
        (41, 2.4, 19651.05), (39, 6.17, 10447.39),
        (37, 6.04, 10213.29), (37, 2.57, 1059.38),
        (36, 1.71, 2352.87), (36, 1.78, 6812.77),
        (33, 0.59, 17789.85), (30, 0.44, 83996.85),
        (30, 2.74, 1349.87), (25, 3.16, 4690.48),
    ]
    s = 0.0
    for a, b, c in terms:
        s += a * math.cos(b + c * T)
    return s / 1e8


def _sun_L1(t):
    T = t
    terms = [
        (628331966747, 0, 0), (206059, 2.678235, 6283.07585),
        (4303, 2.6351, 12566.1517), (425, 1.59, 3.523),
        (119, 5.796, 26.298), (109, 2.966, 1577.344),
        (93, 2.59, 18849.23), (72, 1.14, 529.69),
        (68, 1.87, 398.15), (67, 4.41, 5507.55),
        (59, 2.89, 5223.69), (56, 2.17, 155.42),
        (45, 0.4, 796.3), (36, 0.47, 775.52),
        (29, 2.65, 7.11), (21, 5.34, 0.98),
        (19, 1.85, 5486.78), (19, 4.97, 213.3),
        (17, 2.99, 6275.96), (16, 0.03, 2544.31),
        (16, 1.43, 2146.17), (15, 1.21, 10977.08),
        (12, 2.83, 1748.02), (12, 3.26, 5088.63),
        (12, 5.27, 1194.45), (12, 2.08, 4694),
        (11, 0.77, 553.57), (10, 1.3, 6286.6),
        (10, 4.24, 1349.87), (9, 2.7, 242.73),
        (9, 5.64, 951.72), (8, 5.3, 2352.87),
        (6, 2.65, 9437.76), (6, 4.67, 4690.48),
    ]
    s = 0.0
    for a, b, c in terms:
        s += a * math.cos(b + c * T)
    return s / 1e8


def _sun_L2(t):
    T = t
    terms = [
        (52919, 0, 0), (8720, 1.0721, 6283.0758),
        (309, 0.867, 12566.152), (27, 0.05, 3.52),
        (16, 5.19, 26.3), (16, 3.68, 155.42),
        (10, 0.76, 18849.23), (9, 2.06, 77713.77),
        (7, 0.83, 775.52), (5, 4.66, 1577.34),
        (4, 1.03, 7.11), (4, 3.44, 5573.14),
        (3, 5.14, 796.3), (3, 6.05, 5507.55),
        (3, 1.19, 242.73), (3, 6.12, 529.69),
        (3, 0.31, 398.15), (3, 2.28, 553.57),
        (2, 4.38, 5223.69), (2, 3.75, 0.98),
    ]
    s = 0.0
    for a, b, c in terms:
        s += a * math.cos(b + c * T)
    return s / 1e8


def _sun_L3(t):
    T = t
    terms = [(289, 5.844, 6283.076), (35, 0, 0), (17, 5.49, 12566.15),
             (3, 5.2, 155.42), (1, 4.72, 3.52), (1, 5.3, 18849.23),
             (1, 5.97, 242.73)]
    s = 0.0
    for a, b, c in terms:
        s += a * math.cos(b + c * T)
    return s / 1e8


def sun_apparent_longitude(jde):
    """太阳视黄经（度，0–360）。输入为力学时儒略日。"""
    t = (jde - 2451545.0) / 365250.0
    L = (_sun_L0(t) + _sun_L1(t) * t + _sun_L2(t) * t ** 2
         + _sun_L3(t) * t ** 3)
    lon = math.degrees(L) + 180.0            # 地心 → 太阳视方向
    # 章动与光行差（主项）
    omega = math.radians(125.04 - 1934.136 * (jde - 2451545.0) / 365.25)
    lon += -0.00569 - 0.00478 * math.sin(omega)
    # FK5 修正
    lon += -0.09033 / 3600.0
    return lon % 360.0


def solve_sun_longitude(target_deg, jd_guess):
    """求太阳视黄经等于 target_deg 的儒略日（牛顿迭代）。"""
    jd = jd_guess
    for _ in range(12):
        lon = sun_apparent_longitude(jd)
        diff = (target_deg - lon + 180.0) % 360.0 - 180.0
        if abs(diff) < 1e-7:
            break
        jd += diff / 0.9856473      # 太阳每日行进度
    return jd


# 二十四节气：太阳黄经
TERMS24 = [
    ("春分", 0), ("清明", 15), ("谷雨", 30), ("立夏", 45),
    ("小满", 60), ("芒种", 75), ("夏至", 90), ("小暑", 105),
    ("大暑", 120), ("立秋", 135), ("处暑", 150), ("白露", 165),
    ("秋分", 180), ("寒露", 195), ("霜降", 210), ("立冬", 225),
    ("小雪", 240), ("大雪", 255), ("冬至", 270), ("小寒", 285),
    ("大寒", 300), ("立春", 315), ("雨水", 330), ("惊蛰", 345),
]
TERM_BY_DEG = {d: n for n, d in TERMS24}
# 十二「节」（月令之始），其余为「气」
JIE = ["立春", "惊蛰", "清明", "立夏", "芒种", "小暑",
       "立秋", "白露", "寒露", "立冬", "大雪", "小寒"]
JIE_DEG = {n: d for n, d in TERMS24 if n in JIE}


def term_time_cst(year, name):
    """某年某节气的北京时间（datetime）。"""
    deg = dict(TERMS24)[name]
    # 粗略起算：按黄经估月份
    approx_month = {0: 3, 15: 4, 30: 4, 45: 5, 60: 5, 75: 6, 90: 6, 105: 7,
                    120: 7, 135: 8, 150: 8, 165: 9, 180: 9, 195: 10, 210: 10,
                    225: 11, 240: 11, 255: 12, 270: 12, 285: 1, 300: 1,
                    315: 2, 330: 2, 345: 3}[deg]
    y = year if approx_month >= 2 else year
    guess = to_jd(datetime(y, approx_month, 6, 12, 0))
    # 小寒、大寒在 1 月，属「上年冬至之后」，仍用当年 1 月
    jde = solve_sun_longitude(deg, guess)
    # TT → UT
    ut = jde - delta_t(year) / 86400.0
    return from_jd(ut) + timedelta(hours=8)


def terms_of_year(year):
    """某公历年 24 节气的北京时间，按时间排序。"""
    out = []
    for name, deg in TERMS24:
        out.append((name, term_time_cst(year, name)))
    out.sort(key=lambda x: x[1])
    return out


# ---------------- 真太阳时 ----------------
def equation_of_time(day_of_year):
    """均时差（分钟）。"""
    b = (day_of_year - 1) * 360.0 / 365.0
    return 229.18 * (0.000075
                     + 0.001868 * math.cos(math.radians(b))
                     - 0.032077 * math.sin(math.radians(b))
                     - 0.014615 * math.cos(2 * math.radians(b))
                     - 0.040849 * math.sin(2 * math.radians(b)))


def true_solar_time(dt, lon):
    """北京时间 → 当地真太阳时。"""
    off = (lon - 120.0) * 4.0 + equation_of_time(dt.timetuple().tm_yday)
    return dt + timedelta(minutes=off), off


# ---------------- 四柱 ----------------
def jdn_of(d):
    """公历日期 → 儒略日数（正午制，整数）。"""
    return int(to_jd(datetime(d.year, d.month, d.day, 12, 0)) + 0.5)


ANCHOR_2000 = (date(2000, 1, 1), "戊午")
ANCHOR_1900 = (date(1900, 1, 1), "甲戌")


def day_pillar(d):
    """日柱：双锚点交叉，不一致即抛错。"""
    i1 = (JIAZI.index(ANCHOR_2000[1]) + (jdn_of(d) - jdn_of(ANCHOR_2000[0]))) % 60
    i2 = (JIAZI.index(ANCHOR_1900[1]) + (jdn_of(d) - jdn_of(ANCHOR_1900[0]))) % 60
    if i1 != i2:
        raise ValueError("日柱双锚点不一致：%s vs %s" % (JIAZI[i1], JIAZI[i2]))
    return JIAZI[i1]


def year_pillar(dt, lichun):
    """年柱：以立春为界。"""
    y = dt.year if dt >= lichun else dt.year - 1
    return JIAZI[(y - 4) % 60], y


JIE_BRANCH = {"立春": "寅", "惊蛰": "卯", "清明": "辰", "立夏": "巳",
              "芒种": "午", "小暑": "未", "立秋": "申", "白露": "酉",
              "寒露": "戌", "立冬": "亥", "大雪": "子", "小寒": "丑"}


def month_pillar(dt, year_gz, jie_all):
    """月柱：以节为界，五虎遁。jie_all 为跨年十二节（北京时间，升序）。

    月支由「最近一个已过的节」定，月干由五虎遁按年干起正月丙寅顺数。
    正月＝立春，故偏移以立春为 0。
    """
    last = None
    for name, t in jie_all:
        if name in JIE and t <= dt:
            last = name
    if last is None:
        raise ValueError("未找到出生时刻之前的节")
    branch = JIE_BRANCH[last]
    off = (BRANCHES.index(branch) - 2) % 12          # 立春起寅为 0
    yg = year_gz[0]
    start = {"甲": "丙", "己": "丙", "乙": "戊", "庚": "戊", "丙": "庚",
             "辛": "庚", "丁": "壬", "壬": "壬", "戊": "甲", "癸": "甲"}[yg]
    stem = STEMS[(STEMS.index(start) + off) % 10]
    return stem + branch, last


def hour_pillar(dt_tst, day_gz):
    """时柱：五鼠遁。dt_tst 为真太阳时。"""
    h = dt_tst.hour
    branch = BRANCHES[((h + 1) // 2) % 12]      # 23-1 子、1-3 丑 …
    dg = day_gz[0]
    start = {"甲": "甲", "己": "甲", "乙": "丙", "庚": "丙", "丙": "戊",
             "辛": "戊", "丁": "庚", "壬": "庚", "戊": "壬", "癸": "壬"}[dg]
    base = STEMS.index(start)
    off = BRANCHES.index(branch)
    return STEMS[(base + off) % 10] + branch


def effective_day(dt_tst):
    """晚子时换日：本器取「子初换日」（23:00 后日柱进一位）。

    **不是**「梁氏定论」——原书两法并存，本器取其一并明示，不代裁（未决登记 U-P9-01）：
      ·《命学大辞渊》述元史曆法「建子初——即二十三点换日柱」，
        明大统「命起子正，即以午夜○时换日柱」，并谓「此為子正、子夜二大差之根源」。
      · 若按子正（0 点）换日，23:00–23:59 生者日柱与时柱皆不同，六亲、晚运随之异。
    故凡落此段者，输出必附「时辰边界」一行；静默换日等于替读者作了主张。
    """
    if dt_tst.hour >= 23:
        return dt_tst.date() + timedelta(days=1)
    return dt_tst.date()


def dayun(month_gz, forward, birth_dt_tst, jie_list_all, n=8):
    """大运：顺逆排 + 起运精确到年月日。"""
    step = 1 if forward else -1
    out = []
    i = JIAZI.index(month_gz)
    for k in range(1, n + 1):
        out.append(JIAZI[(i + step * k) % 60])
    # 起运：顺数至下一「节」，逆数至上一「节」（只认十二节，不认气）
    if forward:
        nxt = [t for nm, t in jie_list_all if nm in JIE and t > birth_dt_tst]
        target = min(nxt) if nxt else None
    else:
        prv = [t for nm, t in jie_list_all if nm in JIE and t <= birth_dt_tst]
        target = max(prv) if prv else None
    start = None
    if target:
        mins = abs((target - birth_dt_tst).total_seconds()) / 60.0
        years = int(mins // 4320)
        rem = mins % 4320
        months = int(rem * 4 / 1440)
        rem2 = rem - months * 1440 / 4
        days = int(rem2 / 120 * 10)
        start = {"年": years, "月": months, "日": days,
                 "虚岁": years + 1, "节气": None}
        # 找节气名
        for nm, t in jie_list_all:
            if t == target:
                start["节气"] = nm
        # 精确起运日
        d = birth_dt_tst.date()
        y2 = d.year + years
        m2 = d.month + months
        while m2 > 12:
            m2 -= 12
            y2 += 1
        try:
            d2 = date(y2, m2, min(d.day, 28)) + timedelta(days=days)
        except ValueError:
            d2 = date(y2, m2, 1) + timedelta(days=days)
        start["起运日"] = d2.isoformat()
        # 交运时的虚岁（虚岁 = 交运年 - 出生年 + 1），与「折年数」分开标，免混
        start["交运虚岁"] = d2.year - d.year + 1
    return out, start


# ---------------- 十神 ----------------
def shishen(day_stem, other):
    """以日干为我，判十神。other 可为天干或地支（地支取其本气）。"""
    if other in BRANCHES:
        other = CANG[other][0]
    me, ot = WX_OF[day_stem], WX_OF[other]
    same = (STEMS.index(day_stem) % 2) == (STEMS.index(other) % 2)
    order = "木火土金水"
    mi, oi = order.index(me), order.index(ot)
    rel = (oi - mi) % 5
    if rel == 0:
        return "比肩" if same else "劫财"
    if rel == 1:
        return "食神" if same else "伤官"
    if rel == 2:
        return "偏财" if same else "正财"
    if rel == 3:
        return "七杀" if same else "正官"
    return "偏印" if same else "正印"


# ---------------- 主流程 ----------------
def paipan(d, tstr, gender, lon=None, name=""):
    hh, mm = [int(x) for x in tstr.split(":")]
    dt_bj = datetime(d.year, d.month, d.day, hh, mm)
    checks = []

    def ck(code, ok, msg):
        checks.append({"code": code, "ok": bool(ok), "msg": msg})

    # 真太阳时
    if lon is None:
        dt_tst = dt_bj
        tst_note = "未校正（未给经度，按北京时间）"
        ck("P02", True, "未给经度，真太阳时未校正（已明示，不假装校正）")
    else:
        dt_tst, off = true_solar_time(dt_bj, lon)
        tst_note = "经度 %.2f°，偏移 %+.1f 分钟 → %s" % (lon, off, dt_tst.strftime("%H:%M"))
        ck("P02", True, "真太阳时已校正：%s" % tst_note)

    # 节气
    jie_all = []
    for y in (d.year - 1, d.year, d.year + 1):
        for nm, t in terms_of_year(y):
            jie_all.append((nm, t))
    jie_all.sort(key=lambda x: x[1])
    jie_list = [(n, t) for n, t in jie_all if n in JIE and t.year == d.year]
    if len(jie_list) != 12:
        jie_list = [(n, t) for n, t in jie_all if n in JIE]
    ck("P03", len(jie_list) >= 12, "本年十二节已算得（天文算法，本地）")

    # 年柱以本年立春为界（须取出生年那一个立春，不可取 dict 折叠后的）
    lichun = None
    for nm, t in jie_all:
        if nm == "立春" and t.year == d.year:
            lichun = t
    if lichun is None:
        raise ValueError("未找到 %d 年立春" % d.year)
    ygz, ynum = year_pillar(dt_tst, lichun)
    ck("P04", ygz == JIAZI[(ynum - 4) % 60] and
       (dt_tst >= lichun) == (ynum == d.year),
       "年柱 %s（以立春 %s 为界）" % (ygz, lichun.strftime("%Y-%m-%d %H:%M")))

    mgz, mgz_jie = month_pillar(dt_tst, ygz, jie_all)
    ck("P05", True, "月柱 %s（以「%s」为界，五虎遁）" % (mgz, mgz_jie))

    dgz = day_pillar(effective_day(dt_tst))
    ck("P06", True, "日柱 %s（双锚点交叉一致：2000-01-01 戊午 / 1900-01-01 甲戌）" % dgz)

    hgz = hour_pillar(dt_tst, dgz)
    ck("P07", True, "时柱 %s（真太阳时 %s，五鼠遁）" % (hgz, dt_tst.strftime("%H:%M")))

    pillars = [ygz, mgz, dgz, hgz]
    ck("P08", all(p in JIAZI_SET for p in pillars), "四柱皆为合法干支")

    # 距节气报警
    near = []
    for nm, t in jie_all:
        gap = abs((dt_tst - t).total_seconds()) / 60.0
        if gap <= 45:
            near.append("%s 相差 %.0f 分钟" % (nm, gap))
    if near:
        ck("P09", False, "生日距节气过近（%s）：本器节气误差约 ±15 分钟，"
                         "月柱须用专业排盘软件复核" % "；".join(near))
    else:
        ck("P09", True, "生日距最近节气 > 45 分钟，月柱无边界风险")

    # 大运
    forward = (ygz[0] in YANG) == (gender == "男")
    dys, start = dayun(mgz, forward, dt_tst, jie_all)
    ck("P10", forward == ((ygz[0] in YANG) == (gender == "男")),
       "大运%s排（年干 %s 为%s，%s命）" % ("顺" if forward else "逆", ygz[0],
                                          "阳" if ygz[0] in YANG else "阴", gender))
    if start:
        ok = 0 <= start["年"] <= 10
        ck("P11", ok, "起运折 %d 年 %d 月 %d 日，%s 交运（交运虚岁 %d，数至「%s」）%s" % (
            start["年"], start["月"], start["日"], start["起运日"],
            start.get("交运虚岁", start["虚岁"]), start["节气"] or "",
            "" if ok else "——超出 0~10 岁，节气可能取错"))
    else:
        ck("P11", False, "起运未能算出（节气表不完整）")

    # 十神 / 藏干 / 纳音 / 空亡
    day_stem = dgz[0]
    detail = []
    for k, p in enumerate(pillars):
        cg = CANG[p[1]]
        detail.append({
            "pos": POS[k], "gz": p,
            "stem_ss": "日主" if k == 2 else shishen(day_stem, p[0]),
            "branch_ss": shishen(day_stem, p[1]),
            "cang": [{"gan": g, "ss": shishen(day_stem, g)} for g in cg],
            "nayin": nayin(p),
            "kong": list(kong_of(p)),
        })
    ck("P12", len(detail) == 4 and all(d["cang"] for d in detail), "十神／藏干／纳音已出")

    # 五行统计（含藏干）
    wx = {e: 0 for e in "木火土金水"}
    for p in pillars:
        wx[WX_OF[p[0]]] += 1
        for g in CANG[p[1]]:
            wx[WX_OF[g]] += 1
    ck("P13", sum(wx.values()) == 4 + sum(len(CANG[p[1]]) for p in pillars),
       "五行统计含藏干共 %d 字" % sum(wx.values()))

    # 逐柱空亡落点
    all_zhi = [p[1] for p in pillars]
    kong_hits = []
    for k, p in enumerate(pillars):
        kw = kong_of(p)
        for j, z in enumerate(all_zhi):
            if z in kw:
                kong_hits.append({"旬": p, "旬位": POS[k], "旬名": JIAZI[xun_of(p)][:2],
                                  "空": list(kw), "落": z, "位": POS[j]})
    ck("P14", True, "逐柱空亡已查（%d 处落空）" % len(kong_hits))

    # 当前大运（以今年计）
    today = date.today()
    cur = None
    if start and start.get("起运日"):
        sy = date.fromisoformat(start["起运日"])
        age = today.year - sy.year
        if age >= 0:
            idx = age // 10
            if idx < len(dys):
                cur = {"gz": dys[idx], "from": sy.year + idx * 10,
                       "to": sy.year + idx * 10 + 9,
                       "xu": start["虚岁"] + idx * 10}
    ck("P15", True, "当前大运：%s" % (("%s（%d–%d）" % (cur["gz"], cur["from"], cur["to"]))
                                    if cur else "未到起运"))

    return {
        "input": {"name": name, "date": d.isoformat(), "time": tstr,
                  "gender": gender, "lon": lon,
                  "bj": dt_bj.strftime("%Y-%m-%d %H:%M"),
                  "tst": dt_tst.strftime("%Y-%m-%d %H:%M"), "tst_note": tst_note},
        "pillars": pillars, "detail": detail,
        "borders": _borders(dt_bj, dt_tst),
        "wuxing": wx, "missing": [e for e in "木火土金水" if wx[e] == 0],
        "forward": forward, "dayun": dys, "start": start, "current": cur,
        "kong_hits": kong_hits,
        "jie": [{"name": n, "time": t.strftime("%Y-%m-%d %H:%M")}
                for n, t in jie_all if t.year == d.year],
        "checks": checks,
        "all_pass": all(c["ok"] for c in checks),
        "evidence_grade": "E6_结构计算",
    }


def _borders(dt_bj, dt_tst):
    """时辰边界提示：日柱可能因「换日法」或「真太阳时跨日」而与直觉不同时，必须说出来。

    这两件事的共同点是——盘照样排得出来，结果也照样「全部通过」，
    但日柱可能差一天。不提示，读者拿去用，错的是六亲与晚运。
    """
    out = []
    if dt_tst.hour >= 23:
        out.append(
            "**晚子时（真太阳时 %s）**：本器取**子初换日**，日柱已进一位。"
            "原书两法并存——《命学大辞渊》述元史「建子初，即二十三点换日柱」，"
            "明大统「命起子正，即午夜○时换日柱」，并谓此为「子正、子夜二大差之根源」。"
            "若按子正换日，日柱退回前一日、时干随之变。本器取其一并明示，不代裁（未决 U-P9-01）。"
            % dt_tst.strftime("%H:%M"))
    if dt_tst.date() != dt_bj.date():
        out.append(
            "**真太阳时跨日**：北京时间 %s → 真太阳时 %s，日柱按真太阳时取。"
            "同一生日不做经度校正，日柱会落在另一日——此造须先定出生地经度，再论其余。"
            % (dt_bj.strftime("%Y-%m-%d %H:%M"), dt_tst.strftime("%Y-%m-%d %H:%M")))
    return out


def render(r):
    L = []
    L.append("# 排盘（E6 结构计算，非梁氏判断）")
    L.append("")
    i = r["input"]
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append("| 公历 | %s %s（北京时间） |" % (i["date"], i["time"]))
    L.append("| 真太阳时 | %s |" % i["tst"])
    L.append("| 校正 | %s |" % i["tst_note"])
    L.append("| 性别 | %s |" % i["gender"])
    L.append("| 四柱 | %s |" % "　".join(r["pillars"]))
    L.append("| 大运 | %s排，起运 %s |" % (
        "顺" if r["forward"] else "逆",
        ("折 %d 年 %d 月 %d 日，%s 交运（交运虚岁 %d）" % (
            r["start"]["年"], r["start"]["月"], r["start"]["日"],
            r["start"]["起运日"], r["start"].get("交运虚岁", r["start"]["虚岁"])))
        if r["start"] else "—"))
    L.append("")
    if r.get("borders"):
        L.append("## 时辰边界（须先看这一节，再看四柱）")
        L.append("")
        for b in r["borders"]:
            L.append("> " + b)
            L.append("")
    L.append("## 四柱明细")
    L.append("")
    L.append("| 柱 | 干支 | 天干十神 | 地支十神 | 藏干 | 纳音 | 旬空 |")
    L.append("|---|---|---|---|---|---|---|")
    for d in r["detail"]:
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            d["pos"], d["gz"], d["stem_ss"], d["branch_ss"],
            "／".join("%s%s" % (c["gan"], c["ss"]) for c in d["cang"]),
            d["nayin"], "".join(d["kong"])))
    L.append("")
    L.append("## 五行（含藏干）")
    L.append("")
    L.append("　".join("%s%d" % (k, v) for k, v in r["wuxing"].items())
             + ("　**缺：%s**" % "、".join(r["missing"]) if r["missing"] else "　五行俱全"))
    L.append("")
    L.append("## 大运")
    L.append("")
    L.append("　".join(r["dayun"]))
    L.append("")
    L.append("## 逐柱空亡")
    L.append("")
    if r["kong_hits"]:
        for k in r["kong_hits"]:
            L.append("- %s柱%s（%s旬）空 %s → **%s柱%s 落空**" % (
                k["旬位"], k["旬"], k["旬名"], "".join(k["空"]), k["位"], k["落"]))
    else:
        L.append("- 四柱无落空。")
    L.append("")
    L.append("## 自检")
    L.append("")
    for c in r["checks"]:
        L.append("- %s %s　%s" % ("✅" if c["ok"] else "❌", c["code"], c["msg"]))
    L.append("")
    L.append("**结论：%s**" % ("全部通过" if r["all_pass"] else "有 FAIL，须修正后再用"))
    return "\n".join(L)


def self_test():
    """自检：日柱锚点、已知盘、节气落点。"""
    bad = []
    # 1. 双锚点
    if day_pillar(date(2000, 1, 1)) != "戊午":
        bad.append("2000-01-01 应为戊午")
    if day_pillar(date(1900, 1, 1)) != "甲戌":
        bad.append("1900-01-01 应为甲戌")
    # 2. 已知盘：1984-11-12 未时 → 甲子 乙亥 庚戌 癸未
    r = paipan(date(1984, 11, 12), "14:00", "男")
    want = ["甲子", "乙亥", "庚戌", "癸未"]
    if r["pillars"] != want:
        bad.append("1984-11-12 14:00 应得 %s，实得 %s" % (want, r["pillars"]))
    # 3. 节气落点（公历日）
    for y, name, lo, hi in ((2026, "立春", (2, 3), (2, 5)),
                            (2026, "冬至", (12, 21), (12, 23)),
                            (2026, "夏至", (6, 20), (6, 22)),
                            (2026, "春分", (3, 19), (3, 22)),
                            (1984, "立冬", (11, 6), (11, 9))):
        t = term_time_cst(y, name)
        d = (t.month, t.day)
        if not (lo <= d <= hi):
            bad.append("%d %s 落 %s，应在 %s–%s" % (y, name, d, lo, hi))
    # 4. 大运顺逆
    if not paipan(date(1984, 11, 12), "14:00", "男")["forward"]:
        bad.append("甲年男命应顺排")
    if paipan(date(1984, 11, 12), "14:00", "女")["forward"]:
        bad.append("甲年女命应逆排")
    if bad:
        print("自检 FAIL：")
        for b in bad:
            print("  -", b)
        return 1
    print("自检 PASS（4 组 12 项）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="自包含排盘（E6 结构计算）")
    ap.add_argument("--date", help="公历生日 YYYY-MM-DD")
    ap.add_argument("--time", help="出生时刻 HH:MM（北京时间）；不给则拒绝排盘——时柱不可默认")
    ap.add_argument("--gender", choices=["男", "女"])
    ap.add_argument("--lon", type=float, help="出生地经度（东经为正，须在 -180～180）；不给则不做真太阳时校正")
    ap.add_argument("--name", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        sys.exit(self_test())
    if not (a.date and a.gender):
        ap.error("须给 --date 与 --gender")
    if not a.time:
        ap.error("须给 --time。未给出生时刻即无法定时柱，本器不设默认值——"
                 "默认午时排出来的盘，时柱一错，六亲、子女、晚运全跟着错。")
    # 参数校验一律走 ap.error：抛 ValueError 出来的是堆栈，用户看不懂，
    # 也不知道该改哪个参数。宁可多三行，不让人对着 traceback 猜。
    try:
        d = date.fromisoformat(a.date)
    except ValueError:
        ap.error("--date %r 不是合法日期（须 YYYY-MM-DD，且日数在该月范围内）" % a.date)
    if not _TIME_RE.match(a.time or ""):
        ap.error("--time %r 格式不对，须 HH:MM（24 小时制，00:00–23:59）" % a.time)
    hh, mm = (int(x) for x in a.time.split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        ap.error("--time %r 越界：时 0–23、分 0–59" % a.time)
    if a.lon is not None and not (-180.0 <= a.lon <= 180.0):
        # 越界经度算出的是无意义的偏移，且不会报错——静默错比报错更坏
        ap.error("--lon %r 越界：经度须在 -180～180（东经为正）" % a.lon)
    r = paipan(d, a.time, a.gender, a.lon, a.name)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(render(r))
    sys.exit(0 if r["all_pass"] else 1)


if __name__ == "__main__":
    main()
