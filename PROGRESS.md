# 经验教训沉淀

## 2026-02-20

### 问题描述
YAML 导出器中的图表 args 参数格式不清晰，难以理解和维护。原来使用的嵌套列表格式：
```yaml
args:
  - field-constraint
  - - - supply_counts
      - trade_counts
    - - area_range
      - '{}-{}m²'
      - '0'
      - '300'
      - 20
    - - supply_sets
      - trade_sets
    - - count
      - count
```

### 解决方案
进行了符合软件工程原则的重构，将 `TableAnalysisConfig` 贯穿整个数据流：

1. **ChartElement** - 添加可选的 `config` 字段存储 `TableAnalysisConfig`
2. **PresentationContext** - 添加 `_configs` 字典存储配置
3. **data_provider** - `execute_by_function_key` 返回三元组 `(df, conclusions, config)`
4. **context_builder** - 自动将 config 保存到 context
5. **builder** - 创建 ChartElement 时传入 config
6. **yaml_exporter** - 直接从 ChartElement.config 导出清晰格式
7. **layouts.yaml + layout_manager** - 将 slide_size 解耦到配置文件

现在生成的 args 格式清晰易读：
```yaml
args:
  table_type: "field-constraint"
  dimensions:
    - source_col: "dim_area"
      target_col: "area_range"
      method: "range"
      step: 20
      format_str: "{}-{}m²"
  metrics:
    - name: "Supply Count"
      source_col: "supply_sets"
      agg_func: "count"
      filter_condition:
        supply_sets: 1
```

### 以后如何避免
- 数据配置应该与数据本身绑定，而不是分开存储
- 避免使用硬编码的映射字典，尽量使用配置驱动的方式

### Git Commit
- 分支: feature/chart-element-with-config

## 2026-02-20 (续)

### 问题描述
YAML 导出的 args 中缺少 min/max 字段，导致无法从配置中获取数据的实际范围。

### 解决方案
在 data_provider.py 中为每个 BinningRule 添加 min/max 的计算：

1. **get_supply_transaction_stats** - 从 raw_df["dim_area"] 计算 min/max
2. **get_area_price_cross_stats** - 分别计算 dim_area 和 dim_price 的 min/max
3. **get_area_distribution_stats** - 从 raw_df["dim_area"] 计算 min/max
4. **get_price_distribution_stats** - 从 raw_df["dim_price"] 计算 min/max

同时更新 yaml_exporter.py 的 _config_to_dict 方法，导出 min/max 字段。

现在生成的 args 包含完整的范围信息：
```yaml
args:
  table_type: "field-constraint"
  dimensions:
    - source_col: "dim_area"
      target_col: "area_range"
      method: "range"
      step: 20
      format_str: "{}-{}m²"
      min: 0
      max: 300
  metrics:
    - name: "Supply Count"
      source_col: "supply_sets"
      agg_func: "count"
      filter_condition:
        supply_sets: 1
```

---

## 2026-02-21

### 问题描述
1. **代码可读性问题**：代码中存在大量被注释的死代码（transformers.py、data_utils.py、data_provider.py），影响阅读
2. **类型注解不完整**：多个核心类缺少返回类型注解
3. **YAML 导出冗余**：yaml_exporter.py 中存在硬编码的静态映射表（`CHART_ARGS_TEMPLATES` 和 `SELECT_COLUMNS_MAP`），这些数据实际上已经存在于 `TableAnalysisConfig` 中，造成重复和冗余

### 解决方案

#### 1. 删除死代码
- 删除 `core/transformers.py` 中约 120 行被注释的旧实现代码
- 删除 `utils/data_utils.py` 中约 150 行被注释的旧函数
- 删除 `core/data_provider.py` 中被注释的分析配置代码

#### 2. 补充类型注解
- `style_manager.py` - 添加 `__init__` 返回类型
- `resources.py` - 添加多个方法的返回类型
- `context_builder.py` - 添加方法返回类型
- `ppt_operations.py` - 添加 `_configure_axes` 参数类型

#### 3. YAML Exporter 重构（核心重构）
删除 yaml_exporter.py 中的硬编码静态映射：
- 删除 `CHART_ARGS_TEMPLATES` 字典
- 删除 `SELECT_COLUMNS_MAP` 字典
- 简化 `_build_chart_args` 方法 - 强制要求 `config` 存在，不再做 fallback 推断
- 修改 `_build_slide_filters` - 从 `context.configs` 动态获取列信息

### 以后如何避免
- 定期清理被注释的代码，不要保留过时代码
- 使用 Python 的 type hint，提高代码可读性
- 数据配置应该与数据本身绑定，避免硬编码映射

### Git Commit
- 分支: refactor/clean-up-code-base
- Commit ID: 78e7b6b

---



---

### 给 Claude 的指令模板

为了让你一次完成重构，指令应该包含：

```
请对这个仓库进行代码重构，主要关注以下几点：

1. 删除死代码 - 删除所有被注释掉的旧代码（搜索所有包含 "# def" 或 "# result" 等注释代码的行）

2. 补充类型注解 - 为以下文件中的方法添加返回类型：
   - core/style_manager.py
   - core/resources.py
   - core/context_builder.py
   - core/ppt_operations.py

3. 重构 yaml_exporter.py - 删除以下硬编码的静态映射：
   - CHART_ARGS_TEMPLATES
   - SELECT_COLUMNS_MAP
   并修改相关方法从 context.configs 获取数据，而不是从静态映射获取
```

请注意：指令越具体、指向的文件和函数越明确越好。

---

## 2026-02-22

### 问题描述
YAML 导出器 yaml_exporter.py 在导出 fun_tool.args 时，无论 function_key 是什么，都总是输出 `area_range_size` 和 `price_range_size`：

```python
"fun_tool": {
    "fun": func_key,
    "args": {
        "area_range_size": area_size,
        "price_range_size": price_size,
    }
},
```

这导致：
1. 导出的 YAML 参数冗余（不是所有函数都需要这两个参数）
2. yaml_importer.py 中的 FUNCTION_KEY_PARAMS 与导出参数不一致（如 "step" vs "area_range_size"）
3. 导入时参数丢失，如 "Area Segment Distribution" 的 `area_range_size: 20` 无法被识别

### 解决方案

1. **yaml_exporter.py** - 添加 FUNCTION_KEY_PARAMS 常量，根据 function_key 筛选需要的参数：
   ```python
   FUNCTION_KEY_PARAMS = {
       "Supply-Transaction Unit Statistic": {"area_range_size"},
       "Area x Price Cross Pivot": {"area_range_size", "price_range_size"},
       "Area Segment Distribution": {"area_range_size"},
       "Price Segment Distribution": {"price_range_size"},
   }
   ```

2. **yaml_importer.py** - 同步更新 FUNCTION_KEY_PARAMS 保持一致

### 以后如何避免
- 导出器和导入器的参数定义必须保持一致，建议使用共享常量
- 每个 function_key 的参数应该明确定义，避免硬编码输出不需要的参数

### Git Commit
- 分支: refactor/clean-up-code-base


## 2026-03-06

### 问题描述
阶段 1（GT 生成）到阶段 2（错误注入）衔接不稳定：
原流程只在 YAML 中保存了最终渲染后的 summary 文本，没有保存 summary 模板与槽位真值，导致注入时只能做正则替换，容易误改、难追踪。

### 解决方案
本次采用“最小改动”方案，只增强 summary 链路，不改图表数据链路：

1. **resources.py**
   - 在加载 `text_pattern.yaml` 时保留 `raw_summaries`
   - 新增 `get_summary_template(theme, func, variant_idx)` 获取未渲染模板字符串

2. **context_builder.py**
   - 在 context 中保存 `_conclusion_vars`（结论真值）
   - 供 YAML 导出阶段精准提取 summary 相关槽位

3. **yaml_exporter.py**
   - 新增 `summary_binding` 字段，结构如下：
   ```yaml
   summary_binding:
     summary_template: "..."
     summary_slots_truth: {...}
     summary_context_fixed: {...}
     summary_slot_overrides: {}
     target_text_role: body-text
   ```
   - `summary_slots_truth` 作为真值，不参与注入修改
   - `summary_slot_overrides` 作为注入入口

4. **新增正式模块 engine/summary_injector.py**
   - `inject_summary_slots(...)`：仅更新 `summary_slot_overrides`
   - 基于 `summary_template + truth + overrides` 重新渲染 summary
   - 覆盖 `template_slide` 中 `body-text` 文本
   - `inject_summary_and_rebuild_ppt(...)`：注入后直接复用 `yaml_importer` 重建 PPT

### 当前满足度评估（对最初阶段 1-2 需求）
1. **阶段 1：GT PPT + YAML 生成**
   - 已满足
   - 说明：重新生成的 YAML 已包含 `summary_binding`，可追溯 summary 模板和真值槽位

2. **阶段 2：按槽位改错误结论并重建 PPT**
   - 已满足（针对 summary 槽位）
   - 说明：可精确改 `summary_slot_overrides` 并重渲染，不再依赖正则替换整句文本

### 当前已知边界（非阻塞）
1. 旧的历史 YAML 文件（已生成在 `output/mass_production`）不自动补 `summary_binding`，需要重新生成一遍 GT 数据。
2. `test/error_injector.py` 仍是旧正则方案，尚未切换到 `engine/summary_injector.py`。
3. `yaml_importer.py` 目前仍依赖文件名解析 `template_id`，建议后续改为优先读取 YAML 内显式元信息。

### 后续重构建议（推荐顺序）

#### Phase A：Schema 固化（先做）
1. 在 YAML 顶层新增 `schema_version`（例如 `v2`）
2. 新增 `meta`（`template_id/layout_type/style_id/theme_key/function_keys`）
3. `yaml_importer` 优先读 `meta.template_id`，去掉文件名解析耦合

#### Phase B：注入流程统一（第二步）
1. 将 `test/error_injector.py` 迁移为对 `SummaryInjector` 的封装入口
2. 批量注入脚本改为“按槽位注入”而非“正则全文替换”
3. 输出注入审计信息（注入前值/注入后值/注入键）

#### Phase C：模型化与校验（第三步）
1. 为 YAML schema 建立 Pydantic 模型
2. 导出前和注入后做结构校验
3. 增加回归测试：`GT 导出 -> 槽位注入 -> 重建 PPT -> 校验 truth 不变`

### 以后如何避免
1. 对“需要后续机器改写”的文本，必须同时保存 `template + slot truth + overrides` 三要素。
2. 注入逻辑必须基于结构化槽位，不允许回退到整句正则替换。
3. 导出器与导入器使用同一份 schema 定义，避免字段漂移。


## 2026-03-14

### 当前进展（以当前代码为准）

#### 1) Agent 三种模式已明确并文档化
- 已整理 `no_tool / with_tool / with_tool_react` 的执行原理、调用次数、输出差异与适用场景。
- 文档位置：`docs/agent_modes_comparison.md`。

#### 2) 模型调用链路补充了 Thinking 开关（默认关闭）
- `Client` 支持 `enable_thinking`，并通过请求体下发 `extra_body.enable_thinking`。
- `run_single.py`、`run_small_eval.py` 已支持从环境变量读取：`DASHSCOPE_ENABLE_THINKING`。
- 现状说明：在当前网关/模型下，关闭后仍可能返回 `reasoning_content` 字段，但可降低“只出思考、不出 content”的概率；`max_tokens` 仍需合理设置。

#### 3) ReAct 路径已加默认递归步数限制
- `PPTSummaryJudgeAgent` 新增 `react_recursion_limit`（默认 `15`）。
- `with_tool_react` 调用时自动注入 `graph_config.recursion_limit`（可被外部显式配置覆盖）。

#### 4) with_tool 路线的参数来源已厘清
- 当前 `with_tool` 不从图片提取 `function_args`。
- `function_args` 来自 `resolve_plan(template_id)` + `common/function_specs.py` 默认参数映射。
- 实际执行参数以 `slide_filters[].fun_tool.args` 为准。

#### 5) YAML 字段冗余已收敛
- 导出器 `query_filters` 已移除冗余字段：`project / area_range_size / price_range_size`。
- 保留字段：`city / block / start_date / end_date`。
- 说明：导入重建实际使用的函数参数一直来自 `slide_filters[].fun_tool.args`，不是 `query_filters`。

#### 6) 已生成数据集已做一致性清理
- 已批量清理 `output/benchmark/dataset_v1/split/**/slide.yaml` 中 `query_filters` 的冗余键。
- 变更统计：`3757` 个 YAML 文件更新，共移除 `11271` 个键。

#### 7) 数据集模板覆盖现状已盘点
- 模板总数（定义）：`13`
- 当前有样本覆盖：`7`
- 当前缺失覆盖：`6`
  - `T02_Area_Dist_Line`
  - `T02_Double_Price_Dist_Bar`
  - `T02_Double_Price_Dist_Line`
  - `T02_Price_Dist_Line`
  - `T04_Annual_Supply_Demand_Bar`
  - `T04_Annual_Supply_Demand_Line`

### 已知边界（当前仍需注意）
1. `with_tool` 的 claim 提取目前是“提示约束 + 必填校验”，尚未做强约束候选校验（如 template_id/table_name 必须在候选集合）。
2. 当筛选条件导致空数据时，底层可能出现 `area_range`/`price_range` 相关错误日志，属于“上游抽取或数据为空”连锁结果，不是 function_args 键名映射错误。
3. PPTX 转 PNG 在不同渲染后端（PowerPoint vs LibreOffice）存在可见差异，评测时应固定同一渲染链路。


## 2026-03-30

### 问题描述
这轮目标从“只判断 summary 是否有问题”推进到“让 agent 能指出要改哪个 textBox，并把修改真正落到 YAML/PPT 上”，同时把这套能力接进 `no_tool / with_tool / with_tool_react` 三种范式里，便于后续比较三种方法的修正效果。

### 解决方案
本次采用“最小可执行闭环”方案，只新增通用单文本框编辑能力，不引入多余工具编排：

1. **agent/tools_local.py**
   - 新增 `list_editable_textboxes(...)`
   - 新增 `apply_textbox_edit(...)`
   - 新增 runtime `yaml_path` 上下文，用于让 workflow/react 在工具层隐式持有当前样本 YAML，不把路径暴露给 agent
   - 默认输出路径规则：
     - 输入：`slide.yaml`
     - 输出 YAML：`slide-text_edited.yaml`
     - 输出 PPT：`slide-text_edited.pptx`

2. **agent/workflows/no_tool_flow.py**
   - `no_tool` 不再只输出 `{"has_issue": bool}`
   - 现在支持输出：
     - `has_issue`
     - `shape_id`
     - `updated_summary`
   - 其中 `shape_id/updated_summary` 只在 `has_issue=true` 时有意义

3. **agent/workflows/with_tool_flow.py**
   - 维持固定流程：
     - `extract_claim`
     - `validate_claim`
     - `plan_tools`
     - `run_tools`
     - `judge_with_tool`
     - `apply_text_edit`
   - 在 `judge_with_tool` 阶段，模型基于：
     - 图片 summary
     - tool 真值 summary
     - editable textboxes
     生成 `has_issue / shape_id / updated_summary`
   - 新增 `apply_text_edit` 节点，负责真正调用 `apply_textbox_edit(...)`

4. **agent/react_agent.py**
   - 为 `with_tool_react` 新增两个工具：
     - `list_editable_textboxes`
     - `apply_textbox_edit`
   - agent 现在不仅能查证据，还能在 react 轨迹中自主选择要改的 textBox 并执行编辑

5. **agent/pipeline.py**
   - `AgentResult` 新增字段：
     - `shape_id`
     - `updated_summary`
     - `execution_success`
   - 新增 `_resolve_yaml_path(...)`，优先接收显式 `yaml_path`，否则再尝试从图片同目录推断
   - pipeline 在三种模式调用前统一注入 `editable_shapes`

6. **agent/run_single.py / scripts/run_small_eval.py**
   - 增加 `yaml_path` 传递，避免只靠图片路径猜测当前样本 YAML

7. **test/test_tools_local_text_edit.py**
   - 新增最小单测，覆盖：
     - 只列出 `textBox`
     - 单个 textBox 修改后 YAML 更新
     - 触发 PPT 重建调用
     - runtime `yaml_path` 可用

### 已完成验证

#### 1) 单元测试
- 命令：
  ```bash
  uv run python -m unittest test.test_tools_local_text_edit
  ```
- 结果：通过

#### 2) 真实重建测试
- 对真实样本 YAML 直接调用 `apply_textbox_edit(...)`
- 成功生成：
  - `slide-text_edited.yaml`
  - `slide-text_edited.pptx`
- 说明：底层“改单个 textBox 并重建 PPT”能力已经可用

#### 3) GT 样本真实链路测试
- 在关闭代理的前提下，分别跑了：
  - `no_tool`
  - `with_tool`
  - `with_tool_react`
- 结果：
  - `no_tool`：可跑通，返回 `has_issue=false`
  - `with_tool`：可跑通，返回 `has_issue=false`
  - `with_tool_react`：
    - 默认递归上限 `15` 时仍可能触发 `GraphRecursionError`
    - 将 `react_recursion_limit` 提到 `30` 后可跑通，返回 `has_issue=false`

#### 4) Injected 正样本真实链路测试
- 对 injected 样本实际跑了三种模式
- 结果暴露出当前主问题：
  - `no_tool`：误判为 `has_issue=false`
  - `with_tool`：当前测试中也未稳定检出问题
  - `with_tool_react`：出现“最终 `has_issue=false`，但中途却调用了 `apply_textbox_edit`”的不一致行为

### 本轮额外修正
在 workflow/react 的执行层，修正了“执行失败直接中断整条样本”的问题：

1. **with_tool**
   - 若 `shape_id` 缺失
   - 或 `updated_summary` 缺失
   - 或 `shape_id` 非法
   - 或执行 `apply_textbox_edit(...)` 报错
   - 现在都不会再抛异常中断样本
   - 而是保留模型已输出的：
     - `has_issue`
     - `shape_id`
     - `updated_summary`
   - 并将 `execution_success=false`

2. **with_tool_react**
   - 若最终判断 `has_issue=true`，但没有形成有效编辑动作
   - 也会将 `execution_success=false`
   - 不再因为执行层失败吞掉前面的判断结果

### 当前已知问题
1. **react 存在逻辑不一致**
   - 当前观察到：`has_issue=false` 时，react 仍可能调用 `apply_textbox_edit`
   - 这违反了当前任务定义，应继续收紧 prompt / tool-use 终止条件

2. **正样本检出率不稳定**
   - 在已测 injected case 上，`no_tool` 和 `with_tool` 都没有稳定检出问题
   - 说明当前 prompt 和任务定义还不够强

3. **react 默认递归上限过低**
   - `react_recursion_limit=15` 仍可能触发 `GraphRecursionError`
   - 虽然调高到 `30` 后可缓解，但本质问题仍是 agent 终止条件不清晰

4. **评测脚本尚未完全升级**
   - 当前 `run_small_eval.py` 仍主要统计 `pred_has_issue`
   - 尚未完整纳入：
     - `shape_selection_accuracy`
     - `summary_update_accuracy`
     - `ppt_execution_success_rate`

5. **执行层依赖重新查库**
   - `apply_textbox_edit(...)` 底层是改 YAML 后走 `yaml_importer.rebuild_from_yaml(...)`
   - 因此仍会重新查数据库并重渲染整页 PPT
   - 当前这不算阻塞，但后续若要更快或更稳定，可能要考虑“仅文本替换”的更轻量路径

### 针对剩余工程问题的收敛方案（除“正样本检出率不稳定”外）

#### A) react 存在逻辑不一致：`has_issue=false` 但仍调用编辑工具
目标：让 react 的“判断”和“执行”保持单调一致，不允许出现自相矛盾轨迹。

建议收敛方式：
1. **把最终结构化输出扩成最小闭环结果**
   - 目前 `ReactJudgeOutput` 只有 `has_issue`
   - 建议改为至少显式包含：
     - `has_issue`
     - `will_edit`
   - 并加硬约束：
     - `has_issue=false -> will_edit=false`
     - `has_issue=true -> 允许 will_edit=true`
   - 这样 evaluator 不需要再从模糊轨迹里猜 agent 意图

2. **在 react prompt 中把编辑工具定义为“终止动作”**
   - 明确写成：
     - 如果决定编辑，`apply_textbox_edit(...)` 必须是最后一个业务工具
     - 调完后立刻输出最终结构化结果
     - 如果判断无问题，禁止调用编辑工具
   - 目的：避免 agent 在“还没决定好”时先试探性调用编辑工具

3. **在 pipeline 侧加入最小一致性校验**
   - 不要额外改 agent 逻辑，只在结果归一化时加一条规则：
     - 若 `final.has_issue=false` 且轨迹里出现 `apply_textbox_edit`
     - 则记为：
       - `execution_success=false`
       - `react_protocol_violation=true`
   - 这不是兜底修复，而是把错误暴露成可评测信号

4. **如果 react 在这个任务上长期不稳定，考虑把“编辑执行”从 react 中摘掉**
   - 即：
     - react 只负责产出 `has_issue / shape_id / updated_summary`
     - 真正执行统一交给 runtime
   - 这样仍然保留 react 的“自主取证”特性，但避免它在执行层制造协议噪声
   - 这是备选路线，不是当前第一优先级

#### B) react 默认递归上限仍偏紧
目标：减少 `GraphRecursionError`，但不靠一味把上限调得很大。

建议收敛方式：
1. **先固定为两段式心智**
   - 取证阶段：最多调用若干信息工具
   - 决策阶段：要么结束，要么执行单次编辑
   - 不鼓励在 react 中反复“查一点 -> 想一点 -> 再查一点”

2. **为 react 增加显式停止准则**
   - 当以下条件满足时应立即结束：
     - 已拿到 `expected_summary`
     - 已拿到 `editable_textboxes`
     - 已完成一次明确判断
   - 当前本质问题不是上限值太小，而是模型不知道“什么时候已经足够”

3. **默认值保持保守，但把实验值和生产值分开**
   - 当前默认 `15` 可以继续保留
   - 真正做实验时允许显式传 `30`
   - 不建议再把默认值继续往上推，否则会掩盖真实的停止条件问题

4. **在评测中额外记录 react 的步数成本**
   - 建议后续把以下指标纳入日志：
     - `tool_call_count`
     - `message_count`
     - `hit_recursion_limit`
   - 这样以后能区分“能力不足”和“搜索过程过长”

#### C) 评测脚本尚未完全升级
目标：让三种范式统一落到可比的修正任务指标上，而不是只看 `has_issue`。

建议收敛方式：
1. **统一 evaluator 最终抽取字段**
   - 对三种方法都归一化成：
     - `pred_has_issue`
     - `pred_shape_id`
     - `pred_updated_summary`
     - `execution_success`

2. **明确主指标 / 辅指标分层**
   - 主指标：
     - `issue_detection_accuracy`
     - `shape_selection_accuracy`
     - `summary_update_accuracy`
   - 辅指标：
     - `ppt_execution_success_rate`
     - `avg_tool_calls`
     - `avg_latency`
   - 这样可以把“模型修正能力”和“工程执行能力”分开

3. **对 no-tool 和有工具范式分开解释，不强行做伪公平**
   - `no_tool`：
     - 不评执行工具能力
     - 只评内容层输出质量
   - `workflow/react`：
     - 除内容层指标外，再额外报告执行成功率
   - 这样实验叙事最自然

4. **把执行失败从“样本错误”改成“样本结果的一部分”**
   - 当前这个方向已经开始做了
   - 后续在 `run_small_eval.py` 里需要继续落实：
     - 不要因执行失败丢失 `pred_has_issue`
     - 不要因工具报错直接把整条样本排除

#### D) 执行层依赖重新查库
目标：把“文本编辑执行”与“整页重建依赖数据库”解耦，降低波动和成本。

建议收敛方式：
1. **短期保持现状**
   - 当前为了复用现有 `yaml_importer`，允许重新查库并整页重渲染
   - 这条链路已经验证可用，因此短期不建议重写

2. **中期增加一个“仅文本替换”轻量路径**
   - 新增独立执行器，只做：
     - 定位 textBox
     - 替换文本
     - 基于现有 PPT 直接另存
   - 不重新查数据库，不重算图表
   - 这个路径更贴近“修正文案”任务本身

3. **保留两种执行模式，而不是立刻替换旧模式**
   - `rebuild` 模式：
     - 复用当前 YAML -> PPT 整页重建
   - `text-only` 模式：
     - 只对 PPT 文本框做轻量更新
   - 后续可在评测中比较两者稳定性和速度

4. **如果未来主任务只考修正能力，优先使用 text-only 执行**
   - 因为当前研究重点不是重新生成图表，而是 agent 是否能选对 shape 并写对文本
   - 把数据库重查放进执行链，只会把无关变量带进来

### 以后如何避免
1. 对“agent 要修改哪个元素”的任务，优先暴露最小执行工具：单个 shape、单次文本修改，不要一开始就做批量编辑。
2. 在评测设计中，必须把“模型判断结果”和“执行层是否成功”分开记录，不能因为工具执行失败直接丢失 `has_issue`。
3. react 路径必须用显式约束防止“最终判断无问题，但中途仍执行编辑”的不一致行为。
4. 真机链路测试必须显式关闭代理，否则网络问题会掩盖真实的 agent / workflow 问题。

### Git Commit
- 当前 HEAD: `13e0403`
- 说明：本轮修改尚未形成新的提交，以上记录对应当前工作区增量
