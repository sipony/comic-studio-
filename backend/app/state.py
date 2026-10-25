"""Stato condiviso dell'applicazione: impostazioni, progetti, lavori e connessione a ComfyUI."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from .comfy.client import ComfyClient, ComfyErrore
from .comfy.discovery import Installazione, cerca, conta_modelli, interroga, e_cartella_comfy
from .diagnostica import diagnostica
from .jobs import Bus, Gestore, Lavoro
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

    def __post_init__(self):
        self.gestore = Gestore(self.bus)

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
        nuovo = StatoComfy(url=imp.comfy_url, cartella=imp.comfy_dir)
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
            else:
                nuovo.errore = f"ComfyUI non risponde su {imp.comfy_url}. È avviato?"
        else:
            nuovo.errore = "ComfyUI non è ancora configurato."
        cambiato = (nuovo.connesso, nuovo.url, nuovo.cartella, nuovo.versione) != \
                   (self.comfy.connesso, self.comfy.url, self.comfy.cartella, self.comfy.versione)
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
        """Sequenza di avvio: trova ComfyUI se serve, poi controlla il sistema."""
        imp = self.impostazioni.valori
        if not (imp.comfy_url and imp.comfy_dir):
            l = self.avvia_ricerca(auto_seleziona=True)
            while l.stato in ("in_coda", "in_corso"):
                await asyncio.sleep(0.2)
        else:
            # serve comunque sapere dov'è il codice (main.py) per controllare gli aggiornamenti
            self.installazioni = await asyncio.to_thread(cerca, [imp.comfy_url], [imp.comfy_dir])
        self.avvia_diagnostica(rete=True)

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
