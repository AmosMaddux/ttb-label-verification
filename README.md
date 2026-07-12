# TTB Label Verification Proof Of Concept

This is a small proof of concept for checking alcohol beverage label images against application
data. It uses a FastAPI backend, a plain HTML/CSS/JavaScript frontend, OpenAI vision extraction,
and deterministic comparison rules.

The app is intentionally stateless. It has no database and does not submit anything to TTB systems.

## Live Demo

- App: https://ttb-label-verification-production-b67a.up.railway.app/
- Health check: https://ttb-label-verification-production-b67a.up.railway.app/health
- Last live verification: June 22, 2026
- Single-label target: under 5 seconds
- Observed live single-label range during final audit: 1421 ms to 2316 ms
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

| Field | Match type |
| --- | --- |
| Brand name | Fuzzy token-sort match |
| Product type | Fuzzy token-sort match |
| Producer or company | Fuzzy token-sort match after role/location cleanup |
| Country | Exact match after country, state, province, and wine-region normalization |
| Alcohol percentage | Numeric ABV normalization with tolerance |
| Bottle size | Unit normalization to milliliters with tolerance |
| Government warning | Case-sensitive exact match after whitespace collapse |

Whitespace-only OCR differences such as line breaks, tabs, repeated spaces, or leading/trailing
spaces are tolerated for the government warning. Capitalization, punctuation, colon, spelling, and
wording must still match.

Country matching normalizes common wine regions and subdivisions to their countries, such as
`California` to `United States`, `Mendoza` to `Argentina`, and `Bordeaux` to `France`. Producer
matching ignores common role phrases and trailing locations, such as `VINTED & BOTTLED BY ...,
MODESTO, CALIFORNIA`, while still rejecting unrelated company names. ABV matching prefers numbers
attached to alcohol wording and does not loosen tolerance to hide bad OCR.

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
gpt-5.4-mini
```

The model can be changed with the `VISION_MODEL` environment variable.

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
VISION_MODEL=gpt-5.4-mini
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

To run an optional live single-label verification, provide an ignored local image and the seven
application fields through environment variables, then add `--verify`. This may use the deployed
vision model and incur API cost.

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

Response shape:

```json
{
  "verification": {
    "overall_verdict": "APPROVED",
    "latency_ms": 12,
    "results": [
      {
        "field": "brand_name",
        "status": "PASS",
        "expected": "Acme Reserve",
        "found": "Acme Reserve",
        "match_type": "fuzzy_token_sort_ratio",
        "score": 100.0,
        "normalized_application_value": "acme reserve",
        "normalized_extracted_value": "acme reserve",
        "message": "Fuzzy match passed."
      }
    ]
  },
  "latency_ms": 1421,
  "vision_extraction_failed": false,
  "extracted_label": {
    "brand_name": "Acme Reserve",
    "class_type": "Red Wine",
    "producer": "Acme Winery LLC",
    "country_of_origin": "USA",
    "abv": "13.5% Alc. by Vol.",
    "net_contents": "750 mL",
    "government_warning": "GOVERNMENT WARNING: exact text",
    "raw_text": "Complete transcribed label text",
    "extraction_confidence": 0.94
  },
  "timings": {
    "vision_ms": 1200,
    "compare_ms": 12,
    "request_total_ms": 1421
  }
}
```

Per-field `status` values remain `PASS` or `FAIL`. The overall verdict uses `APPROVED` or
`NEEDS_REVIEW`.

### POST /verify/batch

Accepts up to five images plus matching application-data objects.

Multipart fields:

```text
images
items_json
```

`items_json` is a JSON array. Each item corresponds to the image at the same index.

Response shape:

```json
{
  "summary": {
    "passed": 1,
    "needs_review": 0,
    "total": 1
  },
  "items": [
    {
      "index": 0,
      "filename": "label.jpg",
      "status": "APPROVED",
      "verification": {
        "overall_verdict": "APPROVED",
        "latency_ms": 12,
        "results": []
      },
      "extracted_label": null,
      "vision_extraction_failed": false,
      "latency_ms": 1421,
      "timings": {},
      "errors": {}
    }
  ]
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
VISION_MODEL=gpt-5.4-mini
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
- Government-warning matching is intentionally strict and may fail for small OCR differences.
- Railway free-tier behavior may add cold-start latency.
- The app does not replace legal review.
- The app does not submit, retrieve, or validate records with TTB systems.

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
rg --hidden --glob '!.git' --glob '!tests/test_images/**' -n 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*='
git log --all -G 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*=' --oneline -- . ':!tests/test_images'
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
- Preserve strict government-warning wording checks while allowing harmless whitespace and line-break
  differences from OCR extraction.
- Add more real-label regression fixtures beyond the current Barefoot-style cases, especially for
  imported wines, multi-label batches, glare/cropping, and labels with several producer/importer
  statements.
- Re-run full backend and frontend tests after each extraction or comparison change, then verify the
  deployed demo against representative real bottle photos.
