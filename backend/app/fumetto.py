"""Step 4 — Fumetto: pagine, vignette con uno o più personaggi (ognuno con il suo LoRA), balloon e tavole.

Le scene con più personaggi si fanno in due passaggi dentro lo stesso workflow:
  1. composizione con tutti i LoRA a forza bassa e un prompt per zona (il primo personaggio a sinistra…)
  2. ripasso di ogni zona con il solo LoRA di quel personaggio (inpainting), poi incollata sulla scena

File: <progetto>/fumetto/{fumetto.json, immagini.json, vignette/*.png}
"""
from __future__ import annotations

import io
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from .testo_prompt import PromptScena  # noqa: F401 - usato nelle annotazioni
from .projects import ErroreProgetto, Personaggio

Formato = Literal["larga", "alta", "quadrata"]
Posizione = Literal["auto", "alto-sx", "alto-dx", "basso-sx", "basso-dx"]
DIMENSIONI: dict[str, tuple[int, int]] = {"larga": (1688, 832), "alta": (832, 1216), "quadrata": (1024, 1024)}
_lock = threading.RLock()


# ---------------------------------------------------------------- modelli

class Dialogo(BaseModel):
    chi: str = "narratore"             # id del personaggio oppure "narratore"
    testo: str = ""
    posizione: Posizione = "auto"


class Vignetta(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    formato: Formato = "larga"
    personaggi: list[str] = Field(default_factory=list, max_length=3)   # da sinistra a destra
    azione: str = ""                  # cosa succede, in inglese, a tag (si aggiunge a quanto ricavato dal testo)
    descrizione: str = Field(default="", max_length=20000)   # la scena in linguaggio naturale, qualsiasi lingua
    analisi: dict | None = None       # {"chiave": impronta del testo, "dati": analisi dell'IA}
    rafforza: list[str] = Field(default_factory=list)        # elementi da far pesare di più alla prossima
    dialoghi: list[Dialogo] = Field(default_factory=list)
    seme: int | None = None


class Pagina(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    vignette: list[Vignetta] = Field(default_factory=list)


class Impostazioni(BaseModel):
    checkpoint: str | None = None
    lora_stile: str | None = None
    forza_stile: float = Field(0.6, ge=0, le=2)
    forza_personaggio: float = Field(0.85, ge=0, le=2)
    positivo: str = "{qualita}, western comics (style), detailed lineart, clean inking, cel shading"
    negativo: str = ("{negativo_qualita}, nsfw, lowres, blurry, bad anatomy, bad hands, extra fingers, deformed, "
                     "text, watermark, signature, speech bubble, multiple panels, frame, border")
    tag_qualita: str | None = None
    tag_qualita_negativi: str | None = None
    passi: int = Field(30, ge=1, le=150)
    cfg: float = Field(6.5, ge=1, le=30)
    sampler: str = "euler_ancestral"
    scheduler: str = "karras"
    ripasso: float = Field(0.5, ge=0, le=1)      # denoise del ripasso di ogni personaggio nelle scene di gruppo
    font: str | None = None
    larghezza_pagina: int = Field(1736, ge=800, le=4000)
    margine: int = Field(24, ge=0, le=120)


class Fumetto(BaseModel):
    titolo: str = ""
    impostazioni: Impostazioni = Field(default_factory=Impostazioni)
    pagine: list[Pagina] = Field(default_factory=lambda: [Pagina()])


class Versione(BaseModel):
    file: str
    seme: int
    creato: float = Field(default_factory=time.time)
    prompt: str = ""
    aderenza: dict | None = None      # elementi chiave trovati / mancanti secondo il tagger


class ImmaginiVignetta(BaseModel):
    versioni: list[Versione] = Field(default_factory=list)
    scelta: int | None = None          # indice della versione usata nella tavola

    def corrente(self) -> Versione | None:
        if not self.versioni:
            return None
        i = self.scelta if self.scelta is not None and 0 <= self.scelta < len(self.versioni) else len(self.versioni) - 1
        return self.versioni[i]


# ---------------------------------------------------------------- archivio

class ArchivioFumetto:
    def __init__(self, progetti):
        self.progetti = progetti

    def cartella(self, pid: str) -> Path:
        return self.progetti.cartella(pid) / "fumetto"

    def leggi(self, pid: str) -> Fumetto:
        self.progetti.leggi(pid)
        try:
            return Fumetto.model_validate_json((self.cartella(pid) / "fumetto.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Fumetto()

    def salva(self, pid: str, f: Fumetto) -> Fumetto:
        self.progetti.leggi(pid)
        ids = [v.id for p in f.pagine for v in p.vignette]
        if len(ids) != len(set(ids)):
            raise ErroreProgetto("Due vignette hanno lo stesso identificativo")
        _scrivi(self.cartella(pid) / "fumetto.json", f.model_dump())
        return f

    def immagini(self, pid: str) -> dict[str, ImmaginiVignetta]:
        try:
            dati = json.loads((self.cartella(pid) / "immagini.json").read_text(encoding="utf-8"))
            return {k: ImmaginiVignetta(**v) for k, v in dati.items()}
        except (OSError, ValueError):
            return {}

    def _salva_immagini(self, pid: str, tutte: dict[str, ImmaginiVignetta]):
        _scrivi(self.cartella(pid) / "immagini.json", {k: v.model_dump() for k, v in tutte.items()})

    def aggiungi_versione(self, pid: str, vid: str, dati: bytes, seme: int, prompt: str) -> ImmaginiVignetta:
        with _lock:
            d = self.cartella(pid) / "vignette"
            d.mkdir(parents=True, exist_ok=True)
            tutte = self.immagini(pid)
            iv = tutte.get(vid, ImmaginiVignetta())
            nome = f"{vid}_{len(iv.versioni) + 1:02d}_{int(time.time())}.png"
            (d / nome).write_bytes(dati)
            iv.versioni.append(Versione(file=nome, seme=seme, prompt=prompt))
            iv.scelta = len(iv.versioni) - 1
            tutte[vid] = iv
            self._salva_immagini(pid, tutte)
            return iv

    def imposta_aderenza(self, pid: str, vid: str, indice: int, aderenza: dict):
        with _lock:
            tutte = self.immagini(pid)
            iv = tutte.get(vid)
            if iv and 0 <= indice < len(iv.versioni):
                iv.versioni[indice].aderenza = aderenza
                self._salva_immagini(pid, tutte)

    def scegli_versione(self, pid: str, vid: str, indice: int) -> ImmaginiVignetta:
        with _lock:
            tutte = self.immagini(pid)
            iv = tutte.get(vid)
            if not iv or not 0 <= indice < len(iv.versioni):
                raise ErroreProgetto("Versione inesistente", 404)
            iv.scelta = indice
            self._salva_immagini(pid, tutte)
            return iv

    def file(self, pid: str, nome: str) -> Path:
        if not re.fullmatch(r"[\w-]{1,80}\.png", nome):
            raise ErroreProgetto("Nome non valido", 404)
        f = self.cartella(pid) / "vignette" / nome
        if not f.exists():
            raise ErroreProgetto("Immagine non trovata", 404)
        return f

    def trova(self, f: Fumetto, vid: str) -> Vignetta:
        for p in f.pagine:
            for v in p.vignette:
                if v.id == vid:
                    return v
        raise ErroreProgetto("Vignetta non trovata", 404)


def _scrivi(f: Path, dati):
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(dati, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


# ---------------------------------------------------------------- prompt e workflow

def pulisci(t: str) -> str:
    return ", ".join(p.strip() for p in t.split(",") if p.strip())


def componi(modello: str, valori: dict[str, str]) -> str:
    return pulisci(re.sub(r"\{(\w+)\}", lambda m: valori.get(m.group(1), m.group(0)), modello))


def descrivi(p: Personaggio, con_lora: bool) -> str:
    """Il personaggio nel prompt: con il LoRA basta la trigger word, senza servono i tratti fissi."""
    return pulisci(f"{p.trigger}, {p.genere}" + ("" if con_lora else f", {p.descrizione}"))


def coppia(generi: list[str]) -> str:
    ragazze, ragazzi = generi.count("1girl"), generi.count("1boy")
    parti = []
    if ragazze:
        parti.append("1girl" if ragazze == 1 else f"{ragazze}girls")
    if ragazzi:
        parti.append("1boy" if ragazzi == 1 else f"{ragazzi}boys")
    return ", ".join(parti)


class Costruttore:
    """Costruisce il workflow API di una vignetta."""

    def __init__(self, imp: Impostazioni, qualita: tuple[str, str]):
        self.imp = imp
        self.qualita = qualita
        self.wf: dict[str, dict] = {}

    def n(self, classe: str, **ingressi) -> str:
        k = str(len(self.wf) + 1)
        self.wf[k] = {"class_type": classe, "inputs": ingressi}
        return k

    def lora(self, model, clip, nome, forza):
        k = self.n("LoraLoader", model=model, clip=clip, lora_name=nome, strength_model=forza, strength_clip=forza)
        return [k, 0], [k, 1]

    def testo(self, clip, t):
        return [self.n("CLIPTextEncode", clip=clip, text=t), 0]

    def campiona(self, model, pos, neg, latente, seme, denoise=1.0):
        i = self.imp
        return [self.n("KSampler", model=model, positive=pos, negative=neg, latent_image=latente, seed=seme,
                       steps=i.passi, cfg=i.cfg, sampler_name=i.sampler, scheduler=i.scheduler, denoise=denoise), 0]

    def costruisci(self, v: Vignetta, pers: list[Personaggio], lora: dict[str, str | None], seme: int,
                   scena: "PromptScena | None" = None) -> tuple[dict, str, str]:
        """Restituisce (workflow, id del nodo di salvataggio, prompt principale).

        Con `scena` (ricavata dalla descrizione) la scena è quella del testo, e ogni personaggio riceve nella sua
        zona la sua azione, posa ed espressione; `v.azione` si aggiunge in fondo."""
        imp = self.imp
        azione = pulisci(f"{scena.globale}, {v.azione}") if scena else v.azione
        extra = scena.per_personaggio if scena else {}
        da_solo = "" if scena and scena.altri_soggetti else ", solo"

        def chi(p: Personaggio) -> str:
            return pulisci(f"{descrivi(p, bool(lora.get(p.id)))}, {extra.get(p.id, '')}")
        if not imp.checkpoint:
            raise ErroreProgetto("Scegli il checkpoint del fumetto nelle impostazioni.")
        W, H = DIMENSIONI[v.formato]
        val = {"qualita": self.qualita[0], "negativo_qualita": self.qualita[1]}
        stile = componi(imp.positivo, val)
        negativo = componi(imp.negativo, val)
        if scena and scena.negativo:
            negativo = pulisci(f"{negativo}, {scena.negativo}")
        ck = self.n("CheckpointLoaderSimple", ckpt_name=imp.checkpoint)
        m0, c0, vae = [ck, 0], [ck, 1], [ck, 2]
        if imp.lora_stile:
            m0, c0 = self.lora(m0, c0, imp.lora_stile, imp.forza_stile)
        lat = [self.n("EmptyLatentImage", width=W, height=H, batch_size=1), 0]

        if len(pers) <= 1:
            model, clip = m0, c0
            soggetto = "" if scena and scena.altri_soggetti else "no humans, scenery"
            if pers:
                p = pers[0]
                if lora.get(p.id):
                    model, clip = self.lora(model, clip, lora[p.id], imp.forza_personaggio)
                soggetto = f"{chi(p)}{da_solo}"
            prompt = pulisci(f"{stile}, {soggetto}, {azione}")
            ks = self.campiona(model, self.testo(clip, prompt), self.testo(clip, negativo), lat, seme)
            dec = self.n("VAEDecode", samples=ks, vae=vae)
            return self.wf, self.n("SaveImage", images=[dec, 0], filename_prefix="comic_studio/fumetto"), prompt

        # --- più personaggi: una zona verticale per ciascuno, da sinistra a destra
        n = len(pers)
        spazio = 64 if n == 2 else 40
        larg = (W - spazio * (n - 1)) // n
        vuota = self.n("SolidMask", value=0.0, width=W, height=H)
        blocco = self.n("SolidMask", value=1.0, width=larg, height=H)
        zone, sfumate = [], []
        for i in range(n):
            x = i * (larg + spazio)
            z = self.n("MaskComposite", destination=[vuota, 0], source=[blocco, 0], x=x, y=0, operation="add")
            zone.append([z, 0])
            sfumate.append([self.n("FeatherMask", mask=[z, 0], left=0 if i == 0 else 64, top=0,
                                   right=0 if i == n - 1 else 64, bottom=0), 0])
        mc, cc = m0, c0
        for p in pers:
            if lora.get(p.id):
                mc, cc = self.lora(mc, cc, lora[p.id], round(imp.forza_personaggio * 0.55, 2))
        posizioni = ["on the left", "on the right"] if n == 2 else ["on the left", "in the center", "on the right"]
        dove = ", ".join(f"{p.trigger} {posizioni[i]}" for i, p in enumerate(pers))
        prompt = pulisci(f"{stile}, {coppia([p.genere for p in pers])}, {n} people, {dove}, {azione}")
        pos = self.testo(cc, prompt)
        for i, p in enumerate(pers):
            reg = self.testo(cc, chi(p))
            zona = [self.n("ConditioningSetMask", conditioning=reg, mask=zone[i], strength=0.85,
                           set_cond_area="default"), 0]
            pos = [self.n("ConditioningCombine", conditioning_1=pos, conditioning_2=zona), 0]
        neg = self.testo(cc, negativo + ", extra people, crowd")
        ks = self.campiona(mc, pos, neg, lat, seme)
        img = [self.n("VAEDecode", samples=ks, vae=vae), 0]
        for i, p in enumerate(pers):
            mp, cp = m0, c0
            if lora.get(p.id):
                mp, cp = self.lora(m0, c0, lora[p.id], imp.forza_personaggio)
            pp = self.testo(cp, pulisci(f"{stile}, {chi(p)}, solo, {azione}"))
            nn = self.testo(cp, negativo)
            inp = self.n("InpaintModelConditioning", positive=pp, negative=nn, vae=vae, pixels=img, mask=sfumate[i],
                         noise_mask=True)
            k2 = self.campiona(mp, [inp, 0], [inp, 1], [inp, 2], seme + 1 + i, denoise=imp.ripasso)
            d2 = self.n("VAEDecode", samples=k2, vae=vae)
            img = [self.n("ImageCompositeMasked", destination=img, source=[d2, 0], x=0, y=0, resize_source=False,
                          mask=sfumate[i]), 0]
        return self.wf, self.n("SaveImage", images=img, filename_prefix="comic_studio/fumetto"), prompt


# ---------------------------------------------------------------- balloon e impaginazione

FONT_CANDIDATI = [
    "C:/Windows/Fonts/comicbd.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Chalkboard.ttc", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def carica_font(preferito: str | None, dim: int):
    for f in ([preferito] if preferito else []) + FONT_CANDIDATI:
        try:
            return ImageFont.truetype(f, dim)
        except OSError:
            continue
    try:
        return ImageFont.load_default(dim)
    except TypeError:
        return ImageFont.load_default()


def a_capo(testo: str, font, larghezza: int) -> list[str]:
    righe, riga = [], ""
    for parola in testo.split():
        prova = f"{riga} {parola}".strip()
        if font.getlength(prova) <= larghezza or not riga:
            riga = prova
        else:
            righe.append(riga)
            riga = parola
    if riga:
        righe.append(riga)
    return righe


def disegna_balloon(img: Image.Image, v: Vignetta, font_pref: str | None) -> Image.Image:
    if not any(d.testo.strip() for d in v.dialoghi):
        return img
    img = img.convert("RGB").copy()
    d = ImageDraw.Draw(img)
    W, H = img.size
    scala = W / DIMENSIONI[v.formato][0]
    font = carica_font(font_pref, max(14, round((34 if W > H else 30) * scala)))
    alt_riga = font.getbbox("Ag")[3] + round(8 * scala)
    pad, bordo = round(22 * scala), max(2, round(4 * scala))
    max_l = int(W * (0.40 if W > H else 0.72))
    margine = round(24 * scala)
    occupato = {"alto-sx": margine, "alto-dx": margine, "basso-sx": H - margine, "basso-dx": H - margine}
    for dial in v.dialoghi:
        if not dial.testo.strip():
            continue
        pos = dial.posizione
        if pos == "auto":
            if dial.chi in v.personaggi and len(v.personaggi) > 1:
                pos = "alto-sx" if v.personaggi.index(dial.chi) < len(v.personaggi) / 2 else "alto-dx"
            else:
                pos = "alto-sx"
        righe = a_capo(dial.testo.strip(), font, max_l - 2 * pad)
        bw = int(max(font.getlength(r) for r in righe)) + 2 * pad
        bh = len(righe) * alt_riga + 2 * pad - round(8 * scala)
        x = margine if pos.endswith("sx") else W - margine - bw
        coda = round(55 * scala)
        if pos.startswith("alto"):
            y = occupato[pos]
            occupato[pos] = y + bh + (round(24 * scala) if dial.chi == "narratore" else coda + round(20 * scala))
        else:
            y = occupato[pos] - bh - (0 if dial.chi == "narratore" else coda)
            occupato[pos] = y - round(20 * scala)
        if dial.chi == "narratore":
            d.rectangle([x, y, x + bw, y + bh], fill=(255, 244, 176), outline="black", width=bordo)
        else:
            d.rounded_rectangle([x, y, x + bw, y + bh], radius=min(round(34 * scala), bh // 2), fill="white",
                                outline="black", width=bordo)
            cx = x + bw // 3 if pos.endswith("sx") else x + 2 * bw // 3
            verso = -1 if pos.endswith("sx") else 1
            if pos.startswith("alto"):
                base_y, punta = y + bh - bordo, (cx + verso * round(30 * scala), y + bh + coda)
            else:
                base_y, punta = y + bordo, (cx + verso * round(30 * scala), y - coda)
            mezzo = round(18 * scala)
            d.polygon([(cx - mezzo, base_y), (cx + mezzo, base_y), punta], fill="white")
            d.line([(cx - mezzo, base_y), punta], fill="black", width=bordo)
            d.line([(cx + mezzo, base_y), punta], fill="black", width=bordo)
        for i, r in enumerate(righe):
            d.text((x + pad, y + pad + i * alt_riga), r, font=font, fill="black")
    return img


def segnaposto(v: Vignetta, nomi: dict[str, str]) -> Image.Image:
    W, H = DIMENSIONI[v.formato]
    img = Image.new("RGB", (W, H), (214, 214, 220))
    d = ImageDraw.Draw(img)
    chi = " + ".join(nomi.get(p, p) for p in v.personaggi) or "scena senza personaggi"
    font = carica_font(None, 36)
    d.text((48, H // 2 - 40), chi, font=font, fill=(60, 60, 70))
    for i, r in enumerate(a_capo(v.descrizione or v.azione or "da descrivere", carica_font(None, 26), W - 96)[:4]):
        d.text((48, H // 2 + 10 + i * 34), r, font=carica_font(None, 26), fill=(90, 90, 100))
    return img


def righe_pagina(p: Pagina) -> list[list[Vignetta]]:
    """Due vignette alte di fila stanno affiancate; le altre occupano una riga intera."""
    righe, i = [], 0
    while i < len(p.vignette):
        v = p.vignette[i]
        if v.formato == "alta" and i + 1 < len(p.vignette) and p.vignette[i + 1].formato == "alta":
            righe.append([v, p.vignette[i + 1]])
            i += 2
        else:
            righe.append([v])
            i += 1
    return righe


def componi_pagina(p: Pagina, immagine_di, imp: Impostazioni) -> Image.Image:
    """immagine_di(vignetta) -> PIL.Image già con i balloon."""
    L, m = imp.larghezza_pagina, imp.margine
    interna = L - 2 * m
    pezzi = []
    for riga in righe_pagina(p):
        if len(riga) == 2:
            w = (interna - m) // 2
            h = round(w * DIMENSIONI["alta"][1] / DIMENSIONI["alta"][0])
            pezzi.append((h, [(riga[0], m, w, h), (riga[1], m * 2 + w, w, h)]))
        else:
            v = riga[0]
            dw, dh = DIMENSIONI[v.formato]
            if v.formato == "larga":
                w = interna
            else:
                w = min(interna, round(interna * (0.5 if v.formato == "alta" else 0.62)))
            h = round(w * dh / dw)
            pezzi.append((h, [(v, (L - w) // 2, w, h)]))
    altezza = m + sum(h + m for h, _ in pezzi)
    pagina = Image.new("RGB", (L, max(altezza, 200)), "white")
    d = ImageDraw.Draw(pagina)
    y = m
    for h, celle in pezzi:
        for v, x, w, hh in celle:
            img = immagine_di(v).convert("RGB").resize((w, hh), Image.LANCZOS)
            pagina.paste(img, (x, y))
            d.rectangle([x - 2, y - 2, x + w + 1, y + hh + 1], outline="black", width=5)
        y += h + m
    return pagina


def pdf(pagine: list[Image.Image]) -> bytes:
    b = io.BytesIO()
    pagine[0].save(b, "PDF", save_all=True, append_images=pagine[1:], resolution=200.0)
    return b.getvalue()


# ---------------------------------------------------------------- importazione da testo

def importa_storia(testo: str, personaggi: list[Personaggio]) -> list[Pagina]:
    """Formato: una vignetta per riga  «formato | personaggi | azione | chi: battuta | …»; «---» = nuova pagina.
    I personaggi si indicano per nome, id o trigger, separati da «+»; «nessuno» per le scene vuote."""
    alias = {}
    for p in personaggi:
        for k in (p.id, p.nome, p.trigger):
            alias[k.lower()] = p.id
    pagine, errori = [Pagina()], []
    for nr, riga in enumerate(testo.splitlines(), 1):
        r = riga.strip()
        if not r or r.startswith("#"):
            continue
        if r.startswith("---"):
            if pagine[-1].vignette:
                pagine.append(Pagina())
            continue
        campi = [c.strip() for c in r.split("|")]
        if len(campi) < 3:
            errori.append(f"riga {nr}: servono almeno 3 campi separati da |")
            continue
        formato = campi[0].lower()
        if formato not in DIMENSIONI:
            errori.append(f"riga {nr}: formato «{campi[0]}» sconosciuto (larga, alta, quadrata)")
            continue
        chi = [] if campi[1].lower() in ("", "-", "nessuno") else [c.strip().lower() for c in campi[1].split("+")]
        ignoti = [c for c in chi if c not in alias]
        if ignoti:
            errori.append(f"riga {nr}: personaggi sconosciuti: {', '.join(ignoti)}")
            continue
        if len(chi) > 3:
            errori.append(f"riga {nr}: al massimo 3 personaggi per vignetta")
            continue
        dialoghi = []
        for dd in campi[3:]:
            if ":" not in dd:
                continue
            parla, frase = (x.strip() for x in dd.split(":", 1))
            dialoghi.append(Dialogo(chi=alias.get(parla.lower(), "narratore"), testo=frase))
        pagine[-1].vignette.append(Vignetta(formato=formato, personaggi=[alias[c] for c in chi], azione=campi[2],
                                            dialoghi=dialoghi))
    if errori:
        raise ErroreProgetto("Storia non valida: " + "; ".join(errori[:6]))
    return [p for p in pagine if p.vignette]
