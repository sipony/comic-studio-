"""Il dataset usa lo stesso prompt e lo stesso workflow della proposta da cui è nato il personaggio?

La regola (vedi `proposte.modello_dataset`): il dataset deve generare con il workflow delle proposte, con in più solo
l'immagine di riferimento (IPAdapter), e con il prompt delle proposte, con la sola differenza della parte che descrive
inquadratura, sguardo, espressione, posa e sfondo, che nel dataset cambia a ogni immagine. Qui si verifica:

- prompt: le parti fisse (tutto tranne quella variabile) della proposta scelta e del dataset, tag per tag e nello
  stesso ordine; il prompt della proposta è sempre salvato, anche nelle proposte delle versioni vecchie
- negativo: quello delle proposte (con i tag negativi di qualità del checkpoint) e quello del dataset, tag per tag
- workflow: il workflow delle proposte ricostruito dalla ricetta e quello del dataset (libreria + modifiche del
  personaggio, senza nodi staccati): stessi nodi con gli stessi valori, stesse catene (il modello che arriva al
  campionatore passa per gli stessi nodi, il CLIP dei prompt anche), nodi in più solo quelli del riferimento
  (IPAdapter) e il riferimento davvero collegato al modello
"""
from __future__ import annotations

import random
import re

from .dataset import ConfigDataset, componi, crea_variante, modello_positivo, tag_qualita, valori_prompt
from .esclusione import _link
from .modelinfo import TAG_QUALITA, famiglia_da_nome
from .proposte import BASE, NEGATIVO, PARTE_VARIABILE, TAG_INQUADRATURA, ConfigProposte, Proposta, pulisci
from .proposte import workflow as workflow_proposte

CAMPIONATORI = ("KSampler", "KSamplerAdvanced")
# nodi che il dataset può avere in più delle proposte: quelli che portano l'immagine di riferimento
NODI_RIFERIMENTO = {"IPAdapterModelLoader", "CLIPVisionLoader", "LoadImage", "PrepImageForClipVision",
                    "IPAdapterAdvanced", "IPAdapter", "IPAdapterUnifiedLoader", "CLIPVisionEncode", "IPAdapterFaceID"}
# valori da confrontare nei nodi che proposte e dataset hanno in comune
CONFRONTATI = ("ckpt_name", "lora_name", "strength_model", "strength_clip", "steps", "cfg", "sampler_name",
               "scheduler", "denoise")
VARIABILI_DATASET = ("variante", "inquadratura", "angolazione", "espressione", "posa", "sfondo")


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


def famiglia_da_prompt(prompt: str) -> str | None:
    """La famiglia del checkpoint dai tag di qualità all'inizio del prompt (per le proposte senza ricetta)."""
    n = [norm(t) for t in tag(prompt)]
    for fam, (pos, _) in sorted(TAG_QUALITA.items(), key=lambda x: -len(tag(x[1][0]))):
        q = [norm(t) for t in tag(pos)]
        if q and n[:len(q)] == q:
            return fam
    return None


def inquadratura_da_prompt(prompt: str) -> str:
    n = {norm(t) for t in tag(prompt)}
    adatte = [k for k, v in TAG_INQUADRATURA.items() if {norm(t) for t in tag(v)} <= n]
    return max(adatte, key=lambda k: len(tag(TAG_INQUADRATURA[k])), default="mezzo_busto")


def parti_fisse(tags: list[str]) -> list[str]:
    return [t for t in tags if norm(t) not in PARTE_VARIABILE]


def _confronta_liste(a: list[str], b: list[str]) -> dict:
    na, nb = [norm(x) for x in a], [norm(x) for x in b]
    mancano = [x for x, n in zip(a, na) if n not in nb]
    in_piu = [x for x, n in zip(b, nb) if n not in na]
    comuni_a = [n for n in na if n in nb]
    comuni_b = [n for n in nb if n in na]
    return {"mancano": mancano, "in_piu": in_piu, "ordine_ok": comuni_a == comuni_b,
            "uguale": not mancano and not in_piu and comuni_a == comuni_b}


# ---------------------------------------------------------------- workflow

def _a_monte(wf: dict, nodo: str, ingresso: str) -> list[str]:
    """Le classi dei nodi risalendo da un ingresso (model o clip) fino al primo nodo senza quell'ingresso."""
    classi, visti = [], set()
    v = wf.get(nodo, {}).get("inputs", {}).get(ingresso)
    while _link(v) and str(v[0]) in wf and str(v[0]) not in visti:
        k = str(v[0])
        visti.add(k)
        classi.append(wf[k].get("class_type", "?"))
        ing = wf[k].get("inputs", {})
        v = ing.get(ingresso) if ingresso in ing else ing.get("model" if ingresso == "model" else "clip")
    return classi


def effettivo(wf: dict, config: ConfigDataset) -> dict:
    """Il workflow del dataset come lo userà la prossima generazione: con le modifiche del personaggio."""
    import copy
    w = copy.deepcopy(wf)
    for nodo, valori in (config.modifiche or {}).items():
        if nodo in w:
            for k, v in valori.items():
                if not _link(w[nodo]["inputs"].get(k)):
                    w[nodo]["inputs"][k] = v
    return w


def confronta_workflow(ricetta: dict, wf: dict | None, config: ConfigDataset) -> dict:
    if not wf:
        return {"uguale": False, "riferimento": False, "differenze": ["Il dataset non ha ancora un workflow."]}
    cp = ConfigProposte(checkpoint=ricetta["checkpoint"], lora_stile=ricetta.get("lora_stile"),
                        forza_lora=ricetta.get("forza_lora", 0.8), passi=ricetta.get("passi", 28),
                        cfg=ricetta.get("cfg", 6.0), sampler=ricetta.get("sampler", "euler_ancestral"),
                        scheduler=ricetta.get("scheduler", "karras"))
    prop, _ = workflow_proposte(cp, "", "", 0, None)
    ds = effettivo(wf, config)
    diff = []
    if config.disattivati:
        diff.append(f"Nel dataset ci sono nodi staccati ({', '.join(config.disattivati)}): le proposte non li hanno.")
    per_classe_p: dict[str, list[dict]] = {}
    per_classe_d: dict[str, list[dict]] = {}
    for n in prop.values():
        per_classe_p.setdefault(n["class_type"], []).append(n)
    for k, n in ds.items():
        if k not in config.disattivati:
            per_classe_d.setdefault(n.get("class_type", "?"), []).append(n)
    for classe, nodi_p in per_classe_p.items():
        nodi_d = per_classe_d.get(classe, [])
        if classe in CAMPIONATORI and not nodi_d:
            nodi_d = [n for c in CAMPIONATORI for n in per_classe_d.get(c, [])]
        if len(nodi_d) < len(nodi_p):
            diff.append(f"Manca {classe}" + (f" (le proposte ne hanno {len(nodi_p)})" if len(nodi_p) > 1 else "") + ".")
            continue
        if len(nodi_d) > len(nodi_p) and classe not in ("CLIPTextEncode",):
            diff.append(f"{classe}: nel dataset ce ne sono {len(nodi_d)}, nelle proposte {len(nodi_p)}.")
        for a, b in zip(nodi_p, nodi_d):
            for c in CONFRONTATI:
                va, vb = a["inputs"].get(c), b.get("inputs", {}).get(c)
                if va is None or _link(va) or _link(vb):
                    continue
                uguali = (float(va) == float(vb)) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) \
                    else str(va) == str(vb)
                if not uguali:
                    diff.append(f"{classe} · {c}: proposte {va}, dataset {vb}.")
    for classe, nodi_d in per_classe_d.items():
        if classe not in per_classe_p and classe not in NODI_RIFERIMENTO and not (
                classe in CAMPIONATORI and any(c in per_classe_p for c in CAMPIONATORI)):
            diff.append(f"Nodo in più nel dataset: {classe}" + (f" ×{len(nodi_d)}" if len(nodi_d) > 1 else "") + ".")
    # catene: il modello che arriva al campionatore e il CLIP dei prompt passano per gli stessi nodi
    ks_p = next(k for k, n in prop.items() if n["class_type"] in CAMPIONATORI)
    ks_d = next((k for k, n in ds.items() if n.get("class_type") in CAMPIONATORI), None)
    riferimento = False
    if ks_d:
        catena_d = _a_monte(ds, ks_d, "model")
        riferimento = any(c.startswith("IPAdapter") for c in catena_d)
        if [c for c in catena_d if c not in NODI_RIFERIMENTO] != _a_monte(prop, ks_p, "model"):
            diff.append("Il modello arriva al campionatore per un'altra strada: proposte "
                        f"{' ← '.join(_a_monte(prop, ks_p, 'model'))}, dataset {' ← '.join(catena_d) or '—'}.")
        pos_d = ds.get(ks_d, {}).get("inputs", {}).get("positive")
        pos_p = prop[ks_p]["inputs"]["positive"]
        if _link(pos_d):
            cl_d = _a_monte(ds, str(pos_d[0]), "clip")
            cl_p = _a_monte(prop, str(pos_p[0]), "clip")
            if cl_d != cl_p:
                diff.append(f"Il CLIP del prompt arriva per un'altra strada: proposte {' ← '.join(cl_p)}, dataset "
                            f"{' ← '.join(cl_d) or '—'}.")
    if not riferimento:
        diff.append("Manca l'immagine di riferimento: nel dataset non c'è IPAdapter collegato al modello (installalo da "
                    "Sistema → Controllo, poi «Rendi il dataset identico alle proposte»).")
    return {"uguale": not diff, "riferimento": riferimento, "differenze": diff}


# ---------------------------------------------------------------- confronto completo

def confronta(proposta: Proposta, pers, config: ConfigDataset, wf: dict | None, checkpoint: str | None,
              lora: list[str]) -> dict:
    r = proposta.ricetta.model_dump() if proposta.ricetta else None
    famiglia_proposta = famiglia_da_nome(r["checkpoint"]) if r else famiglia_da_prompt(proposta.prompt)
    stile_proposta = tag_di_stile(proposta.prompt, pers.descrizione, pers.genere)
    q = tag_qualita(checkpoint, config)

    # prompt: parti fisse (il dataset senza le varianti)
    vuoti = {k: "" for k in VARIABILI_DATASET}
    fisso_dataset = componi(modello_positivo(config), valori_prompt(pers, vuoti, q, config.stile))
    fp, fd = parti_fisse(tag(proposta.prompt)), parti_fisse(tag(fisso_dataset))
    prompt = {"proposta": fp, "dataset": fd, **_confronta_liste(fp, fd)}
    rng, conteggio = random.Random(3), {}
    v = crea_variante(config.varianti, conteggio, rng)
    esempio = componi(modello_positivo(config), valori_prompt(pers, v, q, config.stile, config.aspetto))
    neg_dataset = componi(config.prompt_negativo, valori_prompt(pers, v, q, config.stile))
    mancanti = [t for t in stile_proposta if norm(t) not in {norm(x) for x in fd}]

    # negativo: quello delle proposte con i tag negativi di qualità del loro checkpoint
    q_prop = TAG_QUALITA.get(famiglia_proposta or "sdxl", TAG_QUALITA["sdxl"])
    neg_proposta = pulisci(((r or {}).get("negativo") or NEGATIVO).replace("{negativo_qualita}", q_prop[1]))
    negativo = {"proposta": neg_proposta, "dataset": neg_dataset,
                **_confronta_liste(tag(neg_proposta), tag(neg_dataset))}

    workflow = confronta_workflow(r, wf, config) if r else {
        "uguale": None, "riferimento": None,
        "differenze": ["Questa proposta è stata fatta prima della versione 0.16 e non ricorda il checkpoint: indicalo "
                       "qui sotto per poter confrontare (e allineare) il workflow."]}

    righe = []

    def riga(voce, proposte, dataset, uguale, nota=""):
        righe.append({"voce": voce, "proposte": proposte, "dataset": dataset, "uguale": uguale, "nota": nota})

    riga("Prompt (senza le varianti)", ", ".join(fp), ", ".join(fd), prompt["uguale"],
         "; ".join(x for x in (f"mancano: {', '.join(prompt['mancano'])}" if prompt["mancano"] else "",
                               f"in più: {', '.join(prompt['in_piu'])}" if prompt["in_piu"] else "",
                               "" if prompt["ordine_ok"] else "ordine diverso") if x))
    riga("Negativo", neg_proposta, neg_dataset, negativo["uguale"],
         "; ".join(x for x in (f"mancano: {', '.join(negativo['mancano'])}" if negativo["mancano"] else "",
                               f"in più: {', '.join(negativo['in_piu'])}" if negativo["in_piu"] else "",
                               "" if negativo["ordine_ok"] else "ordine diverso") if x))
    riga("Workflow", "Checkpoint → LoRA → Prompt → KSampler → VAE → Salva" if r else "non registrato",
         "uguale + immagine di riferimento" if workflow["uguale"] else (
             f"{len(workflow['differenze'])} differenze" if workflow["uguale"] is False else "da verificare"),
         workflow["uguale"], " ".join(workflow["differenze"]))
    riga("Checkpoint", r["checkpoint"] if r else f"non registrato ({famiglia_proposta or '?'} dai tag di qualità)",
         checkpoint or "—", (r["checkpoint"] == checkpoint) if r else None)
    if r:
        riga("LoRA di stile", f"{r['lora_stile']} ({r['forza_lora']})" if r.get("lora_stile") else "nessuna",
             ", ".join(lora) or "nessuna", (not r.get("lora_stile")) or r["lora_stile"] in lora)
    if config.aspetto.strip():
        riga("Aspetto dal riferimento", "nessuno (vestiti decisi dal seme)", config.aspetto, True,
             "Tag letti dal tagger sull'immagine di riferimento e aggiunti dopo i tratti: ogni immagine chiede gli stessi "
             "vestiti, capelli e accessori della proposta scelta. Non contano nel confronto del prompt.")
    if config.pose.attive:
        riga("Pose guidate", "nessuna (posa dal prompt)",
             f"ControlNet OpenPose, forza {config.pose.forza}, fino al {round(config.pose.fine * 100)}% dei passi", True,
             "In più rispetto alle proposte c'è solo lo scheletro della posa (aggiunto a ogni immagine): decide braccia, "
             "gambe e angolazione; aspetto, stile e prompt restano quelli delle proposte.")
    coerente = bool(prompt["uguale"] and negativo["uguale"] and workflow["uguale"])
    return {"proposta": {"file": proposta.file, "prompt": proposta.prompt, "ricetta": r},
            "famiglia_proposta": famiglia_proposta, "stile_proposta": stile_proposta, "mancanti": mancanti,
            "esempio_dataset": esempio, "prompt": prompt, "negativo": negativo, "workflow": workflow,
            "righe": righe, "coerente": coerente}


def ricetta_da_proposta_vecchia(proposta: Proposta, pers, checkpoint: str) -> dict:
    """La ricetta di una proposta fatta prima della 0.16: il checkpoint lo dice l'utente; stile e inquadratura si
    leggono dal prompt; campionamento e negativo erano fissi (28 passi, CFG 6, euler_ancestral karras)."""
    from .proposte import Ricetta
    fam_prompt, fam_ck = famiglia_da_prompt(proposta.prompt), famiglia_da_nome(checkpoint) or "sdxl"
    if fam_prompt and fam_prompt != fam_ck and TAG_QUALITA.get(fam_prompt) != TAG_QUALITA.get(fam_ck):
        raise ValueError(f"Il prompt della proposta ha i tag di qualità di {fam_prompt}, ma {checkpoint} è {fam_ck}: "
                         "scegli il checkpoint con cui l'hai creata.")
    return Ricetta(checkpoint=checkpoint, stile=", ".join(tag_di_stile(proposta.prompt, pers.descrizione, pers.genere)),
                   inquadratura=inquadratura_da_prompt(proposta.prompt)).model_dump()


__all__ = ["confronta", "confronta_workflow", "ricetta_da_proposta_vecchia", "tag_di_stile", "NEGATIVO"]
