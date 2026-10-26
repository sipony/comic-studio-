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


# ---------------------------------------------------------------- confronto di due workflow

def _percorsi(wf: dict) -> dict[str, str]:
    """Per ogni nodo, il percorso più corto (per nomi degli ingressi) dal nodo che salva: identifica il «ruolo» del
    nodo indipendentemente dai numeri. Es. «SaveImage.images ← VAEDecode.samples ← KSampler.positive ←
    CLIPTextEncode» è il prompt positivo in qualunque workflow."""
    from collections import deque
    pozzi = [k for k, n in wf.items() if n.get("class_type") in ("SaveImage", "PreviewImage")] or \
        [k for k in wf if not any(_link(v) and str(v[0]) == k for n in wf.values() for v in n.get("inputs", {}).values())]
    out: dict[str, str] = {}
    coda = deque((k, wf[k].get("class_type", "?")) for k in sorted(pozzi))
    while coda:
        k, percorso = coda.popleft()
        if k in out:
            continue
        out[k] = percorso
        for nome in sorted(wf[k].get("inputs", {})):
            v = wf[k]["inputs"][nome]
            if _link(v) and str(v[0]) in wf and str(v[0]) not in out:
                coda.append((str(v[0]), f"{percorso}.{nome} ← {wf[str(v[0])].get('class_type', '?')}"))
    for k, n in wf.items():                              # nodi staccati da tutto
        out.setdefault(k, f"staccato ← {n.get('class_type', '?')}")
    return out


def _tag(t: str) -> list[str]:
    return [x.strip() for x in str(t).split(",") if x.strip()]


def abbina(a: dict, b: dict) -> list[tuple[str | None, str | None]]:
    """Coppie di nodi (a, b) con lo stesso ruolo: prima per percorso dal salvataggio, poi per classe se è unica."""
    pa, pb = _percorsi(a), _percorsi(b)
    comuni = {n.get("class_type") for n in a.values()} & {n.get("class_type") for n in b.values()}

    def ridotto(percorso: str) -> str:
        """Il percorso senza i nodi che ci sono solo in uno dei due (IPAdapter, ControlNet…): la LoRA resta «quella che
        arriva al modello del campionatore» anche se nel mezzo c'è un IPAdapter."""
        pezzi, tenuti = percorso.split(" ← "), []
        for x in pezzi[:-1]:
            classe, _, ingresso = x.partition(".")
            if classe in comuni:
                tenuti.append(x)
            elif tenuti:          # conta l'ingresso del nodo tolto: ControlNet.positive → è il prompt positivo
                tenuti[-1] = tenuti[-1].split(".")[0] + "." + ingresso
        return " ← ".join(tenuti + pezzi[-1:])

    coppie, usati_a, usati_b = [], set(), set()
    for chiave in (lambda x: x, ridotto):
        per_b: dict[str, list[str]] = {}
        for k in sorted(b, key=lambda x: (len(x), x)):
            if k not in usati_b:
                per_b.setdefault(chiave(pb[k]), []).append(k)
        for k in sorted(a, key=lambda x: (len(x), x)):
            if k in usati_a:
                continue
            cand = [x for x in per_b.get(chiave(pa[k]), []) if x not in usati_b]
            if cand:
                coppie.append((k, cand[0]))
                usati_a.add(k)
                usati_b.add(cand[0])
    soli_a = [k for k in a if k not in usati_a]
    for k in list(soli_a):
        classe = a[k].get("class_type")
        cand = [x for x in b if x not in usati_b and b[x].get("class_type") == classe]
        if len(cand) == 1 and sum(1 for x in soli_a if a[x].get("class_type") == classe) == 1:
            coppie.append((k, cand[0]))
            usati_b.add(cand[0])
            soli_a.remove(k)
    return coppie + [(k, None) for k in soli_a] + [(None, k) for k in b if k not in usati_b]


def _classi_a_monte(wf: dict, k: str) -> set[str]:
    visti, pila = set(), [k]
    while pila:
        x = pila.pop()
        if x in visti or x not in wf:
            continue
        visti.add(x)
        pila += [str(v[0]) for v in wf[x].get("inputs", {}).values() if _link(v)]
    return {wf[x].get("class_type") for x in visti if x != k}


def confronta(a: dict, b: dict, nome_a: str = "A", nome_b: str = "B", ignora: tuple[str, ...] = ()) -> dict:
    """Le differenze tra due workflow, nodo per nodo: valori diversi (i testi anche tag per tag), nodi solo in uno dei
    due, collegamenti diversi. `ignora`: ingressi che si sa che cambiano (es. seed, filename_prefix)."""
    righe: list[dict] = []
    classi_a = {n.get("class_type") for n in a.values()}
    evid_a: dict[str, list[str]] = {}
    evid_b: dict[str, list[str]] = {}
    for ka, kb in abbina(a, b):
        na, nb = a.get(ka) if ka else None, b.get(kb) if kb else None
        classe = (na or nb).get("class_type", "?")
        titolo = ((na or nb).get("_meta") or {}).get("title") or classe
        if na is None or nb is None:
            dove = nome_b if nb else nome_a
            righe.append({"tipo": "solo_b" if nb else "solo_a", "nodo_a": ka, "nodo_b": kb, "classe": classe,
                          "titolo": titolo, "campo": None, "a": None, "b": None,
                          "testo": f"{titolo} ({classe}) c'è solo in {dove}"})
            (evid_b if nb else evid_a).setdefault(kb or ka, []).append("*")
            continue
        ia, ib = na.get("inputs", {}), nb.get("inputs", {})
        for campo in list(dict.fromkeys([*ia, *ib])):
            va, vb = ia.get(campo), ib.get(campo)
            if _link(va) or _link(vb):
                ca = a.get(str(va[0]), {}).get("class_type") if _link(va) else None
                cb = b.get(str(vb[0]), {}).get("class_type") if _link(vb) else None
                if ca != cb and cb and cb not in classi_a and ca and ca in _classi_a_monte(b, str(vb[0])):
                    righe.append({"tipo": "passa_per", "nodo_a": ka, "nodo_b": kb, "classe": classe, "titolo": titolo,
                                  "campo": campo, "a": ca, "b": cb,
                                  "testo": f"{titolo} · {campo}: in {nome_b} passa prima per {cb}, poi arriva da {ca} "
                                           f"come in {nome_a}"})
                    evid_b.setdefault(kb, []).append(campo)
                elif ca != cb:
                    righe.append({"tipo": "collegamento", "nodo_a": ka, "nodo_b": kb, "classe": classe, "titolo": titolo,
                                  "campo": campo, "a": ca, "b": cb,
                                  "testo": f"{titolo} · {campo}: in {nome_a} arriva da {ca or 'niente'}, in {nome_b} "
                                           f"da {cb or 'niente'}"})
                    evid_a.setdefault(ka, []).append(campo)
                    evid_b.setdefault(kb, []).append(campo)
                continue
            if va == vb or campo in ignora:
                continue
            riga = {"tipo": "valore", "nodo_a": ka, "nodo_b": kb, "classe": classe, "titolo": titolo, "campo": campo,
                    "a": va, "b": vb, "testo": f"{titolo} · {campo}: {nome_a} {va!r}, {nome_b} {vb!r}"}
            if isinstance(va, str) and isinstance(vb, str) and ("," in va or "," in vb):
                ta, tb = _tag(va), _tag(vb)
                sa, sb = {x.lower() for x in ta}, {x.lower() for x in tb}
                riga["solo_a"] = [x for x in ta if x.lower() not in sb]
                riga["solo_b"] = [x for x in tb if x.lower() not in sa]
                riga["testo"] = (f"{titolo} · {campo}: " + "; ".join(x for x in (
                    f"solo in {nome_a}: {', '.join(riga['solo_a'])}" if riga["solo_a"] else "",
                    f"solo in {nome_b}: {', '.join(riga['solo_b'])}" if riga["solo_b"] else "",
                    "stessi tag in un altro ordine" if not riga["solo_a"] and not riga["solo_b"] else "") if x))
            righe.append(riga)
            evid_a.setdefault(ka, []).append(campo)
            evid_b.setdefault(kb, []).append(campo)
    ordine = {"solo_a": 0, "solo_b": 1, "collegamento": 2, "passa_per": 3, "valore": 4}
    righe.sort(key=lambda r: ordine[r["tipo"]])
    return {"righe": righe, "evidenzia_a": evid_a, "evidenzia_b": evid_b, "uguali": not righe}


__all__ = ["USCITE_NOTE", "abbina", "confronta", "descrivi", "firma", "riassunto"]
