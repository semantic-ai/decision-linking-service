"""Load agent settings from ``.env`` and ``config.json``."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from src.agent_helpers.models import AgentConfig
from src.agent_helpers.prompts import validate_prompt_overrides


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT / ".env"
DEFAULT_CONFIG_FILE = ROOT / "config.json"


# ---------------------------------------------------------------------------
# JSON file schema
# ---------------------------------------------------------------------------


class _AgentFileConfig(BaseModel):
    """Non-secret Agent settings accepted under ``config.json["agent"]``."""

    model_config = ConfigDict(extra="forbid")

    mcp_server_url: str = "http://127.0.0.1:8000/mcp"
    max_search_attempts: int = Field(default=3, ge=1, le=5)
    max_pivots: int = Field(default=1, ge=0, le=2)
    temperature: float = 0.0
    reasoning_effort: str = "none"
    cache_path: str | None = None


class _FileConfig(BaseModel):
    """Validated root structure of ``config.json``."""

    model_config = ConfigDict(extra="forbid")

    agent: _AgentFileConfig = Field(default_factory=_AgentFileConfig)
    prompts: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def _read_file_config(path: Path) -> _FileConfig:
    """Read and validate JSON configuration, or return defaults if absent.

    Unknown fields deliberately fail Pydantic validation so misspelled agent
    options do not silently fall back to defaults.
    """
    if not path.exists():
        return _FileConfig()
    with path.open(encoding="utf-8") as config_file:
        return _FileConfig.model_validate(json.load(config_file))


def load_agent_environment(env_file: Path | None = None) -> None:
    """Expose legacy lowercase values under the generic LLM variable names.

    Canonical provider variables always win because aliases are installed with
    :meth:`dict.setdefault`.  Existing deployments can therefore migrate
    without changing secrets immediately.
    """
    load_dotenv(env_file or DEFAULT_ENV_FILE, override=False)
    aliases = {
        "subscription_key": "LLM_API_KEY",
        "azure_endpoint": "LLM_ENDPOINT",
        "api_version": "LLM_API_VERSION",
        "deployment": "LLM_DEPLOYMENT_NAME",
    }
    for legacy_name, canonical_name in aliases.items():
        value = os.getenv(legacy_name)
        if value:
            os.environ.setdefault(canonical_name, value)


def _resolve_model_selection() -> tuple[str, str | None]:
    """Resolve the canonical model selector and optional Azure deployment.

    A generic LLM deployment is sufficient to construct the equivalent
    ``azure_openai:<deployment>`` selector.  Other providers must define the
    canonical ``MODEL`` value directly.
    """
    model = os.getenv("MODEL")
    deployment = os.getenv("LLM_DEPLOYMENT_NAME")
    if not model and deployment:
        model = f"azure_openai:{deployment}"
    if not model:
        raise ValueError("MODEL must be set in .env using the 'provider:model' format")

    llm_deployment = deployment if model.startswith("azure_openai:") else None
    return model, llm_deployment


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_agent_config(
    *,
    env_file: Path | None = None,
    config_file: Path | None = None,
) -> AgentConfig:
    """Load and validate the complete Agent configuration.

    Parameters
    ----------
    env_file
        Optional dotenv path.  Defaults to the repository-root ``.env``.
    config_file
        Optional JSON path.  Defaults to the repository-root ``config.json``.

    Returns
    -------
    AgentConfig
        Model/environment values merged with validated non-secret JSON
        settings and prompt overrides.

    Raises
    ------
    ValueError
        If no model can be resolved or a prompt override is unknown/invalid.
    pydantic.ValidationError
        If ``config.json`` contains an unknown field or invalid value.
    """
    load_agent_environment(env_file)

    resolved_config_file = config_file or DEFAULT_CONFIG_FILE
    file_config = _read_file_config(resolved_config_file)
    prompt_overrides = validate_prompt_overrides(file_config.prompts)
    model, llm_deployment = _resolve_model_selection()
    cache_path = (
        Path(file_config.agent.cache_path)
        if file_config.agent.cache_path
        else None
    )
    if cache_path is not None and not cache_path.is_absolute():
        cache_path = resolved_config_file.parent / cache_path
    return AgentConfig(
        model=model,
        mcp_server_url=file_config.agent.mcp_server_url,
        max_search_attempts=file_config.agent.max_search_attempts,
        max_pivots=file_config.agent.max_pivots,
        temperature=file_config.agent.temperature,
        reasoning_effort=file_config.agent.reasoning_effort,
        llm_deployment=llm_deployment,
        prompt_overrides=prompt_overrides,
        cache_path=cache_path,
    )
