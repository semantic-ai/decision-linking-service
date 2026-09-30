"""Core Agent that connects the configured model, MCP tools, and search graph."""

import logging
import os
from typing import Any

from fastmcp import Client
from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI

from src.agent_helpers.mcp_tools import create_mcp_tool
from src.agent_helpers.models import AgentConfig, DocumentContext, ResolutionResponse
from src.agent_helpers.prompts import load_prompts
from src.config import load_agent_environment
from src.agent_helpers.search_graph import (
    REQUIRED_TOOLS,
    create_search_graph,
    initial_search_state,
)
from src.tools.memory import write_memory


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class Agent:
    """Resolve one legal reference using the structured MCP search graph.

    Parameters
    ----------
    config
        Validated model, MCP, prompt, and search-call configuration.
    llm
        Optional initialized chat model.  Primarily useful for tests; when
        omitted the model is created from ``config``.
    mcp_target
        Optional FastMCP client target.  Defaults to the configured HTTP URL,
        but may be an in-memory FastMCP server during tests.
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        llm=None,
        mcp_target: Any | None = None,
    ):
        self.config = config
        self.llm = llm or self._create_llm()
        self.mcp_target = mcp_target or config.mcp_server_url
        self.prompts = load_prompts(config.prompt_overrides)

    # ------------------------------------------------------------------
    # LLM factory
    # ------------------------------------------------------------------
    def _create_llm(self):
        """Initialize the configured LangChain chat model.

        ``init_chat_model`` resolves the ``provider:model`` selector and reads
        provider credentials from the environment.  Azure additionally needs
        the deployment value normalized by :func:`src.config.load_agent_config`.
        """
        load_agent_environment()
        kwargs: dict[str, Any] = {"temperature": self.config.temperature}
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        if self.config.azure_deployment and "/openai/v1" in endpoint.rstrip("/"):
            return ChatOpenAI(
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                base_url=endpoint,
                model=self.config.azure_deployment,
                **kwargs,
            )
        if self.config.azure_deployment:
            kwargs["azure_deployment"] = self.config.azure_deployment
        return init_chat_model(self.config.model, **kwargs)

    # ------------------------------------------------------------------
    # MCP tool discovery
    # ------------------------------------------------------------------
    @staticmethod
    async def _load_required_tools(client: Client) -> dict[str, Any]:
        """Discover, verify, and bridge the required MCP tools.

        Raises
        ------
        RuntimeError
            If the connected server does not expose the complete tool set
            required by the fixed search graph.
        """
        tool_info = await client.list_tools()
        available = {tool.name for tool in tool_info}
        missing = REQUIRED_TOOLS - available
        if missing:
            names = ", ".join(sorted(missing))
            raise RuntimeError(f"MCP server is missing required tools: {names}")

        return {
            tool.name: create_mcp_tool(tool, client)
            for tool in tool_info
            if tool.name in REQUIRED_TOOLS
        }

    # ------------------------------------------------------------------
    # Public search request
    # ------------------------------------------------------------------
    async def search(
        self,
        reference: str,
        document_context: DocumentContext | None = None,
    ) -> ResolutionResponse:
        """Resolve one legal reference against the supported official sources.

        A new MCP connection is opened for the request, the required tools are
        verified, and the fixed graph is invoked once.  The connection closes
        before the graph state is converted to the public response model.

        Parameters
        ----------
        reference
            One legal instrument or local-decision reference to resolve.
        document_context
            Optional origin metadata used only as fallback context during
            classification.

        Returns
        -------
        ResolutionResponse
            Selected unchanged source results, terminal status, reason, trace,
            and any optional guideline lesson persisted for the selected source.

        Raises
        ------
        ValueError
            If ``reference`` is empty or contains only whitespace.
        RuntimeError
            If the MCP server is missing a required graph tool.
        """
        reference = reference.strip()
        if not reference:
            raise ValueError("reference must not be empty")

        async with Client(self.mcp_target) as client:
            tools = await self._load_required_tools(client)
            graph = create_search_graph(
                llm=self.llm,
                tools=tools,
                prompts=self.prompts,
                max_search_attempts=self.config.max_search_attempts,
            )
            state = await graph.ainvoke(
                initial_search_state(reference, document_context=document_context)
            )
        lesson = state["proposed_guideline_lesson"]
        classified = state["classified_reference"]
        if lesson and classified and classified.source:
            try:
                write_memory(classified.source.value, lesson)
            except Exception as error:
                logger.warning("Failed to persist guideline lesson: %s", error)

        response = ResolutionResponse(
            reference=reference,
            classification=state["classified_reference"],
            status=state["resolution_status"],
            results=state["results"],
            reason=state["reason"],
            attempt_count=state["attempt_count"],
            trace=state["trace"],
            proposed_guideline_lesson=state["proposed_guideline_lesson"],
        )

        return response
