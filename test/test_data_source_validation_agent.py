from __future__ import annotations

import json
import unittest
from typing import Any

from langchain_core.messages import AIMessage

from method.agents.client import ClientAgent
from method.agents.data_source_validation import (
    DataSourceValidationAgent,
    apply_state_patch,
)


class FakeGraph:
    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_payload = json.loads(payload["messages"][0].content)
        slots = user_payload["slots"]
        table_index = user_payload["table_index"]

        if not slots["city"]:
            return _message(
                {
                    "status": "needs_client",
                    "table_index": table_index,
                    "slot_check_result": [
                        {"slot": "", "slot_type": "city", "label": "Missing"}
                    ],
                    "client_request": {
                        "request_type": "data_source_slot_clarification",
                        "table_index": table_index,
                        "fields": ["city"],
                        "description": "The city slot is missing.",
                    },
                }
            )

        if slots["city"] == "Beijing" and slots["block"] == "Nanshan CBD":
            return _message(
                {
                    "status": "needs_client",
                    "table_index": table_index,
                    "slot_check_result": [
                        {"slot": "Beijing", "slot_type": "city", "label": "Unmatch"},
                        {
                            "slot": "Nanshan CBD",
                            "slot_type": "block",
                            "label": "Unmatch",
                        },
                    ],
                    "client_request": {
                        "request_type": "data_source_slot_clarification",
                        "table_index": table_index,
                        "fields": ["city", "block"],
                        "description": "The city and block slots do not match.",
                    },
                }
            )

        return _message(
            {
                "status": "pass",
                "table_index": table_index,
                "slot_check_result": [
                    {"slot": slots["table"], "slot_type": "table", "label": "Correct"},
                    {"slot": slots["city"], "slot_type": "city", "label": "Correct"},
                    {"slot": slots["block"], "slot_type": "block", "label": "Correct"},
                    {
                        "slot": f"{slots['start_date']}~{slots['end_date']}",
                        "slot_type": "time_range",
                        "label": "Correct",
                    },
                ],
                "client_request": None,
            }
        )


class FakeClient:
    def respond(self, request: dict[str, Any]) -> dict[str, Any]:
        fields = set(request["fields"])
        if fields == {"city"}:
            return {
                "matched": True,
                "state_patch": {
                    "final_data_source": {"filters": {"city": "Beijing"}}
                },
            }
        if {"city", "block"}.issubset(fields):
            return {
                "matched": True,
                "state_patch": {
                    "final_data_source": {
                        "connection": {"table": "shenzhen_new_house"},
                        "filters": {
                            "city": "Shenzhen",
                            "block": "Nanshan CBD",
                        },
                    }
                },
            }
        return {"matched": False, "state_patch": {}}


class DataSourceValidationAgentTest(unittest.TestCase):
    def test_apply_state_patch_deep_merges_table_state(self) -> None:
        state = {
            "final_data_source": {
                "connection": {"table": "beijing_new_house"},
                "filters": {
                    "city": "",
                    "block": "Liangxiang",
                    "start_date": "2020-01-01",
                    "end_date": "2024-12-31",
                },
            }
        }
        apply_state_patch(
            state,
            {
                "final_data_source": {"filters": {"city": "Beijing"}}
            },
        )
        self.assertEqual(state["final_data_source"]["filters"]["city"], "Beijing")
        self.assertEqual(state["final_data_source"]["filters"]["block"], "Liangxiang")

    def test_run_with_client_patches_missing_slot_and_reruns(self) -> None:
        state = _analysis_state(city="", block="Liangxiang")
        agent = DataSourceValidationAgent(graph=FakeGraph())
        result = agent.run_with_client(state, FakeClient())

        state = result["analysis_state"]
        self.assertEqual(state["final_data_source"]["filters"]["city"], "Beijing")
        self.assertEqual(state["data_source_validation"]["status"], "pass")
        self.assertEqual(len(result["validation_log"]), 2)

    def test_run_with_client_supports_unmatch_patch_and_rerun(self) -> None:
        state = _analysis_state(city="Beijing", block="Nanshan CBD")
        agent = DataSourceValidationAgent(graph=FakeGraph())
        result = agent.run_with_client(state, FakeClient())

        data_source = result["analysis_state"]["final_data_source"]
        self.assertEqual(data_source["connection"]["table"], "shenzhen_new_house")
        self.assertEqual(data_source["filters"]["city"], "Shenzhen")
        self.assertEqual(data_source["filters"]["block"], "Nanshan CBD")
        self.assertEqual(result["analysis_state"]["data_source_validation"]["status"], "pass")
        self.assertEqual(len(result["validation_log"]), 2)

    def test_client_agent_returns_requested_data_source_patch(self) -> None:
        client = ClientAgent(
            feedback_items=[
                {
                    "request_type": "data_source_slot_clarification",
                    "table_index": 0,
                    "fields": ["city", "block"],
                    "targets": ["st.caption"],
                    "state_patch": {
                        "final_data_source": {
                            "connection": {"table": "shenzhen_new_house"},
                            "filters": {
                                "city": "Shenzhen",
                                "block": "Nanshan CBD",
                            },
                        }
                    },
                }
            ]
        )
        response = client.respond(
            {
                "request_type": "data_source_slot_clarification",
                "table_index": 0,
                "fields": ["city", "block", "table"],
            }
        )

        self.assertTrue(response["matched"])
        data_source_patch = response["state_patch"]["final_data_source"]
        self.assertEqual(
            data_source_patch["connection"]["table"],
            "shenzhen_new_house",
        )
        self.assertEqual(
            data_source_patch["filters"],
            {"city": "Shenzhen", "block": "Nanshan CBD"},
        )


def _message(payload: dict[str, Any]) -> dict[str, list[AIMessage]]:
    return {"messages": [AIMessage(content=json.dumps(payload, ensure_ascii=False))]}


def _analysis_state(city: str, block: str) -> dict[str, Any]:
    return {
        "summary": {
            "text": "Example summary",
            "data_source": {
                "connection": {"table": "beijing_new_house"},
                "filters": {
                    "city": city,
                    "block": block,
                    "start_date": "2020-01-01",
                    "end_date": "2024-12-31",
                },
            },
        },
        "tables": [
            {
                "caption": {
                    "text": "Example caption",
                    "data_source": {
                        "connection": {"table": "beijing_new_house"},
                        "select_columns": ["date_code", "trade_sets"],
                        "filters": {
                            "city": city,
                            "block": block,
                            "start_date": "2020-01-01",
                            "end_date": "2024-12-31",
                        },
                    },
                },
            }
        ]
    }

if __name__ == "__main__":
    unittest.main()
