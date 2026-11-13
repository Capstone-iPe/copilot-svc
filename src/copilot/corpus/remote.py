"""HTTP client for Capstone-iPe/onb-corpus search."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from copilot.config import corpus_api_key, corpus_search_url

log = logging.getLogger("copilot")


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
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"corpus {method} {path} failed HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"corpus {method} {path} failed: {exc}") from exc
