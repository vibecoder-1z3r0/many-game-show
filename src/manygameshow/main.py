"""Many Game Show — FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Many Game Show")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


_static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
