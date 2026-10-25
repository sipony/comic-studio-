"""Workflow di ComfyUI: conversione dal formato dell'interfaccia al formato API, analisi dei nodi e
applicazione dei valori di una generazione (riferimento, prompt, seme, dimensioni, salvataggio).

Formato API:  {"3": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "seed": 5}, "_meta": {...}}}
Formato UI:   {"nodes": [...], "links": [...]} — quello salvato normalmente da ComfyUI.
"""
from __future__ import annotations

import copy
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

VALORI_CONTROLLO = {"fixed", "increment", "decrement", "randomize"}
NODI_SOLO_INTERFACCIA = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "Label (rgthree)", "Fast Groups Muter (rgthree)",
                         "Fast Groups Bypasser (rgthree)", "Bookmark (rgthree)"}
TIPI_WIDGET = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}

SAMPLER = {"KSampler": ("seed", "positive", "negative", "latent_image"),
           "KSamplerAdvanced": ("noise_seed", "positive", "negative", "latent_image"),
           "SamplerCustom": ("noise_seed", "positive", "negative", "latent_image")}
LATENTI = {"EmptyLatentImage", "EmptySD3LatentImage", "EmptyHunyuanLatentVideo", "EmptyLatentImagePresets"}
SALVATAGGIO = {"SaveImage", "Image Save", "SaveImageExtended"}
CARICA_IMMAGINE = {"LoadImage", "LoadImageMask", "Load Image (Inspire)"}
CAMPI_TESTO = ("text", "text_g", "text_l", "prompt", "positive", "negative", "string")


class ErroreWorkflow(Exception):
    pass


# ---------------------------------------------------------------- riconoscimento del formato

def formato(dati: Any) -> str:
    if isinstance(dati, dict) and isinstance(dati.get("nodes"), list):
        return "ui"
    if isinstance(dati, dict) and "prompt" in dati and isinstance(dati["prompt"], dict):
        return "api_avvolto"
    if isinstance(dati, dict) and dati and all(isinstance(v, dict) and "class_type" in v for v in dati.values()):
        return "api"
    return "sconosciuto"


def normalizza(dati: Any, object_info: dict | None) -> tuple[dict, list[str]]:
    """Restituisce (workflow API, avvisi). Il formato UI richiede le definizioni dei nodi di ComfyUI."""
    f = formato(dati)
    if f == "api":
        return {str(k): v for k, v in dati.items()}, []
    if f == "api_avvolto":
        return {str(k): v for k, v in dati["prompt"].items()}, []
    if f == "ui":
        if object_info is None:
            raise ErroreWorkflow("Questo workflow è salvato nel formato normale di ComfyUI: per convertirlo serve "
                                 "ComfyUI avviato. In alternativa esportalo da ComfyUI con «Export (API)».")
        return da_interfaccia(dati, object_info)
    raise ErroreWorkflow("Il file non sembra un workflow di ComfyUI (né formato normale né formato API).")


# ---------------------------------------------------------------- conversione UI -> API

def _link(l) -> tuple[int, int, int, int, int]:
    if isinstance(l, dict):
        return l["id"], l["origin_id"], l["origin_slot"], l["target_id"], l["target_slot"]
    return l[0], l[1], l[2], l[3], l[4]


def _spec_ingressi(info: dict) -> list[tuple[str, list]]:
    ing = info.get("input", {})
    ordine = info.get("input_order")
    out = []
    for sezione in ("required", "optional"):
        voci = ing.get(sezione, {}) or {}
        nomi = ordine.get(sezione, list(voci)) if isinstance(ordine, dict) else list(voci)
        for n in nomi:
            if n in voci:
                out.append((n, voci[n]))
    return out


def _e_widget(spec: list) -> bool:
    if not spec:
        return False
    tipo = spec[0]
    opzioni = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if opzioni.get("forceInput"):
        return False
    return isinstance(tipo, list) or tipo in TIPI_WIDGET


def da_interfaccia(ui: dict, object_info: dict) -> tuple[dict, list[str]]:
    avvisi: list[str] = []
    if ui.get("definitions", {}).get("subgraphs"):
        raise ErroreWorkflow("Il workflow contiene dei subgraph: esportalo da ComfyUI con «Export (API)».")

    nodi = {n["id"]: n for n in ui["nodes"]}
    collegamenti = {}
    for l in ui.get("links", []) or []:
        lid, da, slot_da, a, slot_a = _link(l)
        collegamenti[lid] = (da, slot_da, a, slot_a)

    mancanti = sorted({n["type"] for n in nodi.values()
                       if n["type"] not in object_info and n["type"] not in NODI_SOLO_INTERFACCIA
                       and n.get("mode", 0) not in (2, 4)})
    if mancanti:
        raise ErroreWorkflow("Il workflow usa nodi non installati in ComfyUI: " + ", ".join(mancanti) +
                             ". Installali (per esempio da ComfyUI-Manager) e riavvia ComfyUI.")

    def risolvi(nodo_id: int, slot: int, visti: frozenset = frozenset()) -> tuple[str, Any] | None:
        """Segue Reroute, nodi Primitive e nodi in bypass fino a un vero nodo o a un valore."""
        if nodo_id in visti or nodo_id not in nodi:
            return None
        visti = visti | {nodo_id}
        n = nodi[nodo_id]
        modo = n.get("mode", 0)
        if n["type"] == "Reroute":
            ing = (n.get("inputs") or [{}])[0].get("link")
            return _segui(ing, visti)
        if n["type"] == "PrimitiveNode":
            valori = n.get("widgets_values") or []
            return ("valore", valori[0] if valori else None)
        if modo == 2:     # nodo disattivato: niente
            return None
        if modo == 4:     # bypass: passa avanti l'ingresso dello stesso tipo
            uscite = n.get("outputs") or []
            tipo = uscite[slot]["type"] if slot < len(uscite) else None
            for ing in n.get("inputs") or []:
                if ing.get("link") is not None and ing.get("type") == tipo:
                    return _segui(ing["link"], visti)
            return None
        return ("nodo", [str(nodo_id), slot])

    def _segui(link_id, visti=frozenset()):
        if link_id is None or link_id not in collegamenti:
            return None
        da, slot_da, _, _ = collegamenti[link_id]
        return risolvi(da, slot_da, visti)

    api: dict[str, dict] = {}
    for nid, n in nodi.items():
        if n["type"] in NODI_SOLO_INTERFACCIA or n.get("mode", 0) in (2, 4):
            continue
        info = object_info[n["type"]]
        ingressi: dict[str, Any] = {}

        valori = n.get("widgets_values")
        if isinstance(valori, dict):          # alcuni custom node salvano i widget per nome
            for nome, spec in _spec_ingressi(info):
                if _e_widget(spec) and nome in valori:
                    ingressi[nome] = valori[nome]
        elif isinstance(valori, list):
            i = 0
            for nome, spec in _spec_ingressi(info):
                if not _e_widget(spec):
                    continue
                if i >= len(valori):
                    break
                ingressi[nome] = valori[i]
                i += 1
                opzioni = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                if spec[0] == "INT" and i < len(valori) and isinstance(valori[i], str) \
                        and valori[i] in VALORI_CONTROLLO:
                    i += 1                     # control_after_generate
                if opzioni.get("image_upload") and i < len(valori) and valori[i] in ("image", None):
                    i += 1

        for ing in n.get("inputs") or []:
            if ing.get("link") is None:
                continue
            r = _segui(ing["link"])
            nome = ing.get("widget", {}).get("name") if isinstance(ing.get("widget"), dict) else None
            nome = nome or ing["name"]
            if r is None:
                avvisi.append(f"Nodo {nid} ({n['type']}): l'ingresso «{nome}» non è collegato a niente di attivo.")
                continue
            ingressi[nome] = r[1]

        api[str(nid)] = {"class_type": n["type"], "inputs": ingressi,
                         "_meta": {"title": n.get("title") or n["type"]}}

    if not api:
        raise ErroreWorkflow("Il workflow non contiene nodi attivi.")
    return api, avvisi


# ---------------------------------------------------------------- analisi

@dataclass
class Ruoli:
    riferimento: str | None = None
    positivo: str | None = None
    negativo: str | None = None
    seme: str | None = None
    latente: str | None = None
    salva: str | None = None

    def dict(self):
        return asdict(self)


@dataclass
class Analisi:
    ruoli: Ruoli
    candidati: dict[str, list[str]]
    checkpoint: str | None = None
    lora: list[str] = field(default_factory=list)
    nodi: list[dict] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)

    def dict(self):
        d = asdict(self)
        d["ruoli"] = self.ruoli.dict()
        return d


def _sorgenti(wf: dict, nodo: str) -> list[str]:
    return [str(v[0]) for v in wf.get(nodo, {}).get("inputs", {}).values()
            if isinstance(v, list) and len(v) == 2 and str(v[0]) in wf]


def _a_monte(wf: dict, partenza: str) -> list[str]:
    """Nodi a monte di `partenza`, in ordine di distanza."""
    visti, coda, ordine = {partenza}, deque([partenza]), []
    while coda:
        n = coda.popleft()
        for s in _sorgenti(wf, n):
            if s not in visti:
                visti.add(s)
                ordine.append(s)
                coda.append(s)
    return ordine


def campo_testo(nodo: dict) -> str | None:
    for c in CAMPI_TESTO:
        if isinstance(nodo.get("inputs", {}).get(c), str):
            return c
    return None


def _testo_a_monte(wf: dict, sampler: str, ingresso: str) -> str | None:
    v = wf[sampler]["inputs"].get(ingresso)
    if not (isinstance(v, list) and str(v[0]) in wf):
        return None
    inizio = str(v[0])
    for n in [inizio] + _a_monte(wf, inizio):   # il nodo di testo più vicino al sampler
        if campo_testo(wf[n]):
            return n
    return None


def analizza(wf: dict) -> Analisi:
    per_classe: dict[str, list[str]] = {}
    for k, n in wf.items():
        per_classe.setdefault(n.get("class_type", "?"), []).append(k)
    ordina = lambda ids: sorted(ids, key=lambda x: (len(x), x))  # noqa: E731

    sampler = ordina([k for k, n in wf.items() if n.get("class_type") in SAMPLER])
    testi = ordina([k for k, n in wf.items() if campo_testo(n)])
    carica = ordina([k for k, n in wf.items() if n.get("class_type") in CARICA_IMMAGINE])
    latenti = ordina([k for k, n in wf.items() if n.get("class_type") in LATENTI])
    salva = ordina([k for k, n in wf.items() if n.get("class_type") in SALVATAGGIO])
    anteprime = ordina([k for k, n in wf.items() if n.get("class_type") == "PreviewImage"])

    r = Ruoli()
    avvisi: list[str] = []
    if sampler:
        # il sampler "principale" è quello con più nodi a monte (quello finale nei workflow a due passaggi)
        principale = max(sampler, key=lambda s: len(_a_monte(wf, s)))
        campo_seme, pos, neg, lat = SAMPLER[wf[principale]["class_type"]]
        primo = min(sampler, key=lambda s: len(_a_monte(wf, s)))
        r.seme = principale
        r.positivo = _testo_a_monte(wf, primo, pos) or _testo_a_monte(wf, principale, pos)
        r.negativo = _testo_a_monte(wf, primo, neg) or _testo_a_monte(wf, principale, neg)
        sorgente_lat = wf[primo]["inputs"].get(lat)
        if isinstance(sorgente_lat, list) and str(sorgente_lat[0]) in latenti:
            r.latente = str(sorgente_lat[0])
    else:
        avvisi.append("Nessun KSampler trovato: il seme non verrà cambiato tra un'immagine e l'altra.")
    if not r.positivo and testi:
        r.positivo = testi[0]
    if not r.negativo and len(testi) > 1:
        r.negativo = next((t for t in testi if t != r.positivo), None)
    if r.negativo == r.positivo:
        r.negativo = None
    r.latente = r.latente or (latenti[0] if latenti else None)

    if carica:
        # preferisce il LoadImage che finisce in un IPAdapter / CLIP Vision
        def verso_ipadapter(k):
            return any(k in _a_monte(wf, v) or k == v for v, n in wf.items()
                       if "ipadapter" in n["class_type"].lower() or "clipvision" in n["class_type"].lower())
        r.riferimento = next((k for k in carica if verso_ipadapter(k)), carica[0])
    else:
        avvisi.append("Nessun nodo LoadImage: il dataset sarà generato solo dal testo, senza immagine di riferimento.")

    r.salva = salva[-1] if salva else (anteprime[-1] if anteprime else None)
    if not r.salva:
        avvisi.append("Nessun nodo SaveImage o PreviewImage: aggiungine uno, altrimenti non arriva nessuna immagine.")
    if not r.positivo:
        avvisi.append("Nessun nodo di testo per il prompt positivo trovato.")

    ckpt = next((n["inputs"].get("ckpt_name") for n in wf.values()
                 if isinstance(n.get("inputs", {}).get("ckpt_name"), str)), None)
    lora = [n["inputs"]["lora_name"] for n in wf.values() if isinstance(n.get("inputs", {}).get("lora_name"), str)]
    nodi = [{"id": k, "classe": n.get("class_type"), "titolo": n.get("_meta", {}).get("title") or n.get("class_type"),
             "valori": {nome: v for nome, v in n.get("inputs", {}).items() if not isinstance(v, list)}}
            for k, n in sorted(wf.items(), key=lambda kv: (len(kv[0]), kv[0]))]
    return Analisi(ruoli=r, candidati={"riferimento": carica, "positivo": testi, "negativo": testi,
                                       "seme": sampler, "latente": latenti, "salva": salva + anteprime},
                   checkpoint=ckpt, lora=lora, nodi=nodi, avvisi=avvisi)


def controlla_ruoli(wf: dict, ruoli: Ruoli) -> list[str]:
    """Verifica che i nodi indicati esistano e siano del tipo giusto."""
    errori = []
    for nome, nodo in ruoli.dict().items():
        if nodo is None:
            continue
        if nodo not in wf:
            errori.append(f"il nodo {nodo} scelto per «{nome}» non esiste nel workflow")
            continue
        n = wf[nodo]
        if nome in ("positivo", "negativo") and not campo_testo(n):
            errori.append(f"il nodo {nodo} ({n['class_type']}) non ha un campo di testo")
        if nome == "seme" and not ({"seed", "noise_seed"} & set(n["inputs"])):
            errori.append(f"il nodo {nodo} ({n['class_type']}) non ha un seme")
        if nome == "latente" and not ({"width", "height"} <= set(n["inputs"])):
            errori.append(f"il nodo {nodo} ({n['class_type']}) non ha larghezza e altezza")
    return errori


# ---------------------------------------------------------------- applicazione

def applica(wf: dict, ruoli: Ruoli, *, riferimento: str | None = None, positivo: str | None = None,
            negativo: str | None = None, seme: int | None = None, dimensioni: tuple[int, int] | None = None,
            prefisso: str | None = None, modifiche: dict[str, dict[str, Any]] | None = None) -> dict:
    """Copia del workflow con i valori di una singola generazione."""
    w = copy.deepcopy(wf)
    for nodo, valori in (modifiche or {}).items():
        if nodo in w:
            for k, v in valori.items():
                if not isinstance(w[nodo]["inputs"].get(k), list):   # non tocca i collegamenti
                    w[nodo]["inputs"][k] = v

    def testo(nodo_id, valore):
        if nodo_id and valore is not None and nodo_id in w:
            n = w[nodo_id]["inputs"]
            campi = [c for c in ("text_g", "text_l") if isinstance(n.get(c), str)] or [campo_testo(w[nodo_id])]
            for c in campi:
                if c:
                    n[c] = valore

    testo(ruoli.positivo, positivo)
    testo(ruoli.negativo, negativo)
    if ruoli.riferimento and riferimento and ruoli.riferimento in w:
        w[ruoli.riferimento]["inputs"]["image"] = riferimento
    if ruoli.seme and seme is not None and ruoli.seme in w:
        for c in ("seed", "noise_seed"):
            if c in w[ruoli.seme]["inputs"] and not isinstance(w[ruoli.seme]["inputs"][c], list):
                w[ruoli.seme]["inputs"][c] = seme
    if ruoli.latente and dimensioni and ruoli.latente in w:
        n = w[ruoli.latente]["inputs"]
        if not isinstance(n.get("width"), list):
            n["width"] = dimensioni[0]
        if not isinstance(n.get("height"), list):
            n["height"] = dimensioni[1]
        if "batch_size" in n and not isinstance(n["batch_size"], list):
            n["batch_size"] = 1
    if ruoli.salva and prefisso and ruoli.salva in w and "filename_prefix" in w[ruoli.salva]["inputs"]:
        w[ruoli.salva]["inputs"]["filename_prefix"] = prefisso
    # niente _meta nel workflow inviato: ComfyUI lo accetta, ma è inutile
    return w


# ---------------------------------------------------------------- workflow integrato

def integrato(checkpoint: str, ipadapter: str, clip_vision: str, lora_stile: str | None = None,
              forza_stile: float = 0.6, peso_ipadapter: float = 0.7, fine_ipadapter: float = 0.8,
              passi: int = 30, cfg: float = 6.5, sampler: str = "euler_ancestral",
              scheduler: str = "karras") -> tuple[dict, Ruoli]:
    """Workflow SDXL con IPAdapter per generare un personaggio somigliante al riferimento."""
    wf: dict[str, dict] = {}

    def nodo(k, classe, titolo, **ing):
        wf[k] = {"class_type": classe, "inputs": ing, "_meta": {"title": titolo}}

    nodo("1", "CheckpointLoaderSimple", "Checkpoint", ckpt_name=checkpoint)
    modello, clip = ["1", 0], ["1", 1]
    if lora_stile:
        nodo("2", "LoraLoader", "LoRA di stile", model=modello, clip=clip, lora_name=lora_stile,
             strength_model=forza_stile, strength_clip=forza_stile)
        modello, clip = ["2", 0], ["2", 1]
    nodo("3", "IPAdapterModelLoader", "IPAdapter", ipadapter_file=ipadapter)
    nodo("4", "CLIPVisionLoader", "CLIP Vision", clip_name=clip_vision)
    nodo("5", "LoadImage", "Riferimento", image="riferimento.png")
    nodo("6", "PrepImageForClipVision", "Prepara riferimento", image=["5", 0], interpolation="LANCZOS",
         crop_position="top", sharpening=0.0)
    nodo("7", "IPAdapterAdvanced", "Somiglianza", model=modello, ipadapter=["3", 0], clip_vision=["4", 0],
         image=["6", 0], weight=peso_ipadapter, weight_type="linear", combine_embeds="concat", start_at=0.0,
         end_at=fine_ipadapter, embeds_scaling="V only")
    nodo("8", "CLIPTextEncode", "Prompt positivo", clip=clip, text="")
    nodo("9", "CLIPTextEncode", "Prompt negativo", clip=clip, text="")
    nodo("10", "EmptyLatentImage", "Dimensioni", width=832, height=1216, batch_size=1)
    nodo("11", "KSampler", "Sampler", model=["7", 0], positive=["8", 0], negative=["9", 0],
         latent_image=["10", 0], seed=0, steps=passi, cfg=cfg, sampler_name=sampler, scheduler=scheduler,
         denoise=1.0)
    nodo("12", "VAEDecode", "Decodifica", samples=["11", 0], vae=["1", 2])
    nodo("13", "SaveImage", "Salva", images=["12", 0], filename_prefix="comic_studio/dataset")
    return wf, Ruoli(riferimento="5", positivo="8", negativo="9", seme="11", latente="10", salva="13")


def per_invio(wf: dict) -> dict:
    """Toglie i campi che ComfyUI non usa."""
    return {k: {"class_type": v["class_type"], "inputs": v["inputs"]} for k, v in wf.items()}


def workflow_test_lora(checkpoint: str, lora: str, positivo: str, negativo: str, seme: int,
                       larghezza: int = 832, altezza: int = 1216, forza: float = 0.85, passi: int = 28,
                       cfg: float = 6.0, sampler: str = "euler_ancestral", scheduler: str = "karras") -> tuple[dict, str]:
    """Workflow minimo per provare un LoRA: restituisce (workflow, id del nodo SaveImage)."""
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "LoraLoader", "inputs": {"model": ["1", 0], "clip": ["1", 1], "lora_name": lora,
                                                     "strength_model": forza, "strength_clip": forza}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": positivo}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": negativo}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": larghezza, "height": altezza, "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["3", 0], "negative": ["4", 0],
                                                   "latent_image": ["5", 0], "seed": seme, "steps": passi, "cfg": cfg,
                                                   "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "comic_studio/test_lora"}},
    }
    return wf, "8"

