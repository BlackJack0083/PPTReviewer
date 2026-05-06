from __future__ import annotations

from pathlib import Path

import pandas as pd

DATAFRAME_INDEX_COLUMN = "__index__"


def write_dataframe_csv(df: pd.DataFrame, path: str | Path) -> None:
    """Persist a rendered ST dataframe with its index preserved."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=True, index_label=DATAFRAME_INDEX_COLUMN)


def read_dataframe_csv(path: str | Path) -> pd.DataFrame:
    """Load an ST dataframe written by write_dataframe_csv."""
    path = Path(path)
    df = pd.read_csv(path)
    if DATAFRAME_INDEX_COLUMN not in df.columns:
        raise ValueError(f"CSV is missing required index column: {path}")
    result = df.set_index(DATAFRAME_INDEX_COLUMN)
    result.index.name = None
    return result


def data_elements(yaml_data: dict) -> list[dict]:
    """Return chart/table elements in render order."""
    elements = yaml_data.get("template_slide", {}).get("elements", [])
    return [
        element
        for element in elements
        if isinstance(element, dict) and element.get("type") in {"chart", "table"}
    ]


def resolve_element_data_path(yaml_path: str | Path, element: dict) -> Path:
    """Resolve a chart/table element's relative data path from a slide YAML path."""
    data_path = element.get("data")
    if not isinstance(data_path, str) or not data_path.strip():
        element_id = element.get("id", "<unknown>")
        raise ValueError(f"Data element {element_id} is missing required 'data' path")
    path = Path(data_path)
    if path.is_absolute():
        raise ValueError(f"Data path must be relative to slide.yaml: {data_path}")
    return (Path(yaml_path).parent / path).resolve()
