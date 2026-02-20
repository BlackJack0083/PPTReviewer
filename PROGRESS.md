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
