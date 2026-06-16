from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import ground_truth_generation as gt


class GroundTruthGenerationTaskTest(unittest.TestCase):
    def test_table_name_for_template_follows_template_data_family(self) -> None:
        templates = {
            "new_template": SimpleNamespace(data_keys={"chart_main": "newhouse_area_dist_data"}),
            "resale_template": SimpleNamespace(data_keys={"chart_main": "resale_area_dist_data"}),
        }

        with patch.object(gt.resource_manager, "get_template", side_effect=templates.get):
            self.assertEqual(
                gt.table_name_for_template("beijing", "new_template"),
                "Beijing_new_house",
            )
            self.assertEqual(
                gt.table_name_for_template("guangzhou", "resale_template"),
                "Guangzhou_resale_house",
            )
            self.assertEqual(
                gt.table_name_for_template("shenzhen", "resale_template"),
                "Shenzhen_resale_house",
            )
            self.assertIsNone(gt.table_name_for_template("beijing", "resale_template"))

    def test_build_tasks_skips_city_without_required_resale_table(self) -> None:
        templates = {
            "new_template": SimpleNamespace(data_keys={"chart_main": "newhouse_area_dist_data"}),
            "resale_template": SimpleNamespace(data_keys={"chart_main": "resale_area_dist_data"}),
        }

        with (
            patch.object(gt.resource_manager, "get_template", side_effect=templates.get),
            patch.object(gt, "load_blocks_from_csv", return_value=["Block A"]),
        ):
            tasks = gt.build_tasks(
                city_keys=["beijing", "guangzhou"],
                templates=["new_template", "resale_template"],
                max_blocks_per_city=None,
                max_samples=None,
            )

        self.assertEqual(
            [
                (task["city_key"], task["template_id"], task["table_name"])
                for task in tasks
            ],
            [
                ("beijing", "new_template", "Beijing_new_house"),
                ("guangzhou", "new_template", "Guangzhou_new_house"),
                ("guangzhou", "resale_template", "Guangzhou_resale_house"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
