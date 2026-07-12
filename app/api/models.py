from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from app.verification.models import ExtractedLabel, VerificationResult


class ErrorResponse(BaseModel):
    """Error payload returned by API endpoints.

    Inputs:
        `message` is the user-facing summary. `errors` maps field names such
        as `image`, `brand_name`, or `items_json` to specific validation text.

    Outputs:
        A JSON object used for 4xx/5xx responses.
    """

    message: str
    errors: dict[str, str]


class VerifyResponse(BaseModel):
    """Successful single-label verification response.

    Inputs:
        `verification` contains field-level comparison results, `latency_ms`
        reports request duration, `extracted_label` is the raw vision model
        output after schema validation, and `timings` carries diagnostic timing
        metadata.

    Outputs:
        The JSON response shape for `POST /verify`.
    """

    verification: VerificationResult
    latency_ms: int
    extracted_label: ExtractedLabel
    timings: dict[str, int | str | bool | None] = Field(default_factory=dict)


class BatchSummary(BaseModel):
    """Aggregate status for a batch verification request.

    Inputs:
        Counts of approved labels, labels needing review, total labels, and
        total request latency.

    Outputs:
        The `summary` object inside `BatchVerifyResponse`.
    """

    passed: int
    needs_review: int
    total: int
    latency_ms: int


class BatchItemResult(BaseModel):
    """Per-label result inside a batch response.

    Inputs:
        The label index, original filename, approved/review status, optional
        verification/extraction objects, latency/timing metadata, and any
        item-specific validation errors.

    Outputs:
        One entry in `BatchVerifyResponse.results`.
    """

    index: int
    filename: str | None
    status: Literal["APPROVED", "NEEDS_REVIEW"]
    verification: VerificationResult | None = None
    extracted_label: ExtractedLabel | None = None
    latency_ms: int
    timings: dict[str, int | str | bool | None] = Field(default_factory=dict)
    errors: dict[str, str]


class BatchVerifyResponse(BaseModel):
    """Successful batch verification response.

    Inputs:
        `summary` gives aggregate counts and `results` contains one
        `BatchItemResult` per uploaded image/application-data pair.

    Outputs:
        The JSON response shape for `POST /verify/batch`.
    """

    summary: BatchSummary
    results: list[BatchItemResult]
