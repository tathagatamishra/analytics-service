"""
aianalytics-service — FastAPI
Port: 8084

Reads ai_usage_snapshots (written by aitools-service) and serves
aggregations, forecasts, anomaly detection, and burn-rate analytics.

Auth: same Cognito JWT pool as auth-service / org-service / aitools-service.
      org_id is extracted from `custom:org_id` JWT claim.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import analytics, health

settings = get_settings()

app = FastAPI(
    title="aianalytics-service",
    description="AI usage analytics, forecasting, and anomaly detection",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET"],       # analytics service is read-only
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(analytics.router)


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": str(exc)},
    )
