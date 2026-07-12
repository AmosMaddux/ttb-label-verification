from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApplicationData(BaseModel):
    """Expected label data supplied by the user/application form.

    Inputs:
        Seven required strings that represent what should be visible on the
        uploaded label.

    Outputs:
        A validated model passed into `verify_label` as the source of truth for
        comparison.
    """

    brand_name: str
    class_type: str
    producer: str
    country_of_origin: str
    abv: str
    net_contents: str
    government_warning: str


class ExtractedLabel(BaseModel):
    """Structured fields extracted from the uploaded label image.

    Inputs:
        Seven optional strings returned by the vision model. Each field may be
        `None` when the text is missing, unreadable, or uncertain.

    Outputs:
        A strict model with no extra keys, allowing the verifier to distinguish
        missing extraction from mismatched extraction.
    """

    model_config = ConfigDict(extra="forbid")

    brand_name: str | None = None
    class_type: str | None = None
    producer: str | None = None
    country_of_origin: str | None = None
    abv: str | None = None
    net_contents: str | None = None
    government_warning: str | None = None


class FieldResult(BaseModel):
    """Comparison result for one label field.

    Inputs:
        Field name, pass/fail status, original expected/extracted values,
        comparison strategy, optional score/normalized values, and a user-facing
        message.

    Outputs:
        One field row in the verification response.
    """

    field: str
    status: Literal["PASS", "FAIL"]
    application_value: str
    extracted_value: str | None
    strategy: str
    score: float | None = None
    normalized_application_value: str | None = None
    normalized_extracted_value: str | None = None
    message: str


class VerificationResult(BaseModel):
    """Overall result for all seven required label fields.

    Inputs:
        A final verdict plus the ordered list of `FieldResult` objects.

    Outputs:
        The verifier's result object. Any failing field produces
        `NEEDS_REVIEW`; all passing fields produce `PASS`.
    """

    verdict: Literal["PASS", "NEEDS_REVIEW"]
    fields: list[FieldResult]
