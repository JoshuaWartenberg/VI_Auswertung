"""
Zusammenführen und radiometrische Korrektur von MicaSense-RedEdge-P-Aufnahmen
==============================================================================

Für jede Aufnahme (IMG_XXXX_1.tif ... IMG_XXXX_5.tif) werden die 5 Einzelkanäle
  1. radiometrisch korrigiert (Rohwert -> Radianz -> Reflektanz über DLS-2-Einstrahlung),
  2. entzerrt (Linsenverzeichnung) und deckungsgleich aufeinander ausgerichtet,
  3. als ein 5-Kanal-GeoTIFF-kompatibles TIFF (Float32, Reflektanz 0..1) gespeichert,
  4. zusätzlich als 8-Bit-RGB-Bild (Echtfarben) NUR ZUR ANZEIGE gespeichert (optional).

Das Verfahren folgt dem offiziellen MicaSense-Bildverarbeitungsmodell
(github.com/micasense/imageprocessing), ist aber eigenständig implementiert.

Benötigte Pakete:  pip install numpy opencv-python-headless tifffile imagecodecs
Aufruf:            python multispektral_stapeln.py
"""

# =============================================================================
# EINSTELLUNGEN  -  hier den zu verarbeitenden Ordner eintragen
# =============================================================================

# Ordner mit den Rohbildern (IMG_0000_1.tif ... ). Nur diese Zeile ändern,
# um z. B. den Ordner 001 oder einen anderen Flug zu verarbeiten.
EINGABE_ORDNER = r"C:\Users\joshu\OneDrive\Bachelorarbeit\Bilder\0026SET\000"

# Name des Unterordners (wird im EINGABE_ORDNER angelegt) für die Ergebnisse
AUSGABE_UNTERORDNER = "Reflektanz_5Kanal"

# Kanäle deckungsgleich ausrichten (True) oder nur übereinanderlegen (False)
KANAELE_AUSRICHTEN = True

# Referenzkanal für die Ausrichtung (1=Blau, 2=Grün, 3=Rot, 4=NIR, 5=Red Edge).
# Red Edge liegt spektral zwischen sichtbarem Licht und NIR und korreliert
# daher mit allen anderen Kanälen am besten.
REFERENZ_KANAL = 5

# Anzahl Aufnahmen (aus der Flughöhe), aus denen die Ausrichtung geschätzt wird
ANZAHL_KALIBRIER_AUFNAHMEN = 10

# Bereits vorhandene Ergebnisdateien überschreiben?
UEBERSCHREIBEN = False

# Zusätzlich ein RGB-Bild (Echtfarben, 8 Bit) NUR ZUR ANZEIGE erzeugen?
# Es liegt im Unterordner RGB_UNTERORDNER innerhalb des Ausgabeordners.
RGB_ERSTELLEN = True
RGB_UNTERORDNER = "RGB"

# Reflektanz, die im RGB-Bild voll weiß (255) dargestellt wird, und Gamma.
# Fest für alle Bilder, damit Helligkeit/Farben zwischen Bildern vergleichbar bleiben.
RGB_MAX_REFLEKTANZ = 0.12
RGB_GAMMA = 2.2

# =============================================================================
# AB HIER NICHTS MEHR ÄNDERN
# =============================================================================

import csv
import glob
import os
import re
import sys
import time

import cv2
import numpy as np
import tifffile

KANAL_ANZAHL = 5
MAX_VERSATZ_PX = 100   # größere geschätzte Kanalversätze sind physikalisch unplausibel (Ausreißer)


# -----------------------------------------------------------------------------
# Metadaten
# -----------------------------------------------------------------------------
def _xmp_wert(xmp, name):
    m = re.search(rf"<{name}>([^<]*)</{name}>", xmp)
    return m.group(1).strip() if m else None


def _xmp_liste(xmp, name):
    m = re.search(rf"<{name}>\s*<rdf:Seq>(.*?)</rdf:Seq>", xmp, re.S)
    if not m:
        return None
    return [s.strip() for s in re.findall(r"<rdf:li>([^<]*)</rdf:li>", m.group(1))]


def _gps_dezimal(dms, ref):
    grad = sum(float(n) / float(d) / 60 ** i for i, (n, d) in
               enumerate(zip(dms[0::2], dms[1::2])))
    return -grad if ref in ("S", "W") else grad


def lies_kanal(pfad):
    """Liest Rohbild und alle für die Korrektur nötigen Metadaten eines Kanals."""
    with tifffile.TiffFile(pfad) as tif:
        seite = tif.pages[0]
        roh = seite.asarray().astype(np.float64)
        xmp = seite.tags["XMP"].value
        xmp = xmp.decode("utf-8", "ignore") if isinstance(xmp, bytes) else str(xmp)
        exif = seite.tags["ExifTag"].value
        gps = seite.tags["GPSTag"].value if "GPSTag" in seite.tags else {}
        black = seite.tags["BlackLevel"].value if "BlackLevel" in seite.tags else None
        bits = seite.tags["BitsPerSample"].value
        zeit = seite.tags["DateTime"].value if "DateTime" in seite.tags else ""

    def zahl(x):
        return float(x[0]) / float(x[1]) if isinstance(x, tuple) else float(x)

    m = {
        "roh": roh,
        "bandname": _xmp_wert(xmp, "Camera:BandName"),
        "wellenlaenge": float(_xmp_wert(xmp, "Camera:CentralWavelength")),
        "fwhm": float(_xmp_wert(xmp, "Camera:WavelengthFWHM")),
        "radiometrie": [float(v) for v in _xmp_liste(xmp, "MicaSense:RadiometricCalibration")],
        "vignette_koeff": [float(v) for v in _xmp_liste(xmp, "Camera:VignettingPolynomial2D")[0].split(",")],
        "vignette_exp": [int(v) for v in _xmp_liste(xmp, "Camera:VignettingPolynomial2DName")[0].split(",")],
        "brennweite_mm": float(_xmp_wert(xmp, "Camera:PerspectiveFocalLength")),
        "hauptpunkt_mm": [float(v) for v in _xmp_wert(xmp, "Camera:PrincipalPoint").split(",")],
        "verzeichnung": [float(v) for v in _xmp_liste(xmp, "Camera:PerspectiveDistortion")],
        "belichtung_s": zahl(exif["ExposureTime"]),
        "gain": float(exif.get("ISOSpeed", exif.get("ISOSpeedRatings", 100))) / 100.0,
        "px_pro_mm": zahl(exif["FocalPlaneXResolution"]),
        "bits": int(bits if np.isscalar(bits) else bits[0]),
        "zeit": zeit,
        "capture_id": _xmp_wert(xmp, "MicaSense:CaptureId"),
    }
    # Schwarzwert: gemittelter BlackLevel-Tag (wie MicaSense), sonst DarkRowValue
    if black is not None:
        m["schwarzwert"] = float(np.mean(black))
    else:
        m["schwarzwert"] = float(np.mean([float(v) for v in _xmp_liste(xmp, "MicaSense:DarkRowValue")]))

    # DLS-2-Einstrahlung. DLS2 speichert Werte in µW/cm²/nm; ohne expliziten
    # Skalierungs-Tag nimmt MicaSense den Faktor 0.01 -> W/m²/nm an.
    skala = _xmp_wert(xmp, "DLS:IrradianceScaleToSIUnits")
    horiz = _xmp_wert(xmp, "DLS:HorizontalIrradiance")
    if skala is not None:
        skala = float(skala)
    elif horiz is not None:
        skala = 0.01
    else:
        skala = 1.0
    if horiz is None:
        raise ValueError(f"{os.path.basename(pfad)}: keine DLS-Einstrahlung (HorizontalIrradiance) in den Metadaten")
    m["einstrahlung"] = float(horiz) * skala

    # GPS-Position (nur als Metadaten, das Einzelbild ist nicht orthorektifiziert)
    try:
        m["lat"] = _gps_dezimal(gps["GPSLatitude"], gps["GPSLatitudeRef"])
        m["lon"] = _gps_dezimal(gps["GPSLongitude"], gps["GPSLongitudeRef"])
        m["hoehe"] = zahl(gps["GPSAltitude"])
    except (KeyError, TypeError, ZeroDivisionError):
        m["lat"] = m["lon"] = m["hoehe"] = float("nan")
    return m


# -----------------------------------------------------------------------------
# Radiometrische Korrektur (MicaSense-Modell)
# -----------------------------------------------------------------------------
def vignette_karte(m, form):
    """2D-Polynom-Vignettierung (RedEdge-P): V = 1 / sum(c_i * x^ex_i * y^ey_i),
    x und y auf Bildbreite/-höhe normiert (0..1)."""
    h, w = form
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    x /= w
    y /= h
    p = np.zeros(form, dtype=np.float64)
    exps = m["vignette_exp"]
    for i, c in enumerate(m["vignette_koeff"]):
        p += c * x ** exps[2 * i] * y ** exps[2 * i + 1]
    return 1.0 / p


def reflektanz(m, vignette):
    """Rohwert (DN) -> spektrale Radianz L [W/m²/sr/nm] -> Reflektanz rho = pi*L/E.

    L = V(x,y) * a1/g * (p - p_BL) / (t_e + a2*y - a3*t_e*y) / 2^bits
    mit V = Vignettierung, a1..a3 = Radiometrie-Koeffizienten, g = Gain,
    t_e = Belichtungszeit, y = Bildzeile, p_BL = Schwarzwert.
    """
    a1, a2, a3 = m["radiometrie"]
    te = m["belichtung_s"]
    h, w = m["roh"].shape
    zeile = np.arange(h, dtype=np.float64)[:, None]
    r = 1.0 / (1.0 + a2 * zeile / te - a3 * zeile)   # zeilenabhängige Korrektur (Rolling Shutter / Dunkelstrom)
    L = vignette * r * (m["roh"] - m["schwarzwert"])
    L[L < 0] = 0
    radianz = L / (m["gain"] * te) * a1 / float(2 ** m["bits"])
    return radianz * np.pi / m["einstrahlung"]


# -----------------------------------------------------------------------------
# Geometrie: Entzerrung + Ausrichtung
# -----------------------------------------------------------------------------
def entzerr_karten(m, form):
    h, w = form
    f = m["brennweite_mm"] * m["px_pro_mm"]
    cx, cy = (v * m["px_pro_mm"] for v in m["hauptpunkt_mm"])
    K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], dtype=np.float64)
    k1, k2, k3, p1, p2 = m["verzeichnung"]          # MicaSense-Reihenfolge
    dist = np.array([k1, k2, p1, p2, k3])            # OpenCV-Reihenfolge
    return cv2.initUndistortRectifyMap(K, dist, None, K, (w, h), cv2.CV_32FC1)


def _gradient(bild):
    b = cv2.GaussianBlur(bild.astype(np.float32), (0, 0), 1.5)
    gx = cv2.Sobel(b, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(b, cv2.CV_32F, 0, 1, ksize=3)
    g = cv2.magnitude(gx, gy)
    return g / (np.percentile(g, 99) + 1e-12)


def ecc_homographie(referenz, kanal, stufen=4):
    """Homographie, die `kanal` auf `referenz` abbildet (Gradienten-ECC, Bildpyramide)."""
    ref_pyr, kan_pyr = [_gradient(referenz)], [_gradient(kanal)]
    for _ in range(stufen - 1):
        ref_pyr.append(cv2.pyrDown(ref_pyr[-1]))
        kan_pyr.append(cv2.pyrDown(kan_pyr[-1]))
    H = np.eye(3, dtype=np.float32)
    S = np.diag([2, 2, 1]).astype(np.float32)
    kriterium = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
    cc = 0.0
    for lvl in reversed(range(stufen)):
        if lvl != stufen - 1:
            H = S @ H @ np.linalg.inv(S)
        cc, H = cv2.findTransformECC(ref_pyr[lvl], kan_pyr[lvl], H,
                                     cv2.MOTION_HOMOGRAPHY, kriterium, None, 5)
    return H / H[2, 2], cc


def gueltiger_ausschnitt(maske):
    """Größtes achsparalleles Rechteck (Näherung), in dem alle Kanäle gültig sind."""
    r0, r1, c0, c1 = 0, maske.shape[0], 0, maske.shape[1]
    while True:
        sub = maske[r0:r1, c0:c1]
        if sub.all():
            return r0, r1, c0, c1
        ungueltig = {
            "oben": (~sub[0]).sum(), "unten": (~sub[-1]).sum(),
            "links": (~sub[:, 0]).sum(), "rechts": (~sub[:, -1]).sum(),
        }
        seite = max(ungueltig, key=ungueltig.get)
        if seite == "oben": r0 += 1
        elif seite == "unten": r1 -= 1
        elif seite == "links": c0 += 1
        else: c1 -= 1


# -----------------------------------------------------------------------------
# Ausgabe
# -----------------------------------------------------------------------------
def gdal_metadaten(kanaele, allgemein):
    """GDAL-Metadaten-XML (TIFF-Tag 42112): QGIS zeigt damit Kanalnamen an."""
    zeilen = ["<GDALMetadata>"]
    for k, v in allgemein.items():
        zeilen.append(f'  <Item name="{k}">{v}</Item>')
    for i, m in enumerate(kanaele):
        name = f'{m["bandname"]} {m["wellenlaenge"]:.0f} nm'
        zeilen.append(f'  <Item name="DESCRIPTION" sample="{i}" role="description">{name}</Item>')
        zeilen.append(f'  <Item name="WAVELENGTH_NM" sample="{i}">{m["wellenlaenge"]:.0f}</Item>')
        zeilen.append(f'  <Item name="FWHM_NM" sample="{i}">{m["fwhm"]:.0f}</Item>')
        zeilen.append(f'  <Item name="DLS_IRRADIANCE_W_M2_NM" sample="{i}">{m["einstrahlung"]:.6f}</Item>')
        zeilen.append(f'  <Item name="EXPOSURE_S" sample="{i}">{m["belichtung_s"]:.6f}</Item>')
    zeilen.append("</GDALMetadata>")
    return "\n".join(zeilen)


def speichere(pfad, stapel, kanaele):
    m0 = kanaele[0]
    allgemein = {
        "CAMERA": "MicaSense RedEdge-P",
        "CAPTURE_ID": m0["capture_id"],
        "DATETIME": m0["zeit"],
        "GPS_LAT": f'{m0["lat"]:.8f}', "GPS_LON": f'{m0["lon"]:.8f}', "GPS_ALT_M": f'{m0["hoehe"]:.2f}',
        "UNITS": "reflectance (0-1)",
        "PROCESSING": "radiometric correction (MicaSense model) + DLS2 irradiance, undistorted, band-aligned",
    }
    tifffile.imwrite(
        pfad, stapel.astype(np.float32), photometric="minisblack", planarconfig="separate",
        compression="zlib", predictor=True, tile=(256, 256), metadata=None,
        description="Reflektanz (0-1), Kanaele: " + ", ".join(m["bandname"] for m in kanaele),
        extratags=[(42112, "s", 0, gdal_metadaten(kanaele, allgemein), True)],
    )


def speichere_rgb(pfad, stapel):
    """8-Bit-Echtfarbbild (Rot = Kanal 3, Grün = Kanal 2, Blau = Kanal 1) nur zur Anzeige.

    Für alle drei Kanäle gilt dieselbe feste Skalierung. Da Reflektanz physikalisch bereits
    „weißabgeglichen“ ist (eine weiße Fläche hat in allen Kanälen die gleiche Reflektanz),
    entstehen so natürliche Farben. Das Gamma hellt die dunklen Vegetationswerte auf.
    """
    rgb = np.stack([stapel[2], stapel[1], stapel[0]])
    rgb = np.clip(np.nan_to_num(rgb) / RGB_MAX_REFLEKTANZ, 0, 1) ** (1 / RGB_GAMMA)
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    tifffile.imwrite(
        pfad, (rgb * 255 + 0.5).astype(np.uint8), photometric="rgb", planarconfig="separate",
        compression="zlib", tile=(256, 256), metadata=None,
        description=f"Nur Anzeige: Echtfarben aus Reflektanz (R=Kanal 3, G=2, B=1), "
                    f"0..{RGB_MAX_REFLEKTANZ} -> 0..255, Gamma {RGB_GAMMA}",
    )


# -----------------------------------------------------------------------------
# Hauptprogramm
# -----------------------------------------------------------------------------
def finde_aufnahmen(ordner):
    aufnahmen = {}
    for p in glob.glob(os.path.join(ordner, "IMG_*_*.tif")):
        m = re.match(r"(IMG_\d+)_(\d)\.tif$", os.path.basename(p), re.I)
        if m:
            aufnahmen.setdefault(m.group(1), {})[int(m.group(2))] = p
    vollstaendig = {k: v for k, v in aufnahmen.items() if len(v) == KANAL_ANZAHL}
    unvollstaendig = sorted(set(aufnahmen) - set(vollstaendig))
    return dict(sorted(vollstaendig.items())), unvollstaendig


def main():
    t_start = time.time()
    ausgabe = os.path.join(EINGABE_ORDNER, AUSGABE_UNTERORDNER)
    os.makedirs(ausgabe, exist_ok=True)
    aufnahmen, unvollstaendig = finde_aufnahmen(EINGABE_ORDNER)
    print(f"Eingabe:  {EINGABE_ORDNER}")
    print(f"Ausgabe:  {ausgabe}")
    print(f"{len(aufnahmen)} vollständige Aufnahmen gefunden.")
    if unvollstaendig:
        print(f"Übersprungen (nicht alle 5 Kanäle vorhanden): {', '.join(unvollstaendig)}")
    if not aufnahmen:
        sys.exit("Keine Aufnahmen gefunden - EINGABE_ORDNER prüfen.")

    # Sind alle Reflektanzbilder schon vorhanden, nur fehlende RGB-Bilder ergänzen
    # (spart die erneute Ausrichtungsschätzung)
    offen = [n for n in aufnahmen
             if UEBERSCHREIBEN or not os.path.exists(os.path.join(ausgabe, f"{n}_reflektanz.tif"))]
    if not offen:
        print("Alle Reflektanzbilder existieren bereits.")
        if RGB_ERSTELLEN:
            neu = 0
            for i, name in enumerate(aufnahmen, 1):
                rgb_ziel = os.path.join(ausgabe, RGB_UNTERORDNER, f"{name}_rgb.tif")
                if not os.path.exists(rgb_ziel):
                    speichere_rgb(rgb_ziel, tifffile.imread(os.path.join(ausgabe, f"{name}_reflektanz.tif")))
                    neu += 1
                    print(f"[{i:4d}/{len(aufnahmen)}] {name}: RGB-Bild erstellt")
            print(f"{neu} RGB-Bilder neu erstellt.")
        print(f"\nFertig in {time.time() - t_start:.0f} s.")
        return

    # Kameraspezifische, über alle Aufnahmen konstante Größen einmal berechnen
    erste = [lies_kanal(aufnahmen[next(iter(aufnahmen))][b]) for b in range(1, 6)]
    form = erste[0]["roh"].shape
    vignetten = [vignette_karte(m, form) for m in erste]
    karten = [entzerr_karten(m, form) for m in erste]

    def korrigiert(kanaele):
        return [cv2.remap(reflektanz(m, v).astype(np.float32), mx, my, cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
                for m, v, (mx, my) in zip(kanaele, vignetten, karten)]

    # ---- Ausrichtung schätzen (einmal pro Ordner, aus Aufnahmen in Flughöhe) ----
    ref = REFERENZ_KANAL - 1
    homographien = [np.eye(3, dtype=np.float32) for _ in range(KANAL_ANZAHL)]
    ausricht_info = "keine Ausrichtung (KANAELE_AUSRICHTEN = False)"
    if KANAELE_AUSRICHTEN:
        namen = list(aufnahmen)
        hoehen = []
        for n in namen:
            with tifffile.TiffFile(aufnahmen[n][1]) as t:
                g = t.pages[0].tags["GPSTag"].value if "GPSTag" in t.pages[0].tags else {}
            a = g.get("GPSAltitude", (0, 1))
            hoehen.append(a[0] / a[1] if isinstance(a, tuple) else float(a))
        hoehen = np.array(hoehen)
        in_flughoehe = [n for n, h in zip(namen, hoehen) if h >= np.percentile(hoehen, 50)]
        idx = np.linspace(0, len(in_flughoehe) - 1, min(ANZAHL_KALIBRIER_AUFNAHMEN, len(in_flughoehe))).round().astype(int)
        stichprobe = [in_flughoehe[i] for i in idx]
        print(f"\nSchätze Kanal-Ausrichtung aus {len(stichprobe)} Aufnahmen "
              f"(absolute GPS-Höhe >= {np.percentile(hoehen, 50):.1f} m, nicht Höhe über Grund): {', '.join(stichprobe)}")
        # Ausrichtungspartner je Kanal: Blau korreliert kaum mit Red Edge/NIR (direkte ECC-Schätzung
        # scheitert oft oder liefert Ausreißer), aber gut mit Grün -> Blau über Grün ausrichten
        # und die beiden Homographien verketten. Alle anderen Kanäle direkt auf den Referenzkanal.
        partner = {b: ref for b in range(KANAL_ANZAHL) if b != ref}
        if ref not in (0, 1):
            partner[0] = 1
        schaetzungen = {b: [] for b in partner}
        for n in stichprobe:
            bilder = [np.nan_to_num(b) for b in korrigiert([lies_kanal(aufnahmen[n][k]) for k in range(1, 6)])]
            for b, p in partner.items():
                try:
                    H, cc = ecc_homographie(bilder[p], bilder[b])
                except cv2.error:
                    print(f"  {n} Kanal {b + 1}: ECC nicht konvergiert - verworfen")
                    continue
                if np.abs(H[:2, 2]).max() > MAX_VERSATZ_PX:
                    print(f"  {n} Kanal {b + 1}: unplausibler Versatz ({H[0, 2]:+.0f}, {H[1, 2]:+.0f}) px - verworfen")
                    continue
                schaetzungen[b].append((H, cc))

        # Robuster Median: Schätzungen, deren Versatz > 3 px vom Median abweicht, verwerfen
        paar_H, zeilen = {}, []
        for b, liste in schaetzungen.items():
            if liste:
                t_med = np.median([h[:2, 2] for h, _ in liste], axis=0)
                liste = [(h, c) for h, c in liste if np.abs(h[:2, 2] - t_med).max() <= 3.0]
            if len(liste) < 2:
                sys.exit(f"Ausrichtung für Kanal {b + 1} fehlgeschlagen (zu wenige gültige Schätzungen). "
                         f"ANZAHL_KALIBRIER_AUFNAHMEN erhöhen oder REFERENZ_KANAL ändern.")
            paar_H[b] = np.median(np.array([h for h, _ in liste]), axis=0)
            zeilen.append((b, len(liste), np.mean([c for _, c in liste])))

        # Homographien auf den Referenzkanal: direkte Partner zuerst, verkettete danach.
        # kanal(H_b->p · x) ≈ partner(x) und partner(H_p · x) ≈ ref(x)  =>  H_b = H_b->p · H_p
        for b in sorted(partner, key=lambda k: partner[k] != ref):
            p = partner[b]
            homographien[b] = (paar_H[b] if p == ref else paar_H[b] @ homographien[p]).astype(np.float32)
        info = []
        for b, anzahl, cc in zeilen:
            verschiebung = homographien[b][:2, 2]
            ueber = "" if partner[b] == ref else f" (über Kanal {partner[b] + 1})"
            info.append(f"  Kanal {b + 1} ({erste[b]['bandname']}){ueber}: {anzahl} gültige Schätzungen, "
                        f"mittl. Korrelation {cc:.3f}, "
                        f"Verschiebung dx={verschiebung[0]:+.1f} px, dy={verschiebung[1]:+.1f} px")
        ausricht_info = "\n".join(info)
        print(ausricht_info)

    # Gemeinsamer gültiger Bildausschnitt aller Kanäle nach Entzerrung + Ausrichtung
    maske = np.ones(form, dtype=bool)
    for b, (mx, my) in enumerate(karten):
        g = cv2.remap(np.ones(form, np.float32), mx, my, cv2.INTER_NEAREST, borderValue=0)
        g = cv2.warpPerspective(g, homographien[b], (form[1], form[0]),
                                flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0)
        maske &= g > 0
    # 2 px Sicherheitsrand: bilineare Interpolation zieht am Rand ungültige Nachbarpixel mit hinein
    maske = cv2.erode(maske.astype(np.uint8), np.ones((5, 5), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
    r0, r1, c0, c1 = gueltiger_ausschnitt(maske)
    print(f"\nGemeinsamer Ausschnitt: Zeilen {r0}-{r1}, Spalten {c0}-{c1} "
          f"-> {c1 - c0} x {r1 - r0} px (Original {form[1]} x {form[0]})\n")

    # ---- Alle Aufnahmen verarbeiten ----
    protokoll = []
    for i, (name, dateien) in enumerate(aufnahmen.items(), 1):
        ziel = os.path.join(ausgabe, f"{name}_reflektanz.tif")
        rgb_ziel = os.path.join(ausgabe, RGB_UNTERORDNER, f"{name}_rgb.tif")
        if os.path.exists(ziel) and not UEBERSCHREIBEN:
            if RGB_ERSTELLEN and not os.path.exists(rgb_ziel):
                speichere_rgb(rgb_ziel, tifffile.imread(ziel))
                print(f"[{i:4d}/{len(aufnahmen)}] {name}: existiert bereits - nur RGB-Bild erstellt")
            else:
                print(f"[{i:4d}/{len(aufnahmen)}] {name}: existiert bereits - übersprungen")
            continue
        try:
            kanaele = [lies_kanal(dateien[b]) for b in range(1, 6)]
            bilder = korrigiert(kanaele)
            stapel = np.stack([
                cv2.warpPerspective(img, homographien[b], (form[1], form[0]),
                                    flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                    borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
                for b, img in enumerate(bilder)
            ])[:, r0:r1, c0:c1]
            speichere(ziel, stapel, kanaele)
            if RGB_ERSTELLEN:
                speichere_rgb(rgb_ziel, stapel)
            median = np.nanmedian(stapel.reshape(KANAL_ANZAHL, -1), axis=1)
            gesaettigt = sum(int((m["roh"] >= 65500).sum()) for m in kanaele)
            protokoll.append([name, kanaele[0]["zeit"], f'{kanaele[0]["lat"]:.8f}', f'{kanaele[0]["lon"]:.8f}',
                              f'{kanaele[0]["hoehe"]:.2f}']
                             + [f'{m["einstrahlung"]:.5f}' for m in kanaele]
                             + [f"{v:.4f}" for v in median] + [gesaettigt, "ok"])
            print(f"[{i:4d}/{len(aufnahmen)}] {name}: ok  (Median-Reflektanz "
                  + " ".join(f"{v:.3f}" for v in median) + ")")
        except Exception as e:  # einzelne defekte Aufnahmen sollen den Lauf nicht abbrechen
            protokoll.append([name] + [""] * 14 + [f"FEHLER: {e}"])
            print(f"[{i:4d}/{len(aufnahmen)}] {name}: FEHLER - {e}")

    # ---- Protokolle schreiben ----
    kanalnamen = [f'{m["bandname"]}_{m["wellenlaenge"]:.0f}' for m in erste]
    if protokoll:
        # Mit vorhandenem Protokoll zusammenführen, damit bei einem fortgesetzten Lauf
        # (UEBERSCHREIBEN = False) die Zeilen früherer Läufe erhalten bleiben
        protokoll_pfad = os.path.join(ausgabe, "Verarbeitungsprotokoll.csv")
        zeilen = {}
        if os.path.exists(protokoll_pfad):
            with open(protokoll_pfad, newline="", encoding="utf-8") as f:
                zeilen = {z[0]: z for z in list(csv.reader(f, delimiter=";"))[1:] if z}
        zeilen.update({z[0]: z for z in protokoll})
        with open(protokoll_pfad, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Aufnahme", "Zeit", "Lat", "Lon", "Hoehe_m"]
                       + [f"DLS_E_{k}_W_m2_nm" for k in kanalnamen]
                       + [f"Median_Refl_{k}" for k in kanalnamen] + ["Gesaettigte_Pixel", "Status"])
            w.writerows(zeilen[k] for k in sorted(zeilen))
    with open(os.path.join(ausgabe, "Ausrichtung.txt"), "w", encoding="utf-8") as f:
        f.write(f"Referenzkanal: {REFERENZ_KANAL} ({erste[ref]['bandname']})\n{ausricht_info}\n\n")
        f.write(f"Ausschnitt (Zeilen r0:r1, Spalten c0:c1): {r0}:{r1}, {c0}:{c1}\n\n")
        for b, H in enumerate(homographien):
            f.write(f"Homographie Kanal {b + 1} ({erste[b]['bandname']}):\n{np.array2string(H, precision=6)}\n\n")

    fehler = sum(1 for p in protokoll if p[-1] != "ok")
    print(f"\nFertig in {time.time() - t_start:.0f} s: {len(protokoll) - fehler} gespeichert, {fehler} Fehler.")


if __name__ == "__main__":
    main()
