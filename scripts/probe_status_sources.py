"""Read-only HTTP probes with saved response bodies and reproducible receipts.

Used for source discovery, not a production collector. No credentials are read.
Non-200 responses are evidence of access failure, never empty datasets.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "direct-status-research-20261023"


def probe(label, url, data=None, headers=None):
    folder = OUT / label
    folder.mkdir(parents=True, exist_ok=True)
    body = folder / "body"
    args = ["curl", "--silent", "--show-error", "--location", "--compressed", "--max-time", "35",
            "--connect-timeout", "10", "--output", str(body),
            "--write-out", "%{http_code} %{ssl_verify_result} %{url_effective}"]
    for key, value in (headers or {}).items():
        args.extend(["--header", f"{key}: {value}"])
    if data is not None:
        args.extend(["--data", urlencode(data) if isinstance(data, dict) else data])
    result = subprocess.run(args + [url], capture_output=True, text=True)
    parts = result.stdout.strip().split(maxsplit=2)
    receipt = {"label": label, "url": url, "method": "GET" if data is None else "POST",
               "request_data": {k: v for k, v in data.items() if k != "__RequestVerificationToken"}
               if isinstance(data, dict) else data,
               "fetched_at": datetime.now(timezone.utc).isoformat(),
               "curl_exit": result.returncode, "http_status": parts[0] if parts else "0",
               "tls_verify_result": parts[1] if len(parts) > 1 else None,
               "effective_url": parts[2] if len(parts) > 2 else None,
               "error": result.stderr[:1000], "body_path": str(body)}
    if body.exists():
        receipt.update(bytes=body.stat().st_size, sha256=sha256(body.read_bytes()).hexdigest())
    (folder / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    return receipt


def batch(jobs):
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda kwargs: probe(**kwargs), jobs):
            print(json.dumps({k: result.get(k) for k in ("label", "http_status", "bytes", "curl_exit")}), flush=True)
