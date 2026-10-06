"""JSON serialised once, served with an ETag (304 when the client has it)."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response


def _matches(header: str, etag: str) -> bool:
    """If-None-Match lists ETags; weak comparison (W/ ignored) as RFC 9110."""
    bare = etag.removeprefix("W/")
    tags = {t.strip().removeprefix("W/") for t in header.split(",") if t.strip()}
    return "*" in tags or bare in tags


@dataclass(frozen=True, slots=True)
class CachedJson:
    body: bytes
    etag: str  # weak: compressed and plain bodies are the same resource

    @classmethod
    def of(cls, data: Any) -> "CachedJson":
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        return cls(body=body, etag=f'W/"{hashlib.sha256(body).hexdigest()[:32]}"')

    def response(self, request: Request, max_age_s: int) -> Response:
        headers = {"ETag": self.etag, "Cache-Control": f"public, max-age={max_age_s}"}
        if _matches(request.headers.get("if-none-match", ""), self.etag):
            return Response(status_code=304, headers=headers)
        return Response(self.body, media_type="application/json", headers=headers)
