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
from math import ceil
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
        "--verify-runs",
        default=1,
        type=positive_int,
        help="Number of sequential /verify requests to run when --verify is set.",
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
        checks.append(check_verify(f"{base_url}/verify", runs=args.verify_runs))
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


def check_verify(url: str, *, runs: int = 1) -> dict[str, Any]:
    """Post one or more verification requests using environment-provided sample data.

    Inputs:
        URL for the `/verify` endpoint. Image path and all field values are read
        from `READINESS_LABEL_IMAGE` and `READINESS_<FIELD>` environment vars.
        `runs` controls how many sequential requests are sent.

    Outputs:
        A check-result dictionary including verdicts, per-request API latencies,
        p50/p95 API latency statistics, or missing-input/error details.
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
        payloads: list[dict[str, Any]] = []
        statuses: list[int] = []
        for _ in range(runs):
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
            statuses.append(response.status)
            payloads.append(json.loads(response.read().decode("utf-8")))

        api_latencies = [_api_latency_ms(payload) for payload in payloads]
        return {
            "name": f"POST {url}",
            "ok": all(200 <= status < 300 for status in statuses),
            "status": statuses[-1],
            "runs": runs,
            "latency_ms": elapsed_ms(start),
            "overall_verdict": payloads[-1].get("verification", {}).get("overall_verdict"),
            "overall_verdicts": [
                payload.get("verification", {}).get("overall_verdict") for payload in payloads
            ],
            "api_latency_ms": api_latencies[-1],
            "api_latency_ms_values": api_latencies,
            "api_latency_p50_ms": percentile_nearest_rank(api_latencies, 50),
            "api_latency_p95_ms": percentile_nearest_rank(api_latencies, 95),
        }
    except (OSError, HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return failure(f"POST {url}", start, exc)


def _api_latency_ms(payload: dict[str, Any]) -> int:
    """Extract the API-reported latency from a verification response."""
    latency = payload.get("latency_ms")
    if not isinstance(latency, int):
        raise ValueError("Verification response did not include integer latency_ms.")
    return latency


def percentile_nearest_rank(values: list[int], percentile: int) -> int | None:
    """Calculate a nearest-rank percentile for integer latency values."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil((percentile / 100) * len(ordered)) - 1)
    return ordered[index]


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
        "message": str(exc),
    }


def elapsed_ms(start: float) -> int:
    """Calculate elapsed milliseconds for readiness check reporting.

    Inputs:
        A `time.perf_counter()` start value.

    Outputs:
        Integer milliseconds elapsed since `start`.
    """
    return int((time.perf_counter() - start) * 1000)


def positive_int(value: str) -> int:
    """Argparse type for positive integers."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
