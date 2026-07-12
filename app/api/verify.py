"""Verification API routes and request orchestration.

The functions in this module validate uploads and application data, invoke the
vision extraction service, compare extracted label fields against the expected
fields, and return either a single-label or batch result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError

from app.api.models import BatchItemResult, BatchSummary, BatchVerifyResponse, ErrorResponse, VerifyResponse
from app.verification.comparisons import verify_label
from app.verification.models import ApplicationData, ExtractedLabel
from app.vision.service import VisionService


MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_BATCH_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_BATCH_SIZE = 5
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
REQUIRED_FIELDS = [
    "brand_name",
    "class_type",
    "producer",
    "country_of_origin",
    "abv",
    "net_contents",
    "government_warning",
]

logger = logging.getLogger(__name__)
router = APIRouter()

OptionalForm = Annotated[str | None, Form()]
VisionServiceProvider = Callable[[], VisionService]


def get_vision_service_provider() -> VisionServiceProvider:
    """Return the factory used to create a vision service for each request.

    Inputs:
        None.

    Outputs:
        A callable that returns `VisionService`. Tests override this dependency
        with fake services so endpoint tests never require a real API key.
    """
    return VisionService.from_env


def _error_response(status_code: int, message: str, errors: dict[str, str]) -> JSONResponse:
    """Build a consistent JSON error response.

    Inputs:
        `status_code` is the HTTP status to send, `message` is a short
        user-facing summary, and `errors` maps failing fields to details.

    Outputs:
        A FastAPI `JSONResponse` containing the serialized `ErrorResponse`.
    """
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(message=message, errors=errors).model_dump(),
    )


def _latency_ms(start: float) -> int:
    """Calculate elapsed milliseconds from a `time.perf_counter()` start.

    Inputs:
        `start` is a monotonic timestamp captured before the measured work.

    Outputs:
        Integer milliseconds elapsed from `start` until this function is called.
    """
    return int((time.perf_counter() - start) * 1000)


def _log_request(
    *,
    latency_ms: int,
    verdict: str,
    failure_count: int,
    content_type: str | None,
    upload_size: int,
    event: str = "verify_request_complete",
) -> None:
    """Emit structured request-completion information to the app logger.

    Inputs:
        Request latency, verdict, failed-field count, upload metadata, and an
        optional event name.

    Outputs:
        None. The function writes an info log for normal requests and a warning
        when the five-second latency budget is exceeded.
    """
    exceeded_budget = latency_ms > 5000
    log = logger.warning if exceeded_budget else logger.info
    log(
        "%s latency_ms=%s verdict=%s failure_count=%s content_type=%s upload_size=%s exceeded_budget=%s",
        event,
        latency_ms,
        verdict,
        failure_count,
        content_type,
        upload_size,
        exceeded_budget,
    )


def _validate_fields(values: dict[str, str | None]) -> tuple[dict[str, str], dict[str, str]]:
    """Validate and trim required form/application fields.

    Inputs:
        A mapping from required field names to submitted strings or `None`.

    Outputs:
        A tuple of `(cleaned, errors)`. `cleaned` contains stripped strings for
        fields that are present, while `errors` contains required/empty messages
        keyed by field name.
    """
    cleaned: dict[str, str] = {}
    errors: dict[str, str] = {}

    for field in REQUIRED_FIELDS:
        value = values.get(field)
        if value is None:
            errors[field] = "This field is required."
            continue

        stripped = value.strip()
        if not stripped:
            errors[field] = "This field cannot be empty."
            continue

        cleaned[field] = stripped

    return cleaned, errors


async def _validate_image(image: UploadFile | None) -> tuple[bytes | None, dict[str, str], int, int]:
    """Read and validate one uploaded image.

    Inputs:
        A FastAPI `UploadFile` or `None`.

    Outputs:
        `(image_bytes, errors, byte_size, read_latency_ms)`. On success,
        `image_bytes` contains the uploaded data and `errors` is empty. On
        failure, `image_bytes` is `None` and `errors["image"]` explains why.
    """
    read_start = time.perf_counter()
    if image is None:
        return None, {"image": "Image file is required."}, 0, _latency_ms(read_start)

    if image.content_type not in ALLOWED_IMAGE_TYPES:
        return None, {"image": "Unsupported file type."}, 0, _latency_ms(read_start)

    data = await image.read()
    size = len(data)
    if size > MAX_UPLOAD_BYTES:
        return None, {"image": "File is larger than 8 MB."}, size, _latency_ms(read_start)

    try:
        with Image.open(BytesIO(data)) as opened:
            opened.verify()
    except (OSError, UnidentifiedImageError):
        return None, {"image": "Image file could not be read."}, size, _latency_ms(read_start)

    return data, {}, size, _latency_ms(read_start)


def _build_application(cleaned_fields: dict[str, str]) -> ApplicationData:
    """Convert validated request fields into the verifier's expected model.

    Inputs:
        A complete dictionary of stripped field strings.

    Outputs:
        An `ApplicationData` instance used by the comparison layer.
    """
    return ApplicationData(**cleaned_fields)


async def _verify_image_data(
    *,
    vision_service: VisionService,
    image_bytes: bytes,
    filename: str | None,
    content_type: str | None,
    fields: dict[str, str],
) -> VerifyResponse:
    """Run extraction and comparison for already-validated image bytes.

    Inputs:
        A vision service, raw image bytes, optional filename/content type, and
        cleaned expected field values from the application form.

    Outputs:
        A `VerifyResponse` containing the extracted label, field comparison
        result, total latency, and timing diagnostics.
    """
    start = time.perf_counter()
    application = _build_application(fields)
    if hasattr(vision_service, "extract_label_with_metrics"):
        extraction = await vision_service.extract_label_with_metrics(
            image_bytes,
            filename=filename,
            content_type=content_type,
        )
        extracted = extraction.label
        timings = dict(extraction.timings)
    else:
        vision_start = time.perf_counter()
        extracted = await vision_service.extract_label(
            image_bytes,
            filename=filename,
            content_type=content_type,
        )
        timings = {"vision_ms": _latency_ms(vision_start)}

    compare_start = time.perf_counter()
    verification = verify_label(application, extracted)
    timings["compare_ms"] = _latency_ms(compare_start)
    timings["verify_image_ms"] = _latency_ms(start)

    return VerifyResponse(
        verification=verification,
        latency_ms=_latency_ms(start),
        extracted_label=extracted,
        timings=timings,
    )


def _null_batch_item(
    *,
    index: int,
    filename: str | None,
    start: float,
    errors: dict[str, str],
) -> BatchItemResult:
    """Create a failed batch item when validation or processing cannot continue.

    Inputs:
        The item index, optional filename, request start timestamp, and an error
        dictionary for this label.

    Outputs:
        A `BatchItemResult` with `NEEDS_REVIEW`, no extracted/verification data,
        and the supplied errors.
    """
    return BatchItemResult(
        index=index,
        filename=filename,
        status="NEEDS_REVIEW",
        verification=None,
        extracted_label=None,
        latency_ms=_latency_ms(start),
        errors=errors,
    )


async def _verify_batch_item(
    *,
    index: int,
    image: UploadFile,
    item: object,
    vision_service: VisionService,
    semaphore: asyncio.Semaphore,
) -> BatchItemResult:
    """Validate and verify one image/application pair inside a batch.

    Inputs:
        The pair index, uploaded image, decoded item object, shared vision
        service, and semaphore that bounds concurrent vision calls.

    Outputs:
        A populated `BatchItemResult`. Validation or extraction failures are
        represented as `NEEDS_REVIEW` items rather than aborting the whole batch.
    """
    start = time.perf_counter()
    filename = image.filename
    errors: dict[str, str] = {}

    if not isinstance(item, dict):
        errors["item"] = "Application data must be an object."
    else:
        cleaned_fields, field_errors = _validate_fields(
            {field: item.get(field) for field in REQUIRED_FIELDS}
        )
        errors.update(field_errors)

    image_bytes, image_errors, _upload_size, image_read_ms = await _validate_image(image)
    errors.update(image_errors)

    if errors:
        return _null_batch_item(index=index, filename=filename, start=start, errors=errors)

    try:
        async with semaphore:
            result = await _verify_image_data(
                vision_service=vision_service,
                image_bytes=image_bytes or b"",
                filename=filename,
                content_type=image.content_type,
                fields=cleaned_fields,
            )
    except Exception:
        logger.exception("verify_batch_item_failed index=%s filename=%s", index, filename)
        return _null_batch_item(
            index=index,
            filename=filename,
            start=start,
            errors={"server": "Verification failed for this label."},
        )

    return BatchItemResult(
        index=index,
        filename=filename,
        status=result.verification.verdict,
        verification=result.verification,
        extracted_label=result.extracted_label,
        latency_ms=_latency_ms(start),
        timings={**result.timings, "image_read_ms": image_read_ms},
        errors={},
    )


@router.post(
    "/verify",
    response_model=VerifyResponse,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def verify_endpoint(
    vision_service_provider: Annotated[VisionServiceProvider, Depends(get_vision_service_provider)],
    image: Annotated[UploadFile | None, File()] = None,
    brand_name: OptionalForm = None,
    class_type: OptionalForm = None,
    producer: OptionalForm = None,
    country_of_origin: OptionalForm = None,
    abv: OptionalForm = None,
    net_contents: OptionalForm = None,
    government_warning: OptionalForm = None,
) -> VerifyResponse | JSONResponse:
    """Handle the single-label multipart verification endpoint.

    Inputs:
        One uploaded image plus the seven expected label fields supplied as form
        values. The vision service provider is injected for testability.

    Outputs:
        `VerifyResponse` on success, or an `ErrorResponse` JSON body for invalid
        input or unexpected server errors.
    """
    start = time.perf_counter()
    content_type = image.content_type if image else None

    field_values = {
        "brand_name": brand_name,
        "class_type": class_type,
        "producer": producer,
        "country_of_origin": country_of_origin,
        "abv": abv,
        "net_contents": net_contents,
        "government_warning": government_warning,
    }
    cleaned_fields, field_errors = _validate_fields(field_values)
    image_bytes, image_errors, upload_size, image_read_ms = await _validate_image(image)
    errors = {**image_errors, **field_errors}

    if errors:
        status_code = 415 if "Unsupported file type" in errors.get("image", "") else 400
        if "larger than 8 MB" in errors.get("image", ""):
            status_code = 413

        latency = _latency_ms(start)
        _log_request(
            latency_ms=latency,
            verdict="INVALID",
            failure_count=len(errors),
            content_type=content_type,
            upload_size=upload_size,
            event="verify_request_invalid",
        )
        return _error_response(
            status_code,
            "Please provide an image and all required label fields.",
            errors,
        )

    try:
        vision_service = vision_service_provider()
        result = await _verify_image_data(
            vision_service=vision_service,
            image_bytes=image_bytes or b"",
            filename=image.filename if image else None,
            content_type=content_type,
            fields=cleaned_fields,
        )
    except Exception:
        latency = _latency_ms(start)
        logger.exception(
            "verify_request_failed latency_ms=%s content_type=%s upload_size=%s",
            latency,
            content_type,
            upload_size,
        )
        return _error_response(
            500,
            "Verification failed unexpectedly.",
            {"server": "Unexpected internal failure."},
        )

    latency = _latency_ms(start)
    failure_count = sum(field.status == "FAIL" for field in result.verification.fields)
    _log_request(
        latency_ms=latency,
        verdict=result.verification.verdict,
        failure_count=failure_count,
        content_type=content_type,
        upload_size=upload_size,
    )

    return VerifyResponse(
        verification=result.verification,
        latency_ms=latency,
        extracted_label=result.extracted_label,
        timings={
            **result.timings,
            "image_read_ms": image_read_ms,
            "request_total_ms": latency,
            "failure_count": failure_count,
            "verdict": result.verification.verdict,
        },
    )


@router.post(
    "/verify/batch",
    response_model=BatchVerifyResponse,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def verify_batch_endpoint(
    vision_service_provider: Annotated[VisionServiceProvider, Depends(get_vision_service_provider)],
    images: Annotated[list[UploadFile] | None, File()] = None,
    items_json: OptionalForm = None,
) -> BatchVerifyResponse | JSONResponse:
    """Handle multipart batch verification for one to five labels.

    Inputs:
        `images` contains uploaded label photos. `items_json` is a JSON array of
        expected field dictionaries whose order must match `images`.

    Outputs:
        `BatchVerifyResponse` with aggregate counts and per-label results, or an
        `ErrorResponse` JSON body for invalid request shape, size limits, or
        unexpected server errors.
    """
    start = time.perf_counter()

    if not images:
        return _error_response(400, "Please add at least one label.", {"images": "At least one image is required."})

    if len(images) > MAX_BATCH_SIZE:
        return _error_response(
            400,
            "Please check no more than 5 labels at a time.",
            {"images": "Maximum batch size is 5."},
        )

    if not items_json:
        return _error_response(
            400,
            "Please provide application data for each label.",
            {"items_json": "Application data is required."},
        )

    try:
        items = json.loads(items_json)
    except json.JSONDecodeError:
        return _error_response(
            400,
            "Please provide valid application data for each label.",
            {"items_json": "Application data must be valid JSON."},
        )

    if not isinstance(items, list):
        return _error_response(
            400,
            "Please provide application data for each label.",
            {"items_json": "Application data must be a list."},
        )

    if not items:
        return _error_response(400, "Please add at least one label.", {"items_json": "At least one item is required."})

    if len(items) != len(images):
        return _error_response(
            400,
            "Each label needs one photo and one set of application data.",
            {"items_json": "Image count and application data count must match."},
        )

    try:
        total_upload_size = 0
        for image in images:
            data = await image.read()
            total_upload_size += len(data)
            if hasattr(image, "file"):
                image.file.seek(0)
    except Exception:
        logger.exception("verify_batch_upload_read_failed")
        return _error_response(
            400,
            "One or more images could not be read.",
            {"images": "Please choose valid image files."},
        )

    if total_upload_size > MAX_BATCH_UPLOAD_BYTES:
        return _error_response(
            413,
            "The selected photos are too large. Please keep the batch under 25 MB.",
            {"images": "Total upload is larger than 25 MB."},
        )

    try:
        vision_service = vision_service_provider()
        semaphore = asyncio.Semaphore(MAX_BATCH_SIZE)
        results = await asyncio.gather(
            *[
                _verify_batch_item(
                    index=index,
                    image=image,
                    item=item,
                    vision_service=vision_service,
                    semaphore=semaphore,
                )
                for index, (image, item) in enumerate(zip(images, items, strict=True))
            ]
        )
    except Exception:
        latency = _latency_ms(start)
        logger.exception("verify_batch_failed latency_ms=%s", latency)
        return _error_response(
            500,
            "Batch verification failed unexpectedly.",
            {"server": "Unexpected internal failure."},
        )

    passed = sum(item.status == "PASS" for item in results)
    needs_review = sum(item.status == "NEEDS_REVIEW" for item in results)
    latency = _latency_ms(start)

    logger.info(
        "verify_batch_complete latency_ms=%s passed=%s needs_review=%s total=%s",
        latency,
        passed,
        needs_review,
        len(results),
    )

    return BatchVerifyResponse(
        summary=BatchSummary(
            passed=passed,
            needs_review=needs_review,
            total=len(results),
            latency_ms=latency,
        ),
        results=results,
    )
