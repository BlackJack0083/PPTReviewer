from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import yaml

from agent.tools_local import LocalDataTools


class TestLocalDataToolsTextEdit(TestCase):
    def setUp(self) -> None:
        # These methods do not depend on resource loading, so we can bypass __init__.
        self.tools = LocalDataTools.__new__(LocalDataTools)
        self.tools._runtime_context = type("RuntimeContext", (), {})()

    def test_list_editable_textboxes_only_returns_textboxes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            yaml_path = Path(temp_dir) / "slide.yaml"
            yaml_path.write_text(
                yaml.safe_dump(
                    {
                        "template_slide": {
                            "elements": [
                                {"id": "1", "type": "textBox", "role": "slide-title", "text": "Title"},
                                {"id": "2", "type": "chart", "role": "chart-main"},
                                {"id": "3", "type": "textBox", "role": "body-text", "text": "Summary"},
                            ]
                        }
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            editable_shapes = self.tools.list_editable_textboxes(yaml_path)

            self.assertEqual(
                editable_shapes,
                [
                    {"shape_id": "1", "role": "slide-title", "text": "Title"},
                    {"shape_id": "3", "role": "body-text", "text": "Summary"},
                ],
            )

    def test_apply_textbox_edit_updates_yaml_and_rebuilds_ppt(self) -> None:
        with TemporaryDirectory() as temp_dir:
            yaml_path = Path(temp_dir) / "slide.yaml"
            yaml_path.write_text(
                yaml.safe_dump(
                    {
                        "template_slide": {
                            "elements": [
                                {"id": "1", "type": "textBox", "role": "slide-title", "text": "Old Title"},
                                {"id": "2", "type": "textBox", "role": "body-text", "text": "Old Summary"},
                            ]
                        }
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            with patch("engine.yaml_importer.rebuild_ppt_from_yaml") as mock_rebuild:
                success = self.tools.apply_textbox_edit(
                    shape_id="2",
                    new_text="New Summary",
                    yaml_path=yaml_path,
                )

            output_yaml = yaml_path.with_name("slide-text_edited.yaml")
            updated_data = yaml.safe_load(output_yaml.read_text(encoding="utf-8"))
            textboxes = updated_data["template_slide"]["elements"]

            self.assertTrue(success)
            self.assertEqual(textboxes[0]["text"], "Old Title")
            self.assertEqual(textboxes[1]["text"], "New Summary")
            mock_rebuild.assert_called_once_with(
                str(output_yaml),
                str(output_yaml.with_suffix(".pptx")),
            )

    def test_apply_textbox_edit_can_use_runtime_yaml_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            yaml_path = Path(temp_dir) / "slide.yaml"
            yaml_path.write_text(
                yaml.safe_dump(
                    {
                        "template_slide": {
                            "elements": [
                                {"id": "1", "type": "textBox", "role": "body-text", "text": "Old Summary"},
                            ]
                        }
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            self.tools.set_runtime_yaml_path(yaml_path)
            with patch("engine.yaml_importer.rebuild_ppt_from_yaml"):
                success = self.tools.apply_textbox_edit(
                    shape_id="1",
                    new_text="Runtime Summary",
                )
            self.tools.clear_runtime_yaml_path()

            output_yaml = yaml_path.with_name("slide-text_edited.yaml")
            updated_data = yaml.safe_load(output_yaml.read_text(encoding="utf-8"))
            self.assertTrue(success)
            self.assertEqual(
                updated_data["template_slide"]["elements"][0]["text"],
                "Runtime Summary",
            )
