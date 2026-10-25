"""Catalogo dei modelli per l'IA locale (Ollama) e quanto ciascuno si adatta a questo computer.

- Elenco di partenza: famiglie adatte a leggere testi in italiano e rispondere con JSON preciso, con le
  dimensioni e le quantizzazioni più comuni; le dimensioni dei file sono stimate
- Aggiornamento online (un lavoro): per ogni famiglia chiede al registro di Ollama i tag disponibili
  (/v2/library/<famiglia>/tags/list, se non risponde legge la pagina dei tag su ollama.com) e dal manifest di
  ogni tag ricava la dimensione vera; il risultato resta in <cartella dati>/strumenti/catalogo_ia.json
- Modelli già scaricati: da Ollama (/api/tags) con dimensione, parametri e quantizzazione veri
- Valutazione: memoria che serve (file + contesto + margine) confrontata con la VRAM (memoria unificata sui
  Mac) e con la RAM; il punteggio premia i modelli più grandi e precisi che stanno tutti sulla GPU
"""
from __future__ import annotations

import asyncio
import json
import math
import platform
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import httpx
import psutil

from .settings import cartella_dati

REGISTRO = "https://registry.ollama.ai"
SITO = "https://ollama.com"
GB = 1e9
VALIDITA = 7 * 24 * 3600            # dopo una settimana l'elenco online va aggiornato
CONTESTO = 12288                    # contesto usato dalle domande di Comic Studio

# famiglia → descrizione, bonus di qualità (italiano, rispetto dello schema), dimensioni, formato dei tag
# quantizzati, quantizzazioni da proporre senza rete, quantizzazione del tag senza suffisso
FAMIGLIE: dict[str, dict] = {
    "qwen3": {"descrizione": "capisce bene l'italiano e i testi lunghi, segue lo schema con precisione",
              "qualita": 3.0, "dimensioni": ["0.6b", "1.7b", "4b", "8b", "14b", "30b-a3b", "32b"],
              "formato": "{d}-{q}", "quant": ["q4_K_M", "q8_0", "fp16"]},
    "gemma3": {"descrizione": "ottimo con l'italiano e le descrizioni lunghe",
               "qualita": 3.0, "dimensioni": ["1b", "4b", "12b", "27b"],
               "formato": "{d}-it-{q}", "quant": ["q4_K_M", "qat", "q8_0", "fp16"]},
    "mistral-small3.2": {"descrizione": "molto preciso, serve una scheda video grande",
                         "qualita": 3.0, "dimensioni": ["24b"],
                         "formato": "{d}-instruct-2506-{q}", "quant": ["q4_K_M", "q8_0", "fp16"]},
    "qwen2.5": {"descrizione": "generazione precedente di Qwen, buona con l'italiano",
                "qualita": 2.0, "dimensioni": ["0.5b", "1.5b", "3b", "7b", "14b", "32b"],
                "formato": "{d}-instruct-{q}", "quant": ["q4_K_M", "q5_K_M", "q6_K", "q8_0", "fp16"]},
    "llama3.1": {"descrizione": "buono, ma meno preciso in italiano",
                 "qualita": 1.0, "dimensioni": ["8b", "70b"],
                 "formato": "{d}-instruct-{q}", "quant": ["q4_K_M", "q5_K_M", "q8_0", "fp16"]},
    "llama3.2": {"descrizione": "piccolo e veloce, adatto solo a testi brevi",
                 "qualita": 0.5, "dimensioni": ["1b", "3b"],
                 "formato": "{d}-instruct-{q}", "quant": ["q4_K_M", "q8_0", "fp16"]},
    "mistral-nemo": {"descrizione": "contesto lungo, italiano discreto",
                     "qualita": 1.5, "dimensioni": ["12b"],
                     "formato": "{d}-instruct-2407-{q}", "quant": ["q4_K_M", "q5_K_M", "q8_0", "fp16"]},
    "phi4": {"descrizione": "ragiona bene, più debole in italiano",
             "qualita": 1.0, "dimensioni": ["14b"],
             "formato": "{d}-{q}", "quant": ["q4_K_M", "q8_0", "fp16"]},
}
QUANT_PREDEFINITA = "q4_K_M"

# bit per peso (con le parti non quantizzate) e quanto la quantizzazione cambia la qualità
BIT = {"q2_k": 3.0, "q3_k_s": 3.5, "q3_k_m": 3.9, "q3_k_l": 4.3, "q4_0": 4.55, "q4_1": 5.0, "q4_k_s": 4.6,
       "q4_k_m": 4.85, "q5_0": 5.5, "q5_1": 6.0, "q5_k_s": 5.55, "q5_k_m": 5.7, "q6_k": 6.6, "q8_0": 8.5,
       "qat": 4.55, "mxfp4": 4.25, "fp8": 8.0, "bf16": 16.0, "fp16": 16.0, "f16": 16.0, "f32": 32.0}
EFFETTO = {"q2": -3.0, "q3": -1.5, "q4_0": -0.3, "q4_1": -0.2, "q4_k_s": -0.2, "q4_k_m": 0.0, "qat": 0.1,
           "mxfp4": 0.0, "q5": 0.25, "q6": 0.4, "q8": 0.5, "fp8": 0.45, "bf16": 0.5, "fp16": 0.5, "f16": 0.5,
           "f32": 0.3}

_RE_TAG = re.compile(r"^(?P<d>\d+(?:\.\d+)?[bm](?:-a\d+(?:\.\d+)?b)?)(?:-(?P<resto>.+))?$", re.I)
_RE_QUANT = re.compile(r"(?:^|-)(q\d_[0-9a-z]+(?:_[a-z])?|qat|mxfp4|fp8|bf16|fp16|f16|f32)$", re.I)
_ESCLUSI = re.compile(r"(?:^|-)(text|base|pt|cloud|vision|embed)(?:-|$)", re.I)


# ---------------------------------------------------------------- tag e dimensioni

def parametri(dim: str) -> tuple[float, float | None]:
    """Miliardi di parametri (totali, attivi per i modelli MoE) da una dimensione come '8b' o '30b-a3b'."""
    m = re.match(r"^(\d+(?:\.\d+)?)([bm])(?:-a(\d+(?:\.\d+)?)b)?$", dim.lower())
    if not m:
        return 0.0, None
    n = float(m.group(1)) / (1000 if m.group(2) == "m" else 1)
    return n, float(m.group(3)) if m.group(3) else None


def leggi_tag(tag: str) -> tuple[str, str | None] | None:
    """(dimensione, quantizzazione o None se è il tag predefinito) per un tag di Ollama; None se non serve."""
    m = _RE_TAG.match(tag)
    if not m or _ESCLUSI.search(tag):
        return None
    resto = m.group("resto") or ""
    q = _RE_QUANT.search(resto)
    return m.group("d").lower(), (q.group(1) if q else None)


def bit_quant(q: str) -> float:
    return BIT.get(q.lower(), 4.85)


def effetto_quant(q: str) -> float:
    q = q.lower()
    if q in EFFETTO:
        return EFFETTO[q]
    return next((v for k, v in EFFETTO.items() if q.startswith(k)), 0.0)


def stima_byte(miliardi: float, q: str) -> int:
    return int(miliardi * GB * bit_quant(q) / 8)


def memoria_contesto(miliardi: float) -> float:
    """GB per il contesto (cache KV) con 12k token: stima prudente."""
    return min(0.8 + 0.08 * miliardi, 4.5)


def etichetta_quant(q: str) -> str:
    q = q.lower()
    return {"qat": "QAT (4 bit)", "mxfp4": "MXFP4 (4 bit)"}.get(q, q.upper().replace("_K_", "_K_"))


# ---------------------------------------------------------------- hardware

@dataclass
class Hardware:
    gpu: str | None = None
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    apple: bool = False

    @property
    def memoria_gpu(self) -> float:
        """GB che il modello può usare sulla GPU (ComfyUI viene scaricato prima delle domande)."""
        if self.apple:
            return self.ram_gb * 0.67
        return max(self.vram_gb - 0.5, 0.0)

    @property
    def memoria_ram(self) -> float:
        return max(self.ram_gb - 4.0, 0.0)

    def dict(self):
        return asdict(self) | {"memoria_gpu": round(self.memoria_gpu, 1), "memoria_ram": round(self.memoria_ram, 1)}


def leggi_hardware(dispositivi: list[dict] | None) -> Hardware:
    from .diagnostica import gpu_da_comfy, gpu_nvidia_smi
    ram = psutil.virtual_memory().total / GB
    apple = platform.system() == "Darwin" and platform.machine() == "arm64"
    gpu = [g for g in gpu_da_comfy(dispositivi or []) if g.get("tipo") not in ("cpu", "mps")]
    if not gpu and not apple:
        gpu = gpu_nvidia_smi()
    if gpu and gpu[0].get("vram_totale"):
        return Hardware(gpu=gpu[0].get("nome"), vram_gb=gpu[0]["vram_totale"] / GB, ram_gb=ram, apple=apple)
    return Hardware(gpu="Apple Silicon" if apple else None, ram_gb=ram, apple=apple)


# ---------------------------------------------------------------- valutazione

def valuta(miliardi: float, attivi: float | None, byte: int, q: str, qualita: float, hw: Hardware) -> dict:
    """Dove gira il modello su questo computer e quanto è consigliabile (punteggio più alto = meglio)."""
    gb = byte / GB
    serve = gb + memoria_contesto(miliardi) + 0.5
    gb_attivi = gb * (attivi / miliardi if attivi and miliardi else 1)     # pesi letti a ogni token
    # un MoE vale circa quanto un modello denso un po' più piccolo del totale
    efficaci = min(miliardi, 1.4 * math.sqrt(miliardi * attivi)) if attivi else miliardi
    punti = qualita + 2.2 * math.log2(max(efficaci, 0.5)) + effetto_quant(q)
    if efficaci < 2:
        punti -= 2.0                                     # i modelli minuscoli sbagliano spesso lo schema
    if hw.memoria_gpu and serve <= hw.memoria_gpu:
        dove, nota = "gpu", "tutto sulla GPU: veloce"
        if serve > 0.9 * hw.memoria_gpu:
            punti -= 0.5
            nota = "tutto sulla GPU, ma al limite della memoria"
    elif hw.memoria_gpu and serve <= hw.memoria_gpu + hw.memoria_ram:
        dove = "misto"
        nota = "in parte sulla CPU: più lento" if not attivi else "in parte sulla CPU, ma è un MoE: resta rapido"
        fuori = (serve - hw.memoria_gpu) / serve                 # quota che resta sulla CPU
        punti -= (1.5 + 4 * fuori) if attivi else (4.0 + 12 * fuori)
    elif not hw.memoria_gpu and serve <= hw.memoria_ram:
        dove, nota = "cpu", "solo sul processore: lento"
        punti -= 0.8 * gb_attivi
    else:
        dove, nota = "troppo", "troppo grande per questo computer"
        punti -= 100
    return {"gb": round(gb, 2), "memoria_gb": round(serve, 1), "dove": dove, "nota": nota,
            "punteggio": round(punti, 2)}


# ---------------------------------------------------------------- catalogo

@dataclass
class Variante:
    nome: str                       # nome completo per Ollama, es. qwen3:8b-q4_K_M
    quant: str
    byte: int
    stimata: bool = True            # dimensione stimata (senza rete) o letta dal registro
    alias: list[str] = field(default_factory=list)   # altri nomi dello stesso file (qwen3:8b)


def catalogo_offline() -> dict[str, dict[str, list[Variante]]]:
    out: dict[str, dict[str, list[Variante]]] = {}
    for fam, info in FAMIGLIE.items():
        out[fam] = {}
        for d in info["dimensioni"]:
            miliardi, _ = parametri(d)
            vs = []
            for q in info["quant"]:
                if q == "qat" and miliardi < 1.5:
                    continue
                v = Variante(f"{fam}:{info['formato'].format(d=d, q=q)}", q, stima_byte(miliardi, q))
                if q == QUANT_PREDEFINITA:
                    # il tag corto esiste sempre: senza rete si scarica quello
                    v.alias.append(v.nome)
                    v.nome = f"{fam}:{d}"
                vs.append(v)
            out[fam][d] = vs
    return out


def file_cache() -> Path:
    return cartella_dati() / "strumenti" / "catalogo_ia.json"


def leggi_cache() -> dict | None:
    try:
        return json.loads(file_cache().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def scrivi_cache(dati: dict):
    p = file_cache()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


async def tag_online(c: httpx.AsyncClient, fam: str) -> list[str]:
    """I tag di una famiglia: dal registro di Ollama, altrimenti dalla pagina dei tag sul sito."""
    try:
        r = await c.get(f"{REGISTRO}/v2/library/{fam}/tags/list")
        if r.status_code == 200 and isinstance(r.json().get("tags"), list):
            return [str(t) for t in r.json()["tags"]]
    except (httpx.HTTPError, ValueError):
        pass
    r = await c.get(f"{SITO}/library/{fam}/tags")
    if r.status_code == 404:
        raise LookupError(f"Ollama non ha un modello chiamato «{fam}».")
    r.raise_for_status()
    return sorted(set(re.findall(rf"{re.escape(fam)}:([A-Za-z0-9._\-]+)", r.text)))


async def manifest(c: httpx.AsyncClient, fam: str, tag: str) -> tuple[int, str] | None:
    """(byte da scaricare, impronta del file del modello) di un tag, dal manifest del registro."""
    try:
        r = await c.get(f"{REGISTRO}/v2/library/{fam}/manifests/{tag}",
                        headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"})
        if r.status_code != 200:
            return None
        strati = r.json().get("layers", [])
    except (httpx.HTTPError, ValueError):
        return None
    modello = next((s for s in strati if s.get("mediaType", "").endswith(".model")), None)
    return sum(int(s.get("size") or 0) for s in strati), (modello or {}).get("digest", "")


async def famiglia_online(c: httpx.AsyncClient, fam: str, sem: asyncio.Semaphore) -> dict[str, list[Variante]]:
    tags = await tag_online(c, fam)
    letti = [(t, leggi_tag(t)) for t in tags]
    letti = [(t, x) for t, x in letti if x][:150]

    async def uno(t):
        async with sem:
            return await manifest(c, fam, t)
    info = await asyncio.gather(*(uno(t) for t, _ in letti))
    per_dim: dict[str, dict[str, Variante]] = {}
    predefiniti: dict[str, list[tuple[str, str]]] = {}     # dimensione → [(nome, impronta)] senza quantizzazione
    impronte: dict[str, str] = {}
    for (t, (d, q)), m in zip(letti, info):
        if not m:
            continue
        byte, impronta = m
        nome = f"{fam}:{t}"
        if q is None:
            predefiniti.setdefault(d, []).append((nome, impronta))
            continue
        vs = per_dim.setdefault(d, {})
        chiave = q.lower()
        if chiave in vs:                                   # stesso file con un nome più lungo
            if len(nome) < len(vs[chiave].nome):
                vs[chiave].alias.append(vs[chiave].nome)
                vs[chiave].nome = nome
            else:
                vs[chiave].alias.append(nome)
            continue
        vs[chiave] = Variante(nome, q, byte, stimata=False)
        impronte[nome] = impronta
    # i tag senza quantizzazione (qwen3:8b) sono alias della variante con lo stesso file
    for d, nomi in predefiniti.items():
        vs = per_dim.setdefault(d, {})
        for nome, impronta in sorted(nomi, key=lambda x: len(x[0])):
            uguale = next((v for v in vs.values() if impronta and impronte.get(v.nome) == impronta), None)
            if uguale:
                uguale.alias.append(nome)
            elif not vs:
                b = next(m for (t, _), m in zip(letti, info) if m and f"{fam}:{t}" == nome)[0]
                vs["predefinita"] = Variante(nome, QUANT_PREDEFINITA, b, stimata=False)
    return {d: list(vs.values()) for d, vs in per_dim.items() if vs}


async def aggiorna_online(famiglie: list[str], avanza: Callable[[float, str], None],
                          annullato: Callable[[], bool]) -> dict:
    """Scarica l'elenco aggiornato per le famiglie date e lo unisce alla cache."""
    cache = leggi_cache() or {}
    dati = cache.get("famiglie", {})
    errori: dict[str, str] = {}
    sem = asyncio.Semaphore(12)
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8), follow_redirects=True,
                                 headers={"User-Agent": "ComicStudio"}) as c:
        for k, fam in enumerate(famiglie):
            if annullato():
                break
            avanza(k / max(len(famiglie), 1), f"elenco dei modelli: {fam}")
            try:
                vs = await famiglia_online(c, fam, sem)
                if vs:
                    dati[fam] = {d: [asdict(v) for v in lista] for d, lista in vs.items()}
                else:
                    errori[fam] = "nessuna versione adatta trovata"
            except (httpx.HTTPError, LookupError) as e:
                errori[fam] = str(e) or e.__class__.__name__
    if len(errori) < len(famiglie):
        cache = {"aggiornato": time.time(), "famiglie": dati,
                 "extra": sorted(set(cache.get("extra", [])) | {f for f in famiglie if f not in FAMIGLIE and
                                                                  f not in errori})}
        scrivi_cache(cache)
    return {"errori": errori, "aggiornate": [f for f in famiglie if f not in errori]}


def famiglia_e_tag(nome: str) -> tuple[str, str]:
    fam, _, tag = nome.partition(":")
    return fam.split("/")[-1], tag or "latest"


def costruisci(hw: Hardware, installati: list[dict], attuale: str | None) -> dict:
    """L'elenco completo, valutato per questo computer: una riga per famiglia e dimensione, con le varianti."""
    cache = leggi_cache() or {}
    online = cache.get("famiglie", {})
    base = catalogo_offline()
    nomi_inst = {m["name"]: m for m in installati}
    righe = []
    usati: set[str] = set()
    for fam in list(FAMIGLIE) + [f for f in cache.get("extra", []) if f not in FAMIGLIE]:
        info = FAMIGLIE.get(fam, {"descrizione": "aggiunto da te", "qualita": 1.0})
        dimensioni = online.get(fam) or {d: [asdict(v) for v in vs] for d, vs in base.get(fam, {}).items()}
        for d, vs in dimensioni.items():
            miliardi, attivi = parametri(d)
            if not miliardi:
                continue
            varianti = []
            for v in vs:
                nomi = [v["nome"], *v.get("alias", [])]
                inst = next((n for n in nomi if n in nomi_inst), None)
                byte = nomi_inst[inst]["size"] if inst and nomi_inst[inst].get("size") else v["byte"]
                usati.update(nomi)
                voto = valuta(miliardi, attivi, byte, v["quant"], info["qualita"], hw)
                if inst and voto["dove"] != "troppo":
                    voto["punteggio"] = round(voto["punteggio"] + 0.5, 2)     # già scaricato: niente attesa
                varianti.append({"nome": inst or v["nome"], "alias": [n for n in nomi if n != (inst or v["nome"])],
                                 "quant": etichetta_quant(v["quant"]), "stimata": v.get("stimata", True) and not inst,
                                 "installato": bool(inst), "attuale": attuale in nomi, **voto})
            varianti.sort(key=lambda x: (bit_quant(_q(x["quant"])), x["nome"]))
            migliore = max(varianti, key=lambda x: x["punteggio"])
            righe.append({"famiglia": fam, "dimensione": d.upper(), "parametri": miliardi, "attivi": attivi,
                          "descrizione": info["descrizione"], "varianti": varianti, "migliore": migliore["nome"],
                          "punteggio": migliore["punteggio"], "dove": migliore["dove"]})
    # modelli scaricati che non sono nel catalogo (scelti a mano)
    for nome, m in nomi_inst.items():
        if nome in usati:
            continue
        det = m.get("details") or {}
        miliardi = _miliardi(det.get("parameter_size")) or 7.0
        q = (det.get("quantization_level") or QUANT_PREDEFINITA)
        fam, tag = famiglia_e_tag(nome)
        info = FAMIGLIE.get(fam, {"descrizione": "già scaricato", "qualita": 1.0})
        v = {"nome": nome, "alias": [], "quant": etichetta_quant(q), "stimata": False, "installato": True,
             "attuale": nome == attuale, **valuta(miliardi, None, m.get("size") or stima_byte(miliardi, q), q,
                                                    info["qualita"], hw)}
        righe.append({"famiglia": fam, "dimensione": det.get("parameter_size") or tag.upper(), "parametri": miliardi,
                      "attivi": None, "descrizione": "già scaricato", "varianti": [v], "migliore": nome,
                      "punteggio": v["punteggio"], "dove": v["dove"]})
    righe.sort(key=lambda r: -r["punteggio"])
    adatte = [r for r in righe if r["dove"] != "troppo"]
    for k, r in enumerate(adatte[:3]):
        r["consigliato"] = True
        r["migliore_in_assoluto"] = k == 0
    aggiornato = cache.get("aggiornato")
    return {"hardware": hw.dict(), "aggiornato": aggiornato, "online": bool(online),
            "da_aggiornare": not aggiornato or time.time() - aggiornato > VALIDITA, "contesto": CONTESTO,
            "famiglie": list(FAMIGLIE) + [f for f in cache.get("extra", []) if f not in FAMIGLIE],
            "modelli": righe, "attuale": attuale}


def _q(etichetta: str) -> str:
    e = etichetta.lower()
    return {"qat (4 bit)": "qat", "mxfp4 (4 bit)": "mxfp4"}.get(e, e)


def _miliardi(testo: str | None) -> float:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([BM])", testo or "", re.I)
    if not m:
        return 0.0
    return float(m.group(1)) / (1000 if m.group(2).upper() == "M" else 1)


__all__ = ["FAMIGLIE", "Hardware", "aggiorna_online", "catalogo_offline", "costruisci", "leggi_hardware",
           "leggi_tag", "parametri", "valuta"]
