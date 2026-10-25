"""Un ComfyUI finto per i test: imita /system_stats, /object_info, /prompt, /history, /view e /ws."""
from __future__ import annotations

import asyncio
import io
import socket
import threading
import time
import uuid

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse, Response
from PIL import Image


class FintoComfy:
    def __init__(self, cartella_codice: str | None = None):
        self.cartella_codice = cartella_codice
        self.ricevuti: list[dict] = []
        self.storia: dict[str, dict] = {}
        self.client_ws: dict[str, WebSocket] = {}
        self.errore_nodo: str | None = None     # se impostato, l'esecuzione fallisce
        self.object_info: dict | None = None    # definizioni dei nodi restituite da /object_info
        self.lento = 0.0                        # secondi per ogni passo del KSampler
        self.anteprime = False                  # manda anteprime binarie durante il campionamento
        self.coda: list[list] = []              # [numero, prompt_id, workflow, extra, uscite]
        self.in_corso: list | None = None
        self.interrotto: str | None = None
        self.interruzioni = 0
        self.cancellati: list[str] = []
        self.liberazioni = 0
        self._lavoratore: asyncio.Task | None = None
        self.app = self._crea()
        self.porta = _porta_libera()
        self.url = f"http://127.0.0.1:{self.porta}"
        self._server: uvicorn.Server | None = None

    def _crea(self) -> FastAPI:
        app = FastAPI()

        @app.get("/system_stats")
        async def stats():
            argv = [f"{self.cartella_codice}/main.py", "--listen"] if self.cartella_codice else ["main.py"]
            return {"system": {"os": "posix", "comfyui_version": "0.9.9", "python_version": "3.12",
                               "argv": argv, "embedded_python": False},
                    "devices": [{"name": "cuda:0 NVIDIA GeForce RTX 4070 Laptop GPU", "type": "cuda",
                                 "vram_total": 8 * 1024 ** 3, "vram_free": 6 * 1024 ** 3}]}

        @app.get("/models/{cartella}")
        async def modelli(cartella: str):
            dati = {"checkpoints": ["waiIllustriousSDXL_v170.safetensors", "ponyDiffusionV6XL.safetensors"],
                    "loras": ["Comic_Style.safetensors"]}
            return dati.get(cartella, [])

        @app.get("/object_info")
        async def object_info():
            return self.object_info or {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["a.safetensors"]]}}}}

        @app.post("/upload/image")
        async def upload(image: UploadFile = File(...), subfolder: str = Form(""), overwrite: str = Form("")):
            await image.read()
            return {"name": image.filename, "subfolder": subfolder, "type": "input"}

        @app.post("/prompt")
        async def prompt(corpo: dict):
            wf = corpo["prompt"]
            errori = {k: {"class_type": n.get("class_type"), "errors": [{"message": "Value not in list",
                                                                         "details": "ckpt_name"}]}
                      for k, n in wf.items() if n.get("class_type") == "Rotto"}
            if errori:
                return JSONResponse({"error": {"message": "Prompt outputs failed validation"},
                                     "node_errors": errori}, status_code=400)
            self.ricevuti.append(wf)
            pid = uuid.uuid4().hex
            self.coda.append([len(self.ricevuti), pid, wf, {"client_id": corpo.get("client_id")}, []])
            if self._lavoratore is None or self._lavoratore.done():
                self._lavoratore = asyncio.get_running_loop().create_task(self._lavora())
            return {"prompt_id": pid, "number": len(self.ricevuti), "node_errors": {}}

        @app.get("/queue")
        async def queue():
            return {"queue_running": [self.in_corso] if self.in_corso else [], "queue_pending": list(self.coda)}

        @app.post("/queue")
        async def queue_modifica(corpo: dict):
            via = set(corpo.get("delete", []))
            self.cancellati += [v[1] for v in self.coda if v[1] in via]
            self.coda = [v for v in self.coda if v[1] not in via]
            return {}

        @app.post("/interrupt")
        async def interrupt(req: Request):
            self.interruzioni += 1
            if self.in_corso:
                self.interrotto = self.in_corso[1]
            return {}

        @app.get("/history/{pid}")
        async def history(pid: str):
            return {pid: self.storia[pid]} if pid in self.storia else {}

        @app.get("/view")
        async def view(filename: str, subfolder: str = "", type: str = "output"):
            b = io.BytesIO()
            h = abs(hash(filename))
            Image.new("RGB", (64, 96), (h % 256, h // 256 % 256, h // 65536 % 256)).save(b, "PNG")
            return Response(b.getvalue(), media_type="image/png")

        @app.post("/free")
        async def free():
            self.liberazioni += 1
            return {}

        @app.websocket("/ws")
        async def ws(socket_: WebSocket, clientId: str = ""):
            await socket_.accept()
            self.client_ws[clientId] = socket_
            await socket_.send_json({"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 0}}}})
            try:
                while True:
                    await socket_.receive_text()
            except Exception:
                self.client_ws.pop(clientId, None)

        return app

    async def _lavora(self):
        while self.coda:
            voce = self.coda.pop(0)
            self.in_corso = voce
            try:
                await self._esegui(voce[1], voce[2], voce[3].get("client_id"))
            finally:
                self.in_corso = None

    async def _esegui(self, pid, wf, client_id):
        await asyncio.sleep(0.05)
        ws = self.client_ws.get(client_id)

        async def invia(m):
            if ws:
                try:
                    await ws.send_json(m)
                except Exception:
                    pass

        salva = [k for k, n in wf.items() if n.get("class_type") == "SaveImage"]
        for k, n in wf.items():
            await invia({"type": "executing", "data": {"node": k, "prompt_id": pid}})
            if n.get("class_type") == "KSampler":
                for i in range(1, 5):
                    if self.interrotto == pid:
                        self.interrotto = None
                        await invia({"type": "execution_interrupted", "data": {"prompt_id": pid, "node_id": k}})
                        self.storia[pid] = {"status": {"status_str": "error", "completed": False, "messages": [
                            ["execution_interrupted", {"node_type": "KSampler"}]]}, "outputs": {}}
                        return
                    await invia({"type": "progress", "data": {"value": i, "max": 4, "node": k, "prompt_id": pid}})
                    if self.anteprime and ws:
                        b = io.BytesIO()
                        Image.new("RGB", (32, 48), (40 * i, 80, 160)).save(b, "JPEG")
                        try:
                            await ws.send_bytes((1).to_bytes(4, "big") + (1).to_bytes(4, "big") + b.getvalue())
                        except Exception:
                            pass
                    await asyncio.sleep(0.01 + self.lento)
            if self.errore_nodo and n.get("class_type") == self.errore_nodo:
                await invia({"type": "execution_error", "data": {"prompt_id": pid, "node_id": k,
                                                                 "node_type": self.errore_nodo,
                                                                 "exception_message": "CUDA out of memory"}})
                self.storia[pid] = {"status": {"status_str": "error", "completed": False, "messages": [
                    ["execution_error", {"node_type": self.errore_nodo, "exception_message": "CUDA out of memory"}]]},
                    "outputs": {}}
                return
        self.storia[pid] = {"status": {"status_str": "success", "completed": True, "messages": []},
                            "outputs": {k: {"images": [{"filename": f"img_{pid[:8]}_{k}.png", "subfolder": "", "type": "output"}]}
                                        for k in salva}}
        await invia({"type": "executing", "data": {"node": None, "prompt_id": pid}})

    def avvia(self):
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.porta, log_level="error")
        self._server = uvicorn.Server(config)
        threading.Thread(target=self._server.run, daemon=True).start()
        for _ in range(100):
            if self._server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("il finto ComfyUI non parte")

    def ferma(self):
        if self._server:
            self._server.should_exit = True


def _porta_libera() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
