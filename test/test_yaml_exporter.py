from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.context_builder import PresentationContext
from core.schemas import BinningRule, MetricRule, TableAnalysisConfig
from engine.yaml_exporter import YAMLExporter


class YAMLExporterTest(unittest.TestCase):
    def test_slide_filters_keep_filter_conditions_out_of_select_columns(self) -> None:
        context = PresentationContext()
        for key, value in {
            "_table_name": "Guangzhou_new_house",
            "Geo_City_Name": "Guangzhou",
            "Geo_Block_Name": "Lianhuashan",
            "Temporal_Start_Year": "2020",
            "Temporal_End_Year": "2024",
        }.items():
            context.add_variable(key, value)
        context.add_config(
            "annual_supply_data",
            TableAnalysisConfig(
                table_type="field-constraint",
                dimensions=[
                    BinningRule(
                        source_col="date_code",
                        target_col="year",
                        method="period",
                        time_granularity="year",
                    )
                ],
                metrics=[
                    MetricRule(
                        name="supply_area",
                        source_col="dim_area",
                        agg_func="sum",
                        filter_condition={"supply_sets": 1},
                    ),
                    MetricRule(
                        name="deal_area",
                        source_col="dim_area",
                        agg_func="sum",
                        filter_condition={"trade_sets": 1},
                    ),
                ],
            ),
        )
        template_meta = SimpleNamespace(
            uid="T04_Supply_Transaction_Area_Bar",
            function_key=["Supply-Transaction Area"],
            data_keys={"chart_main": "annual_supply_data"},
            function_params={},
        )

        slide_filters = YAMLExporter._build_slide_filters(template_meta, context)

        self.assertEqual(
            slide_filters[0]["select_columns"],
            ["date_code", "dim_area"],
        )
        self.assertNotIn("supply_sets", slide_filters[0]["sql_query"][0])
        self.assertNotIn("trade_sets", slide_filters[0]["sql_query"][0])


if __name__ == "__main__":
    unittest.main()
