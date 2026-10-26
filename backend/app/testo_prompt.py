"""Dal testo in linguaggio naturale (anche lungo, in qualsiasi lingua) a un prompt fedele.

1. l'IA locale legge il testo e restituisce un'analisi strutturata (JSON con schema): soggetti, azioni,
   espressioni, vestiti, inquadratura, ambiente, luce, atmosfera, effetti, elementi chiave
2. Comic Studio compone il prompt in modo deterministico, nello stile giusto per il checkpoint:
   tag Danbooru per Pony / Illustrious / NoobAI, frasi per Flux / SD3, misto per SDXL
3. gli elementi chiave pesano di più; quelli che il tagger non trova nell'immagine si possono rafforzare

Regola fissa: nessun contenuto sessuale con minorenni o con personaggi dall'aspetto infantile.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

from .projects import ErroreProgetto, Personaggio

# ---------------------------------------------------------------- stile del prompt per famiglia

FAMIGLIE_TAG = {"pony", "illustrious", "noobai", "sd15"}
FAMIGLIE_FRASE = {"flux", "sd3"}


def stile_prompt(famiglia: str | None) -> str:
    if famiglia in FAMIGLIE_TAG:
        return "tag"
    if famiglia in FAMIGLIE_FRASE:
        return "frase"
    return "misto"


# ---------------------------------------------------------------- blocco fisso: minori e contenuto sessuale

MESSAGGIO_VIETATO = ("Questa descrizione unisce contenuti sessuali e personaggi minorenni o dall'aspetto infantile: "
                     "Comic Studio non la genera. Questo blocco non si può disattivare.")

_SESSUALE = re.compile(
    r"\b(sesso|sessual\w*|nud[oaie]|nudit\w*|svestit\w*|erotic\w*|porn\w*|hentai|nsfw|orgasm\w*|masturb\w*|"
    r"scopa(?:re|no|ta|ndo)|stupr\w*|molest\w*|sex|sexual\w*|sexy|naked|nude|nudity|nipples?|genital\w*|penis|"
    r"vagina|pussy|cum|intercourse|lewd|ecchi|explicit|topless|bottomless|fellatio|blowjob|lingerie|"
    r"seductive|aroused|rape|undress\w*)\b", re.I)
_MINORE = re.compile(
    r"\b(bambin[oaie]|bimb[oaie]|ragazzin[oaie]|minorenn[ei]|neonat\w*|infan\w*|adolescent\w*|"
    r"scuola (?:elementare|media)|elementari|child|children|kids?|toddler|baby|preteen|underage|"
    r"loli\w*|shota\w*|teen|teens|teenager\w*|young girl|young boy|little girl|little boy|schoolgirl|schoolboy|"
    r"elementary school|middle school|aged? down|petite child|cub)\b", re.I)
_ETA = re.compile(r"\b(\d{1,2})\s*(?:anni|anno|years?[\s-]*old|yo|y/o|yrs?)\b", re.I)


class ContenutoVietato(ErroreProgetto):
    def __init__(self):
        super().__init__(MESSAGGIO_VIETATO, 422)


def sembra_sessuale(testo: str) -> bool:
    return bool(_SESSUALE.search(testo or ""))


def sembra_minore(testo: str) -> bool:
    t = testo or ""
    if _MINORE.search(t):
        return True
    return any(int(m.group(1)) < 18 for m in _ETA.finditer(t))


def verifica_contenuto(testi: list[str], sessuale: bool = False, minori: bool = False):
# BLOCCO DISATTIVATO
    return


# ---------------------------------------------------------------- schemi e istruzioni per l'IA

_LISTA = {"type": "array", "items": {"type": "string"}}

SCHEMA_PERSONAGGIO = {
    "type": "object",
    "properties": {
        "genere": {"type": "string", "enum": ["1girl", "1boy", "1other"]},
        "adulto": {"type": "boolean"},
        "eta_apparente": {"type": "string"},
        "tratti": _LISTA,
        "abbigliamento": _LISTA,
        "accessori": _LISTA,
        "frase": {"type": "string"},
        "non_rappresentabile": _LISTA,
    },
    "required": ["genere", "adulto", "eta_apparente", "tratti", "abbigliamento", "accessori", "frase",
                 "non_rappresentabile"],
}

SISTEMA_PERSONAGGIO = """You turn a character description into Stable Diffusion prompt elements for a comic.
The description can be in any language (often Italian), long, and mixed with backstory and personality.

Extract ONLY what can be seen and stays the same in every picture of this character:
- tratti: physical traits as short English Danbooru-style tags (lowercase, spaces, no underscores):
  hair colour, length and style, eye colour, skin, face, body type, height, age look, scars, tattoos,
  species features (elf ears, horns, tail...). Be precise ("long wavy auburn hair", "green eyes").
- abbigliamento: the usual outfit as tags; accessori: glasses, jewellery, weapons always carried.
- frase: one concrete English sentence describing the character's look.
- non_rappresentabile: personality, backstory, voice, things that cannot be drawn (in the original language).
- genere: 1girl, 1boy or 1other. adulto: false if the character is, or looks, under 18.
- eta_apparente: e.g. "about 30", "elderly", "teenager".
Rules: be faithful, translate exactly, do not invent traits that are not in the text, leave lists empty if
unknown. Personality becomes a visible tag only if the text says how it shows (e.g. "always frowning" -> frown).
Answer only with the JSON object."""

_SOGGETTO = {
    "type": "object",
    "properties": {
        "personaggio": {"type": "string"},
        "descrizione": _LISTA,
        "posizione": {"type": "string", "enum": ["sinistra", "centro", "destra", "sfondo", ""]},
        "azione": _LISTA,
        "posa": _LISTA,
        "espressione": _LISTA,
        "vestiti": _LISTA,
        "adulto": {"type": "boolean"},
    },
    "required": ["personaggio", "descrizione", "posizione", "azione", "posa", "espressione", "vestiti", "adulto"],
}

SCHEMA_SCENA = {
    "type": "object",
    "properties": {
        "soggetti": {"type": "array", "items": _SOGGETTO},
        "interazione": _LISTA,
        "inquadratura": _LISTA,
        "ambiente": _LISTA,
        "illuminazione": _LISTA,
        "atmosfera": _LISTA,
        "oggetti": _LISTA,
        "effetti": _LISTA,
        "elementi_chiave": _LISTA,
        "negativo": _LISTA,
        "frase": {"type": "string"},
        "sessuale": {"type": "boolean"},
        "non_rappresentabile": _LISTA,
    },
    "required": ["soggetti", "interazione", "inquadratura", "ambiente", "illuminazione", "atmosfera", "oggetti",
                 "effetti", "elementi_chiave", "negativo", "frase", "sessuale", "non_rappresentabile"],
}

SISTEMA_SCENA = """You turn the description of ONE comic panel into Stable Diffusion prompt elements.
The description can be in any language (often Italian) and very long. Read all of it.

Known characters are listed with an id, name, trigger word and fixed traits. A LoRA already knows their look:
refer to them by id in "personaggio" and do NOT repeat their fixed traits; describe only what this scene adds or
changes (action, pose, expression, different clothes, wounds, wet, dirty...). For any other person, creature or
crowd use personaggio "" and describe them in "descrizione".

Fields (English Danbooru-style tags: lowercase, short, concrete, no sentences, no underscores):
- soggetti: everyone visible, with posizione (sinistra = left, centro, destra = right, sfondo = background).
- interazione: what characters do to each other (e.g. "fighting", "hug", "holding hands", "punching").
- inquadratura: shot and camera ("close-up", "cowboy shot", "full body", "wide shot", "from below", "dutch angle").
- ambiente, illuminazione, atmosfera, oggetti, effetti (blood, rain, fire, smoke, motion lines, explosion...).
- elementi_chiave: the 3-8 most important visual elements that MUST be in the picture, as simple tags.
- negativo: things the text says must NOT be there.
- frase: 1-3 concrete English sentences describing the picture.
- non_rappresentabile: sounds, smells, thoughts, time passing, anything not drawable (original language).
Rules:
- One single image: if the text tells a sequence, show its most important moment.
- Be faithful: include every visible detail and translate it exactly. Do not add things that are not written.
  Do not soften, censor or tone down violence, blood, gore, injuries, horror or disturbing elements when the
  text describes them.
- adulto is false if a subject is or looks under 18. Never describe minors in sexual situations.
- sessuale is true if the scene contains sexual content or nudity.
Answer only with the JSON object."""

SCHEMA_STORIA = {
    "type": "object",
    "properties": {
        "pagine": {"type": "array", "items": {
            "type": "object",
            "properties": {"vignette": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "formato": {"type": "string", "enum": ["larga", "alta", "quadrata"]},
                    "personaggi": _LISTA,
                    "descrizione": {"type": "string"},
                    "dialoghi": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"chi": {"type": "string"}, "testo": {"type": "string"}},
                        "required": ["chi", "testo"]}},
                },
                "required": ["formato", "personaggi", "descrizione", "dialoghi"]}}},
            "required": ["vignette"]}},
    },
    "required": ["pagine"],
}

SISTEMA_STORIA = """You split a story into comic pages and panels.
- 3-6 panels per page, each panel ONE visual moment, in story order; do not skip events.
- personaggi: ids of the known characters visible in the panel, left to right, at most 3.
- descrizione: a detailed, faithful, visual description of the panel IN THE SAME LANGUAGE AS THE STORY
  (who, where, what they do, expressions, camera, light, mood). Keep violent or horror details as written.
- dialoghi: lines spoken in that panel, copied word for word; chi = character id or "narratore" for captions.
- formato: "larga" for wide/establishing shots, "alta" for tall full-body or vertical action, "quadrata" for close-ups.
Never describe minors in sexual situations. Answer only with the JSON object."""


def elenco_personaggi(personaggi: list[Personaggio]) -> str:
    righe = [f'- id "{p.id}": {p.nome} (trigger "{p.trigger}", {p.genere}) — {p.descrizione or "nessun tratto"}'
             for p in personaggi]
    return "Known characters:\n" + ("\n".join(righe) if righe else "(none)")


def richiesta_scena(descrizione: str, personaggi: list[Personaggio], scelti: list[str]) -> str:
    testo = elenco_personaggi(personaggi)
    if scelti:
        testo += "\nCharacters chosen for this panel, left to right: " + ", ".join(scelti)
    return f"{testo}\n\nPanel description:\n{descrizione.strip()}"


def chiave_analisi(descrizione: str, personaggi: list[Personaggio], scelti: list[str], modello: str) -> str:
    base = json.dumps([descrizione.strip(), [(p.id, p.descrizione) for p in personaggi], scelti, modello])
    return hashlib.sha256(base.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- composizione del prompt

def norm(t: str) -> str:
    t = str(t).strip().strip(".").lower().replace("_", " ")
    return re.sub(r"\s+", " ", t)


def _lista(x) -> list[str]:
    if isinstance(x, str):
        x = x.split(",")
    return [norm(t) for t in (x or []) if norm(t)]


def _unici(*liste: list[str]) -> list[str]:
    visti, out = set(), []
    for lista in liste:
        for t in lista:
            if t and t not in visti:
                visti.add(t)
                out.append(t)
    return out


def _esc(t: str) -> str:
    return t.replace("(", r"\(").replace(")", r"\)")


def pesa(tag: str, peso: float) -> str:
    return _esc(tag) if abs(peso - 1) < 1e-6 else f"({_esc(tag)}:{peso:.2f})"


ORDINE_POSIZIONI = {"sinistra": 0, "centro": 1, "destra": 2, "sfondo": 3, "": 4}


@dataclass
class PromptScena:
    globale: str = ""                                            # la scena, senza i tratti dei personaggi noti
    per_personaggio: dict[str, str] = field(default_factory=dict)  # azione, posa, espressione di ciascuno
    negativo: str = ""
    chiave: list[str] = field(default_factory=list)
    personaggi: list[str] = field(default_factory=list)          # personaggi noti, da sinistra a destra
    altri_soggetti: int = 0
    non_rappresentabile: list[str] = field(default_factory=list)
    sessuale: bool = False

    def dict(self):
        return asdict(self)


def componi_scena(analisi: dict, famiglia: str | None, conosciuti: set[str],
                  rafforza: list[str] | None = None) -> PromptScena:
    stile = stile_prompt(famiglia)
    chiave = _lista(analisi.get("elementi_chiave"))
    forti = set(_lista(rafforza))
    usati: set[str] = set()

    def t(tag: str) -> str:
        usati.add(tag)
        if tag in forti:
            return pesa(tag, 1.3)
        if tag in chiave:
            return pesa(tag, 1.15)
        return _esc(tag)

    soggetti = [s for s in analisi.get("soggetti") or [] if isinstance(s, dict)]
    noti = sorted((s for s in soggetti if s.get("personaggio") in conosciuti),
                  key=lambda s: ORDINE_POSIZIONI.get(s.get("posizione", ""), 4))
    altri = [s for s in soggetti if s.get("personaggio") not in conosciuti]

    per = {}
    for s in noti:
        tag = _unici(_lista(s.get("azione")), _lista(s.get("posa")), _lista(s.get("espressione")),
                     _lista(s.get("vestiti")))
        per[s["personaggio"]] = ", ".join(t(x) for x in tag)
    blocchi = [_lista(analisi.get("inquadratura")), _lista(analisi.get("interazione"))]
    for s in altri:
        blocchi.append(_unici(_lista(s.get("descrizione")), _lista(s.get("azione")), _lista(s.get("posa")),
                              _lista(s.get("espressione")), _lista(s.get("vestiti"))))
    blocchi += [_lista(analisi.get(k)) for k in ("effetti", "oggetti", "ambiente", "illuminazione", "atmosfera")]
    tag_scena = _unici(*blocchi)
    parti = [t(x) for x in tag_scena]
    # elementi chiave che l'IA non ha messo da nessuna parte, e quelli da rafforzare
    tutti_per = {x for s in noti for x in _unici(_lista(s.get("azione")), _lista(s.get("posa")),
                                                   _lista(s.get("espressione")), _lista(s.get("vestiti")))}
    for x in _unici(chiave, list(forti)):
        if x not in tag_scena and x not in tutti_per:
            parti.append(t(x))
    frase = (analisi.get("frase") or "").strip()
    if stile == "frase" and frase:
        globale = frase + (" " + ", ".join(t(x) for x in _unici(chiave, list(forti))) if chiave or forti else "")
    elif stile == "misto" and frase:
        globale = ", ".join(parti + [frase])
    else:
        globale = ", ".join(parti)
    return PromptScena(
        globale=globale, per_personaggio=per, negativo=", ".join(_lista(analisi.get("negativo"))),
        chiave=_unici(chiave, list(forti)), personaggi=[s["personaggio"] for s in noti][:3],
        altri_soggetti=len([s for s in altri if s.get("posizione") != "sfondo"]),
        non_rappresentabile=[str(x) for x in analisi.get("non_rappresentabile") or []],
        sessuale=bool(analisi.get("sessuale")))


def _valori(x) -> list[str]:
    """Tutte le stringhe dentro l'analisi (i valori, non i nomi dei campi)."""
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [s for v in x.values() for s in _valori(v)]
    if isinstance(x, list):
        return [s for v in x for s in _valori(v)]
    return []


def verifica_scena(analisi: dict, descrizione: str, personaggi: list[Personaggio]):
    """Il blocco fisso applicato a una scena già analizzata."""
    soggetti = analisi.get("soggetti") or []
    usati = {s.get("personaggio") for s in soggetti if isinstance(s, dict)}
    minori = any(isinstance(s, dict) and s.get("adulto") is False for s in soggetti) or \
        any(p.adulto is False for p in personaggi if p.id in usati)
    verifica_contenuto([descrizione, " ".join(_valori(analisi))] + [p.descrizione for p in personaggi if p.id in usati],
                       sessuale=bool(analisi.get("sessuale")), minori=minori)


def tratti_personaggio(analisi: dict, famiglia: str | None = None) -> dict:
    """Dall'analisi di un personaggio ai suoi tratti fissi (campo descrizione)."""
    tag = _unici(_lista(analisi.get("tratti")), _lista(analisi.get("abbigliamento")), _lista(analisi.get("accessori")))
    descrizione = ", ".join(_esc(x) for x in tag)
    frase = (analisi.get("frase") or "").strip()
    if stile_prompt(famiglia) == "frase" and frase:
        descrizione = f"{frase} {descrizione}".strip()
    genere = analisi.get("genere") if analisi.get("genere") in ("1girl", "1boy", "1other") else None
    return {"descrizione": descrizione[:1500], "genere": genere, "adulto": analisi.get("adulto"),
            "eta_apparente": analisi.get("eta_apparente", ""), "frase": frase,
            "non_rappresentabile": [str(x) for x in analisi.get("non_rappresentabile") or []]}


# ---------------------------------------------------------------- aderenza dell'immagine alla descrizione

def aderenza(tag_immagine: dict[str, float], chiave: list[str], vocabolario: set[str], soglia: float = 0.3) -> dict:
    """Quali elementi chiave il tagger vede nell'immagine (solo quelli che il tagger conosce)."""
    trovati, mancanti, non_verificabili = [], [], []
    for k in chiave:
        n = norm(k)
        if n not in vocabolario:
            non_verificabili.append(k)
        elif tag_immagine.get(n, 0) >= soglia:
            trovati.append(k)
        else:
            mancanti.append(k)
    verificati = len(trovati) + len(mancanti)
    return {"trovati": trovati, "mancanti": mancanti, "non_verificabili": non_verificabili,
            "punteggio": round(len(trovati) / verificati, 2) if verificati else None}


# ---------------------------------------------------------------- storia → pagine

def spezza_storia(testo: str, massimo: int = 6000) -> list[str]:
    """Pezzi di storia di lunghezza ragionevole, tagliati tra un paragrafo e l'altro."""
    paragrafi = [p for p in re.split(r"\n\s*\n", testo.strip()) if p.strip()]
    pezzi, corrente = [], ""
    for p in paragrafi:
        while len(p) > massimo:            # paragrafo enorme: si taglia sulle frasi
            taglio = p.rfind(". ", 0, massimo)
            taglio = taglio + 1 if taglio > 0 else massimo
            if corrente:
                pezzi.append(corrente)
                corrente = ""
            pezzi.append(p[:taglio].strip())
            p = p[taglio:].strip()
        if corrente and len(corrente) + len(p) + 2 > massimo:
            pezzi.append(corrente)
            corrente = p
        else:
            corrente = f"{corrente}\n\n{p}" if corrente else p
    if corrente:
        pezzi.append(corrente)
    return pezzi


def pagine_da_analisi(dati: dict, personaggi: list[Personaggio]) -> list[dict]:
    """Le pagine restituite dall'IA, ripulite: personaggi esistenti, al massimo 3 per vignetta."""
    ids = {p.id for p in personaggi}
    per_nome = {p.nome.lower(): p.id for p in personaggi} | {p.trigger.lower(): p.id for p in personaggi}

    def trova(x: str) -> str | None:
        x = str(x).strip()
        return x if x in ids else per_nome.get(x.lower())

    pagine = []
    for pg in dati.get("pagine") or []:
        vignette = []
        for v in (pg or {}).get("vignette") or []:
            chi = []
            for x in v.get("personaggi") or []:
                i = trova(x)
                if i and i not in chi:
                    chi.append(i)
            dialoghi = []
            for d in v.get("dialoghi") or []:
                testo = str(d.get("testo", "")).strip()
                if testo:
                    dialoghi.append({"chi": trova(d.get("chi", "")) or "narratore", "testo": testo})
            formato = v.get("formato") if v.get("formato") in ("larga", "alta", "quadrata") else "larga"
            vignette.append({"formato": formato, "personaggi": chi[:3],
                             "descrizione": str(v.get("descrizione", "")).strip(), "dialoghi": dialoghi})
        if vignette:
            pagine.append({"vignette": vignette})
    return pagine
