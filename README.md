# TTB Label Verification Proof Of Concept

This is a small proof of concept for checking alcohol beverage label images against application
data. It uses a FastAPI backend, a plain HTML/CSS/JavaScript frontend, OpenAI vision extraction,
and deterministic comparison rules.

The app is intentionally stateless. It has no database and does not submit anything to TTB systems.

## Live Demo

- App: https://ttb-label-verification-production-00ed.up.railway.app/
- Health check: https://ttb-label-verification-production-00ed.up.railway.app/health
- Last live verification: June 22, 2026
- Single-label target: under 5 seconds
- Measured single-label p50 latency: 1960 ms against 5-second target
- Measured single-label p95 latency: 2899 ms against 5-second target
- Measurement method: `python scripts/readiness_check.py --base-url "$READINESS_BASE_URL" --verify --verify-runs 10` against the deployed Railway app using `tests/test_images/ttb_c.jpg` and matching application fields.
- Batch support: up to 5 labels per request

## What It Does

- Upload one label image with seven application fields.
- Add up to five label cards on the same page for batch checking.
- Extract seven fields from each image using a vision model.
- Compare extracted label text against the submitted application data.
- Show a clear `APPROVED` or `NEEDS REVIEW` verdict.
- Show per-field `PASS` or `FAIL` results with expected-vs-found values.

## Verification Fields

The app verifies these seven fields:

- Brand name
- Product type
- Producer or company
- Country
- Alcohol percentage
- Bottle size
- Government warning

## Matching Rules

Most fields are forgiving because OCR and label formatting vary. The government warning is strict
for wording, punctuation, and capitalization, while tolerating whitespace-only OCR differences.
Fuzzy text matches pass at a score of 90 or higher.

| Field | Match type |
| --- | --- |
| Brand name | Fuzzy token-sort match, threshold 90 |
| Product type | Fuzzy token-sort match, threshold 90 |
| Producer or company | Fuzzy match after role/location cleanup, threshold 90 |
| Country | Exact match after country, state, province, and wine-region normalization |
| Alcohol percentage | Numeric ABV normalization, ±0.1 percentage points |
| Bottle size | Unit normalization to milliliters, ±1 mL |
| Government warning | Case-sensitive exact match after whitespace collapse |

Whitespace-only OCR differences such as line breaks, tabs, repeated spaces, or leading/trailing
spaces are tolerated for the government warning. Capitalization, punctuation, colon, spelling, and
wording must still match.

Country matching normalizes common wine regions and subdivisions to their countries, such as
`California` to `United States`, `Mendoza` to `Argentina`, and `Bordeaux` to `France`. Producer
matching ignores common role phrases and trailing locations, such as `VINTED & BOTTLED BY ...,
MODESTO, CALIFORNIA`, while still rejecting unrelated company names. ABV matching tolerates only
±0.1 percentage points and prefers numbers attached to alcohol wording. Bottle-size matching
tolerates only ±1 mL after converting both values to milliliters.

Verdict rule:

```text
Any failed field => NEEDS REVIEW
All fields pass  => APPROVED
```

If the vision model cannot read a field, that field is returned as missing and fails review.

## Approach

The system separates AI extraction from deterministic verification:

1. The browser submits label photos and application data to FastAPI.
2. The backend validates file type, file size, and required fields.
3. Images are downscaled and re-encoded before model submission to protect latency.
4. The vision service asks the model for structured JSON containing the seven verification fields plus raw text and extraction confidence.
5. Pydantic validates the structured extraction result.
6. Pure comparison functions evaluate each field.
7. The API returns the extracted label, per-field results, `overall_verdict`, and latency timings.

Batch requests process labels concurrently with per-item error isolation. One bad label does not
fail the whole batch.

## AI Workflow

This proof of concept was built with a plan, review, execute cadence using Codex, followed by
pull-request-style review loops. For each development step, the human owner described the goal,
constraints, and acceptance criteria in detail, had Codex propose an implementation plan, reviewed
that plan, then asked Codex to implement the approved scope with tests.

The codebase is roughly 99% AI-generated, but with heavy human direction and review. The human
work centered on clarifying requirements, shaping prompts, reviewing plans, checking code changes,
and deciding whether the generated implementation matched the product goal: fast, simple label
verification that a non-technical user can operate without instructions.

A concrete human override was rejecting backward-compatible use of old field names after the API
contract changed. Codex initially adjusted readiness behavior around legacy field names, but the
human review corrected that direction so the final contract consistently uses the current field
names, such as `class_type`, rather than preserving stale names. The same review direction applied
to tests: new tests were not allowed to keep asserting old field names. When deployed readiness
checks failed because the running environment still expected stale variables, the fix was to
redeploy with the current environment/configuration contract rather than reintroduce legacy
request fields.

## Tools And Libraries

- Python 3.12
- FastAPI
- Uvicorn
- uv
- Pydantic
- Pillow
- OpenAI Python SDK
- RapidFuzz
- pytest
- httpx
- Playwright
- Plain HTML/CSS/JavaScript frontend
- Railway deployment

Default vision model:

```text
gpt-5.4-nano
```

This exact model name was verified against the current OpenAI model list on July 12, 2026. The app
also performs a startup fail-fast model check, and `scripts/readiness_check.py --verify-model` can
run the same validation before deployment.

This proof of concept uses `gpt-5.4-nano` because live testing showed it is consistently fast
enough for the under-5-second single-label requirement. The tradeoff is slightly lower text
extraction accuracy on some label text, such as reading separate words as a single joined word,
so deterministic verification still treats close-but-wrong extractions as fields that may need
review.

The latest deployed benchmark ran 10 sequential live `/verify` requests per model. `gpt-5.4-nano`
was the fastest model overall, with `gpt-5.4-mini` also viable but slower. The older mini/nano
alternatives and `gpt-5.6-luna` missed the under-5-second target by a wide margin.

| Model | API latency p50 | API latency p95 |
| --- | ---: | ---: |
| `gpt-5.4-nano` | 2321 ms | 3400 ms |
| `gpt-5.4-mini` | 3218 ms | 7615 ms |
| `gpt-4o-mini` | 8488 ms | 13607 ms |
| `gpt-4.1-mini` | 13437 ms | 13627 ms |
| `gpt-4.1-nano` | 13504 ms | 13644 ms |
| `gpt-5.6-luna` | 13791 ms | 13949 ms |

After selecting `gpt-5.4-nano`, a second deployed benchmark compared the baseline request with
both latency options enabled: `VISION_REASONING_EFFORT=none` and `OPENAI_SERVICE_TIER=priority`.
This reduced p50 latency from 2449 ms to 2321 ms, a 128 ms / 5.2% improvement, and reduced p95
latency from 3506 ms to 3400 ms, a 106 ms / 3.0% improvement.

| `gpt-5.4-nano` configuration | API latency p50 | API latency p95 |
| --- | ---: | ---: |
| Baseline, latency options unset | 2449 ms | 3506 ms |
| `VISION_REASONING_EFFORT=none`, `OPENAI_SERVICE_TIER=priority` | 2321 ms | 3400 ms |

The model can be changed with the `VISION_MODEL` environment variable. When changing it, keep the
configured model name in sync across the default model constant in `app/vision/service.py`, this
README's model block, local `.env` example, Railway environment variables example, and
`.env.example`.

## Environment Variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `APP_ENV` | No | unset | Identifies the runtime environment. `test` skips the live startup model check. |
| `OPENAI_API_KEY` | Yes for real extraction | unset | OpenAI API key used by the vision client and live model validation. |
| `SKIP_MODEL_CHECK` | No | unset / false | Skips the live `VISION_MODEL` startup check when set to `1`, `true`, `yes`, or `on`. |
| `VISION_MODEL` | No | `gpt-5.4-nano` | OpenAI model used for label extraction and startup validation. |
| `VISION_TIMEOUT_S` | No | `4.0` | Timeout in seconds for OpenAI SDK clients, tuned for the 5-second single-label target. |
| `VISION_REASONING_EFFORT` | No | unset | Optional Responses API reasoning effort for latency experiments. Allowed values: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`. |
| `OPENAI_SERVICE_TIER` | No | unset | Optional Responses API service tier for latency experiments. Allowed values: `auto`, `default`, `flex`, `scale`, `priority`. |
| `MAX_LONG_EDGE` | No | `800` | Maximum long edge, in pixels, for preprocessed label images, tuned for the 5-second single-label target. |
| `JPEG_QUALITY` | No | `55` | JPEG quality used when re-encoding preprocessed label images, tuned for the 5-second single-label target. |
| `MAX_BATCH_SIZE` | No | `5` | Maximum number of labels accepted by one batch request. Keep this at `5` unless the frontend five-card UI limit is changed too. |
| `BATCH_CONCURRENCY` | No | `5` | Maximum number of label images processed concurrently in a batch request. |

## Local Setup

Install dependencies:

```bash
uv sync
```

Create a local environment file if you want to run real vision extraction locally:

```bash
cp .env.example .env
```

Then set local-only values in `.env`:

```text
APP_ENV=local
OPENAI_API_KEY=<your local key>
VISION_MODEL=gpt-5.4-nano
VISION_REASONING_EFFORT=
OPENAI_SERVICE_TIER=
```

Real secret values must not be committed.

## Run Locally

```bash
uv run uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/
```

Health check:

```text
http://127.0.0.1:8000/health
```

Expected health response:

```json
{
  "status": "ok"
}
```

## Run Tests

```bash
uv run pytest
```

The automated tests use fakes/mocks for the vision service. They do not require an OpenAI API key.

Run browser smoke tests for the plain HTML/CSS/JavaScript UI:

```bash
npm install
npx playwright install chromium
npm run test:frontend
```

The frontend smoke tests mock `/verify/batch`; they do not call OpenAI.

## Readiness Check

Run health and page checks against a local or deployed app:

```bash
python scripts/readiness_check.py --base-url http://127.0.0.1:8000
```

To run optional live single-label verification checks, provide an ignored local image and the seven
application fields through environment variables, then add `--verify`. Use `--verify-runs N` to run
N sequential `/verify` requests and report API latency p50/p95 from the response `latency_ms`
values. This may use the deployed vision model and incur API cost.

## API Endpoints

### GET /health

Returns service health:

```json
{
  "status": "ok"
}
```

### POST /verify

Accepts one image plus seven application fields as multipart form data and returns one verification
result. The overall verdict is `APPROVED` when every field passes, otherwise `NEEDS_REVIEW`.

Required multipart fields:

```text
image
brand_name
class_type
producer
country_of_origin
abv
net_contents
government_warning
```

Example request:

Use a real label photo for `image`; replace the sample path with the path to a local image file on
your machine.

```bash
curl -X POST http://127.0.0.1:8000/verify \
  -F "image=@/path/to/your-label-photo.jpg" \
  -F "brand_name=Example Cellars Reserve" \
  -F "class_type=Red Wine" \
  -F "producer=Example Cellars LLC" \
  -F "country_of_origin=United States" \
  -F "abv=13.5%" \
  -F "net_contents=750 mL" \
  -F "government_warning=GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."
```

Successful response:

```json
{
  "verification": {
    "overall_verdict": "APPROVED",
    "latency_ms": 12,
    "results": [
      {
        "field": "brand_name",
        "status": "PASS",
        "expected": "Example Cellars Reserve",
        "found": "Example Cellars Reserve",
        "match_type": "fuzzy_token_sort_ratio",
        "score": 100.0,
        "normalized_application_value": "example cellars reserve",
        "normalized_extracted_value": "example cellars reserve",
        "message": "Fuzzy match passed."
      }
    ]
  },
  "latency_ms": 1380,
  "vision_extraction_failed": false,
  "extracted_label": {
    "brand_name": "Example Cellars Reserve",
    "class_type": "Red Wine",
    "producer": "Example Cellars LLC",
    "country_of_origin": "United States",
    "abv": "13.5% Alc. by Vol.",
    "net_contents": "750 mL",
    "government_warning": "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems.",
    "raw_text": "Example Cellars Reserve\nRed Wine\n13.5% Alc. by Vol.\n750 mL\nGOVERNMENT WARNING: ...",
    "extraction_confidence": 0.96
  },
  "timings": {
    "preprocess_ms": 18,
    "vision_ms": 1210,
    "vision_extraction_failed": false,
    "prepared_image_bytes": 128432,
    "prepared_image_width": 1200,
    "prepared_image_height": 900,
    "model": "gpt-5.4-nano",
    "vision_detail": "high",
    "total_vision_pipeline_ms": 1232,
    "compare_ms": 12,
    "image_read_ms": 2,
    "request_total_ms": 1380,
    "failure_count": 0,
    "overall_verdict": "APPROVED"
  }
}
```

Validation error response:

```json
{
  "message": "Please provide an image and all required label fields.",
  "errors": {
    "image": "Image file is required.",
    "brand_name": "This field is required."
  }
}
```

Per-field `status` values remain `PASS` or `FAIL`. The overall verdict uses `APPROVED` or
`NEEDS_REVIEW`.

### POST /verify/batch

Accepts up to five images plus matching application-data objects. The proof-of-concept UI is
intentionally capped at five label cards, so deployments should keep `MAX_BATCH_SIZE=5` unless the
frontend cap and user-facing copy are updated at the same time.

Multipart fields:

```text
images
items_json
```

`items_json` is a JSON array. Each item corresponds to the image at the same index.

Example request:

Use real label photos for each `images` part; replace the sample paths with paths to local image
files on your machine.

```bash
curl -X POST http://127.0.0.1:8000/verify/batch \
  -F "images=@/path/to/first-label-photo.jpg" \
  -F "images=@/path/to/second-label-photo.jpg" \
  -F 'items_json=[
    {
      "brand_name": "Example Cellars Reserve",
      "class_type": "Red Wine",
      "producer": "Example Cellars LLC",
      "country_of_origin": "United States",
      "abv": "13.5%",
      "net_contents": "750 mL",
      "government_warning": "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."
    },
    {
      "brand_name": "Example Orchard Cider",
      "class_type": "Hard Cider",
      "producer": "Example Orchard LLC",
      "country_of_origin": "United States",
      "abv": "6.2%",
      "net_contents": "12 fl oz",
      "government_warning": "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."
    }
  ]'
```

Successful response:

```json
{
  "summary": {
    "passed": 2,
    "needs_review": 0,
    "total": 2
  },
  "items": [
    {
      "index": 0,
      "filename": "first-label-photo.jpg",
      "status": "APPROVED",
      "verification": {
        "overall_verdict": "APPROVED",
        "latency_ms": 12,
        "results": [
          {
            "field": "brand_name",
            "status": "PASS",
            "expected": "Example Cellars Reserve",
            "found": "Example Cellars Reserve",
            "match_type": "fuzzy_token_sort_ratio",
            "score": 100.0,
            "normalized_application_value": "example cellars reserve",
            "normalized_extracted_value": "example cellars reserve",
            "message": "Fuzzy match passed."
          }
        ]
      },
      "extracted_label": {
        "brand_name": "Example Cellars Reserve",
        "class_type": "Red Wine",
        "producer": "Example Cellars LLC",
        "country_of_origin": "United States",
        "abv": "13.5% Alc. by Vol.",
        "net_contents": "750 mL",
        "government_warning": "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems.",
        "raw_text": "Example Cellars Reserve\nRed Wine\n13.5% Alc. by Vol.\n750 mL\nGOVERNMENT WARNING: ...",
        "extraction_confidence": 0.96
      },
      "vision_extraction_failed": false,
      "latency_ms": 1380,
      "timings": {
        "preprocess_ms": 18,
        "vision_ms": 1210,
        "vision_extraction_failed": false,
        "prepared_image_bytes": 128432,
        "prepared_image_width": 1200,
        "prepared_image_height": 900,
        "model": "gpt-5.4-nano",
        "vision_detail": "high",
        "total_vision_pipeline_ms": 1232,
        "compare_ms": 12,
        "image_read_ms": 2
      },
      "errors": {}
    },
    {
      "index": 1,
      "filename": "second-label-photo.jpg",
      "status": "APPROVED",
      "verification": {
        "overall_verdict": "APPROVED",
        "latency_ms": 10,
        "results": [
          {
            "field": "brand_name",
            "status": "PASS",
            "expected": "Example Orchard Cider",
            "found": "Example Orchard Cider",
            "match_type": "fuzzy_token_sort_ratio",
            "score": 100.0,
            "normalized_application_value": "example orchard cider",
            "normalized_extracted_value": "example orchard cider",
            "message": "Fuzzy match passed."
          }
        ]
      },
      "extracted_label": {
        "brand_name": "Example Orchard Cider",
        "class_type": "Hard Cider",
        "producer": "Example Orchard LLC",
        "country_of_origin": "United States",
        "abv": "6.2% Alc. by Vol.",
        "net_contents": "12 FL OZ",
        "government_warning": "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems.",
        "raw_text": "Example Orchard Cider\nHard Cider\n6.2% Alc. by Vol.\n12 FL OZ\nGOVERNMENT WARNING: ...",
        "extraction_confidence": 0.94
      },
      "vision_extraction_failed": false,
      "latency_ms": 1290,
      "timings": {
        "preprocess_ms": 16,
        "vision_ms": 1130,
        "vision_extraction_failed": false,
        "prepared_image_bytes": 117904,
        "prepared_image_width": 1100,
        "prepared_image_height": 850,
        "model": "gpt-5.4-nano",
        "vision_detail": "high",
        "total_vision_pipeline_ms": 1149,
        "compare_ms": 10,
        "image_read_ms": 2
      },
      "errors": {}
    }
  ]
}
```

Validation error response:

```json
{
  "message": "Each label needs one photo and one set of application data.",
  "errors": {
    "items_json": "Image count and application data count must match."
  }
}
```

Batch `summary` contains counts only. Request/item timing is reported on each item and inside the
nested `verification.latency_ms`; the browser displays client-observed elapsed time for the overall
batch.

## Deployment

The live demo is deployed on Railway from this repository.

Railway start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Required Railway environment variables:

```text
APP_ENV=production
OPENAI_API_KEY=<set in Railway only>
VISION_MODEL=gpt-5.4-nano
```

The OpenAI key is configured only in Railway environment variables. It is not stored in source code,
docs, tests, `.env.example`, or deployment config.

## Accessibility And Usability

The UI is designed for a non-technical user to complete a check without instructions:

- One page with label cards instead of separate single/batch modes.
- Large text and high-contrast controls.
- Clear labels for all seven fields.
- Large primary `Check Label` button.
- Plain-English validation and error messages.
- Visible progress state while labels are being checked.
- Summary counts for batch results.
- Individual results remain viewable for every label.

## Assumptions

- This is a proof of concept, not a production compliance system.
- Human review is required when any field fails or cannot be read.
- The app is stateless and does not store uploaded images or results.
- Batch size is capped at five labels to control latency and API cost.
- JPEG, PNG, and WebP are the supported upload types.

## Limitations

- Vision extraction quality depends on image clarity, glare, cropping, and label layout.
- Poor images may return partial extracted data and produce `NEEDS REVIEW`.
- The fast `gpt-5.4-nano` model can occasionally misread or join visible label text, especially on
  stylized, low-contrast, cropped, or glare-heavy photos.
- Government-warning matching is intentionally strict and may fail for small OCR differences.
- Railway free-tier behavior may add cold-start latency.
- The app does not replace legal review.
- The app does not submit, retrieve, or validate records with TTB systems.

## Potential Fixes

- Add more real-label regression fixtures for OCR-style misspellings, joined words, glare, unusual
  typography, and labels with several producer/importer statements.
- Explore a narrowly scoped second-pass correction step that can repair obvious OCR spacing errors
  without changing the visible label wording or using outside brand knowledge.
- Tune image preprocessing against real bottle photos to improve text readability while preserving
  the under-5-second latency target.

## Secret Handling

- Real API keys belong in environment variables only.
- `.env` and `.env.*` are ignored by git.
- `.env.example` is committed as a placeholder template only.
- Tests use fake vision services and do not need real keys.
- Live readiness checks that post images use local environment variables and ignored local files.

Pre-submission audit commands:

```bash
git ls-files | rg '(^|/)\.env($|\.|-)'
git check-ignore .env
git grep -nE 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*='
rg --hidden --glob '!.git' -n 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*='
git log --all -G 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*=' --oneline
```

For a stronger public-release audit, run a dedicated scanner such as `gitleaks` or `trufflehog`.

## TODO

We are currently tightening the real-label extraction and verification behavior so the proof of
concept handles common wine labels consistently across brands, regions, and countries instead of
only passing curated examples.

- Continue improving the vision prompt so `country_of_origin` is returned as a country-level value,
  producer values contain only the business/entity name, and ABV values ignore unrelated OCR noise.
- Keep expanding country, state, province, and wine-region normalization for common wine-exporting
  countries so labels that show places like California, Mendoza, Bordeaux, Rioja, Marlborough, or
  Western Cape compare against their countries correctly.
- Add alcohol class/type subtype normalization so common subtype labels compare against their main
  TTB-style categories, such as Chardonnay matching Wine and Rye matching Whiskey.
- Preserve strict government-warning wording checks while allowing harmless whitespace and line-break
  differences from OCR extraction.
- Add more real-label regression fixtures beyond the current Barefoot-style cases, especially for
  imported wines, multi-label batches, glare/cropping, and labels with several producer/importer
  statements.
- Re-run full backend and frontend tests after each extraction or comparison change, then verify the
  deployed demo against representative real bottle photos.
