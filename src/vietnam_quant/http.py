"""Public HTTP reads using curl and the operating system's validated TLS trust."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class FetchError(RuntimeError):
    pass


class Client:
    def __init__(self, raw_dir, extra_args=(), *, refresh=False, timeout=30):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.extra_args = list(extra_args)
        self.refresh = refresh
        self.timeout = timeout

    def fetch_large_get(self, url):
        """Verified stdlib transport for large HOSE board responses.

        The host intermittently truncates curl transfers. Keep TLS verification,
        require a full Content-Length match when supplied, and retain receipts.
        """
        key = sha256(url.encode()).hexdigest()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.raw_dir / f"{stamp}-{key}.body"
        receipt_path = path.with_suffix(".receipt.json")
        receipt = {"url": url, "method": "GET", "data": None, "transport": "urllib",
                   "body_path": str(path.resolve()), "http_status": 0,
                   "tls_verify_result": None, "curl_exit": None}
        for attempt in range(2):
            try:
                started = time.monotonic()
                with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as response:
                    receipt["http_status"] = response.status
                    if response.status != 200:
                        raise FetchError(f"Unexpected HTTP {response.status}")
                    chunks = []
                    while True:
                        if time.monotonic() - started > 180:
                            raise FetchError("Large response exceeded 180 second deadline")
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    expected = response.headers.get("Content-Length")
                    if expected is not None and len(body) != int(expected):
                        raise FetchError("Incomplete Content-Length")
                path.write_bytes(body)
                receipt.update(fetched_at=utc_now(), attempts=attempt + 1,
                               tls_verify_result=0, sha256=sha256(body).hexdigest(), error="")
                receipt_path.write_text(json.dumps(receipt, indent=2))
                return body.decode("utf-8-sig"), receipt
            except Exception as exc:
                receipt.update(fetched_at=utc_now(), attempts=attempt + 1, error=str(exc)[:500])
                receipt_path.write_text(json.dumps(receipt, indent=2))
        raise FetchError(f"Large verified HTTP read failed: {url}: {receipt['error']}")

    def fetch(self, url, data=None, *, cache=False):
        safe_data = {k: v for k, v in data.items() if k != "__RequestVerificationToken"} if data else data
        request = {"url": url, "method": "GET" if data is None else "POST", "data": safe_data}
        key = sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        if cache and not self.refresh:
            candidates = sorted(self.raw_dir.glob(f"*-{key}.receipt.json"))
            if candidates:
                receipt_path = candidates[-1]
                receipt = json.loads(receipt_path.read_text())
                body = Path(receipt["body_path"])
                if (receipt.get("http_status") == 200 and receipt.get("curl_exit") == 0
                        and receipt.get("tls_verify_result") == 0 and body.exists()
                        and sha256(body.read_bytes()).hexdigest() == receipt.get("sha256")):
                    return body.read_text(), receipt
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        body_path = self.raw_dir / f"{stamp}-{key}.body"
        receipt_path = self.raw_dir / f"{stamp}-{key}.receipt.json"
        command = ["curl", *self.extra_args, "--silent", "--show-error", "--location", "--compressed", "--max-time", str(self.timeout),
                   "--connect-timeout", "10", "--output", str(body_path),
                   "--write-out", "%{http_code} %{ssl_verify_result}"]
        if data is not None:
            command += ["--data", urlencode(data)]
        for attempt in range(3):
            result = subprocess.run(command + [url], capture_output=True, text=True)
            pieces = result.stdout.strip().split()
            status = int(pieces[0]) if pieces and pieces[0].isdigit() else 0
            tls = int(pieces[1]) if len(pieces) == 2 and pieces[1].isdigit() else -1
            receipt = {**request, "fetched_at": utc_now(), "curl_exit": result.returncode,
                       "http_status": status, "tls_verify_result": tls,
                       "body_path": str(body_path.resolve()), "attempts": attempt + 1,
                       "error": result.stderr[:500]}
            if result.returncode == 0 and status == 200 and tls == 0:
                receipt["sha256"] = sha256(body_path.read_bytes()).hexdigest()
                receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
                return body_path.read_text(encoding="utf-8-sig"), receipt
            if attempt < 2:
                time.sleep(attempt + 1)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        raise FetchError(f"HTTP read failed: {url} (curl={result.returncode}, HTTP={status})")
