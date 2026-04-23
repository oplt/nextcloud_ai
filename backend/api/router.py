from fastapi import APIRouter

from backend.api.v1.admin_routes import router as admin_router
from backend.api.v1.auth_routes import router as auth_router
from backend.api.v1.chat_routes import router as chat_router
from backend.api.v1.connector_routes import router as connector_router
from backend.api.v1.document_routes import router as document_router
from backend.api.v1.health_routes import router as health_router
from backend.api.v1.intelligence_routes import router as intelligence_router
from backend.api.v1.job_routes import router as job_router
from backend.api.v1.nextcloud_auth import router as nextcloud_auth_router
from backend.api.v1.user_routes import router as user_router
from backend.connectors.nextcloud.webhooks import router as nextcloud_webhook_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(nextcloud_auth_router)
api_router.include_router(admin_router)
api_router.include_router(user_router)
api_router.include_router(connector_router)
api_router.include_router(document_router)
api_router.include_router(intelligence_router)
api_router.include_router(job_router)
api_router.include_router(chat_router)
api_router.include_router(nextcloud_webhook_router)
