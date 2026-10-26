"""Progetti e personaggi.

Un progetto è una cartella:
  <progetti>/<id>/progetto.json
  <progetti>/<id>/personaggi/<id_personaggio>/riferimento.png
I progetti eliminati vengono spostati in <progetti>/.cestino, non cancellati.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import threading
import time
import unicodedata
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

Genere = Literal["1girl", "1boy", "1other"]
TRIGGER_RE = re.compile(r"^[a-z][a-z0-9_]{2,23}$")
# parole che il modello conosce già: come trigger si mescolerebbero con ciò che sa
PAROLE_VIETATE = {"girl", "boy", "woman", "man", "police", "officer", "cop", "commissioner", "hero",
                  "solo", "comic", "anime", "style", "person", "character", "lady", "guy"}


class ErroreProgetto(Exception):
    def __init__(self, msg: str, codice: int = 400):
        super().__init__(msg)
        self.codice = codice


def slug(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:40] or "progetto"


def suggerisci_trigger(nome: str, esistenti: set[str] = frozenset(), rng: random.Random | None = None) -> str:
    """Parola inventata dal nome: consonanti del nome + suffisso (es. 'agente' -> 'gnt' + 'qx')."""
    rng = rng or random.Random()
    base = slug(nome).replace("-", "").lstrip("0123456789") or "chr"
    consonanti = re.sub(r"[aeiou0-9]", "", base)[:5] or base[:4] or "chr"
    if len(consonanti) < 3:
        consonanti = (consonanti + base)[:3].ljust(3, "x")
    for _ in range(100):
        t = consonanti + rng.choice("qxzkjvw") + rng.choice("qxzkjvwy0123456789")
        if TRIGGER_RE.match(t) and t not in esistenti:
            return t
    return consonanti + str(rng.randrange(1000, 9999))


class Personaggio(BaseModel):
    id: str
    nome: str = Field(min_length=1, max_length=60)
    trigger: str
    genere: Genere = "1girl"
    descrizione: str = Field(default="", max_length=1500)    # tratti fissi, in inglese a tag
    storia: str = Field(default="", max_length=20000)        # descrizione libera e lunga, in qualsiasi lingua
    adulto: bool | None = None              # ricavato dall'IA dalla descrizione (None = non analizzato)
    riferimento: str | None = None          # nome del file dentro la cartella del personaggio
    # se il riferimento è una proposta generata da Comic Studio: come è stata fatta (proposte.Ricetta)
    origine: dict | None = None
    creato: float = Field(default_factory=time.time)

    @field_validator("trigger")
    @classmethod
    def _trigger(cls, v: str) -> str:
        v = v.strip().lower()
        if not TRIGGER_RE.match(v):
            raise ValueError("la trigger word deve avere 3-24 caratteri: lettere minuscole, cifre o _, "
                             "e iniziare con una lettera")
        if v in PAROLE_VIETATE:
            raise ValueError(f"'{v}' è una parola che il modello conosce già: usane una inventata")
        return v


class Progetto(BaseModel):
    id: str
    nome: str = Field(min_length=1, max_length=80)
    descrizione: str = ""
    creato: float = Field(default_factory=time.time)
    modificato: float = Field(default_factory=time.time)
    personaggi: list[Personaggio] = Field(default_factory=list)


class NuovoPersonaggio(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    trigger: str | None = None
    genere: Genere = "1girl"
    descrizione: str = Field(default="", max_length=1500)
    storia: str = Field(default="", max_length=20000)


class ModificaPersonaggio(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=60)
    trigger: str | None = None
    genere: Genere | None = None
    descrizione: str | None = Field(default=None, max_length=1500)
    storia: str | None = Field(default=None, max_length=20000)
    adulto: bool | None = None


class Archivio:
    def __init__(self, radice: Path):
        self.radice = Path(radice)
        self._lock = threading.RLock()

    # ------------------------------------------------------------ percorsi

    def cartella(self, id_: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]{1,48}", id_):
            raise ErroreProgetto("Identificativo di progetto non valido", 404)
        return self.radice / id_

    def cartella_personaggio(self, id_: str, pid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9_-]{1,48}", pid):
            raise ErroreProgetto("Identificativo di personaggio non valido", 404)
        return self.cartella(id_) / "personaggi" / pid

    # ------------------------------------------------------------ progetti

    def elenco(self) -> list[Progetto]:
        out = []
        if not self.radice.is_dir():
            return out
        for d in self.radice.iterdir():
            f = d / "progetto.json"
            if d.name.startswith(".") or not f.is_file():
                continue
            try:
                out.append(Progetto.model_validate_json(f.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return sorted(out, key=lambda p: -p.modificato)

    def leggi(self, id_: str) -> Progetto:
        f = self.cartella(id_) / "progetto.json"
        if not f.is_file():
            raise ErroreProgetto(f"Progetto '{id_}' non trovato", 404)
        return Progetto.model_validate_json(f.read_text(encoding="utf-8"))

    def salva(self, p: Progetto) -> Progetto:
        with self._lock:
            p.modificato = time.time()
            d = self.cartella(p.id)
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "progetto.json.tmp"
            tmp.write_text(json.dumps(p.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(d / "progetto.json")
            return p

    def crea(self, nome: str, descrizione: str = "") -> Progetto:
        with self._lock:
            base = slug(nome)
            id_, n = base, 2
            while (self.radice / id_).exists():
                id_, n = f"{base}-{n}", n + 1
            return self.salva(Progetto(id=id_, nome=nome.strip(), descrizione=descrizione))

    def modifica(self, id_: str, nome: str | None = None, descrizione: str | None = None) -> Progetto:
        with self._lock:
            p = self.leggi(id_)
            if nome is not None:
                p.nome = nome.strip()
            if descrizione is not None:
                p.descrizione = descrizione
            return self.salva(p)

    def elimina(self, id_: str) -> None:
        with self._lock:
            d = self.cartella(id_)
            if not d.is_dir():
                raise ErroreProgetto(f"Progetto '{id_}' non trovato", 404)
            cestino = self.radice / ".cestino"
            cestino.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(cestino / f"{id_}-{int(time.time())}"))

    # ------------------------------------------------------------ personaggi

    def _trova(self, p: Progetto, pid: str) -> Personaggio:
        for c in p.personaggi:
            if c.id == pid:
                return c
        raise ErroreProgetto(f"Personaggio '{pid}' non trovato", 404)

    def _controlla_trigger(self, p: Progetto, trigger: str, escluso: str | None = None):
        for c in p.personaggi:
            if c.id != escluso and c.trigger == trigger:
                raise ErroreProgetto(f"La trigger word '{trigger}' è già usata da {c.nome}")

    def aggiungi_personaggio(self, id_: str, dati: NuovoPersonaggio) -> Personaggio:
        with self._lock:
            p = self.leggi(id_)
            esistenti = {c.trigger for c in p.personaggi}
            trigger = dati.trigger or suggerisci_trigger(dati.nome, esistenti)
            base = slug(dati.nome).replace("-", "_") or "personaggio"
            pid, n = base, 2
            while any(c.id == pid for c in p.personaggi):
                pid, n = f"{base}_{n}", n + 1
            try:
                c = Personaggio(id=pid, nome=dati.nome.strip(), trigger=trigger, genere=dati.genere,
                                descrizione=dati.descrizione.strip(), storia=dati.storia.strip())
            except ValueError as e:
                raise ErroreProgetto(_primo_errore(e)) from None
            self._controlla_trigger(p, c.trigger)
            p.personaggi.append(c)
            self.salva(p)
            self.cartella_personaggio(id_, pid).mkdir(parents=True, exist_ok=True)
            return c

    def modifica_personaggio(self, id_: str, pid: str, dati: ModificaPersonaggio) -> Personaggio:
        with self._lock:
            p = self.leggi(id_)
            c = self._trova(p, pid)
            nuovi = c.model_dump()
            nuovi.update({k: v for k, v in dati.model_dump().items() if v is not None})
            try:
                aggiornato = Personaggio(**nuovi)
            except ValueError as e:
                raise ErroreProgetto(_primo_errore(e)) from None
            self._controlla_trigger(p, aggiornato.trigger, escluso=pid)
            p.personaggi[p.personaggi.index(c)] = aggiornato
            self.salva(p)
            return aggiornato

    def elimina_personaggio(self, id_: str, pid: str) -> None:
        with self._lock:
            p = self.leggi(id_)
            c = self._trova(p, pid)
            p.personaggi.remove(c)
            self.salva(p)
            d = self.cartella_personaggio(id_, pid)
            if d.exists():
                cestino = self.radice / ".cestino"
                cestino.mkdir(parents=True, exist_ok=True)
                shutil.move(str(d), str(cestino / f"{id_}-{pid}-{int(time.time())}"))

    def salva_riferimento(self, id_: str, pid: str, dati: bytes, origine: dict | None = None) -> Personaggio:
        """Salva l'immagine di riferimento convertita in PNG (accetta png, jpg, webp); `origine` è la ricetta
        della proposta da cui viene (None per un'immagine caricata dall'utente)."""
        if len(dati) > 40 * 1024 * 1024:
            raise ErroreProgetto("Immagine troppo grande (massimo 40 MB)")
        try:
            img = Image.open(BytesIO(dati))
            img.load()
        except (UnidentifiedImageError, OSError):
            raise ErroreProgetto("Il file non è un'immagine valida") from None
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        with self._lock:
            p = self.leggi(id_)
            c = self._trova(p, pid)
            d = self.cartella_personaggio(id_, pid)
            d.mkdir(parents=True, exist_ok=True)
            img.save(d / "riferimento.png")
            c.riferimento = "riferimento.png"
            c.origine = origine
            self.salva(p)
            return c

    def file_riferimento(self, id_: str, pid: str) -> Path:
        c = self._trova(self.leggi(id_), pid)
        if not c.riferimento:
            raise ErroreProgetto("Questo personaggio non ha ancora un'immagine di riferimento", 404)
        f = self.cartella_personaggio(id_, pid) / c.riferimento
        if not f.is_file():
            raise ErroreProgetto("File di riferimento mancante", 404)
        return f


def _primo_errore(e: ValueError) -> str:
    errori = getattr(e, "errors", None)
    if callable(errori):
        lista = errori()
        if lista:
            msg = lista[0].get("msg", str(e))
            return msg.removeprefix("Value error, ")
    return str(e)
