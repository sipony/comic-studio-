"""Step 1 — Dataset: libreria dei workflow del progetto, configurazione per personaggio, generazione
delle immagini con ComfyUI, galleria con scelta manuale e selezione automatica per somiglianza.

File:
  <progetto>/workflows/<id>.json                  libreria dei workflow (formato API + ruoli)
  <progetto>/personaggi/<pid>/dataset/config.json configurazione del personaggio
  <progetto>/personaggi/<pid>/dataset/immagini.json   metadati e stato di ogni immagine
  <progetto>/personaggi/<pid>/dataset/generate/0001.png
  <progetto>/personaggi/<pid>/dataset/anteprime/0001.jpg
"""
from __future__ import annotations

import json
import random
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, Field

from .modelinfo import TAG_QUALITA, famiglia_da_nome
from .projects import Archivio, ErroreProgetto, Personaggio, Progetto, slug
from .workflows import Analisi, Ruoli, analizza, controlla_ruoli, integrato

StatoImmagine = Literal["tenuta", "scartata"] | None
_lock = threading.RLock()


# ---------------------------------------------------------------- modelli

class Inquadratura(BaseModel):
    nome: str
    testo: str
    larghezza: int = Field(ge=256, le=2048)
    altezza: int = Field(ge=256, le=2048)
    quota: float = Field(default=1.0, ge=0)
    con_posa: bool = True


class Varianti(BaseModel):
    inquadrature: list[Inquadratura]
    angolazioni: list[str]
    espressioni: list[str]
    pose: list[str]
    sfondi: list[str]


def varianti_predefinite() -> Varianti:
    return Varianti(
        inquadrature=[
            Inquadratura(nome="primo piano", testo="portrait, close-up, face focus", larghezza=1024, altezza=1024,
                         quota=0.25, con_posa=False),
            Inquadratura(nome="mezzo busto", testo="upper body", larghezza=1024, altezza=1024, quota=0.30),
            Inquadratura(nome="tre quarti", testo="cowboy shot", larghezza=832, altezza=1216, quota=0.20),
            Inquadratura(nome="figura intera", testo="full body", larghezza=832, altezza=1216, quota=0.25),
        ],
        angolazioni=["front view", "front view", "three-quarter view", "three-quarter view", "from side",
                     "from behind, looking back"],
        espressioni=["neutral expression", "smile", "serious", "angry", "surprised", "worried", "laughing",
                     "determined", "tired"],
        pose=["standing", "standing", "sitting on chair", "walking", "arms crossed", "pointing", "hands on hips",
              "holding a document", "leaning against wall", "running"],
        sfondi=["white background", "white background", "white background", "simple background",
                "indoors", "city street, outdoors", "night, street lamps, outdoors"],
    )


POSITIVO_PREDEFINITO = "{qualita}, {genere}, solo, {descrizione}, {variante}, {stile}"
NEGATIVO_PREDEFINITO = ("{negativo_qualita}, lowres, blurry, bad anatomy, bad hands, extra fingers, deformed, "
                        "multiple people, 2girls, 2boys, text, watermark, signature, speech bubble, frame")


class PoseGuidate(BaseModel):
    """Pose guidate: a ogni immagine uno scheletro OpenPose della libreria (pose.py) passa per un ControlNet; il
    prompt prende la posa e l'angolazione dello scheletro. L'aspetto resta quello del workflow (IPAdapter, LoRA)."""
    attive: bool = False
    controlnet: str | None = None                    # None = il primo ControlNet OpenPose trovato in ComfyUI
    pose: list[str] = Field(default_factory=list)    # id delle pose (pose.py); vuoto = tutte
    specchiate: bool = True                          # anche le pose specchiate (il doppio delle pose)
    forza: float = Field(default=0.8, ge=0, le=2)
    fine: float = Field(default=0.8, ge=0.05, le=1)


class ConfigDataset(BaseModel):
    workflow: str | None = None
    ruoli: dict[str, str | None] | None = None      # None = quelli trovati dall'analisi
    prompt_positivo: str = POSITIVO_PREDEFINITO
    prompt_negativo: str = NEGATIVO_PREDEFINITO
    tag_qualita: str | None = None                   # None = automatici in base al checkpoint
    tag_qualita_negativi: str | None = None
    stile: str = ""                                  # {stile}: tag di stile (presi dalle proposte, se ci sono)
    # {aspetto}: vestiti, capelli, occhi, accessori letti dal tagger sull'immagine di riferimento e che i tratti non
    # dicono (es. «police uniform» → «blue pants, necktie, belt…»): ogni immagine chiede lo stesso aspetto
    aspetto: str = ""
    varianti: Varianti = Field(default_factory=varianti_predefinite)
    modifiche: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # con un workflow img2img: "libera" genera ogni immagine da zero con la posa e l'inquadratura della variante,
    # "riferimento" tiene la composizione dell'immagine di riferimento (tutte nella stessa posa)
    composizione: Literal["libera", "riferimento"] = "libera"
    # nodi del workflow staccati per questo personaggio (Comic Studio ricollega il resto)
    disattivati: list[str] = Field(default_factory=list)
    pose: PoseGuidate = Field(default_factory=PoseGuidate)
    quantita: int = Field(default=100, ge=1, le=2000)
    da_tenere: int = Field(default=30, ge=1, le=500)


class VoceWorkflow(BaseModel):
    id: str
    nome: str
    origine: str                     # nome del file caricato oppure "integrato"
    creato: float = Field(default_factory=time.time)
    workflow: dict
    ruoli: dict[str, str | None]
    avvisi: list[str] = Field(default_factory=list)
    parametri: dict | None = None    # per il workflow integrato


class InfoImmagine(BaseModel):
    file: str
    numero: int
    inquadratura: str = ""
    variante: str = ""
    prompt: str = ""
    seme: int | None = None
    larghezza: int | None = None
    altezza: int | None = None
    creato: float = Field(default_factory=time.time)
    stato: StatoImmagine = None
    posa: str = ""                   # id della posa guidata (pose.py), se c'era
    manuale: bool = False            # stato scelto a mano (la selezione automatica non lo cambia)
    punteggio: float | None = None


# ---------------------------------------------------------------- prompt e varianti

def tag_qualita(checkpoint: str | None, config: ConfigDataset) -> tuple[str, str]:
    fam = famiglia_da_nome(checkpoint or "") or "sdxl"
    pos, neg = TAG_QUALITA.get(fam, TAG_QUALITA["sdxl"])
    return (config.tag_qualita if config.tag_qualita is not None else pos,
            config.tag_qualita_negativi if config.tag_qualita_negativi is not None else neg)


def pulisci_prompt(t: str) -> str:
    parti = [p.strip() for p in re.split(r",", t)]
    return ", ".join(p for p in parti if p)


def componi(modello: str, valori: dict[str, str]) -> str:
    def sostituisci(m):
        return valori.get(m.group(1), m.group(0))
    return pulisci_prompt(re.sub(r"\{(\w+)\}", sostituisci, modello))


def prossima_inquadratura(varianti: Varianti, conteggio: dict[str, int]) -> Inquadratura:
    """Sceglie l'inquadratura più indietro rispetto alla sua quota."""
    attive = [i for i in varianti.inquadrature if i.quota > 0] or varianti.inquadrature
    totale = sum(i.quota for i in attive) or 1
    fatte = sum(conteggio.values()) + 1
    return max(attive, key=lambda i: i.quota / totale * fatte - conteggio.get(i.nome, 0))


def crea_variante(varianti: Varianti, conteggio: dict[str, int], rng: random.Random) -> dict[str, str]:
    inq = prossima_inquadratura(varianti, conteggio)
    conteggio[inq.nome] = conteggio.get(inq.nome, 0) + 1
    angolazioni = varianti.angolazioni
    if not inq.con_posa:   # nei primi piani niente "di spalle"
        angolazioni = [a for a in angolazioni if "behind" not in a] or angolazioni
    v = {
        "inquadratura": inq.testo,
        "angolazione": rng.choice(angolazioni) if angolazioni else "",
        "espressione": rng.choice(varianti.espressioni) if varianti.espressioni else "",
        "posa": rng.choice(varianti.pose) if (inq.con_posa and varianti.pose) else "",
        "sfondo": rng.choice(varianti.sfondi) if varianti.sfondi else "",
    }
    v["variante"] = pulisci_prompt(", ".join(v[k] for k in ("inquadratura", "angolazione", "espressione", "posa", "sfondo")))
    v["_nome_inquadratura"] = inq.nome
    v["_dimensioni"] = f"{inq.larghezza}x{inq.altezza}"
    return v


def modello_positivo(c: "ConfigDataset") -> str:
    """Il modello del prompt positivo; se c'è uno stile ma il modello non ha {stile} (configurazioni di prima della
    0.16) lo si aggiunge in fondo, così lo stile delle proposte non si perde."""
    m = c.prompt_positivo
    if c.aspetto.strip() and "{aspetto}" not in m:
        m = m.replace("{descrizione}", "{descrizione}, {aspetto}") if "{descrizione}" in m else m + ", {aspetto}"
    if c.stile.strip() and "{stile}" not in m:
        return m + ", {stile}"
    return m


def valori_prompt(p: Personaggio, variante: dict[str, str], qualita: tuple[str, str],
                  stile: str = "", aspetto: str = "") -> dict[str, str]:
    return {**{k: v for k, v in variante.items() if not k.startswith("_")},
            "nome": p.nome, "genere": p.genere, "descrizione": p.descrizione, "trigger": p.trigger,
            "qualita": qualita[0], "negativo_qualita": qualita[1], "stile": stile, "aspetto": aspetto}


# ---------------------------------------------------------------- aspetto dal riferimento

# tag del tagger che non sono aspetto: inquadratura, posa, sguardo, espressione, sfondo, luce, tecnica, metadati
NON_ASPETTO = re.compile(
    r"background|\bviews?\b|from (side|behind|above|below)|\bprofile\b|standing|sitting|kneeling|squatting|lying|"
    r"walking|running|jumping|leaning|looking|facing|smil|grin|frown|\bmouth\b|closed eyes|expression|blush|"
    r"\bsolo\b|^\d+(girl|boy|other)s?$|^(girl|boy)$|full body|upper body|lower body|cowboy shot|portrait|close-up|"
    r"\bpose\b|contrapposto|\barms?\b|\bhands?\b|\bfingers?\b|legs? (apart|together|up)|crossed|on hip|at sides|"
    r"outstretched|spread|holding|pointing|waving|^v$|salute|\bfeet\b|\btoes\b|shadow|lighting|light rays|"
    r"sunlight|realistic|monochrome|greyscale|\bcomic\b|sketch|signature|watermark|\btext\b|english|artist|parody|"
    r"official|multiple|simple|white theme|border|cropped|out of frame|solo focus|motion|blurry|depth of field|"
    r"turnaround|reference sheet")


def aspetto_da_tag(tag: dict[str, float], p: Personaggio, gia: str = "", soglia: float = 0.35,
                   massimo: int = 25) -> list[str]:
    """I tag dell'aspetto del riferimento che i tratti (e lo stile) non dicono già, dai più sicuri."""
    def norm(t: str) -> str:
        return re.sub(r"\s+", " ", t.replace("_", " ").strip().lower())
    from .proposte import dividi_tag, nucleo
    noti = {nucleo(x) for x in dividi_tag(f"{p.descrizione},{p.genere},{gia}")}
    noti |= {nucleo(y) for x in noti for y in x.split(",")}          # «(a, b:1.1)»
    parole_noti = [set(x.split()) for x in noti]

    def detto(t: str) -> bool:      # «blonde hair» è già in «long blonde hair»
        return t in noti or any(set(t.split()) <= p for p in parole_noti)
    scelti = [norm(t) for t, v in sorted(tag.items(), key=lambda kv: -kv[1])
              if v >= soglia and not NON_ASPETTO.search(norm(t)) and not detto(norm(t)) and "(" not in t]
    return list(dict.fromkeys(scelti))[:massimo]


# preferenze per scegliere da soli i modelli di IPAdapter (come nell'interfaccia)
PREFERENZE_IPADAPTER = [r"plus.*sdxl.*vit-?h", r"sdxl.*vit-?h", r"sdxl|xl"]
PREFERENZE_CLIP_VISION = [r"vit-?h", r"laion"]


# ControlNet per le pose: OpenPose SDXL (per Illustrious / NoobAI prima quello di NoobAI, se c'è), poi gli «union»
PREFERENZE_CONTROLNET_POSA = [r"openpose.*(sdxl|xl)|(sdxl|xl).*openpose", r"openpose", r"union.*(sdxl|xl)|promax",
                              r"pose"]


def scegli_controlnet_posa(elenco: list[str], famiglia: str | None = None,
                           architetture: dict[str, str | None] | None = None) -> str | None:
    """Il ControlNet per le pose, solo tra quelli della stessa architettura del checkpoint: un ControlNet per SD 1.5
    con un checkpoint SDXL fa fallire il KSampler («mat1 and mat2 shapes cannot be multiplied … 2048 and 768»).
    `architetture`: nome → «sd15»/«sdxl»/None (dal file); senza, si guarda il nome."""
    from .modelinfo import architettura_controlnet
    serve = "sd15" if famiglia == "sd15" else "sdxl"
    arch = {n: (architetture or {}).get(n) or architettura_controlnet(n) for n in elenco}
    sicuri = [n for n in elenco if arch[n] == serve]
    dubbi = [n for n in elenco if arch[n] is None]
    for gruppo in (sicuri, dubbi):
        if famiglia in ("illustrious", "noobai"):
            noob = scegli_primo(gruppo, [r"noob.*openpose|openpose.*noob", r"illustrious.*openpose"])
            if noob:
                return noob
        scelto = scegli_primo(gruppo, PREFERENZE_CONTROLNET_POSA)
        if scelto:
            return scelto
    return None


def pose_scelte(c: "PoseGuidate") -> list:
    """Le pose da usare, nell'ordine della libreria (con le specchiate subito dopo l'originale)."""
    from . import pose as libreria
    scelte = [p for p in libreria.POSE if not c.pose or p.id in c.pose]
    return [q for p in scelte for q in ((p, libreria.specchia(p)) if c.specchiate else (p,))]


def con_posa(variante: dict[str, str], posa) -> dict[str, str]:
    """La variante con la posa e l'angolazione dello scheletro, così prompt e ControlNet dicono la stessa cosa."""
    v = dict(variante)
    v["posa"], v["angolazione"] = posa.tag, posa.vista
    v["variante"] = pulisci_prompt(", ".join(v[k] for k in ("inquadratura", "angolazione", "espressione", "posa",
                                                            "sfondo")))
    v["_posa"] = posa.id
    return v


def scegli_primo(elenco: list[str], preferenze: list[str]) -> str | None:
    for r in preferenze:
        trovato = next((x for x in elenco if re.search(r, x, re.I)), None)
        if trovato:
            return trovato
    return None


# ---------------------------------------------------------------- archivio

class ArchivioDataset:
    def __init__(self, progetti: Archivio):
        self.progetti = progetti

    # --- libreria dei workflow

    def cartella_workflow(self, pid: str) -> Path:
        return self.progetti.cartella(pid) / "workflows"

    def elenco_workflow(self, pid: str) -> list[VoceWorkflow]:
        d = self.cartella_workflow(pid)
        voci = []
        if d.is_dir():
            for f in d.glob("*.json"):
                try:
                    voci.append(VoceWorkflow.model_validate_json(f.read_text(encoding="utf-8")))
                except ValueError:
                    continue
        return sorted(voci, key=lambda v: v.creato)

    def leggi_workflow(self, pid: str, wid: str) -> VoceWorkflow:
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", wid):
            raise ErroreProgetto("Workflow non valido", 404)
        f = self.cartella_workflow(pid) / f"{wid}.json"
        if not f.is_file():
            raise ErroreProgetto(f"Workflow '{wid}' non trovato", 404)
        return VoceWorkflow.model_validate_json(f.read_text(encoding="utf-8"))

    def salva_workflow(self, pid: str, v: VoceWorkflow) -> VoceWorkflow:
        self.progetti.leggi(pid)   # il progetto deve esistere
        d = self.cartella_workflow(pid)
        d.mkdir(parents=True, exist_ok=True)
        _scrivi_json(d / f"{v.id}.json", v.model_dump())
        return v

    def aggiungi_workflow(self, pid: str, nome: str, origine: str, wf: dict, avvisi: list[str],
                          ruoli: Ruoli | None = None, parametri: dict | None = None) -> tuple[VoceWorkflow, Analisi]:
        a = analizza(wf)
        r = ruoli or a.ruoli
        wid = f"{slug(nome)[:40]}-{uuid.uuid4().hex[:6]}"
        v = VoceWorkflow(id=wid, nome=nome.strip() or "Workflow", origine=origine, workflow=wf, ruoli=r.dict(),
                         avvisi=avvisi + a.avvisi, parametri=parametri)
        return self.salva_workflow(pid, v), a

    def rinomina_workflow(self, pid: str, wid: str, nome: str) -> VoceWorkflow:
        v = self.leggi_workflow(pid, wid)
        v.nome = nome.strip() or v.nome
        return self.salva_workflow(pid, v)

    def imposta_ruoli_workflow(self, pid: str, wid: str, ruoli: dict[str, str | None]) -> VoceWorkflow:
        v = self.leggi_workflow(pid, wid)
        r = Ruoli(**{k: ruoli.get(k, getattr(Ruoli(), k)) for k in Ruoli().dict()})
        errori = controlla_ruoli(v.workflow, r)
        if errori:
            raise ErroreProgetto("Ruoli non validi: " + "; ".join(errori))
        v.ruoli = r.dict()
        return self.salva_workflow(pid, v)

    def elimina_workflow(self, pid: str, wid: str):
        v = self.leggi_workflow(pid, wid)
        cestino = self.progetti.radice / ".cestino"
        cestino.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.cartella_workflow(pid) / f"{v.id}.json"), str(cestino / f"{pid}-wf-{v.id}-{int(time.time())}.json"))

    def workflow_integrato(self, pid: str, parametri: dict) -> VoceWorkflow:
        wf, ruoli = integrato(**parametri)
        nome = f"Integrato · {Path(parametri['checkpoint']).stem}"
        v, _ = self.aggiungi_workflow(pid, nome, "integrato", wf, [], ruoli, parametri)
        return v

    def come_proposte(self, pid: str, cid: str, ricetta: dict, modelli: dict[str, list[str]]
                      ) -> tuple[ConfigDataset, VoceWorkflow, list[str]]:
        """Configura il dataset del personaggio con le stesse scelte delle proposte da cui viene il riferimento:
        workflow integrato con lo stesso checkpoint, LoRA di stile e campionamento (con IPAdapter sul riferimento se
        i modelli ci sono), lo stesso prompt (salvo la parte delle varianti) e lo stesso negativo. Il workflow si riusa
        se è già in libreria."""
        avvisi = []
        ipadapter = scegli_primo(modelli.get("ipadapter") or [], PREFERENZE_IPADAPTER)
        clip_vision = scegli_primo(modelli.get("clip_vision") or [], PREFERENZE_CLIP_VISION)
        if not (ipadapter and clip_vision):
            ipadapter = clip_vision = None
            avvisi.append("IPAdapter non è installato (modelli in models/ipadapter e models/clip_vision): il dataset "
                          "parte dai tratti scritti e la somiglianza al riferimento la garantisce solo la selezione "
                          "automatica. Con IPAdapter Plus i volti vengono molto più simili.")
        parametri = {"checkpoint": ricetta["checkpoint"], "ipadapter": ipadapter, "clip_vision": clip_vision,
                     "lora_stile": ricetta.get("lora_stile"), "forza_stile": ricetta.get("forza_lora", 0.8),
                     "peso_ipadapter": 0.7, "fine_ipadapter": 0.8, "passi": ricetta.get("passi", 28),
                     "cfg": ricetta.get("cfg", 6.0), "sampler": ricetta.get("sampler", "euler_ancestral"),
                     "scheduler": ricetta.get("scheduler", "karras")}
        voce = next((v for v in self.elenco_workflow(pid) if v.origine == "integrato" and v.parametri == parametri),
                    None)
        if voce is None:
            wf, ruoli = integrato(**parametri)
            nome = f"Come le proposte · {Path(parametri['checkpoint']).stem}"
            if parametri["lora_stile"]:
                nome += f" + {Path(parametri['lora_stile']).stem}"
            voce, _ = self.aggiungi_workflow(pid, nome, "integrato", wf, [], ruoli, parametri)
        from .proposte import modello_dataset
        c = self.config(pid, cid)
        c.workflow, c.ruoli, c.modifiche, c.disattivati, c.composizione = voce.id, None, {}, [], "libera"
        # lo stesso prompt delle proposte (stesso ordine, stessi tag di qualità automatici, stesso negativo): cambia
        # solo la parte delle varianti
        c.prompt_positivo, c.prompt_negativo = modello_dataset(ricetta)
        c.stile = "" if (ricetta.get("positivo") or "").strip() else ricetta.get("stile", "")
        c.tag_qualita = c.tag_qualita_negativi = None
        self.salva_config(pid, cid, c)
        return c, voce, avvisi

    # --- configurazione del personaggio

    def cartella(self, pid: str, cid: str) -> Path:
        return self.progetti.cartella_personaggio(pid, cid) / "dataset"

    def config(self, pid: str, cid: str) -> ConfigDataset:
        self.personaggio(pid, cid)
        f = self.cartella(pid, cid) / "config.json"
        try:
            return ConfigDataset.model_validate_json(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ConfigDataset()

    def salva_config(self, pid: str, cid: str, c: ConfigDataset) -> ConfigDataset:
        self.personaggio(pid, cid)
        if c.workflow:
            v = self.leggi_workflow(pid, c.workflow)
            if c.ruoli:
                errori = controlla_ruoli(v.workflow, Ruoli(**{**v.ruoli, **c.ruoli}))
                if errori:
                    raise ErroreProgetto("Ruoli non validi: " + "; ".join(errori))
        if not c.varianti.inquadrature:
            raise ErroreProgetto("Serve almeno un'inquadratura")
        d = self.cartella(pid, cid)
        d.mkdir(parents=True, exist_ok=True)
        _scrivi_json(d / "config.json", c.model_dump())
        return c

    def ruoli_effettivi(self, pid: str, c: ConfigDataset) -> tuple[VoceWorkflow, Ruoli]:
        if not c.workflow:
            raise ErroreProgetto("Scegli prima un workflow per questo personaggio")
        v = self.leggi_workflow(pid, c.workflow)
        return v, Ruoli(**{**v.ruoli, **(c.ruoli or {})})

    def personaggio(self, pid: str, cid: str) -> tuple[Progetto, Personaggio]:
        p = self.progetti.leggi(pid)
        for c in p.personaggi:
            if c.id == cid:
                return p, c
        raise ErroreProgetto(f"Personaggio '{cid}' non trovato", 404)

    # --- anteprima dei prompt

    def esempi_prompt(self, pid: str, cid: str, c: ConfigDataset, n: int = 4) -> list[dict]:
        _, pers = self.personaggio(pid, cid)
        checkpoint = None
        if c.workflow:
            try:
                checkpoint = analizza(self.leggi_workflow(pid, c.workflow).workflow).checkpoint
            except ErroreProgetto:
                pass
        q = tag_qualita(checkpoint, c)
        rng, conteggio, out = random.Random(7), {}, []
        from . import pose as libreria
        rotazione = libreria.Rotazione(pose_scelte(c.pose)) if c.pose.attive else None
        for _ in range(n):
            v = crea_variante(c.varianti, conteggio, rng)
            posa = rotazione.prossima(libreria.taglio(f"{v['inquadratura']} {v['_nome_inquadratura']}")) \
                if rotazione else None
            if posa:
                v = con_posa(v, posa)
            val = valori_prompt(pers, v, q, c.stile, c.aspetto)
            out.append({"inquadratura": v["_nome_inquadratura"], "dimensioni": v["_dimensioni"],
                        "posa": posa.id if posa else None,
                        "positivo": componi(modello_positivo(c), val), "negativo": componi(c.prompt_negativo, val)})
        return out

    # --- immagini

    def _file_meta(self, pid, cid) -> Path:
        return self.cartella(pid, cid) / "immagini.json"

    def immagini(self, pid: str, cid: str) -> list[InfoImmagine]:
        f = self._file_meta(pid, cid)
        try:
            dati = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        cartella = self.cartella(pid, cid) / "generate"
        out = []
        for d in dati:
            try:
                info = InfoImmagine(**d)
            except ValueError:
                continue
            if (cartella / info.file).exists():
                out.append(info)
        return sorted(out, key=lambda i: i.numero)

    def _salva_immagini(self, pid, cid, voci: list[InfoImmagine]):
        _scrivi_json(self._file_meta(pid, cid), [v.model_dump() for v in voci])

    def aggiungi_immagine(self, pid: str, cid: str, dati: bytes, info: InfoImmagine,
                          wf: dict | None = None) -> InfoImmagine:
        with _lock:
            d = self.cartella(pid, cid)
            (d / "generate").mkdir(parents=True, exist_ok=True)
            (d / "generate" / info.file).write_bytes(dati)
            if wf is not None:            # il workflow esatto mandato a ComfyUI, per rivederne il grafo
                (d / "workflow").mkdir(exist_ok=True)
                (d / "workflow" / (Path(info.file).stem + ".json")).write_text(json.dumps(wf, ensure_ascii=False),
                                                                               encoding="utf-8")
            crea_anteprima(d / "generate" / info.file, d / "anteprime" / (Path(info.file).stem + ".jpg"))
            voci = [v for v in self.immagini(pid, cid) if v.file != info.file] + [info]
            self._salva_immagini(pid, cid, voci)
            return info

    def workflow_immagine(self, pid: str, cid: str, file: str) -> tuple[dict, bool]:
        """Il workflow con cui è stata generata l'immagine: quello salvato (dalla 0.23) oppure ricostruito con la
        configurazione attuale del dataset e il prompt, il seme e le dimensioni dell'immagine. (workflow, ricostruito)"""
        from .workflows import aggiungi_posa, applica, img2img
        self.file_immagine(pid, cid, file)
        f = self.cartella(pid, cid) / "workflow" / (Path(file).stem + ".json")
        if f.is_file():
            return json.loads(f.read_text(encoding="utf-8")), False
        info = next((v for v in self.immagini(pid, cid) if v.file == file), None)
        if info is None:
            raise ErroreProgetto("Immagine non trovata", 404)
        _, pers = self.personaggio(pid, cid)
        c = self.config(pid, cid)
        voce, ruoli = self.ruoli_effettivi(pid, c)
        q = tag_qualita(analizza(voce.workflow).checkpoint, c)
        val = valori_prompt(pers, {"variante": info.variante}, q, c.stile)
        libera = bool(img2img(voce.workflow, ruoli.riferimento)) and (c.composizione == "libera" or bool(info.posa))
        wf = applica(voce.workflow, ruoli, riferimento="riferimento.png" if ruoli.riferimento else None,
                     positivo=info.prompt, negativo=componi(c.prompt_negativo, val), seme=info.seme,
                     dimensioni=(info.larghezza, info.altezza) if info.larghezza and info.altezza else None,
                     prefisso=f"comic_studio/{pid}/{cid}/dataset", modifiche=c.modifiche, composizione_libera=libera,
                     disattivati=c.disattivati)
        if info.posa:
            aggiungi_posa(wf, c.pose.controlnet or "ControlNet OpenPose", f"posa_{info.posa}.png", c.pose.forza, 0.0,
                          c.pose.fine)
        return wf, True

    def prossimo_numero(self, pid: str, cid: str) -> int:
        voci = self.immagini(pid, cid)
        return max((v.numero for v in voci), default=0) + 1

    def imposta_stato(self, pid: str, cid: str, file: str, stato: StatoImmagine) -> InfoImmagine:
        with _lock:
            voci = self.immagini(pid, cid)
            for v in voci:
                if v.file == file:
                    v.stato, v.manuale = stato, stato is not None
                    self._salva_immagini(pid, cid, voci)
                    return v
        raise ErroreProgetto(f"Immagine '{file}' non trovata", 404)

    def imposta_selezione(self, pid: str, cid: str, punteggi: dict[str, float], tenute: set[str]):
        with _lock:
            voci = self.immagini(pid, cid)
            for v in voci:
                if v.file in punteggi:
                    v.punteggio = round(float(punteggi[v.file]), 4)
                if not v.manuale:
                    v.stato = "tenuta" if v.file in tenute else "scartata"
            self._salva_immagini(pid, cid, voci)
            return voci

    def elimina_immagini(self, pid: str, cid: str, files: list[str] | None = None, definitivo: bool = False) -> int:
        """Sposta nel cestino le immagini indicate (tutte se None). Con `definitivo` le cancella dal disco: si usa
        solo dopo che l'utente le ha scaricate, per liberare lo spazio."""
        with _lock:
            voci = self.immagini(pid, cid)
            scelte = None if files is None else set(files)
            via = [v for v in voci if scelte is None or v.file in scelte]
            if not via:
                return 0
            d = self.cartella(pid, cid)
            cestino = None
            if not definitivo:
                cestino = self.progetti.radice / ".cestino" / f"{pid}-{cid}-dataset-{int(time.time())}"
                cestino.mkdir(parents=True, exist_ok=True)
            for v in via:
                for f in (d / "generate" / v.file, d / "anteprime" / (Path(v.file).stem + ".jpg"),
                          d / "workflow" / (Path(v.file).stem + ".json")):
                    if not f.exists():
                        continue
                    if cestino:
                        shutil.move(str(f), str(cestino / f.name))
                    else:
                        f.unlink()
            self._salva_immagini(pid, cid, [v for v in voci if v not in via])
            return len(via)

    # ------------------------------------------------------------ cestino e spazio

    def _cestini(self, pid: str, cid: str) -> list[Path]:
        radice = self.progetti.radice / ".cestino"
        if not radice.is_dir():
            return []
        regola = re.compile(rf"^{re.escape(pid)}-{re.escape(cid)}-dataset-\d+$")
        return sorted(p for p in radice.iterdir() if p.is_dir() and regola.match(p.name))

    def cestino(self, pid: str, cid: str) -> dict:
        """Immagini del dataset di questo personaggio finite nel cestino e quanto spazio occupano."""
        file = [f for c in self._cestini(pid, cid) for f in c.iterdir() if f.is_file()]
        return {"immagini": sum(f.suffix.lower() == ".png" for f in file),
                "byte": sum(f.stat().st_size for f in file)}

    def svuota_cestino(self, pid: str, cid: str) -> dict:
        """Cancella dal disco le immagini del dataset di questo personaggio che sono nel cestino."""
        prima = self.cestino(pid, cid)
        for c in self._cestini(pid, cid):
            shutil.rmtree(c, ignore_errors=True)
        return prima

    def spazio(self, pid: str, cid: str) -> int:
        d = self.cartella(pid, cid)
        return sum(f.stat().st_size for sotto in ("generate", "anteprime") if (d / sotto).is_dir()
                   for f in (d / sotto).iterdir() if f.is_file())

    # ------------------------------------------------------------ esportazione

    def cartella_esportazioni(self, pid: str, cid: str) -> Path:
        return self.cartella(pid, cid) / "esportazioni"

    def esporta(self, pid: str, cid: str, files: list[str] | None, avanza=None, controlla=None) -> dict:
        """ZIP con le immagini indicate (tutte se None), il prompt di ognuna in un .txt e i metadati."""
        voci = self.immagini(pid, cid)
        scelte = None if files is None else set(files)
        voci = [v for v in voci if scelte is None or v.file in scelte]
        if not voci:
            raise ErroreProgetto("Nessuna immagine da scaricare.", 400)
        d = self.cartella(pid, cid)
        dest = self.cartella_esportazioni(pid, cid)
        dest.mkdir(parents=True, exist_ok=True)
        for vecchio in dest.glob("*.zip.parziale"):
            vecchio.unlink(missing_ok=True)
        nome = f"{cid}-dataset-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        tmp = dest / (nome + ".parziale")
        messe = []
        # le PNG sono già compresse: ZIP_STORED è veloce e non perde spazio
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
            for k, v in enumerate(voci):
                if controlla:
                    controlla()
                f = d / "generate" / v.file
                if not f.exists():
                    continue
                z.write(f, f"{cid}/{v.file}")
                if v.prompt:
                    z.writestr(f"{cid}/{Path(v.file).stem}.txt", v.prompt)
                messe.append(v)
                if avanza:
                    avanza((k + 1) / len(voci), f"{k + 1}/{len(voci)} immagini nello ZIP")
            z.writestr(f"{cid}/immagini.json", json.dumps([v.model_dump() for v in messe], indent=2,
                                                          ensure_ascii=False))
        tmp.replace(dest / nome)
        return {"nome": nome, "byte": (dest / nome).stat().st_size, "immagini": len(messe),
                "file": [v.file for v in messe]}

    def file_esportazione(self, pid: str, cid: str, nome: str) -> Path:
        if not re.fullmatch(r"[\w.-]{1,120}\.zip", nome):
            raise ErroreProgetto("Nome di file non valido", 404)
        f = self.cartella_esportazioni(pid, cid) / nome
        if not f.is_file():
            raise ErroreProgetto("Lo ZIP non c'è più: preparalo di nuovo.", 404)
        return f

    def file_immagine(self, pid: str, cid: str, file: str, anteprima: bool = False) -> Path:
        if not re.fullmatch(r"[\w-]{1,64}\.(png|jpg|jpeg|webp)", file):
            raise ErroreProgetto("Nome di file non valido", 404)
        d = self.cartella(pid, cid)
        if anteprima:
            a = d / "anteprime" / (Path(file).stem + ".jpg")
            if not a.exists() and (d / "generate" / file).exists():
                crea_anteprima(d / "generate" / file, a)
            if a.exists():
                return a
        f = d / "generate" / file
        if not f.exists():
            raise ErroreProgetto("Immagine non trovata", 404)
        return f

    def riepilogo(self, pid: str, cid: str) -> dict:
        voci = self.immagini(pid, cid)
        return {"totale": len(voci), "tenute": sum(v.stato == "tenuta" for v in voci),
                "scartate": sum(v.stato == "scartata" for v in voci),
                "da_decidere": sum(v.stato is None for v in voci),
                "byte": self.spazio(pid, cid), "cestino": self.cestino(pid, cid)}


def crea_anteprima(sorgente: Path, dest: Path, lato: int = 384):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(sorgente) as img:
        img = img.convert("RGB")
        img.thumbnail((lato, lato), Image.LANCZOS)
        img.save(dest, "JPEG", quality=85)


def _scrivi_json(f: Path, dati):
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(f.suffix + ".tmp")
    tmp.write_text(json.dumps(dati, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


__all__ = ["ArchivioDataset", "ConfigDataset", "InfoImmagine", "PoseGuidate", "VoceWorkflow", "Varianti", "Inquadratura",
           "componi", "crea_variante", "tag_qualita", "valori_prompt"]
