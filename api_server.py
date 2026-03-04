import asyncio
import os
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from main import run_once


app = FastAPI(title="ETH Perp Trading Bot API")

_run_lock = asyncio.Lock()
_last_run_ts = 0.0
MIN_INTERVAL_SECONDS = int(os.getenv("MIN_INTERVAL_SECONDS", "60"))


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "eth-perp-trading-bot"}


@app.post("/run")
async def trigger_run(x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    global _last_run_ts

    expected_api_key = os.getenv("API_KEY", "")
    if expected_api_key and x_api_key != expected_api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = time.time()
    if now - _last_run_ts < MIN_INTERVAL_SECONDS:
        return {
            "ok": True,
            "skipped": True,
            "reason": f"too_frequent(<{MIN_INTERVAL_SECONDS}s)",
        }

    if _run_lock.locked():
        return {"ok": True, "skipped": True, "reason": "already_running"}

    async with _run_lock:
        _last_run_ts = time.time()
        result = await asyncio.to_thread(run_once)
        return {
            "ok": bool(result.get("ok")),
            "result": result,
        }
