"""Intelligenza artificiale locale che legge i testi: Ollama (consigliato) o un server compatibile OpenAI.

- Ollama: se è già in esecuzione ci si aggancia; se è installato lo si avvia; altrimenti Comic Studio può
  scaricare la versione portatile in <cartella dati>/strumenti/ollama (solo dopo conferma dell'utente)
- i modelli si scaricano con Ollama (/api/pull) con l'avanzamento
- le risposte sono JSON con uno schema: Ollama lo fa rispettare (format), negli altri server lo si chiede nel testo
- keep_alive = 0: il modello esce dalla memoria della GPU appena ha risposto, così ComfyUI ha tutta la VRAM
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import tarfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from .settings import cartella_dati

URL_OLLAMA = "http://127.0.0.1:11434"
RELEASE_OLLAMA = "https://api.github.com/repos/ollama/ollama/releases/latest"

# modelli proposti (nome Ollama, descrizione, GB circa)
MODELLI_CONSIGLIATI = [
    ("qwen3:8b", "consigliato: capisce bene l'italiano e i testi lunghi", 5.2),
    ("qwen3:4b", "più leggero e veloce, un po' meno preciso", 2.6),
    ("gemma3:12b", "più preciso, più lento (meglio con 32 GB di RAM)", 8.1),
]

Avanzamento = Callable[[float, str], None]


class ErroreIA(Exception):
    pass


@dataclass
class StatoIA:
    tipo: str                         # ollama, openai, nessuna
    url: str | None = None
    modello: str | None = None
    raggiungibile: bool = False
    versione: str | None = None
    modelli: list[str] = field(default_factory=list)
    modello_presente: bool = False
    eseguibile: str | None = None     # Ollama trovato sul disco (anche se spento)
    portatile: bool = False           # è quello scaricato da Comic Studio
    errore: str | None = None

    @property
    def pronta(self) -> bool:
        return self.raggiungibile and self.modello_presente

    def dict(self):
        return asdict(self) | {"pronta": self.pronta}


# ---------------------------------------------------------------- dove sta Ollama

def cartella_ollama() -> Path:
    return cartella_dati() / "strumenti" / "ollama"


def _nome_exe() -> str:
    return "ollama.exe" if os.name == "nt" else "ollama"


def ollama_portatile() -> Path | None:
    c = cartella_ollama()
    if not c.is_dir():
        return None
    for p in sorted(c.rglob(_nome_exe()), key=lambda x: len(x.parts)):
        if p.is_file() and "modelli" not in p.parts:
            return p
    return None


def ollama_di_sistema() -> Path | None:
    trovato = shutil.which("ollama")
    if trovato:
        return Path(trovato)
    candidati = []
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidati += [base / "Programs" / "Ollama" / "ollama.exe"]
    elif platform.system() == "Darwin":
        candidati += [Path("/Applications/Ollama.app/Contents/Resources/ollama"), Path("/usr/local/bin/ollama"),
                      Path("/opt/homebrew/bin/ollama")]
    else:
        candidati += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    return next((c for c in candidati if c.is_file()), None)


def asset_ollama(release: dict, sistema: str | None = None, macchina: str | None = None) -> dict:
    """L'archivio portatile giusto per questo computer, tra quelli della release di Ollama."""
    sistema = (sistema or platform.system()).lower()
    macchina = (macchina or platform.machine()).lower()
    arm = macchina in ("arm64", "aarch64")
    if sistema == "windows":
        voluti = [rf"^ollama-windows-{'arm64' if arm else 'amd64'}\.zip$"]
    elif sistema == "darwin":
        voluti = [r"^ollama-darwin\.tgz$", r"^ollama-darwin\.tar\.zst$"]
    else:
        a = "arm64" if arm else "amd64"
        voluti = [rf"^ollama-linux-{a}\.tar\.zst$", rf"^ollama-linux-{a}\.tgz$"]
    nomi = {x["name"]: x for x in release.get("assets", [])}
    for regex in voluti:
        for nome, x in nomi.items():
            if re.match(regex, nome):
                return x
    raise ErroreIA(f"Nella release di Ollama non trovo l'archivio per {sistema} {macchina}.")


def estrai(archivio: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    nome = archivio.name
    if nome.endswith(".zip"):
        with zipfile.ZipFile(archivio) as z:
            z.extractall(dest)
    elif nome.endswith(".tgz") or nome.endswith(".tar.gz"):
        with tarfile.open(archivio) as t:
            t.extractall(dest, filter="tar")
    elif nome.endswith(".tar.zst"):
        import zstandard
        with open(archivio, "rb") as f:
            dati = zstandard.ZstdDecompressor().stream_reader(f)
            with tarfile.open(fileobj=dati, mode="r|") as t:
                t.extractall(dest, filter="tar")
    else:
        raise ErroreIA(f"Archivio sconosciuto: {nome}")
    exe = next((p for p in dest.rglob(_nome_exe()) if p.is_file()), None)
    if not exe:
        raise ErroreIA("Nell'archivio di Ollama non c'è il programma ollama.")
    if os.name != "nt":
        exe.chmod(0o755)
    return exe


def scarica_ollama(avanzamento: Avanzamento, annullato: Callable[[], bool]) -> Path:
    """Scarica ed estrae Ollama portatile (circa 1-2 GB con le librerie per la GPU)."""
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(RELEASE_OLLAMA, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        rel = r.json()
    a = asset_ollama(rel)
    dest = cartella_ollama()
    archivio = dest / "download" / a["name"]
    archivio.parent.mkdir(parents=True, exist_ok=True)
    tmp = archivio.with_suffix(archivio.suffix + ".parziale")
    with httpx.stream("GET", a["browser_download_url"], follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        totale = int(r.headers.get("content-length") or a.get("size") or 0)
        fatto = 0
        with open(tmp, "wb") as f:
            for blocco in r.iter_bytes(1 << 20):
                if annullato():
                    raise ErroreIA("Download annullato")
                f.write(blocco)
                fatto += len(blocco)
                if totale:
                    avanzamento(0.9 * fatto / totale, f"Ollama {rel.get('tag_name', '')}: "
                                                      f"{fatto / 1e6:.0f}/{totale / 1e6:.0f} MB")
    tmp.replace(archivio)
    avanzamento(0.92, "estraggo l'archivio")
    programma = dest / "programma"
    if programma.exists():
        shutil.rmtree(programma)
    exe = estrai(archivio, programma)
    archivio.unlink(missing_ok=True)
    return exe


# ---------------------------------------------------------------- client

def _json_da_testo(t: str) -> dict:
    """Il JSON dentro una risposta (toglie eventuali ```json e i ragionamenti <think>)."""
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    inizio, fine = t.find("{"), t.rfind("}")
    if inizio < 0 or fine < inizio:
        raise ErroreIA("L'IA non ha risposto con dati validi: riprova o scegli un modello più grande.")
    try:
        return json.loads(t[inizio:fine + 1])
    except json.JSONDecodeError as e:
        raise ErroreIA(f"L'IA ha risposto con JSON non valido ({e}): riprova o scegli un modello più grande.") from None


class ClientIA:
    def __init__(self, tipo: str, url: str, modello: str, chiave: str | None = None, timeout: float = 600):
        self.tipo = tipo
        self.url = url.rstrip("/")
        self.modello = modello
        self.chiave = chiave
        self._http = httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(timeout, connect=5),
                                       headers={"Authorization": f"Bearer {chiave}"} if chiave else {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._http.aclose()

    async def versione(self) -> str | None:
        try:
            if self.tipo == "ollama":
                r = await self._http.get("/api/version", timeout=3)
                r.raise_for_status()
                return r.json().get("version") or "?"
            r = await self._http.get("/v1/models", timeout=5)
            r.raise_for_status()
            return "compatibile OpenAI"
        except (httpx.HTTPError, ValueError):
            return None

    async def modelli(self) -> list[str]:
        if self.tipo == "ollama":
            r = await self._http.get("/api/tags", timeout=10)
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
        r = await self._http.get("/v1/models", timeout=10)
        r.raise_for_status()
        return sorted(m["id"] for m in r.json().get("data", []))

    async def scarica_modello(self, nome: str, avanzamento: Avanzamento, annullato: Callable[[], bool]):
        if self.tipo != "ollama":
            raise ErroreIA("I modelli si scaricano da Comic Studio solo con Ollama.")
        async with self._http.stream("POST", "/api/pull", json={"model": nome, "stream": True},
                                     timeout=httpx.Timeout(None, connect=5)) as r:
            if r.status_code >= 400:
                raise ErroreIA(f"Ollama non riesce a scaricare {nome}: {(await r.aread()).decode()[:300]}")
            async for riga in r.aiter_lines():
                if annullato():
                    raise ErroreIA("Download annullato")
                if not riga.strip():
                    continue
                d = json.loads(riga)
                if d.get("error"):
                    raise ErroreIA(f"Ollama: {d['error']}")
                stato = d.get("status", "")
                if d.get("total"):
                    fatto = d.get("completed", 0)
                    avanzamento(fatto / d["total"], f"{nome}: {fatto / 1e9:.1f}/{d['total'] / 1e9:.1f} GB")
                else:
                    avanzamento(-1, f"{nome}: {stato}")

    async def chat_json(self, sistema: str, utente: str, schema: dict, contesto: int = 12288,
                        temperatura: float = 0.2) -> dict:
        """Una risposta JSON che rispetta lo schema."""
        if self.tipo == "ollama":
            corpo = {"model": self.modello, "stream": False, "keep_alive": 0, "format": schema, "think": False,
                     "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": utente}],
                     "options": {"temperature": temperatura, "num_ctx": contesto}}
            r = await self._http.post("/api/chat", json=corpo)
            if r.status_code == 400 and "think" in r.text:          # modelli che non conoscono l'opzione
                corpo.pop("think")
                r = await self._http.post("/api/chat", json=corpo)
            if r.status_code == 404:
                raise ErroreIA(f"Il modello {self.modello} non è in Ollama: scaricalo da Sistema → IA locale.")
            if r.status_code >= 400:
                raise ErroreIA(f"Ollama ha risposto {r.status_code}: {r.text[:300]}")
            return _json_da_testo(r.json().get("message", {}).get("content", ""))
        istruzioni = (sistema + "\n\nRispondi SOLO con un oggetto JSON valido che rispetta questo JSON Schema:\n"
                      + json.dumps(schema, ensure_ascii=False))
        corpo = {"model": self.modello, "temperature": temperatura, "response_format": {"type": "json_object"},
                 "messages": [{"role": "system", "content": istruzioni}, {"role": "user", "content": utente}]}
        r = await self._http.post("/v1/chat/completions", json=corpo)
        if r.status_code == 400 and "response_format" in r.text:
            corpo.pop("response_format")
            r = await self._http.post("/v1/chat/completions", json=corpo)
        if r.status_code >= 400:
            raise ErroreIA(f"Il server dell'IA ha risposto {r.status_code}: {r.text[:300]}")
        try:
            testo = r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError):
            raise ErroreIA("Risposta del server dell'IA non riconosciuta.") from None
        return _json_da_testo(testo or "")


__all__ = ["ClientIA", "ErroreIA", "MODELLI_CONSIGLIATI", "StatoIA", "URL_OLLAMA", "asset_ollama", "estrai",
           "ollama_di_sistema", "ollama_portatile", "scarica_ollama"]
