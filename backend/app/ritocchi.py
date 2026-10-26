"""Impostazioni dei nodi cambiate dal grafo della console, salvate dove le usa la prossima generazione.

Il grafo mostra l'ultimo workflow che un lavoro ha mandato a ComfyUI: è una copia. Cambiare un valore lì ha senso solo
se finisce nella «sorgente» da cui Comic Studio ricostruisce il workflow la volta dopo:

  dataset   → `ConfigDataset.modifiche` del personaggio (le stesse di Dataset → Nodi e parametri); il workflow
              della libreria non cambia, e le modifiche valgono solo per quel personaggio
  proposte  → `Personaggio.scelte_proposte`: le scelte del pannello «Crea dal testo» (checkpoint, LoRA, passi, CFG,
              sampler, scheduler, forza delle varianti)

Tutto il resto si vede ma non si cambia, e ogni impostazione bloccata dice perché e dove si cambia: i valori che
Comic Studio scrive a ogni generazione (prompt, seme, dimensioni, immagine di riferimento, nome dei file), i nodi
aggiunti per una sola generazione, i lavori che non hanno una sorgente modificabile.

I valori si controllano come fa ComfyUI: tipo, minimo e massimo (da /object_info), elenchi (modelli, sampler…).
Senza ComfyUI collegato si usano i modelli sul disco e gli elenchi noti.
"""
from __future__ import annotations

import math
from typing import Any

from .esclusione import _link

SAMPLER_NOTI = ["euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp", "heun", "heunpp2", "dpm_2",
                "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_2s_ancestral_cfg_pp",
                "dpmpp_sde", "dpmpp_sde_gpu", "dpmpp_2m", "dpmpp_2m_cfg_pp", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu",
                "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ipndm", "ipndm_v", "deis", "res_multistep",
                "gradient_estimation", "er_sde", "seeds_2", "seeds_3", "ddim", "uni_pc", "uni_pc_bh2"]
SCHEDULER_NOTI = ["simple", "sgm_uniform", "karras", "exponential", "ddim_uniform", "beta", "normal",
                  "linear_quadratic", "kl_optimal"]
CARTELLE = {"ckpt_name": "checkpoints", "lora_name": "loras", "ipadapter_file": "ipadapter", "clip_name": "clip_vision",
            "vae_name": "vae", "control_net_name": "controlnet", "model_name": "upscale_models"}
CAMPIONATORI = ("KSampler", "KSamplerAdvanced", "SamplerCustom")

NON_MODIFICABILE = "Per questo tipo di lavoro le impostazioni si cambiano nella sua pagina, non dal grafo."


# ---------------------------------------------------------------- tipi e controlli dei valori

def _da_spec(d: list, valore) -> dict:
    tipo = d[0] if d else None
    opz = d[1] if len(d) > 1 and isinstance(d[1], dict) else {}
    if isinstance(tipo, list):
        return {"tipo": "COMBO", "opzioni": [str(x) for x in tipo]}
    if tipo == "COMBO":
        return {"tipo": "COMBO", "opzioni": [str(x) for x in opz.get("options") or []]}
    if tipo in ("INT", "FLOAT"):
        return {"tipo": tipo, "min": opz.get("min"), "max": opz.get("max"), "step": opz.get("step"),
                "default": opz.get("default")}
    if tipo == "STRING":
        return {"tipo": "STRING", "multiline": bool(opz.get("multiline"))}
    if tipo == "BOOLEAN":
        return {"tipo": "BOOLEAN"}
    return _da_valore("", valore)


def _da_valore(nome: str, valore) -> dict:
    if isinstance(valore, bool):
        return {"tipo": "BOOLEAN"}
    if isinstance(valore, int):
        return {"tipo": "INT", "min": None, "max": None, "step": None, "default": None}
    if isinstance(valore, float):
        return {"tipo": "FLOAT", "min": None, "max": None, "step": None, "default": None}
    return {"tipo": "STRING", "multiline": nome in ("text", "text_g", "text_l") or len(str(valore)) > 60}


def spec_ingresso(classe: str, nome: str, valore, info: dict | None, modelli: dict | None) -> dict:
    """Tipo e limiti di un ingresso: da ComfyUI se è collegato, altrimenti dagli elenchi noti e dal valore."""
    s = (info or {}).get(classe) or {}
    for sezione in ("required", "optional"):
        d = (s.get("input", {}).get(sezione) or {}).get(nome)
        if d:
            return _da_spec(d, valore)
    if nome in CARTELLE and modelli is not None:
        opzioni = list(modelli.get(CARTELLE[nome]) or [])
        return {"tipo": "COMBO", "opzioni": opzioni + ([str(valore)] if str(valore) not in opzioni else [])}
    if nome == "sampler_name":
        return {"tipo": "COMBO", "opzioni": SAMPLER_NOTI}
    if nome == "scheduler":
        return {"tipo": "COMBO", "opzioni": SCHEDULER_NOTI}
    return _da_valore(nome, valore)


def valida(valore: Any, spec: dict) -> tuple[Any, str | None]:
    """Il valore convertito al tipo giusto, oppure il motivo per cui non va."""
    t = spec.get("tipo")
    if t in ("INT", "FLOAT"):
        if isinstance(valore, bool):
            return None, "serve un numero"
        try:
            v = float(str(valore).replace(",", "."))
        except (TypeError, ValueError):
            return None, "serve un numero"
        if not math.isfinite(v):
            return None, "serve un numero"
        if t == "INT":
            if v != int(v):
                return None, "serve un numero intero"
            v = int(v)
        if spec.get("min") is not None and v < spec["min"]:
            return None, f"il minimo è {spec['min']}"
        if spec.get("max") is not None and v > spec["max"]:
            return None, f"il massimo è {spec['max']}"
        return v, None
    if t == "BOOLEAN":
        if isinstance(valore, bool):
            return valore, None
        return None, "serve sì o no"
    if t == "COMBO":
        v = str(valore)
        if spec.get("opzioni") and v not in spec["opzioni"]:
            return None, f"«{v}» non c'è tra le scelte possibili"
        return v, None
    if not isinstance(valore, str):
        return None, "serve un testo"
    return valore, None


# ---------------------------------------------------------------- sorgenti

def _controllati_dataset(ruoli, libera: bool, wf: dict) -> dict[tuple[str, str], str]:
    """Gli ingressi che Comic Studio scrive a ogni immagine del dataset (vedi workflows.applica)."""
    out: dict[tuple[str, str], str] = {}
    for nodo, campi, perche in (
        (ruoli.positivo, ("text", "text_g", "text_l"),
         "Il prompt lo scrive Comic Studio a ogni immagine: cambialo in Dataset → Prompt e varianti."),
        (ruoli.negativo, ("text", "text_g", "text_l"),
         "Il negativo viene da Dataset → Prompt e varianti (modello del prompt negativo)."),
        (ruoli.seme, ("seed", "noise_seed"), "Il seme cambia a ogni immagine: è quello che le rende diverse."),
        (ruoli.latente, ("width", "height", "batch_size"),
         "Le dimensioni vengono dall'inquadratura di ogni variante (Dataset → Prompt e varianti)."),
        (ruoli.riferimento, ("image",), "È l'immagine di riferimento del personaggio: cambiala nella pagina Personaggi."),
        (ruoli.salva, ("filename_prefix",), "Il nome dei file lo decide Comic Studio."),
    ):
        if nodo:
            for c in campi:
                out[(str(nodo), c)] = perche
    if libera:
        for k, n in wf.items():
            if n.get("class_type") in CAMPIONATORI or n.get("class_type") == "BasicScheduler":
                out[(k, "denoise")] = ("Con «pose dalle varianti» ogni immagine parte da zero (denoise 1): per usare la "
                                       "composizione del riferimento cambia «Composizione» nel dataset.")
    return out


MAPPA_PROPOSTE = {
    ("CheckpointLoaderSimple", "ckpt_name"): "checkpoint",
    ("LoraLoader", "lora_name"): "lora_stile",
    ("LoraLoader", "strength_model"): "forza_lora",
    ("KSampler", "steps"): "passi",
    ("KSampler", "cfg"): "cfg",
    ("KSampler", "sampler_name"): "sampler",
    ("KSampler", "scheduler"): "scheduler",
    ("KSampler", "denoise"): "forza_variante",
}
PERCHE_PROPOSTE = {
    "seed": "Ogni proposta ha un seme nuovo: è quello che le rende diverse.",
    "noise_seed": "Ogni proposta ha un seme nuovo: è quello che le rende diverse.",
    "width": "Le dimensioni vengono dall'inquadratura scelta nel pannello «Crea dal testo».",
    "height": "Le dimensioni vengono dall'inquadratura scelta nel pannello «Crea dal testo».",
    "batch_size": "Comic Studio genera una proposta alla volta.",
    "text": "Il prompt è fatto di tratti, stile e tag: cambiali nel pannello «Crea dal testo», che ne mostra l'anteprima.",
    "strength_clip": "Segue la forza della LoRA (strength_model).",
    "image": "È la proposta da cui nascono le varianti.",
    "filename_prefix": "Il nome dei file lo decide Comic Studio.",
}


def ricetta_base(app, pid: str, pers, wf: dict | None = None) -> dict:
    """Le scelte da cui partono le prossime proposte: quelle salvate dal grafo, altrimenti l'ultima proposta con la
    ricetta; per le proposte fatte prima della 0.16 (senza ricetta) i valori si leggono dal workflow inviato."""
    from .proposte import ArchivioProposte, Ricetta
    if pers.scelte_proposte:
        return dict(pers.scelte_proposte)
    ultima = next((p.ricetta for p in reversed(ArchivioProposte(app.progetti).elenco(pid, pers.id)) if p.ricetta),
                  None)
    if ultima:
        return ultima.model_dump()
    base = Ricetta(checkpoint="").model_dump()
    for n in (wf or {}).values():
        for (classe, ingresso), campo in MAPPA_PROPOSTE.items():
            v = n.get("inputs", {}).get(ingresso)
            if n.get("class_type") == classe and v is not None and not _link(v) and campo != "forza_variante":
                base[campo] = v
    return base


async def descrivi(app, lavoro, info: dict | None) -> dict:
    """Per ogni nodo e ingresso non collegato del workflow del lavoro: si può cambiare? con quali limiti? c'è già un
    valore salvato per le prossime generazioni?"""
    wf, ctx = lavoro.workflow or {}, lavoro.contesto_workflow or {}
    modelli = None
    try:
        modelli = await app.modelli()
    except Exception:  # noqa: BLE001 - senza elenchi dei modelli si controlla solo il tipo
        pass
    sorgente, bloccati, salvati, liberi = None, {}, {}, set()
    tutto_bloccato = NON_MODIFICABILE
    try:
        pers = next(p for p in app.progetti.leggi(ctx["progetto"]).personaggi if p.id == ctx["personaggio"]) \
            if ctx.get("progetto") and ctx.get("personaggio") else None
    except Exception:  # noqa: BLE001 - progetto o personaggio eliminati
        pers = None
    if ctx.get("tipo") == "dataset" and pers:
        from .dataset import ArchivioDataset
        a = ArchivioDataset(app.progetti)
        config = a.config(ctx["progetto"], pers.id)
        if config.workflow != ctx.get("workflow"):
            tutto_bloccato = ("Il dataset di questo personaggio ora usa un altro workflow: genera di nuovo e modifica il "
                              "grafo del lavoro nuovo.")
        else:
            voce, ruoli = a.ruoli_effettivi(ctx["progetto"], config)
            sorgente = {"tipo": "dataset", "personaggio": pers.nome,
                        "descrizione": f"Dataset di {pers.nome}: le modifiche si salvano nelle sue impostazioni "
                                       f"(Dataset → Nodi e parametri) e valgono dalla prossima generazione. Il workflow "
                                       f"«{voce.nome}» della libreria resta com'è."}
            bloccati = _controllati_dataset(ruoli, bool(ctx.get("libera")), voce.workflow)
            liberi = set(voce.workflow)
            salvati = config.modifiche
            tutto_bloccato = None
    elif ctx.get("tipo") == "proposte" and pers:
        sorgente = {"tipo": "proposte", "personaggio": pers.nome,
                    "descrizione": f"Proposte di {pers.nome}: le modifiche diventano le scelte del pannello «Crea dal "
                                   "testo» e valgono dalle prossime proposte (e per il dataset, con «Usa questa»)."}
        base = ricetta_base(app, ctx["progetto"], pers, wf)
        for k, n in wf.items():
            for (classe, ingresso), campo in MAPPA_PROPOSTE.items():
                if n.get("class_type") == classe and ingresso in n.get("inputs", {}) and pers.scelte_proposte \
                        and campo in pers.scelte_proposte:
                    salvati.setdefault(k, {})[ingresso] = base[campo]
        tutto_bloccato = None
    campi: dict[str, dict] = {}
    for k, n in wf.items():
        classe = n.get("class_type", "")
        for nome, v in n.get("inputs", {}).items():
            if _link(v):
                continue
            perche = tutto_bloccato
            if perche is None and sorgente["tipo"] == "dataset":
                perche = bloccati.get((k, nome)) or (None if k in liberi else
                                                     "Nodo aggiunto da Comic Studio solo per questa generazione.")
            elif perche is None:
                campo = MAPPA_PROPOSTE.get((classe, nome))
                if campo == "forza_variante" and not ctx.get("variante"):
                    perche = "Le proposte partono da zero (denoise 1): la forza si cambia nelle varianti."
                elif campo is None:
                    perche = PERCHE_PROPOSTE.get(nome, "Le proposte usano un workflow fisso: qui si cambiano "
                                                       "checkpoint, LoRA e campionamento.")
            voce = {"modificabile": perche is None, "perche": perche,
                    "spec": spec_ingresso(classe, nome, v, info, modelli)}
            if nome in (salvati.get(k) or {}):
                voce["salvato"] = salvati[k][nome]
            campi.setdefault(k, {})[nome] = voce
    return {"sorgente": sorgente, "campi": campi}


async def salva(app, lavoro, modifiche: dict[str, dict[str, Any]], info: dict | None) -> tuple[dict, list[dict]]:
    """Controlla tutte le modifiche (o tutte o nessuna) e le salva nella sorgente. `None` come valore toglie la
    modifica salvata (si torna al valore del workflow della libreria, o a quello dell'ultima proposta)."""
    d = await descrivi(app, lavoro, info)
    errori, buone = [], {}
    for nodo, valori in (modifiche or {}).items():
        for nome, valore in (valori or {}).items():
            campo = (d["campi"].get(str(nodo)) or {}).get(nome)
            if campo is None:
                errori.append({"nodo": nodo, "ingresso": nome, "errore": "questa impostazione non esiste nel workflow"})
                continue
            if not campo["modificabile"]:
                errori.append({"nodo": nodo, "ingresso": nome, "errore": campo["perche"]})
                continue
            if valore is None:
                buone.setdefault(str(nodo), {})[nome] = None
                continue
            v, errore = valida(valore, campo["spec"])
            if errore:
                errori.append({"nodo": nodo, "ingresso": nome, "errore": errore})
            else:
                buone.setdefault(str(nodo), {})[nome] = v
    if errori or not buone:
        return d, errori
    ctx = lavoro.contesto_workflow
    if d["sorgente"]["tipo"] == "dataset":
        from .dataset import ArchivioDataset
        a = ArchivioDataset(app.progetti)
        config = a.config(ctx["progetto"], ctx["personaggio"])
        originale = a.leggi_workflow(ctx["progetto"], config.workflow).workflow
        mod = {k: dict(v) for k, v in config.modifiche.items()}
        for nodo, valori in buone.items():
            for nome, v in valori.items():
                if v is None or originale.get(nodo, {}).get("inputs", {}).get(nome) == v:
                    (mod.get(nodo) or {}).pop(nome, None)
                else:
                    mod.setdefault(nodo, {})[nome] = v
        config.modifiche = {k: v for k, v in mod.items() if v}
        a.salva_config(ctx["progetto"], ctx["personaggio"], config)
        app.bus.pubblica({"tipo": "dataset", "progetto": ctx["progetto"], "personaggio": ctx["personaggio"],
                          "azione": "config"})
    else:
        from .projects import ModificaPersonaggio
        from .proposte import Ricetta
        pers = next(p for p in app.progetti.leggi(ctx["progetto"]).personaggi if p.id == ctx["personaggio"])
        base = ricetta_base(app, ctx["progetto"], pers, lavoro.workflow)
        ultima = ricetta_base(app, ctx["progetto"], pers.model_copy(update={"scelte_proposte": None}), lavoro.workflow)
        for nodo, valori in buone.items():
            classe = lavoro.workflow[nodo]["class_type"]
            for nome, v in valori.items():
                campo = MAPPA_PROPOSTE[(classe, nome)]
                base[campo] = ultima.get(campo) if v is None else v
        try:
            scelte = Ricetta(**base).model_dump()
        except ValueError as e:
            return d, [{"nodo": "", "ingresso": "", "errore": f"impostazioni non valide: {e}"}]
        app.progetti.modifica_personaggio(ctx["progetto"], ctx["personaggio"],
                                          ModificaPersonaggio(scelte_proposte=scelte))
        app.bus.pubblica({"tipo": "personaggi", "progetto": ctx["progetto"], "personaggio": ctx["personaggio"]})
    n = sum(len(v) for v in buone.values())
    app.bus.log(f"{d['sorgente']['descrizione'].split(':')[0]}: {n} impostazioni salvate dal grafo, valgono dalla "
                "prossima generazione", "ok", lavoro.id)
    return await descrivi(app, lavoro, info), []


__all__ = ["descrivi", "salva", "spec_ingresso", "valida"]
