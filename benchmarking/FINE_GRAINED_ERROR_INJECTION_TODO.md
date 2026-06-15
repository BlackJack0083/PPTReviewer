# Fine-Grained Error Injection Notes

当前 benchmark 错误构造只保留三类研究问题：`scope`、`value`、`claim`。

## Error Families

### Scope

Scope 错误对应 slide-level data source slot，必须记录：

- `error_type: scope_error`
- `field`: `city`、`block` 或 `time_range`
- `scope_error_type`: `missing`、`error`、`unmatch` 或 `conflict`

其中 `time_range` 不生成 `unmatch`，因为时间范围没有 city/block 那样的组合匹配语义。

### Value

Value 错误对应可见数值和 ground-truth 计算结果不一致，不再拆 `field`。

当前 mutation：

- `value_table_cell`
- `value_summary_slot`

### Claim

Claim 错误对应非数值事实性表述错误，不再拆 `field`。

当前 mutation：

- `claim_caption_presentation`
- `claim_summary_slot`

## Feedback Episode

`feedback_episode.json` 使用统一列表：

```json
{
  "feedback_items": []
}
```

Scope feedback 按 `field + scope_error_type` 匹配：

```json
{
  "request_type": "data_source_slot_clarification",
  "error_type": "scope_error",
  "field": "block",
  "scope_error_type": "unmatch",
  "response": "Please use block=Liangxiang."
}
```

Content feedback 按 `error_type + target` 匹配：

```json
{
  "request_type": "content_update_confirmation",
  "error_type": "value_error",
  "target": "st.body",
  "response": "Yes, please apply the proposed update."
}
```

## Implementation Rule

错误注入优先使用 GT YAML 的 `text_binding.slots` 和外置 CSV 数据，不通过正则回写最终文本。文本 mutation 先修改 slot，再按原模板重新渲染。
