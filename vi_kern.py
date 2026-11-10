"""
Rechenkern der Vegetationsindex-Auswertung (ohne Oberfläche)
=============================================================

Laden einer MicaSense-RedEdge-P-Einzelaufnahme, Berechnung von NDVI, NDRE, ReNDVI und GNDVI,
Maskierung, pixelweise Statistik und Export.

Die Vorverarbeitung (Rohwert -> Reflektanz über DLS 2, Entzerrung, Kanalausrichtung) wird NICHT neu
implementiert, sondern aus dem bereits geprüften Skript `multispektral_stapeln.py` übernommen
(Pfad unten in STAPEL_SKRIPT). So liefern Software und Stapelskript identische Reflektanzen.

Der Kern kann auch ohne Oberfläche benutzt werden, z. B.:
    import vi_kern as vk
    a = vk.lade_aufnahme(r"...\\IMG_0100_1.tif")
    idx = vk.berechne_index(a.stapel, a.kanalindex, "NDVI")
"""

# =============================================================================
# EINSTELLUNGEN
# =============================================================================

# Geprüftes Vorverarbeitungsskript (Radiometrie, Entzerrung, Ausrichtung)
STAPEL_SKRIPT = r"C:\Users\joshu\OneDrive\Bachelorarbeit\Bilder\Flugtag130726\0029SET\000\multispektral_stapeln.py"

# Name des Unterordners mit vorhandenen Reflektanzbildern (Ausgabe von multispektral_stapeln.py)
REFLEKTANZ_UNTERORDNER = "Reflektanz_5Kanal"

# Name des Ergebnis-Unterordners dieser Software (wird im Aufnahmeordner angelegt)
AUSWERTUNG_UNTERORDNER = "VI_Auswertung"

# Kanalzahl der Rohaufnahmen (Dateien IMG_XXXX_1 … _n je Aufnahme; in der Oberfläche vor dem Laden wählbar).
# None = automatisch (häufigste Dateizahl im Ordner). Welche Datei welcher Kanal ist, wird aus den Metadaten
# (Camera:BandName) gelesen – so funktionieren auch Sets mit 4 Kanälen oder mit zusätzlichem Panchro-Kanal (_6).
KANALZAHL = None
KANALZAHL_AUSWAHL = {"automatisch": None, "4 Kanäle": 4, "5 Kanäle": 5, "6 Kanäle (mit Panchro)": 6}
PANCHRO = "Panchro"            # Kanalname des panchromatischen Kanals der RedEdge-P
PANCHRO_SCHAERFEN = False      # Panchro zum Schärfen verwenden (sonst wird er ignoriert)
PANCHRO_NUR_KRONEN = True      # ab 0.14: geschärftes Bild nur für Maske/Kronen/Anzeige; Indizes und Statistik aus den
                               # Original-Spektralkanälen (auf das feine Raster übertragen, Werte unverändert)

# Maskierung ungültiger Pixel (identisch zu den QGIS-Projekten, Doku Abschnitt 8.1)
MIN_NENNER = 0.01          # |Nenner| darunter -> instabil, maskiert
MIN_REFLEKTANZ = -0.02     # Reflektanz darunter -> unplausibel, maskiert

# Ausrichtung schätzen, falls für einen Ordner noch keine vorliegt
ANZAHL_KALIBRIER_AUFNAHMEN = 10

# RGB-Anzeige (wie im Stapelskript)
RGB_MAX_REFLEKTANZ = 0.12
RGB_GAMMA = 2.2

# =============================================================================

import csv
import datetime as _dt
import glob
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

import cv2
import numpy as np
import tifffile

VERSION = "0.20.3 (2026-11-09)"

# -----------------------------------------------------------------------------
# Vegetationsindizes (Formeln wie in Kapitel 2.3 der Arbeit)
# -----------------------------------------------------------------------------
# Kanalkürzel in den Formeln: B = Blau 475, G = Grün 560, R = Rot 668, RE = Red Edge 717, N = NIR 842 nm.
# Jeder Index = Zähler / Nenner. Pixel sind ungültig (NaN), wenn |Nenner| < MIN_NENNER, eine verwendete Reflektanz
# < MIN_REFLEKTANZ ist oder der Wert außerhalb des gültigen Bereichs liegt (bei normierten Differenzen nicht möglich).
#   formel   Anzeige (Unicode)        ascii   für TIFF-Beschreibungen
#   kanaele  verwendete Kanäle        bereich gültiger Wertebereich       skala  feste Farbskala der Anzeige
#   gruppe   Kernindizes der Arbeit (Kapitel 2.3) oder in Kapitel 3 erwähnte Indizes
INDIZES = {
    # --- Kernindizes (Kapitel 2.3, Formel 5–8)
    "NDVI":   dict(z=lambda b: b["NIR"] - b["Red"], n=lambda b: b["NIR"] + b["Red"],
                   formel="(NIR − Rot) / (NIR + Rot)", ascii="(NIR - Red) / (NIR + Red)",
                   kanaele=["NIR", "Red"], quelle="Rouse et al. (1974)", gruppe="Kern"),
    "NDRE":   dict(z=lambda b: b["NIR"] - b["Red edge"], n=lambda b: b["NIR"] + b["Red edge"],
                   formel="(NIR − Red Edge) / (NIR + Red Edge)", ascii="(NIR - RedEdge) / (NIR + RedEdge)",
                   kanaele=["NIR", "Red edge"], quelle="Barnes et al. (2000)", gruppe="Kern"),
    "ReNDVI": dict(z=lambda b: b["Red edge"] - b["Red"], n=lambda b: b["Red edge"] + b["Red"],
                   formel="(Red Edge − Rot) / (Red Edge + Rot)", ascii="(RedEdge - Red) / (RedEdge + Red)",
                   kanaele=["Red edge", "Red"], quelle="Wang (2021)", gruppe="Kern"),
    "GNDVI":  dict(z=lambda b: b["NIR"] - b["Green"], n=lambda b: b["NIR"] + b["Green"],
                   formel="(NIR − Grün) / (NIR + Grün)", ascii="(NIR - Green) / (NIR + Green)",
                   kanaele=["NIR", "Green"], quelle="Gitelson et al. (1996)", gruppe="Kern"),
    # --- weitere in der Arbeit (Kapitel 3) erwähnte Indizes
    "BNDVI":  dict(z=lambda b: b["NIR"] - b["Blue"], n=lambda b: b["NIR"] + b["Blue"],
                   formel="(NIR − Blau) / (NIR + Blau)", ascii="(NIR - Blue) / (NIR + Blue)",
                   kanaele=["NIR", "Blue"], quelle="verwendet u. a. von Klouček et al. (2024), Ecke et al. (2024)",
                   gruppe="Kapitel 3"),
    "SAVI":   dict(z=lambda b: 1.5 * (b["NIR"] - b["Red"]), n=lambda b: b["NIR"] + b["Red"] + 0.5,
                   formel="1,5 · (NIR − Rot) / (NIR + Rot + 0,5)   (L = 0,5)",
                   ascii="1.5 * (NIR - Red) / (NIR + Red + 0.5)", bereich=(-1.5, 1.5),
                   kanaele=["NIR", "Red"], quelle="Huete (1988)", gruppe="Kapitel 3"),
    "EVI":    dict(z=lambda b: 2.5 * (b["NIR"] - b["Red"]), n=lambda b: b["NIR"] + 6 * b["Red"] - 7.5 * b["Blue"] + 1,
                   formel="2,5 · (NIR − Rot) / (NIR + 6 · Rot − 7,5 · Blau + 1)",
                   ascii="2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)",
                   kanaele=["NIR", "Red", "Blue"], quelle="Huete et al. (2002)", gruppe="Kapitel 3"),
    "EVI2":   dict(z=lambda b: 2.5 * (b["NIR"] - b["Red"]), n=lambda b: b["NIR"] + 2.4 * b["Red"] + 1,
                   formel="2,5 · (NIR − Rot) / (NIR + 2,4 · Rot + 1)", ascii="2.5 * (NIR - Red) / (NIR + 2.4*Red + 1)",
                   kanaele=["NIR", "Red"], quelle="Jiang et al. (2008)", gruppe="Kapitel 3"),
    "VARI":   dict(z=lambda b: b["Green"] - b["Red"], n=lambda b: b["Green"] + b["Red"] - b["Blue"],
                   formel="(Grün − Rot) / (Grün + Rot − Blau)", ascii="(Green - Red) / (Green + Red - Blue)",
                   skala=(-0.2, 0.8), kanaele=["Green", "Red", "Blue"], quelle="Gitelson et al. (2002)",
                   gruppe="Kapitel 3"),
    "NGRDI":  dict(z=lambda b: b["Green"] - b["Red"], n=lambda b: b["Green"] + b["Red"],
                   formel="(Grün − Rot) / (Grün + Rot)", ascii="(Green - Red) / (Green + Red)",
                   skala=(-0.2, 0.8), kanaele=["Green", "Red"], quelle="Tucker (1979)", gruppe="Kapitel 3"),
    "GLI":    dict(z=lambda b: 2 * b["Green"] - b["Red"] - b["Blue"], n=lambda b: 2 * b["Green"] + b["Red"] + b["Blue"],
                   formel="(2 · Grün − Rot − Blau) / (2 · Grün + Rot + Blau)   (identisch mit VDVI)",
                   ascii="(2*Green - Red - Blue) / (2*Green + Red + Blue)",
                   skala=(-0.2, 0.8), kanaele=["Green", "Red", "Blue"],
                   quelle="Louhaichi et al. (2001); als VDVI bei Wang et al. (2015)", gruppe="Kapitel 3"),
}
for _d in INDIZES.values():
    _d.setdefault("bereich", (-1.0, 1.0))
    _d.setdefault("skala", (-0.2, 1.0))
    _d.setdefault("cmap", "RdYlGn")
BAUM_INDIZES = ["NDVI", "NDRE", "ReNDVI", "GNDVI"]   # feste Auswahl für die Merkmale des Baummodells
KANALNAMEN = ["Blue", "Green", "Red", "NIR", "Red edge"]   # Original-Reihenfolge _1 … _5


# -----------------------------------------------------------------------------
# Vorverarbeitungsskript einbinden
# -----------------------------------------------------------------------------
_ms = None


def stapelmodul():
    """Lädt multispektral_stapeln.py als Modul (nur Funktionen, main() wird nicht ausgeführt)."""
    global _ms
    if _ms is None:
        # ab 0.17.1: zuerst der eingestellte Pfad, sonst eine Kopie neben diesem Programm (digitaler Anhang,
        # anderer Rechner)
        kandidaten = [STAPEL_SKRIPT, os.path.join(os.path.dirname(os.path.abspath(__file__)), "multispektral_stapeln.py")]
        skript = next((p for p in kandidaten if os.path.exists(p)), None)
        if skript is None:
            raise FileNotFoundError("Vorverarbeitungsskript multispektral_stapeln.py nicht gefunden:\n"
                                    + "\n".join(kandidaten) + "\nPfad STAPEL_SKRIPT in vi_kern.py anpassen oder "
                                    "die Datei neben vi_kern.py legen.")
        spec = importlib.util.spec_from_file_location("multispektral_stapeln", skript)
        _ms = importlib.util.module_from_spec(spec)
        alt, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # kein __pycache__ im Datenordner
        try:
            spec.loader.exec_module(_ms)
        finally:
            sys.dont_write_bytecode = alt
    return _ms


# -----------------------------------------------------------------------------
# Aufnahmen finden
# -----------------------------------------------------------------------------
@dataclass
class Aufnahme:
    name: str                      # z. B. "IMG_0100"
    ordner: str                    # Ordner mit den Rohbildern
    stapel: np.ndarray             # (k, h, w) float32, Reflektanz der Spektralkanäle (ohne Panchro)
    kanalindex: dict               # Kanalname -> Index im Stapel
    quelle: str                    # Beschreibung der Datenherkunft
    meta: dict = field(default_factory=dict)
    maskenstapel: np.ndarray = None  # ab 0.14: geschärfter Stapel nur für Maske, Kronentrennung und Anzeige

    @property
    def geschaerft(self):
        return bool(self.meta.get("geschaerft", False))

    @property
    def kronenstapel(self):
        """Stapel für Maske, Kronentrennung und Anzeige (geschärft, falls vorhanden), sonst der Spektralstapel."""
        return self.stapel if self.maskenstapel is None else self.maskenstapel


def setze_kanalzahl(n):
    """Kanalzahl der Rohaufnahmen: None = automatisch, sonst 4, 5 oder 6 (Dateien je Aufnahme)."""
    global KANALZAHL
    KANALZAHL = n


def setze_panchro_schaerfen(an):
    global PANCHRO_SCHAERFEN
    PANCHRO_SCHAERFEN = bool(an)


def setze_panchro_nur_kronen(an):
    global PANCHRO_NUR_KRONEN
    PANCHRO_NUR_KRONEN = bool(an)


def gleiche_aufnahme(f, aufn):
    """Gehört eine gespeicherte Fläche (Training/Referenz) zu dieser Aufnahme in derselben Auflösung?
    Flächen sind in Pixelkoordinaten gespeichert; geschärfte Aufnahmen haben ein anderes Pixelraster."""
    return (f["aufnahme"] == aufn.name
            and os.path.normcase(os.path.normpath(f["ordner"])) == os.path.normcase(os.path.normpath(aufn.ordner))
            and bool(f.get("geschaerft", False)) == aufn.geschaerft)


def _ordner_und_name(pfad):
    """Rohbildordner und Aufnahmename aus einem Roh- oder Reflektanzbildpfad."""
    datei = os.path.basename(pfad)
    m = re.match(r"(IMG_\d+)_(\d)\.tif$", datei, re.I) or re.match(r"(IMG_\d+)_reflektanz\.tif$", datei, re.I)
    if not m:
        raise ValueError(f"Unbekannter Dateiname: {datei}\nErwartet IMG_XXXX_1.tif … _6.tif oder IMG_XXXX_reflektanz.tif")
    ordner = os.path.dirname(os.path.abspath(pfad))
    if os.path.basename(ordner).lower() == REFLEKTANZ_UNTERORDNER.lower():
        ordner = os.path.dirname(ordner)
    return ordner, m.group(1)


def _alle_rohdateien(ordner):
    """{Aufnahmename: {Dateinummer: Pfad}} aller Rohbilder eines Ordners (ohne Prüfung der Vollständigkeit)."""
    roh = {}
    for p in glob.glob(os.path.join(ordner, "IMG_*_*.tif")):
        m = re.match(r"(IMG_\d+)_(\d)\.tif$", os.path.basename(p), re.I)
        if m:
            roh.setdefault(m.group(1), {})[int(m.group(2))] = p
    return roh


def _soll_kanalzahl(roh):
    """Gewählte Kanalzahl bzw. (automatisch) die häufigste Dateizahl je Aufnahme im Ordner."""
    if KANALZAHL is not None or not roh:
        return KANALZAHL
    zaehl = Counter(len(v) for v in roh.values())
    return max(zaehl, key=lambda k: (zaehl[k], k))


def rohaufnahmen(ordner):
    """{Aufnahmename: {Dateinummer: Pfad}} der vollständigen Aufnahmen: genau _1 … _n vorhanden,
    n = gewählte Kanalzahl (bzw. automatisch die häufigste im Ordner). Unvollständige werden übersprungen."""
    roh = _alle_rohdateien(ordner)
    n = _soll_kanalzahl(roh)
    if not n:
        return {}
    return {name: dict(sorted(d.items())) for name, d in sorted(roh.items()) if sorted(d) == list(range(1, n + 1))}


def liste_aufnahmen(ordner):
    """Alle Aufnahmenamen eines Ordners (Rohbilder mit passender Kanalzahl oder fertige Reflektanzbilder;
    Letztere nur bei Kanalzahl „automatisch“ oder 5, da sie aus 5 Kanälen bestehen)."""
    namen = set(rohaufnahmen(ordner))
    if KANALZAHL in (None, 5):
        for p in glob.glob(os.path.join(ordner, REFLEKTANZ_UNTERORDNER, "IMG_*_reflektanz.tif")):
            namen.add(os.path.basename(p)[:-len("_reflektanz.tif")])
    return sorted(namen)


def kanal_uebersicht(wurzel):
    """Counter {Dateien je Aufnahme: Anzahl Aufnahmen} unterhalb von `wurzel` – für Hinweise, wenn mit der
    gewählten Kanalzahl nichts gefunden wird."""
    zaehl = Counter()
    for ordner, unterordner, _ in os.walk(wurzel):
        unterordner[:] = [u for u in unterordner if u.lower() not in (REFLEKTANZ_UNTERORDNER.lower(),
                                                                     AUSWERTUNG_UNTERORDNER.lower(), "__pycache__")]
        zaehl.update(len(d) for d in _alle_rohdateien(ordner).values())
    return zaehl


def finde_aufnahmeordner(wurzel):
    """Alle Ordner unterhalb von `wurzel` (einschließlich), die Aufnahmen enthalten.
    So kann z. B. ein ganzes Set (0029SET mit 000…003) oder ein Flugtag gewählt werden."""
    gefunden = []
    for ordner, unterordner, _ in os.walk(wurzel):
        unterordner[:] = sorted(u for u in unterordner
                                if u.lower() not in (REFLEKTANZ_UNTERORDNER.lower(), AUSWERTUNG_UNTERORDNER.lower(),
                                                     "__pycache__"))
        if liste_aufnahmen(ordner):
            gefunden.append(ordner)
    return gefunden


def liste_aufnahmen_rekursiv(wurzel):
    """[(Ordner, Aufnahmename)] für alle Aufnahmen unterhalb von `wurzel`."""
    return [(o, n) for o in finde_aufnahmeordner(wurzel) for n in liste_aufnahmen(o)]


# -----------------------------------------------------------------------------
# Laden
# -----------------------------------------------------------------------------
def _lies_reflektanzbild(pfad):
    with tifffile.TiffFile(pfad) as tif:
        stapel = tif.asarray().astype(np.float32)
        beschr = tif.pages[0].description or ""
        gdal = tif.pages[0].tags.get(42112)
        gdal = str(gdal.value) if gdal is not None else ""
    m = re.search(r"Kanaele:\s*(.+)$", beschr)
    namen = [s.strip() for s in m.group(1).split(",")] if m else KANALNAMEN
    # Aufnahmezeit und GPS aus den GDAL-Metadaten des Stapelskripts
    meta = {}
    for schluessel, ziel in (("DATETIME", "zeit"), ("GPS_LAT", "lat"), ("GPS_LON", "lon")):
        t = re.search(rf'<Item name="{schluessel}">([^<]*)</Item>', gdal)
        if t:
            meta[ziel] = t.group(1) if ziel == "zeit" else float(t.group(1))
    return stapel, {n: i for i, n in enumerate(namen)}, meta


def _parse_ausrichtung_txt(pfad):
    """Homographien aus Ausrichtung.txt des Stapelskripts ({Kanalname: H}; das Skript nummeriert die Kanäle
    _1 … _5 = KANALNAMEN). Der dort notierte Zuschnitt wird bewusst NICHT übernommen (er kann aus einem
    älteren Lauf ohne Sicherheitsrand stammen), sondern neu berechnet."""
    text = open(pfad, encoding="utf-8").read()
    H = {}
    for m in re.finditer(r"Homographie Kanal (\d) \([^)]*\):\s*(\[\[.*?\]\])", text, re.S):
        zahlen = [float(z) for z in re.findall(r"[-+]?\d+\.?\d*(?:e[-+]?\d+)?", m.group(2))]
        H[int(m.group(1)) - 1] = np.array(zahlen, dtype=np.float32).reshape(3, 3)
    if len(H) != 5:
        raise ValueError(f"{pfad}: Ausrichtung nicht lesbar")
    return {KANALNAMEN[b]: H[b] for b in range(5)}


def _bandname(pfad):
    """Kanalname (Camera:BandName) aus den XMP-Metadaten, ohne die Bilddaten zu lesen."""
    with tifffile.TiffFile(pfad) as tif:
        xmp = tif.pages[0].tags["XMP"].value if "XMP" in tif.pages[0].tags else b""
    xmp = xmp.decode("utf-8", "ignore") if isinstance(xmp, bytes) else str(xmp)
    m = re.search(r"<Camera:BandName>([^<]*)</Camera:BandName>", xmp)
    if not m:
        raise ValueError(f"{os.path.basename(pfad)}: Kanalname (Camera:BandName) fehlt in den Metadaten")
    return m.group(1).strip()


def _vorverarbeitung(kanaele):
    ms = stapelmodul()
    form = kanaele[0]["roh"].shape
    vign = [ms.vignette_karte(m, form) for m in kanaele]
    karten = [ms.entzerr_karten(m, form) for m in kanaele]
    bilder = [cv2.remap(ms.reflektanz(m, v).astype(np.float32), mx, my, cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
              for m, v, (mx, my) in zip(kanaele, vign, karten)]
    return bilder, karten, form


def _lies_einen_kanal(pfad):
    ms = stapelmodul()
    if os.path.getsize(pfad) == 0:
        raise ValueError(f"{os.path.basename(pfad)} ist leer (0 Byte) – Datei beschädigt "
                         "oder von OneDrive nicht heruntergeladen.")
    try:
        return ms.lies_kanal(pfad)
    except ValueError as e:
        if "DLS" in str(e):
            raise ValueError(f"{e}.\n\nDiese Aufnahme enthält keine Messwerte des Sonnenlichtsensors (DLS 2). "
                             "Ohne DLS oder Kalibrierpanel lässt sich keine Reflektanz berechnen.") from None
        raise ValueError(f"{os.path.basename(pfad)} ist beschädigt oder unvollständig ({e}).") from None
    except Exception as e:
        raise ValueError(f"{os.path.basename(pfad)} ist beschädigt oder unvollständig ({e}).") from None


def _ordne_dateien(dateien):
    """Teilt die Dateien einer Aufnahme nach dem Kanalnamen in den Metadaten auf:
    ({Kanalname: Pfad} der Spektralkanäle in Dateireihenfolge, Pfad des Panchro-Kanals oder None)."""
    spektral, pan = {}, None
    for b, p in sorted(dateien.items()):
        if os.path.getsize(p) == 0:
            raise ValueError(f"{os.path.basename(p)} ist leer (0 Byte) – Datei beschädigt "
                             "oder von OneDrive nicht heruntergeladen.")
        name = _bandname(p)
        if name == PANCHRO:
            pan = p
        elif name in spektral:
            raise ValueError(f"Kanal {name} kommt in der Aufnahme doppelt vor ({os.path.basename(p)}).")
        else:
            spektral[name] = p
    if not spektral:
        raise ValueError("Die Aufnahme enthält keine Spektralkanäle.")
    return spektral, pan


def _lies_kanaele(spektral):
    return [_lies_einen_kanal(p) for p in spektral.values()]


def _zuschnitt(karten, H, form):
    """Gemeinsamer gültiger Ausschnitt aller Kanäle (wie multispektral_stapeln.py, inkl. 2 px Sicherheitsrand)."""
    maske = np.ones(form, dtype=bool)
    for b, (mx, my) in enumerate(karten):
        g = cv2.remap(np.ones(form, np.float32), mx, my, cv2.INTER_NEAREST, borderValue=0)
        g = cv2.warpPerspective(g, H[b], (form[1], form[0]), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP,
                                borderValue=0)
        maske &= g > 0
    maske = cv2.erode(maske.astype(np.uint8), np.ones((5, 5), np.uint8), borderType=cv2.BORDER_CONSTANT,
                      borderValue=0) > 0
    return stapelmodul().gueltiger_ausschnitt(maske)


def _referenzkanal(namen):
    return "Red edge" if "Red edge" in namen else ("NIR" if "NIR" in namen else namen[0])


def _ausrichtungsplan(namen):
    """Referenzkanal und [(Kanal, [Partner in Vorzugsreihenfolge])]. Bei allen 5 Kanälen identisch mit
    multispektral_stapeln.py: Referenz Red Edge; Grün, NIR direkt; Rot direkt oder ersatzweise über Grün;
    Blau über Grün. Fehlt ein Kanal, wird der nächstbeste Weg genommen (z. B. Referenz NIR ohne Red Edge)."""
    ref = _referenzkanal(namen)
    plan, geloest = [], {ref}
    reihenfolge = [k for k in ("Green", "NIR", "Red edge", "Red", "Blue") if k in namen and k != ref]
    reihenfolge += [k for k in namen if k not in reihenfolge and k != ref]
    for k in reihenfolge:
        if k == "Blue":
            vorzug = ["Green"] if "Green" in geloest else [ref]
        elif k == "Red":
            vorzug = [ref, "Green"]
        else:
            vorzug = [ref]
        plan.append((k, [p for p in vorzug if p in geloest]))
        geloest.add(k)
    return ref, plan


def _stichprobe(aufn):
    """Aufnahmen für die Ausrichtungsschätzung: gleichmäßig verteilt über die Aufnahmen in Flughöhe."""
    namen = list(aufn)
    hoehen = []
    for n in namen:
        with tifffile.TiffFile(next(iter(aufn[n].values()))) as t:
            g = t.pages[0].tags["GPSTag"].value if "GPSTag" in t.pages[0].tags else {}
        a = g.get("GPSAltitude", (0, 1))
        hoehen.append(a[0] / a[1] if isinstance(a, tuple) else float(a))
    hoehen = np.array(hoehen)
    in_fh = [n for n, h in zip(namen, hoehen) if h >= np.percentile(hoehen, 50)]
    idx = np.linspace(0, len(in_fh) - 1, min(ANZAHL_KALIBRIER_AUFNAHMEN, len(in_fh))).round().astype(int)
    return [in_fh[i] for i in idx]


def _vollstaendige_rohaufnahmen(ordner):
    aufn = rohaufnahmen(ordner)
    aufn = {n: d for n, d in aufn.items() if all(os.path.getsize(p) > 0 for p in d.values())}
    if not aufn:
        raise RuntimeError(f"In {ordner} gibt es keine vollständigen Rohaufnahmen mit der gewählten Kanalzahl.")
    return aufn


def schaetze_ausrichtung(ordner, namen=None, fortschritt=print):
    """Schätzt die Kanalausrichtung für einen Ordner – gleiches Verfahren wie multispektral_stapeln.py
    (Gradienten-ECC, Stichprobe in Flughöhe, robuster Median, Ausreißerverwurf), für beliebige Kanalsätze.
    Rückgabe: {Kanalname: Homographie}."""
    ms = stapelmodul()
    aufn = _vollstaendige_rohaufnahmen(ordner)
    stichprobe = _stichprobe(aufn)
    ref, plan = None, None
    schaetzungen, karten, form = {}, None, None
    for i, n in enumerate(stichprobe, 1):
        fortschritt(f"Schätze Kanalausrichtung … Aufnahme {i}/{len(stichprobe)} ({n})")
        try:
            spektral, _ = _ordne_dateien(aufn[n])
            if namen is not None:
                spektral = {k: p for k, p in spektral.items() if k in namen}
            if plan is None:
                ref, plan = _ausrichtungsplan(list(spektral))
                schaetzungen = {(k, p): [] for k, partner in plan for p in partner}
            bilder, karten, form = _vorverarbeitung(_lies_kanaele(spektral))
        except ValueError as e:
            if "DLS" in str(e):
                raise
            continue                              # beschädigte Aufnahme in der Stichprobe überspringen
        pos = {k: j for j, k in enumerate(spektral)}
        bilder = [np.nan_to_num(b) for b in bilder]
        for (b, p) in schaetzungen:
            try:
                H, cc = ms.ecc_homographie(bilder[pos[p]], bilder[pos[b]])
            except cv2.error:
                continue
            if np.abs(H[:2, 2]).max() <= ms.MAX_VERSATZ_PX:
                schaetzungen[(b, p)].append((H, cc))
    if plan is None or karten is None:
        raise RuntimeError("Ausrichtung fehlgeschlagen: keine Aufnahme der Stichprobe lesbar.")
    paar, info = {}, {}
    for (b, p), liste in schaetzungen.items():
        if liste:
            t_med = np.median([h[:2, 2] for h, _ in liste], axis=0)
            liste = [(h, c) for h, c in liste if np.abs(h[:2, 2] - t_med).max() <= 3.0]
        if len(liste) >= 2:
            paar[(b, p)] = np.median(np.array([h for h, _ in liste]), axis=0)
            info[(b, p)] = (len(liste), float(np.mean([c for _, c in liste])))
    H = {ref: np.eye(3, dtype=np.float32)}
    weg = {}
    for b, kandidaten in plan:
        p = next((k for k in kandidaten if (b, k) in paar), None)
        if p is None:
            raise RuntimeError(f"Ausrichtung für Kanal {b} fehlgeschlagen (zu wenige gültige Schätzungen).")
        H[b] = (paar[(b, p)] if p == ref else paar[(b, p)] @ H[p]).astype(np.float32)
        weg[b] = p
    reihen = [k for k in KANALNAMEN if k in H] + [k for k in H if k not in KANALNAMEN]
    zuschnitt = _zuschnitt(karten, [H[k] for k in spektral], form)

    ziel = os.path.join(ordner, AUSWERTUNG_UNTERORDNER)
    os.makedirs(ziel, exist_ok=True)
    with open(os.path.join(ziel, "Ausrichtung.json"), "w", encoding="utf-8") as f:
        json.dump({"erstellt": _dt.datetime.now().isoformat(timespec="seconds"),
                   "verfahren": "wie multispektral_stapeln.py (Gradienten-ECC; Referenz Red Edge, sonst NIR; "
                                "Blau über Grün; Rot ersatzweise über Grün)",
                   "stichprobe": stichprobe, "referenzkanal": ref, "kanaele": reihen,
                   "ausrichtungsweg": {b: ("direkt auf " + ref if p == ref else f"über {p}") for b, p in weg.items()},
                   "gueltige_schaetzungen_korrelation": {f"{b} -> {p}": v for (b, p), v in info.items()},
                   "homographien": {k: H[k].tolist() for k in reihen}, "zuschnitt_r0_r1_c0_c1": list(zuschnitt)},
                  f, indent=2, ensure_ascii=False)
    return H


def ausrichtung_fuer_ordner(ordner, namen=None, fortschritt=print):
    """Liefert ({Kanalname: Homographie}, Herkunft) für die Kanäle `namen`. Reihenfolge: Ausrichtung.txt des
    Stapelskripts, eigener Zwischenspeicher, sonst neu schätzen (auch, wenn dort ein Kanal fehlt)."""
    namen = list(namen) if namen is not None else KANALNAMEN
    txt = os.path.join(ordner, REFLEKTANZ_UNTERORDNER, "Ausrichtung.txt")
    if os.path.exists(txt):
        H = _parse_ausrichtung_txt(txt)
        if set(namen) <= set(H) and _referenzkanal(namen) == "Red edge":
            return H, f"aus {REFLEKTANZ_UNTERORDNER}\\Ausrichtung.txt"
    js = os.path.join(ordner, AUSWERTUNG_UNTERORDNER, "Ausrichtung.json")
    if os.path.exists(js):
        d = json.load(open(js, encoding="utf-8"))
        h = d["homographien"]
        if isinstance(h, list):                       # Format bis Version 0.9.2: Liste in der Reihenfolge _1 … _5
            h = dict(zip(d.get("kanaele", KANALNAMEN), h))
        ref_alt = d.get("referenzkanal", "Red edge")
        if set(namen) <= set(h) and ref_alt == _referenzkanal(namen):
            return ({k: np.array(v, dtype=np.float32) for k, v in h.items()},
                    f"aus {AUSWERTUNG_UNTERORDNER}\\Ausrichtung.json")
    return (schaetze_ausrichtung(ordner, namen, fortschritt),
            f"neu geschätzt, gespeichert in {AUSWERTUNG_UNTERORDNER}\\Ausrichtung.json")


def _ms_stapel(kanaele, H):
    """Ausgerichteter, zugeschnittener Reflektanzstapel der Spektralkanäle. Rückgabe: (stapel, zuschnitt, form)."""
    bilder, karten, form = _vorverarbeitung(kanaele)
    Hl = [H[m["bandname"]] for m in kanaele]
    r0, r1, c0, c1 = _zuschnitt(karten, Hl, form)
    stapel = np.stack([cv2.warpPerspective(img, Hl[b], (form[1], form[0]),
                                           flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                           borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
                       for b, img in enumerate(bilder)])[:, r0:r1, c0:c1]
    return stapel, (r0, r1, c0, c1), form


# -----------------------------------------------------------------------------
# Panchromatischer Kanal (RedEdge-P): Schärfen nach SFIM
# -----------------------------------------------------------------------------
# Verfahren: Smoothing Filter-based Intensity Modulation (Liu 2000), ein Verhältnisverfahren wie Brovey:
#   MS_geschärft = MS_hochgerechnet · P / P_glatt
# P = Panchro auf dem feinen Raster, P_glatt = P auf die MS-Pixelgröße gemittelt und wieder hochgerechnet.
# Alle Kanäle eines Pixels werden mit demselben Faktor P / P_glatt multipliziert. Dadurch
#  - bleibt der Mittelwert jedes MS-Pixels (≈) erhalten (Radiometrie),
#  - bleiben normierte Differenzindizes (NDVI, NDRE, ReNDVI, GNDVI, NGRDI, BNDVI) pixelweise unverändert
#    gegenüber dem bloß hochgerechneten MS-Bild; SAVI, EVI, EVI2, VARI, GLI ändern sich geringfügig.
# Die Panchro-Werte gehen nur als Verhältnis ein, ihre absolute Kalibrierung spielt keine Rolle.
PAN_FAKTOR = 2                 # feines Raster = 2 × MS-Auflösung (Panchro ist ≈ 1,9 × feiner)
PAN_MIN_GLATT = 1e-4           # P_glatt darunter -> Pixel ungültig (Division)
PAN_FEIN_MAX_PX = 15           # Feinausrichtung je Bild: größere Restverschiebung (MS-Pixel) -> Ordnerwert behalten
PAN_FEIN_MIN_KORR = 0.2        # Feinausrichtung je Bild: Mindestkorrelation (Gradienten-ECC)


def _pan_bild(m_pan):
    """Panchro-Rohbild -> radiometrisch korrigiert und entzerrt (eigene Kameraparameter)."""
    ms = stapelmodul()
    form = m_pan["roh"].shape
    v = ms.vignette_karte(m_pan, form)
    mx, my = ms.entzerr_karten(m_pan, form)
    return cv2.remap(ms.reflektanz(m_pan, v).astype(np.float32), mx, my, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)


def _kamera(m):
    f = m["brennweite_mm"] * m["px_pro_mm"]
    cx, cy = (v * m["px_pro_mm"] for v in m["hauptpunkt_mm"])
    return f, cx, cy


def _pan_startgeometrie(m_ref, m_pan):
    """Näherung MS-Referenzkamera -> Panchro-Kamera (Pixel) aus Brennweiten und Hauptpunkten
    (gleiche Blickrichtung angenommen; Restversatz wird per ECC geschätzt)."""
    f_ms, cx_ms, cy_ms = _kamera(m_ref)
    f_p, cx_p, cy_p = _kamera(m_pan)
    k = f_p / f_ms
    return np.array([[k, 0, cx_p - k * cx_ms], [0, k, cy_p - k * cy_ms], [0, 0, 1]], dtype=np.float64)


def ecc_pan(referenz, kanal, stufen=3):
    """Ausrichtung Panchro -> MS (Gradienten-ECC wie im Stapelskript, Bildpyramide), zweistufig:
    erst reine Verschiebung (robust, schnell), dann affin ausgehend davon. Eine volle Homographie blieb in
    Tests (0002SET) teils im Startwert hängen und war 5–10× langsamer. Rückgabe: (3×3-Matrix, Korrelation)."""
    ms = stapelmodul()
    rp, kp = [ms._gradient(referenz)], [ms._gradient(kanal)]
    for _ in range(stufen - 1):
        rp.append(cv2.pyrDown(rp[-1]))
        kp.append(cv2.pyrDown(kp[-1]))
    kriterium = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5)
    W, cc = np.eye(2, 3, dtype=np.float32), 0.0
    for art in (cv2.MOTION_TRANSLATION, cv2.MOTION_AFFINE):
        W[:, 2] /= 2 ** (stufen - 1)
        for lvl in reversed(range(stufen)):
            if lvl != stufen - 1:
                W[:, 2] *= 2
            cc, W = cv2.findTransformECC(rp[lvl], kp[lvl], W, art, kriterium, None, 5)
    return np.vstack([W, [0, 0, 1]]).astype(np.float64), float(cc)


def _verschiebung(dx, dy):
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], dtype=np.float64)


def _pan_auf_ms(pan, B, R, zuschnitt, form_ziel):
    """Panchro auf das (zugeschnittene) MS-Raster abbilden; vorher geglättet (Panchro ist feiner)."""
    r0, _, c0, _ = zuschnitt
    glatt = cv2.GaussianBlur(np.nan_to_num(pan), (0, 0), 0.8 * B[0, 0])
    M = B @ R @ _verschiebung(c0, r0)
    return cv2.warpPerspective(glatt, M.astype(np.float32), (form_ziel[1], form_ziel[0]),
                               flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=0)


def schaetze_panchro_ausrichtung(ordner, H, fortschritt=print):
    """Restausrichtung Panchro -> MS-Referenzkamera (Homographie R im ungeschnittenen MS-Raster) für einen Ordner:
    Stichprobe wie bei den Spektralkanälen, Gradienten-ECC gegen das Mittel der Spektralkanäle, robuster Median."""
    ms = stapelmodul()
    aufn = _vollstaendige_rohaufnahmen(ordner)
    stichprobe = _stichprobe(aufn)
    liste = []
    for i, n in enumerate(stichprobe, 1):
        fortschritt(f"Schätze Panchro-Ausrichtung … Aufnahme {i}/{len(stichprobe)} ({n})")
        try:
            spektral, pan_p = _ordne_dateien(aufn[n])
            if pan_p is None:
                continue
            spektral = {k: p for k, p in spektral.items() if k in H}
            kanaele = _lies_kanaele(spektral)
            m_pan = _lies_einen_kanal(pan_p)
        except ValueError:
            continue
        stapel, zs, _ = _ms_stapel(kanaele, H)
        ref = np.nan_to_num(np.nanmean(stapel, axis=0)).astype(np.float32)
        m_ref = kanaele[[m["bandname"] for m in kanaele].index(_referenzkanal(list(spektral)))]
        B = _pan_startgeometrie(m_ref, m_pan)
        pan0 = _pan_auf_ms(_pan_bild(m_pan), B, np.eye(3), zs, ref.shape)
        try:
            Rc, cc = ecc_pan(ref, pan0)
        except cv2.error:
            continue
        if np.abs(Rc[:2, 2]).max() > ms.MAX_VERSATZ_PX:
            continue
        r0, _, c0, _ = zs
        C = _verschiebung(c0, r0)
        liste.append((C @ Rc.astype(np.float64) @ np.linalg.inv(C), float(cc)))
    if liste:
        t_med = np.median([r[:2, 2] for r, _ in liste], axis=0)
        liste = [(r, c) for r, c in liste if np.abs(r[:2, 2] - t_med).max() <= 3.0]
    if len(liste) < 2:
        raise RuntimeError("Panchro-Ausrichtung fehlgeschlagen (zu wenige gültige Schätzungen). "
                           "Bitte ohne „Panchro schärfen“ laden.")
    R = np.median(np.array([r for r, _ in liste]), axis=0)
    erg = {"erstellt": _dt.datetime.now().isoformat(timespec="seconds"),
           "verfahren": "Startgeometrie aus Brennweite/Hauptpunkt, Restausrichtung Gradienten-ECC (Verschiebung, "
                        "dann affin) gegen das Mittel der Spektralkanäle (MS-Raster), Median über die Stichprobe; "
                        "je Bild zusätzlich Feinausrichtung",
           "stichprobe": stichprobe, "gueltige_schaetzungen": len(liste),
           "korrelation_mittel": float(np.mean([c for _, c in liste])), "homographie_R": R.tolist()}
    ziel = os.path.join(ordner, AUSWERTUNG_UNTERORDNER)
    os.makedirs(ziel, exist_ok=True)
    with open(os.path.join(ziel, "Ausrichtung_Panchro.json"), "w", encoding="utf-8") as f:
        json.dump(erg, f, indent=2, ensure_ascii=False)
    return R, erg


def panchro_ausrichtung_fuer_ordner(ordner, H, fortschritt=print):
    js = os.path.join(ordner, AUSWERTUNG_UNTERORDNER, "Ausrichtung_Panchro.json")
    if os.path.exists(js):
        d = json.load(open(js, encoding="utf-8"))
        return np.array(d["homographie_R"], dtype=np.float64), d, f"aus {AUSWERTUNG_UNTERORDNER}\\Ausrichtung_Panchro.json"
    R, d = schaetze_panchro_ausrichtung(ordner, H, fortschritt)
    return R, d, f"neu geschätzt, gespeichert in {AUSWERTUNG_UNTERORDNER}\\Ausrichtung_Panchro.json"


def pan_feinausrichtung(stapel, zuschnitt, pan, B, R):
    """Feinausrichtung Panchro -> MS für eine einzelne Aufnahme, ausgehend von der Ordnerausrichtung R.
    Nötig, weil der Versatz zwischen Panchro- und MS-Kamera von Bild zu Bild etwas schwankt (Höhe, Neigung).
    Rückgabe: (R für dieses Bild, Info). Misslingt die Schätzung, bleibt R (Ordnerwert) und Info sagt das."""
    ms = stapelmodul()
    ref = np.nan_to_num(np.nanmean(stapel, axis=0)).astype(np.float32)
    pan0 = _pan_auf_ms(pan, B, R, zuschnitt, ref.shape)
    try:
        Rc, cc = ecc_pan(ref, pan0)
    except cv2.error:
        return R, {"feinausrichtung": "fehlgeschlagen (ECC konvergiert nicht) – Ordnerwert verwendet"}
    rest = float(np.abs(Rc[:2, 2]).max())
    if rest > PAN_FEIN_MAX_PX or cc < PAN_FEIN_MIN_KORR:
        return R, {"feinausrichtung": f"verworfen (Rest {rest:.1f} px, Korrelation {cc:.2f}) – Ordnerwert verwendet"}
    r0, _, c0, _ = zuschnitt
    C = _verschiebung(c0, r0)
    return (R @ C @ Rc.astype(np.float64) @ np.linalg.inv(C),
            {"feinausrichtung": "je Bild (Gradienten-ECC, Verschiebung + affin)", "rest_verschiebung_px": [round(float(v), 2) for v in Rc[:2, 2]],
             "korrelation": round(float(cc), 3)})


def _auf_raster(a, b, f):
    """Grenzen a..b (feines Raster) nach innen auf Vielfache von f runden."""
    return -(-a // f) * f, (b // f) * f


def schaerfen_sfim(stapel, zuschnitt, pan, B, R, faktor=PAN_FAKTOR):
    """SFIM-Schärfung des zugeschnittenen MS-Stapels mit dem entzerrten Panchro-Bild.
    Rückgabe: (geschärfter Stapel, Ausschnitt im MS-Raster (r0, r1, c0, c1) als Info)."""
    k, h, w = stapel.shape
    F = faktor
    r0, _, c0, _ = zuschnitt
    # feines Raster -> MS-Raster (Pixelmitten wie cv2.resize): x_ms = (X + 0,5) / F − 0,5
    A = np.array([[1 / F, 0, 0.5 / F - 0.5], [0, 1 / F, 0.5 / F - 0.5], [0, 0, 1]], dtype=np.float64)
    M = B @ R @ _verschiebung(c0, r0) @ A
    P = cv2.warpPerspective(pan, M.astype(np.float32), (w * F, h * F), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
    ms_ok = np.all(np.isfinite(stapel), axis=0)
    gueltig = np.isfinite(P) & np.repeat(np.repeat(ms_ok, F, axis=0), F, axis=1)
    gueltig = cv2.erode(gueltig.astype(np.uint8), np.ones((2 * F + 1, 2 * F + 1), np.uint8),
                        borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
    R0, R1, C0, C1 = stapelmodul().gueltiger_ausschnitt(gueltig)
    R0, R1 = _auf_raster(R0, R1, F)
    C0, C1 = _auf_raster(C0, C1, F)
    if R1 - R0 < 4 * F or C1 - C0 < 4 * F:
        raise ValueError("Panchro und Spektralkanäle überlappen kaum – Schärfen nicht möglich.")
    Pc = P[R0:R1, C0:C1]
    hk, wk = (R1 - R0) // F, (C1 - C0) // F
    P_glatt = cv2.resize(cv2.resize(Pc, (wk, hk), interpolation=cv2.INTER_AREA), (wk * F, hk * F),
                         interpolation=cv2.INTER_LINEAR)
    with np.errstate(divide="ignore", invalid="ignore"):
        faktor_bild = np.where(P_glatt > PAN_MIN_GLATT, Pc / P_glatt, np.nan).astype(np.float32)
    ms_teil = stapel[:, R0 // F:R1 // F, C0 // F:C1 // F]
    hoch = np.stack([cv2.resize(b, (wk * F, hk * F), interpolation=cv2.INTER_LINEAR) for b in ms_teil])
    return (hoch * faktor_bild[None]).astype(np.float32), (R0 // F, R1 // F, C0 // F, C1 // F)


def lade_aufnahme(pfad_oder_ordner, name=None, fortschritt=print, aus_rohbildern=False, schaerfen=None,
                  nur_kronen=None):
    """Lädt eine Aufnahme als Reflektanzstapel der Spektralkanäle.

    Ist bereits ein Reflektanzbild des Stapelskripts vorhanden (5 Kanäle), wird es direkt gelesen (identische
    Werte, schnell). Sonst werden die Rohbilder mit dem Verfahren des Stapelskripts verarbeitet; welche Datei
    welcher Kanal ist, steht in den Metadaten (Camera:BandName). Ein Panchro-Kanal wird nur bei
    `schaerfen` (Standard: Einstellung PANCHRO_SCHAERFEN) verwendet – dann wird nach SFIM geschärft."""
    if name is None:
        ordner, name = _ordner_und_name(pfad_oder_ordner)
    else:
        ordner = pfad_oder_ordner
    schaerfen = PANCHRO_SCHAERFEN if schaerfen is None else bool(schaerfen)
    nur_kronen = PANCHRO_NUR_KRONEN if nur_kronen is None else bool(nur_kronen)
    maskenstapel = None
    refl = os.path.join(ordner, REFLEKTANZ_UNTERORDNER, f"{name}_reflektanz.tif")
    roh = rohaufnahmen(ordner).get(name)
    spektral = pan_p = None
    if roh:
        spektral, pan_p = _ordne_dateien(roh)
    meta = {"geschaerft": False}

    if os.path.exists(refl) and not aus_rohbildern and KANALZAHL in (None, 5) and not (schaerfen and pan_p):
        fortschritt(f"Lade {name} (vorhandenes Reflektanzbild) …")
        stapel, kidx, m = _lies_reflektanzbild(refl)
        meta.update(m)
        quelle = f"Reflektanzbild {REFLEKTANZ_UNTERORDNER}\\{name}_reflektanz.tif (multispektral_stapeln.py)"
    elif roh:
        kanaele = _lies_kanaele(spektral)     # zuerst: prüft DLS-Daten, bevor ggf. lange ausgerichtet wird
        namen = [m["bandname"] for m in kanaele]
        H, herkunft = ausrichtung_fuer_ordner(ordner, namen, fortschritt)
        fortschritt(f"Verarbeite Rohbilder {name} (Radiometrie, Entzerrung, Ausrichtung) …")
        stapel, zs, _ = _ms_stapel(kanaele, H)
        kidx = {n: i for i, n in enumerate(namen)}
        nummern = {os.path.normcase(p): b for b, p in roh.items()}
        datei_info = ", ".join(f"_{nummern[os.path.normcase(p)]} {k}" for k, p in spektral.items())
        quelle = f"Rohbilder {name} ({datei_info}), DLS-2-Kalibrierung, Ausrichtung {herkunft}"
        meta.update({"zeit": kanaele[0]["zeit"], "lat": kanaele[0]["lat"], "lon": kanaele[0]["lon"],
                     "kanaele": namen, "dateien_je_aufnahme": len(roh),
                     "dls_einstrahlung_W_m2_nm": {m["bandname"]: m["einstrahlung"] for m in kanaele},
                     "gesaettigte_rohpixel": int(sum((m["roh"] >= 65500).sum() for m in kanaele))})
        if pan_p and schaerfen:
            m_pan = _lies_einen_kanal(pan_p)
            R, info, herkunft_p = panchro_ausrichtung_fuer_ordner(ordner, H, fortschritt)
            fortschritt(f"Schärfe {name} mit Panchro (SFIM) …")
            m_ref = kanaele[namen.index(_referenzkanal(namen))]
            B = _pan_startgeometrie(m_ref, m_pan)
            pan = _pan_bild(m_pan)
            R, fein = pan_feinausrichtung(stapel, zs, pan, B, R)
            scharf, ausschnitt = schaerfen_sfim(stapel, zs, pan, B, R)
            if nur_kronen:
                # Spektralwerte unverändert: jedes MS-Pixel deckt F x F feine Pixel (Pansharpening kann die
                # Spektralwerte verfälschen); das geschärfte Bild dient nur Maske, Kronentrennung und Anzeige
                r0, r1, c0, c1 = ausschnitt
                orig = stapel[:, r0:r1, c0:c1]
                stapel = np.repeat(np.repeat(orig, PAN_FAKTOR, axis=1), PAN_FAKTOR, axis=2).astype(np.float32)
                maskenstapel = scharf
            else:
                stapel = scharf
            meta["geschaerft"] = True
            meta["panchro_nur_kronen"] = bool(nur_kronen)
            meta["panchro"] = {"verfahren": "SFIM (Liu 2000), Verhältnisverfahren", "faktor": PAN_FAKTOR,
                               "ausrichtung": herkunft_p, "ausschnitt_im_ms_raster_r0_r1_c0_c1": list(ausschnitt),
                               "korrelation_ausrichtung_ordner": info.get("korrelation_mittel")} | fein
            quelle += (f"; geschärft mit Panchro (_{nummern[os.path.normcase(pan_p)]}, SFIM, Faktor {PAN_FAKTOR}, "
                       f"Ausrichtung {herkunft_p})"
                       + ("; Panchro nur für Maske/Kronen, Indizes aus den Original-Spektralkanälen" if nur_kronen
                          else "; Indizes aus den geschärften Kanälen"))
        elif pan_p:
            quelle += f"; Panchro (_{nummern[os.path.normcase(pan_p)]}) nicht verwendet"
    else:
        vorhanden = sorted(_alle_rohdateien(ordner).get(name, {}))
        raise FileNotFoundError(
            f"Für {name} wurden weder vollständige Rohbilder noch ein Reflektanzbild gefunden."
            + (f"\nVorhanden: Dateien {', '.join(f'_{b}' for b in vorhanden)} – gewählte Kanalzahl: "
               f"{KANALZAHL or 'automatisch'}." if vorhanden else ""))

    if "NIR" not in kidx:
        raise ValueError("Kanal NIR fehlt – ohne NIR ist keine Auswertung möglich.")
    fehlend = [k for k in KANALNAMEN if k not in kidx]
    if fehlend:
        meta["fehlende_kanaele"] = fehlend
    return Aufnahme(name, ordner, stapel, kidx, quelle, meta, maskenstapel)


# -----------------------------------------------------------------------------
# Indizes, Masken, Statistik
# -----------------------------------------------------------------------------
def berechne_index(stapel, kidx, index):
    """Index als float32-Array; ungültige Pixel = NaN (Maskierung wie in den QGIS-Projekten, s. INDIZES)."""
    d = INDIZES[index]
    if not index_verfuegbar(kidx, index):          # Kanal fehlt (z. B. Set mit 4 Kanälen) -> alles ungültig
        return np.full(stapel.shape[1:], np.nan, np.float32)
    b = {k: stapel[kidx[k]].astype(np.float64) for k in d["kanaele"]}
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        z, n = d["z"](b), d["n"](b)
        wert = z / n
    gueltig = np.isfinite(wert) & (np.abs(n) >= MIN_NENNER)
    for k in d["kanaele"]:
        gueltig &= b[k] >= MIN_REFLEKTANZ
    lo, hi = d["bereich"]
    gueltig &= (wert >= lo - 1e-9) & (wert <= hi + 1e-9)
    wert = np.clip(wert, lo, hi)
    wert[~gueltig] = np.nan
    return wert.astype(np.float32)


def index_verfuegbar(kidx, index):
    return all(k in kidx for k in INDIZES[index]["kanaele"])


def fehlende_kanaele(kidx, index):
    return [k for k in INDIZES[index]["kanaele"] if k not in kidx]


def vegetationsmaske(stapel, kidx, schwelle):
    """True = Vegetation (NDVI >= Schwelle)."""
    if not index_verfuegbar(kidx, "NDVI"):
        raise ValueError(f"Vegetationsmaske nicht möglich: Kanal {', '.join(fehlende_kanaele(kidx, 'NDVI'))} fehlt.")
    ndvi = berechne_index(stapel, kidx, "NDVI")
    return np.nan_to_num(ndvi, nan=-9.0) >= schwelle


# -----------------------------------------------------------------------------
# Baummaske: überwachte Pixelklassifikation (Random Forest) + Nachbearbeitung
# -----------------------------------------------------------------------------
# Merkmale je Pixel, berechnet auf halber Auflösung (≈ 1,5 cm/px bei 12 m Flughöhe):
#  - Reflektanz der 5 Kanäle und die 4 Indizes (spektrale Information)
#  - Helligkeit (Mittel aller Kanäle)
#  - lokale Mittelwerte von NIR, NDVI und Helligkeit in zwei Fenstergrößen (Umgebung / Objektgröße)
#  - lokale Standardabweichung von NIR und Helligkeit in zwei Fenstergrößen (Textur: Nadeln/Äste vs. Gras)
BAUM_FAKTOR = 2                    # Verkleinerung für Merkmale und Klassifikation
BAUM_SKALEN = (3, 10)              # Gauß-Sigma der lokalen Merkmale in Pixeln (verkleinertes Bild) ≈ 4,5 und 15 cm
BAUM_SCHWELLE = 0.5                # Baumwahrscheinlichkeit ab der ein Pixel als Baum gilt
BAUM_GLAETTUNG_PX = 4              # Radius Öffnen/Schließen (volle Auflösung)
BAUM_MIN_FLAECHE_PX = 1500         # kleinere Baum-Objekte werden verworfen (≈ 0,09 m² bei 0,77 cm/px)
BAUM_MAX_LOCH_PX = 1500            # kleinere Lücken innerhalb von Bäumen werden geschlossen
BAUM_MAX_PIXEL_JE_FLAECHE = 4000   # Stichprobe je Trainingsfläche (verhindert Übergewicht großer Flächen)


def baum_merkmalsnamen():
    namen = [f"Refl_{k}" for k in KANALNAMEN] + BAUM_INDIZES + ["Helligkeit"]
    for s in BAUM_SKALEN:
        namen += [f"NIR_mittel_s{s}", f"NDVI_mittel_s{s}", f"Hell_mittel_s{s}", f"NIR_std_s{s}", f"Hell_std_s{s}"]
    return namen


def baum_merkmale(stapel, kidx):
    """Merkmalsbild (h/f, w/f, m) float32 auf verkleinerter Auflösung."""
    fehlt = [k for k in KANALNAMEN if k not in kidx]
    if fehlt:
        raise ValueError(f"Das Baummodell braucht alle 5 Spektralkanäle – in dieser Aufnahme fehlt {', '.join(fehlt)}. "
                         "Bitte die Maske „Vegetation“ verwenden.")
    f = BAUM_FAKTOR
    h, w = stapel.shape[1:]
    klein = np.stack([cv2.resize(np.nan_to_num(b), (w // f, h // f), interpolation=cv2.INTER_AREA)
                      for b in stapel]).astype(np.float32)
    ebenen = [klein[kidx[k]] for k in KANALNAMEN]
    ebenen += [np.nan_to_num(berechne_index(klein, kidx, i), nan=0.0) for i in BAUM_INDIZES]
    hell = klein.mean(axis=0)
    ebenen.append(hell)
    nir, ndvi = klein[kidx["NIR"]], ebenen[5]
    for s in BAUM_SKALEN:
        g = lambda x: cv2.GaussianBlur(x, (0, 0), s)
        for x in (nir, ndvi, hell):
            ebenen.append(g(x))
        for x in (nir, hell):
            ebenen.append(np.sqrt(np.maximum(g(x * x) - g(x) ** 2, 0)))
    return np.stack(ebenen, axis=-1).astype(np.float32)


def polygon_maske(form, xy, faktor=1):
    """Bool-Maske (Form `form`) für ein Polygon in Vollbild-Pixelkoordinaten."""
    m = np.zeros(form, np.uint8)
    pts = np.round(np.asarray(xy, dtype=np.float64) / faktor).astype(np.int32)
    cv2.fillPoly(m, [pts], 1)
    return m.astype(bool)


def trainingspixel(merkmale, xy, rng=None):
    """Merkmalsvektoren der Pixel innerhalb eines Polygons (Stichprobe)."""
    rng = rng or np.random.default_rng(0)
    m = polygon_maske(merkmale.shape[:2], xy, BAUM_FAKTOR)
    X = merkmale[m]
    if len(X) > BAUM_MAX_PIXEL_JE_FLAECHE:
        X = X[rng.choice(len(X), BAUM_MAX_PIXEL_JE_FLAECHE, replace=False)]
    return X


class Baummodell:
    """Random-Forest-Klassifikator Baum / kein Baum mit gespeicherten Trainingsdaten.

    Die Trainingsflächen (Polygone) werden mit ihren Merkmalen gespeichert, sodass das Modell
    jederzeit um weitere Flächen/Bilder ergänzt und neu trainiert werden kann."""

    def __init__(self):
        self.X = np.zeros((0, len(baum_merkmalsnamen())), np.float32)
        self.y = np.zeros(0, np.int8)            # 1 = Baum, 0 = kein Baum
        self.gruppe = np.zeros(0, np.int32)      # Nummer der Trainingsfläche
        self.flaechen = []                       # [{nr, klasse, aufnahme, ordner, xy, pixel}]
        self.rf = None
        self.info = {}

    # --- Trainingsdaten
    def flaeche_hinzufuegen(self, aufn, merkmale, xy, klasse):
        X = trainingspixel(merkmale, xy)
        if len(X) == 0:
            return 0
        if self.flaechen and self.geschaerft != aufn.geschaerft:
            raise ValueError("Das Baummodell enthält bereits Flächen aus "
                             + ("geschärften" if self.geschaerft else "ungeschärften") + " Aufnahmen. Geschärfte "
                             "Aufnahmen haben eine andere Pixelgröße – bitte ein eigenes Modell dafür anlegen.")
        nr = max([f["nr"] for f in self.flaechen], default=0) + 1
        self.X = np.vstack([self.X, X])
        self.y = np.concatenate([self.y, np.full(len(X), klasse, np.int8)])
        self.gruppe = np.concatenate([self.gruppe, np.full(len(X), nr, np.int32)])
        self.flaechen.append({"nr": nr, "klasse": int(klasse), "aufnahme": aufn.name, "ordner": aufn.ordner,
                              "xy": np.round(np.asarray(xy), 1).tolist(), "pixel": int(len(X)),
                              "geschaerft": aufn.geschaerft})
        return len(X)

    @property
    def geschaerft(self):
        """Wurde das Modell an mit Panchro geschärften Aufnahmen trainiert? (Pixelgröße!)"""
        return bool(self.flaechen and self.flaechen[0].get("geschaerft", False))

    def flaeche_entfernen(self, nr):
        behalten = self.gruppe != nr
        self.X, self.y, self.gruppe = self.X[behalten], self.y[behalten], self.gruppe[behalten]
        self.flaechen = [f for f in self.flaechen if f["nr"] != nr]

    def anzahl(self):
        baum = sum(1 for f in self.flaechen if f["klasse"] == 1)
        return baum, len(self.flaechen) - baum

    # --- Training
    def trainieren(self):
        from sklearn.ensemble import RandomForestClassifier
        baum, kein = self.anzahl()
        if baum < 2 or kein < 2:
            raise ValueError("Für das Modell werden mindestens je 2 Flächen „Baum“ und „kein Baum“ benötigt "
                             f"(vorhanden: {baum} Baum, {kein} kein Baum).")
        def neues_rf():
            return RandomForestClassifier(n_estimators=150, min_samples_leaf=5, max_features="sqrt",
                                          class_weight="balanced", n_jobs=-1, random_state=0)

        # Räumlich unabhängige Prüfung: Kreuzvalidierung über ganze Trainingsflächen (GroupKFold),
        # damit benachbarte, ähnliche Pixel nicht gleichzeitig in Training und Prüfung liegen.
        k = min(5, baum, kein)
        richtig = np.zeros(len(self.y), bool)
        # Folds getrennt je Klasse bilden, damit jede Prüfung beide Klassen enthält
        gruppen_baum = sorted({f["nr"] for f in self.flaechen if f["klasse"] == 1})
        gruppen_kein = sorted({f["nr"] for f in self.flaechen if f["klasse"] == 0})
        fold_von = {}
        for liste in (gruppen_baum, gruppen_kein):
            for i, g in enumerate(liste):
                fold_von[g] = i % k
        fold = np.array([fold_von[g] for g in self.gruppe])
        for i in range(k):
            test = fold == i
            rf = neues_rf().fit(self.X[~test], self.y[~test])
            richtig[test] = rf.predict(self.X[test]) == self.y[test]
        # Genauigkeit je Klasse (Pixel), dann ausgewogen gemittelt
        acc_baum = float(richtig[self.y == 1].mean())
        acc_kein = float(richtig[self.y == 0].mean())

        self.rf = neues_rf().fit(self.X, self.y)
        wichtig = sorted(zip(baum_merkmalsnamen(), self.rf.feature_importances_), key=lambda t: -t[1])
        self.info = {
            "trainiert": _dt.datetime.now().isoformat(timespec="seconds"),
            "verfahren": "Random Forest (scikit-learn), 150 Bäume, min_samples_leaf=5, class_weight=balanced",
            "flaechen_baum": baum, "flaechen_kein_baum": kein,
            "pixel_baum": int((self.y == 1).sum()), "pixel_kein_baum": int((self.y == 0).sum()),
            "aufnahmen": sorted({f"{os.path.basename(f['ordner'])}/{f['aufnahme']}" for f in self.flaechen}),
            "kreuzvalidierung": f"{k}-fach, gruppiert nach Trainingsfläche",
            "trefferquote_baum": round(acc_baum, 4), "trefferquote_kein_baum": round(acc_kein, 4),
            "ausgewogene_genauigkeit": round((acc_baum + acc_kein) / 2, 4),
            "wichtigste_merkmale": [(n, round(float(v), 4)) for n, v in wichtig[:8]],
            "nachbearbeitung": {"schwelle": BAUM_SCHWELLE, "glaettung_px": BAUM_GLAETTUNG_PX,
                                "min_flaeche_px": BAUM_MIN_FLAECHE_PX, "max_loch_px": BAUM_MAX_LOCH_PX},
        }
        return self.info

    # --- Anwendung
    def wahrscheinlichkeit(self, stapel, kidx, merkmale=None):
        """Baumwahrscheinlichkeit (0..1) in voller Auflösung."""
        if self.rf is None:
            raise ValueError("Das Baummodell ist noch nicht berechnet.")
        if merkmale is None:
            merkmale = baum_merkmale(stapel, kidx)
        hk, wk, m = merkmale.shape
        p = self.rf.predict_proba(merkmale.reshape(-1, m))[:, list(self.rf.classes_).index(1)]
        p = p.reshape(hk, wk).astype(np.float32)
        h, w = stapel.shape[1:]
        return cv2.resize(p, (w, h), interpolation=cv2.INTER_LINEAR)

    def maske(self, stapel, kidx, merkmale=None):
        return nachbearbeiten(self.wahrscheinlichkeit(stapel, kidx, merkmale) >= BAUM_SCHWELLE)

    # --- Speichern / Laden
    def speichern(self, pfad):
        import joblib
        joblib.dump({"version": VERSION, "merkmale": baum_merkmalsnamen(), "faktor": BAUM_FAKTOR,
                     "skalen": BAUM_SKALEN, "X": self.X, "y": self.y, "gruppe": self.gruppe,
                     "flaechen": self.flaechen, "rf": self.rf, "info": self.info}, pfad, compress=3)
        with open(os.path.splitext(pfad)[0] + "_Info.json", "w", encoding="utf-8") as f:
            json.dump({"info": self.info, "merkmale": baum_merkmalsnamen(),
                       "trainingsflaechen": [{k: v for k, v in fl.items() if k != "xy"} | {"eckpunkte": len(fl["xy"])}
                                             for fl in self.flaechen]}, f, indent=2, ensure_ascii=False)

    @classmethod
    def laden(cls, pfad):
        """Lädt ein mit `speichern` erzeugtes Modell (nur eigene Dateien laden: joblib nutzt pickle)."""
        import joblib
        d = joblib.load(pfad)
        if d["merkmale"] != baum_merkmalsnamen() or d["faktor"] != BAUM_FAKTOR or tuple(d["skalen"]) != BAUM_SKALEN:
            raise ValueError("Das Modell wurde mit anderen Merkmalseinstellungen erstellt und passt nicht zu "
                             "dieser Programmversion. Bitte neu berechnen.")
        m = cls()
        m.X, m.y, m.gruppe, m.flaechen, m.rf, m.info = d["X"], d["y"], d["gruppe"], d["flaechen"], d["rf"], d["info"]
        return m


def nachbearbeiten(maske):
    """Glättet die Klassifikation: Öffnen/Schließen, kleine Objekte entfernen, kleine Lücken füllen."""
    k = _ellipse(BAUM_GLAETTUNG_PX)
    m = cv2.morphologyEx(maske.astype(np.uint8), cv2.MORPH_OPEN, k)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    m = _kleine_entfernen(m, BAUM_MIN_FLAECHE_PX)
    m = 1 - _kleine_entfernen(1 - m, BAUM_MAX_LOCH_PX)       # Lücken = kleine Hintergrundobjekte
    return m.astype(bool)


def _kleine_entfernen(b, min_px):
    """uint8-Maske ohne zusammenhängende Flächen < min_px (8er-Nachbarschaft)."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(b.astype(np.uint8), connectivity=8)
    gross = np.zeros(n, np.uint8)
    gross[1:] = st[1:, cv2.CC_STAT_AREA] >= min_px
    return gross[lab]


def _ellipse(r):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


# -----------------------------------------------------------------------------
# Maskenverfeinerung (Version 0.8)
# -----------------------------------------------------------------------------
# Die Baummaske entsteht auf halber Auflösung aus Merkmalen mit Umgebungsinformation und wird geglättet. Dadurch
# zählen dunkle Lücken zwischen den Kronen (Boden, Schatten, Unterwuchs) oft mit zum Baum; im NDVI unterscheiden sie
# sich kaum von Nadeln (0026SET: 0,86–0,89 gegenüber 0,95), im NIR dagegen deutlich (≈ 0,08–0,10 gegenüber ≈ 0,45).
# Verfeinerung in voller Auflösung:
#  1. Kandidaten = Maske, nach außen um VERFEIN_RAND_PX erweitert (nur wo Baumwahrscheinlichkeit >= VERFEIN_P_MIN)
#  2. Lücken entfernen: NIR (leicht geglättet) < Anteil × P90 des NIR innerhalb der Maske (relativ -> unabhängig von
#     der Beleuchtung des Fluges)
#  3. leichte Glättung (Radius VERFEIN_GLAETTUNG_PX statt BAUM_GLAETTUNG_PX), Splitter und kleine Löcher < VERFEIN_MIN_PX
VERFEIN_LUECKE_ANTEIL = 0.30     # Vorgabe: Pixel dunkler als 30 % der Kronenhelligkeit (P90) = Lücke
VERFEIN_NIR_SIGMA = 2.0          # Glättung des NIR vor dem Vergleich (Pixel)
VERFEIN_RAND_PX = 6              # so weit darf die Maske nach außen wachsen
VERFEIN_P_MIN = 0.3              # ... aber nur, wo das Baummodell mindestens diese Wahrscheinlichkeit liefert
VERFEIN_GLAETTUNG_PX = 2
VERFEIN_MIN_PX = 300             # Splitter und Löcher darunter werden entfernt bzw. gefüllt


def verfeinere_maske(maske, stapel, kidx, wahrscheinlichkeit=None, luecke_anteil=VERFEIN_LUECKE_ANTEIL):
    """Zieht die Maskengrenzen in voller Auflösung am NIR-Kanal nach (siehe oben).
    Rückgabe: (verfeinerte bool-Maske, Info-Dict für das Protokoll)."""
    if not maske.any():
        return maske, {"nir_schwelle": None}
    nir = cv2.GaussianBlur(np.nan_to_num(stapel[kidx["NIR"]]).astype(np.float32), (0, 0), VERFEIN_NIR_SIGMA)
    p90 = float(np.percentile(nir[maske], 90))
    t = luecke_anteil * p90
    if wahrscheinlichkeit is not None:
        kand = cv2.dilate(maske.astype(np.uint8), _ellipse(VERFEIN_RAND_PX)).astype(bool) \
               & (wahrscheinlichkeit >= VERFEIN_P_MIN)
        kand |= maske
    else:
        kand = maske
    m = (kand & (nir >= t)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, _ellipse(VERFEIN_GLAETTUNG_PX))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, _ellipse(VERFEIN_GLAETTUNG_PX))
    m = _kleine_entfernen(m, VERFEIN_MIN_PX)
    m = (1 - _kleine_entfernen(1 - m, VERFEIN_MIN_PX)).astype(bool)
    info = {"nir_p90_maske": round(p90, 4), "nir_schwelle": round(t, 4),
            "anteil_vorher": round(float(maske.mean()), 4), "anteil_nachher": round(float(m.mean()), 4),
            "entfernt_anteil_bild": round(float((maske & ~m).mean()), 4),
            "hinzu_anteil_bild": round(float((m & ~maske).mean()), 4)}
    return m, info


# -----------------------------------------------------------------------------
# Maskenvorgabe (für Anzeige, Export und Ordnerauswertung einheitlich)
# -----------------------------------------------------------------------------
@dataclass
class Maskenvorgabe:
    art: str                          # "Vegetation" oder "Baum"
    schwelle: float = 0.4             # nur Vegetation
    modell: "Baummodell" = None       # nur Baum
    modellpfad: str = ""              # nur Baum (Protokoll)
    verfeinern: bool = False          # Grenzen in voller Auflösung am NIR nachziehen (verfeinere_maske)
    luecke_anteil: float = VERFEIN_LUECKE_ANTEIL

    @property
    def name(self):
        return self.art

    def beschreibung(self):
        if self.art == "Vegetation":
            text = f"Vegetation: NDVI >= {self.schwelle}"
        else:
            i = self.modell.info if self.modell else {}
            text = (f"Baum: Random-Forest-Modell {os.path.basename(self.modellpfad) or '(nicht gespeichert)'}, "
                    f"{i.get('flaechen_baum', '?')}+{i.get('flaechen_kein_baum', '?')} Beispielflächen, "
                    f"ausgewogene Genauigkeit {i.get('ausgewogene_genauigkeit', '?')}")
        if self.verfeinern:
            text += f"; verfeinert (Lücken: NIR < {self.luecke_anteil * 100:.0f} % von P90)"
        return text

    def berechne(self, aufn, merkmale=None, info=None):
        """bool-Maske. `info` (dict) wird bei Verfeinerung mit den Kennwerten je Aufnahme gefüllt."""
        p = None
        if self.art == "Vegetation":
            m = vegetationsmaske(aufn.kronenstapel, aufn.kanalindex, self.schwelle)
        else:
            p = self.modell.wahrscheinlichkeit(aufn.kronenstapel, aufn.kanalindex, merkmale)
            m = nachbearbeiten(p >= BAUM_SCHWELLE)
        if self.verfeinern:
            m, i = verfeinere_maske(m, aufn.kronenstapel, aufn.kanalindex, p, self.luecke_anteil)
            if info is not None:
                info.update(i)
        return m

    def protokoll(self):
        d = {"art": self.art, "beschreibung": self.beschreibung()}
        if self.art == "Baum" and self.modell:
            d["modell"] = self.modellpfad
            d["modell_info"] = self.modell.info
        d["verfeinerung"] = ({"luecke_nir_anteil_von_p90": self.luecke_anteil, "nir_sigma_px": VERFEIN_NIR_SIGMA,
                              "rand_wachstum_px": VERFEIN_RAND_PX, "p_min_wachstum": VERFEIN_P_MIN,
                              "glaettung_px": VERFEIN_GLAETTUNG_PX, "min_flaeche_loch_px": VERFEIN_MIN_PX}
                             if self.verfeinern else "aus")
        return d


STAT_SPALTEN = ["Pixel", "Mittel", "Median", "Std", "Min", "P5", "P25", "P75", "P95", "Max"]


def statistik(werte):
    w = werte[np.isfinite(werte)]
    if w.size == 0:
        return dict.fromkeys(STAT_SPALTEN, float("nan")) | {"Pixel": 0}
    p = np.percentile(w, [5, 25, 50, 75, 95])
    return {"Pixel": int(w.size), "Mittel": float(w.mean()), "Median": float(p[2]),
            "Std": float(w.std(ddof=1)) if w.size > 1 else 0.0,
            "Min": float(w.min()), "P5": float(p[0]), "P25": float(p[1]), "P75": float(p[3]), "P95": float(p[4]),
            "Max": float(w.max())}


def regionen(form, maske=None, maskenname="Vegetation", rois=()):
    """[(Name, bool-Maske)] für Gesamtbild, Maske und ROIs (x0, y0, x1, y1 in Pixeln)."""
    out = [("Gesamtbild", np.ones(form, bool))]
    if maske is not None:
        out.append((maskenname, maske))
    for roi in rois:
        m = np.zeros(form, bool)
        x0, y0, x1, y1 = roi["box"]
        m[y0:y1, x0:x1] = True
        out.append((roi["name"], m))
        if maske is not None:
            out.append((f"{roi['name']} ∩ {maskenname}", m & maske))
    return out


def rgb_art(kidx):
    """Welche Kanäle zeigt das Anzeigebild? (Echtfarben braucht Rot, Grün, Blau.)"""
    if all(k in kidx for k in ("Red", "Green", "Blue")):
        return ("Red", "Green", "Blue"), "Echtfarben"
    if all(k in kidx for k in ("NIR", "Red", "Green")):
        return ("NIR", "Red", "Green"), "Falschfarben NIR/Rot/Grün"
    k = list(kidx)[:3]
    while len(k) < 3:
        k.append(k[-1])
    return tuple(k), "Kanäle " + "/".join(k)


def rgb_anzeige(stapel, kidx):
    kanaele, _ = rgb_art(kidx)
    rgb = np.stack([stapel[kidx[k]] for k in kanaele], axis=-1)
    return np.clip(np.nan_to_num(rgb) / RGB_MAX_REFLEKTANZ, 0, 1) ** (1 / RGB_GAMMA)


def _index_tif(pfad, werte, idx):
    tifffile.imwrite(pfad, werte, compression="zlib", predictor=True, metadata=None,   # Beschreibung muss ASCII sein
                     description=f"{idx} = {INDIZES[idx]['ascii']}; ungueltig = NaN")


# -----------------------------------------------------------------------------
# Schwellwert-Klassifizierung (gestresst / Übergang / vital) und Bewertung je Baumobjekt
# -----------------------------------------------------------------------------
# Je Index zwei frei wählbare Schwellen:  Wert < gestresst -> "gestresst";  gestresst <= Wert < vital -> "Übergang";
# Wert >= vital -> "vital". Gleiche Schwellen ergeben zwei Klassen. Alle hier verwendeten Indizes steigen mit
# zunehmender Vitalität (hoher Wert = vital).
# Baumobjekte = zusammenhängende Flächen (8er-Nachbarschaft) der aktuellen Maske ab OBJEKT_MIN_PX Pixeln (optional per
# Wasserscheide getrennt). Klasse je Baum:
#   gestresst  – Anteil gestresster Pixel >= anteil_markierung (so fallen auch teilweise geschädigte Kronen auf,
#                deren Mittelwert unauffällig ist)
#   vital      – sonst, wenn Anteil vitaler Pixel >= OBJEKT_VITAL_ANTEIL (Mehrheit; entspricht Median >= Schwelle vital)
#   Übergang   – alle übrigen
KLASSE_GESTRESST, KLASSE_UEBERGANG, KLASSE_VITAL, KLASSE_UNGUELTIG = 0, 1, 2, 255
KLASSENNAMEN = {KLASSE_GESTRESST: "gestresst", KLASSE_UEBERGANG: "Übergang", KLASSE_VITAL: "vital"}
KLASSEN_SPALTEN = ["Anteil_gestresst", "Anteil_Uebergang", "Anteil_vital", "Objekte", "Objekte_gestresst",
                   "Objekte_Uebergang", "Objekte_vital"]
OBJEKT_MIN_PX = 1500          # wie BAUM_MIN_FLAECHE_PX (≈ 0,09 m² bei 0,77 cm/px)
OBJEKT_VITAL_ANTEIL = 0.5     # Baum „vital“, wenn (und nicht gestresst) mindestens die Hälfte seiner Pixel vital ist
# Baumregel (ab 0.16): wie aus den Pixelklassen die Klasse des Baums wird
BAUMREGELN = {"anteil": "Anteil gestresster Pixel", "median": "Median je Baum"}


@dataclass
class Schwellen:
    gestresst: float
    vital: float
    anteil_markierung: float = 0.10      # Objekt markiert ab diesem Anteil gestresster Pixel
    kronenabstand_px: int = 0            # > 0: berührende Kronen per Wasserscheide trennen (Mindestabstand der Kronenmitten)
    herkunft: str = "manuell"            # Protokoll: manuell / Startwerte / aus Referenzflächen
    kronen_nir: bool = True              # Kronentrennung zusätzlich an der NIR-Helligkeit ausrichten (ab 0.8)
    kronen_raster: bool = False          # Kronenmitten aus dem Pflanzraster schätzen (ab 0.13)
    baumregel: str = "anteil"            # ab 0.16: "anteil" (Anteil gestresster Pixel) oder "median" (Median je Baum)

    def __post_init__(self):
        if self.vital < self.gestresst:
            raise ValueError(f"Schwelle „vital“ ({self.vital}) muss ≥ Schwelle „gestresst“ ({self.gestresst}) sein.")

    def protokoll(self):
        return {"herkunft": self.herkunft, "gestresst_unter": self.gestresst, "vital_ab": self.vital,
                "objekt_markiert_ab_anteil_gestresst": self.anteil_markierung, "objekt_min_px": OBJEKT_MIN_PX,
                "baumregel": BAUMREGELN.get(self.baumregel, self.baumregel),
                "objekt_klassen": ((f"gestresst: Median des Baums < {self.gestresst}; vital: Median >= {self.vital}; "
                                    "sonst Übergang") if self.baumregel == "median" else
                                   (f"gestresst: Anteil gestresster Pixel >= {self.anteil_markierung:.2f}; sonst vital: "
                                    f"Anteil vitaler Pixel >= {OBJEKT_VITAL_ANTEIL:.2f}; sonst Übergang")),
                "kronentrennung": (("Pflanzraster je Bild geschätzt (Ersatz: " if self.kronen_raster else "")
                                   + (f"Wasserscheide auf {'Maskenform + NIR-Helligkeit' if self.kronen_nir else 'Maskenform'}"
                                      f", Mindestabstand Kronenmitten {self.kronenabstand_px} px"
                                      if self.kronenabstand_px else "aus (zusammenhängende Flächen)")
                                   + (")" if self.kronen_raster else "")),
                "kronenkorrekturen": "von Hand, Datei " + os.path.join(AUSWERTUNG_UNTERORDNER, KRONEN_KORREKTUR_DATEI)
                                     + " je Aufnahmeordner"}


def klassifiziere(werte, schw):
    """uint8-Klassenbild: 0 gestresst, 1 Übergang, 2 vital, 255 ungültig."""
    kl = np.full(werte.shape, KLASSE_UNGUELTIG, np.uint8)
    g = np.isfinite(werte)
    kl[g & (werte < schw.gestresst)] = KLASSE_GESTRESST
    kl[g & (werte >= schw.gestresst) & (werte < schw.vital)] = KLASSE_UEBERGANG
    kl[g & (werte >= schw.vital)] = KLASSE_VITAL
    return kl


def klassenanteile(kl, region=None):
    r = kl if region is None else kl[region]
    n = int((r != KLASSE_UNGUELTIG).sum())
    anteile = {name: (float((r == k).sum()) / n if n else float("nan")) for k, name in KLASSENNAMEN.items()}
    return {"Pixel": n, **anteile}


KRONEN_NIR_GEWICHT = 0.5      # Anteil der NIR-Helligkeit an der „Kronenhöhe“ (Rest: Abstand zum Maskenrand)
KRONEN_NIR_SIGMA = 4.0        # Glättung des NIR (Pixel), damit einzelne Nadeln/Äste keine eigenen Mitten bilden

# Pflanzraster (Version 0.13): Weihnachtsbaumkulturen stehen in Reihen mit festem Abstand. Das Raster wird je Bild aus
# der Autokorrelation der (geglätteten, maskierten) NIR-Helligkeit geschätzt; je Rasterpunkt wird eine Kronenmitte
# gesetzt. So werden auch Kronen getrennt, die sich ohne Schattenlinie berühren.
RASTER_FAKTOR = 2              # Verkleinerung für die Schätzung (Geschwindigkeit)
RASTER_GLAETTUNG_PX = 12       # Glättung vor der Autokorrelation (volle Auflösung), unterdrückt Nadel-/Asttextur
RASTER_MIN_ABSTAND_PX = 50     # kürzester zulässiger Rasterabstand (volle Auflösung)
RASTER_MIN_SPITZE = 0.08       # Mindesthöhe der Autokorrelationsspitzen (1 = Nullverschiebung)
RASTER_SUCHE = 0.30            # Kronenmitte darf um diesen Anteil des Rasterabstands vom Rasterpunkt abweichen
RASTER_MIN_BELEGUNG = 0.30     # Anteil Maske im Umkreis (¼ Rasterabstand) des Rasterpunkts, sonst Lücke (kein Baum)
RASTER_EXTRA_ABSTAND = 0.5     # zusätzliche Kronenmitte abseits des Rasters nur, wenn so weit (· Rasterabstand) entfernt
KRONEN_KORREKTUR_DATEI = "Kronenkorrekturen.json"   # im Ergebnisordner VI_Auswertung des Aufnahmeordners
SCHNITT_BREITE_PX = 3          # ab 0.18: Breite der Schnittlinie (Korrektur „Krone teilen“ per Linie)
SCHNITT_ZUORDNUNG_PX = 6       # Pixel an der Schnittlinie gehen danach an die nächste Krone (bis zu diesem Abstand)


def schaetze_pflanzraster(maske, nir=None):
    """Schätzt das Pflanzraster einer Aufnahme. Rückgabe: dict mit den Rastervektoren a, b (dy, dx in Pixeln, volle
    Auflösung), 'abstand_px' (kürzester Vektor), 'staerke' (Höhe der schwächeren Spitze) – oder None, wenn kein
    eindeutiges Raster erkennbar ist."""
    f = RASTER_FAKTOR
    m = maske.astype(np.float32)
    if m.mean() < 0.05:
        return None
    # Helligkeit INNERHALB der Maske (Kronenmitten hell, Kronenränder dunkler); außerhalb 0. So bildet die
    # Autokorrelation die Lage der Kronenmitten ab und nicht die Form der Maske (die bei geschlossenen Beständen kaum
    # Struktur hat). Ohne NIR: Abstand zum Maskenrand.
    klein = (m.shape[1] // f, m.shape[0] // f)
    md = cv2.resize(m, klein, interpolation=cv2.INTER_AREA) > 0.5
    if nir is not None:
        s = cv2.resize(np.nan_to_num(nir).astype(np.float32), klein, interpolation=cv2.INTER_AREA)
    else:
        s = cv2.distanceTransform(md.astype(np.uint8), cv2.DIST_L2, 5)
    s = cv2.GaussianBlur(s, (0, 0), RASTER_GLAETTUNG_PX / f) * md
    s = (s - s[md].mean() * md).astype(np.float32)
    h, w = s.shape
    F = np.fft.rfft2(s, s=(2 * h, 2 * w))
    ac = np.fft.fftshift(np.fft.irfft2(np.abs(F) ** 2, s=(2 * h, 2 * w)))
    # Überlappung je Verschiebung ausgleichen (sonst fallen weite Verschiebungen künstlich ab)
    ov = np.outer(h - np.abs(np.arange(-h, h)), w - np.abs(np.arange(-w, w))).astype(np.float64)
    ac = ac / np.maximum(ov, 1) * (h * w)
    cy, cx = h, w
    ac /= ac[cy, cx]
    r_max = int(0.45 * min(h, w))
    fen = ac[cy - r_max:cy + r_max + 1, cx - r_max:cx + r_max + 1].astype(np.float32)
    k = max(3, int(0.6 * RASTER_MIN_ABSTAND_PX / f) | 1)
    spitzen = (fen >= cv2.dilate(fen, np.ones((k, k), np.uint8))) & (fen > RASTER_MIN_SPITZE)
    pk = [(float(y - r_max), float(x - r_max), float(fen[y, x])) for y, x in np.argwhere(spitzen)]
    pk = [p for p in pk if np.hypot(p[0], p[1]) >= RASTER_MIN_ABSTAND_PX / f and (p[0] > 0 or (p[0] == 0 and p[1] > 0))]
    if len(pk) < 2:
        return None
    pk.sort(key=lambda p: np.hypot(p[0], p[1]))
    a = pk[0]
    b = None
    for p in pk[1:]:
        cosw = (a[0] * p[0] + a[1] * p[1]) / (np.hypot(a[0], a[1]) * np.hypot(p[0], p[1]))
        if abs(cosw) < np.cos(np.radians(35)):
            b = p
            break
    if b is None or np.hypot(b[0], b[1]) > 2.0 * np.hypot(a[0], a[1]):
        return None
    va, vb = np.array(a[:2]) * f, np.array(b[:2]) * f
    return {"a": va.round(1).tolist(), "b": vb.round(1).tolist(),
            "abstand_px": float(np.hypot(*va)), "abstand2_px": float(np.hypot(*vb)),
            "staerke": round(min(a[2], b[2]), 3)}


def _raster_saatpunkte(maske, dist, hoehe, raster):
    """Kronenmitten aus dem Pflanzraster: Phase (Verschiebung) so, dass die Rasterpunkte möglichst auf hellen,
    randfernen Stellen liegen; dann jeden Punkt im Umkreis RASTER_SUCHE · Abstand auf das lokale Maximum schieben.
    Rasterpunkte in Lücken (kaum Maske) erhalten keine Mitte."""
    h, w = maske.shape
    a, b = np.array(raster["a"], float), np.array(raster["b"], float)
    abstand = min(np.hypot(*a), np.hypot(*b))
    S = cv2.GaussianBlur(hoehe.astype(np.float32), (0, 0), max(2.0, 0.08 * abstand))
    M = np.column_stack([a, b])                         # Punkt = M @ (i, j)
    ecken = np.array([[0, 0], [0, w], [h, 0], [h, w]], float)
    ij = np.linalg.solve(M, ecken.T)
    i0, i1 = int(np.floor(ij[0].min())) - 1, int(np.ceil(ij[0].max())) + 1
    j0, j1 = int(np.floor(ij[1].min())) - 1, int(np.ceil(ij[1].max())) + 1
    I, J = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
    P0 = I.ravel()[:, None] * a + J.ravel()[:, None] * b
    n = max(8, int(np.ceil(abstand / 4)))
    bester, phase = -1.0, np.zeros(2)
    for s_ in np.arange(n) / n:
        for t_ in np.arange(n) / n:
            P = P0 + s_ * a + t_ * b
            yy, xx = np.round(P[:, 0]).astype(int), np.round(P[:, 1]).astype(int)
            ok = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
            if ok.sum() < 3:
                continue
            wert = float(S[yy[ok], xx[ok]].mean())
            if wert > bester:
                bester, phase = wert, s_ * a + t_ * b
    P = P0 + phase
    r = max(2, int(RASTER_SUCHE * abstand))
    rb = max(2, int(0.25 * abstand))
    kandidaten = []
    for py, px in P:
        if not (-0.5 * abstand <= py < h + 0.5 * abstand and -0.5 * abstand <= px < w + 0.5 * abstand):
            continue
        cy, cx = int(round(min(max(py, 0), h - 1))), int(round(min(max(px, 0), w - 1)))
        y0, y1, x0, x1 = max(0, cy - rb), min(h, cy + rb + 1), max(0, cx - rb), min(w, cx + rb + 1)
        if maske[y0:y1, x0:x1].mean() < RASTER_MIN_BELEGUNG:
            continue                                     # Lücke im Raster (fehlender Baum)
        y0, y1, x0, x1 = max(0, cy - r), min(h, cy + r + 1), max(0, cx - r), min(w, cx + r + 1)
        fen = np.where(maske[y0:y1, x0:x1], S[y0:y1, x0:x1], -1)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        fen[(yy - cy) ** 2 + (xx - cx) ** 2 > r * r] = -1
        k = int(np.argmax(fen))
        if fen.flat[k] < 0:
            continue
        kandidaten.append((float(fen.flat[k]), y0 + k // fen.shape[1], x0 + k % fen.shape[1]))
    saat = []                                            # zu nahe Punkte zusammenfassen (stärkerer bleibt)
    for wert, y, x in sorted(kandidaten, reverse=True):
        if all((y - sy) ** 2 + (x - sx) ** 2 >= (0.5 * abstand) ** 2 for sy, sx in saat):
            saat.append((y, x))
    return saat


def _wasserscheide(maske, hoehe, saat):
    m = maske.astype(np.uint8)
    marker = np.zeros(maske.shape, np.int32)
    for k, (y, x) in enumerate(saat, 1):
        cv2.circle(marker, (int(x), int(y)), 2, k, -1)
    marker[m == 0] = 0
    hintergrund = len(saat) + 1
    marker[m == 0] = hintergrund
    relief = (255 - cv2.normalize(hoehe, None, 0, 255, cv2.NORM_MINMAX)).astype(np.uint8)
    cv2.watershed(cv2.merge([relief, relief, relief]), marker)
    marker[(marker == hintergrund) | (marker < 0) | (m == 0)] = 0
    return marker


def objekt_labels(maske, kronenabstand_px=0, nir=None, raster=False, korrekturen=None, info=None):
    """Labelbild der Baumobjekte (0 = Hintergrund).
    kronenabstand_px = 0 und raster = False: zusammenhängende Flächen der Maske (8er-Nachbarschaft).
    kronenabstand_px > 0: Wasserscheiden-Segmentierung. Ohne `nir` auf der Distanztransformation: Saatpunkte sind
    lokale Maxima der Distanz zum Maskenrand (= Kronenmitten) mit einem Mindestabstand von kronenabstand_px;
    berührende Kronen werden an den Einschnürungen zwischen ihnen getrennt.
    Mit `nir` (ab 0.8): „Kronenhöhe“ = (1 − g) · Distanz (bis zum halben Kronenabstand normiert) + g · NIR (geglättet,
    auf P95 der Maske normiert), g = KRONEN_NIR_GEWICHT. Kronenmitten sind weit vom Rand UND hell, die Grenzen
    zwischen Kronen verlaufen zusätzlich entlang dunkler (beschatteter) Bereiche.
    raster = True (ab 0.13): Kronenmitten aus dem geschätzten Pflanzraster (schaetze_pflanzraster); der Kronenabstand
    wird dann aus dem Raster genommen. Ist kein Raster erkennbar, gilt das Verfahren mit kronenabstand_px.
    korrekturen (ab 0.13): Liste von Korrekturen von Hand, je {"art": "teilen", "xy": [x, y]} (zusätzliche
    Kronenmitte), {"art": "verbinden", "xy": [[x1, y1], [x2, y2]]} (zwei Objekte zusammenlegen) oder (ab 0.18)
    {"art": "schnitt", "xy": [[x1, y1], [x2, y2]]} (Schnittlinie: die Maske wird entlang der Linie getrennt, danach
    gehen die Linienpixel an die nächste Krone zurück).
    `info` (dict) erhält das verwendete Verfahren und ggf. das Raster."""
    korrekturen = korrekturen or []
    teilen = [k["xy"] for k in korrekturen if k.get("art") == "teilen"]
    verbinden = [k["xy"] for k in korrekturen if k.get("art") == "verbinden"]
    schnitte = [k["xy"] for k in korrekturen if k.get("art") == "schnitt"]
    info = {} if info is None else info
    if schnitte:
        original = maske
        maske = _schneiden(maske, schnitte)
        lab = objekt_labels(maske, kronenabstand_px, nir, raster, [k for k in korrekturen if k.get("art") == "teilen"],
                            info)
        lab = _schnitt_zuordnen(lab, original & ~maske, original)
        info["korrekturen"] = len(korrekturen)
        return _verbinden(lab, verbinden)
    m = maske.astype(np.uint8)
    r = schaetze_pflanzraster(maske, nir) if raster else None
    abstand = r["abstand_px"] if r else kronenabstand_px
    info.update(verfahren=("Pflanzraster" if r else "Wasserscheide" if abstand else "zusammenhängende Flächen"),
                raster=r, korrekturen=len(korrekturen))
    if raster and not r:
        info["hinweis"] = "kein Pflanzraster erkennbar – Kronenabstand verwendet"
    if not abstand and not teilen:
        lab = cv2.connectedComponents(m, connectivity=8)[1]
        return _verbinden(lab, verbinden)
    dist = cv2.distanceTransform(m, cv2.DIST_L2, 5)
    abstand_n = abstand or float(np.percentile(dist[m > 0], 99) * 2 if m.any() else 1)
    if nir is not None and maske.any():
        ns = cv2.GaussianBlur(np.nan_to_num(nir).astype(np.float32), (0, 0), KRONEN_NIR_SIGMA)
        ns = np.clip(ns / max(float(np.percentile(ns[maske], 95)), 1e-6), 0, 1)
        dn = np.clip(dist / (0.5 * abstand_n), 0, 1)
        hoehe = ((1 - KRONEN_NIR_GEWICHT) * dn + KRONEN_NIR_GEWICHT * ns).astype(np.float32)
        hoehe[m == 0] = 0
        suche = cv2.GaussianBlur(hoehe, (0, 0), 3)
    else:
        hoehe = suche = dist
    if r:
        saat = _raster_saatpunkte(maske, dist, hoehe, r)
        # Bäume abseits des Rasters (unregelmäßig gepflanzt, nachgepflanzt): deutliche lokale Maxima der Kronenhöhe,
        # die weiter als RASTER_EXTRA_ABSTAND · Rasterabstand von allen Rastermitten entfernt sind
        k = max(3, int(RASTER_EXTRA_ABSTAND * abstand) | 1)
        nachbar_max = cv2.dilate(suche, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        spitzen = (suche >= nachbar_max) & (dist >= 0.25 * abstand)
        n, sp = cv2.connectedComponents(spitzen.astype(np.uint8), connectivity=8)
        extra = 0
        for i in range(1, n):
            ys, xs = np.nonzero(sp == i)
            y, x = int(ys.mean()), int(xs.mean())
            if all((y - sy) ** 2 + (x - sx) ** 2 >= (RASTER_EXTRA_ABSTAND * abstand) ** 2 for sy, sx in saat):
                saat.append((y, x))
                extra += 1
        info["kronenmitten_abseits_raster"] = extra
    elif abstand:
        k = max(3, int(abstand) | 1)
        nachbar_max = cv2.dilate(suche, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        spitzen = (suche >= nachbar_max) & (dist >= 0.25 * abstand)
        n, sp = cv2.connectedComponents(spitzen.astype(np.uint8), connectivity=8)
        saat = []
        for i in range(1, n):
            ys, xs = np.nonzero(sp == i)
            saat.append((int(ys.mean()), int(xs.mean())))
    else:
        saat = []
    # Maskenflächen ohne Kronenmitte (z. B. abseits des Rasters) behalten: Mitte = randfernster Punkt
    n, komp = cv2.connectedComponents(m, connectivity=8)
    belegt = {int(komp[y, x]) for y, x in saat}
    for i in range(1, n):
        if i not in belegt:
            d = np.where(komp == i, dist, -1)
            y, x = np.unravel_index(int(np.argmax(d)), d.shape)
            saat.append((int(y), int(x)))
    h, w = maske.shape
    for x, y in teilen:                                   # Korrektur: zusätzliche Kronenmitte
        y, x = int(round(y)), int(round(x))
        if 0 <= y < h and 0 <= x < w and maske[y, x]:
            saat.append((y, x))
    info["kronenmitten"] = len(saat)
    lab = _wasserscheide(maske, hoehe, saat)
    return _verbinden(lab, verbinden)


def _schneiden(maske, linien):
    """Korrektur „Krone teilen“ per Linie (ab 0.18): Maske entlang der Linien auf False setzen."""
    m = maske.astype(np.uint8).copy()
    for (x1, y1), (x2, y2) in linien:
        cv2.line(m, (int(round(x1)), int(round(y1))), (int(round(x2)), int(round(y2))), 0, SCHNITT_BREITE_PX)
    return m.astype(bool)


def _schnitt_zuordnen(lab, linie, original):
    """Pixel der Schnittlinien (nur Maskenpixel) der nächsten Krone zuordnen."""
    from scipy import ndimage
    linie = cv2.dilate(linie.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0   # inkl. Grenzpixel daneben
    offen = linie & original & (lab == 0)
    if not offen.any():
        return lab
    d, (iy, ix) = ndimage.distance_transform_edt(lab == 0, return_indices=True)
    neu = offen & (d <= SCHNITT_ZUORDNUNG_PX)
    lab = lab.copy()
    lab[neu] = lab[iy[neu], ix[neu]]
    return lab


def _verbinden(lab, paare):
    """Korrektur: Objekte an zwei Punkten zusammenlegen (Label des zweiten Punkts -> Label des ersten)."""
    if not paare:
        return lab
    lab = lab.copy()
    h, w = lab.shape
    for (x1, y1), (x2, y2) in paare:
        p1 = (int(round(y1)), int(round(x1)))
        p2 = (int(round(y2)), int(round(x2)))
        if not all(0 <= p[0] < h and 0 <= p[1] < w for p in (p1, p2)):
            continue
        l1, l2 = int(lab[p1]), int(lab[p2])
        if l1 and l2 and l1 != l2:
            lab[lab == l2] = l1
    return lab


def _korrektur_pfad(ordner):
    return os.path.join(ordner, AUSWERTUNG_UNTERORDNER, KRONEN_KORREKTUR_DATEI)


def _korrektur_schluessel(name, geschaerft=False):
    return name + (" (Panchro-geschärft)" if geschaerft else "")


def lade_kronenkorrekturen(ordner, name, geschaerft=False):
    """Korrekturen von Hand für eine Aufnahme (Liste, leer wenn keine)."""
    p = _korrektur_pfad(ordner)
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    return list(d.get(_korrektur_schluessel(name, geschaerft), []))


def speichere_kronenkorrekturen(ordner, name, korrekturen, geschaerft=False):
    """Speichert die Korrekturen einer Aufnahme in <ordner>\\VI_Auswertung\\Kronenkorrekturen.json."""
    p = _korrektur_pfad(ordner)
    d = {}
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
    schluessel = _korrektur_schluessel(name, geschaerft)
    if korrekturen:
        d[schluessel] = korrekturen
    else:
        d.pop(schluessel, None)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def kronenkorrekturen_fuer(aufn):
    return lade_kronenkorrekturen(aufn.ordner, aufn.name, aufn.geschaerft)


def bewerte_objekte(werte, kl, maske, schw, nir=None, korrekturen=None, info=None):
    """Baumobjekte der Maske bewerten. Rückgabe: (Labelbild, Liste je Objekt, Objekte < OBJEKT_MIN_PX ausgelassen).
    `nir` (NIR-Reflektanz der Aufnahme) wird für die Kronentrennung genutzt, wenn schw.kronen_nir gesetzt ist;
    `korrekturen` = Korrekturen von Hand (s. objekt_labels)."""
    from scipy import ndimage
    lab = objekt_labels(maske, schw.kronenabstand_px, nir if schw.kronen_nir else None,
                        raster=schw.kronen_raster, korrekturen=korrekturen, info=info)
    objekte = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        teil = lab[sl] == i
        flaeche = int(teil.sum())
        if flaeche < OBJEKT_MIN_PX:
            continue
        yy, xx = np.nonzero(teil)
        werte_o, kl_o = werte[sl][teil], kl[sl][teil]
        a = klassenanteile(kl_o)
        st = statistik(werte_o)
        objekte.append({"nr": len(objekte) + 1, "label": i, "pixel": flaeche,
                        "x": round(float(xx.mean() + sl[1].start), 1), "y": round(float(yy.mean() + sl[0].start), 1),
                        "box": (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop),
                        "mittel": st["Mittel"], "median": st["Median"],
                        "anteil_gestresst": a["gestresst"], "anteil_uebergang": a["Übergang"], "anteil_vital": a["vital"],
                        "klasse": _objektklasse(a, schw, st["Median"])})
        objekte[-1]["markiert"] = objekte[-1]["klasse"] == KLASSE_GESTRESST
    return lab, _nummerieren(objekte)


def _nummerieren(objekte):
    """Baumnummern in Leserichtung (ab 0.14.1): zeilenweise von oben nach unten, in der Zeile von links nach rechts.
    Eine Zeile umfasst Bäume, deren Mitte weniger als einen halben Kronendurchmesser (Median) unter der Mitte des
    ersten Baums der Zeile liegt. Die Nummer hängt damit nur von der Lage ab, nicht von der Reihenfolge der Trennung."""
    if not objekte:
        return objekte
    band = 0.5 * float(np.median([2 * np.sqrt(o["pixel"] / np.pi) for o in objekte]))
    rest = sorted(objekte, key=lambda o: o["y"])
    reihen = []
    while rest:
        y0 = rest[0]["y"]
        zeile = [o for o in rest if o["y"] - y0 < band]
        rest = [o for o in rest if o["y"] - y0 >= band]
        reihen.append(sorted(zeile, key=lambda o: o["x"]))
    neu = [o for zeile in reihen for o in zeile]
    for i, o in enumerate(neu, 1):
        o["nr"] = i
    return neu


def _objektklasse(a, schw, median=None):
    if not a["Pixel"]:
        return KLASSE_UNGUELTIG
    if getattr(schw, "baumregel", "anteil") == "median":   # Median der Indexwerte des Baums mit den Schwellen
        if median is None or median != median:
            return KLASSE_UNGUELTIG
        if median < schw.gestresst:
            return KLASSE_GESTRESST
        return KLASSE_VITAL if median >= schw.vital else KLASSE_UEBERGANG
    if a["gestresst"] >= schw.anteil_markierung:
        return KLASSE_GESTRESST
    if a["vital"] >= OBJEKT_VITAL_ANTEIL:
        return KLASSE_VITAL
    return KLASSE_UEBERGANG


def objekt_klassenbild(lab, objekte):
    """uint8-Bild: Klasse des Baums je Pixel (0 gestresst, 1 Übergang, 2 vital), 255 = kein (bewerteter) Baum."""
    tabelle = np.full(int(lab.max()) + 1, KLASSE_UNGUELTIG, np.uint8)
    for o in objekte:
        tabelle[o["label"]] = o["klasse"]
    return tabelle[lab]


def _klassen_zellen(kl, region, objekte=None):
    a = klassenanteile(kl, region)
    zellen = [f"{a[k]:.4f}" if a["Pixel"] else "" for k in ("gestresst", "Übergang", "vital")]
    if objekte is None:
        return zellen + ["", "", "", ""]
    return zellen + [len(objekte)] + [sum(o["klasse"] == k for o in objekte)
                                       for k in (KLASSE_GESTRESST, KLASSE_UEBERGANG, KLASSE_VITAL)]


# -----------------------------------------------------------------------------
# Export einer Aufnahme
# -----------------------------------------------------------------------------
def exportiere(aufn, index_aktiv, vorgabe=None, rois=(), figur=None, pixelwerte=False, maske=None, alle_raster=False,
               schwellen=None):
    """Schreibt Index-Raster, Maske, Statistik aller Indizes, ROI-Pixelwerte (optional), Parameter und Abbildung.
    `maske` kann bereits berechnet übergeben werden (sonst aus `vorgabe`). Raster: nur der angezeigte Index,
    mit alle_raster=True alle Indizes. Die Statistik enthält immer alle Indizes. `schwellen` = {Index: Schwellen}:
    Klassenanteile für diese Indizes; für den angezeigten Index zusätzlich Klassenraster und (mit Maske) Objektliste.
    Gibt den Ergebnisordner zurück."""
    schwellen = schwellen or {}
    ziel = os.path.join(aufn.ordner, AUSWERTUNG_UNTERORDNER, aufn.name)
    os.makedirs(ziel, exist_ok=True)
    form = aufn.stapel.shape[1:]
    kidx = aufn.kanalindex
    if vorgabe is not None and maske is None:
        maske = vorgabe.berechne(aufn)
    mname = vorgabe.name if vorgabe else ""
    werte = {i: berechne_index(aufn.stapel, kidx, i) for i in INDIZES}

    for i, w in werte.items():
        if alle_raster or i == index_aktiv:
            _index_tif(os.path.join(ziel, f"{aufn.name}_{i}.tif"), w, i)
    if maske is not None:
        tifffile.imwrite(os.path.join(ziel, f"{aufn.name}_Maske_{mname}.tif"), maske.astype(np.uint8),
                         compression="zlib", metadata=None,
                         description=f"1 = {mname}".encode("ascii", "replace").decode())

    reg = regionen(form, maske, mname, rois)
    klassen = {i: klassifiziere(werte[i], schw) for i, schw in schwellen.items()}
    objekte, labels = {}, {}
    if maske is not None:
        for i in klassen:
            labels[i], objekte[i] = bewerte_objekte(werte[i], klassen[i], maske, schwellen[i],
                                                    aufn.kronenstapel[aufn.kanalindex["NIR"]], kronenkorrekturen_fuer(aufn))
    with open(os.path.join(ziel, f"{aufn.name}_Statistik.csv"), "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(["Aufnahme", "Index", "Region"] + STAT_SPALTEN + KLASSEN_SPALTEN)
        for i, w in werte.items():
            for rname, m in reg:
                s = statistik(w[m])
                kz = (_klassen_zellen(klassen[i], m, objekte.get(i) if rname == mname else None)
                      if i in klassen else [""] * len(KLASSEN_SPALTEN))
                wr.writerow([aufn.name, i, rname] + [s["Pixel"]] + [f"{s[k]:.4f}" for k in STAT_SPALTEN[1:]] + kz)
    if index_aktiv in klassen:
        tifffile.imwrite(os.path.join(ziel, f"{aufn.name}_{index_aktiv}_Klassen.tif"), klassen[index_aktiv],
                         compression="zlib", metadata=None,
                         description="0 = gestresst, 1 = Uebergang, 2 = vital, 255 = ungueltig")
        if index_aktiv in objekte:
            with open(os.path.join(ziel, f"{aufn.name}_{index_aktiv}_Objekte.csv"), "w", newline="",
                      encoding="utf-8-sig") as f:
                wr = csv.writer(f, delimiter=";")
                wr.writerow(["Objekt", "Pixel", "x_Mitte", "y_Mitte", "x0", "y0", "x1", "y1", f"{index_aktiv}_Mittel",
                             f"{index_aktiv}_Median", "Anteil_gestresst", "Anteil_Uebergang", "Anteil_vital", "Klasse"])
                for o in objekte[index_aktiv]:
                    wr.writerow([o["nr"], o["pixel"], o["x"], o["y"], *o["box"], f"{o['mittel']:.4f}", f"{o['median']:.4f}",
                                 f"{o['anteil_gestresst']:.4f}", f"{o['anteil_uebergang']:.4f}", f"{o['anteil_vital']:.4f}",
                                 KLASSENNAMEN.get(o["klasse"], "")])
            tifffile.imwrite(os.path.join(ziel, f"{aufn.name}_{index_aktiv}_Baumklassen.tif"),
                             objekt_klassenbild(labels[index_aktiv], objekte[index_aktiv]), compression="zlib",
                             metadata=None, description="Klasse je Baum: 0 = gestresst, 1 = Uebergang, 2 = vital, "
                                                        "255 = kein Baum")

    if pixelwerte and rois:
        with open(os.path.join(ziel, f"{aufn.name}_ROI_Pixelwerte.csv"), "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f, delimiter=";")
            kn = [k for k in KANALNAMEN if k in kidx]
            wr.writerow(["ROI", "x", "y"] + [f"Refl_{k}" for k in kn] + list(INDIZES)
                        + ([mname] if maske is not None else []))
            for roi in rois:
                x0, y0, x1, y1 = roi["box"]
                for y in range(y0, y1):
                    for x in range(x0, x1):
                        wr.writerow([roi["name"], x, y]
                                    + [f"{aufn.stapel[kidx[k], y, x]:.5f}" for k in kn]
                                    + [f"{werte[i][y, x]:.4f}" for i in INDIZES]
                                    + ([int(maske[y, x])] if maske is not None else []))

    with open(os.path.join(ziel, f"{aufn.name}_Parameter.json"), "w", encoding="utf-8") as f:
        json.dump({"software": f"VI-Auswertung {VERSION}", "exportiert": _dt.datetime.now().isoformat(timespec="seconds"),
                   "aufnahme": aufn.name, "ordner": aufn.ordner, "datenquelle": aufn.quelle,
                   "bildgroesse_px": [int(form[1]), int(form[0])], "kanaele": list(aufn.kanalindex),
                   "panchro_geschaerft": aufn.geschaerft, "panchro": aufn.meta.get("panchro"),
                   "indizes": {k: v["formel"] for k, v in INDIZES.items()}, "angezeigter_index": index_aktiv,
                   "maskierung": {"min_nenner": MIN_NENNER, "min_reflektanz": MIN_REFLEKTANZ, "wertebereich": [-1, 1]},
                   "maske": vorgabe.protokoll() if vorgabe else None,
                   "maskenanteil": None if maske is None else round(float(maske.mean()), 4),
                   "rois_x0_y0_x1_y1": {r["name"]: list(r["box"]) for r in rois},
                   "schwellwerte": {i: schw.protokoll() for i, schw in schwellen.items()},
                   "metadaten": aufn.meta}, f, indent=2, ensure_ascii=False, default=str)

    if figur is not None:
        figur.savefig(os.path.join(ziel, f"{aufn.name}_{index_aktiv}_Ansicht.png"), dpi=200)
    return ziel


# -----------------------------------------------------------------------------
# Ordnerauswertung (alle Aufnahmen eines oder mehrerer Ordner)
# -----------------------------------------------------------------------------
def werte_ordner_aus(wurzel, vorgabe=None, fortschritt=print, abbrechen=lambda: False, raster=False,
                     raster_indizes=None, schwellen=None):
    """Wertet alle Aufnahmen unterhalb von `wurzel` aus: je Aufnahme, Index und Region (Gesamtbild,
    ggf. Maske) eine Statistikzeile. Ergebnis: Datei Ordnerauswertung_<Zeit>.csv im Unterordner VI_Auswertung.
    Die CSV wird zeilenweise geschrieben, ein Abbruch hinterlässt also eine gültige Teilauswertung.
    Mit raster=True werden zusätzlich Indexraster (und Maske) jeder Aufnahme gespeichert, und zwar für
    `raster_indizes` (Liste) bzw. alle Indizes, wenn None.
    `schwellen` = {Index: Schwellen}: zusätzlich Klassenanteile und (Maskenregion) Anzahl Bäume je Klasse.
    Rückgabe: (CSV-Pfad, Anzahl ok, Liste der Fehler)."""
    schwellen = schwellen or {}
    liste = liste_aufnahmen_rekursiv(wurzel)
    if not liste:
        raise FileNotFoundError(f"Keine Aufnahmen in {wurzel} gefunden.")
    zielordner = os.path.join(wurzel, AUSWERTUNG_UNTERORDNER)
    os.makedirs(zielordner, exist_ok=True)
    stempel = _dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    csv_pfad = os.path.join(zielordner, f"Ordnerauswertung_{stempel}.csv")
    ok, fehler = 0, []
    with open(csv_pfad, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(["Ordner", "Aufnahme", "Zeit", "Lat", "Lon", "Index", "Region"] + STAT_SPALTEN
                    + ["Maskenanteil"] + KLASSEN_SPALTEN + ["Status"])
        for i, (ordner, name) in enumerate(liste, 1):
            if abbrechen():
                fehler.append(("—", "abgebrochen durch Nutzer"))
                break
            rel = os.path.relpath(ordner, wurzel)
            fortschritt((i - 1, len(liste), os.path.join(rel, name)))
            try:
                a = lade_aufnahme(ordner, name, fortschritt=lambda t: None)
                maske = vorgabe.berechne(a) if vorgabe else None
            except Exception as e:
                msg = str(e).splitlines()[0]
                fehler.append((os.path.join(rel, name), msg))
                wr.writerow([rel, name, "", "", "", "", ""] + [""] * len(STAT_SPALTEN) + [""]
                            + [""] * len(KLASSEN_SPALTEN) + [f"FEHLER: {msg}"])
                f.flush()
                continue
            reg = regionen(a.stapel.shape[1:], maske, vorgabe.name if vorgabe else "")
            anteil = "" if maske is None else f"{maske.mean():.4f}"
            lat, lon = a.meta.get("lat", float("nan")), a.meta.get("lon", float("nan"))
            rz = os.path.join(ordner, AUSWERTUNG_UNTERORDNER, name)
            if raster:
                os.makedirs(rz, exist_ok=True)
                if maske is not None:
                    tifffile.imwrite(os.path.join(rz, f"{name}_Maske_{vorgabe.name}.tif"), maske.astype(np.uint8),
                                     compression="zlib", metadata=None, description=f"1 = {vorgabe.name}")
            for idx in INDIZES:
                w = berechne_index(a.stapel, a.kanalindex, idx)
                if raster and (raster_indizes is None or idx in raster_indizes):
                    _index_tif(os.path.join(rz, f"{name}_{idx}.tif"), w, idx)
                kl = klassifiziere(w, schwellen[idx]) if idx in schwellen else None
                obj = (bewerte_objekte(w, kl, maske, schwellen[idx], a.kronenstapel[a.kanalindex["NIR"]],
                                       kronenkorrekturen_fuer(a))[1]
                       if kl is not None and maske is not None else None)
                for rname, m in reg:
                    s = statistik(w[m])
                    kz = (_klassen_zellen(kl, m, obj if rname != "Gesamtbild" else None) if kl is not None
                          else [""] * len(KLASSEN_SPALTEN))
                    wr.writerow([rel, name, a.meta.get("zeit", ""), f"{lat:.8f}", f"{lon:.8f}", idx, rname, s["Pixel"]]
                                + [f"{s[k]:.4f}" for k in STAT_SPALTEN[1:]]
                                + [anteil if rname != "Gesamtbild" else ""] + kz + ["ok"])
            f.flush()
            ok += 1
    with open(csv_pfad[:-4] + "_Parameter.json", "w", encoding="utf-8") as f:
        json.dump({"software": f"VI-Auswertung {VERSION}", "erstellt": stempel, "wurzelordner": wurzel,
                   "ordner": [os.path.relpath(o, wurzel) for o in finde_aufnahmeordner(wurzel)],
                   "aufnahmen_gesamt": len(liste), "ausgewertet": ok, "fehler": fehler,
                   "kanalzahl": KANALZAHL or "automatisch", "panchro_schaerfen": PANCHRO_SCHAERFEN,
                   "indizes": {k: v["formel"] for k, v in INDIZES.items()},
                   "maskierung": {"min_nenner": MIN_NENNER, "min_reflektanz": MIN_REFLEKTANZ, "wertebereich": [-1, 1]},
                   "maske": vorgabe.protokoll() if vorgabe else None,
                   "schwellwerte": {i: schw.protokoll() for i, schw in schwellen.items()},
                   "indexraster_gespeichert": (raster_indizes or list(INDIZES)) if raster else False}, f, indent=2, ensure_ascii=False, default=str)
    fortschritt((len(liste), len(liste), "fertig"))
    return csv_pfad, ok, fehler


# -----------------------------------------------------------------------------
# Schwellen aus Referenzflächen (vitale / geschädigte Bäume) ableiten
# -----------------------------------------------------------------------------
# Literaturwerte nur zur ORIENTIERUNG (Anzeige). Prüfung 2026-10-31: auf eigene Daten angewendet klassifizieren sie
# nahezu alle Baumpixel als vital (Grenzen trennen Vegetation/Boden in Acker- und Weinbau, nicht Stress in dichten
# Nadelkronen; RedEdge-NDVI zudem hoch, vgl. Wang 2021 S. 15). Daher keine Literatur-Standardwerte.
LITERATUR_ORIENTIERUNG = {
    "NDVI": "< 0,33 ungesund · 0,33–0,66 gesund · > 0,66 sehr gesund (Wang 2021, S. 1; Vera-Esmeraldas et al. 2025, "
            "S. 12); gesund 0,6–0,9, Stress < 0,4 (Nguyen et al. 2025, S. 2); Balsamtanne 0,50–0,80 (MacDonald et al. "
            "2025, S. 8)",
    "GNDVI": "gesund 0,5–0,8, starker Stress < 0,3 (Nguyen et al. 2025, S. 3)",
    "EVI": "gesund 0,2–0,8, schwaches Wachstum < 0,15 (Nguyen et al. 2025, S. 3)",
    "EVI2": "Balsamtanne 0,52–0,75 (MacDonald et al. 2025, S. 9)",
    "ReNDVI": "< 0,1 keine Vegetation, Rasen 0,2–0,5, Wald 0,5–0,85 (Wang 2021, S. 1, 15) – Dichte, nicht Stress",
    "NGRDI": "< 0,15 Waldboden (Maskierung bei Huo et al. 2025, S. 5) – keine Stressgrenze",
}
REF_KLASSEN = {1: "vital", 0: "geschädigt"}
REF_MAX_PIXEL = 5000           # Stichprobe je Referenzfläche


class Referenzen:
    """Referenzflächen vitaler und geschädigter Bäume. Je Fläche werden die Werte ALLER Indizes gespeichert,
    damit Schwellen für jeden Index ohne erneutes Laden der Bilder abgeleitet werden können."""

    def __init__(self):
        self.flaechen = []     # {nr, klasse, aufnahme, ordner, xy, maske, pixel, werte: {Index: ndarray}}

    def hinzufuegen(self, aufn, xy, klasse, maske=None, maskenname=""):
        form = aufn.stapel.shape[1:]
        poly = polygon_maske(form, xy)
        if maske is not None:
            poly &= maske
        ys, xs = np.nonzero(poly)
        if ys.size == 0:
            return 0
        rng = np.random.default_rng(len(self.flaechen))
        if ys.size > REF_MAX_PIXEL:
            wahl = rng.choice(ys.size, REF_MAX_PIXEL, replace=False)
            ys, xs = ys[wahl], xs[wahl]
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        teil = aufn.stapel[:, y0:y1, x0:x1]
        werte = {}
        for i in INDIZES:
            w = berechne_index(teil, aufn.kanalindex, i)[ys - y0, xs - x0]
            werte[i] = w[np.isfinite(w)].astype(np.float32)
        # Reflektanz je Kanal für dieselben Pixel (Kanalanalyse, Version 0.12)
        kanaele = {k: teil[aufn.kanalindex[k]][ys - y0, xs - x0].astype(np.float32)
                   for k in KANALNAMEN if k in aufn.kanalindex}
        nr = max([f["nr"] for f in self.flaechen], default=0) + 1
        self.flaechen.append({"nr": nr, "klasse": int(klasse), "aufnahme": aufn.name, "ordner": aufn.ordner,
                              "xy": np.round(np.asarray(xy), 1).tolist(), "maske": maskenname or "keine",
                              "pixel": int(ys.size), "werte": werte, "geschaerft": aufn.geschaerft,
                              "panchro_nur_kronen": bool(aufn.meta.get("panchro_nur_kronen", False)),
                              "kanaele": kanaele, "kanaele_herkunft": "beim Einzeichnen"})
        return int(ys.size)

    def entfernen(self, nr):
        self.flaechen = [f for f in self.flaechen if f["nr"] != nr]

    def anzahl(self):
        v = sum(1 for f in self.flaechen if f["klasse"] == 1)
        return v, len(self.flaechen) - v

    def speichern(self, pfad):
        import joblib
        joblib.dump({"version": VERSION, "indizes": list(INDIZES), "flaechen": self.flaechen}, pfad, compress=3)

    @classmethod
    def laden(cls, pfad):
        """Lädt eine mit `speichern` erzeugte Datei (nur eigene Dateien laden: joblib nutzt pickle)."""
        import joblib
        d = joblib.load(pfad)
        r = cls()
        r.flaechen = d["flaechen"]
        fehlend = [i for i in INDIZES if any(i not in f["werte"] for f in r.flaechen)]
        if fehlend:
            raise ValueError(f"Die Referenzdatei enthält keine Werte für: {', '.join(fehlend)}")
        return r

    def zusammenfuehren(self, andere):
        """Fügt die Flächen einer zweiten Referenzsammlung hinzu (z. B. aus einem anderen Bestand).
        Flächen werden neu nummeriert; exakt gleiche Flächen (Ordner, Aufnahme, Klasse, Umriss) werden übersprungen.
        Rückgabe: (hinzugefügt, übersprungen)."""
        def schluessel(f):
            return (os.path.normcase(os.path.normpath(f["ordner"])), f["aufnahme"], bool(f.get("geschaerft")),
                    f["klasse"],
                    tuple(map(tuple, np.round(np.asarray(f["xy"], float), 1).tolist())))
        vorhanden = {schluessel(f) for f in self.flaechen}
        nr = max([f["nr"] for f in self.flaechen], default=0)
        neu, doppelt = 0, 0
        for f in andere.flaechen:
            k = schluessel(f)
            if k in vorhanden:
                doppelt += 1
                continue
            nr += 1
            self.flaechen.append(dict(f, nr=nr))
            vorhanden.add(k)
            neu += 1
        return neu, doppelt

    def auswerten(self, index):
        """Trennschärfe und Schwellen für einen Index. Annahme: vitale Bäume haben höhere Werte."""
        from scipy.stats import mannwhitneyu
        vf = [f for f in self.flaechen if f["klasse"] == 1]
        gf = [f for f in self.flaechen if f["klasse"] == 0]
        if not vf or not gf:
            raise ValueError("Es wird mindestens je eine Referenzfläche „vital“ und „geschädigt“ benötigt.")
        v = np.concatenate([f["werte"][index] for f in vf])
        g = np.concatenate([f["werte"][index] for f in gf])
        if v.size == 0 or g.size == 0:
            raise ValueError(f"{index}: keine gültigen Werte in den Referenzflächen (Kanal fehlt?).")
        auc = float(mannwhitneyu(v, g).statistic / (v.size * g.size))   # P(vital > geschädigt)
        vs, gs = np.sort(v), np.sort(g)
        kand = np.unique(np.quantile(np.concatenate([v, g]), np.linspace(0, 1, 2001)))
        sens = np.searchsorted(gs, kand, side="left") / gs.size          # geschädigt korrekt: Wert < t
        spez = 1 - np.searchsorted(vs, kand, side="left") / vs.size      # vital korrekt: Wert >= t
        j = sens + spez - 1
        k = int(np.argmax(j))
        t_opt = float(kand[k])
        p5_vital, p95_gesch = float(np.percentile(v, 5)), float(np.percentile(g, 95))
        # Flächenebene: Median je Fläche mit der Youden-Schwelle einordnen
        richtig = sum(bool((np.median(f["werte"][index]) >= t_opt) == (f["klasse"] == 1)) for f in vf + gf)
        return {"Index": index, "Flaechen_vital": len(vf), "Flaechen_geschaedigt": len(gf),
                "Pixel_vital": int(v.size), "Pixel_geschaedigt": int(g.size),
                "Median_vital": float(np.median(v)), "Median_geschaedigt": float(np.median(g)),
                "AUC": auc, "Richtung_ok": auc >= 0.5,
                "Youden_J": float(j[k]), "Youden_Schwelle": t_opt,
                "Sensitivitaet": float(sens[k]), "Spezifitaet": float(spez[k]),
                "P5_vital": p5_vital, "P95_geschaedigt": p95_gesch,
                "Flaechen_richtig": int(richtig), "Flaechen_gesamt": len(vf) + len(gf)}

    def schwellen(self, index, schema="3", anteil_markierung=0.10, kronenabstand_px=0):
        """Schwellen aus den Referenzen. schema "3": gestresst < P5(vital), vital >= P95(geschädigt), dazwischen
        Übergang (Überlappungsbereich); ohne Überlappung bzw. schema "2": beide = Youden-Schwelle."""
        e = self.auswerten(index)
        if not e["Richtung_ok"]:
            raise ValueError(f"{index}: Geschädigte Referenzen haben höhere Werte als vitale (AUC {e['AUC']:.2f}) – "
                             "Schwellen nach dem Schema „hoher Wert = vital“ nicht sinnvoll.")
        lo, hi = e["P5_vital"], e["P95_geschaedigt"]
        if schema == "2" or lo >= hi:
            lo = hi = e["Youden_Schwelle"]
            regel = "Youden-Schwelle (2 Klassen)"
        else:
            regel = "gestresst < P5(vital), vital >= P95(geschädigt), dazwischen Überlappung"
        herkunft = (f"Referenzflächen: {e['Flaechen_vital']} vital / {e['Flaechen_geschaedigt']} geschädigt, "
                    f"AUC {e['AUC']:.3f}, Youden {e['Youden_Schwelle']:.3f}; Regel: {regel}")
        return Schwellen(round(lo, 4), round(hi, 4), anteil_markierung, kronenabstand_px, herkunft), e


REF_SPALTEN = ["Index", "Flaechen_vital", "Flaechen_geschaedigt", "Pixel_vital", "Pixel_geschaedigt", "Median_vital",
               "Median_geschaedigt", "AUC", "Youden_J", "Youden_Schwelle", "Sensitivitaet", "Spezifitaet", "P5_vital",
               "P95_geschaedigt", "Flaechen_richtig", "Flaechen_gesamt"]


def referenzen_als_csv(ergebnisse, pfad):
    with open(pfad, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(REF_SPALTEN)
        for e in ergebnisse:
            wr.writerow([e[k] if isinstance(e[k], (int, str)) else f"{e[k]:.4f}" for k in REF_SPALTEN])


# -----------------------------------------------------------------------------
# Prüfung von Schwellen an unabhängigen Prüfbäumen (Version 0.9)
# -----------------------------------------------------------------------------
# Die Schwellen werden aus einer Referenzsammlung abgeleitet („Ableitung“) und an einer zweiten, getrennten Sammlung
# („Prüfung“) kontrolliert. Für jede Prüffläche wird – mit derselben Maske, Kronentrennung und Baumregel wie in der
# Auswertung – der Baum (Objekt) bestimmt, der die Fläche am stärksten überdeckt, und seine Klasse mit der Sollklasse
# verglichen: Referenz „vital“ -> soll „vital“, Referenz „geschädigt“ -> soll „gestresst“. „Übergang“ wird getrennt
# gezählt (weder richtig noch falsch zugeordnet, für die Trefferquote aber nicht richtig).
PRUEF_SPALTEN = ["Index", "Pruefflaeche", "Soll", "Ordner", "Aufnahme", "Baum_Nr", "Ueberdeckung", "Klasse",
                 "Ergebnis", "Anteil_gestresst", "Anteil_Uebergang", "Anteil_vital", "Median", "Baum_Pixel"]
PRUEF_SUMME_SPALTEN = ["Index", "gestresst_unter", "vital_ab", "Baumregel", "Baum_gestresst_ab", "Herkunft",
                       "Vital_n", "Vital_richtig", "Vital_Uebergang", "Vital_falsch",
                       "Geschaedigt_n", "Geschaedigt_richtig", "Geschaedigt_Uebergang", "Geschaedigt_falsch",
                       "Kein_Baum", "Trefferquote", "Ausgewogene_Trefferquote"]


def _polygon_bbox_maske(xy, x0, y0, w, h):
    m = np.zeros((h, w), np.uint8)
    pts = np.round(np.asarray(xy, float) - [x0, y0]).astype(np.int32)
    cv2.fillPoly(m, [pts], 1)
    return m.astype(bool)


def referenz_ueberschneidungen(ableitung, pruefung):
    """Prüfflächen, die sich mit einer Ableitungsfläche im selben Bild überschneiden: [(Nr Prüfung, Nr Ableitung)].
    (Derselbe Baum in einem anderen, überlappenden Bild wird hiermit nicht erkannt.)"""
    treffer = []
    for p in pruefung.flaechen:
        for a in ableitung.flaechen:
            if a["aufnahme"] != p["aufnahme"] or bool(a.get("geschaerft")) != bool(p.get("geschaerft")) or \
                    os.path.normcase(os.path.normpath(a["ordner"])) != os.path.normcase(os.path.normpath(p["ordner"])):
                continue
            alle = np.vstack([np.asarray(a["xy"], float), np.asarray(p["xy"], float)])
            x0, y0 = np.floor(alle.min(0)).astype(int)
            x1, y1 = np.ceil(alle.max(0)).astype(int) + 1
            ma = _polygon_bbox_maske(a["xy"], x0, y0, x1 - x0, y1 - y0)
            mp = _polygon_bbox_maske(p["xy"], x0, y0, x1 - x0, y1 - y0)
            if (ma & mp).any():
                treffer.append((p["nr"], a["nr"]))
    return treffer


# -----------------------------------------------------------------------------
# Referenzbäume über Bilder und Sets hinweg abgleichen (Version 0.20)
# -----------------------------------------------------------------------------
# Derselbe Baum kann in mehreren, sich überlappenden Aufnahmen und in mehreren Flügen über dieselbe Fläche
# (z. B. 0026SET und 0028SET) vorkommen. Ableitungs- und Prüfbäume dürfen nicht derselbe Baum sein.
# Verfahren: Nur Aufnahmen, deren GPS-Mittelpunkte näher als DOPPEL_MAX_ABSTAND_M liegen, können dieselben Bäume
# zeigen. Für solche Paare werden SIFT-Merkmale im Grün-, ersatzweise im NIR-Kanal (ab 0.20.1) (gleiches Pixelraster wie die gezeichneten Umrisse)
# zugeordnet und eine Homographie mit RANSAC geschätzt; damit wird ein Umriss in die andere Aufnahme übertragen.
# Überdeckt er dort einen Umriss zu mindestens DOPPEL_MIN_UEBERDECKUNG (bezogen auf die kleinere Fläche) oder liegt
# sein Mittelpunkt darin, gilt er als derselbe Baum. Paare mit zu wenig Übereinstimmungen werden gemeldet.
DOPPEL_MAX_ABSTAND_M = 16.0
DOPPEL_MIN_INLIER = 25
DOPPEL_MIN_UEBERDECKUNG = 0.3      # ab hier „fraglich“ (Nachbarbaum möglich) – selbst vergleichen
DOPPEL_SICHER = 0.5                # ab hier „sicher derselbe Baum“ (ab 0.20.1; Kronenspitzen verschieben sich
                                   # zwischen zwei Blickwinkeln, Bäume ≈ 2 m hoch bei 12 m Flughöhe)
_GPS_CACHE, _SIFT_CACHE, _H_CACHE = {}, {}, {}


def _bild_schluessel(ordner, name, geschaerft=False):
    return (os.path.normcase(os.path.normpath(ordner)), name, bool(geschaerft))


def aufnahme_gps(ordner, name):
    """(Breite, Länge) der Aufnahme aus den Metadaten des ersten Spektralkanals; None, wenn nicht lesbar."""
    k = _bild_schluessel(ordner, name)
    if k not in _GPS_CACHE:
        try:
            sp, _ = _ordne_dateien(rohaufnahmen(ordner)[name])
            m = _lies_einen_kanal(next(iter(sp.values())))
            _GPS_CACHE[k] = (float(m["lat"]), float(m["lon"]))
        except Exception:
            _GPS_CACHE[k] = None
    return _GPS_CACHE[k]


def gps_abstand_m(a, b):
    if a is None or b is None:
        return float("inf")
    dy = (a[0] - b[0]) * 110540.0
    dx = (a[1] - b[1]) * 111320.0 * np.cos(np.radians(a[0]))
    return float(np.hypot(dx, dy))


DOPPEL_KANAELE = ("Green", "NIR")      # ab 0.20.1: Grün zuerst (schärfere Schatten/Kronenstruktur), NIR als Ersatz


def _sift_merkmale(ordner, name, geschaerft=False, nur_kronen=False, aufn=None):
    """SIFT-Merkmale je Kanal in DOPPEL_KANAELE (zwischengespeichert): {'form': (h, w), Kanal: (Punkte, Deskriptoren)}.
    `aufn` vermeidet erneutes Laden der angezeigten Aufnahme."""
    k = _bild_schluessel(ordner, name, geschaerft)
    if k not in _SIFT_CACHE:
        if aufn is None:
            aufn = lade_aufnahme(ordner, name, fortschritt=lambda t: None, schaerfen=geschaerft, nur_kronen=nur_kronen)
        erg = {"form": tuple(aufn.stapel.shape[1:])}
        for kanal in DOPPEL_KANAELE:
            if kanal not in aufn.kanalindex:
                continue
            b = np.nan_to_num(aufn.stapel[aufn.kanalindex[kanal]].astype(np.float32))
            lo, hi = np.percentile(b, (1, 99))
            b8 = np.clip((b - lo) / max(float(hi - lo), 1e-6) * 255, 0, 255).astype(np.uint8)
            kp, des = cv2.SIFT_create(nfeatures=6000).detectAndCompute(b8, None)
            erg[kanal] = (np.float32([q.pt for q in kp]) if kp else np.zeros((0, 2), np.float32), des)
        if len(_SIFT_CACHE) > 80:
            _SIFT_CACHE.pop(next(iter(_SIFT_CACHE)))
        _SIFT_CACHE[k] = erg
    return _SIFT_CACHE[k]


def _homographie_plausibel(H):
    """Gleiche Flughöhe: nahezu Drehung + Verschiebung (Maßstab 0,75–1,33, kaum Perspektive)."""
    if H is None or abs(H[2, 2]) < 1e-9:
        return False
    Hn = H / H[2, 2]
    s = np.linalg.svd(Hn[:2, :2], compute_uv=False)
    return bool(0.75 < s.min() and s.max() < 1.33 and abs(Hn[2, 0]) < 5e-4 and abs(Hn[2, 1]) < 5e-4)


def _homographie(qa, qb):
    """Homographie von Bild a nach Bild b aus zwischengespeicherten Merkmalen: (H oder None, Zahl Übereinstimmungen).
    Versucht nacheinander die Kanäle in DOPPEL_KANAELE; nur plausible Homographien zählen."""
    k = (qa[0], qb[0])
    if k in _H_CACHE:
        return _H_CACHE[k]
    erg = (None, 0)
    for kanal in DOPPEL_KANAELE:
        if kanal not in qa[1] or kanal not in qb[1]:
            continue
        (pa, da), (pb, db) = qa[1][kanal], qb[1][kanal]
        if da is None or db is None or len(pa) < 10 or len(pb) < 10:
            continue
        paare = cv2.BFMatcher().knnMatch(da, db, k=2)
        gut = [m for m, n in (x for x in paare if len(x) == 2) if m.distance < 0.75 * n.distance]
        n = len(gut)
        H = None
        if n >= DOPPEL_MIN_INLIER:
            H, maske = cv2.findHomography(pa[[m.queryIdx for m in gut]], pb[[m.trainIdx for m in gut]],
                                          cv2.RANSAC, 5.0)
            n = int(maske.sum()) if maske is not None else 0
            if n < DOPPEL_MIN_INLIER or not _homographie_plausibel(H):
                H = None
        if H is not None:
            erg = (H, n)
            break
        erg = (None, max(erg[1], n))
    _H_CACHE[k] = erg
    return erg


def flaechen_uebertragen(flaechen, ziel_ordner, ziel_name, ziel_geschaerft=False, ziel_aufn=None,
                         abbrechen=lambda: False):
    """Überträgt Referenzflächen anderer (naher) Aufnahmen in das Pixelraster der Zielaufnahme.
    Flächen der Zielaufnahme selbst werden unverändert übernommen.
    Rückgabe: (Liste {flaeche, xy, quelle}, Liste nahe Aufnahmen ohne Abgleich [(ordner, name, Übereinstimmungen)])."""
    zk = _bild_schluessel(ziel_ordner, ziel_name, ziel_geschaerft)
    zgps = aufnahme_gps(ziel_ordner, ziel_name)
    nach_bild = {}
    for f in flaechen:
        nach_bild.setdefault(_bild_schluessel(f["ordner"], f["aufnahme"], f.get("geschaerft")), []).append(f)
    aus, ohne = [], []
    zq = None
    for bk, fl in nach_bild.items():
        if abbrechen():
            break
        if bk == zk:
            aus += [{"flaeche": f, "xy": np.asarray(f["xy"], float), "quelle": "dieses Bild"} for f in fl]
            continue
        if bk[2] != zk[2] or gps_abstand_m(zgps, aufnahme_gps(fl[0]["ordner"], fl[0]["aufnahme"])) >= DOPPEL_MAX_ABSTAND_M:
            continue
        if zq is None:
            zq = (zk, _sift_merkmale(ziel_ordner, ziel_name, ziel_geschaerft, aufn=ziel_aufn))
        try:
            q = (bk, _sift_merkmale(fl[0]["ordner"], fl[0]["aufnahme"], bk[2],
                                    bool(fl[0].get("panchro_nur_kronen", False))))
        except Exception:
            ohne.append((fl[0]["ordner"], fl[0]["aufnahme"], 0))
            continue
        H, n = _homographie(q, zq)
        if H is None:
            ohne.append((fl[0]["ordner"], fl[0]["aufnahme"], n))
            continue
        quelle = f"{_set_name(fl[0]['ordner'])} {fl[0]['aufnahme']}"
        h_z, w_z = zq[1]["form"]
        for f in fl:
            xy = cv2.perspectiveTransform(np.asarray(f["xy"], np.float32).reshape(-1, 1, 2), H).reshape(-1, 2)
            m = xy.mean(0)
            if not (0 <= m[0] < w_z and 0 <= m[1] < h_z):
                continue                            # Baum liegt außerhalb der Zielaufnahme
            aus.append({"flaeche": f, "xy": xy.astype(float), "quelle": quelle})
    return aus, ohne


def umrisse_gleicher_baum(xy_a, xy_b):
    """Überdeckung (Anteil der kleineren Fläche) zweier Umrisse im selben Raster und Einstufung:
    'sicher' (>= DOPPEL_SICHER), 'fraglich' (>= DOPPEL_MIN_UEBERDECKUNG oder Mittelpunkt im Umriss) oder None."""
    a, b = np.asarray(xy_a, float), np.asarray(xy_b, float)
    alle = np.vstack([a, b])
    x0, y0 = np.floor(alle.min(0)).astype(int)
    x1, y1 = np.ceil(alle.max(0)).astype(int) + 1
    if (x1 - x0) * (y1 - y0) > 4e7:
        return 0.0, None
    ma = _polygon_bbox_maske(a, x0, y0, x1 - x0, y1 - y0)
    mb = _polygon_bbox_maske(b, x0, y0, x1 - x0, y1 - y0)
    u = float((ma & mb).sum()) / max(1, min(int(ma.sum()), int(mb.sum())))
    if u >= DOPPEL_SICHER:
        return u, "sicher"
    mitte = a.mean(0)
    drin = cv2.pointPolygonTest(b.astype(np.float32).reshape(-1, 1, 2), (float(mitte[0]), float(mitte[1])), False) >= 0
    return u, ("fraglich" if (u >= DOPPEL_MIN_UEBERDECKUNG or drin) else None)


def _gleiche_flaeche(f, g):
    """Exakt dieselbe gespeicherte Fläche (z. B. dieselbe Datei als Ableitung und Prüfung geladen)."""
    a, b = np.asarray(f["xy"], float), np.asarray(g["xy"], float)
    return (_bild_schluessel(f["ordner"], f["aufnahme"], f.get("geschaerft"))
            == _bild_schluessel(g["ordner"], g["aufnahme"], g.get("geschaerft"))
            and f["klasse"] == g["klasse"] and a.shape == b.shape and np.allclose(a, b))


def referenz_dopplungen(ableitung, pruefung, fortschritt=print, abbrechen=lambda: False):
    """Findet Prüfbäume, die derselbe Baum wie ein Ableitungsbaum sind (auch in anderen Aufnahmen/Sets), und
    Prüfbäume, die mehrfach eingezeichnet sind. Identische Flächen (gleiche Datei zweimal) werden übergangen.
    Jedes Paar wird aus beiden Richtungen geprüft; es zählt die höhere Überdeckung.
    Rückgabe: {'ableitung': [{pruef, abl, ueberdeckung, wo}] (sicher), 'innerhalb': [{a, b, ueberdeckung, wo}] (sicher),
               'fraglich': [{a, b, art, ueberdeckung, wo}] (selbst vergleichen),
               'ohne_abgleich': [(Prüfaufnahme, nahe Aufnahme, Übereinstimmungen)]}."""
    abl = [f for f in (ableitung.flaechen if ableitung else [])
           if not any(_gleiche_flaeche(f, g) for g in pruefung.flaechen)]
    ids_abl = {id(f) for f in abl}
    bilder = sorted({_bild_schluessel(f["ordner"], f["aufnahme"], f.get("geschaerft")) for f in pruefung.flaechen})
    paare, ohne_abgleich = {}, []

    def merke(f, g, ueb, stufe, wo):
        k = tuple(sorted((id(f), id(g))))
        alt = paare.get(k)
        if alt is None or ueb > alt["ueberdeckung"]:
            paare[k] = {"f": f, "g": g, "ueberdeckung": ueb, "stufe": stufe, "wo": wo}

    for i, bk in enumerate(bilder):
        if abbrechen():
            break
        fl = [f for f in pruefung.flaechen if _bild_schluessel(f["ordner"], f["aufnahme"], f.get("geschaerft")) == bk]
        fortschritt((i, len(bilder), f"{_set_name(fl[0]['ordner'])} {fl[0]['aufnahme']}"))
        andere_pruef = [g for g in pruefung.flaechen if not any(g is x for x in fl)]
        uebertragen, ohne = flaechen_uebertragen(abl + andere_pruef, fl[0]["ordner"], fl[0]["aufnahme"], bk[2],
                                                 abbrechen=abbrechen)
        ohne_abgleich += [(f"{_set_name(fl[0]['ordner'])} {fl[0]['aufnahme']}", f"{_set_name(o)} {n}", m)
                          for o, n, m in ohne]
        for f in fl:
            for u in uebertragen:
                ueb, stufe = umrisse_gleicher_baum(f["xy"], u["xy"])
                if stufe:
                    merke(f, u["flaeche"], ueb, stufe, u["quelle"])
            for g in fl:
                if g is not f:
                    ueb, stufe = umrisse_gleicher_baum(f["xy"], g["xy"])
                    if stufe:
                        merke(f, g, ueb, stufe, "dieses Bild")
    erg = {"ableitung": [], "innerhalb": [], "fraglich": [], "ohne_abgleich": ohne_abgleich}
    for d in paare.values():
        f, g = d["f"], d["g"]
        if id(f) in ids_abl:
            f, g = g, f                                  # f = Prüfbaum, g = ggf. Ableitungsbaum
        art = "ableitung" if id(g) in ids_abl else "innerhalb"
        if d["stufe"] == "sicher":
            if art == "ableitung":
                erg["ableitung"].append({"pruef": f, "abl": g, "ueberdeckung": d["ueberdeckung"], "wo": d["wo"]})
            else:
                erg["innerhalb"].append({"a": f, "b": g, "ueberdeckung": d["ueberdeckung"], "wo": d["wo"]})
        else:
            erg["fraglich"].append({"a": f, "b": g, "art": art, "ueberdeckung": d["ueberdeckung"], "wo": d["wo"]})
    fortschritt((len(bilder), len(bilder), "fertig"))
    return erg


def dopplungen_text(erg, max_zeilen=12):
    """Kurzbeschreibung für Meldungen."""
    def nm(f):
        return f"{'V' if f['klasse'] else 'G'}{f['nr']} ({_set_name(f['ordner'])} {f['aufnahme']})"
    z = [f"Prüfbaum {nm(d['pruef'])} = Ableitungsbaum {nm(d['abl'])} ({d['ueberdeckung']:.0%})" for d in erg["ableitung"]]
    z += [f"Prüfbaum {nm(d['a'])} = Prüfbaum {nm(d['b'])} ({d['ueberdeckung']:.0%}, doppelt eingezeichnet)"
          for d in erg["innerhalb"]]
    text = "\n".join(z[:max_zeilen]) + (f"\n… und {len(z) - max_zeilen} weitere" if len(z) > max_zeilen else "")
    fr = erg.get("fraglich", [])
    if fr:
        text += ("\n\nFraglich (Überdeckung " + f"{DOPPEL_MIN_UEBERDECKUNG:.0%}–{DOPPEL_SICHER:.0%}, evtl. Nachbarbaum – "
                 "selbst vergleichen, wird nicht ausgeschlossen):\n"
                 + "\n".join(f"{nm(d['a'])} ↔ {nm(d['b'])} ({d['ueberdeckung']:.0%})" for d in fr[:8])
                 + (f"\n… und {len(fr) - 8} weitere" if len(fr) > 8 else ""))
    return text.strip()


def dopplungen_protokoll(erg):
    def kurz(f):
        return {"nr": f["nr"], "klasse": REF_KLASSEN[f["klasse"]], "set": _set_name(f["ordner"]), "aufnahme": f["aufnahme"]}
    return {"verfahren": (f"GPS < {DOPPEL_MAX_ABSTAND_M} m, SIFT ({'/'.join(DOPPEL_KANAELE)}) + Homographie (RANSAC, "
                          f">= {DOPPEL_MIN_INLIER} Punkte, plausibel), sicher ab Überdeckung {DOPPEL_SICHER}, "
                          f"fraglich ab {DOPPEL_MIN_UEBERDECKUNG} oder Mittelpunkt im Umriss"),
            "pruef_gleich_ableitung": [{"pruef": kurz(d["pruef"]), "ableitung": kurz(d["abl"]),
                                        "ueberdeckung": round(d["ueberdeckung"], 2)} for d in erg["ableitung"]],
            "pruef_doppelt": [{"a": kurz(d["a"]), "b": kurz(d["b"]), "ueberdeckung": round(d["ueberdeckung"], 2)}
                              for d in erg["innerhalb"]],
            "fraglich": [{"a": kurz(d["a"]), "b": kurz(d["b"]), "art": d["art"], "ueberdeckung": round(d["ueberdeckung"], 2)}
                         for d in erg.get("fraglich", [])],
            "nahe_aufnahmen_ohne_abgleich": erg["ohne_abgleich"]}


def pruefe_schwellen(pruefung, vorgabe, schwellen, fortschritt=print, abbrechen=lambda: False):
    """Prüft Schwellen {Index: Schwellen} an den Prüfflächen. Jede Aufnahme wird einmal geladen.
    Rückgabe: (Zeilen je Prüffläche und Index, Zusammenfassung je Index, Fehler [(Aufnahme, Meldung)])."""
    if vorgabe is None:
        raise ValueError("Für die Prüfung je Baum wird eine Maske benötigt (am besten „Bäume (Modell)“).")
    if not schwellen:
        raise ValueError("Es sind keine Schwellwerte eingeschaltet.")
    bilder = {}
    for f in pruefung.flaechen:
        bilder.setdefault((f["ordner"], f["aufnahme"], bool(f.get("geschaerft"))), []).append(f)
    zeilen, fehler = [], []
    for k, ((ordner, name, geschaerft), flaechen) in enumerate(sorted(bilder.items()), 1):
        if abbrechen():
            fehler.append(("—", "abgebrochen durch Nutzer"))
            break
        fortschritt((k - 1, len(bilder), os.path.join(os.path.basename(ordner), name)))
        try:
            a = lade_aufnahme(ordner, name, fortschritt=lambda t: None, schaerfen=geschaerft,   # Raster der Fläche
                              nur_kronen=bool(flaechen[0].get("panchro_nur_kronen", False)))
            if geschaerft and not a.geschaerft:
                raise ValueError("Fläche stammt aus der geschärften Aufnahme, Panchro ist aber nicht (mehr) vorhanden.")
            maske = vorgabe.berechne(a)
        except Exception as e:
            fehler.append((os.path.join(ordner, name), str(e).splitlines()[0]))
            continue
        nir = a.kronenstapel[a.kanalindex["NIR"]]
        for idx, schw in schwellen.items():
            w = berechne_index(a.stapel, a.kanalindex, idx)
            kl = klassifiziere(w, schw)
            lab, obj = bewerte_objekte(w, kl, maske, schw, nir, kronenkorrekturen_fuer(a))
            nach_label = {o["label"]: o for o in obj}
            for f in flaechen:
                poly = polygon_maske(maske.shape, f["xy"])
                ids, cnt = np.unique(lab[poly & (lab > 0)], return_counts=True)
                kandidaten = [(c, i) for i, c in zip(ids, cnt) if i in nach_label]
                soll = KLASSE_VITAL if f["klasse"] == 1 else KLASSE_GESTRESST
                z = {"Index": idx, "Pruefflaeche": f["nr"], "Soll": KLASSENNAMEN[soll], "Ordner": ordner,
                     "Aufnahme": name, "Panchro_geschaerft": geschaerft}
                if not kandidaten:
                    z.update(Baum_Nr="", Ueberdeckung=0.0, Klasse="kein Baum", Ergebnis="kein Baum")
                else:
                    c, i = max(kandidaten)
                    o = nach_label[i]
                    ist = o["klasse"]
                    z.update(Baum_Nr=o["nr"], Ueberdeckung=float(c / max(poly.sum(), 1)),
                             Klasse=KLASSENNAMEN.get(ist, "?"),
                             Ergebnis=("richtig" if ist == soll else "Übergang" if ist == KLASSE_UEBERGANG else "falsch"),
                             Anteil_gestresst=o["anteil_gestresst"], Anteil_Uebergang=o["anteil_uebergang"],
                             Anteil_vital=o["anteil_vital"], Median=o["median"], Baum_Pixel=o["pixel"])
                zeilen.append(z)
    fortschritt((len(bilder), len(bilder), "fertig"))
    summe = []
    for idx, schw in schwellen.items():
        zi = [z for z in zeilen if z["Index"] == idx]
        s = {"Index": idx, "gestresst_unter": schw.gestresst, "vital_ab": schw.vital,
             "Baumregel": BAUMREGELN.get(schw.baumregel, schw.baumregel),
             "Baum_gestresst_ab": schw.anteil_markierung, "Herkunft": schw.herkunft}
        for soll, pre in (("vital", "Vital"), ("gestresst", "Geschaedigt")):
            zs = [z for z in zi if z["Soll"] == soll]
            s[f"{pre}_n"] = len(zs)
            for erg, suf in (("richtig", "richtig"), ("Übergang", "Uebergang"), ("falsch", "falsch")):
                s[f"{pre}_{suf}"] = sum(z["Ergebnis"] == erg for z in zs)
        s["Kein_Baum"] = sum(z["Ergebnis"] == "kein Baum" for z in zi)
        n = len(zi)
        s["Trefferquote"] = (s["Vital_richtig"] + s["Geschaedigt_richtig"]) / n if n else float("nan")
        quoten = [s[f"{p}_richtig"] / s[f"{p}_n"] for p in ("Vital", "Geschaedigt") if s[f"{p}_n"]]
        s["Ausgewogene_Trefferquote"] = float(np.mean(quoten)) if len(quoten) == 2 else float("nan")
        summe.append(s)
    return zeilen, summe, fehler


def pruefung_als_csv(zeilen, summe, pfad, protokoll=None):
    """Schreibt <pfad> (Ergebnis je Prüffläche) und <pfad>_Zusammenfassung.csv; optional Parameterprotokoll (JSON)."""
    def zelle(v):
        return f"{v:.4f}" if isinstance(v, float) else ("" if v is None else v)
    with open(pfad, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(PRUEF_SPALTEN)
        for z in zeilen:
            wr.writerow([zelle(z.get(k)) for k in PRUEF_SPALTEN])
    basis = os.path.splitext(pfad)[0]
    with open(basis + "_Zusammenfassung.csv", "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(PRUEF_SUMME_SPALTEN)
        for s in summe:
            wr.writerow([zelle(s.get(k)) for k in PRUEF_SUMME_SPALTEN])
    if protokoll is not None:
        with open(basis + "_Parameter.json", "w", encoding="utf-8") as f:
            json.dump(protokoll, f, indent=2, ensure_ascii=False, default=str)



# -----------------------------------------------------------------------------
# Kanalanalyse an Referenzbäumen (Version 0.12, Anmerkungen Max 06.11.2026)
# -----------------------------------------------------------------------------
# 1) Trennung je Kanal und Index: Welche Merkmale unterscheiden sich stark ZWISCHEN den Bäumen bei wenig Streuung
#    INNERHALB eines Baums? Einfaktorielle Varianzanalyse mit dem Baum als Faktor:
#       F = MS_zwischen / MS_innerhalb,  ICC(1) = (MSB - MSW) / (MSB + (n0 - 1) * MSW)
#    ICC = Anteil der Gesamtvarianz, der auf Unterschiede zwischen den Bäumen entfällt (0 bis 1).
#    Zusätzlich vital gegen geschädigt auf Baumebene (Mittelwert je Baum): Cohens d, AUC und der
#    Klassenabstand in Einheiten der Streuung innerhalb der Bäume.
#    (Welch-Test und Holm-Korrektur bis 0.20.2, in 0.20.3 entfernt, da in der Bachelorarbeit nicht verwendet;
#    alter Stand: Sicherungen/Software/vi_kern_vor0203.py)
# 2) Welche Kanäle zeigen dasselbe? Korrelationsmatrix der Kanäle (Pixel- und Baumebene), PCA auf den
#    standardisierten Kanälen und Vergleich der Kanalsätze RGB / RGB+NIR / alle 5: Wie gut lassen sich die
#    weggelassenen Kanäle linear aus den übrigen vorhersagen (R²), und wie gut trennen die Kanalsätze vital und
#    geschädigt (lineare Diskriminanzanalyse mit Leave-one-tree-out, k-means mit k = 2 auf den Baummitteln).
# Jeder Baum geht mit gleich vielen Pixeln ein (Stichprobe), damit große Kronen nicht überwiegen.
# Hinweis: Benachbarte Pixel sind nicht unabhängig. F-Werte auf Pixelebene sind deshalb nur relativ (zum Vergleich
# der Merkmale) zu lesen; Cohens d und AUC arbeiten auf Baumebene.
ANALYSE_PIXEL_JE_BAUM = 2000
KANALSAETZE = {"RGB": ["Blue", "Green", "Red"],
               "RGB+NIR": ["Blue", "Green", "Red", "NIR"],
               "ohne Blau": ["Green", "Red", "Red edge", "NIR"],     # Kanäle wie DJI Mavic 3M (Näherung)
               "alle 5": ["Blue", "Green", "Red", "Red edge", "NIR"]}
KANAL_ANZEIGE = {"Blue": "Blau", "Green": "Grün", "Red": "Rot", "Red edge": "Red Edge", "NIR": "NIR"}


def ergaenze_kanalwerte(ref, vorgabe=None, fortschritt=print, abbrechen=lambda: False, alle=False):
    """Ergänzt für Referenzflächen ohne Kanalwerte (Dateien vor Version 0.12) die Reflektanz je Kanal.
    Die Aufnahme wird neu geladen; Pixel = Umriss geschnitten mit der Maske der Vorgabe (wie beim Einzeichnen,
    falls dort eine Maske aktiv war). Rückgabe: (Zahl ergänzt, Fehler [(Aufnahme, Meldung)])."""
    offen = [f for f in ref.flaechen if alle or "kanaele" not in f]
    bilder = {}
    for f in offen:
        bilder.setdefault((f["ordner"], f["aufnahme"], bool(f.get("geschaerft"))), []).append(f)
    n, fehler = 0, []
    for k, ((ordner, name, geschaerft), flaechen) in enumerate(sorted(bilder.items()), 1):
        if abbrechen():
            fehler.append(("-", "abgebrochen durch Nutzer"))
            break
        fortschritt((k - 1, len(bilder), os.path.join(os.path.basename(ordner), name)))
        try:
            a = lade_aufnahme(ordner, name, fortschritt=lambda t: None, schaerfen=geschaerft,
                              nur_kronen=bool(flaechen[0].get("panchro_nur_kronen", False)))
            brauche_maske = any(f.get("maske", "keine") != "keine" for f in flaechen)
            maske = vorgabe.berechne(a) if (vorgabe is not None and brauche_maske) else None
        except Exception as e:
            fehler.append((os.path.join(ordner, name), str(e).splitlines()[0]))
            continue
        form = a.stapel.shape[1:]
        for f in flaechen:
            poly = polygon_maske(form, f["xy"])
            if maske is not None and f.get("maske", "keine") != "keine":
                poly &= maske
            ys, xs = np.nonzero(poly)
            if ys.size == 0:
                fehler.append((os.path.join(ordner, name), f"Fläche {f['nr']}: keine Pixel in der Maske"))
                continue
            rng = np.random.default_rng(int(f["nr"]))
            if ys.size > REF_MAX_PIXEL:
                wahl = rng.choice(ys.size, REF_MAX_PIXEL, replace=False)
                ys, xs = ys[wahl], xs[wahl]
            f["kanaele"] = {kn: a.stapel[a.kanalindex[kn]][ys, xs].astype(np.float32)
                            for kn in KANALNAMEN if kn in a.kanalindex}
            f["kanaele_herkunft"] = ("nachträglich aus der Aufnahme, Maske: "
                                     + (vorgabe.beschreibung() if maske is not None else "keine"))
            n += 1
    fortschritt((len(bilder), len(bilder), "fertig"))
    return n, fehler


def _baumdaten(flaechen, merkmale, n_je_baum=ANALYSE_PIXEL_JE_BAUM):
    """{Merkmal: [Array je Baum]} aus den Kanalwerten; Indizes werden aus denselben Pixeln berechnet.
    Je Baum dieselben Pixel für alle Merkmale (gemeinsam gültig), damit Kanäle und Indizes vergleichbar sind."""
    daten = {m: [] for m in merkmale}
    for f in flaechen:
        kan = f["kanaele"]
        n = min(len(v) for v in kan.values())
        idx = np.random.default_rng(int(f["nr"])).permutation(n)
        stapel = np.stack([kan[k][idx] for k in kan]).astype(np.float64)
        kidx = {k: i for i, k in enumerate(kan)}
        werte = {}
        ok = np.all(stapel >= MIN_REFLEKTANZ, axis=0)
        for m in merkmale:
            w = stapel[kidx[m]] if m in kidx else berechne_index(stapel, kidx, m).astype(np.float64)
            werte[m] = w
            ok &= np.isfinite(w)
        auswahl = np.nonzero(ok)[0][:n_je_baum]
        for m in merkmale:
            daten[m].append(werte[m][auswahl])
    return daten


def _trennung(werte_je_baum, klassen):
    paare = [(w, c) for w, c in zip(werte_je_baum, klassen) if w.size > 1]
    if len(paare) < 2:
        return None
    gruppen = [w for w, _ in paare]
    kl = np.array([c for _, c in paare])
    k = len(gruppen)
    n_i = np.array([g.size for g in gruppen], float)
    m_i = np.array([g.mean() for g in gruppen])
    N = n_i.sum()
    M = float((n_i * m_i).sum() / N)
    ssb = float((n_i * (m_i - M) ** 2).sum())
    ssw = float(sum(((g - g.mean()) ** 2).sum() for g in gruppen))
    msb, msw = ssb / (k - 1), ssw / (N - k)
    n0 = (N - (n_i ** 2).sum() / N) / (k - 1)
    nenner = msb + (n0 - 1) * msw
    icc = (msb - msw) / nenner if nenner > 0 else float("nan")
    s_innen = float(np.sqrt(msw))
    e = {"Baeume": k, "Pixel_je_Baum": int(np.median(n_i)), "Mittel": M,
         "Std_zwischen_Baeumen": float(m_i.std(ddof=1)), "Std_innerhalb_Baum": s_innen,
         "Verhaeltnis_zwischen_innen": float(m_i.std(ddof=1) / s_innen) if s_innen > 0 else float("nan"),
         "F": msb / msw if msw > 0 else float("nan"), "ICC": float(icc)}
    mv, mg = m_i[kl == 1], m_i[kl == 0]
    if mv.size >= 2 and mg.size >= 2:
        sp = np.sqrt(((mv.size - 1) * mv.var(ddof=1) + (mg.size - 1) * mg.var(ddof=1)) / (mv.size + mg.size - 2))
        diff = mv.mean() - mg.mean()
        auc = float(((mv[:, None] > mg[None, :]).sum() + 0.5 * (mv[:, None] == mg[None, :]).sum())
                    / (mv.size * mg.size))
        e.update({"Baeume_vital": int(mv.size), "Baeume_geschaedigt": int(mg.size),
                  "Mittel_vital": float(mv.mean()), "Mittel_geschaedigt": float(mg.mean()),
                  "Cohen_d_Baum": float(diff / sp) if sp > 0 else float("nan"),
                  "AUC_Baum": auc,
                  "Abstand_in_Std_innen": float(abs(diff) / s_innen) if s_innen > 0 else float("nan")})
    return e


def _r2_vorhersage(X, ziel, aus):
    """R² der linearen Vorhersage der Spalte `ziel` aus den Spalten `aus` (mit Achsenabschnitt)."""
    A = np.column_stack([np.ones(len(X))] + [X[:, j] for j in aus])
    y = X[:, ziel]
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    rest = y - A @ coef
    sst = ((y - y.mean()) ** 2).sum()
    return float(1 - (rest ** 2).sum() / sst) if sst > 0 else float("nan")


def _pca(X):
    """PCA auf standardisierten Spalten: (Eigenwerte absteigend, Ladungen [Komponente x Variable])."""
    C = np.corrcoef(X, rowvar=False)
    ew, ev = np.linalg.eigh(C)
    o = np.argsort(ew)[::-1]
    ew, ev = ew[o], ev[:, o]
    ev = ev * np.sign(ev[np.abs(ev).argmax(0), range(ev.shape[1])])     # Vorzeichen: größte Ladung positiv
    return ew, (ev * np.sqrt(np.clip(ew, 0, None))).T


def _set_name(ordner):
    teile = os.path.normpath(ordner).split(os.sep)
    s = [t for t in teile if t.upper().endswith("SET")]
    return s[-1] if s else os.path.basename(ordner)


def kanalanalyse(ref, je_set=True):
    """Kanalanalyse an den Referenzbäumen (alle Flächen benötigen Kanalwerte, s. ergaenze_kanalwerte).
    Rückgabe: dict mit 'trennung', 'korrelation', 'pca', 'kanalsaetze' (Listen von Zeilen) und 'info'."""
    from sklearn.cluster import KMeans
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    fl = [f for f in ref.flaechen if "kanaele" in f]
    if not fl or len(fl) < len(ref.flaechen):
        raise ValueError(f"{len(ref.flaechen) - len(fl)} Referenzfläche(n) ohne Kanalwerte - zuerst ergänzen.")
    kanaele = [k for k in KANALNAMEN if all(k in f["kanaele"] for f in fl)]
    indizes = [i for i in INDIZES if all(c in kanaele for c in INDIZES[i]["kanaele"])]
    gruppen = {"alle": fl}
    if je_set:
        sets = sorted({os.path.normpath(f["ordner"]) for f in fl})
        if len(sets) > 1:
            for s in sets:
                gruppen[_set_name(s)] = [f for f in fl if os.path.normpath(f["ordner"]) == s]
    erg = {"trennung": [], "korrelation": [], "pca": [], "kanalsaetze": [],
           "info": {"version": VERSION, "pixel_je_baum": ANALYSE_PIXEL_JE_BAUM, "kanaele": kanaele,
                    "indizes": indizes, "kanalsaetze": KANALSAETZE,
                    "flaechen": [{"nr": f["nr"], "klasse": REF_KLASSEN[f["klasse"]], "ordner": f["ordner"],
                                  "aufnahme": f["aufnahme"], "kanaele_herkunft": f.get("kanaele_herkunft", "")}
                                 for f in fl]}}
    for gname, gfl in gruppen.items():
        klassen = [f["klasse"] for f in gfl]
        daten = _baumdaten(gfl, kanaele + indizes)
        zeilen = []
        for m in kanaele + indizes:
            e = _trennung(daten[m], klassen)
            if e:
                zeilen.append({"Gruppe": gname, "Merkmal": KANAL_ANZEIGE.get(m, m),
                               "Art": "Kanal" if m in kanaele else "Index"} | e)
        erg["trennung"].extend(zeilen)
        # Kanalmatrix: Pixel (gleich viele je Baum) und Mittelwert je Baum
        n_min = min(len(w) for w in daten[kanaele[0]])
        Xp = np.column_stack([np.concatenate([w[:n_min] for w in daten[k]]) for k in kanaele])
        Xb = np.column_stack([[w.mean() for w in daten[k]] for k in kanaele])
        baum_id = np.repeat(np.arange(len(gfl)), n_min)
        y_b = np.array(klassen)
        for ebene, X in (("Pixel", Xp), ("Baum", Xb)):
            if len(X) <= len(kanaele):
                continue
            R = np.corrcoef(X, rowvar=False)
            for i, a in enumerate(kanaele):
                erg["korrelation"].append({"Gruppe": gname, "Ebene": ebene, "Kanal": KANAL_ANZEIGE[a]}
                                          | {KANAL_ANZEIGE[b]: float(R[i, j]) for j, b in enumerate(kanaele)})
            ew, lad = _pca(X)
            for c, (w, l) in enumerate(zip(ew, lad), 1):
                erg["pca"].append({"Gruppe": gname, "Ebene": ebene, "Komponente": f"PC{c}", "Eigenwert": float(w),
                                   "Anteil": float(w / ew.sum()), "Anteil_kumuliert": float(ew[:c].sum() / ew.sum())}
                                  | {KANAL_ANZEIGE[b]: float(l[j]) for j, b in enumerate(kanaele)})
        for sname, satz in KANALSAETZE.items():
            if not all(k in kanaele for k in satz):
                continue
            spalten = [kanaele.index(k) for k in satz]
            z = {"Gruppe": gname, "Kanalsatz": sname, "Kanaele": ", ".join(KANAL_ANZEIGE[k] for k in satz)}
            for ebene, X in (("Pixel", Xp), ("Baum", Xb)):
                r2 = {}
                for j, k in enumerate(kanaele):
                    if j in spalten:
                        r2[k] = 1.0
                    else:
                        r2[k] = _r2_vorhersage(X, j, spalten) if len(X) > len(spalten) + 1 else float("nan")
                z[f"Erklaerte_Varianz_{ebene}"] = float(np.nanmean(list(r2.values())))
                for k in kanaele:
                    if k not in satz:
                        z[f"R2_{KANAL_ANZEIGE[k]}_{ebene}"] = r2[k]
            if (y_b == 1).sum() >= 2 and (y_b == 0).sum() >= 2:
                richtig = 0
                for t in range(len(gfl)):                    # Leave-one-tree-out, Mehrheitsentscheid je Baum
                    lern = baum_id != t
                    lda = LinearDiscriminantAnalysis().fit(Xp[lern][:, spalten], y_b[baum_id[lern]])
                    p = lda.predict(Xp[~lern][:, spalten])
                    richtig += int((p.mean() >= 0.5) == (y_b[t] == 1))
                z["LDA_Trefferquote_Baum"] = richtig / len(gfl)
                Zb = Xb[:, spalten]
                sd = Zb.std(0)
                Zb = (Zb - Zb.mean(0)) / np.where(sd > 0, sd, 1)
                km = KMeans(n_clusters=2, n_init=20, random_state=0).fit(Zb)
                treffer = float((km.labels_ == y_b).mean())
                z["kMeans_Uebereinstimmung_Baum"] = max(treffer, 1 - treffer)
            erg["kanalsaetze"].append(z)
    return erg


# -----------------------------------------------------------------------------
# Rechenaufwand je Kanalsatz (Version 0.19)
# -----------------------------------------------------------------------------
# Für Kapitel 5.3 (Teilziel „Rechenaufwand“): Was kostet ein Kanal mehr oder weniger?
# 1) Datenmenge: Rohdateien der Kanäle einer Aufnahme (Dateigröße) und Reflektanzstapel im Speicher (float32).
# 2) Vorverarbeitung: eine Aufnahme je Set wird aus den Rohbildern geladen (Radiometrie, Entzerrung, Ausrichtung)
#    und die Zeit je Kanal bestimmt (Gesamtzeit / Kanalzahl; jeder Kanal wird einzeln verarbeitet). Der Wert je
#    Kanalsatz ist eine Hochrechnung (Kanalzahl x Zeit je Kanal), keine Einzelmessung.
# 3) Klassifikator: Random Forest mit denselben Einstellungen wie das Baummodell, nur auf den Reflektanzen des
#    Kanalsatzes, vital/geschädigt je Pixel; Prüfung über ganze Bäume (GroupKFold), Baum = Mehrheit seiner Pixel.
#    Gemessen werden Trefferquote, Trainingszeit und Vorhersagezeit je 1 Mio. Pixel (Median aus Wiederholungen).
#    Zum Vergleich dieselben Größen für die LDA. Alle Zeiten mit einem Rechenkern (n_jobs = 1), damit sie
#    vergleichbar sind und nicht von der Auslastung paralleler Kerne abhängen.
AUFWAND_PIXEL_JE_BAUM = 300
AUFWAND_FALTEN = 5
AUFWAND_WIEDERHOLUNGEN = 3
AUFWAND_VORHERSAGE_PIXEL = 200_000


def _zeit(f, wdh=AUFWAND_WIEDERHOLUNGEN):
    import time
    z = []
    for _ in range(wdh):
        t0 = time.perf_counter()
        f()
        z.append(time.perf_counter() - t0)
    return float(np.median(z))


def _rechner_info():
    import platform
    import sklearn
    return {"prozessor": platform.processor() or platform.machine(), "kerne_logisch": os.cpu_count(),
            "system": platform.platform(), "python": platform.python_version(), "scikit_learn": sklearn.__version__,
            "numpy": np.__version__}


def rechenaufwand(ref, je_set=True, fortschritt=print, abbrechen=lambda: False):
    """Rechenaufwand je Kanalsatz (Datenmenge, Vorverarbeitung, Random Forest/LDA) an den Referenzbäumen.
    Rückgabe: {'zeilen': [...], 'vorverarbeitung': [...], 'info': {...}}."""
    import time
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import GroupKFold
    fl = [f for f in ref.flaechen if "kanaele" in f]
    if not fl or len(fl) < len(ref.flaechen):
        raise ValueError(f"{len(ref.flaechen) - len(fl)} Referenzfläche(n) ohne Kanalwerte - zuerst ergänzen "
                         "(„Kanalanalyse …“).")
    kanaele = [k for k in KANALNAMEN if all(k in f["kanaele"] for f in fl)]
    saetze = {s: k for s, k in KANALSAETZE.items() if all(c in kanaele for c in k)}
    gruppen = {"alle": fl}
    sets = sorted({os.path.normpath(f["ordner"]) for f in fl})
    if je_set and len(sets) > 1:
        for s in sets:
            gruppen[_set_name(s)] = [f for f in fl if os.path.normpath(f["ordner"]) == s]
    erg = {"zeilen": [], "vorverarbeitung": [],
           "info": {"version": VERSION, "rechner": _rechner_info(), "pixel_je_baum": AUFWAND_PIXEL_JE_BAUM,
                    "falten": AUFWAND_FALTEN, "wiederholungen_zeitmessung": AUFWAND_WIEDERHOLUNGEN,
                    "vorhersage_pixel": AUFWAND_VORHERSAGE_PIXEL, "kanalsaetze": saetze,
                    "random_forest": "150 Bäume, min_samples_leaf=5, max_features=sqrt, class_weight=balanced, "
                                     "random_state=0, n_jobs=1 (wie Baummodell, aber ein Kern)",
                    "pruefung": "GroupKFold über Bäume; Baum richtig, wenn die Mehrheit seiner Pixel richtig ist",
                    "vorverarbeitung": "je Set eine Aufnahme aus Rohbildern geladen (2. Lauf, Ausrichtung "
                                       "gespeichert); Zeit je Kanal = Gesamtzeit / Kanalzahl; Kanalsatz = Hochrechnung"}}
    schritte = len(sets) + len(gruppen) * len(saetze)
    schritt = 0

    # 1) + 2) Datenmenge und Vorverarbeitung je Set (eine Aufnahme)
    vv = {}
    for s in sets:
        if abbrechen():
            raise InterruptedError("abgebrochen")
        f0 = next(f for f in fl if os.path.normpath(f["ordner"]) == s)
        fortschritt((schritt, schritte, f"Vorverarbeitung {_set_name(s)} {f0['aufnahme']}"))
        schritt += 1
        z = {"Set": _set_name(s), "Aufnahme": f0["aufnahme"]}
        try:
            roh = rohaufnahmen(f0["ordner"]).get(f0["aufnahme"])
            if not roh:
                raise FileNotFoundError("keine Rohbilder gefunden")
            spektral, _ = _ordne_dateien(roh)
            z["MB_je_Kanal_roh"] = {k: os.path.getsize(p) / 1e6 for k, p in spektral.items()}

            def lade():
                return lade_aufnahme(f0["ordner"], f0["aufnahme"], fortschritt=lambda t: None,
                                     aus_rohbildern=True, schaerfen=False)
            lade()                                              # 1. Lauf: Ausrichtung ggf. schätzen/laden
            t0 = time.perf_counter()
            a = lade()
            dauer = time.perf_counter() - t0
            n_k = a.stapel.shape[0]
            z.update({"Kanaele": n_k, "Bildgroesse_px": f"{a.stapel.shape[2]} x {a.stapel.shape[1]}",
                      "Vorverarbeitung_s": dauer, "Vorverarbeitung_s_je_Kanal": dauer / n_k,
                      "MB_Stapel_je_Kanal": a.stapel[0].size * 4 / 1e6})
        except Exception as e:
            z["Fehler"] = str(e).splitlines()[0]
        vv[s] = z
        erg["vorverarbeitung"].append({k: v for k, v in z.items() if k != "MB_je_Kanal_roh"}
                                      | {f"MB_roh_{KANAL_ANZEIGE[k]}": v
                                         for k, v in z.get("MB_je_Kanal_roh", {}).items()})

    # 3) Klassifikatoren je Gruppe und Kanalsatz
    for gname, gfl in gruppen.items():
        daten = _baumdaten(gfl, kanaele, n_je_baum=AUFWAND_PIXEL_JE_BAUM)
        n_je = min(len(w) for w in daten[kanaele[0]])
        X = np.column_stack([np.concatenate([w[:n_je] for w in daten[k]]) for k in kanaele])
        baum = np.repeat(np.arange(len(gfl)), n_je)
        y_baum = np.array([f["klasse"] for f in gfl])
        y = y_baum[baum]
        n_falten = min(AUFWAND_FALTEN, len(gfl))
        gruppen_sets = {os.path.normpath(f["ordner"]) for f in gfl}
        vv_g = [vv[s] for s in gruppen_sets if "Vorverarbeitung_s_je_Kanal" in vv.get(s, {})]
        for sname, satz in saetze.items():
            if abbrechen():
                raise InterruptedError("abgebrochen")
            fortschritt((schritt, schritte, f"{gname}: Kanalsatz {sname}"))
            schritt += 1
            sp = [kanaele.index(k) for k in satz]
            Xs = X[:, sp]
            z = {"Gruppe": gname, "Kanalsatz": sname, "Kanaele": ", ".join(KANAL_ANZEIGE[k] for k in satz),
                 "Kanalzahl": len(satz), "Baeume": len(gfl), "Pixel_je_Baum": int(n_je)}
            if vv_g:
                z["MB_roh_je_Aufnahme"] = float(np.mean([sum(v["MB_je_Kanal_roh"][k] for k in satz) for v in vv_g]))
                z["MB_Stapel_je_Aufnahme"] = float(np.mean([v["MB_Stapel_je_Kanal"] for v in vv_g])) * len(satz)
                z["Vorverarbeitung_s_je_Aufnahme_hochgerechnet"] = float(
                    np.mean([v["Vorverarbeitung_s_je_Kanal"] for v in vv_g])) * len(satz)
            if (y_baum == 1).sum() >= 2 and (y_baum == 0).sum() >= 2:
                for verfahren in ("RF", "LDA"):
                    richtig = np.zeros(len(gfl), bool)
                    t_lern = []
                    mod = None
                    for lern, test in GroupKFold(n_splits=n_falten).split(Xs, y, baum):
                        if verfahren == "RF":
                            mod = RandomForestClassifier(n_estimators=150, min_samples_leaf=5, max_features="sqrt",
                                                         class_weight="balanced", n_jobs=1, random_state=0)
                        else:
                            mod = LinearDiscriminantAnalysis()
                        t0 = time.perf_counter()
                        mod.fit(Xs[lern], y[lern])
                        t_lern.append(time.perf_counter() - t0)
                        p = mod.predict(Xs[test])
                        for b in np.unique(baum[test]):
                            richtig[b] = (p[baum[test] == b].mean() >= 0.5) == (y_baum[b] == 1)
                    # Vorhersagezeit: letztes Modell auf AUFWAND_VORHERSAGE_PIXEL Pixeln (wiederholte Zeilen)
                    Xv = np.resize(Xs, (AUFWAND_VORHERSAGE_PIXEL, Xs.shape[1]))
                    t_vor = _zeit(lambda: mod.predict(Xv))
                    q_v = richtig[y_baum == 1].mean()
                    q_g = richtig[y_baum == 0].mean()
                    z.update({f"{verfahren}_Treffer_Baum": float(richtig.mean()),
                              f"{verfahren}_Treffer_ausgewogen": float((q_v + q_g) / 2),
                              f"{verfahren}_Training_s": float(np.mean(t_lern)),
                              f"{verfahren}_Vorhersage_s_je_Mio_Pixel": t_vor * 1e6 / AUFWAND_VORHERSAGE_PIXEL})
            erg["zeilen"].append(z)
    fortschritt((schritte, schritte, "fertig"))
    return erg


def rechenaufwand_als_csv(erg, pfad, protokoll=None):
    """Schreibt <basis>_Rechenaufwand.csv, _Vorverarbeitung.csv und _Rechenaufwand_Parameter.json."""
    basis = os.path.splitext(pfad)[0]
    dateien = []
    for teil, name in (("zeilen", "Rechenaufwand"), ("vorverarbeitung", "Vorverarbeitung")):
        zeilen = erg[teil]
        if not zeilen:
            continue
        spalten = list(dict.fromkeys(k for z in zeilen for k in z))
        p = f"{basis}_{name}.csv"
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f, delimiter=";")
            wr.writerow(spalten)
            for z in zeilen:
                wr.writerow([(f"{v:.6g}" if isinstance(v, float) else ("" if v is None else v))
                             for v in (z.get(k) for k in spalten)])
        dateien.append(p)
    p = basis + "_Rechenaufwand_Parameter.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump((protokoll or {}) | {"rechenaufwand": erg["info"]}, f, indent=2, ensure_ascii=False, default=str)
    dateien.append(p)
    return dateien


def kanalanalyse_als_csv(erg, pfad, protokoll=None):
    """Schreibt <basis>_Trennung.csv, _Korrelation.csv, _PCA.csv, _Kanalsaetze.csv und _Parameter.json."""
    basis = os.path.splitext(pfad)[0]
    namen = {"trennung": "Trennung", "korrelation": "Korrelation", "pca": "PCA", "kanalsaetze": "Kanalsaetze"}

    def zelle(v):
        return f"{v:.4f}" if isinstance(v, float) else ("" if v is None else v)

    dateien = []
    for teil, name in namen.items():
        zeilen = erg[teil]
        if not zeilen:
            continue
        spalten = list(dict.fromkeys(k for z in zeilen for k in z))
        p = f"{basis}_{name}.csv"
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f, delimiter=";")
            wr.writerow(spalten)
            for z in zeilen:
                wr.writerow([zelle(z.get(k)) for k in spalten])
        dateien.append(p)
    with open(basis + "_Parameter.json", "w", encoding="utf-8") as f:
        json.dump((protokoll or {}) | {"kanalanalyse": erg["info"]}, f, indent=2, ensure_ascii=False, default=str)
    dateien.append(basis + "_Parameter.json")
    return dateien


# -----------------------------------------------------------------------------
# Schwellen aus Baummedianen (Version 0.17)
# -----------------------------------------------------------------------------
# Für die Baumregel „Median je Baum“ wird die Schwelle auf derselben Einheit abgeleitet, auf der sie angewendet wird:
# Jede Ableitungsfläche wird – mit derselben Maske, Kronentrennung und Kronenkorrektur wie in der Auswertung – dem
# Baumobjekt mit der größten Überdeckung zugeordnet; dessen Median je Index geht in eine Youden-Analyse auf Baumebene
# ein (vital: Median ≥ t, geschädigt: Median < t). Die Schwelle liegt in der Mitte zwischen zwei benachbarten
# Baummedianen. Kleine Stichproben: Die Schwelle ist nur so genau wie die Lücke zwischen den Klassen.
BAUMSCHW_SPALTEN = ["Index", "Baeume_vital", "Baeume_geschaedigt", "Kein_Baum", "Schwelle", "Youden_J",
                    "Sensitivitaet", "Spezifitaet", "AUC_Baum", "Median_vital_min", "Median_vital_max",
                    "Median_geschaedigt_min", "Median_geschaedigt_max", "Pixel_Schwelle"]


def _youden_baum(v, g):
    """Youden-Schwelle für wenige Werte: Kandidaten = Mitten zwischen benachbarten sortierten Werten."""
    w = np.unique(np.concatenate([v, g]))
    kand = np.concatenate([[w[0] - 1e-6], (w[:-1] + w[1:]) / 2, [w[-1] + 1e-6]])
    best = None
    for t in kand:
        sens, spez = float((g < t).mean()), float((v >= t).mean())
        j = sens + spez - 1
        if best is None or j > best[1] + 1e-12:
            best = (float(t), j, sens, spez)
    return best


def baum_schwellen(ableitung, vorgabe, basis, fortschritt=print, abbrechen=lambda: False):
    """Schwellen je Index aus den Baummedianen der Ableitungsbäume.
    basis: {Index: Schwellen} – liefert Kronentrennung und Pixel-Schwelle (Klassen werden für die Mediane nicht
    gebraucht). Rückgabe: (Ergebnis je Index [dict], {Index: Schwellen (2 Klassen, Baumregel Median)}, Fehler)."""
    zeilen, _, fehler = pruefe_schwellen(ableitung, vorgabe, basis, fortschritt, abbrechen)
    ergebnisse, neu = [], {}
    for idx, s0 in basis.items():
        zi = [z for z in zeilen if z["Index"] == idx]
        v = np.array([z["Median"] for z in zi if z["Soll"] == "vital" and z.get("Median") == z.get("Median")
                      and "Median" in z], float)
        g = np.array([z["Median"] for z in zi if z["Soll"] == "gestresst" and z.get("Median") == z.get("Median")
                      and "Median" in z], float)
        kein = sum(z["Ergebnis"] == "kein Baum" for z in zi)
        if v.size < 2 or g.size < 2:
            fehler.append((idx, f"zu wenige Bäume mit Median (vital {v.size}, geschädigt {g.size})"))
            continue
        t, j, sens, spez = _youden_baum(v, g)
        auc = float(((v[:, None] > g[None, :]).sum() + 0.5 * (v[:, None] == g[None, :]).sum()) / (v.size * g.size))
        e = {"Index": idx, "Baeume_vital": int(v.size), "Baeume_geschaedigt": int(g.size), "Kein_Baum": int(kein),
             "Schwelle": t, "Youden_J": j, "Sensitivitaet": sens, "Spezifitaet": spez, "AUC_Baum": auc,
             "Median_vital_min": float(v.min()), "Median_vital_max": float(v.max()),
             "Median_geschaedigt_min": float(g.min()), "Median_geschaedigt_max": float(g.max()),
             "Pixel_Schwelle": float(s0.gestresst)}
        ergebnisse.append(e)
        herkunft = (f"Baummediane von {v.size} vitalen / {g.size} geschädigten Ableitungsbäumen (Youden J {j:.2f}, "
                    f"AUC Baum {auc:.2f}); Maske: {vorgabe.beschreibung()}; Baumregel Median je Baum")
        neu[idx] = Schwellen(round(t, 4), round(t, 4), s0.anteil_markierung, s0.kronenabstand_px, herkunft,
                             s0.kronen_nir, s0.kronen_raster, "median")
    return ergebnisse, neu, fehler


def baum_schwellen_als_csv(ergebnisse, pfad, protokoll=None):
    def zelle(v):
        return f"{v:.4f}" if isinstance(v, float) else v
    with open(pfad, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(BAUMSCHW_SPALTEN)
        for e in ergebnisse:
            wr.writerow([zelle(e[k]) for k in BAUMSCHW_SPALTEN])
    if protokoll is not None:
        with open(os.path.splitext(pfad)[0] + "_Parameter.json", "w", encoding="utf-8") as f:
            json.dump(protokoll, f, indent=2, ensure_ascii=False, default=str)
