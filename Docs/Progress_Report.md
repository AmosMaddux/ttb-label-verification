# Progress Report

## Current Status

Phases 0 through 7 are implemented through the current documentation/readiness pass.

- Phase 0: FastAPI health app and hello frontend deployed.
- Phase 1: deterministic comparison engine implemented.
- Phase 2: `VisionService` implemented and mock-tested.
- Phase 3: single-label `POST /verify` implemented.
- Phase 4: single-label UI implemented.
- Phase 5: unified multi-label UI and concurrent `POST /verify/batch` implemented.
- Phase 6: latency, validation, imperfect-image handling, and accessibility hardening implemented.
- Phase 7: README and secret audit completed.

Follow-up hardening pass completed:

- Phase 1 fuzzy matching now uses `rapidfuzz.fuzz.token_sort_ratio` as specified in `Docs/Plan.md`.
- Government-warning comparison now uses case-sensitive exact matching after whitespace collapse;
  wording, capitalization, punctuation, colon, and spelling differences still fail.
- Country matching normalizes common wine states, provinces, and regions to their countries, such as
  California to USA, Mendoza to Argentina, Bordeaux to France, and Marlborough to New Zealand.
- Producer matching strips common role prefixes and trailing location suffixes while still rejecting
  unrelated producer names.
- ABV extraction guidance now emphasizes alcohol-context percentages and comparator tests ensure bad
  OCR such as `IA 5c, ME 15%` does not pass for `14.5%`.
- API response models use stricter status literals and safe default factories for timing maps.
- Added real FastAPI multipart tests for `/verify` and `/verify/batch`.
- Added generated imperfect-image tests for blurry, cropped, glare-like, non-label, and non-image paths.
- Added Playwright frontend smoke tests for core single/batch UI behavior, plain-English errors,
  explicit `View details`, and mobile overflow.
- Added `scripts/readiness_check.py` for health/page checks and optional manually supplied live
  single-label verification.

Live app:

```text
https://ttb-label-verification-production-b67a.up.railway.app
```

Latest verified live behavior:

```text
GET /                -> 200, frontend HTML loads
GET /health          -> 200, {"status":"ok"}
POST /verify         -> valid single label returns PASS under 5 seconds
POST /verify         -> case-only government-warning mismatch returns NEEDS_REVIEW
POST /verify/batch   -> 3-label batch returns correct summary counts and item results
```

Final Phase 7 live audit on June 22, 2026:

```text
Health: PASS, HTTP 200 {"status":"ok"}
Single valid label: PASS, overall_verdict=APPROVED, latency=1692 ms
Warning exact/case mismatch: PASS, overall_verdict=NEEDS_REVIEW, warning=FAIL, latency=1421 ms
Imperfect image: PASS, overall_verdict=APPROVED, latency=2316 ms
Batch: PASS, summary={passed: 2, needs_review: 1, total: 3}
```

The frontend uses same-origin API paths and the backend remains stateless.

## Repository

GitHub remote:

```text
git@github.com:AmosMaddux-FedStack/ttb-label-verification.git
```

Branch:

```text
main
```

Phase 0 commit:

```text
b03d79a Scaffold Phase 0 FastAPI health app
```

Phase 0 deployment docs commit:

```text
bd16dc7 Document Phase 0 deployment progress
```

Push command used:

```bash
git push -u origin main
```

## Railway Deployment

Railway account used:

```text
amos.maddux@fedstack.com
```

Railway workspace:

```text
amosmaddux-fedstack's Projects
```

Railway project:

```text
ttb-label-verification
```

Project ID:

```text
8f92b9fb-44a6-4744-9a80-226fc80f2f36
```

Environment:

```text
production
```

Environment ID:

```text
bc930578-7c11-4513-b2d9-cdf8a13c8681
```

Service:

```text
ttb-label-verification
```

Service ID:

```text
823abc67-f4c0-4298-a0c9-414ad3e2dce2
```

Initial Phase 0 deployment ID:

```text
ad4dc8d5-fbed-4aa2-bf64-e90a6e44d41e
```

Latest verified application deployment ID:

```text
e3f383e2-eb76-4ef5-8eff-7e332f6b4430
```

Public domain:

```text
https://ttb-label-verification-production-b67a.up.railway.app
```

Railway status after deploy:

```text
Online
```

## Commands Used

Local dependency lock and test:

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv lock
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest
```

The `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` overrides were needed in this sandbox because the
default uv cache and Python install directories under the home directory were read-only. On a
normal local machine, these shorter commands should be enough:

```bash
uv lock
uv run pytest
```

Git remote setup:

```bash
git remote set-url origin git@github.com:AmosMaddux-FedStack/ttb-label-verification.git
git ls-remote origin HEAD
```

Commit and push:

```bash
git branch -M main
git add .
git commit -m "Scaffold Phase 0 FastAPI health app"
git push -u origin main
```

Railway CLI login and deployment:

```bash
npx -y @railway/cli login
npx -y @railway/cli up --new --name ttb-label-verification -y --detach --json
npx -y @railway/cli variable set APP_ENV=production --skip-deploys --json
npx -y @railway/cli domain --json
npx -y @railway/cli status
npx -y @railway/cli domain list --json
```

Live verification:

```bash
curl -sS -i https://ttb-label-verification-production-b67a.up.railway.app/health
curl -sS -i https://ttb-label-verification-production-b67a.up.railway.app/
```

Expected `/health` response:

```json
{"status":"ok"}
```

## Files Created For Phase 0

```text
.env.example
.gitignore
.python-version
README.md
pyproject.toml
railway.json
uv.lock
app/__init__.py
app/main.py
app/static/index.html
app/static/app.js
app/static/styles.css
tests/test_health.py
```

`Docs/Plan.md` contains the Phase 0 plan and finalized Phase 1, Phase 2, and Phase 3 plans.

## Phase 1 Comparison Engine

Phase 1 adds pure Python comparison logic for structured application data against structured label
extraction data. This phase does not include model calls, image handling, upload flow, database
state, or UI work.

Files added:

```text
app/verification/__init__.py
app/verification/models.py
app/verification/comparisons.py
tests/test_verification_comparisons.py
```

Implemented models:

- `ApplicationData`
- `ExtractedLabel`
- `FieldResult`
- `VerificationResult`

Implemented comparison functions:

- `compare_brand_name`
- `compare_product_class`
- `compare_producer`
- `compare_country_of_origin`
- `compare_abv`
- `compare_net_contents`
- `compare_government_warning`
- `verify_label`

Country comparison now recognizes common wine-producing states, provinces, and regions and maps
them to country-level values. Producer comparison removes common label role phrases and location
suffixes before RapidFuzz scoring. ABV comparison still uses a strict `<= 0.1` percentage-point
tolerance and does not accept incorrect OCR percentages.

Phase 1 verification command:

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest
```

Latest result:

```text
47 passed in 0.23s
```

Strict government warning behavior:

- Exact all-caps warning passes.
- Title-case warning fails.
- Lowercase warning fails.
- Warning missing the colon fails.
- Missing punctuation fails.
- Whitespace-only differences such as repeated spaces, tabs, or line breaks pass.
- Missing extracted warning fails.
- Reworded warning fails.
- Misread warning failures preserve the exact extracted warning text in `FieldResult.found`.

The implementation uses strict case-sensitive comparison after whitespace collapse for the
government warning:

```python
status = "PASS" if normalized_application == normalized_extracted else "FAIL"
```

The Phase 1 work honored the no-network requirement. Fuzzy matching now uses local deterministic
RapidFuzz token-sort scoring.

## Phase 2 VisionService

Phase 2 adds the service layer for extracting structured label fields from one image. It introduces
AI for extraction only; deterministic verification remains in the Phase 1 comparison engine.

Files added:

```text
app/vision/__init__.py
app/vision/client.py
app/vision/fakes.py
app/vision/preprocessing.py
app/vision/service.py
scripts/run_sample_extraction.py
tests/test_vision_service.py
```

Files changed:

```text
.env.example
.gitignore
app/verification/models.py
pyproject.toml
uv.lock
```

Implemented behavior:

- `VisionService.extract_label(...)` accepts image bytes and returns `ExtractedLabel`.
- Images are preprocessed with Pillow: EXIF orientation correction, RGB conversion, long-edge
  downscale, and JPEG re-encode.
- OpenAI access is behind an injectable client adapter so tests can use fakes and Phase 3 endpoint
  tests do not need real API calls.
- Structured output uses the existing seven `ExtractedLabel` fields.
- Defensive parsing returns an all-null `ExtractedLabel` for malformed output, missing output,
  provider/client errors, timeouts, preprocessing failures, and non-label/null responses.
- The extraction prompt emphasizes verbatim government-warning capture because downstream matching
  is exact and case-sensitive.
- `app/vision/fakes.py` provides `FakeVisionClient` for tests and future endpoint integration tests.

Dependencies added:

```text
openai
pillow
```

Environment variables:

```text
OPENAI_API_KEY
VISION_MODEL
```

Secret status:

- `OPENAI_API_KEY` is set in Railway.
- No API key value is stored in the repo, docs, `.env.example`, tests, or committed config.
- `.env` and `.env.*` remain ignored by git.

Phase 2 verification command:

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest
```

Latest result:

```text
68 passed in 0.45s
```

Sample extraction command:

```bash
uv run python scripts/run_sample_extraction.py
```

The script creates `samples/sample_label.jpg` if no path is provided. `samples/` is gitignored.

Real sample status:

- Initial local run without `OPENAI_API_KEY` failed safely with a controlled config message.
- User later set a new OpenAI API key locally/Railway.
- User confirmed sample image extraction is working and returns a populated `ExtractedLabel`.
- A transient `RateLimitError` path was observed and correctly returned an all-null
  `ExtractedLabel` instead of crashing.

Railway variable command that works:

```bash
printf '%s' "$OPENAI_API_KEY" | npx -y @railway/cli variable set OPENAI_API_KEY --stdin
```

## Phase 3 Verification Endpoint

Phase 3 adds a single-image multipart `POST /verify` API endpoint. It validates request input,
extracts label data through `VisionService`, compares with the Phase 1 deterministic verifier, and
returns verification results plus latency.

Files added:

```text
app/api/__init__.py
app/api/models.py
app/api/verify.py
tests/test_verify_endpoint.py
```

Files changed:

```text
app/main.py
pyproject.toml
uv.lock
Docs/Plan.md
```

Dependency added:

```text
python-multipart
```

Implemented behavior:

- `POST /verify` accepts multipart `image` plus seven required application fields.
- Valid image content types: `image/jpeg`, `image/png`, `image/webp`.
- Upload size cap: `8 MB`.
- Missing image and missing/blank fields return readable `400` JSON errors.
- Bad file type returns readable `415` JSON error.
- Oversized file returns readable `413` JSON error.
- Response includes `verification`, `verification.overall_verdict`, all per-field results,
  `latency_ms`, and `extracted_label`.
- Failed fields include expected-vs-found values through `expected` and
  `found`.
- Government warning extracted text is surfaced in both `extracted_label.government_warning` and
  the `government_warning` field result's `found`.
- Latency is measured for each request and logged.
- Requests over `5000 ms` produce warning-level logs for the single-label budget.
- Endpoint tests use mocked vision service and do not call OpenAI.

Phase 3 verification command:

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest
```

Latest result:

```text
82 passed in 0.47s
```

Local HTTP success check:

- Ran local FastAPI server with Railway environment variables via `railway run`.
- Posted `samples/sample_label.jpg` to `/verify`.
- Response status: `200`.
- Response included full `VerificationResult`, all seven field results, `latency_ms`, and
  `extracted_label`.
- Observed `latency_ms`: `3249`.
- Observed verdict: `NEEDS_REVIEW`.
- Note: current government-warning comparison now tolerates whitespace-only OCR differences such as
  extracted line breaks while preserving strict wording, punctuation, and case checks.

Invalid input checks:

Bad file type:

```json
{"message":"Please provide an image and all required label fields.","errors":{"image":"Unsupported file type."}}
```

```text
HTTP_STATUS:415
```

Empty submission:

```json
{"message":"Please provide an image and all required label fields.","errors":{"image":"Image file is required.","brand_name":"This field is required.","class_type":"This field is required.","producer":"This field is required.","country_of_origin":"This field is required.","abv":"This field is required.","net_contents":"This field is required.","government_warning":"This field is required."}}
```

```text
HTTP_STATUS:400
```

Deployment note:

- Phase 3 has been tested locally but the public Railway app still needs redeploy after this commit
  before `/verify` is live on the Railway URL.

## Phase 4 Single-Label Frontend

Phase 4 replaces the Phase 0 health-check screen with a usable single-label verification page wired
to same-origin `/verify`.

Files changed:

```text
app/static/index.html
app/static/app.js
app/static/styles.css
Docs/Progress_Report.md
```

Implemented behavior:

- Image upload control for JPEG, PNG, and WebP.
- Preview of selected label image.
- Required application fields for brand name, product class, producer, country of origin, ABV, net
  contents, and government warning.
- Form submission sends `multipart/form-data` to `/verify`.
- Successful responses render overall verdict, latency, all per-field results, expected-vs-found
  values, and extracted label text.
- Government warning extracted text is visible in field results and extracted-label details.
- API errors render readable messages on the page.
- Backend health badge still uses same-origin `/health`.

Phase 4 verification command:

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest
```

Latest local result:

```text
82 passed in 0.57s
```

## Phase 5 Unified Multi-Label Batch Flow

Phase 5 removes the separate single/batch mode split and uses one page with one or more label cards.
One card behaves like single-label mode. Two to five cards behave like batch mode.

Files changed:

```text
app/api/models.py
app/api/verify.py
app/static/index.html
app/static/app.js
app/static/styles.css
tests/test_verify_endpoint.py
Docs/Plan.md
```

Implemented backend behavior:

- Added `POST /verify/batch`.
- Accepts repeated `images` plus an `items_json` array.
- Pairs each image with the application-data object at the same index.
- Enforces batch size maximum of `5`.
- Enforces total batch upload maximum of `25 MB`.
- Processes labels concurrently with `asyncio.gather` and a bounded semaphore.
- Preserves per-item error isolation: one invalid label returns one item-level `NEEDS_REVIEW` and
  does not fail the whole batch.
- Returns summary counts:
  - `passed`
  - `needs_review`
  - `total`
  - `latency_ms`
- Returns individual results for drill-down.

Implemented frontend behavior:

- The page starts with one label card.
- `Add Label` adds another card up to five total cards.
- Multiple cards submit to `/verify/batch`.
- One card submits to `/verify`.
- Shows a progress indicator while labels are being checked.
- Shows batch summary counts.
- Keeps individual results viewable for each label.

Phase 5 local verification:

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest
node --check app/static/app.js
```

Live Phase 5-style batch check:

```text
3-label batch returned HTTP 200
summary={passed: 2, needs_review: 1, total: 3}
```

## Phase 6 Hardening, Latency, Validation, And Accessibility

Phase 6 adds no new feature workflow. It hardens the existing single and batch paths.

Files changed:

```text
app/api/models.py
app/api/verify.py
app/static/styles.css
app/vision/preprocessing.py
app/vision/service.py
tests/test_verify_endpoint.py
tests/test_vision_service.py
Docs/Plan.md
```

Implemented behavior:

- Tuned image preprocessing to a `1400px` max long edge and JPEG quality `76`.
- Added timing metadata to single-label and batch item responses.
- Timing metadata includes preprocessing, model call, prepared image size, comparison, total
  request time, model name, detail level, verdict, and failure count.
- Validates that uploaded image bytes are readable images, not just that the content type is allowed.
- Unreadable image bytes return a plain `400` response instead of reaching vision extraction.
- Preserves existing limits:
  - single image max: `8 MB`
  - batch total image bytes max: `25 MB`
  - batch size max: `5`
  - supported image types: JPEG, PNG, WebP
- Vision failures and imperfect images degrade into partial/null extraction and normal
  `NEEDS_REVIEW` behavior instead of stack traces.
- UI accessibility pass increased base font size, strengthened labels and messages, and added
  clearer focus states.

Phase 6 local verification:

```text
92 passed in 0.58s
node --check app/static/app.js passed
```

Phase 6 live latency audit:

```text
single-label count: 8
min: 1001 ms
max: 1453 ms
mean: 1203.4 ms
p50: 1184.5 ms
batch latency: 1462 ms
```

The deployed app met the project requirement that single-label checks complete under five seconds.

## Phase 7 README And Secret Audit

Phase 7 updates project documentation and runs a final readiness audit.

Files changed:

```text
README.md
Docs/Plan.md
Docs/Progress_Report.md
```

README now covers:

- live URL and health URL,
- overview,
- seven verification fields,
- matching rules,
- verdict rule,
- local setup with `uv`,
- run and test commands,
- API endpoints,
- Railway deployment notes,
- tools and libraries,
- accessibility/usability notes,
- assumptions,
- limitations,
- secret handling.

Secret audit checks run:

```bash
git ls-files | rg '(^|/)\.env($|\.|-)'
git check-ignore .env
git check-ignore tests/test_images/
git grep -nE 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*='
rg --hidden --glob '!.git' --glob '!tests/test_images/**' -n 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*='
git log --all -G 'sk-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|OPENAI_API_KEY\s*=.+|RAILWAY_TOKEN\s*=.+|api[_-]?key\s*=|secret\s*=|token\s*=' --oneline -- . ':!tests/test_images'
```

Secret audit result:

- `.env.example` is the only tracked env-style file.
- `.env` is ignored.
- `tests/test_images/` is ignored.
- Current-tree matches are placeholders, documentation, or code reading environment variable names.
- History matches were reviewed and did not contain real key values.

Final Phase 7 local verification:

```text
92 passed in 0.65s
node --check app/static/app.js passed
```

Final Phase 7 live verification on June 22, 2026:

```text
Health: PASS, HTTP 200 {"status":"ok"}
Single valid label: PASS, overall_verdict=APPROVED, latency=1692 ms
Warning exact/case mismatch: PASS, overall_verdict=NEEDS_REVIEW, warning=FAIL, latency=1421 ms
Imperfect image: PASS, overall_verdict=APPROVED, latency=2316 ms
Batch: PASS, summary={passed: 2, needs_review: 1, total: 3}
```

## Important Decisions

- One FastAPI service serves both the API and the static frontend.
- No CORS middleware is needed in Phase 0 because frontend and backend are same-origin.
- Frontend uses relative `/health`, not a hardcoded backend URL.
- `.env` and `.env.*` are gitignored.
- `.env.example` is committed and contains placeholders only.
- `APP_ENV=production` is set in Railway.
- `railway.json` pins the start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

## Restart Checklist

From a fresh clone:

```bash
git clone git@github.com:AmosMaddux-FedStack/ttb-label-verification.git
cd ttb-label-verification
uv run pytest
uv run uvicorn app.main:app --reload
```

Open locally:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/health
```

To check Railway:

```bash
npx -y @railway/cli login
npx -y @railway/cli status
npx -y @railway/cli logs --lines 100
```

To redeploy from the current directory:

```bash
npx -y @railway/cli up --detach
```

To run the Phase 2 sample extractor from a fresh clone:

```bash
export OPENAI_API_KEY="set-this-locally-only"
uv run python scripts/run_sample_extraction.py
```

## Current Next Notes

The implemented proof of concept now includes deploy-first setup, deterministic comparison, vision
extraction, single-label verification, unified multi-label batch verification, hardening, README
documentation, and a clean secret audit.

Future work should stay inside the standing project rules:

- Single-label result under 5 seconds.
- Batch upload is required.
- Government warning match is exact and case-sensitive after whitespace collapse.
- Other fields are fuzzy/normalized.
- API keys must only live in environment variables, never in code or commits.
