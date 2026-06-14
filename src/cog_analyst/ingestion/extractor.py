"""Structured extraction via LangChain.

The LLM is an UNTRUSTED extraction mechanism. We constrain it three ways:
1. `.with_structured_output(Schema)` forces output into a Pydantic schema.
2. A strict system prompt forbids inference and demands a source citation.
3. Downstream, the entity guard + SQLite types reject anything that slips through.

`StructuredExtractor` is an abstract base class (ABC) so the pipeline can be
unit-tested with a fake subclass and never needs a live API key.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger("cog_analyst.extractor")

TSchema = TypeVar("TSchema", bound=BaseModel)

_SYSTEM_PROMPT = (
    "You are a meticulous defense-intelligence data extractor working only with "
    "open-source text. Extract ONLY facts explicitly stated in the provided "
    "passage into the required schema. Rules:\n"
    "- Do NOT infer, estimate, or add knowledge from memory.\n"
    "- If a field is not explicitly stated in the passage, leave it null "
    "(for optional fields) rather than guessing.\n"
    "- Convert ranges to whole kilometers and lengths to whole meters.\n"
    "- Always populate source_citation with the document and page provided in "
    "the passage header.\n"
    "- If the passage does not describe the requested entity at all, return the "
    "schema with empty/null fields; never fabricate an entity."
)


class StructuredExtractor(ABC):
    """Anything that can turn text into a validated schema instance."""

    @abstractmethod
    def extract(self, text: str, schema: Type[TSchema]) -> TSchema:
        """Extract ``text`` into an instance of ``schema``."""
        raise NotImplementedError


class LangChainExtractor(StructuredExtractor):
    """Extractor backed by any OpenAI-compatible chat endpoint.

    Works against:
      - OpenAI (default; needs OPENAI_API_KEY)
      - Ollama        -> base_url="http://localhost:11434/v1", api_key="ollama"
      - LM Studio     -> base_url="http://localhost:1234/v1",  api_key="lm-studio"
      - vLLM          -> base_url="http://<host>:8000/v1",     api_key="<any>"

    LangChain is imported lazily so importing this module (and running the
    deterministic test suite) does not require LangChain or an API key.

    Parameters
    ----------
    base_url:
        OpenAI-compatible endpoint. ``None`` uses the real OpenAI API.
    api_key:
        Local servers ignore the value but the client requires *some* string;
        when ``base_url`` is set and no key is given, a placeholder is used.
    structured_output_method:
        Passed to ``with_structured_output``. Local/tool-capable models often
        do best with ``"function_calling"`` or ``"json_schema"``; ``None`` lets
        LangChain choose its default.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        structured_output_method: Optional[str] = None,
    ) -> None:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "LangChainExtractor requires 'langchain-openai'. Install with "
                "`pip install -e \".[llm]\"`."
            ) from exc

        self._method = structured_output_method

        kwargs: dict = {"model": model, "temperature": temperature}
        if base_url is not None:
            kwargs["base_url"] = base_url
            # Local servers don't validate the key, but the client demands one.
            kwargs["api_key"] = api_key or "local-no-key"
        elif api_key is not None:
            kwargs["api_key"] = api_key

        # temperature=0 for maximum determinism in an extraction task.
        self._llm = ChatOpenAI(**kwargs)

    def extract(self, text: str, schema: Type[TSchema]) -> TSchema:
        """Run a single structured-output extraction call."""

        if self._method is not None:
            structured = self._llm.with_structured_output(schema, method=self._method)
        else:
            structured = self._llm.with_structured_output(schema)
        messages = [
            ("system", _SYSTEM_PROMPT),
            ("human", text),
        ]
        result = structured.invoke(messages)
        if not isinstance(result, schema):  # defensive; LC should guarantee this
            raise TypeError(
                f"Extractor returned {type(result)!r}, expected {schema!r}"
            )
        return result
