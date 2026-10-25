"""Anonymous, TLS-verified HTTP with pacing and immutable attempt receipts."""

import hashlib
import json
import ssl
import threading
import time
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

import truststore

from .contract import SourceError


class TransportError(SourceError):
    pass


def retry_after_seconds(value, now=None):
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try:
            until = parsedate_to_datetime(value)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            return max(0, (until - (now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


class Transport:
    def __init__(
        self, raw_dir, settings, *, opener=urlopen, sleep=time.sleep, clock=time.monotonic
    ):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.opener, self.sleep, self.clock = opener, sleep, clock
        self.lock = threading.Lock()
        self.last_started = None
        self.progress = None
        self.ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def _pace(self):
        if self.last_started is not None:
            delay = self.settings.request_interval_seconds - (self.clock() - self.last_started)
            if delay > 0:
                self.sleep(delay)
        self.last_started = self.clock()

    def request(self, name, url, *, payload=None, form=None):
        if not url.startswith("https://"):
            raise TransportError("Only HTTPS endpoints are supported")
        if payload is not None and form is not None:
            raise ValueError("Specify JSON or form data, not both")
        data = None
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/html"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if form is not None:
            data = urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=data, headers=headers)
        # Directory fetches may use threads; serialize to enforce one global pace.
        with self.lock:
            for attempt in range(1, self.settings.max_attempts + 1):
                self._pace()
                receipt = {
                    "url": url,
                    "method": request.get_method(),
                    "request": payload if payload is not None else form,
                    "authentication": "none",
                    "tls_verification": True,
                    "tls_backend": "system_truststore",
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                    "attempt": attempt,
                }
                raw, status, retry_header, error, retryable = b"", 0, None, None, False
                try:
                    with self.opener(
                        request, timeout=self.settings.timeout_seconds, context=self.ssl_context
                    ) as response:
                        status = response.status
                        retry_header = response.headers.get("Retry-After")
                        raw = response.read(16 * 1024 * 1024 + 1)
                        if len(raw) > 16 * 1024 * 1024:
                            raise TransportError("Response exceeds 16 MiB limit")
                        length = response.headers.get("Content-Length")
                        if length is not None and len(raw) != int(length):
                            raise IncompleteRead(raw)
                        if status != 200:
                            error = f"HTTP {status}"
                            retryable = status == 429 or 500 <= status < 600
                except HTTPError as exc:
                    status, retry_header = exc.code, exc.headers.get("Retry-After")
                    raw = exc.read(16 * 1024 * 1024)
                    exc.close()
                    error = f"HTTP {status}"
                    retryable = status == 429 or 500 <= status < 600
                except (URLError, TimeoutError, OSError, IncompleteRead) as exc:
                    if isinstance(exc, IncompleteRead):
                        raw = exc.partial
                    error, retryable = str(exc), True
                except (ValueError, TransportError) as exc:
                    error = str(exc)
                receipt.update(
                    http_status=status,
                    received_at=datetime.now(timezone.utc).isoformat(),
                    bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    error=error,
                    retry_after=retry_header,
                )
                stem = f"{name}-attempt-{attempt}-{uuid.uuid4().hex[:8]}"
                (self.raw_dir / f"{stem}.body").write_bytes(raw)
                (self.raw_dir / f"{stem}-receipt.json").write_text(
                    json.dumps(receipt, indent=2), encoding="utf-8"
                )
                if error is None:
                    return raw, receipt
                if not retryable or attempt == self.settings.max_attempts:
                    break
                wait = retry_after_seconds(retry_header)
                if wait is None:
                    wait = self.settings.backoff_seconds * 2 ** (attempt - 1)
                if wait > self.settings.max_retry_wait_seconds:
                    raise TransportError(
                        f"{name}: server requests {wait}s wait; retry on a later run"
                    )
                if self.progress:
                    self.progress(
                        f"请求暂未成功，{wait:g} 秒后重试（{attempt}/{self.settings.max_attempts}）…",
                        flush=True,
                    )
                self.sleep(wait)
        raise TransportError(f"{name}: {error}")

    def json(self, name, url, payload=None):
        raw, receipt = self.request(name, url, payload=payload)
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise TransportError(f"{name}: invalid JSON response (raw response saved)") from exc
        # Named copies are consumed by the same offline replay parser.
        (self.raw_dir / f"{name}.json").write_bytes(raw)
        (self.raw_dir / f"{name}-receipt.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )
        return parsed

    def fetch(self, url, data=None, **kwargs):
        """Adapter for the existing exchange-directory parser; no curl required."""
        query = parse_qs(urlsplit(url).query)
        page = int((data or {}).get("p_currentpage", query.get("pageIndex", [1])[0]))
        if self.progress and (page == 1 or page % 10 == 0):
            self.progress(f"股票目录：读取第 {page} 页…", flush=True)
        raw, receipt = self.request(f"directory-{uuid.uuid4().hex[:8]}", url, form=data)
        return raw.decode("utf-8-sig"), receipt
