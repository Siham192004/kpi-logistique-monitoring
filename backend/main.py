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
# CORS — ajouter localhost:3000
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev
        "http://localhost:3000",  # Docker
        "https://kpi-logistique.onrender.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers — ajouter prefix="/api" partout
app.include_router(shipment_router.router,   prefix="/api/shipments",  tags=["Shipments"])
app.include_router(kpi_router.router,        prefix="/api/kpis",       tags=["KPIs"])
app.include_router(prediction_router.router, prefix="/api/predict",    tags=["Prédiction"])
app.include_router(messaging_router.router,  prefix="/api/messages",   tags=["Messagerie"])
app.include_router(admin_router.router,      prefix="/api/admin",      tags=["Administration"])
app.include_router(export_router.router,     prefix="/api/export",     tags=["Export"])


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "KPI Monitoring API is running"}