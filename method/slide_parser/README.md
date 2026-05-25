# Slide Parser

Phase 1.1 parser for feedback-aware PPT correction.

The parser follows a two-step design:

1. `python-pptx` extracts editable PPT elements from the source `.pptx`.
2. A VLM labels the role of each parser-provided element using the rendered slide image.

The VLM does not detect new elements or return bounding boxes. It only assigns one role to each element id from:

```text
slide-title
body-text
caption
chart-bar
chart-line
chart-pie
table
```

The final `observed_slide` is shaped like `template_slide`:

```json
{
  "slide_size": {"width": 19.05, "height": 14.29},
  "elements": [
    {
      "id": "1",
      "type": "textBox",
      "role": "slide-title",
      "text": "...",
      "layout": {"x": 0.5, "y": 1.0, "width": 18.0, "height": 1.1}
    },
    {
      "id": "4",
      "type": "chart",
      "role": "chart-bar",
      "layout": {"x": 3.7, "y": 4.85, "width": 12.2, "height": 7.25}
    }
  ]
}
```

Chart/table data is not extracted or stored in Phase 1.1. Later stages should use a separate data extraction tool if they need chart/table values.

Shared model/client helpers live under `method/utils`; this module does not depend on the legacy `agent/` package.
