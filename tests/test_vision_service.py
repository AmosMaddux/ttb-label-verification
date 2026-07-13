import importlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.verification.models import ExtractedLabel
from app.vision.client import VisionClientResult, VisionConfigurationError
from app.vision.fakes import FakeVisionClient
import app.vision.preprocessing as preprocessing
import app.vision.service as vision_service_module
from app.vision.preprocessing import prepare_image
from app.vision.service import (
    EXTRACTION_PROMPT,
    VisionService,
    build_extracted_label_schema,
    null_extracted_label,
)


def image_bytes(size: tuple[int, int] = (600, 400), image_format: str = "PNG") -> bytes:
    image = Image.new("RGB", size, color=(255, 255, 255))
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def image_to_bytes(image: Image.Image, image_format: str = "PNG") -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def blurry_label_bytes() -> bytes:
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 120), "ACME RESERVE", fill="black")
    draw.text((80, 180), "13.5% Alc. by Vol.", fill="black")
    return image_to_bytes(image.filter(ImageFilter.GaussianBlur(radius=6)))


def cropped_label_bytes() -> bytes:
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 120), "ACME RESERVE", fill="black")
    draw.text((80, 180), "GOVERNMENT WARNING: cropped text", fill="black")
    return image_to_bytes(image.crop((0, 0, 450, 260)))


def glare_label_bytes() -> bytes:
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 120), "ACME RESERVE", fill="black")
    draw.text((80, 180), "750 mL", fill="black")
    draw.rectangle((40, 80, 860, 240), fill=(252, 252, 252))
    return image_to_bytes(image)


def non_label_image_bytes() -> bytes:
    image = Image.new("RGB", (500, 500), (200, 220, 240))
    draw = ImageDraw.Draw(image)
    draw.ellipse((120, 120, 380, 380), fill=(80, 130, 180))
    return image_to_bytes(image)


def populated_payload() -> dict[str, str | float]:
    return {
        "brand_name": "Acme Reserve",
        "class_type": "Red Wine",
        "producer": "Acme Winery LLC",
        "country_of_origin": "United States",
        "abv": "13.5% Alc. by Vol.",
        "net_contents": "750 mL",
        "government_warning": "GOVERNMENT WARNING: exact text",
        "raw_text": "Acme Reserve\nRed Wine\n13.5% Alc. by Vol.\n750 mL\nGOVERNMENT WARNING: exact text",
        "extraction_confidence": 0.94,
    }


def test_preprocessing_downscales_large_images_and_outputs_jpeg_rgb() -> None:
    prepared = prepare_image(image_bytes(size=(3000, 1200)))

    assert prepared.content_type == "image/jpeg"
    assert prepared.width == 800
    assert prepared.height == 320
    assert prepared.data.startswith(b"\xff\xd8")

    reopened = Image.open(BytesIO(prepared.data))
    assert reopened.format == "JPEG"
    assert reopened.mode == "RGB"


def test_preprocessing_uses_default_env_values_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_LONG_EDGE", raising=False)
    monkeypatch.delenv("JPEG_QUALITY", raising=False)
    importlib.reload(preprocessing)
    try:
        prepared = preprocessing.prepare_image(image_bytes(size=(3000, 1200)))

        assert preprocessing.MAX_LONG_EDGE == 800
        assert preprocessing.JPEG_QUALITY == 55
        assert prepared.width == 800
        assert prepared.height == 320
    finally:
        importlib.reload(preprocessing)
        importlib.reload(vision_service_module)


def test_preprocessing_honors_max_long_edge_env_on_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_LONG_EDGE", "600")
    importlib.reload(preprocessing)
    try:
        prepared = preprocessing.prepare_image(image_bytes(size=(3000, 1200)))

        assert preprocessing.MAX_LONG_EDGE == 600
        assert prepared.width == 600
        assert prepared.height == 240
    finally:
        monkeypatch.delenv("MAX_LONG_EDGE", raising=False)
        importlib.reload(preprocessing)
        importlib.reload(vision_service_module)


@pytest.mark.parametrize("env_var", ["MAX_LONG_EDGE", "JPEG_QUALITY"])
def test_preprocessing_rejects_invalid_integer_env(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
) -> None:
    monkeypatch.setenv(env_var, "large")
    try:
        with pytest.raises(VisionConfigurationError, match=env_var):
            importlib.reload(preprocessing)
    finally:
        monkeypatch.delenv(env_var, raising=False)
        importlib.reload(preprocessing)
        importlib.reload(vision_service_module)


def test_preprocessing_does_not_enlarge_small_images() -> None:
    prepared = prepare_image(image_bytes(size=(500, 300)))

    assert prepared.width == 500
    assert prepared.height == 300


def test_schema_matches_extracted_label_and_disallows_extra_properties() -> None:
    schema = build_extracted_label_schema()

    assert set(schema["properties"]) == set(ExtractedLabel.model_fields)
    assert schema["required"] == list(ExtractedLabel.model_fields)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["raw_text"]["type"] == ["string", "null"]
    assert schema["properties"]["extraction_confidence"]["type"] == ["number", "null"]
    assert schema["properties"]["extraction_confidence"]["minimum"] == 0
    assert schema["properties"]["extraction_confidence"]["maximum"] == 1
    assert all(
        property_schema["type"] == ["string", "null"]
        for field, property_schema in schema["properties"].items()
        if field != "extraction_confidence"
    )


def test_prompt_forces_verbatim_government_warning_capture() -> None:
    prompt = EXTRACTION_PROMPT.lower()

    for phrase in [
        "verbatim character by character",
        "capitalization",
        "punctuation",
        "colon",
        "spacing",
        "line breaks",
        "spelling",
        "do not correct",
        "do not normalize",
    ]:
        assert phrase in prompt


def test_prompt_guides_country_level_origin_extraction() -> None:
    prompt = EXTRACTION_PROMPT.lower()

    for phrase in [
        "return a country-level value",
        "not a state, province",
        "convert it to the country",
        "california",
        "mendoza",
        "bordeaux",
        "marlborough",
    ]:
        assert phrase in prompt


def test_prompt_guides_producer_cleanup() -> None:
    prompt = EXTRACTION_PROMPT.lower()

    for phrase in [
        "return only the business/entity name",
        "vinted & bottled by",
        "bottled by",
        "remove trailing city/state/country location suffixes",
        "barefoot wines",
    ]:
        assert phrase in prompt


def test_prompt_guides_abv_context_and_uncertainty() -> None:
    prompt = EXTRACTION_PROMPT.lower()

    for phrase in [
        "% alc/vol",
        "% by vol",
        "alcohol by volume",
        "ignore unrelated ocr fragments",
        "return null instead of guessing",
    ]:
        assert phrase in prompt


def test_prompt_guides_raw_text_and_confidence_extraction() -> None:
    prompt = EXTRACTION_PROMPT.lower()

    for phrase in [
        "raw_text",
        "complete transcribed text",
        "all readable label text",
        "extraction_confidence",
        "number from 0 to 1",
        "meaningful",
        "confidence estimate",
    ]:
        assert phrase in prompt


def test_prompt_requires_literal_evidence_for_brand_and_producer() -> None:
    prompt = EXTRACTION_PROMPT.lower()

    for phrase in [
        "transcribe raw_text before choosing",
        "derive brand_name and producer only from text visible in raw_text",
        "do not expand, normalize, infer, substitute, or repair",
        "outside knowledge",
        "business suffixes",
        "alternate company names",
        "return null instead of guessing",
    ]:
        assert phrase in prompt


@pytest.mark.anyio
async def test_service_returns_complete_structured_data_from_fake_client() -> None:
    fake = FakeVisionClient(VisionClientResult(structured_data=populated_payload()))
    service = VisionService(client=fake)

    extracted = await service.extract_label(image_bytes())

    assert fake.calls == 1
    assert fake.last_model == "gpt-5.4-nano"
    assert fake.last_detail == "high"
    assert extracted.brand_name == "Acme Reserve"
    assert extracted.government_warning == "GOVERNMENT WARNING: exact text"
    assert extracted.raw_text == "Acme Reserve\nRed Wine\n13.5% Alc. by Vol.\n750 mL\nGOVERNMENT WARNING: exact text"
    assert extracted.extraction_confidence == 0.94


@pytest.mark.anyio
async def test_service_returns_partial_null_data() -> None:
    payload = populated_payload()
    payload["producer"] = None
    payload["government_warning"] = None
    payload["raw_text"] = None
    payload["extraction_confidence"] = None
    service = VisionService(client=FakeVisionClient(VisionClientResult(structured_data=payload)))

    extracted = await service.extract_label(image_bytes())

    assert extracted.brand_name == "Acme Reserve"
    assert extracted.producer is None
    assert extracted.government_warning is None
    assert extracted.raw_text is None
    assert extracted.extraction_confidence is None


@pytest.mark.anyio
async def test_blurry_or_glare_response_does_not_throw() -> None:
    service = VisionService(client=FakeVisionClient(VisionClientResult(structured_data={"brand_name": None})))

    extracted = await service.extract_label(image_bytes())

    assert extracted == null_extracted_label()


@pytest.mark.anyio
async def test_non_label_image_returns_all_nulls() -> None:
    service = VisionService(client=FakeVisionClient(VisionClientResult(structured_data=null_extracted_label().model_dump())))

    extracted = await service.extract_label(image_bytes())

    assert extracted == null_extracted_label()


@pytest.mark.anyio
async def test_preprocessing_failure_sets_vision_extraction_failed_metric() -> None:
    fake = FakeVisionClient(VisionClientResult(structured_data=populated_payload()))
    service = VisionService(client=fake)

    result = await service.extract_label_with_metrics(b"not an image")

    assert fake.calls == 0
    assert result.label == null_extracted_label()
    assert result.timings["vision_extraction_failed"] is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    "result",
    [
        VisionClientResult(structured_data=None, raw_json=None),
        VisionClientResult(raw_json="{not json"),
        VisionClientResult(structured_data={**populated_payload(), "extra": "not allowed"}),
        VisionClientResult(structured_data={**populated_payload(), "brand_name": 123}),
        VisionClientResult(structured_data={"brand_name": "missing required keys"}),
    ],
)
async def test_malformed_structured_responses_return_all_nulls(result: VisionClientResult) -> None:
    service = VisionService(client=FakeVisionClient(result))

    extracted = await service.extract_label(image_bytes())

    assert extracted == null_extracted_label()


@pytest.mark.anyio
@pytest.mark.parametrize("confidence", [-0.01, 1.01])
async def test_out_of_range_extraction_confidence_returns_all_nulls(confidence: float) -> None:
    payload = populated_payload()
    payload["extraction_confidence"] = confidence
    service = VisionService(client=FakeVisionClient(VisionClientResult(structured_data=payload)))

    extracted = await service.extract_label(image_bytes())

    assert extracted == null_extracted_label()


@pytest.mark.anyio
async def test_json_response_is_parsed_defensively() -> None:
    service = VisionService(client=FakeVisionClient(VisionClientResult(raw_json=json.dumps(populated_payload()))))

    extracted = await service.extract_label(image_bytes())

    assert extracted.brand_name == "Acme Reserve"


@pytest.mark.anyio
@pytest.mark.parametrize("error", [TimeoutError("timeout"), RuntimeError("sdk error")])
async def test_api_timeout_or_client_error_returns_all_nulls(error: Exception) -> None:
    service = VisionService(client=FakeVisionClient(error))

    extracted = await service.extract_label(image_bytes())

    assert extracted == null_extracted_label()


@pytest.mark.anyio
async def test_provider_exception_sets_vision_extraction_failed_metric() -> None:
    fake = FakeVisionClient(RuntimeError("sdk error"))
    service = VisionService(client=fake)

    result = await service.extract_label_with_metrics(image_bytes())

    assert fake.calls == 1
    assert result.label == null_extracted_label()
    assert result.timings["vision_extraction_failed"] is True


@pytest.mark.anyio
async def test_structured_object_is_preferred_over_raw_text() -> None:
    fake = FakeVisionClient(
        VisionClientResult(
            structured_data=populated_payload(),
            raw_json="{bad raw text that must not be used",
        )
    )
    service = VisionService(client=fake)

    extracted = await service.extract_label(image_bytes())

    assert extracted.brand_name == "Acme Reserve"


@pytest.mark.anyio
async def test_non_image_bytes_return_all_nulls_without_calling_client() -> None:
    fake = FakeVisionClient(VisionClientResult(structured_data=populated_payload()))
    service = VisionService(client=fake)

    extracted = await service.extract_label(b"not an image")

    assert fake.calls == 0
    assert extracted == null_extracted_label()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "generated_image",
    [
        blurry_label_bytes(),
        cropped_label_bytes(),
        glare_label_bytes(),
    ],
)
async def test_imperfect_generated_images_degrade_to_partial_or_null_data(
    generated_image: bytes,
) -> None:
    payload = populated_payload()
    payload["producer"] = None
    payload["government_warning"] = None
    service = VisionService(client=FakeVisionClient(VisionClientResult(structured_data=payload)))

    extracted = await service.extract_label(generated_image)

    assert extracted.brand_name == "Acme Reserve"
    assert extracted.producer is None
    assert extracted.government_warning is None


@pytest.mark.anyio
async def test_generated_non_label_image_returns_all_nulls() -> None:
    fake = FakeVisionClient(VisionClientResult(structured_data=null_extracted_label().model_dump()))
    service = VisionService(client=fake)

    extracted = await service.extract_label(non_label_image_bytes())

    assert fake.calls == 1
    assert extracted == null_extracted_label()


def test_missing_api_key_produces_controlled_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(VisionConfigurationError):
        VisionService.from_env()


def test_env_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VISION_MODEL", "custom-vision-model")

    service = VisionService.from_env(client=FakeVisionClient(VisionClientResult(structured_data=populated_payload())))

    assert service.model == "custom-vision-model"


def test_sample_script_exists() -> None:
    assert Path("scripts/run_sample_extraction.py").exists()
