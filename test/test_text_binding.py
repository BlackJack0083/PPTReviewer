from __future__ import annotations

import unittest
from types import SimpleNamespace

from core import LayoutType, PresentationContext, TemplateMeta
from core.schemas import ElementType, TextSlotDefinition
from engine import builder
from engine.builder import SlideConfigBuilder


class TextBindingTest(unittest.TestCase):
    def test_summary_text_binding_keeps_used_scope_value_and_claim_slots(self) -> None:
        context = PresentationContext()
        context.add_variable("Geo_City_Name", "Beijing")
        context.add_variable("Geo_Block_Name", "Miyun District")
        context.add_variable("Temporal_Start_Year", "2020")
        context.add_variable("Temporal_End_Year", "2024")
        context.add_variable("Metric_Volume_Total", "1,914")
        context.add_variable("Trend_Trajectory_Type", "increased")
        context.add_variable("Text_Market_Balance_Assessment", "balanced")
        original = builder.resource_manager.get_summary_template
        builder.resource_manager.get_summary_template = lambda theme, func, variant_idx: (
            "{{ Geo_City_Name }} {{ Geo_Block_Name }} "
            "{{ Temporal_Start_Year }}-{{ Temporal_End_Year }} "
            "{{ Metric_Volume_Total }} {{ Trend_Trajectory_Type }} "
            "{{ Text_Market_Balance_Assessment }}"
        )
        try:
            binding = SlideConfigBuilder()._build_text_binding(
                TextSlotDefinition(
                    part="summary",
                    role="body-text",
                    x=0,
                    y=0,
                    width=10,
                    height=1,
                ),
                _template_meta(),
                context,
            )
        finally:
            builder.resource_manager.get_summary_template = original

        self.assertEqual(binding["kind"], "summary")
        self.assertNotIn("part", binding["render"])
        self.assertEqual(binding["slots"]["Geo_City_Name"]["category"], "scope")
        self.assertEqual(binding["slots"]["Geo_City_Name"]["field"], "city")
        self.assertEqual(binding["slots"]["Metric_Volume_Total"]["category"], "value")
        self.assertEqual(binding["slots"]["Metric_Volume_Total"]["value_type"], "number")
        self.assertEqual(binding["slots"]["Trend_Trajectory_Type"]["category"], "claim")
        self.assertEqual(
            binding["slots"]["Text_Market_Balance_Assessment"]["category"],
            "claim",
        )

    def test_caption_text_binding_adds_presentation_type_claim(self) -> None:
        context = PresentationContext()
        context.add_variable("Geo_City_Name", "Beijing")
        context.add_variable("Geo_Block_Name", "Miyun District")
        context.add_variable("Temporal_Start_Year", "2020")
        context.add_variable("Temporal_End_Year", "2024")
        original_template = builder.resource_manager.get_caption_template
        original_layout = builder.layout_manager.get_layout_slots
        builder.resource_manager.get_caption_template = lambda theme, func: (
            "{{ Geo_City_Name }} {{ Geo_Block_Name }} "
            "{{ Temporal_Start_Year }}-{{ Temporal_End_Year }}"
        )
        builder.layout_manager.get_layout_slots = lambda layout_type: [
            SimpleNamespace(type=ElementType.CHART, role="chart-bar")
        ]
        try:
            binding = SlideConfigBuilder()._build_text_binding(
                TextSlotDefinition(
                    part="caption",
                    role="caption",
                    function_index=0,
                    x=0,
                    y=0,
                    width=10,
                    height=1,
                ),
                _template_meta(),
                context,
            )
        finally:
            builder.resource_manager.get_caption_template = original_template
            builder.layout_manager.get_layout_slots = original_layout

        self.assertEqual(binding["kind"], "caption")
        self.assertNotIn("part", binding["render"])
        self.assertEqual(binding["render"]["view_label"], "Bar chart")
        self.assertEqual(
            binding["slots"]["Chart_View_Label"],
            {
                "category": "claim",
                "field": "presentation_type",
                "value": "Bar chart",
                "value_type": "string",
            },
        )


def _template_meta() -> TemplateMeta:
    return TemplateMeta(
        uid="T_test",
        layout_type=LayoutType.SINGLE_COLUMN_BAR,
        style_config_id="default",
        theme_key="Theme",
        function_key=["Function"],
        summary_item=0,
        data_keys={"chart_main": "main"},
    )
