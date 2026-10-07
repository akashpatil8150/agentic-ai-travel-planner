import logging
import time
from typing import Optional

from groq import Groq

from app.core.config import settings
from app.observability.metrics import observability_metrics


logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """
    Raised when the LLM client fails.
    """

    pass


class LLMClient:
    """
    Central LLM client for the application.

    Provider:
        Groq

    Model:
        Configured through settings.llm_model

    Responsibilities:
        - Initialize Groq client
        - Send chat completion requests
        - Handle reasoning configuration
        - Support structured JSON responses
        - Return final model response
        - Handle provider errors

    Agents should use this client instead of
    creating their own Groq clients.
    """

    def __init__(self):

        # ====================================================
        # API KEY VALIDATION
        # ====================================================

        if not settings.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is not configured."
            )

        # ====================================================
        # GROQ CLIENT
        # ====================================================

        self.client = Groq(
            api_key=settings.groq_api_key
        )

        # ====================================================
        # MODEL
        # ====================================================

        self.model = settings.llm_model

        logger.info(
            "LLM client initialized | model=%s",
            self.model,
        )

    # ========================================================
    # GENERATE
    # ========================================================

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1000,
        reasoning_effort: str = "low",
        response_format: Optional[dict] = None,
    ) -> str:
        """
        Generate a response from the configured LLM.

        reasoning_effort:
            low
            medium
            high

        response_format:
            Optional Groq structured-output configuration.

            Example:

            {
                "type": "json_schema",
                "json_schema": {
                    "name": "supervisor_plan",
                    "strict": True,
                    "schema": {...}
                }
            }

        For normal agent tasks we use LOW reasoning
        to keep latency and token usage controlled.
        """

        # ====================================================
        # VALIDATE SYSTEM PROMPT
        # ====================================================

        if (
            not system_prompt
            or not system_prompt.strip()
        ):
            raise ValueError(
                "System prompt cannot be empty."
            )

        # ====================================================
        # VALIDATE USER PROMPT
        # ====================================================

        if (
            not user_prompt
            or not user_prompt.strip()
        ):
            raise ValueError(
                "User prompt cannot be empty."
            )

        # ====================================================
        # VALIDATE REASONING EFFORT
        # ====================================================

        allowed_reasoning_efforts = {
            "low",
            "medium",
            "high",
        }

        if reasoning_effort not in (
            allowed_reasoning_efforts
        ):
            raise ValueError(
                "reasoning_effort must be "
                "'low', 'medium', or 'high'."
            )

        # ====================================================
        # BUILD REQUEST PARAMETERS
        # ====================================================

        request_params = {
            "model": self.model,

            "messages": [
                {
                    "role": "system",
                    "content": system_prompt.strip(),
                },
                {
                    "role": "user",
                    "content": user_prompt.strip(),
                },
            ],

            # ------------------------------------------------
            # GPT-OSS REASONING
            # ------------------------------------------------

            "reasoning_effort": reasoning_effort,

            # Do not return internal reasoning
            # to the application.
            "include_reasoning": False,

            # ------------------------------------------------
            # GENERATION SETTINGS
            # ------------------------------------------------

            "temperature": temperature,

            "max_completion_tokens": max_tokens,
        }

        # ====================================================
        # STRUCTURED OUTPUT
        # ====================================================

        if response_format is not None:

            request_params["response_format"] = (
                response_format
            )

            logger.info(
                "Structured output enabled | format=%s",
                response_format.get("type"),
            )

        # ====================================================
        # LLM REQUEST
        # ====================================================

        llm_start_time = time.perf_counter()

        try:

            logger.info(
                "LLM request started | "
                "model=%s | "
                "reasoning_effort=%s",
                self.model,
                reasoning_effort,
            )

            response = (
                self.client.chat.completions.create(
                    **request_params
                )
            )

        except Exception as exc:

            llm_duration_ms = (
                time.perf_counter() - llm_start_time
            ) * 1000

            observability_metrics.record_llm_call(
                model=self.model,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                latency_ms=llm_duration_ms,
                status="failed",
            )

            logger.error(
                "LLM request failed | "
                "model=%s | "
                "duration_ms=%.2f | "
                "error=%s",
                self.model,
                llm_duration_ms,
                exc,
            )

            raise LLMClientError(
                "LLM service is currently unavailable."
            ) from exc

        # ====================================================
        # RESPONSE VALIDATION
        # ====================================================

        if response is None:

            raise LLMClientError(
                "LLM returned no response."
            )

        if not response.choices:

            raise LLMClientError(
                "LLM returned no choices."
            )

        # ====================================================
        # GET MESSAGE
        # ====================================================

        message = response.choices[0].message

        if message is None:

            raise LLMClientError(
                "LLM returned no message."
            )

        # ====================================================
        # GET FINAL CONTENT
        # ====================================================

        content = message.content

        if (
            content is None
            or not content.strip()
        ):

            logger.error(
                "LLM returned empty content | "
                "model=%s | "
                "finish_reason=%s",
                self.model,
                response.choices[0].finish_reason,
            )

            raise LLMClientError(
                "LLM returned empty content."
            )

        # ====================================================
        # USAGE LOGGING
        # ====================================================

        llm_duration_ms = (
            time.perf_counter() - llm_start_time
        ) * 1000

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        total_tokens = response.usage.total_tokens if response.usage else (input_tokens + output_tokens)

        observability_metrics.record_llm_call(
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=llm_duration_ms,
            status="success",
        )

        return content.strip()