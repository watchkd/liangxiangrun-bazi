# 梁湘润批八字 · 技能包

把梁湘润子平命理体系整理成可被 AI 直接调用的批八字技能包。**每个判断都带规则／格值 ID、
来源定位、证据等级、核验状态、确定性使用级别。**

**项目特征**：

- **数据层**：1,164 条结构化规则（177 项未决如实标注）、4,103 格值、84 命例、322 张原书表格，
  每条可回查来源文件与行号
- **全流程**：排盘（天文算法现算节气，非查表）→ 复述核盘 → 十七节命书（HTML，含实用指要与
  待验问事）→ 回访纠偏闭环（符／偏问单 → 疑盘核查 → 复核版）
- **可复跑校验**：`tools/validate.py` 七组 91 项守护（含动态层批法、赞赏尾注、文档数字对账），
  一条命令验全部
- **纯 Python 标准库**，不联网，无第三方依赖

日期：2026-11-01　入口：[`SKILL.md`](SKILL.md)

> **使用前请先读 [`DISCLAIMER.md`](DISCLAIMER.md)**：本包是传统命理文献的整理与检索工具，
> 不主张预测效力，不替代医疗／法律／投资等专业意见，禁止用于收费欺诈与歧视性决策。
> 许可见 [`LICENSE.md`](LICENSE.md)：自撰部分 CC BY-NC-SA 4.0，原书著作权归原作者。
>
> **版权说明**：全文类底本（《穷通宝鉴》全文、引文核验库、《栏江网》文本）仅限本地研究
> 使用，**不随本公开仓分发**（见 `.gitignore`）。克隆者跑 `validate.py` 时，相关逐字比对、
> 六书台账与检索器项自动跳过；全量校验须自备底本。

## 这是什么

把梁湘润五套资料（LX2-11～15）整理成可被 AI 直接调用的批八字技能包。**每个判断都带规则／格值 ID、来源定位、证据等级、核验状态、确定性使用级别。**

Part 47 起本包**自带排盘**（`tools/paipan.py`，天文算法现算节气，非查表）。排盘结果一律标 E6 结构计算：它给出四柱、起运、大运、空亡的**结构**，不给出吉凶；节气落点误差约 ±15 分钟，生日距节气 45 分钟内者校验器会报 FAIL，须以专业排盘软件复核。**不以通行术数补写梁氏原文**——排盘是本包自己算的结构，断语仍只从规则库出。

## 怎么用

作为技能：放到 `~/.workbuddy/skills/liangxiangrun-bazi/`，用户给**公历生日＋时刻＋性别**即触发（旧版要求四柱，Part 47 起改为首选生日，四柱仍收）。旧路径 `~/.workbuddy-ai/skills/` 亦可，但当前会话扫描的是前一个。

**交付六轨**：底稿／推演稿／命书（HTML）／十九板块报告（简版默认·详版挂号）／批词／行动附录（三档宜平避）；证据索引并入报告详版，不再是必交件。

作为命令行：

```bash
# 排盘（Part 47 新增）
python tools/paipan.py --date 1984-11-12 --time 14:00 --gender 男
python tools/paipan.py --date 1984-11-12 --time 14:00 --gender 男 --lon 116.4 --json

# 批命推演（P11 新增 · 主入口）：按梁氏次序断，不出编号
python tools/panduan.py 甲子 乙亥 庚戌 癸未 --gender 男 \
    --birth-year 1984 --start-age 10 --dayun 丙子,丁丑,戊寅 --liunian 2026,2027
python tools/panduan.py 甲子 乙亥 庚戌 癸未 --gender 男 \
    --birth-year 1984 --start-age 10 --dayun 丙子,丁丑,戊寅 --recent 5   # 当前大运近五年
python tools/panduan.py 甲子 乙亥 庚戌 癸未 --gender 男 --trace   # 批者自核时附编号
python tools/panduan.py --self-test

# 一致率（回量「像不像梁师」；量不到「准不准」，那要事实标注集）
python tools/trace_audit.py
python tools/trace_audit.py --out _命书/一致率报告.md

# 回访纠偏（交件后：问单 → 命主填「符/偏/说不清」 → 校准 → 复核版）
python tools/feedback.py --pan pan.json --quiz 回执问单.md
python tools/feedback.py --recv 回执问单_已填.md --out-json calibrated.json
python tools/feedback.py --pan pan.json --filled 回执问单_已填.md --recheck 复核版.md

# 四柱分析（底稿 · 台账）
python tools/analyze.py 戊辰 戊午 甲午 乙丑 --gender 男
python tools/analyze.py 甲子 乙亥 庚戌 癸未 --gender 男 --dayun 丙子,丁丑,戊寅

# 多因子交叉（Part 47 新增）
python tools/crosscheck.py 甲子 乙亥 庚戌 癸未 --gender 男

# 神煞探源起例（P7 新增）
python tools/shensha_calc.py 甲子 乙亥 庚戌 癸未 --gender 男 --all
python tools/shensha_calc.py --self-test
```

五件东西分工不同：`xingqing.py` 出**性情**（量十神力量，取过多者为主，再取其心性条列，
分过旺／微偏／无偏三档），`liuqin.py` 出**出身与父母兄弟**（年柱看出身、偏财与印看父母、比劫看兄弟），`panduan.py` 出**判断稿**（十项优先→核心矛盾→用神→十神定位乙轨→星宫合参→大运→流年，
每条写「看到什么／依什么理／断什么」），`shishen_pos.py` 出**十神定位**（柱位×十神、坐、数量、通根四类，
财官派的路子），`analyze.py` 出**台账**（资料维度逐项检索），`trace_audit.py` 出**一致率**（判断点压到条文上的比例、
梁氏所引条文的召回、梁氏断过的主题本器断没断），`feedback.py` 出**回访纠偏**（问单→校准→复核版，偏差成片先疑盘）。
都不算交付件，执行者须复核后按六段体例落笔。

一致率现行四数：接线率 92.0%、落地率 92.9%、梁氏召回 63.5%、主题呼应 88.1%。
判据缺口已归零——17 条不是靠加边补的，是补出乙轨（十神定位）之后自然接上的：
偏印格三依据、食神变德、七杀坐七杀、比肩分柱这些本就是财官派的断法。
4.3 财与事业 0/59→57/59、4.7 寿元疾病 0/59→10/59，两节不再空转。
**召回六成不是断准六成**——那要事实标注集，仍未开工。

问「这几年怎么样」，加 `--recent 5`（默认 5，含今年）即可，不必逐年手敲：
工具先由 `--birth-year`／`--start-age`／`--dayun` 定出今年在第几运、运内第几年，
再论这五年——未起运者明写「运未立，不下断」，窗口跨运者逐年带运名。
只在五年里看五年，看到的是五个干支，不是五年。

对客件（命书／报告／附录）**不出书目页码与 rule_id**——出处留给底稿与 `--trace`。

## 自检

```bash
python tools/validate.py            # 7 组 91 项，退出码 0 = 无 FAIL
python tools/validate.py --quiet
python tools/validate.py --json > validate_report.json
```

当前：`PASS 91｜WARN 0｜FAIL 0`。

**`FAIL 0` 只证结构与自洽，不证内容已验真。** 校验器查的是 ID 唯一、外键完整、门控不泄漏、计数对得上、引文与全文逐字一致、文档与数据不打架；它不重读图版、不重判原文。

## 数据规模

| 类型 | 数量 |
|---|---|
| 规则 | 1164 |
| 命例 | 84（完整四柱 59、不完整 4、非四柱 21） |
| 表格格值 | 4,103（322 个表级 ID） |
| 冲突 | 63（开放 19、已裁定（并列保留）22、待核 13、已关闭 8、已裁定（占位）1） |
| 未决项 | 177（开放 133、已关闭 18、已裁定（引用注意）14、部分处置 8、其他 4） |
| crosswalk | 5,997 |

## 证据门控（摘要）

| 等级 | 含义 | 能不能用 |
|---|---|---|
| E1 | 同书图版 | 可作强证据，仍看核验状态 |
| E2 | 异本图版 | 只能标“异本” |
| E3 | 电子文本／OCR | 可定位，未回图者降级 |
| E4 | 字幕 | 只证明“说过”，不证明“说对” |
| E4b | 视频帧 | 覆盖极低，不得外推 |
| E5 | 整理者推论 | 只作线索 |
| E6 | 结构计算 | 只作结构，非梁氏结论 |

状态：`已核／部分核／待核／冲突／候选／排除`。确定性使用：`允许／条件允许／禁止`。**待核、冲突、候选、排除一律禁止进入结论。**

## 目录

```text
SKILL.md               入口：输入、执行顺序、输出格式、禁止事项
README.md              本文件：交付说明
DISCLAIMER.md          **使用前必读**：使用限制、禁止用法、责任限制、个人信息
LICENSE.md             三层许可：自撰部分 CC BY-NC-SA 4.0／原书归原作者／古籍按其版本
INTEGRATION_STATUS.md  验收门槛逐项对照、已知阻断
TOTAL_ASSEMBLY.md      Part 15 总装执行报告（校验器落地）
QA.md                  上游包检查与总装自检结果
CHANGELOG.md           逐轮变更
PATCH_SUMMARY.md       回传摘要
references/            分析流程、证据政策、冲突、未决、术语、各类索引
references/interaction_flow.md   交互话术（开场白、索要件、缺件六种应对、交付）——开口前必读
references/demo_session.md       一次完整交互的实录（八轮对话到交件，附后台命令与交付清单）
references/report_19.md          十九板块报告规格（Part 47 新增，每节挂证据）
references/appendix_actions.md   行动附录规格（Part 47 新增，非梁氏原文，不标证据等级）
data/                  30 个 CSV ＋ 4 个 TXT（引文核验库／古籍原文／神煞表）＋ 2 个统计快照
tools/                 10 个运行期工具（见下）
_命书/                 交付件样本：命书 HTML、十九板块报告、批词底稿
_dev/                  构建期工具与样本（**运行不需要**，见 _dev/README.md）
```

运行期十件：`paipan.py` 排盘／`analyze.py` 检索底稿／`crosscheck.py` 多因子交叉／
`shensha_calc.py` 神煞起例／`mingshu.py` 命书两轨／`report_gen.py` 报告骨架与索引／
`report_check.py` 交付件验收／`corpus_search.py` 跨书原文检索／`test_golden.py` 回归／
`validate.py` 总装校验。

## 运行环境

- **Python ≥ 3.7**，**纯标准库**，不装任何第三方包，不联网（无网络请求、无遥测）。
- 全平台可用（Windows／macOS／Linux）；路径均按脚本位置推算，可在任意工作目录调用。
- 二进制零依赖，故无 `requirements.txt`。

**Windows 控制台编码**：中文版 Windows 默认代码页 cp936，直接输出 `✅` 会在第一张表之前崩。
`paipan.py`／`corpus_search.py` 已自行把 stdout 转为 UTF-8；若见乱码，先 `chcp 65001`
或在 Windows Terminal／VS Code 终端中运行。

## 四条铁律

1. **排盘只出结构，不出吉凶。** 排盘结果标 E6；节气误差 ±15 分钟，距节气 45 分钟内报 FAIL 须复核；真太阳时无经度即明写「未校正」。
2. 不换算历法、不补用户未给的柱。用户给农历者，请其改给公历。
3. 不把整理者推论、字幕、异本写成梁氏原文。
4. 不为“验收数字归零”删冲突、降分母、把未核改通过。
