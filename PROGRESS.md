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
