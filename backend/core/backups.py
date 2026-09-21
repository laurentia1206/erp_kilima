"""Sauvegarde SQLite cohérente, y compris lorsque le journal WAL est actif."""
from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
import tempfile


def sauvegarder_sqlite(source: Path, dossier: Path | None = None) -> Path:
    source = source.resolve(strict=True)
    dossier = dossier or source.parent / "backups"
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / f"{source.stem}_{date.today():%Y%m%d}.db"
    if cible.exists():
        return cible
    # Publication seulement après copie complète et contrôle d'intégrité.
    with tempfile.NamedTemporaryFile(dir=dossier, suffix=".tmp", delete=False) as f:
        temporaire = Path(f.name)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(temporaire)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("La sauvegarde SQLite a échoué au contrôle d'intégrité.")
        temporaire.replace(cible)
    finally:
        temporaire.unlink(missing_ok=True)
    return cible
