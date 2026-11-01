# `_dev/` —— 构建期工具（运行本包不需要）

这里的脚本是**把原始资料做成包**时用的，不参与排盘、检索、成文、验收任何一环。
删掉整个 `_dev/`，`tools/` 的十个运行期工具照常工作，`validate.py` 仍 PASS 83。

保留它们是为了**可复现**：别人拿到同样的源件，能照原路重做一遍，而不是只能相信结果。

## 各件用途

| 文件 | 用途 | 前提 |
|---|---|---|
| `check_note_coverage.py` | 笔记章节 ↔ 视频集覆盖核对 | 需包外资料库（`--lib`，默认 `D:/梁湘润`） |
| `check_subtitle_content.py` | 32／38 集字幕与知识点逐条对账 | 同上 |
| `corpus_build.py` | 把语料原文规范为 `data/*_fulltext.txt` | 需包外语料目录（脚本内 `CORPUS` 常量） |
| `corpus_merge_parts.py` | 分段文本合并成整本全文，并核页数 | 需分段 txt |
| `fix_after_merge.py` | 补丁并入后的一次性收口 | — |
| `gen_stats.py` | 从 `data/` 实载重算 `_integration_stats.json`（`--check` 只核对） | 无 |
| `merge_patch.py` | 把增量补丁规则并入 `rules.csv` | 无 |
| `rule_tags.py` | 重算规则的 `topic`／`trigger_tags` | 无 |

## `samples/`

- `upgrade_plan.md`：P0–P8 的内部升级计划（开发过程文档，不进交付）。
- `骨架_甲子乙亥庚戌癸未.md`：`report_gen.py` 出的**未填骨架**样本，故意保留——
  它会被 `report_check.py` 判 FAIL（B06 待批未清）。留作「骨架 ≠ 交付件」的实物证据。

## 注意

- 前三个脚本里的 `D:/梁湘润` 是**构建机上的语料库位置**，换机器须改 `--lib` 或改常量。
  这也是它们不进 `tools/` 的原因：交付件里不该有一条指向别人硬盘的默认路径。
- `gen_stats.py` 改了 `data/` 就该跑一次；否则 `validate.py` 的 C01／C03 会报计数不符。
