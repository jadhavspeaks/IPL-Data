from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel, TEXT, ASCENDING, DESCENDING
from config import get_settings
import logging

logger = logging.getLogger(__name__)
settings = get_settings()

client: AsyncIOMotorClient = None
db = None


async def connect_db():
    global client, db
    client = AsyncIOMotorClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=30000,   # 30s to find server
        connectTimeoutMS=30000,           # 30s to connect
        socketTimeoutMS=120000,           # 2min for slow operations like index creation
    )
    db = client[settings.mongo_db]

    # ── Ping using YOUR database, not admin ───────────────────────────────────
    # admin ping fails if user has no admin access (common in org setups)
    await db.command("ping")
    logger.info(f"Connected to MongoDB: {settings.mongo_uri}")

    # Create indexes in background — don't block startup if slow network
    try:
        await create_indexes()
    except Exception as e:
        logger.warning(f"Index creation skipped (will retry next startup): {e}")


async def close_db():
    global client
    if client:
        client.close()
        logger.info("MongoDB connection closed")


async def create_indexes():
    """Create all required indexes on startup."""
    docs = db.documents

    await docs.create_indexes([
        IndexModel(
            [("title", TEXT), ("content", TEXT), ("tags", TEXT)],
            name="text_search",
            weights={"title": 10, "tags": 5, "content": 1}
        ),
        IndexModel([("source_type", ASCENDING)], name="source_type_idx"),
        IndexModel([("source", ASCENDING)], name="source_idx"),
        IndexModel([("ingested_at", DESCENDING)], name="ingested_at_idx"),
        IndexModel([("updated_at", DESCENDING)], name="updated_at_idx"),
        IndexModel(
            [("source_type", ASCENDING), ("external_id", ASCENDING)],
            unique=True, name="unique_doc_idx"
        ),
        IndexModel(
            [("entities.jira_tickets", ASCENDING)],
            name="entity_tickets_idx", sparse=True
        ),
        IndexModel(
            [("entities.change_numbers", ASCENDING)],
            name="entity_change_idx", sparse=True
        ),
    ])

    await db.sync_logs.create_indexes([
        IndexModel([("source_type", ASCENDING)], name="sync_log_source_idx"),
        IndexModel([("started_at", DESCENDING)], name="sync_log_time_idx"),
    ])

    await db.sync_state.create_indexes([
        IndexModel(
            [("source_type", ASCENDING)],
            unique=True, name="sync_state_source_idx"
        ),
    ])

    logger.info("MongoDB indexes created")


async def get_last_sync(source_type: str):
    state = await db.sync_state.find_one({"source_type": source_type})
    return state.get("last_sync_at") if state else None


async def set_last_sync(source_type: str, timestamp):
    await db.sync_state.update_one(
        {"source_type": source_type},
        {"$set": {"source_type": source_type, "last_sync_at": timestamp}},
        upsert=True,
    )


def get_db():
    return db
