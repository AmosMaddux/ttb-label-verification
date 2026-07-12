import asyncio
import json
import logging
from io import BytesIO

import pytest
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import ValidationError

from app.api.models import BatchItemResult, BatchResult, VerifyResponse
from app.api.verify import _verify_image_data, verify_batch_endpoint, verify_endpoint
from app.verification.models import ExtractedLabel
from app.vision.client import VisionClientResult
from app.vision.fakes import FakeVisionClient
from app.vision.service import VisionExtractionResult, VisionService, null_extracted_label


CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)


class MockVisionService:
    def __init__(
        self,
        extracted: ExtractedLabel | None = None,
        error: Exception | None = None,
    ) -> None:
        self.extracted = extracted or matching_extracted_label()
        self.error = error
        self.calls = 0

    async def extract_label(
        self,
        image_bytes: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.extracted


class SequencedMockVisionService:
    def __init__(self, extracted: list[ExtractedLabel]) -> None:
        self.extracted = extracted
        self.calls = 0

    async def extract_label(
        self,
        image_bytes: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        result = self.extracted[self.calls]
        self.calls += 1
        return result


class SlowMockVisionService:
    def __init__(self, extracted: ExtractedLabel, delay: float = 0.05) -> None:
        self.extracted = extracted
        self.delay = delay
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def extract_label(
        self,
        image_bytes: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(self.delay)
        self.active -= 1
        return self.extracted


class MetricsMockVisionService:
    def __init__(self, extraction: VisionExtractionResult) -> None:
        self.extraction = extraction
        self.calls = 0

    async def extract_label_with_metrics(
        self,
        image_bytes: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> VisionExtractionResult:
        self.calls += 1
        return self.extraction


def image_bytes(image_format: str = "JPEG") -> bytes:
    image = Image.new("RGB", (64, 64), "white")
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


class MockUploadFile:
    def __init__(self, content: bytes | None = None, content_type: str = "image/jpeg") -> None:
        self._content = content if content is not None else image_bytes()
        self.content_type = content_type
        self.filename = "label.jpg"

    async def read(self) -> bytes:
        return self._content


def upload_file(content: bytes | None = None, content_type: str = "image/jpeg") -> MockUploadFile:
    return MockUploadFile(content=content, content_type=content_type)


def matching_extracted_label(**overrides: str | None) -> ExtractedLabel:
    values = {
        "brand_name": "Acme Reserve",
        "class_type": "Red Wine",
        "producer": "Acme Winery LLC",
        "country_of_origin": "USA",
        "abv": "13.5% Alc. by Vol.",
        "net_contents": "750ml",
        "government_warning": CANONICAL_WARNING,
    }
    values.update(overrides)
    return ExtractedLabel(**values)


def form_data(**overrides: str | None) -> dict[str, str | None]:
    values: dict[str, str | None] = {
        "brand_name": "Acme Reserve",
        "class_type": "Red Wine",
        "producer": "Acme Winery LLC",
        "country_of_origin": "United States",
        "abv": "13.5%",
        "net_contents": "750 mL",
        "government_warning": CANONICAL_WARNING,
    }
    values.update(overrides)
    return values


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def provider_for(mock: MockVisionService):
    return lambda: mock


def response_body(response: VerifyResponse | BatchResult | JSONResponse) -> dict:
    if isinstance(response, VerifyResponse | BatchResult):
        return response.model_dump(mode="json")
    return json.loads(response.body)


def response_status(response: VerifyResponse | BatchResult | JSONResponse) -> int:
    if isinstance(response, VerifyResponse | BatchResult):
        return 200
    return response.status_code


async def call_verify(
    mock: MockVisionService,
    *,
    data: dict[str, str | None] | None = None,
    image: MockUploadFile | None = None,
) -> VerifyResponse | JSONResponse:
    values = data if data is not None else form_data()
    return await verify_endpoint(
        vision_service_provider=provider_for(mock),
        image=image,
        brand_name=values.get("brand_name"),
        class_type=values.get("class_type"),
        producer=values.get("producer"),
        country_of_origin=values.get("country_of_origin"),
        abv=values.get("abv"),
        net_contents=values.get("net_contents"),
        government_warning=values.get("government_warning"),
    )


async def call_batch_verify(
    mock,
    *,
    items: list[dict[str, str | None]] | None = None,
    images: list[MockUploadFile] | None = None,
) -> BatchResult | JSONResponse:
    values = items if items is not None else [form_data()]
    upload_images = images if images is not None else [upload_file() for _ in values]
    return await verify_batch_endpoint(
        vision_service_provider=provider_for(mock),
        images=upload_images,
        items_json=json.dumps(values),
    )


@pytest.mark.anyio
async def test_successful_verify_returns_full_verification_result() -> None:
    mock = MockVisionService()

    response = await call_verify(mock, image=upload_file())
    body = response_body(response)

    assert response_status(response) == 200
    assert body["verification"]["overall_verdict"] == "APPROVED"
    assert len(body["verification"]["results"]) == 7
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0
    assert body["timings"]["request_total_ms"] >= 0
    assert body["timings"]["image_read_ms"] >= 0
    assert body["timings"]["compare_ms"] >= 0
    assert body["vision_extraction_failed"] is False
    assert body["extracted_label"]["government_warning"] == CANONICAL_WARNING
    assert mock.calls == 1


@pytest.mark.anyio
async def test_verify_response_flags_preprocessing_extraction_failure() -> None:
    service = VisionService(
        client=FakeVisionClient(
            VisionClientResult(structured_data=matching_extracted_label().model_dump())
        )
    )

    response = await _verify_image_data(
        vision_service=service,
        image_bytes=b"not an image",
        filename="bad.jpg",
        content_type="image/jpeg",
        fields=form_data(),
    )
    body = response.model_dump(mode="json")

    assert body["vision_extraction_failed"] is True
    assert body["timings"]["vision_extraction_failed"] is True


@pytest.mark.anyio
async def test_verify_response_flags_provider_extraction_failure() -> None:
    service = VisionService(client=FakeVisionClient(RuntimeError("provider boom")))

    response = await _verify_image_data(
        vision_service=service,
        image_bytes=image_bytes(),
        filename="label.jpg",
        content_type="image/jpeg",
        fields=form_data(),
    )
    body = response.model_dump(mode="json")

    assert body["vision_extraction_failed"] is True
    assert body["timings"]["vision_extraction_failed"] is True


@pytest.mark.anyio
async def test_failure_includes_expected_vs_found_and_overall_verdict() -> None:
    mock = MockVisionService(extracted=matching_extracted_label(brand_name="Wrong Brand"))

    response = await call_verify(mock, image=upload_file())
    body = response_body(response)
    brand_result = next(
        field for field in body["verification"]["results"] if field["field"] == "brand_name"
    )

    assert response_status(response) == 200
    assert body["verification"]["overall_verdict"] == "NEEDS_REVIEW"
    assert brand_result["status"] == "FAIL"
    assert brand_result["expected"] == "Acme Reserve"
    assert brand_result["found"] == "Wrong Brand"


@pytest.mark.anyio
async def test_warning_extracted_text_is_surfaced_on_failure() -> None:
    title_case_warning = CANONICAL_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
    mock = MockVisionService(extracted=matching_extracted_label(government_warning=title_case_warning))

    response = await call_verify(mock, image=upload_file())
    body = response_body(response)
    warning_result = next(
        field for field in body["verification"]["results"] if field["field"] == "government_warning"
    )

    assert response_status(response) == 200
    assert body["verification"]["overall_verdict"] == "NEEDS_REVIEW"
    assert body["extracted_label"]["government_warning"] == title_case_warning
    assert warning_result["found"] == title_case_warning


@pytest.mark.anyio
async def test_warning_whitespace_only_difference_passes_and_preserves_original() -> None:
    warning_with_newline = CANONICAL_WARNING.replace(
        "GOVERNMENT WARNING:",
        "GOVERNMENT WARNING:\n",
    )
    mock = MockVisionService(extracted=matching_extracted_label(government_warning=warning_with_newline))

    response = await call_verify(mock, image=upload_file())
    body = response_body(response)
    warning_result = next(
        field for field in body["verification"]["results"] if field["field"] == "government_warning"
    )

    assert response_status(response) == 200
    assert body["verification"]["overall_verdict"] == "APPROVED"
    assert warning_result["status"] == "PASS"
    assert warning_result["found"] == warning_with_newline
    assert warning_result["normalized_extracted_value"] == CANONICAL_WARNING


@pytest.mark.anyio
async def test_barefoot_style_cleaned_extraction_returns_pass() -> None:
    warning_with_newline = CANONICAL_WARNING.replace(
        "GOVERNMENT WARNING:",
        "GOVERNMENT WARNING:\n",
    )
    mock = MockVisionService(
        extracted=ExtractedLabel(
            brand_name="BAREFOOT",
            class_type="PINK MOSCATO",
            producer="VINTED & BOTTLED BY BAREFOOT WINES, MODESTO, CALIFORNIA",
            country_of_origin="CALIFORNIA",
            abv="14.5%",
            net_contents="750 mL",
            government_warning=warning_with_newline,
        )
    )

    response = await call_verify(
        mock,
        data=form_data(
            brand_name="BAREFOOT",
            class_type="PINK MOSCATO",
            producer="BAREFOOT WINES",
            country_of_origin="USA",
            abv="14.5%",
            net_contents="750mL",
            government_warning=CANONICAL_WARNING,
        ),
        image=upload_file(),
    )

    assert response_status(response) == 200
    assert response_body(response)["verification"]["overall_verdict"] == "APPROVED"


@pytest.mark.anyio
async def test_barefoot_style_bad_abv_returns_needs_review() -> None:
    warning_with_newline = CANONICAL_WARNING.replace(
        "GOVERNMENT WARNING:",
        "GOVERNMENT WARNING:\n",
    )
    mock = MockVisionService(
        extracted=ExtractedLabel(
            brand_name="BAREFOOT",
            class_type="PINK MOSCATO",
            producer="VINTED & BOTTLED BY BAREFOOT WINES, MODESTO, CALIFORNIA",
            country_of_origin="CALIFORNIA",
            abv="IA 5c, ME 15%",
            net_contents="750 mL",
            government_warning=warning_with_newline,
        )
    )

    response = await call_verify(
        mock,
        data=form_data(
            brand_name="BAREFOOT",
            class_type="PINK MOSCATO",
            producer="BAREFOOT WINES",
            country_of_origin="USA",
            abv="14.5%",
            net_contents="750mL",
            government_warning=CANONICAL_WARNING,
        ),
        image=upload_file(),
    )
    body = response_body(response)
    abv_result = next(field for field in body["verification"]["results"] if field["field"] == "abv")

    assert response_status(response) == 200
    assert body["verification"]["overall_verdict"] == "NEEDS_REVIEW"
    assert abv_result["status"] == "FAIL"


@pytest.mark.anyio
async def test_partial_extraction_returns_needs_review_not_exception() -> None:
    mock = MockVisionService(extracted=matching_extracted_label(producer=None, abv=None))

    response = await call_verify(mock, image=upload_file())

    assert response_status(response) == 200
    assert response_body(response)["verification"]["overall_verdict"] == "NEEDS_REVIEW"


@pytest.mark.anyio
async def test_missing_image_returns_400_readable_error() -> None:
    mock = MockVisionService()

    response = await call_verify(mock, image=None)

    assert response_status(response) == 400
    assert response_body(response)["errors"]["image"] == "Image file is required."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_empty_submission_returns_400_readable_error() -> None:
    mock = MockVisionService()

    response = await call_verify(
        mock,
        data={field: None for field in form_data()},
        image=None,
    )
    body = response_body(response)

    assert response_status(response) == 400
    assert body["message"] == "Please provide an image and all required label fields."
    assert body["errors"]["image"] == "Image file is required."
    assert body["errors"]["brand_name"] == "This field is required."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_unsupported_content_type_returns_415_and_does_not_call_vision() -> None:
    mock = MockVisionService()

    response = await call_verify(
        mock,
        image=upload_file(content=b"not an image", content_type="text/plain"),
    )

    assert response_status(response) == 415
    assert response_body(response)["errors"]["image"] == "Unsupported file type."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_unreadable_image_bytes_return_400_and_do_not_call_vision() -> None:
    mock = MockVisionService()

    response = await call_verify(
        mock,
        image=upload_file(content=b"not really a jpeg", content_type="image/jpeg"),
    )

    assert response_status(response) == 400
    assert response_body(response)["errors"]["image"] == "Image file could not be read."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_oversized_image_returns_413() -> None:
    mock = MockVisionService()

    response = await call_verify(mock, image=upload_file(content=b"x" * (8 * 1024 * 1024 + 1)))

    assert response_status(response) == 413
    assert response_body(response)["errors"]["image"] == "File is larger than 8 MB."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_missing_required_field_returns_400() -> None:
    mock = MockVisionService()
    data = form_data()
    data.pop("producer")

    response = await call_verify(mock, data=data, image=upload_file())

    assert response_status(response) == 400
    assert response_body(response)["errors"]["producer"] == "This field is required."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_empty_required_field_returns_400() -> None:
    mock = MockVisionService()

    response = await call_verify(mock, data=form_data(producer="   "), image=upload_file())

    assert response_status(response) == 400
    assert response_body(response)["errors"]["producer"] == "This field cannot be empty."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_mocked_vision_exception_returns_generic_500() -> None:
    mock = MockVisionService(error=RuntimeError("boom"))

    response = await call_verify(mock, image=upload_file())
    body = response_body(response)

    assert response_status(response) == 500
    assert body["message"] == "Verification failed unexpectedly."
    assert "boom" not in str(body)


@pytest.mark.anyio
async def test_latency_is_logged_for_success(caplog) -> None:
    mock = MockVisionService()

    with caplog.at_level(logging.INFO, logger="app.api.verify"):
        response = await call_verify(mock, image=upload_file())

    assert response_status(response) == 200
    assert any("verify_request_complete" in message for message in caplog.messages)


@pytest.mark.anyio
async def test_latency_is_logged_for_4xx(caplog) -> None:
    mock = MockVisionService()

    with caplog.at_level(logging.INFO, logger="app.api.verify"):
        response = await call_verify(mock, image=None)

    assert response_status(response) == 400
    assert any("verify_request_invalid" in message for message in caplog.messages)


@pytest.mark.anyio
async def test_slow_path_over_budget_logs_warning(caplog, monkeypatch) -> None:
    mock = MockVisionService()
    ticks = iter([0.0, 0.0, 0.1, 5.25])

    def fake_perf_counter() -> float:
        try:
            return next(ticks)
        except StopIteration:
            return 5.25

    monkeypatch.setattr("app.api.verify.time.perf_counter", fake_perf_counter)

    with caplog.at_level(logging.WARNING, logger="app.api.verify"):
        response = await call_verify(mock, image=upload_file())

    assert response_status(response) == 200
    assert response_body(response)["latency_ms"] == 5250
    assert any("exceeded_budget=True" in message for message in caplog.messages)


@pytest.mark.anyio
async def test_batch_size_one_returns_summary_and_result() -> None:
    mock = MockVisionService()

    response = await call_batch_verify(mock)
    body = response_body(response)

    assert response_status(response) == 200
    assert body["summary"]["passed"] == 1
    assert body["summary"]["needs_review"] == 0
    assert body["summary"]["total"] == 1
    assert body["items"][0]["index"] == 0
    assert body["items"][0]["status"] == "APPROVED"
    assert body["items"][0]["verification"]["overall_verdict"] == "APPROVED"
    assert body["items"][0]["timings"]["image_read_ms"] >= 0
    assert body["items"][0]["timings"]["compare_ms"] >= 0
    assert mock.calls == 1


@pytest.mark.anyio
async def test_batch_item_includes_vision_extraction_failed_flag() -> None:
    mock = MetricsMockVisionService(
        VisionExtractionResult(
            label=null_extracted_label(),
            timings={"vision_ms": 1, "vision_extraction_failed": True},
        )
    )

    response = await call_batch_verify(mock)
    body = response_body(response)

    assert response_status(response) == 200
    assert body["items"][0]["vision_extraction_failed"] is True
    assert body["items"][0]["timings"]["vision_extraction_failed"] is True
    assert mock.calls == 1


@pytest.mark.anyio
async def test_batch_mixed_results_have_correct_summary_counts() -> None:
    mock = SequencedMockVisionService(
        [
            matching_extracted_label(),
            matching_extracted_label(brand_name="Wrong Brand"),
        ]
    )

    response = await call_batch_verify(mock, items=[form_data(), form_data()])
    body = response_body(response)

    assert response_status(response) == 200
    assert body["summary"]["passed"] == 1
    assert body["summary"]["needs_review"] == 1
    assert body["summary"]["total"] == 2
    assert [item["index"] for item in body["items"]] == [0, 1]
    assert body["items"][0]["status"] == "APPROVED"
    assert body["items"][1]["status"] == "NEEDS_REVIEW"


@pytest.mark.anyio
async def test_batch_one_invalid_item_does_not_block_valid_items() -> None:
    mock = SequencedMockVisionService([matching_extracted_label(), matching_extracted_label()])
    invalid = form_data()
    invalid["producer"] = ""

    response = await call_batch_verify(
        mock,
        items=[form_data(), invalid, form_data()],
        images=[upload_file(), upload_file(), upload_file()],
    )
    body = response_body(response)

    assert response_status(response) == 200
    assert body["summary"]["passed"] == 2
    assert body["summary"]["needs_review"] == 1
    assert body["summary"]["total"] == 3
    assert body["items"][1]["status"] == "NEEDS_REVIEW"
    assert body["items"][1]["errors"]["producer"] == "This field cannot be empty."
    assert mock.calls == 2


@pytest.mark.anyio
async def test_batch_item_unsupported_file_type_is_isolated() -> None:
    mock = SequencedMockVisionService([matching_extracted_label(), matching_extracted_label()])

    response = await call_batch_verify(
        mock,
        items=[form_data(), form_data(), form_data()],
        images=[
            upload_file(),
            upload_file(content=b"not an image", content_type="text/plain"),
            upload_file(),
        ],
    )
    body = response_body(response)

    assert response_status(response) == 200
    assert body["summary"]["passed"] == 2
    assert body["summary"]["needs_review"] == 1
    assert body["items"][1]["errors"]["image"] == "Unsupported file type."
    assert mock.calls == 2


@pytest.mark.anyio
async def test_batch_item_vision_exception_is_isolated() -> None:
    mock = MockVisionService(error=RuntimeError("provider boom"))

    response = await call_batch_verify(mock, items=[form_data(), form_data()])
    body = response_body(response)

    assert response_status(response) == 200
    assert body["summary"]["passed"] == 0
    assert body["summary"]["needs_review"] == 2
    assert body["summary"]["total"] == 2
    assert body["items"][0]["errors"]["server"] == "Verification failed for this label."
    assert "provider boom" not in str(body)


@pytest.mark.anyio
async def test_batch_mismatched_image_and_data_counts_returns_400() -> None:
    mock = MockVisionService()

    response = await call_batch_verify(mock, items=[form_data(), form_data()], images=[upload_file()])

    assert response_status(response) == 400
    assert response_body(response)["errors"]["items_json"] == "Image count and application data count must match."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_batch_more_than_five_labels_returns_400() -> None:
    mock = MockVisionService()

    response = await call_batch_verify(
        mock,
        items=[form_data() for _ in range(6)],
        images=[upload_file() for _ in range(6)],
    )

    assert response_status(response) == 400
    assert response_body(response)["errors"]["images"] == "Maximum batch size is 5."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_batch_total_upload_over_25mb_returns_413() -> None:
    mock = MockVisionService()

    response = await call_batch_verify(
        mock,
        items=[form_data(), form_data(), form_data(), form_data()],
        images=[upload_file(content=b"x" * (7 * 1024 * 1024)) for _ in range(4)],
    )

    assert response_status(response) == 413
    assert response_body(response)["errors"]["images"] == "Total upload is larger than 25 MB."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_batch_slow_service_runs_concurrently() -> None:
    mock = SlowMockVisionService(matching_extracted_label())

    response = await call_batch_verify(
        mock,
        items=[form_data(), form_data(), form_data()],
        images=[upload_file(), upload_file(), upload_file()],
    )

    assert response_status(response) == 200
    assert response_body(response)["summary"]["passed"] == 3
    assert mock.calls == 3
    assert mock.max_active > 1


def test_batch_item_status_rejects_unexpected_values() -> None:
    with pytest.raises(ValidationError):
        BatchItemResult(
            index=0,
            filename="label.jpg",
            status="ERROR",
            latency_ms=1,
            errors={},
        )
