"""Client asincrono per l'API di ComfyUI (HTTP + WebSocket)."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
import websockets

# cartella di modelli -> (nodo, ingresso) da cui ricavarla se l'endpoint /models non esiste
MODELLI_DA_NODI = {
    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
    "loras": ("LoraLoader", "lora_name"),
    "vae": ("VAELoader", "vae_name"),
    "controlnet": ("ControlNetLoader", "control_net_name"),
    "clip_vision": ("CLIPVisionLoader", "clip_name"),
    "ipadapter": ("IPAdapterModelLoader", "ipadapter_file"),
    "upscale_models": ("UpscaleModelLoader", "model_name"),
}


class ComfyErrore(Exception):
    pass


Avanzamento = Callable[[float, str], Awaitable[None] | None]
Anteprima = Callable[[bytes, str], None]


def leggi_anteprima(msg: bytes) -> tuple[bytes, str] | None:
    """Un'anteprima mandata da ComfyUI durante il campionamento (messaggio binario del WebSocket).

    Formati: 4 byte tipo evento (1 = immagine, 4 = immagine con metadati) + 4 byte formato (1 JPEG, 2 PNG) +
    immagine; oppure, per il tipo 4, 4 byte lunghezza dei metadati + JSON + immagine."""
    if len(msg) < 8:
        return None
    evento = int.from_bytes(msg[:4], "big")
    if evento == 1:
        formato = int.from_bytes(msg[4:8], "big")
        return msg[8:], "image/png" if formato == 2 else "image/jpeg"
    if evento == 4:
        n = int.from_bytes(msg[4:8], "big")
        try:
            meta = json.loads(msg[8:8 + n].decode("utf-8"))
        except ValueError:
            meta = {}
        return msg[8 + n:], meta.get("image_type") or "image/jpeg"
    return None


class ComfyClient:
    def __init__(self, url: str, timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.client_id = uuid.uuid4().hex
        self._http = httpx.AsyncClient(base_url=self.url, timeout=timeout)
        self._object_info: dict | None = None

    async def chiudi(self):
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.chiudi()

    # ------------------------------------------------------------ base

    async def _get(self, path: str, **kw):
        try:
            r = await self._http.get(path, **kw)
        except httpx.HTTPError as e:
            raise ComfyErrore(f"ComfyUI non risponde su {self.url}: {e}") from None
        if r.status_code >= 400:
            raise ComfyErrore(f"ComfyUI ha risposto {r.status_code} su {path}: {r.text[:500]}")
        return r

    async def stato(self) -> dict:
        return (await self._get("/system_stats")).json()

    async def object_info(self, ricarica: bool = False) -> dict:
        if self._object_info is None or ricarica:
            self._object_info = (await self._get("/object_info", timeout=120)).json()
        return self._object_info

    async def modelli(self, cartella: str) -> list[str]:
        """Elenco dei file di una cartella di modelli, con l'endpoint /models o dalle definizioni dei nodi."""
        try:
            r = await self._http.get(f"/models/{cartella}")
            if r.status_code == 200 and isinstance(r.json(), list):
                return sorted(r.json(), key=str.lower)
        except (httpx.HTTPError, ValueError):
            pass
        nodo, ingresso = MODELLI_DA_NODI.get(cartella, (None, None))
        info = await self.object_info()
        if nodo and nodo in info:
            spec = info[nodo]["input"]["required"].get(ingresso)
            if spec and isinstance(spec[0], list):
                return sorted(spec[0], key=str.lower)
        return []

    async def coda(self) -> dict:
        return (await self._get("/queue")).json()

    async def interrompi(self):
        await self._http.post("/interrupt")

    async def annulla_nostri(self, prompt_id: str | None = None):
        """Toglie dalla coda i lavori di questo client, ferma quello in corso se è nostro e libera la VRAM.

        Va chiamata quando una generazione viene annullata: senza, ComfyUI continuerebbe a lavorare e a tenere i
        modelli nella memoria della scheda video."""
        try:
            q = (await self._http.get("/queue", timeout=5)).json()
        except (httpx.HTTPError, ValueError):
            q = {}

        def nostri(voci):
            out = []
            for v in voci or []:
                try:
                    pid, extra = v[1], v[3] if len(v) > 3 else {}
                except (IndexError, TypeError):
                    continue
                if pid == prompt_id or (isinstance(extra, dict) and extra.get("client_id") == self.client_id):
                    out.append(pid)
            return out
        in_attesa = nostri(q.get("queue_pending"))
        in_corso = nostri(q.get("queue_running"))
        try:
            if in_attesa:
                await self._http.post("/queue", json={"delete": in_attesa}, timeout=5)
            if in_corso or (prompt_id and not q):
                await self._http.post("/interrupt", json={"prompt_id": (in_corso or [prompt_id])[0]}, timeout=5)
        except httpx.HTTPError:
            pass
        await self.libera_memoria()

    async def libera_memoria(self):
        try:
            await self._http.post("/free", json={"unload_models": True, "free_memory": True})
        except httpx.HTTPError:
            pass

    # ------------------------------------------------------------ file

    async def carica_immagine(self, file: Path, sottocartella: str = "fumetto_studio") -> str:
        """Carica un'immagine in input/ e restituisce il nome da usare in LoadImage."""
        dati = {"overwrite": "true", "subfolder": sottocartella}
        with open(file, "rb") as f:
            try:
                r = await self._http.post("/upload/image", data=dati,
                                          files={"image": (file.name, f, "image/png")})
            except httpx.HTTPError as e:
                raise ComfyErrore(f"Caricamento di {file.name} fallito: {e}") from None
        if r.status_code >= 400:
            raise ComfyErrore(f"Caricamento di {file.name} rifiutato: {r.text[:300]}")
        d = r.json()
        return f"{d['subfolder']}/{d['name']}" if d.get("subfolder") else d["name"]

    async def scarica(self, immagine: dict) -> bytes:
        q = {"filename": immagine["filename"], "subfolder": immagine.get("subfolder", ""),
             "type": immagine.get("type", "output")}
        return (await self._get("/view", params=q)).content

    # ------------------------------------------------------------ esecuzione

    async def esegui(self, workflow: dict, avanzamento: Avanzamento | None = None,
                     timeout: float = 3600, anteprima: Anteprima | None = None) -> dict[str, list[dict]]:
        """Accoda un workflow in formato API, segue l'avanzamento via WebSocket e
        restituisce le immagini prodotte per nodo: {id_nodo: [{filename, subfolder, type}, ...]}.

        Se il lavoro viene annullato, il prompt viene tolto dalla coda o interrotto e la VRAM liberata.
        `anteprima` riceve le immagini parziali che ComfyUI manda durante il campionamento."""
        ws_url = self.url.replace("http", "ws", 1) + f"/ws?clientId={self.client_id}"
        try:
            ws = await websockets.connect(ws_url, max_size=None, open_timeout=10)
        except (OSError, websockets.InvalidHandshake, asyncio.TimeoutError):
            ws = None   # senza WebSocket si va avanti a interrogare /history

        pid: str | None = None
        try:
            try:
                r = await self._http.post("/prompt", json={"prompt": workflow, "client_id": self.client_id})
            except httpx.HTTPError as e:
                raise ComfyErrore(f"ComfyUI non risponde su {self.url}: {e}") from None
            corpo = r.json() if r.content else {}
            if r.status_code >= 400 or corpo.get("node_errors"):
                raise ComfyErrore(descrivi_errori(corpo, workflow))
            pid = corpo["prompt_id"]
            nodi_totali = max(1, len(workflow))
            fatti: set[str] = set()

            async def notifica(v, testo):
                if avanzamento:
                    ris = avanzamento(min(max(v, 0.0), 1.0), testo)
                    if asyncio.iscoroutine(ris):
                        await ris

            scadenza = asyncio.get_running_loop().time() + timeout
            while True:
                if asyncio.get_running_loop().time() > scadenza:
                    raise ComfyErrore("Tempo scaduto in attesa di ComfyUI.")
                if ws is not None:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except asyncio.TimeoutError:
                        msg = None
                    except websockets.ConnectionClosed:
                        ws, msg = None, None
                    if isinstance(msg, str):
                        m = json.loads(msg)
                        d = m.get("data", {})
                        if d.get("prompt_id") not in (None, pid):
                            continue
                        tipo = m.get("type")
                        if tipo == "progress":
                            parte = d["value"] / max(1, d["max"])
                            classe = workflow.get(str(d.get("node")), {}).get("class_type", "")
                            await notifica((len(fatti) + parte) / nodi_totali,
                                           f"{classe} {d['value']}/{d['max']}".strip())
                        elif tipo == "executing" and d.get("node"):
                            fatti.add(str(d["node"]))
                            classe = workflow.get(str(d["node"]), {}).get("class_type", "")
                            await notifica(len(fatti) / nodi_totali, classe)
                        elif tipo == "execution_interrupted":
                            raise ComfyErrore("La generazione è stata interrotta in ComfyUI.")
                        elif tipo == "execution_cached":
                            fatti.update(str(n) for n in d.get("nodes", []))
                        elif tipo == "execution_error":
                            raise ComfyErrore(f"Errore nel nodo {d.get('node_type', '?')} ({d.get('node_id')}): "
                                              f"{d.get('exception_message', '').strip()}")
                        elif tipo == "executing" and d.get("node") is None:
                            break
                        continue
                    if isinstance(msg, bytes):     # anteprima del campionamento
                        if anteprima:
                            a = leggi_anteprima(msg)
                            if a and a[0]:
                                anteprima(*a)
                        continue
                else:
                    await asyncio.sleep(1.0)
                # controllo di sicurezza: la storia dice se è finito
                storia = (await self._get(f"/history/{pid}")).json().get(pid)
                if storia and storia.get("status", {}).get("completed") is not None:
                    st = storia["status"]
                    if st.get("status_str") == "error":
                        if any(x[0] == "execution_interrupted" for x in st.get("messages", [])):
                            raise ComfyErrore("La generazione è stata interrotta in ComfyUI.")
                        err = next((x[1] for x in st.get("messages", []) if x[0] == "execution_error"), {})
                        raise ComfyErrore(f"Errore nel nodo {err.get('node_type', '?')}: "
                                          f"{err.get('exception_message', 'sconosciuto')}")
                    break

            await notifica(1.0, "completato")
            storia = (await self._get(f"/history/{pid}")).json().get(pid, {})
            return {k: v.get("images", []) for k, v in storia.get("outputs", {}).items() if v.get("images")}
        except asyncio.CancelledError:
            # annullato: anche un secondo annullamento non deve fermare la pulizia
            await asyncio.shield(self.annulla_nostri(pid))
            raise
        finally:
            if ws is not None:
                await ws.close()


def descrivi_errori(corpo: dict, workflow: dict) -> str:
    """Trasforma la risposta di errore di /prompt in un messaggio leggibile."""
    righe = []
    err = corpo.get("error")
    if isinstance(err, dict) and err.get("message"):
        righe.append(err["message"] + (f" ({err['details']})" if err.get("details") else ""))
    for nodo, info in (corpo.get("node_errors") or {}).items():
        classe = info.get("class_type") or workflow.get(nodo, {}).get("class_type", "?")
        for e in info.get("errors", []):
            righe.append(f"  nodo {nodo} {classe}: {e.get('message', '')} {e.get('details', '')}".rstrip())
    return "Workflow rifiutato da ComfyUI:\n" + "\n".join(righe) if righe else f"Workflow rifiutato: {corpo}"
