"""Many Game Show — FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from manygameshow.database import create_db_and_tables
from manygameshow.routers import squad_squabble


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    yield


app = FastAPI(title="Many Game Show", lifespan=lifespan)

app.include_router(squad_squabble.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


_static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
