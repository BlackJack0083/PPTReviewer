from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from method.slide_parser import extract_pptx_elements, parse_observed_slide


class SequentialRoleLabeler:
    def label_roles(
        self,
        *,
        image_path: Path,
        observed_slide: dict[str, Any],
    ) -> list[dict[str, str]]:
        roles = ["slide-title", "body-text", "caption", "chart-bar"]
        return [
            {"id": str(element["id"]), "role": roles[idx]}
            for idx, element in enumerate(observed_slide["elements"])
        ]


class TestSlideParser(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_dir = Path(
            "output/benchmark/dataset_v2/split/test/s_00163f7ed3ede3ed/gt"
        )
        self.pptx_path = self.sample_dir / "slide.pptx"
        self.image_path = self.sample_dir / "slide.png"

    def test_extract_pptx_elements_keeps_template_slide_shape_without_roles(self):
        observed_slide = extract_pptx_elements(self.pptx_path)

        self.assertIn("slide_size", observed_slide)
        self.assertEqual(len(observed_slide["elements"]), 4)
        self.assertEqual(
            [element["type"] for element in observed_slide["elements"]],
            ["textBox", "textBox", "textBox", "chart"],
        )
        self.assertTrue(all("role" not in element for element in observed_slide["elements"]))
        self.assertNotIn("data", observed_slide["elements"][-1])

    def test_parse_observed_slide_merges_vlm_roles_without_data_payload(self):
        parsed = parse_observed_slide(
            pptx_path=self.pptx_path,
            image_path=self.image_path,
            role_labeler=SequentialRoleLabeler(),
        )

        elements = parsed.observed_slide["elements"]
        self.assertEqual(
            [element["role"] for element in elements],
            ["slide-title", "body-text", "caption", "chart-bar"],
        )
        self.assertNotIn("data", elements[-1])
        self.assertNotIn("_shape_kind", elements[-1])


if __name__ == "__main__":
    unittest.main()
