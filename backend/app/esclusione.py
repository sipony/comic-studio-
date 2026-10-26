"""Staccare dei nodi da un workflow senza romperlo.

Come il «bypass» di ComfyUI, ma fatto da Comic Studio prima di inviare il workflow:

- ogni nodo che usava un'uscita di un nodo staccato viene ricollegato all'ingresso dello stesso tipo del nodo
  staccato (es. LoRA staccato: il KSampler prende il MODEL dal checkpoint, il CLIPTextEncode prende il CLIP);
  si preferisce l'ingresso nella stessa posizione dell'uscita, poi quello con lo stesso nome, poi il primo del tipo
  giusto (ControlNetApplyAdvanced: positive → positive, negative → negative); le catene di nodi staccati si
  attraversano tutte
- se un ingresso non si può ricollegare ma è facoltativo, viene tolto
- altrimenti il nodo che lo usa non può più funzionare e viene staccato anche lui, e così via a valle: chi usava
  le sue uscite viene ricollegato (es. riferimento staccato → l'IPAdapter perde l'immagine e viene staccato → il
  KSampler prende il modello che entrava nell'IPAdapter); un'anteprima del nodo staccato sparisce con lui.
  I nodi con un ruolo (campionatore principale, prompt positivo, immagine finale) non vengono mai staccati da soli:
  se la catena arriva a uno di loro, il workflow non funziona e lo si spiega
- quello che resta irrisolto viene spiegato all'utente

I tipi di uscite e ingressi arrivano dalle definizioni dei nodi di ComfyUI (/object_info); senza ComfyUI si usano
quelli dei nodi più comuni e il nome dell'ingresso (model → MODEL, clip → CLIP, image → IMAGE…).
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Iterable

TIPO_DA_NOME = {
    "model": "MODEL", "clip": "CLIP", "vae": "VAE", "image": "IMAGE", "images": "IMAGE", "pixels": "IMAGE",
    "samples": "LATENT", "latent": "LATENT", "latent_image": "LATENT", "conditioning": "CONDITIONING",
    "conditioning_1": "CONDITIONING", "conditioning_2": "CONDITIONING", "conditioning_to": "CONDITIONING",
    "conditioning_from": "CONDITIONING", "positive": "CONDITIONING", "negative": "CONDITIONING", "mask": "MASK",
    "control_net": "CONTROL_NET", "clip_vision": "CLIP_VISION", "clip_vision_output": "CLIP_VISION_OUTPUT",
    "ipadapter": "IPADAPTER", "upscale_model": "UPSCALE_MODEL", "sigmas": "SIGMAS", "sampler": "SAMPLER",
    "noise": "NOISE", "guider": "GUIDER", "style_model": "STYLE_MODEL",
}

# tipi delle uscite dei nodi più comuni, per quando ComfyUI non è collegato
USCITE_NOTE: dict[str, list[str]] = {
    "CheckpointLoaderSimple": ["MODEL", "CLIP", "VAE"], "CheckpointLoader": ["MODEL", "CLIP", "VAE"],
    "UNETLoader": ["MODEL"], "DualCLIPLoader": ["CLIP"], "CLIPLoader": ["CLIP"], "VAELoader": ["VAE"],
    "LoraLoader": ["MODEL", "CLIP"], "LoraLoaderModelOnly": ["MODEL"], "CLIPSetLastLayer": ["CLIP"],
    "CLIPTextEncode": ["CONDITIONING"], "CLIPTextEncodeSDXL": ["CONDITIONING"],
    "ConditioningCombine": ["CONDITIONING"], "ConditioningConcat": ["CONDITIONING"],
    "ConditioningSetArea": ["CONDITIONING"], "ConditioningSetAreaPercentage": ["CONDITIONING"],
    "ConditioningSetMask": ["CONDITIONING"], "ConditioningZeroOut": ["CONDITIONING"],
    "KSampler": ["LATENT"], "KSamplerAdvanced": ["LATENT"], "SamplerCustom": ["LATENT", "LATENT"],
    "EmptyLatentImage": ["LATENT"], "EmptySD3LatentImage": ["LATENT"], "LatentUpscale": ["LATENT"],
    "LatentUpscaleBy": ["LATENT"], "SetLatentNoiseMask": ["LATENT"], "RepeatLatentBatch": ["LATENT"],
    "VAEDecode": ["IMAGE"], "VAEDecodeTiled": ["IMAGE"], "VAEEncode": ["LATENT"], "VAEEncodeTiled": ["LATENT"],
    "LoadImage": ["IMAGE", "MASK"], "PrepImageForClipVision": ["IMAGE"], "ImageScale": ["IMAGE"], "ImageScaleBy": ["IMAGE"],
    "ImageScaleToTotalPixels": ["IMAGE"], "ImageInvert": ["IMAGE"], "ImageSharpen": ["IMAGE"], "ImageBlur": ["IMAGE"],
    "UpscaleModelLoader": ["UPSCALE_MODEL"], "ImageUpscaleWithModel": ["IMAGE"],
    "ControlNetLoader": ["CONTROL_NET"], "ControlNetApply": ["CONDITIONING"],
    "ControlNetApplyAdvanced": ["CONDITIONING", "CONDITIONING"], "ControlNetApplySD3": ["CONDITIONING", "CONDITIONING"],
    "CLIPVisionLoader": ["CLIP_VISION"], "CLIPVisionEncode": ["CLIP_VISION_OUTPUT"],
    "IPAdapterModelLoader": ["IPADAPTER"], "IPAdapterUnifiedLoader": ["MODEL", "IPADAPTER"],
    "IPAdapter": ["MODEL"], "IPAdapterAdvanced": ["MODEL"], "IPAdapterFaceID": ["MODEL"],
    "FreeU": ["MODEL"], "FreeU_V2": ["MODEL"], "ModelSamplingDiscrete": ["MODEL"], "ModelSamplingFlux": ["MODEL"],
    "PerturbedAttentionGuidance": ["MODEL"], "SelfAttentionGuidance": ["MODEL"], "RescaleCFG": ["MODEL"],
    "SaveImage": [], "PreviewImage": [],
}


@dataclass
class EsitoEsclusione:
    wf: dict
    richiesti: list[str] = field(default_factory=list)
    automatici: list[dict] = field(default_factory=list)      # {nodo, titolo, perche}
    collegamenti: list[dict] = field(default_factory=list)    # {nodo, titolo, ingresso, da, da_titolo, testo}
    problemi: list[str] = field(default_factory=list)

    @property
    def esclusi(self) -> list[str]:
        return self.richiesti + [a["nodo"] for a in self.automatici]

    def dict(self) -> dict:
        d = asdict(self)
        d.pop("wf")
        return d | {"esclusi": self.esclusi, "ok": not self.problemi}


def _link(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[1], int)


def titolo(wf: dict, nodo: str) -> str:
    n = wf.get(nodo, {})
    return f"#{nodo} {n.get('_meta', {}).get('title') or n.get('class_type', '?')}"


def _spec(info: dict | None, classe: str) -> dict | None:
    return (info or {}).get(classe)


def tipi_uscite(n: dict, info: dict | None) -> list[str] | None:
    s = _spec(info, n.get("class_type", ""))
    if s and isinstance(s.get("output"), list):
        return [t if isinstance(t, str) else "COMBO" for t in s["output"]]
    return USCITE_NOTE.get(n.get("class_type", ""))


def nomi_uscite(n: dict, info: dict | None) -> list[str]:
    s = _spec(info, n.get("class_type", ""))
    return [str(x).lower() for x in (s or {}).get("output_name") or []]


def tipo_ingresso(n: dict, nome: str, info: dict | None) -> str | None:
    s = _spec(info, n.get("class_type", ""))
    if s:
        for sezione in ("required", "optional"):
            spec = (s.get("input", {}).get(sezione) or {}).get(nome)
            if spec:
                return spec[0] if isinstance(spec[0], str) else "COMBO"
    return TIPO_DA_NOME.get(nome.lower())


def facoltativo(n: dict, nome: str, info: dict | None) -> bool:
    s = _spec(info, n.get("class_type", ""))
    return bool(s and nome in (s.get("input", {}).get("optional") or {}))


def consumatori(wf: dict, esclusi: set[str]) -> dict[str, list[tuple[str, str, int]]]:
    """nodo → [(chi lo usa, ingresso, uscita usata)] tra i nodi non staccati."""
    out: dict[str, list[tuple[str, str, int]]] = {}
    for c, n in wf.items():
        if c in esclusi:
            continue
        for nome, v in n.get("inputs", {}).items():
            if _link(v):
                out.setdefault(str(v[0]), []).append((c, nome, v[1]))
    return out


def passaggio(wf: dict, nodo: str, uscita: int, esclusi: set[str], info: dict | None,
              visti: frozenset = frozenset()) -> list | None:
    """Da dove prendere quello che l'uscita `uscita` del nodo staccato forniva: l'ingresso dello stesso tipo."""
    if nodo in visti or nodo not in wf:
        return None
    n = wf[nodo]
    tipi = tipi_uscite(n, info)
    if not tipi or uscita >= len(tipi):
        return None
    tipo = tipi[uscita]
    collegati = [(nome, v) for nome, v in n.get("inputs", {}).items()
                 if _link(v) and tipo_ingresso(n, nome, info) == tipo]
    if not collegati:
        return None
    tutti = [nome for nome, v in n.get("inputs", {}).items() if _link(v)]
    nomi = nomi_uscite(n, info)
    scelta = None
    if uscita < len(tutti) and any(nome == tutti[uscita] for nome, _ in collegati):
        scelta = next(v for nome, v in collegati if nome == tutti[uscita])
    elif uscita < len(nomi) and any(nome == nomi[uscita] for nome, _ in collegati):
        scelta = next(v for nome, v in collegati if nome == nomi[uscita])
    else:
        scelta = collegati[0][1]
    sorgente = str(scelta[0])
    if sorgente in esclusi:
        return passaggio(wf, sorgente, scelta[1], esclusi, info, visti | {nodo})
    return [sorgente, scelta[1]]


def escludi(wf: dict, nodi: Iterable[str], info: dict | None = None, protetti: Iterable[str] = ()) -> EsitoEsclusione:
    """Copia del workflow senza i nodi indicati, ricollegata dove si può (vedi la descrizione del modulo)."""
    w = copy.deepcopy(wf)
    richiesti = [n for n in dict.fromkeys(str(x) for x in nodi) if n in w]
    esito = EsitoEsclusione(wf=w, richiesti=richiesti)
    esclusi = set(richiesti)
    protetti = {str(p) for p in protetti if p}
    for p in sorted(protetti & esclusi):
        esito.problemi.append(f"{titolo(wf, p)} non si può staccare: Comic Studio lo usa (è uno dei nodi riconosciuti).")

    def stacca_anche(c: str, perche: str):
        esclusi.add(c)
        esito.automatici.append({"nodo": c, "titolo": titolo(wf, c), "perche": perche})

    for _ in range(len(w) + 1):
        irrisolti: list[str] = []
        cambiato = False
        for c in list(w):
            if c in esclusi:
                continue
            for nome, v in list(w[c].get("inputs", {}).items()):
                if not (_link(v) and str(v[0]) in esclusi):
                    continue
                da = passaggio(w, str(v[0]), v[1], esclusi, info)
                if da:
                    w[c]["inputs"][nome] = da
                    esito.collegamenti.append({"nodo": c, "titolo": titolo(wf, c), "ingresso": nome, "da": da[0],
                                               "da_titolo": titolo(wf, da[0])})
                    continue
                if facoltativo(w[c], nome, info):
                    del w[c]["inputs"][nome]
                    esito.collegamenti.append({"nodo": c, "titolo": titolo(wf, c), "ingresso": nome, "da": None,
                                               "da_titolo": None})
                    continue
                if c not in protetti:
                    # il nodo ha perso un ingresso indispensabile: lo si stacca a sua volta e chi lo usa
                    # viene ricollegato al passo successivo (o staccato, fino a un nodo che non si può toccare)
                    usati = consumatori(w, esclusi).get(c, [])
                    sorgente = titolo(wf, str(v[0]))
                    if not usati:
                        perche = f"usava solo {sorgente}"
                    elif all(passaggio(w, c, u, esclusi | {c}, info) for _, _, u in usati):
                        perche = f"senza {sorgente} non serve: lascia passare il resto"
                    else:
                        perche = f"senza {sorgente} non può funzionare"
                    stacca_anche(c, perche)
                    cambiato = True
                    break
                tipo = (tipi_uscite(w[str(v[0])], info) or [None] * (v[1] + 1))[v[1]] if str(v[0]) in w else None
                irrisolti.append(f"{titolo(wf, c)} ha bisogno di «{nome}»{f' ({tipo})' if tipo else ''} da "
                                 f"{titolo(wf, str(v[0]))}, e non c'è niente dello stesso tipo da far passare.")
            if cambiato:
                break
        if not cambiato:
            esito.problemi += irrisolti
            break
    # i collegamenti rifatti su nodi poi staccati non contano
    esito.collegamenti = [x for x in esito.collegamenti if x["nodo"] not in esclusi]
    for x in esito.collegamenti:
        x["testo"] = (f"{x['titolo']} · {x['ingresso']} ← {x['da_titolo']}" if x["da"]
                      else f"{x['titolo']} · {x['ingresso']} tolto (facoltativo)")
    for n in esclusi:
        w.pop(n, None)
    return esito


__all__ = ["EsitoEsclusione", "escludi", "passaggio"]
