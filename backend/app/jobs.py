"""Gestore dei lavori in background: ogni lavoro ha log, avanzamento e può essere annullato.

Gli eventi (log, avanzamento, cambi di stato) vengono inviati a tutti i client collegati al WebSocket.
I lavori possono scrivere log anche da thread diversi da quello di asyncio.
"""
from __future__ import annotations

import asyncio
import itertools
import time
import traceback
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, Literal

Livello = Literal["debug", "info", "ok", "avviso", "errore"]
Stato = Literal["in_coda", "in_corso", "completato", "errore", "annullato"]


class Bus:
    """Distribuisce gli eventi a tutti gli iscritti e tiene gli ultimi log per chi si collega dopo."""

    def __init__(self, storico: int = 2000):
        self._iscritti: set[asyncio.Queue] = set()
        self.storico: deque[dict] = deque(maxlen=storico)
        self._loop: asyncio.AbstractEventLoop | None = None

    def lega(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def iscrivi(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._iscritti.add(q)
        return q

    def disiscrivi(self, q: asyncio.Queue):
        self._iscritti.discard(q)

    def _consegna(self, evento: dict):
        if evento["tipo"] == "log":
            self.storico.append(evento)
        for q in list(self._iscritti):
            try:
                q.put_nowait(evento)
            except asyncio.QueueFull:
                pass   # client troppo lento: perde qualche evento ma non blocca gli altri

    def pubblica(self, evento: dict):
        evento.setdefault("ts", time.time())
        try:
            corrente = asyncio.get_running_loop()
        except RuntimeError:
            corrente = None
        if self._loop is None or corrente is self._loop:
            self._consegna(evento)
        else:
            self._loop.call_soon_threadsafe(self._consegna, evento)

    def log(self, msg: str, livello: Livello = "info", lavoro: str | None = None):
        self.pubblica({"tipo": "log", "livello": livello, "msg": msg, "lavoro": lavoro})


class Annullato(Exception):
    pass


class Lavoro:
    def __init__(self, gestore: "Gestore", id_: str, tipo: str, titolo: str, progetto: str | None):
        self.gestore = gestore
        self.id = id_
        self.tipo = tipo
        self.titolo = titolo
        self.progetto = progetto
        self.stato: Stato = "in_coda"
        self.progresso = 0.0
        self.testo = ""
        self.errore: str | None = None
        self.codice: str | None = None      # tipo di errore riconoscibile dall'interfaccia (es. ia_non_pronta)
        self.risultato: Any = None
        self.creato = time.time()
        self.iniziato: float | None = None
        self.finito: float | None = None
        self._task: asyncio.Task | None = None
        self._annulla = False
        self.esclusivo = False
        self.anteprima: tuple[bytes, str] | None = None     # ultima immagine (parziale o finita)
        self.n_anteprima = 0
        self._ultima_anteprima = 0.0

    # chiamabili dal codice del lavoro, anche da un thread
    def log(self, msg: str, livello: Livello = "info"):
        self.gestore.bus.log(msg, livello, self.id)

    def avanza(self, valore: float, testo: str | None = None):
        self.progresso = min(max(float(valore), 0.0), 1.0)
        if testo is not None:
            self.testo = testo
        self.gestore.bus.pubblica({"tipo": "avanzamento", "lavoro": self.id,
                                   "progresso": self.progresso, "testo": self.testo})

    def imposta_anteprima(self, dati: bytes, tipo: str = "image/png", finale: bool = False):
        """Anteprima del lavoro: le parziali al massimo 3 volte al secondo, le immagini finite sempre."""
        self.anteprima = (dati, tipo)
        self.n_anteprima += 1
        adesso = time.monotonic()
        if finale or adesso - self._ultima_anteprima >= 0.33:
            self._ultima_anteprima = adesso
            self.gestore.bus.pubblica({"tipo": "anteprima", "lavoro": self.id, "n": self.n_anteprima,
                                       "finale": finale})

    def controlla(self):
        """Da chiamare nei cicli lunghi: interrompe il lavoro se è stato annullato."""
        if self._annulla:
            raise Annullato()

    @property
    def annullato(self) -> bool:
        return self._annulla

    def dict(self) -> dict:
        return {"id": self.id, "tipo": self.tipo, "titolo": self.titolo, "progetto": self.progetto,
                "stato": self.stato, "progresso": self.progresso, "testo": self.testo, "errore": self.errore,
                "codice": self.codice,
                "creato": self.creato, "iniziato": self.iniziato, "finito": self.finito,
                "anteprima": self.n_anteprima if self.anteprima else 0, "annullando": self._annulla}


Funzione = Callable[[Lavoro], Awaitable[Any]]


class Gestore:
    def __init__(self, bus: Bus, conserva: int = 100):
        self.bus = bus
        self.lavori: dict[str, Lavoro] = {}
        self._conserva = conserva
        self._contatore = itertools.count(1)
        self._esclusivi = asyncio.Lock()   # lavori che usano la GPU: uno alla volta

    def _stato(self, l: Lavoro, stato: Stato):
        l.stato = stato
        self.bus.pubblica({"tipo": "lavoro", "lavoro": l.id, "dati": l.dict()})

    def avvia(self, tipo: str, titolo: str, funzione: Funzione, progetto: str | None = None,
              esclusivo: bool = False) -> Lavoro:
        l = Lavoro(self, f"L{next(self._contatore):04d}", tipo, titolo, progetto)
        l.esclusivo = esclusivo
        self.lavori[l.id] = l
        self._pota()
        self._stato(l, "in_coda")

        async def esegui():
            preso = False
            try:
                if esclusivo:
                    if self._esclusivi.locked():
                        l.log("In attesa che finisca il lavoro precedente sulla GPU...")
                    await self._esclusivi.acquire()
                    preso = True
                if l._annulla:
                    raise Annullato()
                l.iniziato = time.time()
                self._stato(l, "in_corso")
                l.log(f"Avvio: {titolo}")
                l.risultato = await funzione(l)
                l.avanza(1.0, "completato")
                l.finito = time.time()
                l.log(f"Completato: {titolo} ({l.finito - l.iniziato:.1f} s)", "ok")
                self._stato(l, "completato")
            except (Annullato, asyncio.CancelledError):
                l.finito = time.time()
                if esclusivo and l.iniziato:
                    l.log(f"Annullato: {titolo}. Generazione fermata e memoria della GPU liberata.", "avviso")
                else:
                    l.log(f"Annullato: {titolo}", "avviso")
                self._stato(l, "annullato")
            except Exception as e:  # noqa: BLE001 - qualunque errore va mostrato all'utente
                l.finito = time.time()
                l.errore = str(e) or e.__class__.__name__
                l.codice = getattr(e, "codice", None)
                l.log(f"Errore in '{titolo}': {l.errore}", "errore")
                dettaglio = "".join(traceback.format_exception(e)).strip()
                l.log(dettaglio, "debug")
                self._stato(l, "errore")
            finally:
                if preso:
                    self._esclusivi.release()

        l._task = asyncio.get_running_loop().create_task(esegui())
        return l

    def annulla(self, id_: str) -> bool:
        l = self.lavori.get(id_)
        if not l or l.stato in ("completato", "errore", "annullato"):
            return False
        if l._annulla:          # già richiesto: un secondo annullamento interromperebbe la pulizia
            return True
        l._annulla = True
        if l.stato == "in_corso":
            l.log(f"Annullamento di «{l.titolo}»: fermo e libero le risorse...", "info")
        self.bus.pubblica({"tipo": "lavoro", "lavoro": l.id, "dati": l.dict()})
        if l._task:
            # interrompe l'attesa corrente; il codice che gira in un thread si ferma al prossimo controlla()
            l._task.cancel()
        return True

    def annulla_tutti(self) -> int:
        return sum(self.annulla(l.id) for l in self.attivi())

    def attivi(self) -> list[Lavoro]:
        return [l for l in self.lavori.values() if l.stato in ("in_coda", "in_corso")]

    def _pota(self):
        finiti = [l for l in self.lavori.values() if l.stato in ("completato", "errore", "annullato")]
        for l in sorted(finiti, key=lambda x: x.creato)[:max(0, len(self.lavori) - self._conserva)]:
            del self.lavori[l.id]
