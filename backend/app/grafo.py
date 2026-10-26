"""Il workflow che un lavoro manda a ComfyUI, descritto per disegnarlo come in ComfyUI e per riassumerlo nei log.

Il formato API di ComfyUI ha solo i nodi e i loro ingressi (valori o collegamenti [nodo, uscita]): nomi e tipi delle
uscite e l'ordine degli ingressi vengono da /object_info quando ComfyUI è collegato, altrimenti dalle tabelle dei nodi
più comuni (le stesse usate per staccare i nodi).
"""
from __future__ import annotations

from pathlib import Path

from .esclusione import USCITE_NOTE, _link, tipi_uscite, tipo_ingresso


def _spec(info: dict | None, classe: str) -> dict:
    return (info or {}).get(classe) or {}


def _ordine_ingressi(n: dict, info: dict | None) -> list[str]:
    """Gli ingressi nell'ordine di ComfyUI (prima i collegamenti, poi i widget), poi quelli che conosce solo il
    workflow."""
    s = _spec(info, n.get("class_type", ""))
    ordine = []
    for sezione in ("required", "optional"):
        ordine += [k for k in (s.get("input", {}).get(sezione) or {}) if k in n.get("inputs", {})]
    return ordine + [k for k in n.get("inputs", {}) if k not in ordine]


def _ordine_topologico(wf: dict) -> list[str]:
    fatti: list[str] = []
    visti: set[str] = set()

    def visita(k: str, pila: set[str]):
        if k in visti or k in pila or k not in wf:
            return
        pila.add(k)
        for v in wf[k].get("inputs", {}).values():
            if _link(v):
                visita(str(v[0]), pila)
        pila.discard(k)
        visti.add(k)
        fatti.append(k)

    for k in sorted(wf, key=lambda x: (len(x), x)):
        visita(k, set())
    return fatti


def descrivi(wf: dict, info: dict | None = None) -> dict:
    """Nodi (titolo, ingressi con il tipo e il collegamento, widget con il valore, uscite) e collegamenti."""
    usate: dict[str, int] = {}
    for n in wf.values():
        for v in n.get("inputs", {}).values():
            if _link(v):
                usate[str(v[0])] = max(usate.get(str(v[0]), 0), v[1] + 1)
    nodi, collegamenti = [], []
    for k in _ordine_topologico(wf):
        n = wf[k]
        classe = n.get("class_type", "?")
        s = _spec(info, classe)
        tipi = tipi_uscite(n, info)
        nomi = [str(x) for x in s.get("output_name") or []]
        quante = max(len(tipi or []), usate.get(k, 0))
        uscite = []
        for i in range(quante):
            tipo = (tipi or [])[i] if tipi and i < len(tipi) else "*"
            uscite.append({"nome": nomi[i] if i < len(nomi) else tipo, "tipo": tipo})
        ingressi, widget = [], []
        for nome in _ordine_ingressi(n, info):
            v = n["inputs"][nome]
            if _link(v):
                da = str(v[0])
                tipo_da = (tipi_uscite(wf[da], info) or []) if da in wf else []
                tipo = tipo_ingresso(n, nome, info) or (tipo_da[v[1]] if v[1] < len(tipo_da) else "*")
                ingressi.append({"nome": nome, "tipo": tipo, "da": da, "uscita": v[1]})
                collegamenti.append({"da": da, "uscita": v[1], "a": k, "ingresso": nome, "tipo": tipo})
            else:
                widget.append({"nome": nome, "valore": v})
        nodi.append({"id": k, "classe": classe,
                     "titolo": n.get("_meta", {}).get("title") or s.get("display_name") or classe,
                     "ingressi": ingressi, "widget": widget, "uscite": uscite})
    return {"nodi": nodi, "collegamenti": collegamenti, "da_comfy": info is not None}


def _corto(v) -> str:
    s = Path(str(v)).stem if isinstance(v, str) and "." in str(v)[-14:] else str(v)
    return s if len(s) <= 40 else s[:37] + "…"


def riassunto(wf: dict) -> str:
    """Una riga per la console: i nodi in ordine, con i valori che contano (modelli, campionamento)."""
    parti = []
    for k in _ordine_topologico(wf):
        n = wf[k]
        c, i = n.get("class_type", "?"), n.get("inputs", {})
        if "ckpt_name" in i:
            parti.append(f"{c} {_corto(i['ckpt_name'])}")
        elif "lora_name" in i:
            parti.append(f"{c} {_corto(i['lora_name'])} {i.get('strength_model', '')}".rstrip())
        elif "ipadapter_file" in i or "clip_name" in i:
            parti.append(f"{c} {_corto(i.get('ipadapter_file') or i.get('clip_name'))}")
        elif "steps" in i and "cfg" in i:
            parti.append(f"{c} ({i['steps']} passi, CFG {i['cfg']}, {i.get('sampler_name', '')} "
                         f"{i.get('scheduler', '')}, denoise {i.get('denoise', 1)})".replace("  ", " "))
        elif "width" in i and "height" in i:
            parti.append(f"{c} {i['width']}×{i['height']}")
        else:
            parti.append(c)
    return f"{len(wf)} nodi: " + " → ".join(parti)


def firma(wf: dict) -> tuple:
    """Cambia quando cambia la struttura o un modello (non con prompt e seme, che cambiano a ogni immagine)."""
    chiavi = ("ckpt_name", "lora_name", "strength_model", "ipadapter_file", "clip_name", "steps", "cfg",
              "sampler_name", "scheduler")
    return tuple(sorted((k, n.get("class_type"), tuple((c, str(n.get("inputs", {}).get(c))) for c in chiavi
                                                       if c in n.get("inputs", {})))
                        for k, n in wf.items()))


__all__ = ["USCITE_NOTE", "descrivi", "firma", "riassunto"]
