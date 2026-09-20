"""Point d'entrée FastAPI — ERP KILIMA HOLDINGS (V1)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import (
    analytique, approbations, auth, avances, caisse, commercial, compta, config,
    intersociete, lecture, ordres_depense, pieces_jointes, requisitions, taux,
    transferts, transport, ventes,
)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0-v1",
    description="Système intégré de gestion — V1 : décaissement & avances à justifier.",
)


@app.on_event("startup")
def _sauvegarde_quotidienne():
    """Filet de sécurité : copie quotidienne de la base SQLite au démarrage
    (backups/kilima_dev_AAAAMMJJ.db, 14 dernières conservées). Les données de
    test de Laurent ne doivent JAMAIS être perdues."""
    try:
        from datetime import date as _d
        import shutil
        url = settings.database_url
        if "sqlite" not in url:
            return
        db_path = Path(url.split("///")[-1])
        if not db_path.is_absolute():
            db_path = Path(__file__).resolve().parent.parent / db_path
        if not db_path.exists():
            return
        dossier = db_path.parent / "backups"
        dossier.mkdir(exist_ok=True)
        cible = dossier / f"{db_path.stem}_{_d.today().strftime('%Y%m%d')}.db"
        if not cible.exists():
            shutil.copy2(db_path, cible)
        anciennes = sorted(dossier.glob(f"{db_path.stem}_*.db"))
        for vieille in anciennes[:-14]:
            vieille.unlink(missing_ok=True)
    except Exception:
        pass   # la sauvegarde ne doit jamais empêcher le démarrage

# CORS — à restreindre aux domaines du frontend en production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def _no_cache_frontend(request, call_next):
    """Empêche la mise en cache du frontend (sinon l'utilisateur voit une ancienne version)."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.include_router(auth.router)
app.include_router(taux.router)
app.include_router(requisitions.router)
app.include_router(ordres_depense.router)
app.include_router(avances.router)
app.include_router(approbations.router)
app.include_router(lecture.router)
app.include_router(pieces_jointes.router)
app.include_router(config.router)
app.include_router(compta.router)
app.include_router(caisse.router)
app.include_router(transferts.router)
app.include_router(analytique.router)
app.include_router(commercial.router)
app.include_router(ventes.router)
app.include_router(intersociete.router)
app.include_router(transport.router)


@app.get("/api/health", tags=["système"])
def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}


# Frontend : assets sous /static, page d'accueil à la racine
_STATIC = Path(__file__).resolve().parent.parent / "static"
if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(_STATIC / "index.html"))
