from fastapi import FastAPI

from backend.api.router import api_router
from backend.core.config import settings

app = FastAPI(title=settings.APP_NAME)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok"}