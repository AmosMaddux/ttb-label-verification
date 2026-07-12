import json
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.api.verify import get_vision_service_provider
from app.main import app
from app.verification.models import ExtractedLabel


CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)


class MockVisionService:
    def __init__(self, extracted: list[ExtractedLabel] | None = None) -> None:
        self.extracted = extracted or [matching_extracted_label()]
        self.calls = 0

    async def extract_label(
        self,
        image_bytes: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        result = self.extracted[min(self.calls, len(self.extracted) - 1)]
        self.calls += 1
        return result


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def image_bytes(image_format: str = "JPEG") -> bytes:
    image = Image.new("RGB", (80, 80), "white")
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


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


def form_data(**overrides: str) -> dict[str, str]:
    values = {
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


def file_tuple(
    *,
    name: str = "label.jpg",
    content: bytes | None = None,
    content_type: str = "image/jpeg",
) -> tuple[str, bytes, str]:
    return (name, content if content is not None else image_bytes(), content_type)


async def post_with_mock(
    mock: MockVisionService,
    path: str,
    *,
    data: dict[str, str],
    files: dict[str, tuple[str, bytes, str]] | list[tuple[str, tuple[str, bytes, str]]] | None = None,
) -> httpx.Response:
    async def override_provider():
        return lambda: mock

    app.dependency_overrides[get_vision_service_provider] = override_provider
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(path, data=data, files=files)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_verify_real_multipart_success() -> None:
    mock = MockVisionService()

    response = await post_with_mock(
        mock,
        "/verify",
        data=form_data(),
        files={"image": file_tuple()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["verdict"] == "PASS"
    assert len(body["verification"]["fields"]) == 7
    assert mock.calls == 1


@pytest.mark.anyio
async def test_verify_real_multipart_missing_image_returns_400() -> None:
    mock = MockVisionService()

    response = await post_with_mock(mock, "/verify", data=form_data())

    assert response.status_code == 400
    assert response.json()["errors"]["image"] == "Image file is required."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_verify_real_multipart_unsupported_content_type_returns_415() -> None:
    mock = MockVisionService()

    response = await post_with_mock(
        mock,
        "/verify",
        data=form_data(),
        files={"image": file_tuple(content=b"plain text", content_type="text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["errors"]["image"] == "Unsupported file type."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_verify_real_multipart_oversized_image_returns_413(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = MockVisionService()
    monkeypatch.setattr("app.api.verify.MAX_UPLOAD_BYTES", 128)

    response = await post_with_mock(
        mock,
        "/verify",
        data=form_data(),
        files={"image": file_tuple(content=b"x" * 129)},
    )

    assert response.status_code == 413
    assert response.json()["errors"]["image"] == "File is larger than 8 MB."
    assert mock.calls == 0


@pytest.mark.anyio
async def test_verify_real_multipart_warning_case_mismatch_returns_needs_review() -> None:
    title_case_warning = CANONICAL_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
    mock = MockVisionService([matching_extracted_label(government_warning=title_case_warning)])

    response = await post_with_mock(
        mock,
        "/verify",
        data=form_data(),
        files={"image": file_tuple()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["verdict"] == "NEEDS_REVIEW"
    warning = next(
        field for field in body["verification"]["fields"] if field["field"] == "government_warning"
    )
    assert warning["status"] == "FAIL"
    assert warning["extracted_value"] == title_case_warning


@pytest.mark.anyio
async def test_verify_real_multipart_warning_whitespace_only_difference_passes() -> None:
    warning_with_extra_space = CANONICAL_WARNING.replace(
        "GOVERNMENT WARNING:",
        "GOVERNMENT  WARNING:",
    )
    mock = MockVisionService([matching_extracted_label(government_warning=warning_with_extra_space)])

    response = await post_with_mock(
        mock,
        "/verify",
        data=form_data(),
        files={"image": file_tuple()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["verdict"] == "PASS"
    warning = next(
        field for field in body["verification"]["fields"] if field["field"] == "government_warning"
    )
    assert warning["status"] == "PASS"
    assert warning["extracted_value"] == warning_with_extra_space


@pytest.mark.anyio
async def test_verify_real_multipart_barefoot_style_normalization_passes() -> None:
    warning_with_newline = CANONICAL_WARNING.replace(
        "GOVERNMENT WARNING:",
        "GOVERNMENT WARNING:\n",
    )
    mock = MockVisionService(
        [
            ExtractedLabel(
                brand_name="BAREFOOT",
                class_type="PINK MOSCATO",
                producer="VINTED & BOTTLED BY BAREFOOT WINES, MODESTO, CALIFORNIA",
                country_of_origin="CALIFORNIA",
                abv="14.5%",
                net_contents="750 mL",
                government_warning=warning_with_newline,
            )
        ]
    )

    response = await post_with_mock(
        mock,
        "/verify",
        data=form_data(
            brand_name="BAREFOOT",
            class_type="PINK MOSCATO",
            producer="BAREFOOT WINES",
            country_of_origin="USA",
            abv="14.5%",
            net_contents="750mL",
            government_warning=CANONICAL_WARNING,
        ),
        files={"image": file_tuple()},
    )

    assert response.status_code == 200
    assert response.json()["verification"]["verdict"] == "PASS"


@pytest.mark.anyio
async def test_batch_real_multipart_size_one_success() -> None:
    mock = MockVisionService()

    response = await post_with_mock(
        mock,
        "/verify/batch",
        data={"items_json": json.dumps([form_data()])},
        files=[("images", file_tuple())],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["passed"] == 1
    assert body["summary"]["needs_review"] == 0
    assert body["summary"]["total"] == 1
    assert body["results"][0]["status"] == "PASS"
    assert mock.calls == 1


@pytest.mark.anyio
async def test_batch_real_multipart_mixed_summary_counts() -> None:
    mock = MockVisionService(
        [
            matching_extracted_label(),
            matching_extracted_label(brand_name="Wrong Brand"),
        ]
    )

    response = await post_with_mock(
        mock,
        "/verify/batch",
        data={"items_json": json.dumps([form_data(), form_data()])},
        files=[("images", file_tuple()), ("images", file_tuple(name="label-2.jpg"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["passed"] == 1
    assert body["summary"]["needs_review"] == 1
    assert [item["index"] for item in body["results"]] == [0, 1]
    assert mock.calls == 2


@pytest.mark.anyio
async def test_batch_real_multipart_mismatched_counts_returns_400() -> None:
    mock = MockVisionService()

    response = await post_with_mock(
        mock,
        "/verify/batch",
        data={"items_json": json.dumps([form_data(), form_data()])},
        files=[("images", file_tuple())],
    )

    assert response.status_code == 400
    assert response.json()["errors"]["items_json"] == "Image count and application data count must match."
    assert mock.calls == 0
