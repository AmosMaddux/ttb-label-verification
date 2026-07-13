"""Fake vision client used by tests.

The fake records call metadata and returns a fixed result or raises a fixed
exception, allowing service and endpoint tests to exercise extraction behavior
without network access or API keys.
"""

from __future__ import annotations

from app.vision.client import VisionClientResult


class FakeVisionClient:
    """Deterministic test double for `VisionClientProtocol`.

    Inputs:
        A `VisionClientResult` to return, or an exception to raise.

    Outputs:
        An object with the same async extraction method as the real client plus
        recorded prompt/schema/model/detail metadata for assertions.
    """

    def __init__(
        self,
        result: VisionClientResult | Exception,
        *,
        reasoning_effort: str | None = None,
        requested_service_tier: str | None = None,
    ) -> None:
        """Store the fixed fake result and initialize call tracking.

        Inputs:
            `result` is either returned from extraction or raised if it is an
            exception instance.

        Outputs:
            A fake client ready for test use.
        """
        self.result = result
        self.reasoning_effort = reasoning_effort
        self.requested_service_tier = requested_service_tier
        self.calls = 0
        self.last_prompt: str | None = None
        self.last_schema: dict | None = None
        self.last_model: str | None = None
        self.last_detail: str | None = None

    async def extract_structured_label(
        self,
        *,
        image_bytes: bytes,
        prompt: str,
        schema: dict,
        model: str,
        detail: str,
    ) -> VisionClientResult:
        """Record the extraction call and return or raise the configured result.

        Inputs:
            The same arguments expected by the real vision client.

        Outputs:
            The configured `VisionClientResult`, or raises the configured
            exception to simulate provider/client failure.
        """
        self.calls += 1
        self.last_prompt = prompt
        self.last_schema = schema
        self.last_model = model
        self.last_detail = detail

        if isinstance(self.result, Exception):
            raise self.result
        return self.result
