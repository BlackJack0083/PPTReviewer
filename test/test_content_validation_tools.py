from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from core.transformers import StatTransformer
from method.tools.content_validation import (
    compare_display_dataframes,
    execute_table_state,
    modify_chart,
    write_content_artifacts,
)


class FakeDAO:
    def fetch_raw_data(self, query_filter, columns):
        del query_filter, columns
        return pd.DataFrame(
            {
                "date_code": ["2020-01-01", "2021-01-01", "2021-02-01"],
                "trade_sets": [1, 1, 1],
            }
        )


class ContentValidationToolsTest(unittest.TestCase):
    def test_compare_display_dataframes_allows_rounding_noise(self) -> None:
        visible = pd.DataFrame({"year": [2020], "value": [100.0]})
        expected = pd.DataFrame({"year": [2020], "value": [100.4]})

        result = compare_display_dataframes(visible, expected)

        self.assertEqual(result["status"], "equal")

    def test_execute_table_state_runs_extracted_state(self) -> None:
        expected = execute_table_state(
            _analysis_state(data_path="visible.csv")["tables"][0],
            dao=FakeDAO(),
            transformer=StatTransformer(),
        )

        self.assertEqual(list(expected.columns), ["year", "trade_counts"])
        self.assertEqual(expected["trade_counts"].tolist(), [1, 2])

    def test_write_content_artifacts_emits_yaml_and_repaired_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected_path = root / "expected.csv"
            visible_path = root / "visible.csv"
            pd.DataFrame({"year": [2020], "trade_counts": [2]}).to_csv(
                expected_path,
                index=False,
            )
            pd.DataFrame({"year": [2020], "trade_counts": [1]}).to_csv(
                visible_path,
                index=False,
            )

            artifacts = write_content_artifacts(
                analysis_state=_analysis_state(data_path=str(visible_path)),
                ppt_representation=_ppt_representation(str(visible_path)),
                table_records=[
                    {
                        "table_index": 0,
                        "expected_data_path": str(expected_path),
                    }
                ],
                update_log=[
                    {
                        **modify_chart(
                            element_id="4",
                            data_path=str(expected_path),
                        ),
                        "table_index": 0,
                        "field": "table_values",
                    }
                ],
                artifact_dir=root / "review_artifacts",
            )

            repaired_yaml = yaml.safe_load(
                Path(artifacts["yaml_path"]).read_text(encoding="utf-8")
            )
            repaired_data_path = Path(repaired_yaml["tables"][0]["body"]["data_path"])
            self.assertTrue(repaired_data_path.exists())
            self.assertEqual(
                pd.read_csv(repaired_data_path)["trade_counts"].tolist(),
                [2],
            )


def _analysis_state(data_path: str) -> dict[str, Any]:
    return {
        "title": "Example",
        "summary": "Example summary",
        "tables": [
            {
                "caption": "Example caption",
                "data_path": data_path,
                "data_source": {
                    "connection": {"table": "beijing_new_house"},
                    "select_columns": ["date_code", "trade_sets"],
                    "filters": {
                        "city": "Beijing",
                        "block": "Liangxiang",
                        "start_date": "2020-01-01",
                        "end_date": "2021-12-31",
                    },
                },
                "calculation_logic": {
                    "table_type": "field-constraint",
                    "dimensions": [
                        {
                            "source_col": "date_code",
                            "target_col": "year",
                            "method": "period",
                            "time_granularity": "year",
                        }
                    ],
                    "metrics": [
                        {
                            "name": "trade_counts",
                            "source_col": "trade_sets",
                            "agg_func": "count",
                            "filter_condition": {"trade_sets": 1},
                        }
                    ],
                    "crosstab_row": None,
                    "crosstab_col": None,
                },
            }
        ],
    }


def _ppt_representation(data_path: str) -> dict[str, Any]:
    return {
        "title": {"text": "Example"},
        "summary": {"text": "Example summary"},
        "structured_tables": [
            {
                "caption": {"text": "Example caption"},
                "body": {"type": "chart-bar", "data_path": data_path},
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
