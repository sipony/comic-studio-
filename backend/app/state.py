"""Stato condiviso dell'applicazione: impostazioni, progetti, lavori e connessione a ComfyUI."""
from __future__ import annotations

import asyncio
import collections
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .comfy import avvio as avvio_comfy
from .comfy.client import ComfyClient, ComfyErrore
from .comfy.discovery import (Installazione, Istanza, cartella_da_argv, cerca, conta_modelli, e_cartella_comfy,
                              interroga, istanze_attive, risolvi)
from .diagnostica import diagnostica
from .jobs import Annullato, Bus, Gestore, Lavoro
from .projects import Archivio as ArchivioProgetti
from .settings import Archivio as ArchivioImpostazioni, cartella_dati

RADICE_APP = Path(__file__).resolve().parents[2]

ESTENSIONI_MODELLI = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx"}


@dataclass
class StatoComfy:
    connesso: bool = False
    url: str | None = None
    cartella: str | None = None
    versione: str | None = None
    gpu: str | None = None
    vram_totale: int | None = None
    vram_libera: int | None = None
    dispositivi: list = field(default_factory=list)
    errore: str | None = None
    in_avvio: bool = False            # Comic Studio lo sta avviando
    avviato_da_noi: bool = False      # il processo è stato avviato da Comic Studio (e lo si può fermare)
    pid: int | None = None
    avvio_automatico: bool = True

    def dict(self):
        return dict(self.__dict__)


@dataclass
class App:
    impostazioni: ArchivioImpostazioni
    bus: Bus = field(default_factory=Bus)
    gestore: Gestore = field(init=False)
    comfy: StatoComfy = field(default_factory=StatoComfy)
    installazioni: list[Installazione] = field(default_factory=list)
    ricerca_in_corso: bool = False
    rapporto: dict | None = None
    _object_info: dict | None = None
    _object_info_chiave: tuple | None = None
    comfy_pid: int | None = None
    comfy_in_avvio: bool = False
    in_preparazione: bool = False     # la sequenza di apertura sta ancora decidendo se avviare ComfyUI
    righe_comfy: collections.deque = field(default_factory=lambda: collections.deque(maxlen=80))
    _segui: asyncio.Task | None = None

    def __post_init__(self):
        self.gestore = Gestore(self.bus)

    @property
    def file_log_comfy(self) -> Path:
        return cartella_dati() / "comfyui.log"

    @property
    def file_pid_comfy(self) -> Path:
        return cartella_dati() / "comfyui.pid"

    @property
    def progetti(self) -> ArchivioProgetti:
        return ArchivioProgetti(Path(self.impostazioni.valori.cartella_progetti))

    def client(self) -> ComfyClient:
        url = self.impostazioni.valori.comfy_url
        if not url:
            raise ComfyErrore("ComfyUI non è configurato: vai in Connessione e cercalo.")
        return ComfyClient(url)

    # ------------------------------------------------------------ connessione

    async def aggiorna_comfy(self) -> StatoComfy:
        imp = self.impostazioni.valori
        if self.comfy_pid and not avvio_comfy.vivo(self.comfy_pid):
            self.comfy_pid = None
        nuovo = StatoComfy(url=imp.comfy_url, cartella=imp.comfy_dir, in_avvio=self.comfy_in_avvio,
                           avviato_da_noi=self.comfy_pid is not None, pid=self.comfy_pid,
                           avvio_automatico=imp.avvio_automatico)
        if imp.comfy_url:
            ist = await asyncio.to_thread(interroga, imp.comfy_url, 2.0)
            if ist:
                nuovo.connesso = True
                nuovo.versione = ist.versione
                nuovo.dispositivi = ist.dispositivi
                if ist.dispositivi:
                    d = ist.dispositivi[0]
                    nuovo.gpu = d.get("name")
                    nuovo.vram_totale = d.get("vram_total")
                    nuovo.vram_libera = d.get("vram_free")
            elif self.comfy_in_avvio:
                nuovo.errore = "ComfyUI si sta avviando…"
            else:
                nuovo.errore = f"ComfyUI non risponde su {imp.comfy_url}. È avviato?"
        else:
            nuovo.errore = "ComfyUI non è ancora configurato."
        cambiato = (nuovo.connesso, nuovo.url, nuovo.cartella, nuovo.versione) != \
                   (self.comfy.connesso, self.comfy.url, self.comfy.cartella, self.comfy.versione)
        if (self.comfy_in_avvio or self.in_preparazione) and not nuovo.connesso:
            cambiato = False          # durante l'avvio il "non risponde" è normale
        self.comfy = nuovo
        self.bus.pubblica({"tipo": "comfy", "dati": nuovo.dict()})
        if cambiato:
            if nuovo.connesso:
                self.bus.log(f"Connesso a ComfyUI {nuovo.versione or ''} su {nuovo.url}"
                             + (f" — GPU {nuovo.gpu}" if nuovo.gpu else ""), "ok")
            elif nuovo.url:
                self.bus.log(nuovo.errore or "ComfyUI non raggiungibile", "avviso")
        return nuovo

    async def sorveglia(self, intervallo: float = 5.0):
        while True:
            try:
                await self.aggiorna_comfy()
            except Exception as e:  # noqa: BLE001
                self.bus.log(f"Controllo di ComfyUI fallito: {e}", "debug")
            await asyncio.sleep(intervallo)

    def usa(self, url: str | None, cartella: str | None):
        if cartella:
            c = Path(cartella).expanduser()
            if not e_cartella_comfy(c):
                if e_cartella_comfy(c / "ComfyUI"):
                    c = c / "ComfyUI"
                else:
                    raise ValueError(f"{cartella} non sembra una cartella di ComfyUI (manca models/)")
            cartella = str(c.resolve())
        self.impostazioni.aggiorna(comfy_url=url.rstrip("/") if url else None, comfy_dir=cartella)

    def avvia_ricerca(self, auto_seleziona: bool) -> Lavoro:
        async def lavoro(l: Lavoro):
            self.ricerca_in_corso = True
            try:
                l.avanza(0.1, "interrogo le porte di rete e i processi")
                extra_url = [self.impostazioni.valori.comfy_url] if self.impostazioni.valori.comfy_url else []
                extra_dir = [self.impostazioni.valori.comfy_dir] if self.impostazioni.valori.comfy_dir else []
                trovate = await asyncio.to_thread(cerca, extra_url, extra_dir)
                self.installazioni = trovate
                if not trovate:
                    l.log("Nessuna installazione di ComfyUI trovata. Avvia ComfyUI e riprova, "
                          "oppure indica la cartella a mano.", "avviso")
                for i in trovate:
                    stato = f"in esecuzione su {i.url}" if i.url else "non avviato"
                    l.log(f"Trovato ComfyUI ({i.tipo}, {stato}) in {i.cartella} — "
                          f"{i.modelli.get('checkpoints', 0)} checkpoint, {i.modelli.get('loras', 0)} LoRA", "ok")
                imp = self.impostazioni.valori
                if auto_seleziona and trovate and not (imp.comfy_url and imp.comfy_dir):
                    scelta = trovate[0]
                    self.usa(scelta.url or imp.comfy_url or "http://127.0.0.1:8188", scelta.cartella)
                    l.log(f"Uso automaticamente {scelta.cartella}", "info")
                await self.aggiorna_comfy()
                return [i.dict() for i in trovate]
            finally:
                self.ricerca_in_corso = False
                self.bus.pubblica({"tipo": "installazioni", "dati": [i.dict() for i in self.installazioni]})

        return self.gestore.avvia("ricerca_comfy", "Ricerca di ComfyUI", lavoro)

    async def object_info(self, ricarica: bool = False) -> dict:
        """Definizioni dei nodi di ComfyUI, tenute in memoria finché non cambia l'installazione."""
        chiave = (self.comfy.url, self.comfy.versione)
        if ricarica or self._object_info is None or self._object_info_chiave != chiave:
            async with self.client() as c:
                self._object_info = await c.object_info()
            self._object_info_chiave = chiave
        return self._object_info

    # ------------------------------------------------------------ controllo del sistema

    def avvia_diagnostica(self, rete: bool = True) -> Lavoro:
        async def lavoro(l: Lavoro):
            stato = await self.aggiorna_comfy()
            nodi = None
            if stato.connesso:
                try:
                    async with self.client() as c:
                        nodi = set(await c.object_info())
                except ComfyErrore as e:
                    l.log(f"Definizioni dei nodi non disponibili: {e}", "avviso")
            codice = next((i.codice for i in self.installazioni if i.cartella == stato.cartella), None)
            r = await diagnostica(stato.cartella, codice, stato.versione, stato.dispositivi, nodi,
                                  cartella_dati(), RADICE_APP, rete=rete,
                                  avanzamento=lambda v, t: l.avanza(v, t))
            for v in r.voci:
                if v.esito in ("errore", "avviso"):
                    l.log(f"{v.categoria} · {v.nome}: {v.dettaglio}" + (f" — {v.azione}" if v.azione else ""),
                          v.esito)
            for c in r.consigli:
                l.log(f"Consiglio: {c}", "info")
            rip = r.dict()["riepilogo"]
            l.log(f"Controllo del sistema: {rip['ok']} ok, {rip['avviso']} avvisi, {rip['errore']} problemi",
                  "ok" if not rip["errore"] else "avviso")
            self.rapporto = r.dict()
            self.bus.pubblica({"tipo": "diagnostica", "dati": self.rapporto})
            return self.rapporto

        return self.gestore.avvia("diagnostica", "Controllo del sistema", lavoro)

    async def avvio(self):
        """Sequenza di avvio: trova ComfyUI se serve, lo avvia se è spento, poi controlla il sistema."""
        self.in_preparazione = True
        try:
            await self._prepara()
        finally:
            self.in_preparazione = False
        self.avvia_diagnostica(rete=True)

    async def _prepara(self):
        imp = self.impostazioni.valori
        if not (imp.comfy_url and imp.comfy_dir):
            await _attendi(self.avvia_ricerca(auto_seleziona=True))
        else:
            # serve comunque sapere dov'è il codice (main.py) per controllare gli aggiornamenti
            self.installazioni = await asyncio.to_thread(cerca, [imp.comfy_url], [imp.comfy_dir])
        # un ComfyUI avviato da noi in una sessione precedente, ancora acceso
        pid = await asyncio.to_thread(avvio_comfy.leggi_pid, self.file_pid_comfy)
        if pid:
            self.comfy_pid = pid
            self._segui_log(None)
        stato = await self.aggiorna_comfy()
        imp = self.impostazioni.valori
        if stato.connesso:
            return
        if imp.avvio_automatico and (imp.comfy_dir or imp.comando_comfy):
            await _attendi(self.avvia_comfy())
        elif imp.comfy_dir:
            self.bus.log("ComfyUI non è avviato: premi «Avvia ComfyUI» in Sistema → Connessione "
                         "(o attiva l'avvio automatico).", "avviso")

    # ------------------------------------------------------------ avvio e arresto di ComfyUI

    def _lavoro_comfy_attivo(self) -> Lavoro | None:
        return next((l for l in self.gestore.attivi() if l.tipo in ("avvio_comfy", "arresto_comfy")), None)

    def avvia_comfy(self) -> Lavoro:
        """Si aggancia a ComfyUI se è già attivo, altrimenti lo avvia e aspetta che sia pronto."""
        return self._lavoro_comfy_attivo() or \
            self.gestore.avvia("avvio_comfy", "Avvio di ComfyUI", self._avvia_comfy)

    def ferma_comfy(self) -> Lavoro:
        async def lavoro(l: Lavoro):
            await self._ferma_comfy(l)
        return self._lavoro_comfy_attivo() or self.gestore.avvia("arresto_comfy", "Arresto di ComfyUI", lavoro)

    def riavvia_comfy(self) -> Lavoro:
        async def lavoro(l: Lavoro):
            if self.comfy_pid:
                await self._ferma_comfy(l)
            elif self.comfy.connesso:
                raise avvio_comfy.ErroreAvvio("ComfyUI non è stato avviato da Comic Studio: chiudilo tu "
                                              "e poi premi Avvia.")
            return await self._avvia_comfy(l)
        return self._lavoro_comfy_attivo() or self.gestore.avvia("avvio_comfy", "Riavvio di ComfyUI", lavoro)

    async def _ferma_comfy(self, l: Lavoro):
        pid = self.comfy_pid
        if not pid:
            raise avvio_comfy.ErroreAvvio("Posso fermare solo un ComfyUI avviato da Comic Studio.")
        l.avanza(0.2, "chiudo ComfyUI")
        self.comfy_pid = None
        await asyncio.to_thread(avvio_comfy.ferma, pid)
        self.file_pid_comfy.unlink(missing_ok=True)
        l.log(f"ComfyUI fermato (PID {pid})", "ok")
        await self.aggiorna_comfy()

    def _da_agganciare(self, attive: list[Istanza]) -> Istanza | None:
        """Tra le istanze attive, quella della nostra installazione (o l'unica, se non si sa)."""
        imp = self.impostazioni.valori
        if not attive:
            return None
        if imp.comfy_dir:
            mia = os.path.normcase(str(Path(imp.comfy_dir).resolve()))
            for ist in attive:
                p = cartella_da_argv(ist.argv)
                r = risolvi(p) if p else None
                if r and os.path.normcase(str(r[0].resolve())) == mia:
                    return ist
        for ist in attive:
            if imp.comfy_url and ist.url == imp.comfy_url.rstrip("/"):
                return ist
        return attive[0] if len(attive) == 1 else None

    async def _avvia_comfy(self, l: Lavoro):
        self.comfy_in_avvio = True
        await self.aggiorna_comfy()
        try:
            return await self._avvia_comfy_passi(l)
        finally:
            self.comfy_in_avvio = False
            await self.aggiorna_comfy()

    async def _avvia_comfy_passi(self, l: Lavoro):
        imp = self.impostazioni.valori
        l.avanza(0.02, "controllo se ComfyUI è già attivo")
        attive = await asyncio.to_thread(istanze_attive, [imp.comfy_url] if imp.comfy_url else [])
        gia = self._da_agganciare(attive)
        if gia:
            cartella = imp.comfy_dir
            if not cartella and (p := cartella_da_argv(gia.argv)) and (r := risolvi(p)):
                cartella = str(r[0].resolve())
            self.impostazioni.aggiorna(comfy_url=gia.url, comfy_dir=cartella)
            l.log(f"ComfyUI è già attivo su {gia.url}: mi aggancio", "ok")
            return {"agganciato": True, "url": gia.url}

        inst = next((i for i in self.installazioni if imp.comfy_dir and
                     os.path.normcase(i.cartella) == os.path.normcase(imp.comfy_dir)), None)
        c = avvio_comfy.comando(imp.comfy_dir, inst.codice if inst else None, inst.tipo if inst else "sconosciuto",
                                imp.comfy_url, imp.comando_comfy, imp.argomenti_comfy)
        url = f"http://127.0.0.1:{c.porta}"
        if imp.comfy_url and avvio_comfy.porta_da_url(imp.comfy_url) == c.porta:
            url = imp.comfy_url.rstrip("/")
        l.log(f"Avvio {c.descrizione}: {' '.join(c.argomenti)}")
        l.avanza(0.04, "avvio di ComfyUI")
        self.righe_comfy.clear()
        lettore = avvio_comfy.LettoreLog(self.file_log_comfy)
        pid = await asyncio.to_thread(avvio_comfy.avvia, c, self.file_log_comfy)
        if not c.app_desktop:
            self.comfy_pid = pid
            await asyncio.to_thread(avvio_comfy.salva_pid, self.file_pid_comfy, pid)
        self._segui_log(l.id, lettore, pid if not c.app_desktop else None)
        inizio = time.monotonic()
        try:
            while True:
                l.controlla()
                if await asyncio.to_thread(interroga, url, 1.5):
                    break
                trascorso = time.monotonic() - inizio
                if not c.app_desktop and not avvio_comfy.vivo(pid):
                    await asyncio.sleep(0.6)          # l'ultima uscita arrivi nel registro
                    self.comfy_pid = None
                    raise avvio_comfy.ErroreAvvio("ComfyUI si è chiuso durante l'avvio. "
                                                  + avvio_comfy.spiega_errore(list(self.righe_comfy), c.porta))
                if trascorso > imp.attesa_avvio:
                    self.impostazioni.aggiorna(comfy_url=url)
                    raise avvio_comfy.ErroreAvvio(
                        f"ComfyUI non risponde dopo {imp.attesa_avvio} s. Se sta ancora caricando i nodi "
                        "personalizzati, Comic Studio si aggancerà appena è pronto.")
                l.avanza(0.05 + 0.9 * (1 - math.exp(-trascorso / 45)),
                         f"attendo che ComfyUI sia pronto ({int(trascorso)} s)")
                await asyncio.sleep(1.0)
        except (Annullato, asyncio.CancelledError):
            if self.comfy_pid:
                await asyncio.to_thread(avvio_comfy.ferma, self.comfy_pid)
                self.comfy_pid = None
                self.file_pid_comfy.unlink(missing_ok=True)
            raise
        self.impostazioni.aggiorna(comfy_url=url)
        l.log(f"ComfyUI pronto su {url} dopo {time.monotonic() - inizio:.0f} s", "ok")
        return {"agganciato": False, "url": url, "pid": self.comfy_pid}

    def _segui_log(self, lavoro: str | None, lettore: avvio_comfy.LettoreLog | None = None,
                   pid: int | None = None):
        """Porta nella console di Comic Studio quello che ComfyUI scrive nel suo registro."""
        if self._segui and not self._segui.done():
            self._segui.cancel()
        lettore = lettore or avvio_comfy.LettoreLog(self.file_log_comfy)
        pid = pid or self.comfy_pid

        async def segui():
            vuoti = 0
            while True:
                righe = await asyncio.to_thread(lettore.nuove)
                id_lavoro = lavoro if lavoro and lavoro in self.gestore.lavori and \
                    self.gestore.lavori[lavoro].stato in ("in_coda", "in_corso") else None
                for r in righe:
                    if r.startswith("===== avvio:"):
                        continue
                    self.righe_comfy.append(r)
                    self.bus.log(f"ComfyUI › {r}", avvio_comfy.livello_riga(r), id_lavoro)
                if pid and not avvio_comfy.vivo(pid):
                    vuoti = vuoti + 1 if not righe else 0
                    if vuoti >= 2:
                        if self.comfy_pid == pid:
                            self.comfy_pid = None
                            self.file_pid_comfy.unlink(missing_ok=True)
                            self.bus.log("ComfyUI si è chiuso. "
                                         + avvio_comfy.spiega_errore(
                                list(self.righe_comfy), avvio_comfy.porta_da_url(self.impostazioni.valori.comfy_url))
                                         if any(avvio_comfy.livello_riga(x) == "errore" for x in self.righe_comfy)
                                         else "ComfyUI si è chiuso.", "avviso")
                            await self.aggiorna_comfy()
                        return
                await asyncio.sleep(0.5)

        self._segui = asyncio.get_running_loop().create_task(segui())

    # ------------------------------------------------------------ modelli

    async def modelli(self) -> dict[str, list[str]]:
        cartelle = ["checkpoints", "loras", "vae", "controlnet", "clip_vision", "ipadapter", "upscale_models"]
        if self.comfy.connesso:
            try:
                async with self.client() as c:
                    return {k: await c.modelli(k) for k in cartelle}
            except ComfyErrore as e:
                self.bus.log(f"Elenco modelli da ComfyUI non disponibile: {e}", "debug")
        base = self.impostazioni.valori.comfy_dir
        if not base:
            return {k: [] for k in cartelle}
        return await asyncio.to_thread(_modelli_da_disco, Path(base), cartelle)


async def _attendi(l: Lavoro):
    while l.stato in ("in_coda", "in_corso"):
        await asyncio.sleep(0.2)


def _modelli_da_disco(base: Path, cartelle: list[str]) -> dict[str, list[str]]:
    out = {}
    for k in cartelle:
        d = base / "models" / k
        nomi = []
        if d.is_dir():
            for radice, _, files in os.walk(d):
                for f in files:
                    if Path(f).suffix.lower() in ESTENSIONI_MODELLI:
                        nomi.append(str((Path(radice) / f).relative_to(d)))
        out[k] = sorted(nomi, key=str.lower)
    return out


__all__ = ["App", "StatoComfy", "conta_modelli"]
