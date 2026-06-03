from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from method.agents import SlideParserAgent, SlideReviewInput

PRESENTATION_LABEL_RE = re.compile(r"\((bar chart|line chart|pie chart|table)\)\s*$", re.I)
TREND_RE = re.compile(
    r"\b(increase|increased|decrease|decreased|growth|decline|upward|downward)\b",
    re.I,
)


class BatchRoleClient:
    """测试用 role client，根据 PPTX 元素文本和 shape 类型生成稳定 role。"""

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path,
        response_format: str,
    ) -> str:
        del system_prompt, image_path, response_format
        payload = json.loads(user_prompt.split("Input elements:\n", 1)[1])
        elements = list(payload.get("elements", []))
        roles: dict[str, str] = {}
        text_elements = [element for element in elements if element.get("type") == "textBox"]

        for element in elements:
            if element.get("type") == "textBox":
                continue
            shape_kind = str(element.get("shape_kind") or element.get("type") or "")
            roles[str(element["id"])] = shape_kind

        caption_ids = set()
        summary_ids = set()
        for element in text_elements:
            text = str(element.get("text", "")).strip()
            element_id = str(element["id"])
            if PRESENTATION_LABEL_RE.search(text) or "analysis" in text.lower():
                caption_ids.add(element_id)
            elif TREND_RE.search(text) or any(char.isdigit() for char in text):
                summary_ids.add(element_id)

        title_candidates = [
            element
            for element in text_elements
            if str(element["id"]) not in caption_ids | summary_ids
        ]
        if not title_candidates:
            title_candidates = list(text_elements)
        title_candidates.sort(
            key=lambda element: (
                element.get("layout", {}).get("y", 999.0),
                len(str(element.get("text", ""))),
            )
        )
        title_id = str(title_candidates[0]["id"]) if title_candidates else ""

        for element in text_elements:
            element_id = str(element["id"])
            if element_id == title_id:
                roles[element_id] = "title"
            elif element_id in caption_ids:
                roles[element_id] = "caption"
            else:
                roles[element_id] = "summary"

        return json.dumps(
            {
                "roles": [
                    {"id": element_id, "role": role}
                    for element_id, role in sorted(roles.items(), key=lambda item: int(item[0]))
                ]
            },
            ensure_ascii=False,
        )


class SlideParserBatchTest(unittest.TestCase):
    def test_parser_runs_on_ten_real_injected_ppts(self) -> None:
        root = Path("output/benchmark/dataset_v2/split/test")
        cases = [
            pptx_path.parent
            for pptx_path in sorted(root.glob("s_*/injected/*/slide.pptx"))
            if (pptx_path.parent / "slide.png").exists()
        ][:10]
        self.assertEqual(len(cases), 10, f"Expected 10 parser cases under {root}.")

        agent = SlideParserAgent(client=BatchRoleClient())
        for case_dir in cases:
            with self.subTest(case=str(case_dir)):
                result = agent.run(
                    SlideReviewInput(
                        pptx_path=case_dir / "slide.pptx",
                        image_path=case_dir / "slide.png",
                    )
                )

                observed_slide = result["observed_slide"]
                representation = result["ppt_representation"]
                self.assertTrue(observed_slide["elements"])
                self.assertTrue(all("role" in element for element in observed_slide["elements"]))
                self.assertIn("title", representation)
                self.assertIn("summary", representation)
                self.assertTrue(representation["structured_tables"])

                for table in representation["structured_tables"]:
                    self.assertIsNotNone(table["caption"])
                    self.assertTrue(table["header"])
                    body = table["body"]
                    data_path = Path(body["data_path"])
                    self.assertTrue(data_path.exists(), data_path)
                    self.assertEqual(data_path.parent, case_dir)
                    self.assertGreater(data_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
