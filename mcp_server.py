import os
import asyncio
from typing import AsyncGenerator

import httpx
import logfire
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logfire.configure(send_to_logfire='if-token-present')

app = FastAPI(title="Brave Search MCP Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
if not BRAVE_API_KEY:
    raise RuntimeError("BRAVE_API_KEY environment variable is not set.")

PORT = int(os.getenv("PORT", "8000"))


class SearchRequest(BaseModel):
    query: str
    count: int = 5
    language: str = "en"


async def brave_search(query: str, count: int = 5, language: str = "en") -> dict:
    headers = {
        "X-Subscription-Token": BRAVE_API_KEY,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    params = {
        "q": query,
        "count": count,
        "search_lang": language,
        "text_decorations": "true",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        return response.json()


async def event_stream(request: Request, query: str, count: int = 5) -> AsyncGenerator[str, None]:
    try:
        yield "event: status\ndata: Search started\n\n"

        data = await brave_search(query, count)

        web_results = data.get("web", {}).get("results", [])

        if not web_results:
            yield "event: status\ndata: No results found\n\n"
            yield "event: end\ndata: []\n\n"
            return

        yield "event: status\ndata: Streaming results\n\n"

        import json

        for i, result in enumerate(web_results[:count]):
            chunk = {
                "index": i + 1,
                "title": result.get("title", ""),
                "description": result.get("description", ""),
                "url": result.get("url", ""),
            }
            yield f"data: {json.dumps(chunk)}\n\n"

            if await request.is_disconnected():
                break

            await asyncio.sleep(0.1)

        yield "event: end\ndata: end_of_stream\n\n"

    except httpx.HTTPStatusError as e:
        yield f"event: error\ndata: HTTP error {e.response.status_code} - {e.response.text}\n\n"
    except Exception as e:
        yield f"event: error\ndata: Exception: {str(e)}\n\n"


@app.post("/search")
async def search(request: Request, body: SearchRequest):
    """
    SSE endpoint for Brave Search API.

    Accepts JSON body with `query`, optional `count`, and `language`.

    Streams search results incrementally using SSE.
    """
    return StreamingResponse(
        event_stream(request, body.query, body.count or 5),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mcp_server:app", host="0.0.0.0", port=PORT, log_level="info")