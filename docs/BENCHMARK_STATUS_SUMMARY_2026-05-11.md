# Benchmark Status Summary (2026-05-11)

这份文档总结了我们刚刚围绕 benchmark 数据集、受控错误注入、feedback 生成与数据集拆分的讨论结果，作为接下来进入“方法设计讨论”前的工程状态记录。

## 1. 当前 benchmark 主链路

当前 pipeline 已经收敛成三步：

1. `scripts/ground_truth_generation.py`
   - 生成 GT
   - 写入 `split/<split>/s_<sample_id>/gt/`
   - 维护 `manifest/samples.jsonl`

2. `scripts/fine_grained_error_injector.py`
   - 基于 GT 生成受控错误样本
   - 写入 `split/<split>/s_<sample_id>/injected/<artifact_id>/`
   - 维护 `manifest/corruptions.jsonl`

3. `scripts/generate_feedback_episodes.py`
   - 基于 `manifest/corruptions.jsonl` 为每个 injected case 生成 feedback 文件
   - 写回各 case 目录下的 `feedback_episode.json`

另外提供了两个 shell 脚本便于批量运行：

- `scripts/generate_fine_grained_corruptions.sh`
- `scripts/generate_feedback_benchmark.sh`


## 2. 受控错误注入：命名与结构统一

### 2.1 family 命名统一

此前存在：

- family: `metric_label`
- target: `st.header`

我们已经决定把 family 名也一起统一：

- family: `st_header`
- target: `st.header`

已经同步到：

- `benchmarking/fine_grained/common.py`
- `benchmarking/fine_grained/mutations.py`
- `benchmarking/fine_grained/validator.py`
- `scripts/generate_fine_grained_corruptions.sh`
- 对应测试

注意：

- mutation type 仍然是：
  - `series_metric_swap`
  - `table_metric_swap`

### 2.2 当前 family 列表

当前受控错误 family 为：

- `st_caption`
- `st_body`
- `summary`
- `title`
- `st_header`
- `st_summary`
- `summary_title`
- `three_element`


## 3. feedback 数据：从集中式改为 case-local

### 3.1 不再使用数据集级 `feedback/episodes.jsonl`

之前 feedback 输出曾经是集中式：

- `output/benchmark/dataset_v2/feedback/episodes.jsonl`

后来我们讨论后决定：

- feedback 本质上是每个 injected case 的配套监督信息
- 更适合和 `slide.yaml` / `corruption.json` 放在一起

因此现在改为：

```text
split/<split>/s_<sample_id>/injected/<artifact_id>/feedback_episode.json
```

也就是说，一个完整 case 现在是：

```text
split/<split>/s_<sample_id>/injected/<artifact_id>/
  slide.yaml
  corruption.json
  feedback_episode.json
  slide.pptx
  data/...
```

### 3.2 当前 `feedback_episode.json` 的最简结构

我们进一步去掉了冗余字段，当前结构为：

```json
{
  "expected_action": "...",
  "expected_request": {...},
  "user_reply": {...}
}
```

已经去掉：

- `episode_id`
- `sample_ref`
- `corruption_ref`
- `split`
- `grading_spec`
- `turns`

原因：

- 文件已经 case-local，路径本身携带上下文
- 当前只支持单轮 feedback
- grading 规则更适合放在 evaluator 全局逻辑里，而不是每条 case 重复存一遍


## 4. feedback 生成逻辑：当前规则

feedback 生成入口：

- `scripts/generate_feedback_episodes.py`

核心实现：

- `benchmarking/feedback/generator.py`

### 4.1 输入

输入主要来自：

- `manifest/corruptions.jsonl`
- 对应 `record["source_yaml"]` 指向的 GT YAML

### 4.2 四类 expected_action

当前 feedback generator 会把 corruption 映射到 4 类动作：

- `confirm`
- `scope_correction`
- `logic_correction`
- `page_intent_correction`

#### `confirm`

适用于：

- `caption_chart_type_mismatch`
- `data_numeric_delta`
- `numeric_delta`
- `range_delta`
- `trend_flip`
- `title_theme_drift`
- `linked_numeric_delta`

形式：

```json
{
  "expected_action": "confirm",
  "expected_request": {
    "confirm_target": ["summary"]
  },
  "user_reply": {
    "confirm": true
  }
}
```

#### `scope_correction`

适用于 scope 相关 mutation：

- `caption_scope_year/city/object`
- `summary_scope_year/city/object`

`user_reply` 从 GT 的 `query_filters` 中恢复：

- `city`
- `block`
- `start_year`
- `end_year`

#### `logic_correction`

适用于：

- `series_metric_swap`
- `table_metric_swap`

也就是 `st_header` family。

形式：

```json
{
  "expected_action": "logic_correction",
  "expected_request": {
    "required_fields": ["metrics", "group_by"]
  },
  "user_reply": {
    "metrics": [...],
    "group_by": "..."
  }
}
```

#### `page_intent_correction`

当前仅在：

- `targets == {"st.body", "summary", "title"}`

时触发，也就是现在的 `three_element`。

形式：

```json
{
  "expected_action": "page_intent_correction",
  "expected_request": {
    "required_fields": ["scope", "topic"]
  },
  "user_reply": {
    "page_intent": {
      "scope": {...},
      "topic": "..."
    }
  }
}
```


## 5. `logic_correction`：从硬编码改为 GT 驱动

这是这轮最关键的修正之一。

### 5.1 之前的问题

此前 `logic_correction` 采用模板级硬编码：

- 表格模板返回固定的 `trade_counts / avg_unit_price / dim_area`
- 其他模板默认返回 `Supply Count / Sales Count / area_range`

这会导致：

- feedback reply 不是从当前 GT 真值恢复
- 某些 `st_header` case 的逻辑回复不可信

### 5.2 现在的做法

现在已经改成“尽量直接从 GT 真值恢复正确修正逻辑”。

#### chart 类型 `st_header`

直接从 GT element 的：

- `args.metrics`
- `args.dimensions`

恢复：

- `metrics`
- `group_by`

例如：

```json
{
  "expected_action": "logic_correction",
  "expected_request": {
    "required_fields": ["metrics", "group_by"]
  },
  "user_reply": {
    "metrics": [
      {
        "name": "Supply Count",
        "meaning": "供应套数",
        "agg_func": "count",
        "source_col": "supply_sets",
        "filter_condition": {"supply_sets": 1}
      },
      {
        "name": "Sales Count",
        "meaning": "成交套数",
        "agg_func": "count",
        "source_col": "trade_sets",
        "filter_condition": {"trade_sets": 1}
      }
    ],
    "group_by": "area_range"
  }
}
```

#### table 类型 `st_header`

从 GT table 对应的 CSV 中恢复：

- `metric` 列 -> metrics
- 列名结构 -> `group_by`

例如年份列会被推成：

- `group_by = year`

当前 table 逻辑已经比之前的硬编码强很多，但仍然保留少量启发式：

- 含 `price` -> `mean`
- 含 `area` -> `sum`
- 其他默认 `count`

这部分后续仍可继续精炼。


## 6. feedback 生成性能：为什么慢，以及已经做的优化

### 6.1 为什么慢

feedback 生成不查数据库，但仍然慢，主要原因是：

- 要处理的 corruption case 数很多
- 当前 `manifest/corruptions.jsonl` 约有 **38573** 条
- 每条都需要：
  - 读 manifest record
  - 读 GT YAML
  - 某些还要读 GT CSV
  - 写 `feedback_episode.json`
- 数据集位于 `/mnt/g/...`，属于 WSL 挂载 Windows 盘
  - 大量小文件 IO / 目录遍历会明显变慢

### 6.2 已做优化

#### 缓存

已对这些函数加缓存：

- `load_yaml(...)`
- `load_csv_rows(...)`

减少同一 GT 被多个 corruption case 重复读盘。

#### 进度条

已加：

- `cleanup` 进度条
- `feedback` 进度条

避免“看起来像卡住”。

#### cleanup 改为 manifest-driven

之前 cleanup 是全盘 `glob`：

```text
split/*/s_*/injected/*/feedback_episode.json
```

在 `/mnt/g` 上很慢。

现在改成：

1. 先读 `corruptions.jsonl`
2. 按 manifest 定位每条 case
3. 删除对应 case 的旧 `feedback_episode.json`

#### 多线程

已将 cleanup 和 feedback 写入都改为线程池并发执行。

新增参数：

- `--workers`

默认 shell 脚本中为：

- `--workers 32`

对应脚本：

- `scripts/generate_feedback_benchmark.sh`


## 7. 数据集拆分：按 template 做 8:1:1 分层采样

### 7.1 新增脚本

新增：

- `scripts/split_benchmark_dataset.py`

用于把当前全部在 `split/test` 下的数据集，重新拆成：

- `train`
- `val`
- `test`

### 7.2 拆分原则

当前按：

- `template_id`

做分层采样，然后按比例：

- `0.8 / 0.1 / 0.1`

分配 sample。

这意味着：

- 每个 template 的 slide case 数量尽量保持一致比例
- 然后 corruption / feedback 跟随 sample 一起搬迁

### 7.3 最终结果

GT sample：

- `train`: **4436**
- `val`: **560**
- `test`: **560**

对 139 条的 template，典型分法：

- `111 / 14 / 14`

对 137 条的 template（两个 T01 模板）：

- `109 / 14 / 14`

corruption：

- `train`: **30811**
- `val`: **3882**
- `test`: **3880**

### 7.4 已同步的内容

拆分时已同步更新：

- `split/train|val|test/s_<sample_id>/...` 目录
- `manifest/samples.jsonl`
- `manifest/corruptions.jsonl`

因此：

- GT
- injected
- `corruption.json`
- `feedback_episode.json`

都会跟着 case 一起移动。


## 8. 当前还需要继续讨论 / 未完全定稿的点

### 8.1 `page_intent_correction`

这是目前最不稳定的一块。

当前只是临时规则：

- 仅当 `targets == {"st.body", "summary", "title"}` 时触发

后面需要重新明确：

- 什么情况下才算 page intent 错误
- 哪些组合错误应该升级为 page intent 层面的交互
- page intent 的用户回复 schema 是否继续使用：
  - `scope`
  - `topic`

### 8.2 table 类型 `logic_correction`

虽然已经不再是模板硬编码，但表格类仍有启发式成分：

- `price -> mean`
- `area -> sum`
- 其他 `count`

后面可以继续讨论：

- 是否要从更稳定的 GT/模板真值中恢复表格 header semantics
- 是否需要单独定义 table header 的 gold logic schema

### 8.3 方法讨论即将开始

到目前为止，我们主要完成的是：

- benchmark 工程结构整理
- 数据集格式收敛
- feedback 文件结构收敛
- 训练/验证/测试集拆分

下一步将切换到：

- benchmark 方法设计
- phase 1 / phase 2 / phase 3 的接口与评测方式
- agent 全程参与设定下的正式 protocol

