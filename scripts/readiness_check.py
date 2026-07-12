"""Read-only readiness checks for a running deployment or local server.

The script checks `GET /health`, `GET /`, and optionally posts a sample
single-label verification request using environment-provided fields.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.vision.model_check import validate_configured_model_available


REQUIRED_FIELDS = [
    "brand_name",
    "class_type",
    "producer",
    "country_of_origin",
    "abv",
    "net_contents",
    "government_warning",
]


def main() -> int:
    """Parse command-line options and run the selected readiness checks.

    Inputs:
        CLI flags, plus optional environment variables such as
        `READINESS_BASE_URL` and the `READINESS_*` verification fields.

    Outputs:
        Process exit code `0` when all checks pass, otherwise `1`. The function
        also prints a JSON report to stdout.
    """
    parser = argparse.ArgumentParser(description="Run read-only readiness checks against the app.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("READINESS_BASE_URL", "http://127.0.0.1:8000"),
        help="App base URL. Defaults to READINESS_BASE_URL or local dev server.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Also POST /verify using local image and fields from env vars.",
    )
    parser.add_argument(
        "--verify-model",
        action="store_true",
        help="Also confirm VISION_MODEL appears in OpenAI's live models list.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    checks = [
        check_get(f"{base_url}/health", expected_json={"status": "ok"}),
        check_get(f"{base_url}/"),
    ]

    if args.verify:
        checks.append(check_verify(f"{base_url}/verify"))
    if args.verify_model:
        checks.append(check_model())

    print(json.dumps({"base_url": base_url, "checks": checks}, indent=2))
    return 0 if all(check["ok"] for check in checks) else 1


def check_get(url: str, *, expected_json: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check a GET endpoint and optionally verify its JSON body.

    Inputs:
        `url` to request and optional `expected_json` payload for exact body
        comparison.

    Outputs:
        A dictionary containing check name, pass/fail status, HTTP status, and
        latency or error metadata.
    """
    start = time.perf_counter()
    try:
        response = request.urlopen(url, timeout=15)
        body = response.read()
        result: dict[str, Any] = {
            "name": f"GET {url}",
            "ok": 200 <= response.status < 300,
            "status": response.status,
            "latency_ms": elapsed_ms(start),
        }
        if expected_json is not None:
            result["ok"] = result["ok"] and json.loads(body.decode("utf-8")) == expected_json
        return result
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return failure(f"GET {url}", start, exc)


def check_verify(url: str) -> dict[str, Any]:
    """Post one verification request using environment-provided sample data.

    Inputs:
        URL for the `/verify` endpoint. Image path and all field values are read
        from `READINESS_LABEL_IMAGE` and `READINESS_<FIELD>` environment vars.

    Outputs:
        A check-result dictionary including verdict and API latency on success,
        or missing-input/error details on failure.
    """
    start = time.perf_counter()
    image_path = os.environ.get("READINESS_LABEL_IMAGE")
    fields = {field: os.environ.get(f"READINESS_{field.upper()}") for field in REQUIRED_FIELDS}

    missing = [field for field, value in fields.items() if not value]
    if not image_path:
        missing.append("READINESS_LABEL_IMAGE")
    if missing:
        return {
            "name": f"POST {url}",
            "ok": False,
            "status": None,
            "latency_ms": elapsed_ms(start),
            "error": "Missing required readiness inputs.",
            "missing": missing,
        }

    try:
        body, content_type = multipart_body(
            fields={field: value or "" for field, value in fields.items()},
            image_path=Path(image_path),
        )
        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        response = request.urlopen(req, timeout=30)
        payload = json.loads(response.read().decode("utf-8"))
        return {
            "name": f"POST {url}",
            "ok": 200 <= response.status < 300,
            "status": response.status,
            "latency_ms": elapsed_ms(start),
            "overall_verdict": payload.get("verification", {}).get("overall_verdict"),
            "api_latency_ms": payload.get("latency_ms"),
        }
    except (OSError, HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return failure(f"POST {url}", start, exc)


def check_model() -> dict[str, Any]:
    """Verify `VISION_MODEL` against OpenAI's live models-list endpoint."""
    start = time.perf_counter()
    try:
        model = asyncio.run(validate_configured_model_available())
        return {
            "name": "OpenAI VISION_MODEL",
            "ok": True,
            "status": None,
            "latency_ms": elapsed_ms(start),
            "model": model,
        }
    except Exception as exc:
        return failure("OpenAI VISION_MODEL", start, exc)


def multipart_body(*, fields: dict[str, str], image_path: Path) -> tuple[bytes, str]:
    """Build a multipart/form-data body for the readiness verification request.

    Inputs:
        Form field strings and a local image path.

    Outputs:
        `(body_bytes, content_type_header)` ready for `urllib.request.Request`.
    """
    boundary = f"----readiness-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8"),
            image_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def failure(name: str, start: float, exc: Exception) -> dict[str, Any]:
    """Build a standardized failed-check dictionary.

    Inputs:
        Check name, start timestamp, and the exception that caused the failure.

    Outputs:
        A JSON-serializable dictionary with failure status, latency, and error
        type.
    """
    return {
        "name": name,
        "ok": False,
        "status": getattr(exc, "code", None),
        "latency_ms": elapsed_ms(start),
        "error": type(exc).__name__,
    }


def elapsed_ms(start: float) -> int:
    """Calculate elapsed milliseconds for readiness check reporting.

    Inputs:
        A `time.perf_counter()` start value.

    Outputs:
        Integer milliseconds elapsed since `start`.
    """
    return int((time.perf_counter() - start) * 1000)


if __name__ == "__main__":
    raise SystemExit(main())
