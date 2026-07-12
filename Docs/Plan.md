# Phase 0 Plan: Deploy-First FastAPI + Hello Frontend

## Summary

Create a minimal Python 3.12 FastAPI app with a plain HTML/JS frontend served by the backend. The only goal is to get one live deployed URL before building real TTB label features.

Use one service, no database, no real API keys, and no vision/model integration yet.

## Repo Structure And Files

```text
fedstack_opener/
  AGENTS.md
  README.md
  railway.json
  pyproject.toml
  uv.lock
  .python-version
  .env.example
  .gitignore
  app/
    __init__.py
    main.py
    static/
      index.html
      app.js
      styles.css
  tests/
    test_health.py
```

Create:

- `pyproject.toml`: Python `>=3.12`, managed by `uv`; dependencies are `fastapi` and `uvicorn`; dev dependencies are `pytest` and `httpx`.
- `uv.lock`: committed for reproducible installs.
- `.python-version`: `3.12`, so local/dev/deploy runtimes prefer Python 3.12.
- `.env.example`: placeholder-only config, starting with `APP_ENV=local`; no real secrets.
- `.gitignore`: ignore `.env`, `.env.*`, virtualenvs, Python caches, test caches, build output, and editor files; explicitly allow `.env.example`.
- `railway.json`: committed Railway start command so deploy behavior is not hidden in dashboard-only settings.
- `app/main.py`: FastAPI app with `GET /health`, static asset mounting, and `GET /` serving the frontend.
- `app/static/*`: plain, readable hello frontend that calls `/health` on page load and displays success/failure clearly.
- `tests/test_health.py`: minimal API test for `/health`.
- `README.md`: local setup, test commands, run command, Railway deploy steps, and secrets policy.

## Public Interface

- `GET /health`
  - Returns:
    ```json
    {"status": "ok"}
    ```

- `GET /`
  - Returns the hello frontend.

Frontend behavior:
- On load, call relative path `/health`.
- If healthy, show a clear “backend is healthy” message.
- If unavailable, show a clear refresh/retry message.

## CORS

No CORS middleware is needed in Phase 0 because the frontend and backend are served from the same
FastAPI origin. The frontend must use relative API paths such as `/health`, never a hardcoded
Railway URL.

If a later phase splits frontend and backend hosting, add explicit allowlisted origins from
environment variables. Do not use wildcard CORS for secret-bearing or upload endpoints.

## Secrets Policy

- Real API keys and secrets must only live in deployment environment variables or an untracked local
  `.env` file.
- `.env` and `.env.*` must be ignored by git.
- `.env.example` is committed and must contain placeholders only.
- No secret values may appear in source code, tests, README examples, plan files, or committed
  config.
- Before the first commit, verify:
  ```bash
  git check-ignore .env
  git check-ignore .env.local
  git status --short
  ```

## Deploy Steps

Use Railway as the Phase 0 target because it can serve the FastAPI API and static frontend from one public URL.

1. Create the Phase 0 files.
2. Run:
   ```bash
   uv lock
   uv run pytest
   ```
3. Confirm `.env` and `.env.local` are ignored by git.
4. Commit the repo.
5. Push to GitHub.
6. Create a Railway project from the GitHub repo.
7. Configure Railway environment variable:
   ```text
   APP_ENV=production
   ```
8. Railway should use the committed `railway.json` start command:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
   ```
9. Deploy.
10. In Railway service settings, open Networking / Public Networking and generate a Railway domain.
11. Verify:
   ```text
   https://<railway-url>/
   https://<railway-url>/health
   ```

`railway.json` contents:

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "deploy": {
    "startCommand": "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
  }
}
```

Railway notes:

- Railway can deploy this as one Python service using Railpack because the repo includes
  `pyproject.toml` and `uv.lock`.
- Do not rely on Railway's auto-detected FastAPI command, because auto-detection commonly assumes
  a root-level `main.py` while this plan uses `app/main.py`.
- Railway services are not publicly reachable until a domain is generated.
- If Railway free/trial availability is blocked by account state, expired credits, or billing
  requirements, use Render free web service as the fallback with the same FastAPI app and start
  command.

## Test Plan

Before deploy:

- `uv run pytest` passes.
- `uv run uvicorn app.main:app --reload` starts locally.
- `http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
- `http://127.0.0.1:8000/` loads the hello frontend.
- Frontend displays health success after calling `/health`.

After deploy:

- Deployed `/` loads.
- Deployed `/health` returns `200`.
- Frontend health message succeeds from the deployed URL.
- Repo contains no `.env` file and no real secrets.
- `git check-ignore .env` and `git check-ignore .env.local` both confirm those files are ignored.
- Browser dev tools show the frontend requests same-origin `/health`, with no CORS error and no
  hardcoded backend URL.

## Assumptions

- Plain HTML/JS is preferred over React for Phase 0 because the goal is the fastest deployable proof.
- One hosted backend service is preferred over separate frontend/backend hosting for now.
- No upload, batch upload, TTB rules, OCR, model calls, or secret-bearing integrations are included in Phase 0.
- Railway is the primary Phase 0 deploy target; Render free web service is the fallback only if
  Railway free/trial deployment is blocked by account or billing constraints.


# Phase 1 Plan: Comparison Engine

## Summary

Add a small verification package that compares structured `ApplicationData` against structured
`ExtractedLabel` data. Each field gets its own pure comparison function that returns a
`FieldResult`. A top-level `verify_label()` function aggregates results into a
`VerificationResult`.

No model calls, no image handling, no upload flow, no database, and no UI work are included in
this phase.

## Review Result

Phase 1 is approved with the test additions below. The exact review scenarios are all covered by
planned tests:

- Case-only brand difference passes: covered by `Brand case-only difference passes`.
- `45%` vs `45% Alc./Vol. (90 Proof)` passes: covered by `45% matches 45% Alc./Vol. (90 Proof)`.
- `750 mL` vs `750ml` passes: covered by `750 mL matches 750ml`.
- `USA` vs `United States` passes: covered by `USA matches United States`.
- Government warning in title case fails: covered by `Title-case warning fails`.
- Government warning missing the colon fails: covered by `Warning missing colon fails`.
- Correct all-caps warning passes: covered by `Exact all-caps warning passes`.
- Misread warning returns the extracted text in the result: covered by `Misread warning failure keeps extracted warning text`.

## Files To Add Or Change

```text
app/
  verification/
    __init__.py
    models.py
    comparisons.py

tests/
  test_verification_comparisons.py

pyproject.toml
uv.lock
```

Dependency change:

- `rapidfuzz`

Use `rapidfuzz` for fuzzy string matching because it is fast, deterministic, actively used, and has
no AI or network dependency at runtime.

## Pydantic Models

`ApplicationData` represents the expected/source-of-truth application values.

Fields:

- `brand_name: str`
- `class_type: str`
- `producer: str`
- `country_of_origin: str`
- `abv: str`
- `net_contents: str`
- `government_warning: str`

`ExtractedLabel` represents values extracted from the label. Fields are nullable because future
OCR/vision extraction may miss fields.

Fields:

- `brand_name: str | None = None`
- `class_type: str | None = None`
- `producer: str | None = None`
- `country_of_origin: str | None = None`
- `abv: str | None = None`
- `net_contents: str | None = None`
- `government_warning: str | None = None`

`FieldResult` represents one result per compared field.

Fields:

- `field: str`
- `status: Literal["PASS", "FAIL"]`
- `expected: str`
- `found: str | None`
- `match_type: str`
- `score: float | None = None`
- `normalized_application_value: str | None = None`
- `normalized_extracted_value: str | None = None`
- `message: str`

`VerificationResult` represents aggregated comparison output.

Fields:

- `verdict: Literal["APPROVED", "NEEDS_REVIEW"]`
- `fields: list[FieldResult]`

Verdict rule:

- If any `FieldResult.status == "FAIL"`, verdict is `NEEDS_REVIEW`.
- Otherwise overall_verdict is `APPROVED`.
- Missing extracted values count as `FAIL`.

## Comparison Strategies

Shared fuzzy normalization for brand and product class:

- Trim outer whitespace.
- Collapse repeated internal whitespace.
- Lowercase.
- Remove most punctuation.
- Compare with `rapidfuzz.fuzz.token_sort_ratio`.
- Threshold: `90.0`.
- `score >= 90.0` is `PASS`; otherwise `FAIL`.

Functions:

- `compare_brand_name(application, extracted) -> FieldResult`
- `compare_product_class(application, extracted) -> FieldResult`

Producer comparison:

- Function: `compare_producer(application, extracted) -> FieldResult`
- Uses RapidFuzz token matching after producer-specific cleanup.
- Removes common role prefixes such as `vinted & bottled by`, `bottled by`, `produced by`,
  `imported by`, `cellared by`, and `distributed by`.
- Removes trailing city/state/country location suffixes when a business name is present.
- Examples:
  - `BAREFOOT WINES` matches `VINTED & BOTTLED BY BAREFOOT WINES, MODESTO, CALIFORNIA`.
  - `SANTA RITA` matches `BOTTLED BY SANTA RITA, SANTIAGO, CHILE`.
- Location-only extracted values fail.

Country comparison:

- Function: `compare_country_of_origin(application, extracted) -> FieldResult`
- Normalize whitespace, punctuation, and case.
- Map synonyms, states, provinces, and common wine regions to canonical country names.
- Examples:
  - `usa`, `u.s.a.`, `us`, `u.s.`, `united states of america` -> `united states`
  - `uk`, `u.k.`, `great britain` -> `united kingdom`
  - `california`, `napa valley`, `modesto california` -> `united states`
  - `ontario`, `british columbia` -> `canada`
  - `mendoza` -> `argentina`
  - `bordeaux`, `burgundy`, `champagne` -> `france`
  - `tuscany`, `piedmont`, `veneto` -> `italy`
  - `rioja`, `priorat` -> `spain`
  - `marlborough` -> `new zealand`
  - `barossa valley` -> `australia`
- Pass only if canonical values match exactly.
- Unknown countries/regions fall back to normalized exact match.

ABV comparison:

- Function: `compare_abv(application, extracted) -> FieldResult`
- Parse numeric ABV from strings like:
  - `13.5%`
  - `13.5 % alc/vol`
  - `ALC 13.5% BY VOL`
  - `13.50`
  - `45% Alc./Vol. (90 Proof)`
- Normalize to percent as a decimal number.
- Prefer a number marked by `%` and near `alc`, `vol`, `abv`, `alcohol`, or `by vol` when multiple
  numbers are present.
- Ignore unrelated OCR fragments before the alcohol statement.
- Ignore proof values when an ABV percentage is present.
- If only proof is present, convert proof to ABV by dividing by `2`.
- Pass if absolute difference is `<= 0.1` percentage points.
- Fail if either side has no parseable number.

Net contents comparison:

- Function: `compare_net_contents(application, extracted) -> FieldResult`
- Parse amount and unit.
- Normalize to milliliters.
- Supported units:
  - `ml`, `milliliter`, `milliliters`
  - `l`, `liter`, `liters`
  - `cl`, `centiliter`, `centiliters`
  - `fl oz`, `fluid ounce`, `fluid ounces`
- Pass if normalized values differ by `<= 1 ml`.
- Fail if either side cannot be parsed.

Government warning comparison:

- Function: `compare_government_warning(application, extracted) -> FieldResult`
- Case-sensitive exact match after whitespace collapse.
- Whitespace collapse trims leading/trailing whitespace and treats repeated spaces, tabs, and line
  breaks as one space.
- Case-sensitive.
- No fuzzy matching.
- No punctuation normalization.
- No case normalization.
- Any missing, changed-case, missing-punctuation, missing-colon, misspelled, or reworded warning
  fails.
- Whitespace-only differences pass.
- On failure, the `FieldResult.found` must preserve and return the extracted warning text
  exactly as received, so a user can see what the model/OCR read.

Top-level function:

- `verify_label(application: ApplicationData, extracted: ExtractedLabel) -> VerificationResult`
- It runs all field comparison functions and applies the verdict rule.

## Test Cases

Model tests:

- `ApplicationData` accepts complete string data.
- `ExtractedLabel` accepts missing extracted fields as `None`.
- `FieldResult` and `VerificationResult` serialize cleanly with expected literals.

Fuzzy field tests:

- Brand exact match passes.
- Brand case-only difference passes.
- Brand case/punctuation difference passes.
- Brand minor OCR typo above threshold passes.
- Brand materially different value fails.
- Product class fuzzy equivalent passes.
- Product class wrong class fails.
- Producer legal suffix or punctuation variation passes when score is above threshold.
- Producer unrelated name fails.
- Fuzzy score exactly at threshold passes.

Country tests:

- `USA` matches `United States`.
- `U.S.A.` matches `United States of America`.
- Case and punctuation differences pass through synonym normalization.
- Different countries fail.
- Unknown country strings pass only when normalized exact values match.
- Missing extracted country fails.

ABV tests:

- `13.5%` matches `13.5 % alc/vol`.
- `ALC 13.50% BY VOL` matches `13.5`.
- `45%` matches `45% Alc./Vol. (90 Proof)`.
- Difference within `0.1` percentage points passes.
- Difference greater than `0.1` fails.
- Missing extracted ABV fails.
- Unparseable ABV fails.

Net contents tests:

- `750 mL` matches `750ml`.
- `750 ml` matches `0.75 L`.
- `750 ml` matches `75 cl`.
- `750 ml` matches equivalent fluid ounces within tolerance.
- Different sizes fail.
- Missing extracted net contents fails.
- Unparseable net contents fails.

Government warning tests:

- Exact all-caps warning passes.
- Title-case warning fails.
- Lowercase warning fails.
- Warning missing colon fails.
- Missing punctuation fails.
- Extra spaces pass when whitespace is the only difference.
- Leading/trailing whitespace passes.
- Newlines and tabs are treated as spaces.
- Missing extracted warning fails.
- Reworded warning fails.
- Misread warning failure keeps extracted warning text in `FieldResult.found`.

Verification result tests:

- All fields passing gives `overall_verdict == "APPROVED"`.
- One failing field gives `verdict == "NEEDS_REVIEW"`.
- Multiple failing fields still gives `NEEDS_REVIEW`.
- Result includes one `FieldResult` per compared field.
- Failed government warning result includes the exact extracted warning text.

## Risks / Review Points

- Fuzzy threshold `90.0` is conservative but may need tuning once real labels arrive.
- ABV and net-content tolerances are deterministic guesses for Phase 1; they should be reviewed
  against actual TTB/business expectations later.
- Government warning is intentionally strict for wording, punctuation, and case; whitespace-only OCR
  differences are tolerated by collapsing repeated spaces, tabs, and line breaks.
- The ABV parser must avoid accidentally comparing proof numbers as ABV when both are present.



# Phase 2 Plan: VisionService For Structured Label Extraction

## Summary

Add a `VisionService` that accepts one label image and returns the existing `ExtractedLabel` Pydantic model from `app/verification/models.py`. This phase introduces AI only for extraction, not verification: comparison remains the deterministic Phase 1 engine.

Use the OpenAI Responses API with `gpt-5.4-mini` by default, configurable via `VISION_MODEL`. OpenAI’s current docs say current GPT models support image input and vision; Structured Outputs should be used over JSON mode when schema adherence matters. Sources: [Models](https://developers.openai.com/api/docs/models), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Images and vision](https://developers.openai.com/api/docs/guides/images-vision).

## Review Result

Phase 2 is approved with the clarifications and test additions below.

- Government warning capture: the prompt must make verbatim warning transcription the highest-priority extraction requirement. It must say not to correct casing, punctuation, spacing, line breaks, spelling, or wording, and to return `null` if the warning cannot be read character-by-character.
- Non-label image: a valid image that is not an alcohol beverage label must return an all-null `ExtractedLabel` and must not throw.
- Model timeout/API error: timeout or OpenAI client failure must return an all-null `ExtractedLabel`, log a concise warning, and let downstream verification produce `NEEDS_REVIEW`.
- Malformed structured output: parsing must be defensive against missing output, malformed JSON, extra keys, wrong types, or schema validation errors. The service must catch parse/validation failures and return an all-null `ExtractedLabel` without leaking raw model text to users.
- Mockability: `VisionService` must accept an injected client/adapter and must expose a small fakeable interface so Phase 2 and Phase 3 tests never need real OpenAI API calls.

## Key Changes

- Add `app/vision/service.py` with an async `VisionService.extract_label(image_bytes, filename=None, content_type=None) -> ExtractedLabel`.
- Add `app/vision/preprocessing.py` for deterministic image preparation using Pillow: EXIF-correct orientation, RGB conversion, downscale long edge to 1600px, JPEG re-encode at quality 82, and cap oversized payloads before model submission.
- Add `app/vision/client.py` with a small `VisionClientProtocol` / adapter boundary around the OpenAI SDK. `VisionService` receives this client through its constructor so tests can pass a fake client.
- Add dependencies: `openai` and `pillow`; update `.env.example` with placeholder names only: `OPENAI_API_KEY=` and `VISION_MODEL=gpt-5.4-mini`.
- Keep secrets in environment variables only. The service reads `OPENAI_API_KEY` from env and never accepts keys through request payloads or committed config.
- Do not add an upload API or UI in this phase unless approved later; this is the service layer plus tests.

## Structured Extraction Behavior

- Send the preprocessed image to the Responses API as image input with `detail: "high"` because label text and the government warning require readable fine detail.
- Request Structured Outputs with a strict JSON schema matching `ExtractedLabel`: `brand_name`, `class_type`, `producer`, `country_of_origin`, `abv`, `net_contents`, and `government_warning`, each `string | null`, with no extra properties.
- Parse only the structured response object and validate it with `ExtractedLabel.model_validate`; do not regex, substring, or string-parse the model response.
- Treat missing structured output, malformed JSON, wrong field types, extra properties, or Pydantic validation errors as controlled extraction failure. Return an all-null `ExtractedLabel` and log a concise warning.
- For blurry, angled, glare-obscured, cropped, or partially unreadable images, return partial data with unreadable fields as `null`; do not throw just because image quality is poor.
- For a valid image that is not an alcohol beverage label, return an all-null `ExtractedLabel`; do not guess values from nearby text or scene context.
- For non-image bytes or preprocessing failure, return an all-null `ExtractedLabel` and log a concise warning, since the downstream verifier will produce `NEEDS_REVIEW`.
- For model timeout, rate-limit, network failure, SDK error, or response refusal, return an all-null `ExtractedLabel` and log a concise warning without exposing raw provider error text to the end user.

Extraction prompt:

```text
You are extracting text fields from a photographed alcohol beverage label for a TTB label verification proof of concept.

Return only the structured JSON object required by the provided schema. Do not include explanations, markdown, or extra keys.

Extract these seven fields:

1. brand_name
   The brand name shown on the label.

2. class_type
   The product type or class shown on the label, such as wine, red wine, vodka, whiskey, beer, cider, or another visible class/type statement.

3. producer
   The producer, bottler, importer, winery, brewery, distillery, or responsible company shown on the label.
   Return only the business/entity name when present. Do not include role phrases or location text.
   For example, if the label says "VINTED & BOTTLED BY BAREFOOT WINES, MODESTO, CALIFORNIA",
   return "BAREFOOT WINES".

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
   Prefer the number attached to alcohol wording such as "% ALC", "% ALC/VOL", "% ABV",
   "% BY VOL", "% VOL", or "ALCOHOL BY VOLUME". Ignore unrelated OCR fragments near the percentage.
   If the alcohol percentage is uncertain or cannot be read, return null instead of guessing.

6. net_contents
   The net contents statement exactly as visible, such as "750 mL", "1 L", or "12 FL OZ".

7. government_warning
   The government warning text exactly as visible on the label. This field is critical because the downstream verifier requires a case-sensitive match after whitespace collapse.

Rules:
- If a field is not visible, unreadable, blocked by glare, too blurry, cut off, or uncertain, return null for that field.
- Do not guess or infer values from context.
- For producer, remove role prefixes and trailing city/state/country location suffixes.
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
- For all other fields, copy the visible text as closely as possible without adding information.
- If the image is not an alcohol beverage label, return null for all fields.
- Return partial data when only some fields are readable.
```

## Test Plan

- Unit-test preprocessing with generated in-memory images: large image is downscaled, orientation path is handled, output is JPEG/RGB, and small images are not enlarged.
- Unit-test prompt/schema construction: exactly the seven existing `ExtractedLabel` fields are requested, fields are nullable, extra properties are disallowed, and the government-warning instruction says verbatim/exact.
- Unit-test prompt/schema construction: government-warning instructions explicitly forbid correcting casing, punctuation, colon, spacing, spelling, wording, or line breaks.
- Unit-test prompt construction for country-level output, producer cleanup, and ABV alcohol-context
  selection.
- Unit-test service parsing with a fake OpenAI client returning complete structured data.
- Unit-test partial extraction: fake response omits unreadable fields as `null`, and service returns an `ExtractedLabel` with those nulls.
- Unit-test blurry/glare behavior through the fake client: model returns partial/null data, service does not throw.
- Unit-test non-label image behavior through the fake client: model returns all fields as `null`, and service returns an all-null `ExtractedLabel` without throwing.
- Unit-test malformed structured response: missing output, malformed JSON, extra keys, wrong types, and validation failure each return all-null `ExtractedLabel` without leaking raw model text.
- Unit-test API timeout/client error: service handles timeout, rate-limit, network failure, and generic SDK error gracefully and returns all-null `ExtractedLabel`.
- Unit-test no string parsing: fake response should be consumed from the structured output object only.
- Unit-test mockability: `VisionService` can be constructed with a fake client/adapter, and tests assert no OpenAI SDK network method is called.
- Unit-test env config: `VISION_MODEL` overrides the default model, and missing `OPENAI_API_KEY` produces a controlled startup/config error rather than a hardcoded fallback.

## Assumptions

- Phase 2 returns the existing `ExtractedLabel` shape exactly; no new fields like confidence, warnings, or raw OCR text are added yet.
- Default model is `gpt-5.4-mini` for latency/cost under the project’s 5-second target, with `VISION_MODEL` allowing later tuning.
- `detail: "high"` is chosen over `low` because the government warning must be copied exactly; preprocessing protects latency by bounding image size first.
- Network/API integration tests are not required in Phase 2. Tests mock the OpenAI client and avoid real API calls.
- Phase 3 must depend on the service interface or a callable extractor boundary, not directly on the OpenAI SDK, so endpoint tests can inject fake extraction results.



# Phase 3 Plan: `POST /verify` Multipart Verification Endpoint

## Summary

Add a FastAPI `POST /verify` endpoint that accepts one label image plus the seven required application fields as multipart form data. The endpoint orchestrates the existing flow:

`validate request -> VisionService.extract_label -> verify_label -> return verification + latency`

The endpoint will not add batch upload, UI changes, database state, or real feature expansion beyond a single-label API path.

## Review Result

Phase 3 is approved with the clarifications and test additions below.

- Bad file type must return a clear `415` JSON error, never a `500`.
- Empty submissions, including an empty multipart body or a request with no file and no usable form fields, must return a clear `400` JSON error, never a `500`.
- The success response must include:
  - Per-field `verification.results`.
  - Expected-vs-found values on failures through each `FieldResult.expected` and `FieldResult.found`.
  - Overall `verification.overall_verdict`.
  - Endpoint `latency_ms`.
  - `extracted_label`, including `government_warning`, so the warning text read by the model is surfaced.
- The 5-second single-label budget must be measured for every `/verify` request and logged with the verdict. Requests over `5000 ms` must produce a warning log.
- Tests must cover each of those behaviors using a mocked vision service, with no OpenAI API calls.

## API Contract

Request: `multipart/form-data`

- `image`: required file upload.
- Required form fields:
  - `brand_name`
  - `class_type`
  - `producer`
  - `country_of_origin`
  - `abv`
  - `net_contents`
  - `government_warning`

Validation:

- File is required.
- Allowed content types: `image/jpeg`, `image/png`, `image/webp`.
- Maximum upload size: `8 MB`.
- All seven application fields are required and must be non-empty after trimming.
- Unknown extra form fields are ignored for Phase 3.
- Empty multipart submissions return `400` with a human-readable message listing the missing image
  and required fields where possible.
- Invalid requests return human-readable JSON errors, never stack traces.

Response model:

- Add endpoint response model `VerifyResponse` rather than changing the pure Phase 1 `VerificationResult`.
- Shape:
  ```json
  {
    "verification": {
      "overall_verdict": "APPROVED",
      "results": []
    },
    "latency_ms": 1234,
    "extracted_label": {
      "brand_name": null,
      "class_type": null,
      "producer": null,
      "country_of_origin": null,
      "abv": null,
      "net_contents": null,
      "government_warning": null
    }
  }
  ```
- `verification` is the existing `VerificationResult`.
- `verification.results` must be returned in full. Each failed field includes the expected value in
  `expected` and the found value in `found`.
- `latency_ms` is measured around the full endpoint orchestration after basic request parsing starts.
- `extracted_label` is included so users can see what the model read when a field fails.
- `extracted_label.government_warning` must be included exactly as extracted, including on warning
  failures, so users can inspect the warning text used by the exact-match comparator.

Error shape:

```json
{
  "message": "Please upload a JPEG, PNG, or WebP image.",
  "errors": {
    "image": "Unsupported file type."
  }
}
```

Status codes:

- `400`: missing/empty application fields or missing image.
- `413`: file too large.
- `415`: unsupported file type.
- `500`: unexpected internal failure, with generic message only.

Required non-500 cases:

- Missing image -> `400`.
- Empty multipart request -> `400`.
- Required field present but blank after trimming -> `400`.
- Unsupported uploaded file type -> `415`.
- Oversized upload -> `413`.

## Implementation Changes

- Add `python-multipart` dependency for FastAPI form uploads.
- Add API models in a small request/response module, likely `app/api/models.py`, for `VerifyResponse` and `ErrorResponse`.
- Add a dependency provider, likely `get_vision_service()`, so tests can override `VisionService` cleanly.
- Add `POST /verify` in `app/main.py` or a small router module.
- Construct `ApplicationData` from validated form fields.
- Read the image bytes once, enforce size, then pass bytes to `VisionService.extract_label`.
- Pass returned `ExtractedLabel` and `ApplicationData` into `verify_label`.
- Use `time.perf_counter()` for latency measurement and return integer milliseconds.
- Log one structured summary line per `/verify` request with `latency_ms`, `verdict`, field failure
  count, upload content type, upload size, and whether the request exceeded the `5000 ms` budget.
- Log at warning level when `latency_ms > 5000`; otherwise log at info level.
- Wrap unexpected exceptions with logging and a generic user-facing error.

## Orchestration Details

- Request validation happens before model extraction to avoid spending API time on invalid inputs.
- Latency measurement starts before validation work that is part of endpoint handling and stops
  immediately before returning the response or error.
- `VisionService` already handles blurry, invalid, or provider-failed extraction by returning null fields, so `/verify` should still compare and return `NEEDS_REVIEW` when extraction is partial.
- If `VisionService.extract_label` itself raises unexpectedly, catch it at the endpoint boundary and return a generic `500` error.
- Government warning remains case-sensitive after whitespace collapse because `/verify` delegates
  comparison to the existing Phase 1 `verify_label`.
- Government warning extracted text is surfaced twice on failures: in `extracted_label.government_warning`
  and in the `government_warning` `FieldResult.found`.

## Endpoint Tests With Mocked VisionService

- Successful request with valid JPEG and all application fields returns `200`.
- Successful response includes `verification`, `latency_ms`, and `extracted_label`.
- Successful response includes `verification.overall_verdict`.
- Successful response includes one `verification.results` entry per compared field.
- Failed field response includes expected-vs-found values via `expected` and `found`.
- All matching mocked extracted fields returns `overall_verdict == "APPROVED"`.
- One mismatched mocked field returns `verdict == "NEEDS_REVIEW"`.
- Partial mocked extraction with null fields returns `NEEDS_REVIEW`, not an exception.
- Mocked blurry/glare case returns partial data and still returns `200`.
- Missing image returns `400` with human-readable error.
- Empty multipart submission returns `400` with human-readable error.
- Unsupported content type returns `415`.
- Unsupported content type does not call mocked `VisionService`.
- Oversized image returns `413`.
- Missing required application field returns `400`.
- Empty required application field returns `400`.
- Government warning case mismatch returns `NEEDS_REVIEW`.
- Government warning mismatch response includes the extracted warning text in
  `extracted_label.government_warning`.
- Government warning mismatch response includes the extracted warning text in the
  `government_warning` field result's `found`.
- Mocked VisionService exception returns generic `500` with no stack trace.
- Response latency is present, numeric, and non-negative.
- Latency measurement is logged for successful and 4xx responses.
- Slow mocked VisionService path over `5000 ms` logs a warning that the request exceeded the
  single-label budget.
- Normal mocked VisionService path under `5000 ms` logs an info-level summary.
- Test override confirms the endpoint uses the mocked VisionService and makes no real OpenAI call.

## Assumptions

- Phase 3 is single-image `/verify` only; batch upload remains required for the overall project but is not implemented in this phase.
- The endpoint returns a response envelope containing the existing `VerificationResult` plus latency and extracted data, instead of modifying the Phase 1 pure comparison model.
- `8 MB` is the initial upload cap to protect the 5-second budget; preprocessing still handles downscale/re-encode inside `VisionService`.
- JPEG, PNG, and WebP cover Phase 3 browser uploads; HEIC is excluded until explicitly needed because server support is less predictable.


# Final Phase 4 Plan: Single-Label UI For Clear Human Review

## Summary

Build a plain HTML/CSS/JS single-label screen where the primary action is unmistakable: upload one label image, enter the seven approved application values, press one large button, then see either `APPROVED` or `NEEDS REVIEW`.

Review result: the earlier plan was close, but a few items needed tightening for the “70-year-old, no instructions, under 30 seconds” bar. The finalized UI removes jargon, makes failures visible without hunting, and keeps the next action obvious.

## Key UI Changes

- Replace the health-check page with one task-focused form.
- Use a two-card layout on desktop and tablet:
  - Left white card: `Label photo`, large preview/placeholder area, and `Choose Label Photo`.
  - Right white card: `Application Data`, all seven application fields, and inline extracted-result
    boxes aligned with their matching inputs.
- Put the primary `Check Label` button underneath the two cards, spanning the full content width.
- Put the secondary `Check Another Label` button directly under the primary button with lower visual
  emphasis.
- On mobile and narrow screens, collapse to one column in this order: label photo card,
  application data card, buttons, results.
- Use plain labels:
  - `Label photo`
  - `Brand name`
  - `Product type`
  - `Producer or company`
  - `Country`
  - `Alcohol percentage`
  - `Bottle size`
  - `Government warning`
- Use one large full-width primary button: `Check Label`.
- Keep helper text minimal and action-oriented, not instructional paragraphs.
- Show the chosen image filename and preview immediately after selection.
- Disable the button until all seven fields and an image are present, with plain text above it: `Add the missing items to check this label.`
- Loading state says: `Checking the label. This may take a few seconds.`
- Keep the backend field names unchanged: `image`, `brand_name`, `class_type`, `producer`,
  `country_of_origin`, `abv`, `net_contents`, and `government_warning`.

## Results Layout

- Verdict appears at the very top in a large banner:
  - Green `APPROVED`
  - Orange/red `NEEDS REVIEW`
- Under the verdict, show simple timing text:
  - `Checked in 4.2 seconds`
- Show verification results inline beside each matching application field, not in a separate JSON or
  dense results block.
- Each row keeps the user's entered value visible in the input/select/textarea and shows the model's
  extracted value in a read-only result box next to it.
- Show all seven field rows, and make failures visually dominant:
  - Failed rows/results have a large `Needs review` badge.
  - Passed rows/results have a smaller `Looks good` badge.
  - Approved result boxes turn rich green.
  - Needs-review result boxes turn burnt orange.
- Each failed row must show the reason immediately:
  - Field name: `Brand name`
  - User-entered application value remains visible in the input/select/textarea.
  - `Found on label:` extracted value, or `Not found on label`, appears in the inline result box.
  - Plain result message, such as `These do not match closely enough.`
- No user should need to expand, click, inspect JSON, or scroll through dense data to find why the label needs review.
- The separate extracted-label details area may be removed or de-emphasized, but the extracted value
  for every field must remain visible inline beside the matching input.
- Add a large secondary button: `Check Another Label`.

## Error Handling

- Show errors in a large high-contrast panel above the form.
- Use plain English only:
  - Unsupported file: `Please choose a JPG, PNG, or WebP photo.`
  - File too large: `The photo is too large. Please choose one under 8 MB.`
  - Missing field: `Please fill in Brand name.`
  - Network failure: `The checking service is unavailable. Please try again.`
  - Server failure: `Something went wrong while checking the label. Please try again.`
- Never show stack traces, raw JSON, exception names, HTTP codes, or model/provider details to the user.
- Put focus on the error panel after an error so screen readers and keyboard users land on the problem.

## API Call

- Submit with:
  ```js
  fetch("/verify", { method: "POST", body: formData })
  ```
- Multipart field names must match the backend:
  - `image`
  - `brand_name`
  - `class_type`
  - `producer`
  - `country_of_origin`
  - `abv`
  - `net_contents`
  - `government_warning`
- Map user-facing labels to backend names:
  - `Product type` -> `class_type`
  - `Producer or company` -> `producer`
  - `Country` -> `country_of_origin`
  - `Alcohol percentage` -> `abv`
  - `Bottle size` -> `net_contents`
- On success, render `verification.overall_verdict`, `verification.results`, `latency_ms`, and `extracted_label`.
- Use `verification.results` to apply pass/fail styling and status text to the inline result boxes.
- Use `extracted_label` and each field result's `found` to populate the inline
  `Found on label` values.
- On error, render the backend `message` and `errors` as plain-English form errors.

## Test Plan

- Form renders one image picker, seven labeled fields, and one obvious `Check Label` button.
- Button is disabled until image plus all seven fields are present.
- Valid submit sends multipart form data with exact backend field names.
- Loading state disables controls and uses plain text.
- `APPROVED` response shows large `APPROVED`.
- `NEEDS_REVIEW` response shows large `NEEDS REVIEW`.
- Desktop/tablet layout shows two white cards with the photo card on the left and the application
  data/results card on the right.
- The primary `Check Label` button is full-width underneath both cards.
- Mobile layout stacks label photo, application data, buttons, and results with no overlap.
- Each field shows the user-entered application value and the extracted `Found on label` value
  inline without requiring a click.
- Approved fields turn rich green and show `Looks good`.
- Fields needing review turn burnt orange and show `Needs review`.
- Null extracted values display `Not found on label`.
- Server validation errors display plain English near the top and do not show technical details.
- Network failure displays plain English.
- `Check Another Label` resets the screen.
- Mobile/narrow layout has no overlapping labels, buttons, or results.

## Final Review Notes

- Primary action is obvious after changing `Verify Label` to `Check Label` and making it the only primary button.
- Jargon is reduced by changing `ABV`, `net contents`, `product class`, and `verification` language into everyday labels.
- Errors are plain-English and actionable.
- Failing-field reasons are immediately visible because the extracted value appears inline beside
  the user's input and the row/result box is colored burnt orange.
- Approved fields are easy to scan because their inline result boxes turn rich green.
- The revised two-card layout does not change `/verify`, response handling, or FormData field names.
- Nothing important should require hunting, expanding, reading JSON, or interpreting backend terminology.

## Assumptions

- Phase 4 remains single-label only.
- Batch upload is still required for the full project but belongs to a later phase.
- Plain HTML/CSS/JS remains the frontend choice for speed and simplicity.



# Final Phase 5 Plan: Unified Multi-Label Verification

## Summary

Build one unified verification page and one batch-capable endpoint. The page starts with one label card; adding more cards turns the same flow into batch verification. There is no separate mode selector.

`POST /verify/batch` accepts 1 to 5 image + application-data pairs, processes them concurrently with a bounded limit, and returns a summary plus individually viewable results for every submitted label.

Review confirmed:
- One bad label does not fail the whole batch.
- Concurrency is bounded to control latency, API rate pressure, and cost.
- Summary counts are derived from per-item results.
- Every item remains individually viewable.

## API Design

Endpoint: `POST /verify/batch`

Request: `multipart/form-data`

- `images`: repeated files, one per label.
- `items_json`: JSON array of application-data objects.
- Pairing rule: `images[i]` pairs with `items_json[i]`.
- Batch size: minimum `1`, maximum `5`.
- Allowed image types: JPEG, PNG, WebP.
- Max per-image size: `8 MB`.
- Max total image bytes: `25 MB`.
- Each item requires:
  - `brand_name`
  - `class_type`
  - `producer`
  - `country_of_origin`
  - `abv`
  - `net_contents`
  - `government_warning`

Response:

```json
{
  "summary": {
    "passed": 2,
    "needs_review": 1,
    "total": 3,
    "latency_ms": 4200
  },
  "results": [
    {
      "index": 0,
      "filename": "label-1.jpg",
      "status": "PASS",
      "verification": {},
      "extracted_label": {},
      "latency_ms": 1200,
      "errors": {}
    }
  ]
}
```

Top-level errors only happen for malformed batch structure:
- empty batch
- more than 5 labels
- invalid `items_json`
- mismatched image/data counts
- total upload too large

Per-item errors are isolated:
- unsupported file type
- oversized individual image
- missing/empty fields
- extraction failure
- unexpected per-item processing failure

A per-item error returns that item with `status: "NEEDS_REVIEW"` and human-readable `errors`, while other valid items still process and return results.

## Backend Behavior

- Reuse existing single-label validation and verification logic where possible.
- Add batch response models:
  - `BatchSummary`
  - `BatchItemResult`
  - `BatchResult`
- Process valid items with `asyncio.gather`.
- Bound concurrency with `asyncio.Semaphore(5)`.
- Never allow one item exception to escape and fail the whole batch.
- Measure:
  - total batch `summary.latency_ms`
  - each item `latency_ms`
- Compute summary from item statuses:
  - `passed = count(status == "PASS")`
  - `needs_review = count(status == "NEEDS_REVIEW")`
  - `total = len(results)`
- Preserve result order to match input order.
- Return no stack traces, provider details, exception names, or raw model errors.

## Frontend Design

Use one centralized page for both single-label and batch verification.

- Show one centered label card by default.
- Each card contains:
  - `Label 1`, `Label 2`, etc.
  - image picker and preview
  - the seven application fields
  - remove button only when more than one card exists
- Beneath cards:
  - `Add Label` button
  - primary submit button:
    - `Check Label` for one card
    - `Check All Labels` for multiple cards
- Allow up to 5 cards.
- At 5 cards, disable `Add Label` and show `Maximum 5 labels at a time.`
- No mode selector.
- One card is effectively single-label mode.
- Multiple cards are batch mode.
- Frontend may always call `POST /verify/batch`, even for one card.
- Keep `POST /verify` for API compatibility.

Loading/progress:
- Disable all controls while submitting.
- If processing takes more than 700ms, show:
  - `Checking 1 label. This may take a few seconds.`
  - or `Checking 3 labels. This may take a few seconds.`
- Show an elapsed seconds counter or indeterminate progress bar.

Results:
- For one item, show the prominent single result view.
- For multiple items, show summary counts:
  - approved
  - needs review
  - total
- Each item appears in its own result card.
- Each result card shows verdict, filename/label number, latency, and a `View details` control.
- Item details show per-field results with failures first and expected-vs-found visible.
- Per-item errors are shown inside that item’s result card in plain English.

## Test Plan

Backend tests with mocked `VisionService`:

- Batch size 1 works.
- Valid batch of 2 passing labels returns `passed: 2`, `needs_review: 0`, `total: 2`.
- Mixed pass/fail batch returns correct summary counts.
- Result order matches input order.
- One invalid item does not block valid items.
- Unsupported file type produces item-level `NEEDS_REVIEW`.
- Oversized individual image produces item-level `NEEDS_REVIEW`.
- Missing item field produces item-level `NEEDS_REVIEW`.
- Extraction exception for one item produces item-level `NEEDS_REVIEW`.
- Empty batch returns top-level `400`.
- More than 5 labels returns top-level `400`.
- Mismatched image/data counts returns top-level `400`.
- Total upload over 25 MB returns top-level `413`.
- Mocked slow service proves bounded concurrent processing.
- No real OpenAI calls occur.

Frontend tests:

- Page starts with one label card and no mode selector.
- `Add Label` adds cards up to 5.
- Remove button appears only when more than one card exists.
- Submit text changes between `Check Label` and `Check All Labels`.
- Submit disabled until all visible cards are complete.
- Frontend sends `images` and `items_json` in matching order.
- Loading message uses correct singular/plural count.
- Summary counts render correctly.
- Every item result is individually viewable.
- Per-item errors show in the affected card only.
- Failed fields show expected-vs-found without hunting.

## Assumptions

- Batch limit remains 5 for Phase 5.
- `POST /verify/batch` supports 1 to 5 items.
- Batch processing is request/response only: no database, job queue, WebSocket, or server-side persistence.
- The frontend remains plain HTML/CSS/JS.

# Final Phase 6 Plan: Hardening, Measurement, And Accessibility

## Summary

Phase 6 adds no new user-facing features. It hardens the existing single-label and batch flows by
measuring real latency, tuning image/model settings only after measurement, confirming imperfect
images degrade to partial/null extraction, tightening validation/error messages, and doing an
accessibility pass for the 70+ user bar.

Primary success criterion: single-label verification on the deployed Railway app is reliably under
`5 seconds` while preserving case-sensitive government-warning comparison after whitespace collapse
and clear `NEEDS_REVIEW` degradation for poor inputs.

## Full Checklist Review

Every item from the brief is covered:

- Valid label: covered by endpoint/API tests where all seven fields pass and UI shows `APPROVED`.
- Mismatches: covered by one-wrong-field tests for all seven fields and expected-vs-found display.
- Case-only: covered by fuzzy string tests for ordinary fields and strict warning case tests.
- ABV normalization: covered by numeric ABV tests such as equivalent percentages and out-of-tolerance values.
- Units normalization: covered by net-contents tests for `ml`, `L`, `cl`, and fluid-ounce equivalents.
- Missing warning: covered by null/missing extracted warning returning field `FAIL` and `NEEDS_REVIEW`.
- Wrong-caps warning: covered by title-case/lowercase government-warning failures.
- Correct warning: covered by exact all-caps/full-warning pass cases.
- Imperfect image: covered by blurry/cropped/glare/non-label degradation checks returning partial/null data without uncaught exceptions.
- Wrong file type: covered by validation tests returning plain-English errors and no model call.
- Empty submit: covered by missing image plus missing/blank field validation tests.
- Batch summary: covered by mixed pass/fail batch tests with `passed`, `needs_review`, and `total` counts.
- Single-label speed: covered by deployed `/verify` measurement, timing logs, and target thresholds below.

## Measurements And Targets

Add structured timing for each single-label request:

- `request_total_ms`: full `/verify` request time.
- `image_read_ms`: upload read time.
- `preprocess_ms`: EXIF correction, resize, and JPEG encode.
- `prepared_image_bytes`: bytes sent to the model after preprocessing.
- `prepared_image_width` and `prepared_image_height`.
- `vision_ms`: OpenAI vision call duration.
- `compare_ms`: deterministic comparison duration.
- `model`: active `VISION_MODEL`.
- `vision_detail`: active detail level.
- `verdict` and `failure_count`.

Target numbers:

- Single-label p50 total latency: `< 3.0s`.
- Single-label p90 total latency: `< 5.0s`.
- Single-label p95 total latency: tracked and targeted at `< 6.0s`; not considered reliable until p90 is under `5.0s`.
- Preprocessing p90: `< 300ms`.
- Comparison p90: `< 50ms`.
- Prepared image size p90: `< 1.5 MB`.
- Vision call p90: `< 4.3s`, leaving budget for upload, preprocessing, and comparison.
- Batch of 3 labels: total latency should be clearly less than sequential per-item total, confirming concurrency remains active.

Tune only after baseline measurement:

- Test preprocessing long edge values: current `1600px`, then `1400px`, then `1200px`.
- Test JPEG quality values: current `82`, then `76`, then `70`.
- Test model tier only if needed: current `gpt-5.4-mini`, then `gpt-5.4-nano` as a speed/cost candidate.
- Keep a lower-quality/lower-tier setting only if the seven-field extraction remains acceptable, especially the government warning.

## Hardening Changes

- Add timing instrumentation around upload read, preprocessing, model call, comparison, and total request handling.
- Keep `/verify` and `/verify/batch` user-facing errors plain English; never expose stack traces, exception names, provider text, model names, or API-key details.
- Validate that image bytes are actually readable images, not only that content type is allowed.
- Preserve current limits unless measurement proves they must change:
  - single image max: `8 MB`
  - batch size max: `5`
  - batch total image bytes max: `25 MB`
  - allowed types: JPEG, PNG, WebP
- Confirm bad images degrade safely:
  - blurry image -> partial/null fields and `NEEDS_REVIEW`
  - cropped image -> partial/null fields and `NEEDS_REVIEW`
  - angled/rotated image -> partial/null fields and `NEEDS_REVIEW`
  - glare/overexposed image -> partial/null fields and `NEEDS_REVIEW`
  - non-label image -> all-null or mostly-null fields and `NEEDS_REVIEW`
  - unreadable/non-image bytes -> validation/preprocessing failure with plain error or all-null extraction, never a crash
- Keep batch per-item isolation: one bad image/data pair returns one item-level `NEEDS_REVIEW` and does not fail the whole batch.

Plain-English error targets:

- Missing image: `Please choose a label photo.`
- Unsupported type: `Please choose a JPG, PNG, or WebP photo.`
- Too large: `The photo is too large. Please choose one under 8 MB.`
- Missing field: `Please fill in Brand name.`
- Batch too large: `Please check no more than 5 labels at a time.`
- Service failure: `Something went wrong while checking the label. Please try again.`

## Accessibility Pass

Audit and adjust the existing plain HTML/CSS/JS UI:

- Base body/form text target: `20px`.
- Labels target: `20px+`, bold, visible.
- Inputs/buttons minimum height: `50px`; tap target minimum: `48px`.
- Primary action remains full-width and high contrast.
- Text contrast target: WCAG AA `4.5:1` for normal text, `3:1` for large text and UI boundaries.
- Focus states remain thick and obvious for inputs, selects, file picker, buttons, and result drill-down summaries.
- Every input has a visible label; no placeholder-only instructions.
- Error panel receives focus after an error.
- Batch details remain keyboard reachable through native `<details>/<summary>`.
- Check common widths: `375px`, `768px`, and `1280px`; no overlapping text, clipped buttons, or horizontal scrolling from form controls.

## Test Plan

- Add timing tests/log assertions that all timing keys are present and numeric.
- Add preprocessing size tests for large generated images and selected long-edge/quality settings.
- Add imperfect-image fixture tests for blurry, cropped, glare, non-label, and non-image inputs.
- Add validation tests for wrong file type, oversized files, empty submit, blank fields, malformed batch data, and too many batch labels.
- Preserve and expand comparison tests for valid label, mismatches, case-only ordinary fields, ABV normalization, unit normalization, and government-warning exactness after whitespace collapse.
- Add frontend tests or smoke checks for plain-English errors, visible labels, button disabled/enabled behavior, summary counts, and opening individual batch results.
- Measure deployed single-label latency against the real test images and record p50/p90/p95 before and after any tuning.

## Assumptions

- Phase 6 introduces no new features, no database, no queue, and no new UI workflow.
- Railway production URL is the source of truth for latency targets.
- Batch remains capped at 5 labels.
- Government warning remains exact and case-sensitive after whitespace collapse; hardening must not
  normalize punctuation, wording, spelling, or case.

# Phase 7 Plan: Final Readiness, README, And Secret Audit

## Summary

Phase 7 is documentation and readiness work only. It does not add product features. The goal is to
make sure the repo, README, deployed app, and secret handling are in a clean final state.

## Readiness Gates

- Repository has the expected code, tests, docs, lockfile, and deployment config.
- Live Railway URL is functional:
  - `/` loads the label verification UI.
  - `/health` returns `{"status":"ok"}`.
  - Single-label verification works.
  - Batch verification works for up to five labels.
  - Warning exact-match behavior is demonstrable.
  - Imperfect images return a normal result or readable error, never a stack trace.
- Local tests pass with:
  ```bash
  uv run pytest
  ```
- README is complete and reviewer-friendly.
- Secret audit is clean:
  - no `.env` committed,
  - no OpenAI API key committed,
  - no Railway token committed,
  - `.env.example` contains placeholder names only,
  - runtime secrets live only in environment variables.

## README Outline

The README should include:

- Live demo URL and `/health` URL.
- Brief overview of what the app does.
- The seven verification fields.
- Matching rules:
  - fuzzy token-sort for brand, product type, and producer,
  - synonym-normalized exact match for country,
  - numeric normalization for ABV,
  - unit normalization for bottle size,
  - exact case-sensitive match after whitespace collapse for government warning.
- Verdict rule: any failed field means `NEEDS REVIEW`; all fields passing means `APPROVED`.
- Local setup using `uv`.
- Local run command.
- Test command.
- API endpoint summaries for `/health`, `/verify`, and `/verify/batch`.
- Railway deployment notes and required environment variables.
- Tools and libraries used.
- Accessibility/usability notes.
- Assumptions and limitations.
- Secret-handling policy.

## Secret Audit

Run these checks:

```bash
git ls-files | rg '(^|/)\.env($|\.|-)'
git check-ignore .env
git check-ignore tests/test_images/
git grep -nE 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*='
rg --hidden --glob '!.git' --glob '!tests/test_images/**' -n 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*='
git log --all -G 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*=' --oneline -- . ':!tests/test_images'
```

Expected results:

- `git ls-files` should show `.env.example` only.
- `.env` should be ignored.
- `tests/test_images/` should be ignored.
- Grep matches should be placeholders, documentation, or code that reads environment variable names.
- History matches should be reviewed manually to confirm no real key value was ever committed.

If there is any evidence that a real key was committed at any point, rotate that key before sharing
the repo.

## Final Live Checks

Run one clean deployed pass against the Railway URL:

- `GET /health` returns `200` and `{"status":"ok"}`.
- A valid single label returns `APPROVED`.
- A case-only government-warning mismatch returns `NEEDS_REVIEW` with the warning field failing.
- An imperfect image returns a normal verification result or controlled readable error.
- A three-label batch returns correct summary counts and individual item results.
- Single-label latency remains under five seconds.

## Assumptions

- Phase 7 does not change verification behavior.
- Documentation should describe the current implemented system, not future features.
- Local real-image sanity files under `tests/test_images/` remain ignored and are not part of the
  committed test suite.
