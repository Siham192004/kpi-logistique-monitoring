from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers import export_router

from backend.routers import (
    shipment_router,
    kpi_router,
    prediction_router,
    messaging_router,
    admin_router,
)

app = FastAPI(
    title="KPI Monitoring Platform",
    description="Plateforme intelligente de suivi des KPIs logistiques",
    version="1.0.0",
)

# ── CORS : autorise React (Vite) à communiquer avec le backend ───────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(shipment_router.router,   prefix="/shipments",  tags=["Shipments"])
app.include_router(kpi_router.router,        prefix="/kpis",       tags=["KPIs"])
app.include_router(prediction_router.router, prefix="/predict",    tags=["Prédiction"])
app.include_router(messaging_router.router,  prefix="/messages",   tags=["Messagerie"])
app.include_router(admin_router.router,      prefix="/admin",      tags=["Administration"])
app.include_router(export_router.router, prefix="/export", tags=["Export"])


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "KPI Monitoring API is running"}