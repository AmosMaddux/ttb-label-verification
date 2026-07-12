import pytest

from app.verification.comparisons import (
    compare_abv,
    compare_brand_name,
    compare_country_of_origin,
    compare_government_warning,
    compare_net_contents,
    compare_producer,
    compare_product_class,
    verify_label,
)
from app.verification.models import ApplicationData, ExtractedLabel, FieldResult, VerificationResult


CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)

BAREFOOT_WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD NOT DRINK "
    "ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF BIRTH DEFECTS. "
    "(2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO DRIVE A CAR OR "
    "OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
)

BAREFOOT_WARNING_WITH_LINE_BREAKS = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON\n"
    "GENERAL, WOMEN SHOULD NOT DRINK ALCOHOLIC\n"
    "BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF\n"
    "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES\n"
    "IMPAIRS YOUR ABILITY TO DRIVE A CAR OR OPERATE\n"
    "MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
)


def make_application(**overrides: str) -> ApplicationData:
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
    return ApplicationData(**values)


def make_extracted(**overrides: str | None) -> ExtractedLabel:
    values = {
        "brand_name": "Acme Reserve",
        "class_type": "Red Wine",
        "producer": "Acme Winery LLC",
        "country_of_origin": "USA",
        "abv": "13.5 % alc/vol",
        "net_contents": "750ml",
        "government_warning": CANONICAL_WARNING,
    }
    values.update(overrides)
    return ExtractedLabel(**values)


def test_models_accept_and_serialize_expected_shapes() -> None:
    application = make_application()
    extracted = ExtractedLabel()
    field = FieldResult(
        field="brand_name",
        status="PASS",
        expected="Acme",
        found="acme",
        match_type="fuzzy",
        score=100.0,
        normalized_application_value="acme",
        normalized_extracted_value="acme",
        message="Matched",
    )
    result = VerificationResult(overall_verdict="APPROVED", latency_ms=0, results=[field])

    assert application.brand_name == "Acme Reserve"
    assert extracted.brand_name is None
    assert result.model_dump()["results"][0]["status"] == "PASS"


def test_brand_exact_match_passes() -> None:
    result = compare_brand_name("Acme Reserve", "Acme Reserve")

    assert result.status == "PASS"


def test_brand_case_only_difference_passes() -> None:
    result = compare_brand_name("ACME RESERVE", "acme reserve")

    assert result.status == "PASS"


def test_brand_case_and_punctuation_difference_passes() -> None:
    result = compare_brand_name("Acme Reserve!", "acme, reserve")

    assert result.status == "PASS"


def test_brand_token_order_difference_passes() -> None:
    result = compare_brand_name("Reserve Acme", "Acme Reserve")

    assert result.status == "PASS"
    assert result.score == 100.0


def test_brand_minor_ocr_typo_above_threshold_passes() -> None:
    result = compare_brand_name("Acme Reserve", "Acme Resrve")

    assert result.status == "PASS"
    assert result.score is not None
    assert result.score >= 90.0


def test_brand_materially_different_value_fails() -> None:
    result = compare_brand_name("Acme Reserve", "Harbor Lager")

    assert result.status == "FAIL"


def test_class_type_fuzzy_equivalent_passes() -> None:
    result = compare_product_class("Cabernet Sauvignon", "cabernet-sauvignon")

    assert result.status == "PASS"


def test_class_type_wrong_class_fails() -> None:
    result = compare_product_class("Red Wine", "Vodka")

    assert result.status == "FAIL"


def test_producer_punctuation_variation_passes() -> None:
    result = compare_producer("Acme Winery LLC", "ACME Winery, L.L.C.")

    assert result.status == "PASS"


def test_producer_role_and_location_variation_passes() -> None:
    result = compare_producer(
        "BAREFOOT WINES",
        "VINTED & BOTTLED BY BAREFOOT WINES, MODESTO, CALIFORNIA",
    )

    assert result.status == "PASS"
    assert result.normalized_extracted_value == "barefoot wines"


def test_producer_produced_by_location_variation_passes() -> None:
    result = compare_producer("Acme Winery LLC", "PRODUCED BY ACME WINERY, NAPA, CALIFORNIA")

    assert result.status == "PASS"


def test_producer_non_us_location_variation_passes() -> None:
    result = compare_producer("Santa Rita", "BOTTLED BY SANTA RITA, SANTIAGO, CHILE")

    assert result.status == "PASS"


def test_producer_location_only_extracted_value_fails() -> None:
    result = compare_producer("BAREFOOT WINES", "MODESTO, CALIFORNIA")

    assert result.status == "FAIL"


def test_producer_unrelated_name_fails() -> None:
    result = compare_producer("Acme Winery LLC", "Different Cellars")

    assert result.status == "FAIL"


def test_fuzzy_score_exactly_at_threshold_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.verification.comparisons._token_sort_ratio", lambda _a, _b: 90.0)

    result = compare_brand_name("Acme Reserve", "Almost Acme")

    assert result.status == "PASS"
    assert result.score == 90.0


def test_country_usa_matches_united_states() -> None:
    result = compare_country_of_origin("USA", "United States")

    assert result.status == "PASS"
    assert result.normalized_application_value == "united states"
    assert result.normalized_extracted_value == "united states"


def test_country_usa_dotted_matches_united_states_of_america() -> None:
    result = compare_country_of_origin("U.S.A.", "United States of America")

    assert result.status == "PASS"


@pytest.mark.parametrize(
    ("application", "extracted"),
    [
        ("USA", "California"),
        ("United States", "CALIFORNIA"),
        ("USA", "Modesto, California"),
        ("United States", "Napa Valley"),
        ("USA", "Sonoma County"),
        ("Canada", "Ontario"),
        ("Canada", "British Columbia"),
        ("Argentina", "Mendoza"),
        ("France", "Bordeaux"),
        ("France", "Burgundy"),
        ("Italy", "Tuscany"),
        ("Italy", "Piedmont"),
        ("Spain", "Rioja"),
        ("Spain", "Priorat"),
        ("Portugal", "Douro"),
        ("Germany", "Mosel"),
        ("Austria", "Wachau"),
        ("New Zealand", "Marlborough"),
        ("Australia", "Barossa Valley"),
        ("South Africa", "Western Cape"),
        ("Chile", "Maipo"),
    ],
)
def test_country_regions_and_subdivisions_match_country(
    application: str,
    extracted: str,
) -> None:
    result = compare_country_of_origin(application, extracted)

    assert result.status == "PASS"


def test_country_case_and_punctuation_differences_pass() -> None:
    result = compare_country_of_origin("u.s.", "UNITED STATES")

    assert result.status == "PASS"


def test_country_different_countries_fail() -> None:
    result = compare_country_of_origin("United States", "Canada")

    assert result.status == "FAIL"


def test_unknown_country_strings_pass_only_when_normalized_exact_values_match() -> None:
    matching = compare_country_of_origin("Atlantis!", " atlantis ")
    different = compare_country_of_origin("Atlantis", "El Dorado")

    assert matching.status == "PASS"
    assert different.status == "FAIL"


def test_missing_extracted_country_fails() -> None:
    result = compare_country_of_origin("United States", None)

    assert result.status == "FAIL"


def test_abv_percent_matches_alc_vol() -> None:
    result = compare_abv("13.5%", "13.5 % alc/vol")

    assert result.status == "PASS"


def test_abv_with_alcohol_context_after_garbage_prefix_passes() -> None:
    result = compare_abv("14.5%", "IA 5c, 14.5% ALC/VOL")

    assert result.status == "PASS"
    assert result.normalized_extracted_value == "14.5"


def test_abv_bad_ocr_percent_does_not_get_loosened_to_pass() -> None:
    result = compare_abv("14.5%", "IA 5c, ME 15%")

    assert result.status == "FAIL"
    assert result.normalized_extracted_value == "15.0"


def test_abv_labeled_before_number_matches() -> None:
    result = compare_abv("14.5%", "ALC. 14.5% BY VOL")

    assert result.status == "PASS"


def test_abv_labeled_value_matches_plain_number() -> None:
    result = compare_abv("ALC 13.50% BY VOL", "13.5")

    assert result.status == "PASS"


def test_abv_ignores_proof_when_percent_is_present() -> None:
    result = compare_abv("45%", "45% Alc./Vol. (90 Proof)")

    assert result.status == "PASS"
    assert result.normalized_application_value == "45.0"
    assert result.normalized_extracted_value == "45.0"


def test_abv_difference_within_tolerance_passes() -> None:
    result = compare_abv("13.5%", "13.6%")

    assert result.status == "PASS"


def test_abv_difference_greater_than_tolerance_fails() -> None:
    result = compare_abv("13.5%", "13.7%")

    assert result.status == "FAIL"


def test_missing_extracted_abv_fails() -> None:
    result = compare_abv("13.5%", None)

    assert result.status == "FAIL"


def test_unparseable_abv_fails() -> None:
    result = compare_abv("13.5%", "not listed")

    assert result.status == "FAIL"


def test_net_contents_ml_spacing_difference_passes() -> None:
    result = compare_net_contents("750 mL", "750ml")

    assert result.status == "PASS"
    assert result.normalized_application_value == "750.0"
    assert result.normalized_extracted_value == "750.0"


def test_net_contents_liters_passes() -> None:
    result = compare_net_contents("750 ml", "0.75 L")

    assert result.status == "PASS"


def test_net_contents_centiliters_passes() -> None:
    result = compare_net_contents("750 ml", "75 cl")

    assert result.status == "PASS"


def test_net_contents_fluid_ounces_passes_within_tolerance() -> None:
    result = compare_net_contents("750 ml", "25.36 fl oz")

    assert result.status == "PASS"


def test_net_contents_different_sizes_fail() -> None:
    result = compare_net_contents("750 ml", "500 ml")

    assert result.status == "FAIL"


def test_missing_extracted_net_contents_fails() -> None:
    result = compare_net_contents("750 ml", None)

    assert result.status == "FAIL"


def test_unparseable_net_contents_fails() -> None:
    result = compare_net_contents("750 ml", "one bottle")

    assert result.status == "FAIL"


def test_government_warning_exact_all_caps_warning_passes() -> None:
    result = compare_government_warning(CANONICAL_WARNING, CANONICAL_WARNING)

    assert result.status == "PASS"


def test_government_warning_title_case_fails() -> None:
    title_case_warning = CANONICAL_WARNING.replace("GOVERNMENT WARNING", "Government Warning")

    result = compare_government_warning(CANONICAL_WARNING, title_case_warning)

    assert result.status == "FAIL"


def test_government_warning_lowercase_fails() -> None:
    result = compare_government_warning(CANONICAL_WARNING, CANONICAL_WARNING.lower())

    assert result.status == "FAIL"


def test_government_warning_missing_colon_fails() -> None:
    missing_colon = CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT WARNING")

    result = compare_government_warning(CANONICAL_WARNING, missing_colon)

    assert result.status == "FAIL"


def test_government_warning_missing_punctuation_fails() -> None:
    missing_period = CANONICAL_WARNING.rstrip(".")

    result = compare_government_warning(CANONICAL_WARNING, missing_period)

    assert result.status == "FAIL"


def test_government_warning_extra_internal_space_passes() -> None:
    extra_space = CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT  WARNING:")

    result = compare_government_warning(CANONICAL_WARNING, extra_space)

    assert result.status == "PASS"


def test_government_warning_leading_whitespace_passes() -> None:
    result = compare_government_warning(CANONICAL_WARNING, f"  {CANONICAL_WARNING}")

    assert result.status == "PASS"


def test_government_warning_trailing_whitespace_passes() -> None:
    result = compare_government_warning(CANONICAL_WARNING, f"{CANONICAL_WARNING}  ")

    assert result.status == "PASS"


def test_government_warning_newline_treated_as_space_passes() -> None:
    with_newline = CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT WARNING:\n")

    result = compare_government_warning(CANONICAL_WARNING, with_newline)

    assert result.status == "PASS"


def test_government_warning_tab_treated_as_space_passes() -> None:
    with_tab = CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT\tWARNING:")

    result = compare_government_warning(CANONICAL_WARNING, with_tab)

    assert result.status == "PASS"


def test_government_warning_extracted_value_is_original_not_normalized() -> None:
    extra_space = CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT  WARNING:")

    result = compare_government_warning(CANONICAL_WARNING, extra_space)

    assert result.status == "PASS"
    assert result.found == extra_space
    assert result.normalized_extracted_value == CANONICAL_WARNING


def test_government_warning_normalized_values_are_populated() -> None:
    extra_space = CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT  WARNING:")

    result = compare_government_warning(CANONICAL_WARNING, extra_space)

    assert result.normalized_application_value == CANONICAL_WARNING
    assert result.normalized_extracted_value == CANONICAL_WARNING


def test_missing_extracted_government_warning_fails() -> None:
    result = compare_government_warning(CANONICAL_WARNING, None)

    assert result.status == "FAIL"


def test_reworded_government_warning_fails() -> None:
    reworded = CANONICAL_WARNING.replace("women should not drink", "people should avoid")

    result = compare_government_warning(CANONICAL_WARNING, reworded)

    assert result.status == "FAIL"


def test_misread_government_warning_failure_keeps_extracted_text() -> None:
    misread = CANONICAL_WARNING.replace("pregnancy", "pragnancy")

    result = compare_government_warning(CANONICAL_WARNING, misread)

    assert result.status == "FAIL"
    assert result.found == misread


def test_all_fields_passing_gives_pass_verdict() -> None:
    result = verify_label(make_application(), make_extracted())

    assert result.overall_verdict == "APPROVED"
    assert all(field.status == "PASS" for field in result.results)


def test_one_failing_field_gives_needs_review() -> None:
    result = verify_label(make_application(), make_extracted(brand_name="Wrong Brand"))

    assert result.overall_verdict == "NEEDS_REVIEW"


def test_multiple_failing_fields_still_gives_needs_review() -> None:
    result = verify_label(
        make_application(),
        make_extracted(brand_name="Wrong Brand", government_warning="wrong warning"),
    )

    assert result.overall_verdict == "NEEDS_REVIEW"


def test_result_includes_one_field_result_per_compared_field() -> None:
    result = verify_label(make_application(), make_extracted())

    assert [field.field for field in result.results] == [
        "brand_name",
        "class_type",
        "producer",
        "country_of_origin",
        "abv",
        "net_contents",
        "government_warning",
    ]


def test_failed_government_warning_result_includes_exact_extracted_warning_text() -> None:
    extracted_warning = "GOVERNMENT WARNING (1) misread"

    result = verify_label(make_application(), make_extracted(government_warning=extracted_warning))
    warning_result = next(field for field in result.results if field.field == "government_warning")

    assert warning_result.status == "FAIL"
    assert warning_result.found == extracted_warning


def test_barefoot_cleaned_extraction_passes_all_fields() -> None:
    application = ApplicationData(
        brand_name="BAREFOOT",
        class_type="PINK MOSCATO",
        producer="BAREFOOT WINES",
        country_of_origin="USA",
        abv="14.5%",
        net_contents="750mL",
        government_warning=BAREFOOT_WARNING,
    )
    extracted = ExtractedLabel(
        brand_name="BAREFOOT",
        class_type="PINK MOSCATO",
        producer="VINTED & BOTTLED BY BAREFOOT WINES, MODESTO, CALIFORNIA",
        country_of_origin="CALIFORNIA",
        abv="14.5%",
        net_contents="750 mL",
        government_warning=BAREFOOT_WARNING_WITH_LINE_BREAKS,
    )

    result = verify_label(application, extracted)

    assert result.overall_verdict == "APPROVED"
    assert all(field.status == "PASS" for field in result.results)


def test_barefoot_bad_abv_extraction_still_fails_abv() -> None:
    application = ApplicationData(
        brand_name="BAREFOOT",
        class_type="PINK MOSCATO",
        producer="BAREFOOT WINES",
        country_of_origin="USA",
        abv="14.5%",
        net_contents="750mL",
        government_warning=BAREFOOT_WARNING,
    )
    extracted = ExtractedLabel(
        brand_name="BAREFOOT",
        class_type="PINK MOSCATO",
        producer="VINTED & BOTTLED BY BAREFOOT WINES, MODESTO, CALIFORNIA",
        country_of_origin="CALIFORNIA",
        abv="IA 5c, ME 15%",
        net_contents="750 mL",
        government_warning=BAREFOOT_WARNING_WITH_LINE_BREAKS,
    )

    result = verify_label(application, extracted)
    abv_result = next(field for field in result.results if field.field == "abv")

    assert result.overall_verdict == "NEEDS_REVIEW"
    assert abv_result.status == "FAIL"
