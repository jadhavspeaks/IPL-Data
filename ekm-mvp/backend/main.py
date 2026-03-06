from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import connect_db, close_db
from routes.search import router as search_router
from routes.api import sync_router, sources_router, documents_router
from routes.explain import router as explain_router
from utils.sync_service import run_sync
from config import get_settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    logger.info("EKM backend started")

    scheduler.add_job(
        run_sync, "interval",
        minutes=settings.sync_interval_minutes,
        id="auto_sync",
    )
    scheduler.start()
    logger.info(f"Auto-sync scheduled every {settings.sync_interval_minutes} minutes")

    yield

    scheduler.shutdown()
    await close_db()
    logger.info("EKM backend stopped")


app = FastAPI(
    title="Enterprise Knowledge Management API",
    description="Unified search across SharePoint, Confluence, and Jira",
    version="1.0.0-mvp",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_router)
app.include_router(sync_router)
app.include_router(sources_router)
app.include_router(documents_router)
app.include_router(explain_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0-mvp"}
