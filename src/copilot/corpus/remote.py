"""HTTP client for Capstone-iPe/onb-corpus search."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from copilot.config import corpus_api_key, corpus_search_url

log = logging.getLogger("copilot")

# Free Render services return HTML 502 while waking; retry a few times.
_RETRY_STATUSES = {502, 503, 504}
_RETRY_DELAYS = (0, 3, 8, 15)


class RemoteCorpus:
    """Passages implementation that calls onb-corpus over HTTP."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or corpus_search_url()).rstrip("/")
        self.api_key = api_key if api_key is not None else corpus_api_key()
        if not self.base_url:
            raise RuntimeError("Set CORPUS_SEARCH_URL in .env")
        if not self.api_key:
            raise RuntimeError("Set CORPUS_API_KEY in .env")
        self.rows: list[dict] = []
        self._document_ids: set[str] | None = None

    @property
    def document_ids(self) -> set[str]:
        if self._document_ids is None:
            payload = self._request("GET", "/v1/document-ids")
            ids = payload.get("document_ids")
            if not isinstance(ids, list):
                raise RuntimeError("document-ids response was not a list")
            self._document_ids = {str(item) for item in ids}
        return self._document_ids

    def search(self, query: str, k: int = 4) -> list[dict]:
        payload = self._request(
            "POST",
            "/v1/search",
            {"query": query, "k": k},
        )
        hits = payload.get("hits")
        if not isinstance(hits, list):
            raise RuntimeError("search response was not a list of hits")
        log.info("search %s", [row.get("document_id") for row in hits])
        return hits

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
        }
        last_error: Exception | None = None
        for delay in _RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(f"corpus {method} {path} failed HTTP {exc.code}: {detail}")
                if exc.code not in _RETRY_STATUSES:
                    raise last_error from exc
                log.info("corpus %s %s HTTP %s; retrying", method, path, exc.code)
            except urllib.error.URLError as exc:
                last_error = RuntimeError(f"corpus {method} {path} failed: {exc}")
                log.info("corpus %s %s URL error; retrying", method, path)
        assert last_error is not None
        raise last_error
