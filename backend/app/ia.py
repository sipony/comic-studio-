"""Servizio dell'IA locale dentro Comic Studio: stato, installazione, processo di Ollama, modelli e domande.

Ollama (se è il motore scelto):
- all'apertura di Comic Studio si avvia da solo, se non è già acceso (impostazione `ia_avvio_automatico`)
- una sorveglianza lo riavvia se si chiude o non risponde più (non mentre sta rispondendo a una domanda); dopo
  tre tentativi falliti di fila si ferma e lo dice nella console
- Avvia / Riavvia / Ferma dall'interfaccia; un Ollama aperto in un altro modo (servizio di sistema, app di Ollama)
  si usa così com'è e si può fermare solo se è dello stesso utente
- quello avviato da Comic Studio scrive in <cartella dati>/strumenti/ollama/ollama.log, che va nella console;
  il PID è salvato, così dopo una chiusura brusca alla riapertura lo si riconosce
"""
from __future__ import annotations

import asyncio
import collections
import platform
import time

import httpx
from typing import TYPE_CHECKING

from . import processo_ollama as proc
from .comfy import avvio as avvio_proc
from .jobs import Annullato, Lavoro
from .llm import (ClientIA, ErroreIA, StatoIA, URL_OLLAMA, cartella_ollama, ollama_di_sistema, ollama_portatile,
                  scarica_ollama)

if TYPE_CHECKING:
    from .state import App

TIPI_LAVORO_OLLAMA = ("ia_avvio", "ia_arresto")
ATTESA_AVVIO = 60                    # secondi massimi perché Ollama risponda
TENTATIVI = 3                        # riavvii automatici falliti di fila prima di arrendersi
NON_INSTALLATO = "Ollama non è installato: scegli un modello e installalo con un clic."
TIMEOUT_CONTROLLO = 5.0              # secondi di attesa della risposta di Ollama nella sorveglianza


def eseguibile():
    return ollama_portatile() or ollama_di_sistema()


class ServizioIA:
    def __init__(self, app: "App"):
        self.app = app
        self.pid: int | None = None          # Ollama avviato da Comic Studio
        self.stato = StatoIA(tipo="nessuna")
        self.in_avvio = False
        self.fermato = False                 # fermato con «Ferma»: la sorveglianza non lo riaccende
        self.righe: collections.deque = collections.deque(maxlen=80)
        self._lock = asyncio.Lock()          # una domanda all'IA alla volta
        self._lock_avvio = asyncio.Lock()    # un avvio alla volta (sorveglianza, domande, pulsanti)
        self._seguiti: set[asyncio.Task] = set()
        self._generazione = 0                # solo chi segue il processo più recente scrive nella console
        self._fermati: set[int] = set()      # PID fermati da Comic Studio (non «si è chiuso da solo»)
        self._non_risponde = 0
        self._fallimenti = 0

    @property
    def imp(self):
        return self.app.impostazioni.valori

    @property
    def file_log(self):
        return cartella_ollama() / "ollama.log"

    @property
    def file_pid(self):
        return cartella_ollama() / "ollama.pid"

    @property
    def porta(self) -> int:
        return avvio_proc.porta_da_url(self.imp.ia_url or URL_OLLAMA, 11434)

    def client(self, timeout: float = 600) -> ClientIA:
        i = self.imp
        return ClientIA(i.ia_tipo, i.ia_url or URL_OLLAMA, i.ia_modello, i.ia_chiave, timeout)

    async def aggiorna(self) -> StatoIA:
        i = self.imp
        if self.pid and not avvio_proc.vivo(self.pid):
            self.pid = None
        s = StatoIA(tipo=i.ia_tipo, url=i.ia_url, modello=i.ia_modello, in_avvio=self.in_avvio,
                    avviato_da_noi=self.pid is not None, pid=self.pid, fermato=self.fermato,
                    avvio_automatico=i.ia_avvio_automatico)
        if i.ia_tipo == "nessuna":
            s.errore = "IA disattivata: le descrizioni vengono passate così come sono."
        else:
            if i.ia_tipo == "ollama":
                exe = eseguibile()
                s.eseguibile = str(exe) if exe else None
                s.portatile = bool(exe and ollama_portatile() == exe)
            async with self.client(timeout=10) as c:
                s.versione = await c.versione()
                s.raggiungibile = s.versione is not None
                if s.raggiungibile:
                    try:
                        if i.ia_tipo == "ollama":
                            dettagli = await c.modelli_dettagli()
                            s.modelli = sorted(m["name"] for m in dettagli)
                            s.dimensioni = {m["name"]: int(m.get("size") or 0) for m in dettagli}
                        else:
                            s.modelli = await c.modelli()
                    except Exception as e:  # noqa: BLE001
                        s.errore = f"Elenco dei modelli non disponibile: {e}"
            base = i.ia_modello.split(":")[0]
            s.modello_presente = i.ia_modello in s.modelli or (":" not in i.ia_modello and any(
                m.split(":")[0] == base for m in s.modelli)) or (i.ia_tipo == "openai" and s.raggiungibile)
            if i.ia_tipo == "ollama" and s.raggiungibile and not s.avviato_da_noi:
                s.esterno = await asyncio.to_thread(self._chi_lo_ha_aperto)
            if not s.raggiungibile:
                s.errore = await self._perche_non_risponde(s)
            elif not s.modello_presente:
                s.errore = f"Il modello {i.ia_modello} non è ancora scaricato."
        self.stato = s
        self.app.bus.pubblica({"tipo": "ia", "dati": s.dict()})
        return s

    async def _perche_non_risponde(self, s: StatoIA) -> str:
        i = self.imp
        if i.ia_tipo == "openai":
            # un indirizzo di LM Studio con un modello di Ollama: di solito si voleva Ollama
            if eseguibile():
                s.suggerisci_ollama = True
            else:
                async with ClientIA("ollama", URL_OLLAMA, i.ia_modello, timeout=2) as c:
                    s.suggerisci_ollama = await c.versione() is not None
            return (f"L'IA non risponde su {i.ia_url}."
                    + (" Ollama però è installato: per usarlo scegli Tipo → Ollama." if s.suggerisci_ollama else ""))
        if not s.eseguibile:
            return "Ollama non è installato: installalo da qui con un clic."
        if self.in_avvio:
            return "Ollama si sta avviando…"
        if self.fermato:
            return "Ollama è fermo: premi Avvia (si avvia da solo anche alla prossima domanda all'IA)."
        if i.ia_avvio_automatico:
            return f"Ollama non risponde su {i.ia_url}: Comic Studio lo sta riavviando."
        return f"Ollama è spento (non risponde su {i.ia_url}): premi Avvia."

    def _chi_lo_ha_aperto(self) -> str:
        try:
            lista = proc.processi(self.porta)
        except Exception:  # noqa: BLE001
            lista = []
        if any(not p.mio for p in lista):
            utente = next(p.utente for p in lista if not p.mio)
            return (f"servizio di sistema (utente «{utente}»)" if platform.system() == "Linux"
                    else f"aperto dall'utente «{utente}»")
        if lista:
            return "aperto fuori da Comic Studio (app di Ollama o terminale)"
        return "aperto fuori da Comic Studio"

    # ------------------------------------------------------------ processo di Ollama

    async def all_avvio(self):
        """All'apertura di Comic Studio: riconosce l'Ollama avviato la volta prima e, se serve, lo avvia."""
        pid = await asyncio.to_thread(avvio_proc.leggi_pid, self.file_pid)
        if pid:
            self.pid = pid
            self._segui_log(None)
        s = await self.aggiorna()
        i = self.imp
        if i.ia_tipo == "ollama" and i.ia_avvio_automatico and not s.raggiungibile and s.eseguibile:
            self.app.bus.log("Ollama è spento: lo avvio", "info")
            l = self.avvia(a_mano=False)
            asyncio.get_running_loop().create_task(self._esito_automatico(l))

    def _lavoro_attivo(self) -> Lavoro | None:
        return next((l for l in self.app.gestore.attivi() if l.tipo in TIPI_LAVORO_OLLAMA), None)

    def avvia(self, a_mano: bool = True) -> Lavoro:
        """Avvia Ollama (se è già acceso non fa niente)."""
        async def lavoro(l: Lavoro):
            self.fermato = False
            if a_mano:
                self._fallimenti = 0
            if not await self.avvia_ollama(l):
                raise ErroreIA(NON_INSTALLATO, non_pronta=True)
            return (await self.aggiorna()).dict()
        return self._lavoro_attivo() or self.app.gestore.avvia("ia_avvio", "Avvio di Ollama", lavoro)

    def riavvia(self, a_mano: bool = True) -> Lavoro:
        """Ferma Ollama (anche se l'ha aperto qualcun altro, se si può) e lo riavvia."""
        async def lavoro(l: Lavoro):
            self.fermato = False
            if a_mano:
                self._fallimenti = 0
            await self._ferma(l)
            if not await self.avvia_ollama(l):
                raise ErroreIA(NON_INSTALLATO, non_pronta=True)
            return (await self.aggiorna()).dict()
        return self._lavoro_attivo() or self.app.gestore.avvia("ia_avvio", "Riavvio di Ollama", lavoro)

    def ferma(self) -> Lavoro:
        async def lavoro(l: Lavoro):
            self.fermato = True
            await self._ferma(l)
            return (await self.aggiorna()).dict()
        return self._lavoro_attivo() or self.app.gestore.avvia("ia_arresto", "Arresto di Ollama", lavoro)

    async def _ferma(self, l: Lavoro):
        l.avanza(0.1, "chiudo Ollama")
        pid, self.pid = self.pid, None
        if pid:
            self._fermati.add(pid)
            await asyncio.to_thread(avvio_proc.ferma, pid)
            self.file_pid.unlink(missing_ok=True)
            l.log(f"Ollama fermato (PID {pid})", "ok")
        else:
            lista = await asyncio.to_thread(proc.processi, self.porta)
            if not lista:
                l.log("Ollama era già spento")
                return
            fermati, negati = await asyncio.to_thread(proc.termina, lista)
            if negati and not fermati:
                raise ErroreIA(proc.come_fermarlo(negati))
            l.log(f"Ollama fermato (PID {', '.join(map(str, fermati))})", "ok")
        # l'app di Ollama o il servizio di sistema possono riaccenderlo da soli
        for _ in range(20):
            async with self.client(timeout=1) as c:
                if not await c.versione():
                    return
            await asyncio.sleep(0.25)
        l.log("Ollama si è riacceso da solo (lo gestisce il sistema o l'app di Ollama)", "info")

    async def avvia_ollama(self, l: Lavoro | None = None) -> bool:
        """Avvia `ollama serve` se c'è un eseguibile e non è già in esecuzione; False se non è installato."""
        async with self._lock_avvio:
            async with self.client(timeout=5) as c:
                if await c.versione():
                    return True
            exe = eseguibile()
            if not exe:
                return False
            self.fermato = False
            self.in_avvio = True
            await self.aggiorna()
            try:
                return await self._avvia_processo(exe, l)
            finally:
                self.in_avvio = False
                await self.aggiorna()

    async def _avvia_processo(self, exe, l: Lavoro | None) -> bool:
        ambiente = {"OLLAMA_HOST": (self.imp.ia_url or URL_OLLAMA).split("://", 1)[-1].rstrip("/")}
        if ollama_portatile() == exe:
            ambiente["OLLAMA_MODELS"] = str(cartella_ollama() / "modelli")
        cmd = avvio_proc.Comando([str(exe), "serve"], exe.parent, "Ollama", self.porta)
        self.righe.clear()
        lettore = avvio_proc.LettoreLog(self.file_log)
        try:
            pid = await asyncio.to_thread(avvio_proc.avvia, cmd, self.file_log, ambiente)
        except avvio_proc.ErroreAvvio as e:
            raise ErroreIA(str(e).replace("ComfyUI", "Ollama")) from None
        self.pid = pid
        await asyncio.to_thread(avvio_proc.salva_pid, self.file_pid, pid)
        self._segui_log(l.id if l else None, lettore)
        (l.log if l else self.app.bus.log)(f"Avvio Ollama: {exe} serve (PID {pid})", "info")
        inizio = time.monotonic()
        try:
            while time.monotonic() - inizio < ATTESA_AVVIO:
                if l:
                    l.controlla()
                async with self.client(timeout=2) as c:
                    if v := await c.versione():
                        (l.log if l else self.app.bus.log)(
                            f"Ollama {v} pronto su {self.imp.ia_url} in {time.monotonic() - inizio:.0f} s", "ok")
                        return True
                if not avvio_proc.vivo(pid):
                    await asyncio.sleep(0.6)          # le ultime righe arrivino nel registro
                    self._fermati.add(pid)            # lo spiega l'errore del lavoro
                    self.pid = None
                    self.file_pid.unlink(missing_ok=True)
                    raise ErroreIA("Ollama si è chiuso appena avviato. "
                                   + proc.spiega_errore(await self._ultime_righe(), self.porta))
                if l:
                    l.avanza(min(0.9, (time.monotonic() - inizio) / 20), "attendo che Ollama risponda")
                await asyncio.sleep(0.5)
        except (Annullato, asyncio.CancelledError):
            await self._chiudi_nostro()
            raise
        await self._chiudi_nostro()
        raise ErroreIA(f"Ollama non risponde dopo {ATTESA_AVVIO} s. "
                       + proc.spiega_errore(await self._ultime_righe(), self.porta))

    async def _ultime_righe(self) -> list[str]:
        if self.righe:
            return list(self.righe)
        lettore = avvio_proc.LettoreLog(self.file_log)
        lettore.posizione = max(0, lettore.posizione - 4000)
        return await asyncio.to_thread(lettore.nuove)

    async def _chiudi_nostro(self):
        pid, self.pid = self.pid, None
        if pid:
            self._fermati.add(pid)
            await asyncio.to_thread(avvio_proc.ferma, pid)
            self.file_pid.unlink(missing_ok=True)

    async def ferma_ollama(self):
        """Alla chiusura di Comic Studio: ferma Ollama solo se l'ha avviato lui."""
        await self._chiudi_nostro()

    def _segui_log(self, lavoro: str | None, lettore: avvio_proc.LettoreLog | None = None):
        """Porta nella console quello che Ollama scrive nel suo registro (senza le richieste HTTP) e si accorge
        se si chiude da solo, spiegando perché."""
        lettore = lettore or avvio_proc.LettoreLog(self.file_log)
        pid = self.pid
        self._generazione += 1
        mia = self._generazione
        proprie: collections.deque = collections.deque(maxlen=80)

        async def segui():
            vuoti = 0
            while True:
                righe = await asyncio.to_thread(lettore.nuove) if mia == self._generazione else []
                attivo = lavoro if lavoro in self.app.gestore.lavori and \
                    self.app.gestore.lavori[lavoro].stato in ("in_coda", "in_corso") else None
                for r in righe:
                    if r.startswith("===== avvio:"):
                        continue
                    self.righe.append(r)
                    proprie.append(r)
                    livello = proc.livello_riga(r)
                    if livello:
                        self.app.bus.log(f"Ollama › {proc.messaggio(r)}", livello, attivo)
                if not avvio_proc.vivo(pid):
                    vuoti = vuoti + 1 if not righe else 0
                    if vuoti >= 2:
                        if pid in self._fermati:
                            self._fermati.discard(pid)
                            return
                        if self.pid == pid:
                            self.pid = None
                            self.file_pid.unlink(missing_ok=True)
                        errori = any(proc.livello_riga(x) == "errore" for x in proprie)
                        self.app.bus.log("Ollama si è chiuso" + (". " + proc.spiega_errore(list(proprie), self.porta)
                                                                if errori else " da solo."), "avviso")
                        await self.aggiorna()
                        return
                await asyncio.sleep(0.5)

        compito = asyncio.get_running_loop().create_task(segui())
        self._seguiti.add(compito)
        compito.add_done_callback(self._seguiti.discard)

    async def sorveglia(self, intervallo: float = 10.0):
        """Riavvia Ollama se si chiude o non risponde (se l'avvio automatico è attivo)."""
        while True:
            await asyncio.sleep(intervallo)
            try:
                await self.controlla()
            except Exception as e:  # noqa: BLE001
                self.app.bus.log(f"Controllo di Ollama fallito: {e}", "debug")

    async def controlla(self) -> Lavoro | None:
        """Un giro della sorveglianza; restituisce il lavoro di riavvio, se ne ha fatto partire uno."""
        i = self.imp
        if i.ia_tipo != "ollama" or not i.ia_avvio_automatico or self.fermato or self.in_avvio \
                or self._lavoro_attivo() or any(l.tipo == "ia_installa" for l in self.app.gestore.attivi()):
            self._non_risponde = 0
            return None
        async with self.client(timeout=TIMEOUT_CONTROLLO) as c:
            risponde = await c.versione(TIMEOUT_CONTROLLO) is not None
        if risponde:
            self._non_risponde = 0
            self._fallimenti = 0
            if not self.stato.raggiungibile:
                await self.aggiorna()
            return None
        if not eseguibile() or self._fallimenti >= TENTATIVI:
            return None
        if self.stato.raggiungibile:
            await self.aggiorna()           # l'interfaccia vede subito che non risponde
        self._non_risponde += 1
        nostro_vivo = avvio_proc.vivo(self.pid)
        # spento: si riaccende al secondo controllo; acceso ma bloccato: dopo il terzo, se non sta rispondendo
        if self._non_risponde < (3 if nostro_vivo else 2) or (nostro_vivo and self._lock.locked()):
            return None
        self._non_risponde = 0
        if nostro_vivo:
            self.app.bus.log("Ollama non risponde più: lo riavvio", "avviso")
            l = self.riavvia(a_mano=False)
        else:
            self.app.bus.log("Ollama è spento: lo avvio", "avviso")
            l = self.avvia(a_mano=False)
        asyncio.get_running_loop().create_task(self._esito_automatico(l))
        return l

    async def _esito_automatico(self, l: Lavoro):
        while l.stato in ("in_coda", "in_corso"):
            await asyncio.sleep(0.2)
        if l.stato == "completato":
            self._fallimenti = 0
            return
        self._fallimenti += 1
        if self._fallimenti >= TENTATIVI:
            self.app.bus.log(f"Ollama non riparte dopo {TENTATIVI} tentativi: guarda i messaggi qui sopra e premi "
                             "Avvia in Sistema → IA locale quando hai risolto.", "errore")

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

    async def elimina_modello(self, nome: str) -> tuple[bool, StatoIA]:
        """Cancella un modello di Ollama dal disco per liberare spazio; si può riscaricare quando serve.
        Non si può mentre l'IA sta rispondendo o mentre si scarica un modello o Ollama."""
        if self.imp.ia_tipo != "ollama":
            raise ErroreIA("Da Comic Studio si possono eliminare solo i modelli di Ollama.")
        if any(l.tipo in ("ia_modello", "ia_installa") for l in self.app.gestore.attivi()):
            raise ErroreIA("Si sta scaricando un modello: aspetta che finisca, oppure fermalo, poi riprova.")
        if self._lock.locked():
            raise ErroreIA("L'IA sta lavorando: aspetta che finisca, oppure annulla il lavoro, poi riprova.")
        async with self._lock:                  # nessuna domanda all'IA parte mentre si cancella
            async with self.client(timeout=60) as c:
                if not await c.versione():
                    raise ErroreIA("Ollama è spento: avvialo (o scegli un modello) e riprova.")
                try:
                    trovato = await c.elimina_modello(nome)
                except httpx.HTTPError as e:
                    raise ErroreIA(f"Ollama non riesce a eliminare {nome}: {e}") from None
        stato = await self.aggiorna()
        self.app.bus.log(f"Modello {nome} eliminato dal computer" if trovato
                         else f"Il modello {nome} non era più in Ollama", "ok" if trovato else "info")
        return trovato, stato

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
