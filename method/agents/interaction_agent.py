from __future__ import annotations

from typing import Any

from .types import RepairState


def _join(values: list[str]) -> str:
    return ", ".join(str(value) for value in values if str(value))


class InteractionAgent:
    """Turn detected issues into feedback requests and repair_state updates."""

    def build_request(self, issue: dict[str, Any]) -> dict[str, Any]:
        targets = list(issue.get("targets", []))
        error_types = list(issue.get("error_types", []))
        fields = list(issue.get("required_fields_guess", []))
        target = _join(targets) or "this slide element"
        error_type = _join(error_types) or "possible_error"
        evidence = str(issue.get("evidence", "")).strip()
        problem_statement = self._problem_statement(
            targets=targets,
            error_types=error_types,
            evidence=evidence,
        )
        requested_user_action = self._requested_user_action(
            targets=targets,
            error_types=error_types,
            fields=fields,
        )
        response_schema = self._response_schema(fields)
        question = (
            f"I found a possible {error_type} in {target}.\n"
            f"Observed evidence: {evidence or 'No detailed evidence was attached.'}\n"
            f"Why this matters: {problem_statement}\n"
            f"What I need from you: {requested_user_action}\n"
            f"Suggested response format: {response_schema}"
        )
        return {
            "targets": targets,
            "error_types": error_types,
            "required_fields": fields,
            "diagnosis": problem_statement,
            "evidence": evidence,
            "requested_user_action": requested_user_action,
            "suggested_response_schema": response_schema,
            "question": question,
        }

    def _problem_statement(
        self,
        *,
        targets: list[str],
        error_types: list[str],
        evidence: str,
    ) -> str:
        target_set = set(targets)
        error_set = set(error_types)
        if "logic_error" in error_set and "st.header" in target_set:
            return (
                "The chart/table header appears to describe a metric or aggregation "
                "that does not match the visible data series. If we repair this, we "
                "need the correct metric definitions, source columns and aggregation rules."
            )
        if "scope_error" in error_set:
            return (
                "The slide text exposes scope information such as city, district or "
                "year range, and that scope appears inconsistent across slide elements."
            )
        if "claim_error" in error_set:
            return (
                "A natural-language claim appears inconsistent with the visible chart, "
                "table or caption. The repair needs the intended factual claim."
            )
        if "value_error" in error_set:
            return (
                "A numeric value in the text is not directly supported by the visible "
                "chart/table values or their simple derived statistics."
            )
        return evidence or "The issue needs user confirmation before repair."

    def _requested_user_action(
        self,
        *,
        targets: list[str],
        error_types: list[str],
        fields: list[str],
    ) -> str:
        field_set = set(fields)
        if "logic.metrics" in field_set:
            return (
                "Please provide the corrected metric list. For each metric, include "
                "`name`, what it means, `source_col`, `agg_func`, and any filter condition. "
                "Also include the grouping dimension if relevant, for example month or year."
            )
        if {"scope.city", "scope.block"} & field_set or {"scope.start_year", "scope.end_year"} & field_set:
            return (
                "Please provide the intended scope values, such as city, district/block, "
                "start year and end year. If one side is already correct, say which text should change."
            )
        if any(field.startswith("claim.") for field in fields):
            return (
                "Please provide the intended claim text or the corrected factual attribute "
                "that should appear in this element."
            )
        if not fields:
            return (
                "Please confirm whether this is truly an error. If yes, provide the "
                "correct value or wording; if no, say that the current slide is acceptable."
            )
        return f"Please provide corrected values for: {_join(fields)}."

    def _response_schema(self, fields: list[str]) -> dict[str, Any]:
        field_set = set(fields)
        if "logic.metrics" in field_set:
            return {
                "logic": {
                    "metrics": [
                        {
                            "name": "<visible metric name>",
                            "meaning": "<human-readable meaning>",
                            "source_col": "<database column>",
                            "agg_func": "<count|sum|mean|...>",
                            "filter_condition": {},
                        }
                    ],
                    "group_by": "<month|year|area_range|...>",
                    "dimensions": [],
                }
            }
        if any(field.startswith("scope.") for field in fields):
            return {
                "scope": {
                    field.split(".", 1)[1]: "<correct value>"
                    for field in fields
                    if field.startswith("scope.")
                }
            }
        if any(field.startswith("claim.") for field in fields):
            return {
                "claim": {
                    field.split(".", 1)[1]: "<correct value>"
                    for field in fields
                    if field.startswith("claim.")
                }
            }
        return {"confirmation": "<yes/no>", "correction": "<correct value or wording if needed>"}

    def run(self, detected_issues: list[dict[str, Any]], client: Any | None = None) -> dict[str, Any]:
        repair_state = RepairState()
        interaction_log = []
        for issue in detected_issues:
            request = self.build_request(issue)
            response = client.respond(request) if client is not None else None
            matched = bool(response and response.get("matched"))
            state_patch = response.get("state_patch", {}) if response else {}
            if matched:
                repair_state.merge(state_patch, list(issue.get("targets", [])))
            elif not request["required_fields"]:
                repair_state.merge({}, list(issue.get("targets", [])))

            interaction_log.append(
                {
                    "request": request,
                    "matched": matched,
                    "state_patch": state_patch,
                    "matched_feedback_key": response.get("feedback_key") if response else None,
                }
            )

        return {
            "interaction_log": interaction_log,
            "repair_state": repair_state.to_dict(),
        }
