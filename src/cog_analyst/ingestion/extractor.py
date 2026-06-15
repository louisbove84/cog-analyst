"""Deterministic structured extractor backed by an OpenAI-compatible chat model.

The LLM is constrained to fill a Pydantic schema and is treated as untrusted.
``langchain_openai`` is imported lazily inside ``__init__`` so this module (and
the offline test suite, which uses fake extractors) imports with no LLM
dependencies installed.
"""

from __future__ import annotations

from typing import Optional, Type

from cog_analyst.ingestion.interfaces import (
    ExtractionError,
    StructuredExtractor,
    TSchema,
)

__all__ = ["LangChainExtractor"]

_SYSTEM_PROMPT = (
    "You are a strict information extractor for open-source military analysis. "
    "Extract ONLY facts explicitly stated in the provided text into the given "
    "schema. Follow these rules without exception:\n"
    "1. Never infer, guess, or use prior knowledge. If a fact is not in the "
    "text, leave optional fields null and do not fabricate values.\n"
    "2. Use exact equipment designators as written in doctrine (e.g. 'HQ-9B', "
    "not 'HQ-9B SAMs'; 'J-11', not 'J-11 fighters').\n"
    "3. Always populate source_citation from the passage header or source label "
    "provided with the text.\n"
    "4. Do not add fields that are not part of the schema."
)


class LangChainExtractor(StructuredExtractor):
    """Structured extractor using a LangChain OpenAI-compatible chat model.

    Supports OpenAI, xAI/Grok, Ollama, LM Studio, and vLLM via ``base_url``.
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        structured_output_method: Optional[str] = None,
    ) -> None:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - exercised only without deps
            raise ImportError(
                "LangChainExtractor requires the 'langchain-openai' package. "
                "Install it with: pip install langchain-openai"
            ) from exc

        self._structured_output_method = structured_output_method

        kwargs = {
            "model": model,
            "temperature": temperature,
        }
        if base_url is not None:
            kwargs["base_url"] = base_url
            # Local OpenAI-compatible servers often need no real key; supply a
            # placeholder so the client constructs without error.
            kwargs["api_key"] = api_key or "local-no-key"
        elif api_key is not None:
            kwargs["api_key"] = api_key

        try:
            self._llm = ChatOpenAI(**kwargs)
        except Exception as exc:  # noqa: BLE001 - normalize client construction errors
            raise ExtractionError(f"failed to initialize chat model: {exc}") from exc

    def extract(self, text: str, schema: Type[TSchema]) -> TSchema:
        messages = [
            ("system", _SYSTEM_PROMPT),
            ("human", text),
        ]

        try:
            if self._structured_output_method is not None:
                structured = self._llm.with_structured_output(
                    schema, method=self._structured_output_method
                )
            else:
                structured = self._llm.with_structured_output(schema)
            result = structured.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - normalize transport/client errors
            raise ExtractionError(f"extraction failed: {exc}") from exc

        if not isinstance(result, schema):
            raise TypeError(
                f"extractor returned {type(result).__name__}, expected {schema.__name__}"
            )
        return result
