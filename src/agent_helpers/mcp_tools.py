import json
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model


# ---------------------------------------------------------------------------
# JSON Schema -> Pydantic
# ---------------------------------------------------------------------------


def _python_type(schema: dict[str, Any]) -> Any:
    """Convert a JSON Schema type into a Python type."""
    # Handle nullable / union schemas.
    if "anyOf" in schema:
        choices = [
            item
            for item in schema["anyOf"]
            if item.get("type") != "null"
        ]
        return _python_type(choices[0]) if choices else Any

    schema_type = schema.get("type")

    # JSON Schema allows: {"type": ["string", "null"]}
    if isinstance(schema_type, list):
        schema_type = next(
            (item for item in schema_type if item != "null"),
            None,
        )

    if schema_type == "array":
        item_type = _python_type(schema.get("items", {}))
        return list[item_type]

    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
    }.get(schema_type, Any)


def json_schema_to_pydantic(
    schema: dict[str, Any],
    model_name: str,
) -> type[BaseModel]:
    """Convert an MCP input schema into a Pydantic model."""
    required = set(schema.get("required", []))
    fields: dict[str, tuple[Any, Any]] = {}

    for name, property_schema in schema.get("properties", {}).items():
        field_type = _python_type(property_schema)
        description = property_schema.get("description", "")

        if name in required:
            default = Field(
                ...,
                description=description,
            )
        else:
            field_type = Optional[field_type]
            default = Field(
                property_schema.get("default"),
                description=description,
            )

        fields[name] = (field_type, default)

    return create_model(
        f"{model_name}Arguments",
        **fields,
    )


# ---------------------------------------------------------------------------
# MCP result handling
# ---------------------------------------------------------------------------


def _text_from_result(result: Any) -> str:
    """Extract and join text blocks from an MCP result."""
    return "\n".join(
        item.text
        for item in getattr(result, "content", [])
        if hasattr(item, "text")
    )


def _structured_result(result: Any) -> Any:
    """Extract structured data from an MCP result."""
    content = getattr(result, "structured_content", None)

    if content is None:
        content = getattr(result, "structuredContent", None)

    # FastMCP may wrap the actual return value as {"result": value}.
    if isinstance(content, dict) and set(content) == {"result"}:
        return content["result"]

    if content is not None:
        return content

    # Fall back to text content.
    text = _text_from_result(result)

    if not text:
        return ""

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


# ---------------------------------------------------------------------------
# MCP -> LangChain
# ---------------------------------------------------------------------------


def create_mcp_tool(tool_info: Any, client: Any) -> StructuredTool:
    """Create an asynchronous LangChain tool backed by an MCP client."""
    schema = getattr(tool_info, "inputSchema", {}) or {}

    args_schema = json_schema_to_pydantic(
        schema,
        tool_info.name,
    )

    async def call_mcp_tool(**kwargs: Any) -> Any:
        """Call the MCP tool and return its result."""
        result = await client.call_tool(
            tool_info.name,
            kwargs,
        )

        if getattr(result, "is_error", False):
            message = _text_from_result(result)
            raise RuntimeError(
                message or f"MCP tool {tool_info.name!r} failed"
            )

        return _structured_result(result)

    return StructuredTool.from_function(
        coroutine=call_mcp_tool,
        name=tool_info.name,
        description=(
            tool_info.description
            or f"MCP tool {tool_info.name}"
        ),
        args_schema=args_schema,
    )
