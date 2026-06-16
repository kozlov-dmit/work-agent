"""HTTP request tool for calling external APIs."""

from __future__ import annotations

import httpx

from ..base import ToolContext, ToolOutput

_MAX_BODY = 30_000


class HttpRequestTool:
    name = "http_request"
    description = "Make an HTTP request to an external URL and return status, headers, and body."
    input_schema = {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
            "url": {"type": "string"},
            "headers": {"type": "object", "description": "Optional request headers."},
            "body": {"type": "string", "description": "Optional request body."},
        },
        "required": ["method", "url"],
    }
    parallel_safe = False

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        try:
            resp = httpx.request(
                args["method"],
                args["url"],
                headers=args.get("headers"),
                content=args.get("body"),
                timeout=30,
                follow_redirects=True,
            )
        except httpx.HTTPError as e:
            return ToolOutput(f"Request failed: {e}", is_error=True)

        text = resp.text
        if len(text) > _MAX_BODY:
            text = text[:_MAX_BODY] + "\n... [truncated]"
        return ToolOutput(f"HTTP {resp.status_code}\n\n{text}", is_error=resp.status_code >= 400)
