"""Content validation 的非 agent-tool 辅助函数。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml


def write_content_artifacts(
    *,
    analysis_state: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    """写出 repaired semantic YAML 和确认过的 table CSV 更新。

    Args:
        analysis_state: content validation 后的最终 analysis state。
        artifact_dir: repaired YAML/CSV 文件写入目录。

    Returns:
        repaired artifacts 路径。由于当前层还没有实现 PPTX 重写，
        `pptx_path` 目前为 `None`。
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    data_paths = _write_table_data_files(
        analysis_state=analysis_state,
        artifact_dir=artifact_dir,
    )
    yaml_payload = _build_repaired_yaml(
        analysis_state=analysis_state,
        data_paths=data_paths,
    )
    yaml_path = artifact_dir / "repaired_slide.yaml"
    yaml_path.write_text(
        yaml.safe_dump(yaml_payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return {
        "yaml_path": str(yaml_path),
        "data_paths": {str(key): value for key, value in data_paths.items()},
        "pptx_path": None,
    }


def _write_table_data_files(
    *,
    analysis_state: dict[str, Any],
    artifact_dir: Path,
) -> dict[int, str]:
    data_paths: dict[int, str] = {}
    for table_index, table_state in enumerate(analysis_state["tables"]):
        source_path = Path(table_state["data_path"])
        target_path = artifact_dir / f"table_{table_index}_repaired.csv"
        if source_path.resolve() != target_path.resolve():
            shutil.copyfile(source_path, target_path)
        data_paths[table_index] = str(target_path)
    return data_paths


def _build_repaired_yaml(
    *,
    analysis_state: dict[str, Any],
    data_paths: dict[int, str],
) -> dict[str, Any]:
    tables = []
    for table_index, table_state in enumerate(analysis_state.get("tables", [])):
        body = table_state.get("body") or {}
        tables.append(
            {
                "caption": table_state["caption"]["text"],
                "body": {
                    "presentation_type": body.get("type", ""),
                    "data_path": data_paths.get(
                        table_index,
                        table_state.get("data_path", ""),
                    ),
                },
                "data_source": table_state["caption"]["data_source"],
                "calculation_logic": table_state.get("calculation_logic", {}),
            }
        )
    return {
        "title": analysis_state["title"]["text"],
        "summary": analysis_state["summary"]["text"],
        "tables": tables,
    }
