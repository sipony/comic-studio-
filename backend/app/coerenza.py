"""Il dataset è coerente con la proposta da cui è nato il personaggio?

Confronta la proposta scelta come riferimento (il suo prompt è sempre salvato; la ricetta completa solo dalla
versione 0.16) con la configurazione del dataset e il suo workflow: checkpoint, LoRA, campionamento, negativo,
IPAdapter e soprattutto i tag di stile. I tag della proposta che non sono tratti, qualità, inquadratura o la base
«su sfondo bianco» sono le scelte di stile: se nel dataset mancano, il personaggio cambia aspetto.
"""
from __future__ import annotations

import random
import re

from .dataset import ConfigDataset, crea_variante, modello_positivo, tag_qualita, valori_prompt, componi
from .modelinfo import TAG_QUALITA
from .proposte import BASE, NEGATIVO, TAG_INQUADRATURA, Proposta

CAMPIONATORI = ("KSampler", "KSamplerAdvanced")


def tag(testo: str) -> list[str]:
    return [t.strip() for t in (testo or "").split(",") if t.strip()]


def norm(t: str) -> str:
    """Un tag confrontabile: minuscolo, senza peso «(tag:1.2)» e spazi doppi."""
    t = t.strip().lower()
    m = re.fullmatch(r"\((.+?)(:[\d.]+)?\)", t)
    if m and not t.endswith("(style)"):
        t = m.group(1)
    return re.sub(r"\s+", " ", t)


def tag_di_stile(prompt: str, descrizione: str, genere: str) -> list[str]:
    """I tag della proposta che non sono qualità, genere, base, inquadratura o tratti: lo stile scelto."""
    noti = {norm(x) for x in tag(BASE) + tag(descrizione) + [genere]}
    for q in TAG_QUALITA.values():
        noti |= {norm(x) for x in tag(q[0])}
    for v in TAG_INQUADRATURA.values():
        noti |= {norm(x) for x in tag(v)}
    return [t for t in tag(prompt) if norm(t) not in noti]


def _campionatore(wf: dict, modifiche: dict) -> dict:
    for k, n in sorted(wf.items(), key=lambda x: (len(x[0]), x[0])):
        if n.get("class_type") in CAMPIONATORI:
            return {**n.get("inputs", {}), **(modifiche.get(k) or {})}
    return {}


def _ipadapter(wf: dict, modifiche: dict) -> dict | None:
    for k, n in wf.items():
        if n.get("class_type", "").startswith("IPAdapter") and "weight" in n.get("inputs", {}):
            return {**n["inputs"], **(modifiche.get(k) or {})}
    return None


def confronta(proposta: Proposta, pers, config: ConfigDataset, wf: dict | None, checkpoint: str | None,
              lora: list[str]) -> dict:
    r = proposta.ricetta.model_dump() if proposta.ricetta else None
    stile_proposta = tag_di_stile(proposta.prompt, pers.descrizione, pers.genere)
    # i tag che il dataset usa davvero: tutte le varianti possibili non servono, bastano alcuni esempi + lo stile
    q = tag_qualita(checkpoint, config)
    rng, conteggio, nel_dataset = random.Random(3), {}, set()
    esempio = None
    for _ in range(8):
        v = crea_variante(config.varianti, conteggio, rng)
        p = componi(modello_positivo(config), valori_prompt(pers, v, q, config.stile))
        esempio = esempio or p
        nel_dataset |= {norm(t) for t in tag(p)}
    mancanti = [t for t in stile_proposta if norm(t) not in nel_dataset]

    righe = []

    def riga(voce, proposte, dataset, uguale, nota=""):
        righe.append({"voce": voce, "proposte": proposte, "dataset": dataset, "uguale": uguale, "nota": nota})

    non_registrato = "non registrato (proposta fatta prima della versione 0.16)"
    riga("Checkpoint", r["checkpoint"] if r else non_registrato, checkpoint or "—",
         (r["checkpoint"] == checkpoint) if r else None)
    if r:
        riga("LoRA di stile", f"{r['lora_stile']} ({r['forza_lora']})" if r.get("lora_stile") else "nessuna",
             ", ".join(lora) or "nessuna", (not r.get("lora_stile")) or r["lora_stile"] in lora)
    riga("Tag di stile", ", ".join(stile_proposta) or "nessuno", config.stile or "nessuno", not mancanti,
         "mancano: " + ", ".join(mancanti) if mancanti else "")
    ks = _campionatore(wf or {}, config.modifiche)
    if r and ks:
        for voce, a, b in (("Passi", r["passi"], ks.get("steps")), ("CFG", r["cfg"], ks.get("cfg")),
                           ("Sampler", r["sampler"], ks.get("sampler_name")),
                           ("Scheduler", r["scheduler"], ks.get("scheduler"))):
            uguale = (float(a) == float(b)) if isinstance(b, (int, float)) else a == b
            riga(voce, str(a), str(b), uguale, "" if uguale else "pesa poco, ma cambia un po' il tratto")
    if r and r.get("negativo"):
        riga("Negativo", r["negativo"], config.prompt_negativo,
             {norm(t) for t in tag(r["negativo"])} <= {norm(t) for t in tag(config.prompt_negativo)})
    ip = _ipadapter(wf or {}, config.modifiche)
    riga("IPAdapter sul riferimento", "—", f"sì, peso {ip.get('weight')}" if ip else "no",
         None if ip else False,
         "" if ip else "senza IPAdapter il volto dipende solo dai tratti scritti: somiglia poco")
    return {"proposta": {"file": proposta.file, "prompt": proposta.prompt, "ricetta": r},
            "stile_proposta": stile_proposta, "mancanti": mancanti, "esempio_dataset": esempio, "righe": righe,
            "coerente": not mancanti and all(x["uguale"] is not False for x in righe
                                             if x["voce"] in ("Checkpoint", "LoRA di stile", "Tag di stile"))}


__all__ = ["confronta", "tag_di_stile", "NEGATIVO"]
