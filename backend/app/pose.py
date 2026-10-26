"""Libreria delle pose guidate: scheletri OpenPose disegnati da Comic Studio, senza preprocessori.

Ogni posa è descritta con poche misure (rotazione del corpo, inclinazione del busto, angoli di braccia e gambe) e da
queste si calcolano i 18 punti del formato OpenPose (COCO). Il disegno segue quello dei preprocessori di ControlNet
(stessi colori, stessi segmenti, fondo nero), così il ControlNet OpenPose lo legge come uno scheletro estratto da una
foto. Lo scheletro si taglia in base all'inquadratura: per un primo piano restano testa e spalle.

Convenzioni:
  - unità u = altezza della testa; origine al centro delle anche; y verso il basso
  - angoli in gradi, nell'immagine: 0 = verso il basso, 90 = verso destra, -90 = verso sinistra, 180 = verso l'alto
  - rotazione (yaw): 0 = di fronte, positivo = il personaggio si gira verso la destra dell'immagine, 180 = di spalle
  - destra e sinistra dei punti sono quelle del personaggio (di fronte la sua destra è a sinistra nell'immagine)
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

# indici OpenPose (COCO 18)
NASO, COLLO, SPALLA_D, GOMITO_D, POLSO_D, SPALLA_S, GOMITO_S, POLSO_S = range(8)
ANCA_D, GINOCCHIO_D, CAVIGLIA_D, ANCA_S, GINOCCHIO_S, CAVIGLIA_S, OCCHIO_D, OCCHIO_S, ORECCHIO_D, ORECCHIO_S = range(8, 18)

# segmenti e colori dei preprocessori OpenPose di ControlNet (annotator/openpose/util.py), indici da 0
SEGMENTI = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
            (1, 0), (0, 14), (14, 16), (0, 15), (15, 17)]
COLORI = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0),
          (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255),
          (170, 0, 255), (255, 0, 255), (255, 0, 85), (255, 0, 85)]
# per specchiare: destra ↔ sinistra
SCAMBIO = [0, 1, 5, 6, 7, 2, 3, 4, 11, 12, 13, 8, 9, 10, 15, 14, 17, 16]

# proporzioni (in teste): collo → anche, mezza larghezza di spalle e anche, braccia e gambe
BUSTO, SPALLE, ANCHE = 2.7, 0.95, 0.6
OMERO, AVAMBRACCIO, FEMORE, TIBIA = 1.35, 1.2, 1.9, 1.85

Punto = tuple[float, float] | None
Arto = tuple[float, float] | tuple[float, float, float, float]   # (angolo 1, angolo 2[, scala 1, scala 2])


def _dir(angolo: float) -> tuple[float, float]:
    a = math.radians(angolo)
    return math.sin(a), math.cos(a)


@dataclass(frozen=True)
class Posa:
    id: str
    nome: str                       # in italiano, per l'interfaccia
    tag: str                        # per il prompt
    vista: str                      # angolazione per il prompt (sostituisce quella delle varianti)
    rotazione: float = 0            # yaw del corpo
    testa: float = 0                # yaw della testa rispetto al corpo
    busto: float = 0                # inclinazione del busto (positivo: la testa va a destra)
    braccio_d: Arto = (-10, -6)
    braccio_s: Arto = (10, 6)
    gamba_d: Arto = (-3, 0)
    gamba_s: Arto = (3, 0)
    di_spalle: bool = False         # nei primi piani non si usa (come le angolazioni «from behind»)
    figura_intera: bool = True      # la posa ha senso solo con le gambe (seduta, in ginocchio…)
    specchiata: bool = False

    def punti(self) -> list[Punto]:
        return punti(self)


def _arto(radice: tuple[float, float], arto: Arto, l1: float, l2: float) -> tuple[tuple[float, float], tuple[float, float]]:
    a1, a2 = arto[0], arto[1]
    s1, s2 = (arto[2], arto[3]) if len(arto) == 4 else (1.0, 1.0)
    d1, d2 = _dir(a1), _dir(a2)
    medio = (radice[0] + d1[0] * l1 * s1, radice[1] + d1[1] * l1 * s1)
    fine = (medio[0] + d2[0] * l2 * s2, medio[1] + d2[1] * l2 * s2)
    return medio, fine


def punti(p: Posa) -> list[Punto]:
    """I 18 punti OpenPose della posa, in teste, con l'origine al centro delle anche (None = non visibile)."""
    pt: list[Punto] = [None] * 18
    yaw = math.radians(p.rotazione)
    lato = math.cos(yaw)
    if abs(lato) < 0.25:                               # di profilo le spalle non coincidono del tutto
        lato = 0.25 if lato >= 0 else -0.25
    inc = math.radians(p.busto)
    asse = (math.sin(inc), -math.cos(inc))             # dalle anche verso il collo
    perp = (math.cos(inc), math.sin(inc))
    collo = (asse[0] * BUSTO, asse[1] * BUSTO)
    pt[COLLO] = collo
    pt[SPALLA_D] = (collo[0] - perp[0] * SPALLE * lato, collo[1] - perp[1] * SPALLE * lato)
    pt[SPALLA_S] = (collo[0] + perp[0] * SPALLE * lato, collo[1] + perp[1] * SPALLE * lato)
    pt[ANCA_D] = (-ANCHE * lato, 0.0)
    pt[ANCA_S] = (ANCHE * lato, 0.0)
    pt[GOMITO_D], pt[POLSO_D] = _arto(pt[SPALLA_D], p.braccio_d, OMERO, AVAMBRACCIO)
    pt[GOMITO_S], pt[POLSO_S] = _arto(pt[SPALLA_S], p.braccio_s, OMERO, AVAMBRACCIO)
    pt[GINOCCHIO_D], pt[CAVIGLIA_D] = _arto(pt[ANCA_D], p.gamba_d, FEMORE, TIBIA)
    pt[GINOCCHIO_S], pt[CAVIGLIA_S] = _arto(pt[ANCA_S], p.gamba_s, FEMORE, TIBIA)

    # testa: punti su un cerchio visto dall'alto, girato di yaw (corpo + testa); visibili se rivolti verso di noi
    yh = math.radians(p.rotazione + p.testa)
    centro = (collo[0] + asse[0] * 0.85, collo[1] + asse[1] * 0.85)

    def su_testa(phi: float, raggio: float, dy: float, soglia: float) -> Punto:
        a = math.radians(phi) + yh
        if math.cos(a) < soglia:
            return None
        return centro[0] + raggio * math.sin(a), centro[1] + dy

    pt[NASO] = su_testa(0, 0.5, 0.05, -0.1)
    pt[OCCHIO_D] = su_testa(-35, 0.45, -0.15, -0.05)
    pt[OCCHIO_S] = su_testa(35, 0.45, -0.15, -0.05)
    pt[ORECCHIO_D] = su_testa(-95, 0.45, -0.1, -0.5)
    pt[ORECCHIO_S] = su_testa(95, 0.45, -0.1, -0.5)
    if p.specchiata:
        pt = [None if q is None else (-q[0], q[1]) for q in pt]
        pt = [pt[SCAMBIO[i]] for i in range(18)]
    return pt


def specchia(p: Posa) -> Posa:
    from dataclasses import replace
    return replace(p, id=p.id + "-specchiata", nome=p.nome + " (specchiata)", specchiata=not p.specchiata)


# ---------------------------------------------------------------- libreria

POSE: list[Posa] = [
    Posa("in-piedi", "In piedi", "standing", "front view"),
    Posa("tre-quarti", "Tre quarti", "standing", "three-quarter view", rotazione=35,
         braccio_d=(-6, -3), braccio_s=(10, 6), gamba_d=(-2, 0), gamba_s=(6, 2)),
    Posa("profilo", "Di profilo", "standing", "from side, profile", rotazione=80,
         braccio_d=(8, 15), braccio_s=(-5, 0), gamba_d=(4, 0), gamba_s=(-4, 0)),
    Posa("di-spalle", "Di spalle", "standing", "from behind", rotazione=180,
         braccio_d=(10, 6), braccio_s=(-10, -6), di_spalle=True),
    Posa("sguardo-indietro", "Si volta a guardare", "standing, looking back", "from behind, looking back",
         rotazione=160, testa=-75, braccio_d=(12, 8), braccio_s=(-8, -4), gamba_d=(5, 0), gamba_s=(-3, 2),
         di_spalle=True),
    Posa("mani-fianchi", "Mani sui fianchi", "hands on hips", "front view",
         braccio_d=(-40, 45), braccio_s=(40, -45), gamba_d=(-8, -2), gamba_s=(8, 2)),
    Posa("braccia-conserte", "Braccia conserte", "crossed arms", "front view", rotazione=10,
         braccio_d=(-8, 110), braccio_s=(8, -110), gamba_d=(-4, 0), gamba_s=(4, 0)),
    Posa("saluto", "Saluta con la mano", "waving", "front view",
         braccio_d=(-110, -170), braccio_s=(10, 5), gamba_d=(-4, 0), gamba_s=(4, 2)),
    Posa("indica", "Indica di lato", "pointing to the side", "front view", rotazione=15,
         braccio_d=(-85, -88), braccio_s=(8, 4), gamba_d=(-5, 0), gamba_s=(4, 0)),
    Posa("braccia-alzate", "Braccia alzate", "arms up", "front view",
         braccio_d=(-160, -175), braccio_s=(160, 175), gamba_d=(-4, 0), gamba_s=(4, 0)),
    Posa("mano-dietro-testa", "Mano dietro la testa", "hand behind head", "front view", busto=-3,
         braccio_d=(-135, 100), braccio_s=(8, 4), gamba_d=(-6, 0), gamba_s=(2, 6)),
    Posa("pensierosa", "Mano al mento", "hand on own chin, thinking", "front view", rotazione=10, testa=-10,
         braccio_d=(-15, 145, 0.5, 1.0), braccio_s=(5, -100), gamba_d=(-3, 0), gamba_s=(5, 3)),
    Posa("camminata", "Cammina", "walking", "three-quarter view", rotazione=30,
         braccio_d=(-15, -10), braccio_s=(15, 25), gamba_d=(18, 5), gamba_s=(-15, -25)),
    Posa("corsa", "Corre", "running", "from side", rotazione=70, busto=12,
         braccio_d=(-50, 20), braccio_s=(45, 150), gamba_d=(70, 5), gamba_s=(-30, -120)),
    Posa("salto", "Salta", "jumping", "front view",
         braccio_d=(-140, -160), braccio_s=(140, 160), gamba_d=(-25, 25), gamba_s=(25, -25)),
    Posa("seduta", "Seduta", "sitting, chair", "front view", rotazione=15,
         braccio_d=(-5, 10), braccio_s=(5, -10), gamba_d=(-35, -5, 0.3, 1.0), gamba_s=(35, 5, 0.3, 1.0),
         figura_intera=False),
    Posa("seduta-profilo", "Seduta di profilo", "sitting, chair", "from side", rotazione=75,
         braccio_d=(10, 70), braccio_s=(5, 60), gamba_d=(88, 5), gamba_s=(85, 0), figura_intera=False),
    Posa("in-ginocchio", "In ginocchio", "kneeling", "three-quarter view", rotazione=55,
         braccio_d=(8, 25), braccio_s=(-2, 15), gamba_d=(4, -88, 1.0, 0.9), gamba_s=(-2, -84, 1.0, 0.9),
         figura_intera=False),
    Posa("accovacciata", "Accovacciata", "squatting", "front view",
         braccio_d=(-25, -20), braccio_s=(25, 20), gamba_d=(-70, 8, 0.7, 1.0), gamba_s=(70, -8, 0.7, 1.0),
         figura_intera=False),
]
PER_ID = {p.id: p for p in POSE}


def trova(id_: str) -> Posa:
    """La posa con questo id (anche «<id>-specchiata»)."""
    if id_ in PER_ID:
        return PER_ID[id_]
    if id_.endswith("-specchiata") and id_.removesuffix("-specchiata") in PER_ID:
        return specchia(PER_ID[id_.removesuffix("-specchiata")])
    raise KeyError(id_)


def elenco(con_specchiate: bool = False) -> list[Posa]:
    return [q for p in POSE for q in ((p, specchia(p)) if con_specchiate else (p,))]


# ---------------------------------------------------------------- inquadrature

TAGLI = ("intera", "tre_quarti", "mezzo_busto", "primo_piano")


def taglio(testo: str) -> str:
    """Il taglio dello scheletro per un'inquadratura del dataset (dal suo testo o dal suo nome)."""
    t = testo.lower()
    if re.search(r"full body|figura intera|wide shot", t):
        return "intera"
    if re.search(r"cowboy|tre quarti|thighs", t):
        return "tre_quarti"
    if re.search(r"portrait|close-?up|face|primo piano|head", t):
        return "primo_piano"
    if re.search(r"upper body|busto|half body", t):
        return "mezzo_busto"
    return "intera"


def _limiti(pt: list[Punto], taglio_: str) -> tuple[float, float]:
    """Dall'alto in basso (in teste) la parte dello scheletro da far entrare nell'immagine."""
    visibili = [q for q in pt if q]
    testa = [q for q in (pt[NASO], pt[OCCHIO_D], pt[OCCHIO_S], pt[ORECCHIO_D], pt[ORECCHIO_S]) if q]
    cima_testa = (min(q[1] for q in testa) if testa else pt[COLLO][1] - 1.0) - 0.75
    # le mani alzate sopra la testa restano dentro
    alto = min(cima_testa, min(q[1] for q in visibili) - 0.3)
    collo = pt[COLLO][1]
    anche = (pt[ANCA_D][1] + pt[ANCA_S][1]) / 2
    if taglio_ == "primo_piano":
        return cima_testa - 0.15, collo + 0.6
    if taglio_ == "mezzo_busto":
        return alto, collo + 2.3
    if taglio_ == "tre_quarti":
        return alto, anche + 1.3
    return alto, max(q[1] for q in visibili) + 0.35


def disegna(p: Posa, larghezza: int, altezza: int, taglio_: str = "intera") -> Image.Image:
    """Lo scheletro OpenPose della posa su fondo nero, centrato e tagliato per l'inquadratura."""
    pt = punti(p)
    alto, basso = _limiti(pt, taglio_)
    margine = 0.05 * altezza
    scala = (altezza - 2 * margine) / (basso - alto)
    visibili = [q for q in pt if q]
    if taglio_ == "intera":                          # tutta la figura deve entrare anche in larghezza
        larga = max(q[0] for q in visibili) - min(q[0] for q in visibili) + 1.0
        scala = min(scala, (larghezza - 2 * margine) / larga)
        cx = (max(q[0] for q in visibili) + min(q[0] for q in visibili)) / 2
    else:
        cx = pt[COLLO][0]
    y0 = margine + ((altezza - 2 * margine) - (basso - alto) * scala) / 2 if taglio_ == "intera" else margine

    def xy(q):
        return larghezza / 2 + (q[0] - cx) * scala, y0 + (q[1] - alto) * scala

    pix = [None if q is None else xy(q) for q in pt]
    img = Image.new("RGB", (larghezza, altezza), (0, 0, 0))
    d = ImageDraw.Draw(img)
    spessore = max(4.0, 4.0 * min(larghezza, altezza) / 512)
    for i, (a, b) in enumerate(SEGMENTI):
        if pix[a] is None or pix[b] is None:
            continue
        (x1, y1), (x2, y2) = pix[a], pix[b]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        lung = math.hypot(x2 - x1, y2 - y1) / 2
        ang = math.atan2(y2 - y1, x2 - x1)
        poligono = []
        for k in range(36):                           # ellisse allungata come cv2.ellipse2Poly
            t = 2 * math.pi * k / 36
            ex, ey = lung * math.cos(t), spessore * math.sin(t)
            poligono.append((mx + ex * math.cos(ang) - ey * math.sin(ang), my + ex * math.sin(ang) + ey * math.cos(ang)))
        d.polygon(poligono, fill=tuple(int(c * 0.6) for c in COLORI[i]))
    raggio = spessore
    for i, q in enumerate(pix):
        if q is not None:
            d.ellipse((q[0] - raggio, q[1] - raggio, q[0] + raggio, q[1] + raggio), fill=COLORI[i])
    return img


def png(p: Posa, larghezza: int, altezza: int, taglio_: str = "intera") -> bytes:
    buf = io.BytesIO()
    disegna(p, larghezza, altezza, taglio_).save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- scelta delle pose per il dataset

@dataclass
class Rotazione:
    """Sceglie le pose a turno, la meno usata tra quelle adatte all'inquadratura, così tutte compaiono."""
    pose: list[Posa]
    uso: dict[str, int] = field(default_factory=dict)

    def prossima(self, taglio_: str) -> Posa | None:
        adatte = [p for p in self.pose if not (taglio_ == "primo_piano" and p.di_spalle)]
        if not adatte:
            return None
        p = min(adatte, key=lambda q: (self.uso.get(q.id, 0), self.pose.index(q)))
        self.uso[p.id] = self.uso.get(p.id, 0) + 1
        return p


def info(p: Posa) -> dict:
    return {"id": p.id, "nome": p.nome, "tag": p.tag, "vista": p.vista, "di_spalle": p.di_spalle,
            "figura_intera": p.figura_intera, "specchiata": p.specchiata}


__all__ = ["POSE", "Posa", "Rotazione", "disegna", "elenco", "info", "png", "specchia", "taglio", "trova"]
