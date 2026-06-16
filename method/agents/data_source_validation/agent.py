"""数据源验证 agent。

该 agent 负责 scope 验证闭环：
1. 将 summary 和 caption 中的 data-source 候选描述交给 ReAct LLM。
2. 让 ReAct LLM 合成 slide 级 final data source。
3. ReAct LLM 按需调用 `ask_client` 和 `slot_query`。
4. 返回最终确认的 `analysis_state["final_data_source"]`。
"""

import json
import os
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from .tools import (
    DATA_SOURCE_VALIDATION_TOOLS,
    DataSourceValidationContext,
    DataSourceValidationState,
)

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
DEFAULT_PROMPT_PATH = PROMPT_DIR / "data_source_validation_react_prompt.txt"


class SourceConnection(BaseModel):
    """最终 data source 的数据库连接字段。

    Args:
        table: 已确认的数据库表名。
    """

    table: str


class SourceFilters(BaseModel):
    """最终 data source 的 scope 过滤字段。

    Args:
        city: 已确认的城市 slot。
        block: 已确认的板块或区域 slot。
        start_date: 已确认的开始日期，格式为 `YYYY-MM-DD`。
        end_date: 已确认的结束日期，格式为 `YYYY-MM-DD`。
    """

    city: str
    block: str
    start_date: str
    end_date: str


class ValidationOutput(BaseModel):
    """Data source validation ReAct agent 的结构化最终输出。

    Args:
        connection: 已确认的数据库连接字段。
        filters: 已确认的 scope 过滤字段。
    """

    connection: SourceConnection
    filters: SourceFilters


class DataSourceValidationAgent:
    """通过 ReAct 和 client 多轮交互验证、修正 data-source slots。

    该类只负责 data-source validation 阶段：把 analysis 阶段抽取到的
    summary/caption source candidates 交给 ReAct agent，由 agent 调用数据库
    查询工具和 client 澄清工具，最终返回 slide-level `final_data_source`。
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_sec: int = 120,
        enable_thinking: bool | None = False,
    ) -> None:
        """初始化数据源验证 agent。

        Args:
            model: OpenAI-compatible chat model 名称。
            api_key: OpenAI-compatible endpoint 的 API key。
            base_url: OpenAI-compatible endpoint 的 base URL。
            timeout_sec: LLM 请求超时时间，单位为秒。
            enable_thinking: 是否通过 provider-specific `extra_body` 打开模型
                thinking。Qwen tool-calling 默认应关闭，避免内部 parameter
                标签泄漏到 tool arguments。

        Returns:
            None.

        Raises:
            ValueError: 未提供 `model` 时抛出。
        """
        if model is None:
            raise ValueError("DataSourceValidationAgent requires model when using create_agent.")

        self.prompt = DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
        self.llm = ChatOpenAI(
            model=model,
            api_key=api_key or os.getenv("DASHSCOPE_API_KEY"),
            base_url=base_url,
            timeout=timeout_sec,
            temperature=0,
            extra_body={"enable_thinking": enable_thinking}
            if enable_thinking is not None
            else None,
        )

    async def arun(
        self,
        analysis_state: dict[str, Any],
        client: Any,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """让 ReAct agent 合成并验证 slide 级 data-source slots。

        Args:
            analysis_state: 当前 analysis state，包含 summary/caption 抽取结果和可选的 client-confirmed `final_data_source` patch。
            client: 具备 `respond(request)` 的 client simulator 或人工桥接对象。

        Returns:
            `(final_data_source, tool_log)`。
        """
        user_payload = build_validation_payload(analysis_state)
        state: DataSourceValidationState = {
            "messages": [
                HumanMessage(
                    content=json.dumps(
                        user_payload,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            ],
            "tool_log": [],
        }
        agent = create_agent(
            model=self.llm,
            tools=DATA_SOURCE_VALIDATION_TOOLS,
            system_prompt=self.prompt,
            response_format=ToolStrategy(
                ValidationOutput,
                handle_errors=True,
            ),
            state_schema=DataSourceValidationState,
            context_schema=DataSourceValidationContext,
        )
        result = await agent.ainvoke(
            state,
            context=DataSourceValidationContext(client=client),
        )
        structured_response = result.get("structured_response")
        if structured_response is None:
            raise ValueError("ReAct agent returned no structured_response.")
        output = ValidationOutput.model_validate(structured_response)
        return output.model_dump(), result["tool_log"]


def build_validation_payload(
    analysis_state: dict[str, Any],
) -> dict[str, Any]:
    """把 analysis state 转成 ReAct prompt payload。

    该函数只做 schema 收窄，不合成最终 data source。slot 冲突、缺失和
    最终取值选择必须留给 ReAct agent 结合工具证据完成。

    Args:
        analysis_state: 当前 analysis state，包含 summary/caption 抽取结果。

    Returns:
        包含 source candidates 的 JSON payload。

    Raises:
        KeyError: `summary`、`tables` 或 table caption 缺少必要字段时抛出。
    """
    source_data = []
    summary_source = analysis_state["summary"]["data_source"]
    if _has_scope_claim(summary_source):
        source_data.append(("summary", "summary", summary_source))
    source_data.extend(
        (f"caption[{table_index}]", "st.caption", table["caption"]["data_source"])
        for table_index, table in enumerate(analysis_state["tables"])
    )
    return {
        "source_candidates": [
            {
                "source": source,
                "target": target,
                "data_source": {
                    "connection": data_source["connection"],
                    "filters": data_source["filters"],
                },
            }
            for source, target, data_source in source_data
        ]
    }


def _has_scope_claim(data_source: dict[str, Any]) -> bool:
    connection = data_source["connection"]
    filters = data_source["filters"]
    values = [
        connection["table"],
        filters["city"],
        filters["block"],
        filters["start_date"],
        filters["end_date"],
    ]
    return any(str(value).strip() for value in values)
