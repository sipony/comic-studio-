"""Impostazioni dell'applicazione, salvate in un file JSON nella cartella dati dell'utente."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from pydantic import BaseModel, Field


def cartella_dati() -> Path:
    """Cartella dove il programma tiene impostazioni e progetti (sovrascrivibile con COMIC_STUDIO_HOME)."""
    env = os.environ.get("COMIC_STUDIO_HOME")
    return Path(env).expanduser() if env else Path.home() / "ComicStudio"


class Impostazioni(BaseModel):
    comfy_url: str | None = None
    comfy_dir: str | None = None
    cartella_progetti: str = Field(default_factory=lambda: str(cartella_dati() / "progetti"))
    ultimo_progetto: str | None = None


class Archivio:
    def __init__(self, file: Path | None = None):
        self.file = file or cartella_dati() / "impostazioni.json"
        self._lock = threading.Lock()
        self._valori = self._leggi()

    def _leggi(self) -> Impostazioni:
        try:
            return Impostazioni.model_validate_json(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Impostazioni()

    @property
    def valori(self) -> Impostazioni:
        return self._valori

    def aggiorna(self, **campi) -> Impostazioni:
        with self._lock:
            self._valori = self._valori.model_copy(update=campi)
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._valori.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.file)
            return self._valori
