from __future__ import annotations

import unittest
from pathlib import Path

import yaml

TEMPLATE_DEFINITIONS = Path("config/templates/template_definitions.yaml")


class TemplateDataKeyConsistencyTest(unittest.TestCase):
    def test_template_theme_and_data_key_family_are_consistent(self) -> None:
        templates = yaml.safe_load(TEMPLATE_DEFINITIONS.read_text(encoding="utf-8"))

        for template in templates:
            uid = template["uid"]
            theme = str(template["theme_key"]).lower()
            data_keys = [str(value) for value in template["data_keys"].values()]
            has_resale_key = any(key.startswith("resale_") for key in data_keys)
            has_newhouse_key = any(key.startswith("newhouse_") for key in data_keys)

            with self.subTest(template=uid):
                self.assertFalse(
                    has_resale_key and has_newhouse_key,
                    f"{uid} mixes resale and new-house data keys: {data_keys}",
                )
                if "resale" in theme:
                    self.assertTrue(
                        has_resale_key,
                        f"{uid} has resale theme but no resale data key: {data_keys}",
                    )
                    self.assertFalse(
                        has_newhouse_key,
                        f"{uid} has resale theme but new-house data key: {data_keys}",
                    )
                if "new-house" in theme or "new house" in theme:
                    self.assertFalse(
                        has_resale_key,
                        f"{uid} has new-house theme but resale data key: {data_keys}",
                    )


if __name__ == "__main__":
    unittest.main()
