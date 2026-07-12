"""Vision extraction service.

This module owns the extraction prompt, JSON schema for model output, image
preprocessing, provider invocation, timing diagnostics, and defensive parsing of
structured results into `ExtractedLabel`.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import ValidationError

from app.verification.models import ExtractedLabel
from app.vision.client import OpenAIVisionClient, VisionClientProtocol
from app.vision.preprocessing import ImagePreprocessingError, prepare_image


DEFAULT_VISION_MODEL = "gpt-5.4-mini"
VISION_DETAIL = "high"
logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are extracting text fields from a photographed alcohol beverage label for a TTB label verification proof of concept.

Return only the structured JSON object required by the provided schema. Do not include explanations, markdown, or extra keys.

Extract these fields:

1. brand_name
   The brand name shown on the label.

2. class_type
   The product type or class shown on the label, such as wine, red wine, vodka, whiskey, beer, cider, or another visible class/type statement.

3. producer
   The producer, bottler, importer, winery, brewery, distillery, or responsible company shown on the label.
   Return only the business/entity name when present. Do not include role phrases or location text.
   For example, if the label says "VINTED & BOTTLED BY BAREFOOT WINES, MODESTO, CALIFORNIA",
   return "BAREFOOT WINES". If it says "BOTTLED BY SANTA RITA, SANTIAGO, CHILE", return
   "SANTA RITA".

4. country_of_origin
   The country of origin shown on the label. Return a country-level value, not a state, province,
   city, county, valley, appellation, or wine region. If the visible origin/location is an
   unambiguous state, province, or wine region, convert it to the country it belongs to.
   Examples: California, Napa Valley, Sonoma, Oregon, Washington, Modesto California -> USA;
   Ontario or British Columbia -> Canada; Mendoza -> Argentina; Bordeaux, Burgundy, Champagne,
   Loire, or Rhone -> France; Tuscany, Piedmont, Veneto, or Sicily -> Italy; Rioja or Priorat ->
   Spain; Douro or Vinho Verde -> Portugal; Marlborough or Hawke's Bay -> New Zealand; Barossa,
   South Australia, Victoria, or Tasmania -> Australia; Stellenbosch or Western Cape -> South
   Africa; Mosel or Rheingau -> Germany; Wachau or Burgenland -> Austria. If the country cannot
   be determined from visible country/region/state/province text, return null.

5. abv
   The alcohol by volume statement exactly as visible, such as "13.5% Alc. by Vol." or "40% ALC/VOL".
   Prefer the number attached to alcohol wording such as "% ALC", "% ALC/VOL", "% ABV", "% BY VOL",
   "% VOL", or "ALCOHOL BY VOLUME". Ignore unrelated OCR fragments near the percentage. If several
   number fragments are visible, return the percentage clearly connected to alcohol/volume wording.
   If the alcohol percentage is uncertain or cannot be read, return null instead of guessing.

6. net_contents
   The net contents statement exactly as visible, such as "750 mL", "1 L", or "12 FL OZ".

7. government_warning
   The government warning text exactly as visible on the label. This field is critical because the downstream verifier requires an exact, case-sensitive match.

8. raw_text
   The complete transcribed text visible on the label, preserving line breaks as much as possible.
   Include all readable label text, not just the seven verification fields. Return null if the label
   text is too blurry, blocked, cut off, or uncertain to transcribe with confidence.

9. extraction_confidence
   A number from 0 to 1 representing your confidence in the overall extraction. Use 1 only when all
   visible relevant text is clear and confidently extracted. Use lower values for blur, glare,
   cropping, difficult typography, or uncertainty. Return null if you cannot make a meaningful
   confidence estimate.

Rules:
- If a field is not visible, unreadable, blocked by glare, too blurry, cut off, or uncertain, return null for that field.
- Do not guess or infer values from context.
- For producer, remove role prefixes such as VINTED & BOTTLED BY, BOTTLED BY, PRODUCED BY,
  IMPORTED BY, CELLARED BY, DISTRIBUTED BY, and remove trailing city/state/country location suffixes.
- For country_of_origin, strongly prefer country-level output. Do not return state, province, city,
  county, valley, appellation, or region names when they can be mapped to a country.
- For abv, choose the percentage tied to alcohol/volume wording and ignore stray OCR letters or
  unrelated nearby numbers. Return null if uncertain.
- For government_warning, transcribe the visible warning verbatim character by character.
- Preserve the government_warning exact wording, capitalization, punctuation, colon, parentheses, periods, spacing, and line breaks as much as the image allows.
- Do not correct the government_warning into the standard legal text.
- Do not fix capitalization, spelling, punctuation, spacing, or wording in the government_warning.
- Do not normalize the government_warning.
- Do not summarize or rewrite the government_warning.
- If the government_warning is present but you cannot read it character by character, return null for government_warning.
- For raw_text, transcribe the complete readable label text and return null when the full visible text
  cannot be transcribed with confidence.
- For extraction_confidence, return a numeric confidence score between 0 and 1, or null when uncertain.
- For all other fields, copy the visible text as closely as possible without adding information.
- If the image is not an alcohol beverage label, return null for all fields, raw_text, and extraction_confidence.
- Return partial data when only some fields are readable.
"""


def null_extracted_label() -> ExtractedLabel:
    """Return an empty extraction result.

    Inputs:
        None.

    Outputs:
        `ExtractedLabel` with all fields set to `None`, used whenever image
        preprocessing, provider extraction, or schema validation fails.
    """
    return ExtractedLabel()


@dataclass(frozen=True)
class VisionExtractionResult:
    """Vision extraction output plus timing metadata.

    Inputs:
        `label` is the validated extracted label and `timings` contains
        preprocessing/provider/model diagnostic values.

    Outputs:
        A service-level result consumed by API handlers.
    """

    label: ExtractedLabel
    timings: dict[str, int | str | bool | None]


def build_extracted_label_schema() -> dict[str, Any]:
    """Build the strict JSON schema requested from the vision model.

    Inputs:
        None. Field names are derived from `ExtractedLabel`.

    Outputs:
        A schema requiring every expected key, allowing string fields to be
        string-or-null, confidence to be number-or-null, and rejecting
        additional properties.
    """
    properties = {}
    for field in ExtractedLabel.model_fields:
        if field == "extraction_confidence":
            properties[field] = {"type": ["number", "null"], "minimum": 0, "maximum": 1}
        else:
            properties[field] = {"type": ["string", "null"]}
    return {
        "type": "object",
        "properties": properties,
        "required": list(ExtractedLabel.model_fields),
        "additionalProperties": False,
    }


class VisionService:
    """High-level service for extracting label fields from an image.

    Inputs:
        A `VisionClientProtocol`, model name, and image-detail setting.

    Outputs:
        Async methods returning either an `ExtractedLabel` or
        `VisionExtractionResult` with timings.
    """

    def __init__(
        self,
        *,
        client: VisionClientProtocol,
        model: str = DEFAULT_VISION_MODEL,
        detail: str = VISION_DETAIL,
    ) -> None:
        """Initialize the service with its provider client and model settings.

        Inputs:
            `client` performs the provider call, `model` selects the vision
            model, and `detail` controls image detail passed to the provider.

        Outputs:
            A configured `VisionService` instance.
        """
        self.client = client
        self.model = model
        self.detail = detail

    @classmethod
    def from_env(cls, *, client: VisionClientProtocol | None = None) -> "VisionService":
        """Create a service from environment configuration.

        Inputs:
            Optional client override for tests. Without one, the real OpenAI
            client is created using environment variables.

        Outputs:
            A `VisionService` using `VISION_MODEL` or the default model.
        """
        model = os.environ.get("VISION_MODEL", DEFAULT_VISION_MODEL)
        return cls(client=client or OpenAIVisionClient(), model=model)

    async def extract_label(
        self,
        image_bytes: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        """Extract just the validated label fields from image bytes.

        Inputs:
            Raw image bytes plus optional filename and content type for future
            diagnostics.

        Outputs:
            An `ExtractedLabel`. Failures return all-null fields.
        """
        result = await self.extract_label_with_metrics(
            image_bytes,
            filename=filename,
            content_type=content_type,
        )
        return result.label

    async def extract_label_with_metrics(
        self,
        image_bytes: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> VisionExtractionResult:
        """Extract label fields and collect timing/provider diagnostics.

        Inputs:
            Raw image bytes plus optional filename and content type.

        Outputs:
            `VisionExtractionResult` containing the extracted label and metrics
            such as preprocessing time, provider time, prepared image size, and
            whether extraction failed.
        """
        total_start = time.perf_counter()
        preprocess_start = time.perf_counter()
        try:
            prepared = prepare_image(image_bytes)
        except ImagePreprocessingError:
            logger.warning("Vision extraction skipped because input is not a readable image.")
            return VisionExtractionResult(
                label=null_extracted_label(),
                timings={
                    "preprocess_ms": _elapsed_ms(preprocess_start),
                    "vision_ms": 0,
                    "prepared_image_bytes": None,
                    "prepared_image_width": None,
                    "prepared_image_height": None,
                    "model": self.model,
                    "vision_detail": self.detail,
                    "vision_extraction_failed": True,
                    "vision_total_ms": _elapsed_ms(total_start),
                },
            )

        vision_start = time.perf_counter()
        try:
            result = await self.client.extract_structured_label(
                image_bytes=prepared.data,
                prompt=EXTRACTION_PROMPT,
                schema=build_extracted_label_schema(),
                model=self.model,
                detail=self.detail,
            )
        except Exception as exc:
            logger.warning("Vision extraction failed with provider/client error: %s", type(exc).__name__)
            return VisionExtractionResult(
                label=null_extracted_label(),
                timings={
                    "preprocess_ms": _elapsed_ms(preprocess_start, end=vision_start),
                    "vision_ms": _elapsed_ms(vision_start),
                    "prepared_image_bytes": len(prepared.data),
                    "prepared_image_width": prepared.width,
                    "prepared_image_height": prepared.height,
                    "model": self.model,
                    "vision_detail": self.detail,
                    "vision_extraction_failed": True,
                    "vision_total_ms": _elapsed_ms(total_start),
                },
            )

        return VisionExtractionResult(
            label=_parse_extracted_label(result.structured_data, result.raw_json),
            timings={
                "preprocess_ms": _elapsed_ms(preprocess_start, end=vision_start),
                "vision_ms": _elapsed_ms(vision_start),
                "prepared_image_bytes": len(prepared.data),
                "prepared_image_width": prepared.width,
                "prepared_image_height": prepared.height,
                "model": self.model,
                "vision_detail": self.detail,
                "vision_extraction_failed": False,
                "vision_total_ms": _elapsed_ms(total_start),
            },
        )


def _elapsed_ms(start: float, *, end: float | None = None) -> int:
    """Calculate elapsed milliseconds for service timing metadata.

    Inputs:
        A `time.perf_counter()` start value and optional explicit end value.

    Outputs:
        Integer milliseconds between `start` and `end` or now.
    """
    return int(((end if end is not None else time.perf_counter()) - start) * 1000)


def _parse_extracted_label(
    structured_data: Mapping[str, Any] | None,
    raw_json: str | None,
) -> ExtractedLabel:
    """Parse and validate provider output into `ExtractedLabel`.

    Inputs:
        Parsed structured data from the provider, plus raw JSON text fallback.

    Outputs:
        A validated `ExtractedLabel`. Any malformed JSON, missing/extra keys, or
        validation error returns an all-null `ExtractedLabel`.
    """
    payload: Any = structured_data

    if payload is None and raw_json:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Vision extraction returned malformed structured JSON.")
            return null_extracted_label()

    if not isinstance(payload, Mapping):
        logger.warning("Vision extraction returned no structured object.")
        return null_extracted_label()

    expected_keys = set(ExtractedLabel.model_fields)
    if set(payload) != expected_keys:
        logger.warning("Vision extraction returned unexpected structured keys.")
        return null_extracted_label()

    try:
        return ExtractedLabel.model_validate(payload)
    except ValidationError:
        logger.warning("Vision extraction structured object failed validation.")
        return null_extracted_label()
