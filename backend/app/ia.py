"""Servizio dell'IA locale dentro Comic Studio: stato, installazione, avvio, modelli e domande."""
from __future__ import annotations

import asyncio
import time

import httpx
from typing import TYPE_CHECKING

from .comfy import avvio as avvio_proc
from .jobs import Lavoro
from .llm import (ClientIA, ErroreIA, StatoIA, URL_OLLAMA, cartella_ollama, ollama_di_sistema, ollama_portatile,
                  scarica_ollama)

if TYPE_CHECKING:
    from .state import App


class ServizioIA:
    def __init__(self, app: "App"):
        self.app = app
        self.pid: int | None = None          # Ollama avviato da Comic Studio
        self.stato = StatoIA(tipo="nessuna")
        self._lock = asyncio.Lock()

    @property
    def imp(self):
        return self.app.impostazioni.valori

    def client(self, timeout: float = 600) -> ClientIA:
        i = self.imp
        return ClientIA(i.ia_tipo, i.ia_url or URL_OLLAMA, i.ia_modello, i.ia_chiave, timeout)

    async def aggiorna(self) -> StatoIA:
        i = self.imp
        s = StatoIA(tipo=i.ia_tipo, url=i.ia_url, modello=i.ia_modello)
        if i.ia_tipo == "nessuna":
            s.errore = "IA disattivata: le descrizioni vengono passate così come sono."
        else:
            if i.ia_tipo == "ollama":
                exe = ollama_portatile() or ollama_di_sistema()
                s.eseguibile = str(exe) if exe else None
                s.portatile = bool(exe and ollama_portatile() == exe)
            async with self.client(timeout=10) as c:
                s.versione = await c.versione()
                s.raggiungibile = s.versione is not None
                if s.raggiungibile:
                    try:
                        s.modelli = await c.modelli()
                    except Exception as e:  # noqa: BLE001
                        s.errore = f"Elenco dei modelli non disponibile: {e}"
            base = i.ia_modello.split(":")[0]
            s.modello_presente = i.ia_modello in s.modelli or (":" not in i.ia_modello and any(
                m.split(":")[0] == base for m in s.modelli)) or (i.ia_tipo == "openai" and s.raggiungibile)
            if not s.raggiungibile:
                s.errore = ("Ollama non è installato: installalo da qui con un clic." if i.ia_tipo == "ollama"
                            and not s.eseguibile else f"L'IA non risponde su {i.ia_url}.")
            elif not s.modello_presente:
                s.errore = f"Il modello {i.ia_modello} non è ancora scaricato."
        self.stato = s
        self.app.bus.pubblica({"tipo": "ia", "dati": s.dict()})
        return s

    # ------------------------------------------------------------ Ollama

    async def avvia_ollama(self, l: Lavoro | None = None) -> bool:
        """Avvia `ollama serve` se c'è un eseguibile e non è già in esecuzione."""
        async with self.client(timeout=5) as c:
            if await c.versione():
                return True
        exe = ollama_portatile() or ollama_di_sistema()
        if not exe:
            return False
        ambiente = {"OLLAMA_HOST": (self.imp.ia_url or URL_OLLAMA).split("://", 1)[-1]}
        if ollama_portatile() == exe:
            ambiente["OLLAMA_MODELS"] = str(cartella_ollama() / "modelli")
        cmd = avvio_proc.Comando([str(exe), "serve"], exe.parent, "Ollama", 11434)
        self.pid = await asyncio.to_thread(avvio_proc.avvia, cmd, cartella_ollama() / "ollama.log", ambiente)
        if l:
            l.log(f"Avvio Ollama: {exe}")
        inizio = time.monotonic()
        while time.monotonic() - inizio < 60:
            async with self.client(timeout=3) as c:
                if await c.versione():
                    return True
            if not avvio_proc.vivo(self.pid):
                break
            await asyncio.sleep(0.5)
        raise ErroreIA("Ollama non è partito: guarda il registro in " + str(cartella_ollama() / "ollama.log"))

    async def ferma_ollama(self):
        if self.pid and avvio_proc.vivo(self.pid):
            await asyncio.to_thread(avvio_proc.ferma, self.pid)
        self.pid = None

    def installa(self) -> Lavoro:
        """Scarica Ollama portatile, lo avvia e scarica il modello scelto (dopo conferma nell'interfaccia)."""
        async def lavoro(l: Lavoro):
            if not (ollama_portatile() or ollama_di_sistema()):
                l.log("Scarico Ollama (circa 1-2 GB, una volta sola) in " + str(cartella_ollama()))
                exe = await asyncio.to_thread(scarica_ollama, lambda v, t: l.avanza(v * 0.4, t),
                                              lambda: l.annullato)
                l.log(f"Ollama installato: {exe}", "ok")
            await self.avvia_ollama(l)
            await self._scarica_modello(l, self.imp.ia_modello, 0.4)
            return (await self.aggiorna()).dict()
        return self.app.gestore.avvia("ia_installa", "Installazione dell'IA locale", lavoro)

    def scarica_modello(self, nome: str) -> Lavoro:
        async def lavoro(l: Lavoro):
            if self.imp.ia_tipo == "ollama":
                await self.avvia_ollama(l)
            await self._scarica_modello(l, nome, 0.0)
            return (await self.aggiorna()).dict()
        return self.app.gestore.avvia("ia_modello", f"Download del modello {nome}", lavoro)

    async def _scarica_modello(self, l: Lavoro, nome: str, da: float):
        l.log(f"Scarico il modello {nome} (qualche GB, una volta sola)")
        ultimo = [0.0]

        def avanza(v: float, t: str):
            if v >= 0:
                ultimo[0] = v
            l.avanza(da + (1 - da) * ultimo[0] * 0.98, t)
        async with self.client(timeout=60) as c:
            await c.scarica_modello(nome, avanza, lambda: l.annullato)
        l.log(f"Modello {nome} pronto", "ok")

    # ------------------------------------------------------------ domande

    async def chiedi(self, sistema: str, utente: str, schema: dict, l: Lavoro | None = None,
                     contesto: int = 12288) -> dict:
        """Una risposta JSON dall'IA; avvia Ollama se serve e libera la GPU di ComfyUI se richiesto."""
        i = self.imp
        if i.ia_tipo == "nessuna":
            raise ErroreIA("L'IA locale è disattivata: attivala in Sistema → IA locale.", non_pronta=True)
        async with self._lock:
            if i.ia_tipo == "ollama" and not await self.avvia_ollama(l):
                raise ErroreIA("Ollama non è installato: scegli un modello e installalo con un clic.", non_pronta=True)
            if i.ia_libera_gpu and self.app.comfy.connesso:
                try:
                    async with self.app.client() as c:
                        await c.libera_memoria()
                except Exception:  # noqa: BLE001 - non è indispensabile
                    pass
            inizio = time.monotonic()
            async with self.client() as c:
                try:
                    r = await c.chat_json(sistema, utente, schema, contesto)
                except httpx.ConnectError:
                    raise ErroreIA(f"L'IA non risponde su {c.url}.", non_pronta=True) from None
                except asyncio.CancelledError:
                    # annullato: il modello esce subito dalla memoria della GPU
                    await asyncio.shield(c.scarica_dalla_memoria())
                    raise
            if l:
                l.log(f"IA ({i.ia_modello}): risposta in {time.monotonic() - inizio:.0f} s", "debug")
            return r


__all__ = ["ServizioIA"]
