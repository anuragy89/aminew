from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_DB_URI, MONGO_DB_NAME

from ..logging import LOGGER

LOGGER(__name__).info("Connecting to your Mongo Database...")
try:
    _mongo_async_ = AsyncIOMotorClient(MONGO_DB_URI)
    mongodb = _mongo_async_[MONGO_DB_NAME]
    LOGGER(__name__).info("Connected to your Mongo Database.")
except:
    LOGGER(__name__).error("Failed to connect to your Mongo Database.")
    exit()


async def ensure_indexes():
    try:
        await mongodb.assistant_lru.create_index(
            [("assistant", 1), ("last_used", 1)], background=True
        )
    except Exception:
        pass
