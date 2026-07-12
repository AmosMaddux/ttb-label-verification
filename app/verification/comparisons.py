"""Field comparison rules for TTB label verification.

This module turns expected application values and extracted vision-model values
into field-level pass/fail results. The comparison rules are intentionally
different by field: most text fields are fuzzy, country is normalized to a
country-level value, ABV/net contents are numeric, and the government warning is
case-sensitive after whitespace cleanup.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from app.verification.models import ApplicationData, ExtractedLabel, FieldResult, VerificationResult


FUZZY_THRESHOLD = 90.0
ML_PER_FLUID_OUNCE = 29.5735295625

_PUNCTUATION_PATTERN = re.compile(r"[^\w\s]", re.ASCII)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)")

_COUNTRY_SYNONYMS = {
    "argentina": "argentina",
    "australia": "australia",
    "austria": "austria",
    "canada": "canada",
    "chile": "chile",
    "france": "france",
    "germany": "germany",
    "italy": "italy",
    "new zealand": "new zealand",
    "portugal": "portugal",
    "south africa": "south africa",
    "spain": "spain",
    "usa": "united states",
    "us": "united states",
    "u s a": "united states",
    "u s": "united states",
    "united states": "united states",
    "united states of america": "united states",
    "uk": "united kingdom",
    "u k": "united kingdom",
    "great britain": "united kingdom",
    "united kingdom": "united kingdom",
}

_REGION_COUNTRY_SYNONYMS = {
    # United States wine states and regions.
    "alabama": "united states",
    "alaska": "united states",
    "arizona": "united states",
    "arkansas": "united states",
    "california": "united states",
    "ca": "united states",
    "colorado": "united states",
    "connecticut": "united states",
    "delaware": "united states",
    "florida": "united states",
    "hawaii": "united states",
    "idaho": "united states",
    "illinois": "united states",
    "indiana": "united states",
    "iowa": "united states",
    "kansas": "united states",
    "kentucky": "united states",
    "louisiana": "united states",
    "maine": "united states",
    "maryland": "united states",
    "massachusetts": "united states",
    "michigan": "united states",
    "minnesota": "united states",
    "mississippi": "united states",
    "missouri": "united states",
    "montana": "united states",
    "nebraska": "united states",
    "nevada": "united states",
    "new hampshire": "united states",
    "new jersey": "united states",
    "new mexico": "united states",
    "new york": "united states",
    "north carolina": "united states",
    "north dakota": "united states",
    "ohio": "united states",
    "oklahoma": "united states",
    "oregon": "united states",
    "pennsylvania": "united states",
    "rhode island": "united states",
    "south carolina": "united states",
    "south dakota": "united states",
    "tennessee": "united states",
    "texas": "united states",
    "utah": "united states",
    "vermont": "united states",
    "virginia": "united states",
    "washington": "united states",
    "west virginia": "united states",
    "wisconsin": "united states",
    "wyoming": "united states",
    "napa": "united states",
    "napa valley": "united states",
    "sonoma": "united states",
    "sonoma county": "united states",
    "willamette valley": "united states",
    "paso robles": "united states",
    # Canada.
    "ontario": "canada",
    "british columbia": "canada",
    "bc": "canada",
    "quebec": "canada",
    "nova scotia": "canada",
    "niagara": "canada",
    "okanagan": "canada",
    # Common wine regions outside North America.
    "mendoza": "argentina",
    "salta": "argentina",
    "patagonia": "argentina",
    "maipo": "chile",
    "colchagua": "chile",
    "casablanca": "chile",
    "aconcagua": "chile",
    "valle central": "chile",
    "bordeaux": "france",
    "burgundy": "france",
    "bourgogne": "france",
    "champagne": "france",
    "loire": "france",
    "rhone": "france",
    "alsace": "france",
    "languedoc": "france",
    "mosel": "germany",
    "rheingau": "germany",
    "pfalz": "germany",
    "baden": "germany",
    "tuscany": "italy",
    "toscana": "italy",
    "piedmont": "italy",
    "piemonte": "italy",
    "veneto": "italy",
    "sicily": "italy",
    "sicilia": "italy",
    "chianti": "italy",
    "rioja": "spain",
    "priorat": "spain",
    "ribera del duero": "spain",
    "rueda": "spain",
    "rias baixas": "spain",
    "douro": "portugal",
    "vinho verde": "portugal",
    "alentejo": "portugal",
    "dao": "portugal",
    "marlborough": "new zealand",
    "hawke s bay": "new zealand",
    "central otago": "new zealand",
    "barossa": "australia",
    "barossa valley": "australia",
    "south australia": "australia",
    "new south wales": "australia",
    "western australia": "australia",
    "victoria": "australia",
    "tasmania": "australia",
    "stellenbosch": "south africa",
    "western cape": "south africa",
    "paarl": "south africa",
    "swartland": "south africa",
    "constantia": "south africa",
    "wachau": "austria",
    "burgenland": "austria",
    "kamptal": "austria",
    "kremstal": "austria",
}

_PRODUCER_ROLE_PREFIXES = [
    "vinted and bottled by",
    "vinted bottled by",
    "vinted by",
    "bottled by",
    "produced and bottled by",
    "produced by",
    "imported by",
    "cellared by",
    "distributed by",
    "selected by",
    "made by",
]

_UNIT_TO_ML = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
    "cl": 10.0,
    "centiliter": 10.0,
    "centiliters": 10.0,
    "fl oz": ML_PER_FLUID_OUNCE,
    "fluid ounce": ML_PER_FLUID_OUNCE,
    "fluid ounces": ML_PER_FLUID_OUNCE,
}


def _collapse_whitespace(value: str) -> str:
    """Collapse all whitespace runs to one plain space.

    Inputs:
        Any string that may contain line breaks, tabs, repeated spaces, or
        leading/trailing whitespace.

    Outputs:
        A trimmed string with each whitespace run replaced by a single space.
    """
    return _WHITESPACE_PATTERN.sub(" ", value.strip())


def _normalize_fuzzy(value: str) -> str:
    """Normalize text for fuzzy comparison.

    Inputs:
        Raw label or application text.

    Outputs:
        Lowercase text with punctuation converted to spaces, whitespace
        collapsed, and common business suffix OCR spacing fixed.
    """
    without_punctuation = _PUNCTUATION_PATTERN.sub(" ", value)
    normalized = _collapse_whitespace(without_punctuation).lower()
    return (
        normalized.replace("l l c", "llc")
        .replace("l t d", "ltd")
        .replace("i n c", "inc")
    )


def _normalize_country(value: str) -> str:
    """Map countries, aliases, states, provinces, and wine regions to countries.

    Inputs:
        Raw origin text such as `USA`, `California`, `Mendoza`, `Bordeaux`, or a
        longer phrase containing a known region.

    Outputs:
        A canonical country string when recognized, otherwise the generic fuzzy
        normalized value.
    """
    normalized = _normalize_fuzzy(value)
    if normalized in _COUNTRY_SYNONYMS:
        return _COUNTRY_SYNONYMS[normalized]
    if normalized in _REGION_COUNTRY_SYNONYMS:
        return _REGION_COUNTRY_SYNONYMS[normalized]

    padded = f" {normalized} "
    for region, country in sorted(
        _REGION_COUNTRY_SYNONYMS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if f" {region} " in padded:
            return country
    return normalized


def _strip_producer_role_prefix(normalized: str) -> str:
    """Remove common producer/importer/bottler lead-in phrases.

    Inputs:
        Producer text that has already been fuzzy-normalized.

    Outputs:
        The same text with a known role prefix removed when present.
    """
    for prefix in _PRODUCER_ROLE_PREFIXES:
        if normalized.startswith(f"{prefix} "):
            return normalized[len(prefix) + 1 :].strip()
    return normalized


def _is_known_location_chunk(chunk: str) -> bool:
    """Detect whether a comma-separated producer suffix looks like a location.

    Inputs:
        One chunk of producer text, usually a city, state, province, region, or
        country after a comma.

    Outputs:
        `True` when the chunk can be recognized as a country or mapped region;
        otherwise `False`.
    """
    normalized = _normalize_fuzzy(chunk)
    return (
        normalized in _COUNTRY_SYNONYMS
        or normalized in _REGION_COUNTRY_SYNONYMS
        or _normalize_country(normalized) != normalized
    )


def _normalize_producer(value: str) -> str:
    """Normalize producer text to the business/entity name most likely to match.

    Inputs:
        Raw producer text from the application or extraction, including possible
        role phrases and comma-separated location suffixes.

    Outputs:
        Fuzzy-normalized producer text with known role prefixes and trailing
        location suffixes removed.
    """
    role_stripped_value = _strip_producer_role_prefix(_normalize_fuzzy(value))
    chunks = [chunk.strip() for chunk in value.split(",") if chunk.strip()]
    if len(chunks) > 1 and any(_is_known_location_chunk(chunk) for chunk in chunks[1:]):
        role_stripped_value = _strip_producer_role_prefix(_normalize_fuzzy(chunks[0]))
    return role_stripped_value


def _token_sort_ratio(application: str, extracted: str) -> float:
    """Score two normalized strings with RapidFuzz token-sort matching.

    Inputs:
        Normalized expected and extracted strings.

    Outputs:
        A float from 0 to 100, where higher means a closer token-insensitive
        match.
    """
    return float(fuzz.token_sort_ratio(application, extracted))


def _missing_result(field: str, application: str, match_type: str) -> FieldResult:
    """Build the standard failed result for a missing extracted value.

    Inputs:
        Field name, expected application value, and match type name.

    Outputs:
        A `FieldResult` with `FAIL`, no extracted value, and a missing-value
        message.
    """
    return FieldResult(
        field=field,
        status="FAIL",
        expected=application,
        found=None,
        match_type=match_type,
        message="Extracted value is missing.",
    )


def _compare_fuzzy(field: str, application: str, extracted: str | None) -> FieldResult:
    """Compare a generic text field with fuzzy token-sort matching.

    Inputs:
        Field name, expected application text, and optional extracted text.

    Outputs:
        A `FieldResult` whose status passes when the normalized RapidFuzz score
        reaches `FUZZY_THRESHOLD`.
    """
    match_type = "fuzzy_token_sort_ratio"
    if extracted is None:
        return _missing_result(field, application, match_type)

    normalized_application = _normalize_fuzzy(application)
    normalized_extracted = _normalize_fuzzy(extracted)
    score = _token_sort_ratio(normalized_application, normalized_extracted)
    status = "PASS" if score >= FUZZY_THRESHOLD else "FAIL"

    return FieldResult(
        field=field,
        status=status,
        expected=application,
        found=extracted,
        match_type=match_type,
        score=score,
        normalized_application_value=normalized_application,
        normalized_extracted_value=normalized_extracted,
        message="Fuzzy match passed." if status == "PASS" else "Fuzzy match failed.",
    )


def compare_brand_name(application: str, extracted: str | None) -> FieldResult:
    """Compare the brand name field.

    Inputs:
        Expected brand text and optional extracted brand text.

    Outputs:
        A fuzzy `FieldResult` for `brand_name`.
    """
    return _compare_fuzzy("brand_name", application, extracted)


def compare_product_class(application: str, extracted: str | None) -> FieldResult:
    """Compare the product class/type field.

    Inputs:
        Expected product class text and optional extracted class text.

    Outputs:
        A fuzzy `FieldResult` for `class_type`.
    """
    return _compare_fuzzy("class_type", application, extracted)


def compare_producer(application: str, extracted: str | None) -> FieldResult:
    """Compare producer names after producer-specific cleanup.

    Inputs:
        Expected producer text and optional extracted producer text.

    Outputs:
        A `FieldResult` using the better of token-sort and token-set RapidFuzz
        scores after removing role prefixes and known location suffixes.
    """
    match_type = "producer_fuzzy_token_sort_ratio"
    if extracted is None:
        return _missing_result("producer", application, match_type)

    normalized_application = _normalize_producer(application)
    normalized_extracted = _normalize_producer(extracted)
    score = max(
        _token_sort_ratio(normalized_application, normalized_extracted),
        float(fuzz.token_set_ratio(normalized_application, normalized_extracted)),
    )
    status = "PASS" if score >= FUZZY_THRESHOLD else "FAIL"

    return FieldResult(
        field="producer",
        status=status,
        expected=application,
        found=extracted,
        match_type=match_type,
        score=score,
        normalized_application_value=normalized_application,
        normalized_extracted_value=normalized_extracted,
        message="Fuzzy match passed." if status == "PASS" else "Fuzzy match failed.",
    )


def compare_country_of_origin(application: str, extracted: str | None) -> FieldResult:
    """Compare origin as a canonical country-level value.

    Inputs:
        Expected country text and optional extracted country, state, province,
        appellation, or wine-region text.

    Outputs:
        A `FieldResult` that passes only when both sides normalize to the same
        canonical country string.
    """
    match_type = "country_synonym_exact"
    if extracted is None:
        return _missing_result("country_of_origin", application, match_type)

    normalized_application = _normalize_country(application)
    normalized_extracted = _normalize_country(extracted)
    status = "PASS" if normalized_application == normalized_extracted else "FAIL"

    return FieldResult(
        field="country_of_origin",
        status=status,
        expected=application,
        found=extracted,
        match_type=match_type,
        normalized_application_value=normalized_application,
        normalized_extracted_value=normalized_extracted,
        message="Country matched." if status == "PASS" else "Country did not match.",
    )


def _parse_abv(value: str) -> float | None:
    """Extract an alcohol-by-volume percentage from text.

    Inputs:
        Raw ABV text that may include percent signs, alcohol/volume context,
        proof, or OCR noise.

    Outputs:
        A floating-point ABV value when a plausible number is found, preferring
        percentages tied to alcohol wording, or `None` when no number exists.
    """
    normalized = value.lower()
    matches = list(_NUMBER_PATTERN.finditer(normalized))
    if not matches:
        return None

    context_percent_candidates: list[float] = []
    percent_candidates: list[float] = []
    proof_candidates: list[float] = []
    plain_candidates: list[float] = []

    for match in matches:
        number = float(match.group(1))
        before = normalized[max(0, match.start() - 12) : match.start()]
        after = normalized[match.end() : match.end() + 24]
        context = f"{before} {after}"

        if "proof" in after[:10]:
            proof_candidates.append(number / 2)
        elif "%" in after[:4] and re.search(r"alc|vol|abv|alcohol|by\s+vol", context):
            context_percent_candidates.append(number)
        elif "%" in after[:4]:
            percent_candidates.append(number)
        else:
            plain_candidates.append(number)

    if context_percent_candidates:
        return context_percent_candidates[0]
    if percent_candidates:
        return percent_candidates[0]
    if proof_candidates:
        return proof_candidates[0]
    return plain_candidates[0]


def compare_abv(application: str, extracted: str | None) -> FieldResult:
    """Compare ABV values numerically within a small tolerance.

    Inputs:
        Expected ABV text and optional extracted ABV text.

    Outputs:
        A `FieldResult` that passes when both values parse and differ by no more
        than 0.1 percentage points.
    """
    match_type = "abv_numeric_tolerance"
    if extracted is None:
        return _missing_result("abv", application, match_type)

    application_abv = _parse_abv(application)
    extracted_abv = _parse_abv(extracted)

    if application_abv is None or extracted_abv is None:
        status = "FAIL"
    else:
        status = "PASS" if abs(application_abv - extracted_abv) <= 0.1 else "FAIL"

    return FieldResult(
        field="abv",
        status=status,
        expected=application,
        found=extracted,
        match_type=match_type,
        normalized_application_value=None if application_abv is None else str(application_abv),
        normalized_extracted_value=None if extracted_abv is None else str(extracted_abv),
        message="ABV matched within tolerance." if status == "PASS" else "ABV did not match.",
    )


def _parse_net_contents(value: str) -> float | None:
    """Convert a net-contents string into milliliters.

    Inputs:
        Raw net contents such as `750 mL`, `1 L`, `75 cl`, or `25.4 fl oz`.

    Outputs:
        The amount in milliliters, or `None` when no supported amount/unit pair
        is found.
    """
    normalized = _collapse_whitespace(value.lower().replace(".", " "))
    normalized = re.sub(r"(?<=\d)\s+(?=\d)", ".", normalized)
    unit_pattern = "|".join(
        sorted((re.escape(unit) for unit in _UNIT_TO_ML), key=len, reverse=True)
    )
    match = re.search(rf"(\d+(?:\.\d+)?)\s*({unit_pattern})\b", normalized)
    if not match:
        return None

    amount = float(match.group(1))
    unit = match.group(2)
    return amount * _UNIT_TO_ML[unit]


def compare_net_contents(application: str, extracted: str | None) -> FieldResult:
    """Compare net contents after converting both sides to milliliters.

    Inputs:
        Expected net contents text and optional extracted net contents text.

    Outputs:
        A `FieldResult` that passes when both parsed milliliter amounts are
        within 1 mL.
    """
    match_type = "net_contents_ml_tolerance"
    if extracted is None:
        return _missing_result("net_contents", application, match_type)

    application_ml = _parse_net_contents(application)
    extracted_ml = _parse_net_contents(extracted)

    if application_ml is None or extracted_ml is None:
        status = "FAIL"
    else:
        status = "PASS" if abs(application_ml - extracted_ml) <= 1.0 else "FAIL"

    return FieldResult(
        field="net_contents",
        status=status,
        expected=application,
        found=extracted,
        match_type=match_type,
        normalized_application_value=None if application_ml is None else str(application_ml),
        normalized_extracted_value=None if extracted_ml is None else str(extracted_ml),
        message=(
            "Net contents matched within tolerance."
            if status == "PASS"
            else "Net contents did not match."
        ),
    )


def compare_government_warning(application: str, extracted: str | None) -> FieldResult:
    """Compare the government warning with strict text and lenient whitespace.

    Inputs:
        Expected government warning text and optional extracted warning text.

    Outputs:
        A `FieldResult` that passes only when wording, case, and punctuation are
        identical after line breaks and repeated whitespace are collapsed.
    """
    match_type = "exact_case_sensitive_whitespace_collapsed"
    if extracted is None:
        return _missing_result("government_warning", application, match_type)

    normalized_application = _collapse_whitespace(application)
    normalized_extracted = _collapse_whitespace(extracted)
    status = "PASS" if normalized_application == normalized_extracted else "FAIL"

    return FieldResult(
        field="government_warning",
        status=status,
        expected=application,
        found=extracted,
        match_type=match_type,
        normalized_application_value=normalized_application,
        normalized_extracted_value=normalized_extracted,
        message=(
            "Government warning matched after whitespace cleanup."
            if status == "PASS"
            else "Government warning wording, capitalization, and punctuation must match."
        ),
    )


def verify_label(application: ApplicationData, extracted: ExtractedLabel) -> VerificationResult:
    """Run every field comparison and calculate the final verdict.

    Inputs:
        `ApplicationData` with expected values and `ExtractedLabel` with the
        vision-model output.

    Outputs:
        A `VerificationResult` containing seven ordered field results and
        `APPROVED` only when every field passes; otherwise `NEEDS_REVIEW`.
    """
    fields = [
        compare_brand_name(application.brand_name, extracted.brand_name),
        compare_product_class(application.class_type, extracted.class_type),
        compare_producer(application.producer, extracted.producer),
        compare_country_of_origin(application.country_of_origin, extracted.country_of_origin),
        compare_abv(application.abv, extracted.abv),
        compare_net_contents(application.net_contents, extracted.net_contents),
        compare_government_warning(application.government_warning, extracted.government_warning),
    ]
    overall_verdict = "NEEDS_REVIEW" if any(field.status == "FAIL" for field in fields) else "APPROVED"
    return VerificationResult(overall_verdict=overall_verdict, latency_ms=0, results=fields)
