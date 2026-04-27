# Fine-Grained PPT Error Injection TODO

本文档记录当前细粒度 PPT 错误注入 benchmark 的实现状态，以及后续需要补齐的 TODO。

当前阶段只做 PPT 错误注入与标注，不做用户反馈模拟。默认 agent 在评测时只能看到 corrupted `slide.png`/页面内容和查库工具，不直接读取 GT YAML。

## 当前实现概览

实现位置：

- 注入入口：`scripts/fine_grained_error_injector.py`
- 注入主逻辑：`benchmarking/fine_grained/runner.py`
- mutation 策略：`benchmarking/fine_grained/mutations.py`
- schema / IO / 数值工具：`benchmarking/fine_grained/common.py`
- schema 与 coverage 校验：`benchmarking/fine_grained/validator.py`
- CLI 校验入口：`scripts/validate_fine_grained_benchmark.py`
- YAML 重建 data override：`engine/yaml_importer.py`
- GT caption 可见图表类型标签：`engine/builder.py`

当前启用的 error family：

- `st_caption`
- `st_body`
- `summary`
- `title`
- `st_summary`
- `summary_title`
- `three_element`

当前输出结构：

```text
split/<split>/s_<sample_id>/gt/slide.yaml
split/<split>/s_<sample_id>/gt/slide.pptx
split/<split>/s_<sample_id>/gt/slide.png
split/<split>/s_<sample_id>/injected/<artifact_id>/slide.yaml
split/<split>/s_<sample_id>/injected/<artifact_id>/slide.pptx
split/<split>/s_<sample_id>/injected/<artifact_id>/slide.png
split/<split>/s_<sample_id>/injected/<artifact_id>/corruption.json
manifest/corruptions.jsonl
manifest/corruption_coverage.json
manifest/corruption_validation.json
manifest/corruption_coverage_detailed.json
```

每个 corruption 记录：

- `operations`：记录目标元素、mutation 类型、语义槽位，以及 ST body 的 cell 定位。
- `expected_repair_yaml`
- 输入/输出路径

当前标注边界：

- injected `slide.yaml` 只保存 corrupted slide 本身，不内嵌 `corruption`。
- `corruption.json` 只保存 `operations` 与 `expected_repair_yaml`。
- `manifest/corruptions.jsonl` 额外保存路径索引；coverage 中的 family 由 `operations[].target` 推导。
- `before` / `after` 不重复写入标注，可分别从 GT YAML 与 injected YAML 推导。

## 已实现错误注入

### 1. ST-only.caption

状态：已实现。

family：

- `st_caption`

目标元素：

- `st.caption`

实现方式：

- 在 GT 生成阶段，caption 末尾追加可见图表/表格类型标签：
  - `(Bar chart)`
  - `(Line chart)`
  - `(Pie chart)`
  - `(Table)`
- 错误注入阶段直接修改 caption 文本，不改 ST body 数据。
- Summary 和 Title 保持 GT 正确内容。

当前 mutation types：

- `caption_chart_type_mismatch`
- `caption_scope_year`
- `caption_scope_city`
- `caption_scope_object`

具体做法：

- `caption_chart_type_mismatch`
  - 将 caption 末尾可见类型标签随机替换为另一个错误类型。
  - 候选类型：`Bar chart`、`Line chart`、`Pie chart`、`Table`。
  - 例：`(Bar chart)` -> `(Line chart)` / `(Pie chart)` / `(Table)`。
  - 图表本体仍保持柱状图，因此 agent 可以从视觉呈现与 caption 文本冲突发现错误。
  - `truth_basis: visible_rendering`
- `caption_scope_year`
  - 在 caption 中找到年份，随机加一或减一。
  - 例：`2020-2024` -> `2021-2024`。
- `caption_scope_city`
  - 将 caption 中城市名替换为其他城市。
  - 例：`Beijing` -> `Guangzhou`。
- `caption_scope_object`
  - 将 block 名改成同城市输入候选池中的另一个真实 block。
  - 候选池来自 `config/benchmark/ground_truth_inputs/<city>.csv`。
  - 例：`Liangxiang` -> `Miyun District`。
  - 只改 caption 可见文本，不改 `query_filters.block` 和 ST body 数据。
  - `operations` 额外记录 `scope_field: block`、`truth_value`、`wrong_value`。

修复目标：

- `expected_repair_yaml` 指向 GT。
- `expected_operations` 记录 caption 文本从错误值恢复到 GT 值。

当前限制：

- 只改 caption 可见文本，不重新查错 scope 对应的数据。
- 因此 scope 错误目前是“caption 与 ST body / 数据库真值冲突”，不是“caption scope 和 body 同步漂移”。
- block donor 已改为真实 block，但不保证地理相邻，只保证来自同城市 GT 输入池。

TODO：

- [ ] 为 scope 错误增加更细的类型拆分：time / city / block。
- [ ] 评估是否需要生成“caption scope + ST body 数据同步漂移”的版本；这会接近 ST+Summary 或整体漂移，需要单独定义可观测锚点。
- [ ] caption 与图表类型不一致已经可做，后续需要在视觉评测中确认 agent 是否能从截图中识别 chart type。
- [ ] 如果需要“相邻 block”，在 `ground_truth_inputs` 中补充行政区/坐标/邻接关系，而不是从名字上猜。

### 2. ST-only.body

状态：已实现。

family：

- `st_body`

目标元素：

- `st.body`

实现方式：

- 从 GT YAML 的 `slide_filters` 重新查库得到真实 DataFrame。
- 在 chart/table 对应 DataFrame 中选择一个可解析的数值 cell。
- 对该 cell 做数值扰动。
- 将扰动后的 DataFrame 写入 injected YAML 的 `mutated_data`。
- `YAMLImporter` 重建 PPT 时优先使用 `mutated_data[data_key]`，因此 PPT/PNG 中的图表或表格会真的使用 mutated data。

当前 mutation types：

- `data_numeric_delta`

具体做法：

- 对数值进行小幅加减或比例扰动。
- 支持 chart 和 table，因为二者最终都走 DataFrame payload。
- `operations` 中记录：
  - `data_key`
  - `cell.row_index`
  - `cell.row_label`
  - `cell.column_index`
  - `cell.column`
  - `before`
  - `after`
  - `truth_basis: database_rebuild`

修复目标：

- `expected_repair_yaml` 指向 GT。
- `expected_operations` 记录目标 cell 从错误值恢复到 GT 值。

当前限制：

- 只做单 cell 数值扰动。
- 没有实现整行、整列、局部区域、趋势结构级扰动。
- 没有实现统计口径类错误。
- 对 chart/table header 或 legend/axis label 不做修改。

TODO：

- [ ] 增加 row/column/block 级数值扰动。
- [ ] 增加趋势反转型 data perturbation，但需要保证图表仍可读。
- [ ] 增加统计口径类错误设计与实现，见后文“未实现错误”。
- [ ] 增加 data override 与 PPT 图表数据一致性的更强测试。

### 3. Summary-only

状态：已实现。

family：

- `summary`

目标元素：

- `summary`

实现方式：

- 注入时基于 GT YAML 的 `meta`、`query_filters`、`slide_filters` 重查数据库。
- 从对应 Summary text pattern 中解析 Jinja slot，并用数据库结论变量得到 slot 真值。
- 对 slot 真值做扰动。
- 仅在内存中用扰动后的 slot 重新渲染 summary。
- 只改 body-text/summary 文本，不改 ST 和 Title。

当前 mutation types：

- `trend_flip`
- `numeric_delta`
- `summary_scope_year`
- `summary_scope_city`
- `summary_scope_object`

具体做法：

- `trend_flip`
  - 替换 increase/decrease/growth/decline 等趋势词。
- `numeric_delta`
  - 对 summary slot 中的业务数值做扰动。
  - 会跳过 `year/month/date/temporal/time` 等时间类 slot。
  - 会跳过 `1900-2099` 范围内的 year-like token，避免把 `2020` / `2024` 当成普通业务数值。
  - 对单个业务数值按量级扰动，而不是固定 `±5/±20`。
  - 对非年份区间使用 `range_delta`，整体平移区间两端。
  - 例：`16716 units` -> `13373 units`。
  - 例：`80-100m²` -> `70-90m²`。
  - 例：`2020-2024` 不由 `numeric_delta` 处理；时间错误由 `summary_scope_year` 处理。
- `summary_scope_year`
  - 直接修改 Summary 可见文本中的起止年份。
  - 只改 Summary，不改 ST body、caption 或 query scope。
- `summary_scope_city`
  - 直接修改 Summary 可见文本中的城市名。
  - 当前 donor 城市来自 `Beijing` / `Guangzhou` / `Shenzhen`。
- `summary_scope_object`
  - 直接修改 Summary 可见文本中的 block 名。
  - donor block 来自同城市 `config/benchmark/ground_truth_inputs/<city>.csv` 的真实 block。
  - `operations` 额外记录 `scope_field: block`、`truth_value`、`wrong_value`。

修复目标：

- `expected_repair_yaml` 指向 GT。
- `expected_operations` 记录 summary 文本恢复。
- 额外记录：
  - `slot_name`
  - `slot_before`
  - `slot_after`

当前限制：

- 数值、趋势类错误依赖 summary slot 中存在可扰动值。
- scope 类错误直接修改 Summary 可见文本，因此只有当 Summary 文本本身包含年份、城市或 block 时才可生成。
- 非 scope 错误不是直接任意改 summary 自然语言，而是通过即时推导的 slot 真值重新渲染，优点是结构清楚，缺点是错误类型受 slot 限制。
- GT / injected `slide.yaml` 不再持久化 `summary_binding`；Summary 注入所需真值由注入器临时推导。
- 暂未实现“推断性描述不被 ST 支撑”的复杂语义错误。
- 已移除占位式 `text_drift`，不再生成 `core band -> core band Alt` 这类不可解释错误。

TODO：

- [ ] 增加 summary 级别的 unsupported inference 错误。
- [ ] 增加 summary 区间扰动的专门 mutation type，而不是全部归入 `numeric_delta`。
- [ ] 评估是否需要让 text pattern 更稳定地包含 city/block/year，以提升 Summary scope 错误覆盖率。

### 4. Title-only

状态：已实现。

family：

- `title`

目标元素：

- `title`

实现方式：

- 找到 role 为 `slide-title` 的 textBox。
- 从 `TITLE_DONORS` 中选择一个不同主题 title 替换。
- ST 和 Summary 保持 GT 正确内容。

当前 mutation types：

- `title_theme_drift`

具体做法：

- 例：`Block Area Segment Distribution` -> `Annual Avg Price Growth`。
- 不改 template id，不改 ST 数据，不改 Summary。

修复目标：

- `expected_repair_yaml` 指向 GT。
- `expected_operations` 记录 title 文本恢复。

当前限制：

- donor title 是固定列表，不是从同 layout/template 语义空间中严格采样。
- 目前只模拟主题漂移，不模拟轻微措辞错误。

TODO：

- [ ] 将 donor title 分层：同房型/跨房型、同统计对象/跨统计对象。

### 5. ST + Summary

状态：已实现有限版本。

family：

- `st_summary`

目标元素：

- `st.body`
- `summary`

实现方式：

- 先对 ST body 的 DataFrame 某个数值 cell 做 `data_numeric_delta`。
- 要求这个数值能在 summary slot 真值中找到对应项。
- 将 summary 中对应 slot 同步改成与 ST body 一致的错误值。
- Title 保持 GT 正确内容。

当前 mutation types：

- `data_numeric_delta+linked_numeric_delta`

具体做法：

- `mutate_st_body(..., require_summary_link=True)` 只选择能和 summary numeric slot 对齐的数值。
- 然后 `mutate_summary(..., forced_slot=..., forced_value=...)` 将 summary 同步传播到同一错误值。
- 这构造的是“可观测传播错误”：页面内部 ST 与 Summary 局部自洽，但可通过数据库真值恢复。

修复目标：

- `expected_repair_yaml` 指向 GT。
- `expected_operations` 同时记录 data cell 和 summary 文本恢复。

当前限制：

- 只支持数值传播。
- 不支持 caption scope 错误传播到 summary。
- 不支持统计口径错误传播到 summary。
- 不生成内部完全自洽但整体漂移的不可观测样本。

TODO：

- [ ] 支持 caption scope -> summary scope 的传播错误，但必须保留数据库可观测锚点。
- [ ] 支持统计口径 -> summary 的传播错误。
- [ ] 增加多 cell 改动后 summary 聚合值同步错误。

### 6. Summary + Title

状态：已实现。

family：

- `summary_title`

目标元素：

- `summary`
- `title`

实现方式：

- Summary 使用 Summary-only 的 slot override 机制生成错误。
- Title 使用 Title-only 的 donor title 替换。
- ST 保持 GT 正确内容。

当前 mutation types：

- `<summary_mutation>+title_theme_drift`

例：

- `numeric_delta+title_theme_drift`
- `trend_flip+title_theme_drift`

修复目标：

- `expected_repair_yaml` 指向 GT。
- `expected_operations` 同时记录 summary 和 title 文本恢复。

当前限制：

- Summary 和 Title 当前是分别扰动，并不保证两者偏向同一个错误主题。
- 因此它目前表达的是“中高层同时错”，不是严格语义共偏。

TODO：

- [ ] 设计 topic-aware donor，使 title donor 和 summary 错误方向一致。
- [ ] 增加从 ST 推回 Summary + Title 的评测标注说明。

### 7. Three-element Observable

状态：已实现有限版本。

family：

- `three_element`

目标元素：

- `st.body`
- `summary`
- `title`

实现方式：

- ST body 做 `data_numeric_delta`。
- Summary 对同一个 linked summary slot 做 `linked_numeric_delta`。
- Title 做 `title_theme_drift`。

当前 mutation types：

- `data_numeric_delta+linked_numeric_delta+title_theme_drift`

具体做法：

- 保留原 query scope 和数据库锚点。
- ST body 和 Summary 可以对同一个错误数值局部自洽。
- Title 额外发生主题漂移。
- 这不是整体自洽漂移，仍然可通过数据库真值和元素冲突发现。

修复目标：

- `expected_repair_yaml` 指向 GT。
- `expected_operations` 同时记录 data cell、summary、title 恢复。

当前限制：

- 只有数值传播 + title 漂移一种组合。
- 不支持 caption、header、统计口径参与三元素错误。
- 不生成 unobservable 三元素整体偏移。

TODO：

- [ ] 增加 caption + summary + title 的 observable 组合。
- [ ] 增加 data multi-cell + summary + title 的 observable 组合。
- [ ] 明确 three-element 的最低可观测锚点规则。

## 已实现基础设施

### 1. `mutated_data`

状态：已实现。

实现方式：

- injected YAML 可包含：

```yaml
mutated_data:
  <data_key>:
    orient: split
    index: [...]
    columns: [...]
    data: [...]
```

- `YAMLImporter` 重建 PPT 时优先使用 `mutated_data[data_key]`。
- 如果不存在 override，则按原 `slide_filters` 查库。

TODO：

- [ ] 增加 data override schema version。
- [ ] 增加对多 data_key 同时 override 的测试。

### 2. `corruption` metadata

状态：已实现。

写入位置：

- injected `slide.yaml`
- injected `corruption.json`
- `manifest/corruptions.jsonl`

TODO：

- [ ] 根据后续错误类型扩展 `observability` 和 `repair_mode`，不要长期全部写死为 `observable` / `unique_repair`。

### 3. Coverage / schema validator

状态：已实现。

实现方式：

- `scripts/validate_fine_grained_benchmark.py`
- 检查 manifest、路径、ID 唯一性、required fields、targets 与 operations 对齐、sidecar JSON 一致性、output YAML corruption 一致性、expected repair inverse。

输出：

- `manifest/corruption_validation.json`
- `manifest/corruption_coverage_detailed.json`

TODO：

- [ ] 增加每个 family 的可行/不可行原因统计。
- [ ] 增加 40 模板 x family 的正式 coverage gate。
- [ ] 增加 chart/table 分类型 coverage。

## 未实现错误注入

### 1. Header 错误

状态：未实现。

原始设计：

- 字段名错配。
- 例：表头写“成交面积”，实际列内是“成交套数”。

未实现原因：

- 当前 schema 中 table header、chart legend、axis label 不是统一元素。
- chart 的系列名、坐标轴标签、legend 和 table header 的抽象层不同。
- 如果强行统一，会引入冗余兼容逻辑。

建议设计：

- 第一阶段只做 table header。
- 第二阶段再做 chart series label / axis label。
- 不要把它们都叫 `header`，而是拆成：
  - `table_header_label_mismatch`
  - `chart_series_label_mismatch`
  - `chart_axis_label_mismatch`

TODO：

- [ ] 梳理 PPT schema 中 table header 的位置。
- [ ] 梳理 chart series name 是否能稳定从 DataFrame index/columns 映射到 PPT。
- [ ] 先实现 `table_header_label_mismatch`。
- [ ] 再决定是否把 chart legend/axis 纳入同一 family。

### 2. 统计口径类错误

状态：未实现。

原始设计：

- body 数值不是简单 cell 错，而是统计逻辑错。
- 例：应按成交套数 count，却误用成交面积 sum。
- 例：应按年份聚合，却按月份/面积段聚合。

未实现原因：

- 这不是普通 YAML 文本替换，而是 query/filter/function 参数层的错误。
- 当前注入模块只在 GT 后处理阶段工作，适合改最终 YAML/PPT，不适合重新选择统计函数或分析配置。
- 如果只改 DataFrame 数值，无法证明它来自某个错误统计口径。

建议设计：

- 不在 `mutations.py` 里硬造一个随机 DataFrame。
- 应该基于可解释的 alternative query plan 生成：
  - 原 function key
  - 错误 function key 或错误 metric rule
  - 错误 params
  - mutated DataFrame
  - truth query plan
  - wrong query plan

可能 schema：

```yaml
corruption:
  operations:
    - target: st.body
      mutation_type: statistic_logic_mismatch
      data_key: ...
      truth_basis: database_rebuild
      wrong_logic:
        function_key: ...
        params: ...
        metric_rule: ...
      truth_logic:
        function_key: ...
        params: ...
        metric_rule: ...
```

TODO：

- [ ] 列出现有 function specs 中可安全替换的统计口径对。
- [ ] 从最小集合开始：count vs sum、area metric vs unit metric。
- [ ] 只生成数据库可重算且可解释的错误口径。
- [ ] 在 manifest 中记录 wrong query plan 和 truth query plan。

### 3. Title + ST

状态：暂缓，未实现。

原始设计：

- Title 与 ST 一起偏向错误 theme。
- Summary 保持正确或未同步。

暂缓原因：

- 按页面拓扑，ST 决定 Summary，Title 又概括 ST/Summary。
- Title + ST 同错但 Summary 正确会显得不自然。
- 如果 Title、ST、Summary 全部同步，又变成 three-element 或整体漂移。

TODO：

- [ ] 先不生成主评样本。
- [ ] 等用户反馈/真实意图输入设计清楚后，再考虑作为需要用户确认的样本。

### 4. Three-element Unobservable 整体漂移

状态：未实现。

原始设计：

- 整页共同漂移到另一个内部自洽、数据库也支持的状态。
- 例：地点从北京换成广州，数据也换成广州真实数据，Title/Summary/ST 全部一致。

不实现原因：

- 在当前评测设定中，agent 看不到原始 GT 或真实用户意图。
- 如果 corrupted 页面内部自洽且数据库也支持，agent 没有公平依据判断它错。
- 这类样本不适合放进主评。

TODO：

- [ ] 不进入当前主 benchmark。
- [ ] 后续如果加入用户意图或用户反馈，可作为 separate split / diagnostic set。

### 5. 用户反馈模拟

状态：未实现。

原始设计：

- 用 LLM 模拟用户，对 agent 的修复候选进行 confirm / correction。

未实现原因：

- 当前阶段先验证“错误注入与标注”本身可信。
- 用户反馈会改变任务定义，需要单独设计动作空间和评价协议。

TODO：

- [ ] 定义 user simulator 输入：corruption metadata、agent question、GT intent。
- [ ] 定义 user simulator 输出动作：confirm、scope correction、logic correction、page intent correction。
- [ ] 将 requires_user_feedback 样本从主评中分离。

## 当前优先级 TODO

### P0：保证现有 benchmark 可信

- [x] GT YAML/PPT/PNG 可生成。
- [x] injected YAML/PPT/PNG 可生成。
- [x] `mutated_data` 可用于 PPT 重建。
- [x] `corruption.json` 和 `manifest/corruptions.jsonl` 可校验。
- [x] coverage report 可统计 template/layout/family 覆盖。
- [ ] 对完整 40 模板跑一次小规模 generation + injection + validation。
- [ ] 把 coverage gate 加进测试或脚本。

### P1：补齐重要但不复杂的错误

- [ ] table header label mismatch。
- [ ] chart series label mismatch。
- [ ] summary 区间扰动专门类型。
- [ ] data row/column/block 级扰动。

### P2：补统计口径错误

- [ ] 梳理可替换统计口径对。
- [ ] 设计 wrong query plan schema。
- [ ] 实现最小统计口径错误：count vs sum。
- [ ] 让 expected repair 能指回 truth query plan。

### P3：暂缓或诊断集

- [ ] Title + ST。
- [ ] Three-element Unobservable。
- [ ] 用户反馈模拟。

## 最近 smoke test 状态

最近一次简单完整测试：

- GT：3 个样本。
- 模板：
  - `T01_Supply_Trans_Bar`
  - `T02_Cross_Pivot_Table`
  - `T02_Area_Dist_Line`
- 注入：7 个 family，每类 3 个，共 21 个 corruption。
- 覆盖：3 个模板、3 个 layout 都覆盖。
- validator：`errors=0, warnings=0`。
- 输出目录：`output/benchmark/smoke_fine_grained`
