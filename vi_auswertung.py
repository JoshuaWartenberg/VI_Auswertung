"""
VI-Auswertung – Oberfläche zur pixelweisen Auswertung von Vegetationsindizes
=============================================================================

Einzelaufnahmen der MicaSense RedEdge-P laden (einzeln oder ganze Ordner), Vegetationsindex wählen
(NDVI, NDRE, ReNDVI, GNDVI), Indexkarte und Histogramm ansehen, Pixelwerte abfragen, Untersuchungsflächen
(ROIs) aufziehen, mit Vegetations- oder Baummaske auswerten, Ordner komplett auswerten und exportieren.

Baummaske: überwachte Klassifikation. Man zeichnet in einem oder mehreren Bildern Flächen „Baum“ und
„kein Baum“ ein, trainiert ein Random-Forest-Modell und wendet es auf alle Bilder an.

Start:  python vi_auswertung.py      (oder Doppelklick auf "VI_Auswertung starten.bat")
Rechenkern (ohne Oberfläche): vi_kern.py
"""

import dataclasses
import json
import os
import queue
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

import cv2
import matplotlib
matplotlib.use("TkAgg")
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.colors import ListedColormap
from matplotlib.ticker import AutoLocator
from matplotlib.figure import Figure
from matplotlib.patches import Polygon, Rectangle
from matplotlib.widgets import LassoSelector, RectangleSelector

import vi_kern as vk

START_ORDNER = r"C:\Users\joshu\OneDrive\Bachelorarbeit\Bilder"
if not os.path.isdir(START_ORDNER):          # anderer Rechner: im Benutzerordner beginnen
    START_ORDNER = os.path.expanduser("~")
ROI_FARBEN = ["#1f77b4", "#d62728", "#9467bd", "#ff7f0e", "#17becf", "#e377c2", "#8c564b", "#bcbd22"]
KLASSEN_FARBE = {1: "#00e676", 0: "#ff1744"}       # Trainingsflächen: Baum / kein Baum
SCHWELLEN_FARBEN = ["#d7191c", "#fdae61", "#1a9641"]  # gestresst / Übergang / vital
REF_FARBE = {1: "#00e5ff", 0: "#ff00ff"}             # Referenz vital / geschädigt
HINTERLEGT_FARBE = "#ffffff"                          # hinterlegte Ableitungsbäume (eingeblendet, ab 0.20)
MASKEN = ["keine", "Vegetation (NDVI ≥ Schwelle)", "Bäume (Modell)"]

# Darstellung hell / dunkel (Darkmode). Exportierte Abbildungen werden immer hell gespeichert.
THEMEN = {
    False: dict(hintergrund="#f0f0f0", feld="#ffffff", text="#000000", hinweis="#555555", auswahl="#0078d7",
                auswahl_text="#ffffff", rand="#a0a0a0", figur="#ffffff", achse="#ffffff", gitter="#b0b0b0",
                pixel_feld="#f4f4f4", falsch="#c62828", uebergang="#ef6c00", kein_baum="#757575"),
    True: dict(hintergrund="#1e1f22", feld="#2b2d30", text="#dcdcdc", hinweis="#9a9a9a", auswahl="#3d5a80",
               auswahl_text="#ffffff", rand="#4a4d52", figur="#1e1f22", achse="#26282b", gitter="#55585e",
               pixel_feld="#2b2d30", falsch="#ef5350", uebergang="#ffa726", kein_baum="#9e9e9e"),
}
EINSTELLUNGEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VI_Auswertung_Einstellungen.json")
# Arbeitsstand beim Schließen (ab 0.15): Einstellungen + Sicherungskopien von Baummodell und Referenzflächen
SITZUNG_ORDNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Sitzung")
SITZUNG_DATEI = os.path.join(SITZUNG_ORDNER, "Sitzung.json")


def lade_einstellungen():
    try:
        with open(EINSTELLUNGEN, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def speichere_einstellung(schluessel, wert):
    e = lade_einstellungen()
    e[schluessel] = wert
    try:
        with open(EINSTELLUNGEN, "w", encoding="utf-8") as f:
            json.dump(e, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def zwei_klassen(schw):
    """2-Klassen-Schema: Schwelle „gestresst“ = Schwelle „vital“ (kein Übergang) – ab 0.18 für Legenden."""
    return schw is not None and abs(schw.vital - schw.gestresst) < 1e-9


class App:
    def __init__(self, root, wiederherstellen=True):
        self.root = root
        root.title(f"VI-Auswertung {vk.VERSION}")
        root.geometry("1400x850")
        try:
            root.state("zoomed")                     # maximiert starten (Windows)
        except tk.TclError:
            pass
        self.aufn = None
        self.liste, self.pos = [], -1                # [(Ordner, Aufnahmename)]
        self.wurzel = None
        self.index_werte = None
        self.maske = None                            # aktuelle Maske (bool) oder None
        self._masken_schluessel = None
        self.merkmale = None                         # Merkmalsbild der aktuellen Aufnahme (Baummodell)
        self.modell = vk.Baummodell()
        self.modellpfad = ""
        self.modell_version = 0                      # erhöht sich bei jedem Training/Laden
        self.rois, self.roi_artists = [], []
        self.training_artists = []
        self.masken_artists = []
        self.schwellen_artists = []
        self.schwellen_werte = {}                     # Index -> vk.Schwellen (gemerkt)
        self.schwellen_aktiv = set()                  # Indizes mit eingeschalteter Klassifizierung
        self.referenzen = vk.Referenzen()
        self.referenzpfad = ""
        self.hinterlegt = vk.Referenzen()             # ab 0.20: hinterlegte Ableitungsbäume (nur Anzeige/Abgleich)
        self.hinterlegt_pfade = []
        self._einblend = {"schluessel": None, "flaechen": [], "ohne": [], "lauf": 0, "fertig": 0}
        self.klassen = None
        self.objekte = None
        self.objekt_labels = None
        self.kronen_korr = []                         # Kronenkorrekturen von Hand der angezeigten Aufnahme
        self._verbinden_start = None                  # erster Klick beim Verbinden
        self._teilen_zug = None                       # ab 0.18: (x, y, Bildschirm-x, -y, Linie, Objekt) beim Ziehen
        self.stapel_laeuft = False
        self.abbruch = threading.Event()
        self.q = queue.Queue()
        self._baue_oberflaeche()
        self._modell_anzeige()
        self._referenz_anzeige()
        self._schwellen_laden()
        self._hell_theme = ttk.Style().theme_use()
        self._thema_anwenden()
        self._beendet = False
        self._sitzung_text = None
        self._after_id = root.after(100, self._pruefe_queue)
        root.protocol("WM_DELETE_WINDOW", self._schliessen)
        if wiederherstellen:
            root.after(300, self._sitzung_wiederherstellen)

    # ------------------------------------------------------------------ Oberfläche
    def _baue_oberflaeche(self):
        leiste = ttk.Frame(self.root, padding=(4, 4, 4, 0))
        leiste.pack(side=tk.TOP, fill=tk.X)
        leiste2 = ttk.Frame(self.root, padding=(4, 4, 4, 0))
        leiste2.pack(side=tk.TOP, fill=tk.X)
        leiste3 = ttk.Frame(self.root, padding=4)
        leiste3.pack(side=tk.TOP, fill=tk.X)

        # Zeile 1: Kanalzahl/Panchro, Laden, Navigation, Index, Farbskala
        ttk.Label(leiste, text="Kanäle:").pack(side=tk.LEFT)
        self.var_kanalzahl = tk.StringVar(value=next(k for k, v in vk.KANALZAHL_AUSWAHL.items() if v == vk.KANALZAHL))
        ck = ttk.Combobox(leiste, textvariable=self.var_kanalzahl, values=list(vk.KANALZAHL_AUSWAHL), width=20,
                          state="readonly")
        ck.pack(side=tk.LEFT, padx=(2, 4))
        ck.bind("<<ComboboxSelected>>", lambda e: self._kanaele_geaendert())
        self.var_panchro = tk.BooleanVar(value=vk.PANCHRO_SCHAERFEN)
        ttk.Checkbutton(leiste, text="Panchro schärfen", variable=self.var_panchro,
                        command=self._kanaele_geaendert).pack(side=tk.LEFT, padx=(0, 2))
        self.var_panchro_kronen = tk.BooleanVar(value=vk.PANCHRO_NUR_KRONEN)
        ttk.Checkbutton(leiste, text="nur Kronen", variable=self.var_panchro_kronen,
                        command=self._kanaele_geaendert).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(leiste, text="Aufnahme öffnen …", command=self.oeffnen).pack(side=tk.LEFT)
        ttk.Button(leiste, text="Ordner öffnen …", command=self.ordner_oeffnen).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(leiste, text="◀", width=3, command=lambda: self.blaettern(-1)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(leiste, text="▶", width=3, command=lambda: self.blaettern(1)).pack(side=tk.LEFT)
        # Bildnummer direkt eingeben: laufende Nummer (z. B. 57) oder Aufnahmename (IMG_0018 bzw. IMG_18) + Enter
        self.var_pos = tk.StringVar(value="")
        self.ent_pos = ttk.Entry(leiste, textvariable=self.var_pos, width=6, justify=tk.RIGHT)
        self.ent_pos.pack(side=tk.LEFT, padx=(8, 0))
        self.ent_pos.bind("<Return>", lambda e: self.springen())
        self.ent_pos.bind("<KP_Enter>", lambda e: self.springen())
        self.ent_pos.bind("<FocusIn>", lambda e: self.ent_pos.after_idle(lambda: self.ent_pos.select_range(0, tk.END)))
        self.ent_pos.bind("<Escape>", lambda e: (self._pos_anzeigen(), self.root.focus_set()))
        self.lbl_anzahl = ttk.Label(leiste, text="/0")
        self.lbl_anzahl.pack(side=tk.LEFT)
        self.lbl_aufn = ttk.Label(leiste, text="keine Aufnahme geladen", width=38)
        self.lbl_aufn.pack(side=tk.LEFT, padx=8)
        ttk.Separator(leiste, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Label(leiste, text="Index:").pack(side=tk.LEFT)
        self.var_index = tk.StringVar(value="NDVI")
        cb = ttk.Combobox(leiste, textvariable=self.var_index, values=list(vk.INDIZES), width=8, state="readonly",
                          height=len(vk.INDIZES))
        self.cb_index = cb
        cb.pack(side=tk.LEFT, padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: (self._schwellen_laden(), self.aktualisieren()))
        ttk.Label(leiste, text="Farbskala:").pack(side=tk.LEFT, padx=(10, 0))
        self.var_skala = tk.StringVar(value="fest (je Index)")
        cs = ttk.Combobox(leiste, textvariable=self.var_skala, width=18, state="readonly",
                          values=["fest (je Index)", "automatisch (P2–P98)"])
        cs.pack(side=tk.LEFT, padx=4)
        cs.bind("<<ComboboxSelected>>", lambda e: self.aktualisieren())
        ttk.Separator(leiste, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(leiste, text="Ganzes Bild", command=self.ganzes_bild).pack(side=tk.LEFT)

        # Zeile 2: Maske, ROIs, Export, Ordnerauswertung
        ttk.Label(leiste2, text="Maske:").pack(side=tk.LEFT)
        self.var_maskenart = tk.StringVar(value=MASKEN[0])
        cm = ttk.Combobox(leiste2, textvariable=self.var_maskenart, values=MASKEN, width=27, state="readonly")
        cm.pack(side=tk.LEFT, padx=4)
        cm.bind("<<ComboboxSelected>>", lambda e: self.aktualisieren())
        ttk.Label(leiste2, text="Schwelle:").pack(side=tk.LEFT)
        self.var_schwelle = tk.DoubleVar(value=0.40)
        sp = ttk.Spinbox(leiste2, from_=-1.0, to=1.0, increment=0.05, width=5, textvariable=self.var_schwelle,
                         format="%.2f", command=self.aktualisieren)
        sp.pack(side=tk.LEFT, padx=4)
        sp.bind("<Return>", lambda e: self.aktualisieren())
        # Maskenverfeinerung (0.8): Grenzen in voller Auflösung am NIR nachziehen, dunkle Lücken entfernen
        self.var_verfeinern = tk.BooleanVar(value=False)
        ttk.Checkbutton(leiste2, text="verfeinern, Lücken < ", variable=self.var_verfeinern,
                        command=self.aktualisieren).pack(side=tk.LEFT, padx=(4, 0))
        self.var_luecke = tk.DoubleVar(value=vk.VERFEIN_LUECKE_ANTEIL * 100)
        sp = ttk.Spinbox(leiste2, from_=5, to=80, increment=5, width=4, textvariable=self.var_luecke,
                         format="%.0f", command=self.aktualisieren)
        sp.pack(side=tk.LEFT)
        sp.bind("<Return>", lambda e: self.aktualisieren())
        ttk.Label(leiste2, text="% NIR").pack(side=tk.LEFT, padx=(2, 4))
        self.var_umriss = tk.BooleanVar(value=True)
        ttk.Checkbutton(leiste2, text="Umriss im RGB", variable=self.var_umriss,
                        command=self.aktualisieren).pack(side=tk.LEFT, padx=4)

        ttk.Separator(leiste2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(leiste2, text="ROIs löschen", command=self.rois_loeschen).pack(side=tk.LEFT)
        self.var_pixelexport = tk.BooleanVar(value=False)
        ttk.Checkbutton(leiste2, text="mit ROI-Pixeln",
                        variable=self.var_pixelexport).pack(side=tk.LEFT, padx=4)
        ttk.Button(leiste2, text="Exportieren", command=self.exportieren).pack(side=tk.LEFT)

        ttk.Separator(leiste2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self.btn_stapel = ttk.Button(leiste2, text="Ordner auswerten …", command=self.ordner_auswerten)
        self.btn_stapel.pack(side=tk.LEFT)
        self.var_raster = tk.BooleanVar(value=False)
        ttk.Checkbutton(leiste2, text="Indexraster speichern", variable=self.var_raster).pack(side=tk.LEFT, padx=4)
        self.fortschritt = ttk.Progressbar(leiste2, length=110, mode="determinate")
        self.fortschritt.pack(side=tk.LEFT, padx=4)
        self.btn_abbruch = ttk.Button(leiste2, text="Abbrechen", command=self.abbruch.set, state=tk.DISABLED)
        self.btn_abbruch.pack(side=tk.LEFT)

        # Zeile 3: Zeichenmodus + Baummodell
        ttk.Label(leiste3, text="Zeichnen:").pack(side=tk.LEFT)
        self.var_zeichnen = tk.StringVar(value="aus")
        for wert, text in (("aus", "aus / Pixelabfrage"), ("roi", "ROI (Rechteck)"),
                           ("baum", "Beispiel: Baum"), ("kein", "Beispiel: kein Baum"),
                           ("ref_v", "Referenz: vital"), ("ref_g", "Referenz: geschädigt"),
                           ("k_teilen", "Krone teilen"), ("k_verbinden", "Kronen verbinden")):
            ttk.Radiobutton(leiste3, text=text, value=wert, variable=self.var_zeichnen,
                            command=self._zeichenmodus).pack(side=tk.LEFT, padx=3)
        ttk.Button(leiste3, text="↶ Kronenkorrektur", command=self.kronenkorrektur_zurueck).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste3, text="Korrekturen im Bild löschen …",
                   command=self.kronenkorrekturen_loeschen).pack(side=tk.LEFT, padx=2)
        # Baummodell in eigener Zeile (seit 0.13 ist die Zeichenleiste zu breit für beides)
        leiste3b = ttk.Frame(self.root, padding=(4, 0, 4, 4))
        leiste3b.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(leiste3b, text="Baummodell:").pack(side=tk.LEFT)
        ttk.Button(leiste3b, text="Modell berechnen", command=self.trainieren).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste3b, text="Letzte Fläche entfernen", command=self.letzte_flaeche_entfernen).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste3b, text="Modell speichern …", command=self.modell_speichern).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste3b, text="Modell laden …", command=self.modell_laden).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste3b, text="Neues Modell", command=self.modell_neu).pack(side=tk.LEFT, padx=2)
        self.lbl_modell = ttk.Label(leiste3b, text="", style="Hinweis.TLabel")
        self.lbl_modell.pack(side=tk.LEFT, padx=8)
        ttk.Separator(leiste3b, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, before=self.lbl_modell)
        ttk.Label(leiste3b, text="Anzeige:").pack(side=tk.LEFT, before=self.lbl_modell)

        # Zeile 4: Schwellwerte (gestresst / Übergang / vital) und Bewertung je Baumobjekt
        leiste4 = ttk.Frame(self.root, padding=(4, 0, 4, 4))
        leiste4.pack(side=tk.TOP, fill=tk.X)
        self.var_schw_an = tk.BooleanVar(value=False)
        self.chk_schw = ttk.Checkbutton(leiste4, text="Schwellwerte für NDVI:", variable=self.var_schw_an,
                                        command=self._schwellen_umschalten)
        self.chk_schw.pack(side=tk.LEFT)
        self.var_s_gestresst = tk.DoubleVar(value=0.0)
        self.var_s_vital = tk.DoubleVar(value=0.0)
        self.var_s_anteil = tk.DoubleVar(value=10.0)
        self.var_s_kronen = tk.IntVar(value=0)
        self.spins_schw = []
        for text, var, von, bis, schritt, fmt, breite in (
                ("gestresst <", self.var_s_gestresst, -1.5, 1.5, 0.01, "%.2f", 6),
                ("vital ≥", self.var_s_vital, -1.5, 1.5, 0.01, "%.2f", 6),
                ("Baum gestresst ab", self.var_s_anteil, 0, 100, 1, "%.0f", 4)):
            ttk.Label(leiste4, text=text).pack(side=tk.LEFT, padx=(8, 2))
            sp = ttk.Spinbox(leiste4, from_=von, to=bis, increment=schritt, width=breite, textvariable=var, format=fmt,
                             command=self._schwellen_uebernehmen)
            sp.pack(side=tk.LEFT)
            sp.bind("<Return>", lambda e: self._schwellen_uebernehmen())
            sp.bind("<FocusOut>", lambda e: self._schwellen_uebernehmen())
            self.spins_schw.append(sp)
        ttk.Label(leiste4, text="% · Baumregel:").pack(side=tk.LEFT, padx=(2, 2))
        self.var_baumregel = tk.StringVar(value=vk.BAUMREGELN["anteil"])
        cb_regel = ttk.Combobox(leiste4, textvariable=self.var_baumregel, values=list(vk.BAUMREGELN.values()),
                                state="readonly", width=22)
        cb_regel.pack(side=tk.LEFT, padx=(0, 8))
        cb_regel.bind("<<ComboboxSelected>>", lambda e: self._baumregel_alle())
        ttk.Label(leiste4, text="Kronen trennen, Abstand (px, 0 = aus):").pack(side=tk.LEFT)
        sp = ttk.Spinbox(leiste4, from_=0, to=1000, increment=10, width=5, textvariable=self.var_s_kronen,
                         command=self._schwellen_uebernehmen)
        sp.pack(side=tk.LEFT, padx=2)
        sp.bind("<Return>", lambda e: self._schwellen_uebernehmen())
        sp.bind("<FocusOut>", lambda e: self._schwellen_uebernehmen())
        self.spins_schw.append(sp)
        self.var_kronen_nir = tk.BooleanVar(value=True)
        ttk.Checkbutton(leiste4, text="an NIR ausrichten", variable=self.var_kronen_nir,
                        command=self._schwellen_uebernehmen).pack(side=tk.LEFT, padx=(2, 0))
        self.var_kronen_raster = tk.BooleanVar(value=False)
        ttk.Checkbutton(leiste4, text="Pflanzraster", variable=self.var_kronen_raster,
                        command=self._schwellen_uebernehmen).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(leiste4, text="Startwerte P10/P30", command=self._schwellen_startwerte).pack(side=tk.LEFT, padx=6)
        self.var_klassenkarte = tk.BooleanVar(value=True)
        ttk.Checkbutton(leiste3b, text="Klassenkarte", variable=self.var_klassenkarte,
                        command=self.aktualisieren).pack(side=tk.LEFT, padx=4, before=self.lbl_modell)
        self.var_baumfarben = tk.BooleanVar(value=True)
        ttk.Checkbutton(leiste3b, text="Bäume einfärben", variable=self.var_baumfarben,
                        command=self.aktualisieren).pack(side=tk.LEFT, padx=4, before=self.lbl_modell)
        self.var_nummern = tk.BooleanVar(value=True)
        ttk.Checkbutton(leiste3b, text="Baumnummern", variable=self.var_nummern,
                        command=self.aktualisieren).pack(side=tk.LEFT, padx=4, before=self.lbl_modell)

        # Zeile 5: Referenzflächen -> Schwellen
        leiste5 = ttk.Frame(self.root, padding=(4, 0, 4, 4))
        leiste5.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(leiste5, text="Referenzbäume:").pack(side=tk.LEFT)
        ttk.Button(leiste5, text="Schwellen aus Referenzen …", command=self.referenzen_auswerten).pack(side=tk.LEFT, padx=4)
        ttk.Button(leiste5, text="Kanalanalyse …", command=self.kanalanalyse).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste5, text="Letzte Referenz entfernen", command=self.letzte_referenz_entfernen).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste5, text="Referenzen speichern …", command=self.referenzen_speichern).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste5, text="Referenzen laden …", command=self.referenzen_laden).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste5, text="Referenzen hinzuladen …", command=self.referenzen_hinzuladen).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste5, text="Ableitung hinterlegen …",
                   command=self.ableitung_hinterlegen).pack(side=tk.LEFT, padx=(8, 2))
        self.var_einblenden = tk.BooleanVar(value=True)
        ttk.Checkbutton(leiste5, text="einblenden", variable=self.var_einblenden,
                        command=self._einblenden_berechnen).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(leiste5, text="An Prüfbäumen prüfen …",
                   command=self.schwellen_pruefen).pack(side=tk.LEFT, padx=(8, 2))
        self.lbl_ref = ttk.Label(leiste5, text="", style="Hinweis.TLabel", wraplength=360)
        self.lbl_ref.pack(side=tk.LEFT, padx=8)

        unten = ttk.Frame(self.root)
        unten.pack(side=tk.BOTTOM, fill=tk.X)
        self.var_dunkel = tk.BooleanVar(value=bool(lade_einstellungen().get("darkmode", False)))
        ttk.Checkbutton(unten, text="Darkmode", variable=self.var_dunkel,
                        command=self._thema_umschalten).pack(side=tk.RIGHT, padx=6)
        ttk.Button(unten, text="Alles zurücksetzen …", command=self.alles_zuruecksetzen).pack(side=tk.RIGHT, padx=4)
        self.status = ttk.Label(unten, text="Bereit. „Aufnahme öffnen“ (einzelne Datei) oder „Ordner öffnen“ "
                                            "(auch übergeordnete Ordner wie 0029SET). Mausrad = zoomen, rechte "
                                            "Maustaste ziehen = verschieben.", relief=tk.SUNKEN,
                                anchor="w", padding=3)
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)

        haupt = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        haupt.pack(fill=tk.BOTH, expand=True)

        links = ttk.Frame(haupt)
        haupt.add(links, weight=4)
        self.fig = Figure(figsize=(8, 6), layout="constrained")
        gs = self.fig.add_gridspec(2, 2, height_ratios=[3, 1.2])
        self.ax_rgb = self.fig.add_subplot(gs[0, 0])
        self.ax_idx = self.fig.add_subplot(gs[0, 1], sharex=self.ax_rgb, sharey=self.ax_rgb)
        self.ax_hist = self.fig.add_subplot(gs[1, :])
        for ax in (self.ax_rgb, self.ax_idx):
            ax.set_xticks([]); ax.set_yticks([])
        self.canvas = FigureCanvasTkAgg(self.fig, master=links)
        self.toolbar = NavigationToolbar2Tk(self.canvas, links, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("button_press_event", self._klick)
        self.canvas.mpl_connect("scroll_event", self._mausrad)
        self.canvas.mpl_connect("button_press_event", self._pan_start)
        self.canvas.mpl_connect("motion_notify_event", self._pan_bewegen)
        self.canvas.mpl_connect("button_release_event", self._pan_ende)
        self.canvas.mpl_connect("motion_notify_event", self._teilen_bewegen)       # ab 0.18: Schnittlinie
        self.canvas.mpl_connect("button_release_event", self._teilen_los)
        self._pan = None
        # Schwellenlinien im Histogramm verschieben
        self.canvas.mpl_connect("button_press_event", self._linie_druck)
        self.canvas.mpl_connect("motion_notify_event", self._linie_bewegen)
        self.canvas.mpl_connect("button_release_event", self._linie_los)
        self.linien = {}            # "gestresst"/"vital" -> Line2D
        self._legende_texte = {}    # "gestresst"/"vital" -> Legendentext im Histogramm
        self._schwellen_eingabe = None   # Eingabefeld über dem Legendentext
        self._linie_zug = None      # (welche, Startwert gestresst, Startwert vital)
        rahmen = dict(edgecolor="black", fill=False, linewidth=1.5)
        self.rechteck_sel = [RectangleSelector(ax, self._roi_fertig, useblit=True, button=[1], minspanx=3,
                                               minspany=3, spancoords="pixels", interactive=False, props=rahmen)
                             for ax in (self.ax_rgb, self.ax_idx)]
        self.lasso_sel = [LassoSelector(ax, self._lasso_fertig, useblit=True, button=[1],
                                        props=dict(color="white", linewidth=1.5))
                          for ax in (self.ax_rgb, self.ax_idx)]
        for s in self.rechteck_sel + self.lasso_sel:
            s.set_active(False)
        self.im_rgb = self.im_idx = self.cbar = None

        rechts = ttk.Frame(haupt, padding=4)
        haupt.add(rechts, weight=2)
        # ab 0.18: Bilder + Histogramm beim Start auf 2/3 der Breite (Trennlinie bleibt verschiebbar)
        self._haupt = haupt
        haupt.bind("<Map>", lambda e: self.root.after(200, self._aufteilung_setzen), add="+")
        self.lbl_formel = ttk.Label(rechts, text="", font=("Segoe UI", 11, "bold"), wraplength=520)
        self.lbl_formel.pack(anchor="w")
        self.lbl_quelle = ttk.Label(rechts, text="", wraplength=520, style="Hinweis.TLabel")
        self.lbl_quelle.pack(anchor="w", pady=(0, 6))
        spalten = ["Region"] + vk.STAT_SPALTEN
        tabrahmen = ttk.Frame(rechts)
        tabrahmen.pack(fill=tk.X)
        self.tab = ttk.Treeview(tabrahmen, columns=spalten, show="headings", height=10)
        for s in spalten:
            self.tab.heading(s, text=s)
            self.tab.column(s, width=145 if s == "Region" else 70, minwidth=50, stretch=False,
                            anchor="w" if s == "Region" else "e")
        xs = ttk.Scrollbar(tabrahmen, orient=tk.HORIZONTAL, command=self.tab.xview)
        self.tab.configure(xscrollcommand=xs.set)
        self.tab.pack(fill=tk.X)
        xs.pack(fill=tk.X)
        self.lbl_klassen = ttk.Label(rechts, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_klassen.pack(anchor="w", pady=(8, 0))
        sp_kl = ["Region", "Pixel", "% gestresst", "% Übergang", "% vital"]
        self.tab_kl = ttk.Treeview(rechts, columns=sp_kl, show="headings", height=5)
        for c in sp_kl:
            self.tab_kl.heading(c, text=c)
            self.tab_kl.column(c, width=145 if c == "Region" else 85, anchor="w" if c == "Region" else "e", stretch=False)
        self.tab_kl.pack(fill=tk.X)
        self.lbl_objekte = ttk.Label(rechts, text="", wraplength=520)
        self.lbl_objekte.pack(anchor="w")
        self.lbl_literatur = ttk.Label(rechts, text="", wraplength=520, style="Hinweis.TLabel")
        self.lbl_literatur.pack(anchor="w", pady=(4, 0))
        ttk.Label(rechts, text="Pixelabfrage (Klick ins Bild, Zeichnen „aus“):",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 0))
        self.txt_pixel = tk.Text(rechts, height=9, width=60, font=("Consolas", 10), relief=tk.FLAT,
                                 background=THEMEN[False]["pixel_feld"])
        self.txt_pixel.pack(fill=tk.X)
        ttk.Label(rechts, text="Datenquelle / Maske:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 0))
        self.lbl_daten = ttk.Label(rechts, text="–", wraplength=520)
        self.lbl_daten.pack(anchor="w")
        self.lbl_maskeninfo = ttk.Label(rechts, text="", wraplength=520)
        self.lbl_maskeninfo.pack(anchor="w", pady=(4, 0))
        ttk.Label(rechts, wraplength=520, style="Hinweis.TLabel", text=(
            "\nZoomen: Mausrad (auch beim Einzeichnen), Verschieben: rechte Maustaste gedrückt halten, "
            "„Ganzes Bild“ setzt die Ansicht zurück.\n"
            "Grau in der Indexkarte = ungültig bzw. außerhalb der Maske. Baummodell: „Beispiel: Baum“ bzw. "
            "„kein Baum“ wählen und Flächen frei umfahren (linke Maustaste gedrückt halten) – im RGB- oder "
            "Indexbild, gern in mehreren Aufnahmen. Für „kein Baum“ alles einzeichnen, was vorkommt "
            "(Gras, Boden, Schatten, Wege). Danach „Modell berechnen“ und Maske „Bäume (Modell)“ wählen.")).pack(anchor="w")

    # ------------------------------------------------------------------ Laden
    def oeffnen(self):
        pfad = filedialog.askopenfilename(title="Aufnahme wählen (beliebiger Kanal oder Reflektanzbild)",
                                          initialdir=START_ORDNER, filetypes=[("TIFF", "*.tif"), ("Alle", "*.*")])
        if not pfad:
            return
        try:
            ordner, name = vk._ordner_und_name(pfad)
        except ValueError as e:
            messagebox.showerror("Falsche Datei", str(e))
            return
        liste = [(ordner, n) for n in vk.liste_aufnahmen(ordner)]
        if name not in [n for _, n in liste]:
            messagebox.showinfo("Aufnahme passt nicht zur Kanalzahl", self._kanal_hinweis(ordner, name))
            return
        self.wurzel, self.liste = ordner, liste
        self.pos = next((i for i, (_, n) in enumerate(self.liste) if n == name), 0)
        self._lade()

    def _kanal_hinweis(self, wurzel, name=None):
        """Erklärt, warum (für die gewählte Kanalzahl) keine Aufnahmen gefunden wurden."""
        ueb = vk.kanal_uebersicht(wurzel)
        gefunden = ", ".join(f"{n} Aufnahme(n) mit {k} Dateien" for k, n in sorted(ueb.items())) or "keine Rohbilder"
        return ((f"{name} ist mit der gewählten Kanalzahl nicht vollständig.\n\n" if name else "")
                + f"Gewählte Kanalzahl: {self.var_kanalzahl.get()}\nGefunden: {gefunden}.\n\n"
                "Bitte oben unter „Kanäle“ die passende Zahl wählen (6 = 5 Spektralkanäle + Panchro).")

    def _kanaele_geaendert(self):
        """Kanalzahl / Panchro geändert: Einstellung setzen und die aktuelle Liste neu einlesen."""
        vk.setze_kanalzahl(vk.KANALZAHL_AUSWAHL[self.var_kanalzahl.get()])
        vk.setze_panchro_schaerfen(self.var_panchro.get())
        vk.setze_panchro_nur_kronen(self.var_panchro_kronen.get())
        if self.stapel_laeuft:
            self._setze_status("Änderung gilt nach Ende der laufenden Auswertung.")
            return
        if not self.liste:
            self._setze_status(f"Kanäle: {self.var_kanalzahl.get()}, Panchro schärfen: "
                               f"{'ja' if self.var_panchro.get() else 'nein'} – gilt beim nächsten Öffnen.")
            return
        alt = self.liste[self.pos] if 0 <= self.pos < len(self.liste) else None
        liste = vk.liste_aufnahmen_rekursiv(self.wurzel) if self.wurzel else []
        if not liste:
            messagebox.showinfo("Keine Aufnahmen", self._kanal_hinweis(self.wurzel))
            return
        self.liste = liste
        self.pos = liste.index(alt) if alt in liste else 0
        self._lade()

    def ordner_oeffnen(self):
        wurzel = filedialog.askdirectory(title="Ordner wählen (auch übergeordnet, z. B. 0029SET oder ein Flugtag)",
                                         initialdir=START_ORDNER, mustexist=True)
        if not wurzel:
            return
        wurzel = os.path.normpath(wurzel)
        self._setze_status(f"Suche Aufnahmen in {wurzel} …")
        self.root.update_idletasks()
        liste = vk.liste_aufnahmen_rekursiv(wurzel)
        if not liste:
            messagebox.showinfo("Keine Aufnahmen", f"In\n{wurzel}\nund seinen Unterordnern wurden keine passenden "
                                                   "Aufnahmen gefunden.\n\n" + self._kanal_hinweis(wurzel))
            return
        self.wurzel, self.liste, self.pos = wurzel, liste, 0
        self._setze_status(f"{len(liste)} Aufnahmen in {len({o for o, _ in liste})} Ordner(n) gefunden.")
        self._lade()

    def blaettern(self, schritt):
        if not self.liste:
            return
        self.pos = (self.pos + schritt) % len(self.liste)
        self._lade()

    def _pos_anzeigen(self):
        if self.liste:
            self.var_pos.set(str(self.pos + 1))
            self.lbl_anzahl.config(text=f"/{len(self.liste)}")
        else:
            self.var_pos.set("")
            self.lbl_anzahl.config(text="/0")

    def springen(self):
        """Springt zur eingegebenen Bildnummer (1 … N) oder zu einer Aufnahme per Name (IMG_0018 bzw. IMG_18).
        Eine reine Zahl ist die laufende Nummer; Namen werden zuerst im aktuellen Ordner gesucht."""
        text = self.var_pos.get().strip()
        if not self.liste or not text:
            self._pos_anzeigen()
            return
        ziel = None
        if text.isdigit() and not text.startswith("0"):
            n = int(text)
            if 1 <= n <= len(self.liste):
                ziel = n - 1
            else:
                self._setze_status(f"Bildnummer {n} gibt es nicht – gültig ist 1 bis {len(self.liste)}.")
        else:
            name = text.upper()
            if name.replace("IMG_", "").isdigit():
                name = f"IMG_{int(name.replace('IMG_', '')):04d}"
            treffer = [i for i, (_, n) in enumerate(self.liste) if n.upper() == name]
            if treffer:
                aktueller_ordner = self.liste[self.pos][0] if self.pos >= 0 else None
                ziel = next((i for i in treffer if self.liste[i][0] == aktueller_ordner), treffer[0])
            else:
                self._setze_status(f"Keine Aufnahme „{text}“ in der aktuellen Liste.")
        if ziel is None:
            self._pos_anzeigen()
            return
        self.root.focus_set()
        if ziel != self.pos:
            self.pos = ziel
            self._lade()
        else:
            self._pos_anzeigen()

    def _lade(self):
        ordner, name = self.liste[self.pos]
        rel = os.path.relpath(ordner, self.wurzel) if self.wurzel else ""
        anzeige = name if rel in ("", ".") else os.path.join(rel, name)
        self.lbl_aufn.config(text=anzeige + (" · Panchro" if self.var_panchro.get() else ""))
        self._pos_anzeigen()
        self._setze_status(f"Lade {name} …")
        self.root.config(cursor="watch")

        def arbeit():
            try:
                a = vk.lade_aufnahme(ordner, name, fortschritt=lambda t: self.q.put(("status", t)))
                self.q.put(("geladen", a))
            except Exception as e:
                traceback.print_exc()
                self.q.put(("fehler", f"{name}:\n\n{e}"))
        threading.Thread(target=arbeit, daemon=True).start()

    # ------------------------------------------------------------------ Sitzung merken (Version 0.15)
    # Beim Schließen wird der Arbeitsstand gespeichert und beim nächsten Start wiederhergestellt: Ordner und Aufnahme,
    # Einstellungen der Bedienelemente, Schwellwerte je Index, Baummodell und Referenzflächen (als Sicherungskopie im
    # Sitzungsordner, damit auch ungespeicherte Änderungen erhalten bleiben). Kronenkorrekturen liegen ohnehin je
    # Aufnahmeordner in VI_Auswertung\Kronenkorrekturen.json.
    SITZUNG_VARS = ("kanalzahl", "panchro", "panchro_kronen", "index", "skala", "maskenart", "schwelle",
                    "verfeinern", "luecke", "umriss", "pixelexport", "raster", "s_anteil", "s_kronen", "kronen_nir",
                    "kronen_raster", "baumregel", "klassenkarte", "baumfarben", "nummern")

    def _sitzung_speichern(self):
        d = {"software": vk.VERSION, "gespeichert": vk._dt.datetime.now().isoformat(timespec="seconds"),
             "vars": {}, "wurzel": self.wurzel, "aufnahme": None,
             "schwellen": {i: dataclasses.asdict(s) for i, s in self.schwellen_werte.items()},
             "schwellen_aktiv": sorted(self.schwellen_aktiv),
             "modellpfad": self.modellpfad, "referenzpfad": self.referenzpfad,
             "hinterlegt_pfade": self.hinterlegt_pfade,
             "modell_sicherung": False, "referenzen_sicherung": False}
        for n in self.SITZUNG_VARS:
            try:
                d["vars"][n] = getattr(self, "var_" + n).get()
            except (tk.TclError, AttributeError):
                pass
        if self.liste and 0 <= self.pos < len(self.liste):
            d["aufnahme"] = list(self.liste[self.pos])
        os.makedirs(SITZUNG_ORDNER, exist_ok=True)
        try:
            if self.modell.flaechen:
                self.modell.speichern(os.path.join(SITZUNG_ORDNER, "Baummodell_Sitzung.joblib"))
                d["modell_sicherung"] = True
            if self.referenzen.flaechen:
                self.referenzen.speichern(os.path.join(SITZUNG_ORDNER, "Referenzen_Sitzung.joblib"))
                d["referenzen_sicherung"] = True
        except Exception:
            traceback.print_exc()
        tmp = SITZUNG_DATEI + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, SITZUNG_DATEI)

    def _sitzung_wiederherstellen(self):
        try:
            with open(SITZUNG_DATEI, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        fehler = []
        for n, w in d.get("vars", {}).items():
            try:
                getattr(self, "var_" + n).set(w)
            except (tk.TclError, AttributeError):
                pass
        vk.setze_kanalzahl(vk.KANALZAHL_AUSWAHL.get(self.var_kanalzahl.get()))
        vk.setze_panchro_schaerfen(self.var_panchro.get())
        vk.setze_panchro_nur_kronen(self.var_panchro_kronen.get())
        for i, s in d.get("schwellen", {}).items():
            try:
                self.schwellen_werte[i] = vk.Schwellen(**s)
            except (TypeError, ValueError):
                fehler.append(f"Schwellen {i}")
        self.schwellen_aktiv = {i for i in d.get("schwellen_aktiv", []) if i in self.schwellen_werte}
        if d.get("modell_sicherung"):
            try:
                self.modell = vk.Baummodell.laden(os.path.join(SITZUNG_ORDNER, "Baummodell_Sitzung.joblib"))
                self.modellpfad = d.get("modellpfad") or ""
                self.modell_version += 1
            except Exception as e:
                fehler.append(f"Baummodell ({e})")
        if d.get("referenzen_sicherung"):
            try:
                self.referenzen = vk.Referenzen.laden(os.path.join(SITZUNG_ORDNER, "Referenzen_Sitzung.joblib"))
                self.referenzpfad = d.get("referenzpfad") or ""
            except Exception as e:
                fehler.append(f"Referenzen ({e})")
        if d.get("hinterlegt_pfade"):
            try:
                self._hinterlegen(d["hinterlegt_pfade"])
            except Exception as e:
                fehler.append(f"hinterlegte Ableitungsbäume ({e})")
        if self.var_maskenart.get() == MASKEN[2] and self.modell.rf is None:
            self.var_maskenart.set(MASKEN[0])
        self._modell_anzeige()
        self._referenz_anzeige()
        self._schwellen_laden()
        wurzel, aufn = d.get("wurzel"), d.get("aufnahme")
        text = f"Sitzung vom {d.get('gespeichert', '?').replace('T', ' ')} wiederhergestellt"
        if wurzel and os.path.isdir(wurzel):
            self._setze_status(f"{text} – suche Aufnahmen in {wurzel} …")
            self.root.update_idletasks()
            liste = vk.liste_aufnahmen_rekursiv(wurzel)
            if liste:
                self.wurzel, self.liste = wurzel, liste
                ziel = tuple(aufn) if aufn else None
                self.pos = liste.index(ziel) if ziel in liste else 0
                self._lade()
                text += f" ({os.path.basename(wurzel)}, {liste[self.pos][1]})"
        elif wurzel:
            fehler.append(f"Ordner nicht gefunden: {wurzel}")
        text += (" – nicht wiederhergestellt: " + "; ".join(fehler) if fehler else "") + \
            ". Neu beginnen: „Alles zurücksetzen …“."
        self._setze_status(text)
        if self.aufn is None and self.liste:
            self._sitzung_text = text

    def _schliessen(self):
        if self.stapel_laeuft and not messagebox.askyesno(
                "Beenden", "Es läuft noch eine Auswertung. Trotzdem beenden? (Die Auswertung wird abgebrochen.)"):
            return
        self.abbruch.set()
        try:
            self._sitzung_speichern()
        except Exception as e:
            traceback.print_exc()
            if not messagebox.askyesno("Beenden", f"Der Arbeitsstand konnte nicht gespeichert werden:\n{e}\n\n"
                                                  "Trotzdem beenden?"):
                return
        self._beenden_vorbereiten()
        self.root.destroy()

    def _beenden_vorbereiten(self):
        self._beendet = True
        try:
            self.root.after_cancel(self._after_id)
        except (tk.TclError, ValueError, AttributeError):
            pass

    def alles_zuruecksetzen(self):
        if self.stapel_laeuft:
            messagebox.showinfo("Alles zurücksetzen", "Es läuft gerade eine Auswertung. Bitte warten oder abbrechen.")
            return
        if not messagebox.askyesno("Alles zurücksetzen", (
                "Die Software in den Ausgangszustand versetzen?\n\n"
                "Verworfen werden: geöffneter Ordner, alle Einstellungen, Schwellwerte, das aktuelle Baummodell und "
                "die aktuellen Referenzflächen (soweit nicht selbst gespeichert) sowie der gemerkte Arbeitsstand.\n\n"
                "Erhalten bleiben: selbst gespeicherte Modell- und Referenzdateien, Exporte, Kronenkorrekturen "
                "(je Aufnahmeordner) und der Darkmode.")):
            return
        for p in (SITZUNG_DATEI, os.path.join(SITZUNG_ORDNER, "Baummodell_Sitzung.joblib"),
                  os.path.join(SITZUNG_ORDNER, "Baummodell_Sitzung_Info.json"),
                  os.path.join(SITZUNG_ORDNER, "Referenzen_Sitzung.joblib")):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
        vk.setze_kanalzahl(None)
        vk.setze_panchro_schaerfen(False)
        vk.setze_panchro_nur_kronen(True)
        self._beenden_vorbereiten()
        root = self.root
        for w in root.winfo_children():
            w.destroy()
        neu = App(root, wiederherstellen=False)
        neu._setze_status("Alles zurückgesetzt. „Aufnahme öffnen“ oder „Ordner öffnen“.")

    def _pruefe_queue(self):
        if self._beendet:          # Fenster geschlossen bzw. Oberfläche neu aufgebaut
            return
        try:
            while True:
                art, inhalt = self.q.get_nowait()
                if art == "status":
                    self._setze_status(inhalt)
                elif art == "geladen":
                    self.root.config(cursor="")
                    self._zeige_aufnahme(inhalt)
                    if self._sitzung_text:              # Meldung der Wiederherstellung nach dem Laden zeigen
                        self._setze_status(self._sitzung_text)
                        self._sitzung_text = None
                elif art == "fehler":
                    self.root.config(cursor="")
                    self._setze_status("Fehler beim Laden.")
                    messagebox.showerror("Aufnahme kann nicht geladen werden", inhalt)
                elif art == "stapel_fortschritt":
                    i, n, text = inhalt
                    self.fortschritt.config(maximum=n, value=i)
                    self._setze_status(f"Ordnerauswertung: {i}/{n}  {text}")
                elif art == "stapel_fertig":
                    self._stapel_ende(*inhalt)
                elif art == "pruef_fortschritt":
                    i, n, text = inhalt
                    self.fortschritt.config(maximum=max(n, 1), value=i)
                    self._setze_status(f"Prüfung an Prüfbäumen: Bild {i}/{n}  {text}")
                elif art == "pruef_fertig":
                    self._pruefung_ende(*inhalt)
                elif art == "kanal_fortschritt":
                    i, n, text = inhalt
                    self.fortschritt.config(maximum=max(n, 1), value=i)
                    self._setze_status(f"Kanalwerte der Referenzbäume ergänzen: Bild {i}/{n}  {text}")
                elif art == "baumschw_fortschritt":
                    i, n, text = inhalt
                    self.fortschritt.config(maximum=max(n, 1), value=i)
                    self._setze_status(f"Schwellen aus Baummedianen: Bild {i}/{n}  {text}")
                elif art == "baumschw_fertig":
                    self._baum_schwellen_ende(*inhalt)
                elif art == "kanal_fertig":
                    self._kanalanalyse_ende(*inhalt)
                elif art == "aufwand_fortschritt":
                    i, n, text = inhalt
                    self.fortschritt.config(maximum=max(n, 1), value=i)
                    self._setze_status(f"Rechenaufwand messen: Schritt {i}/{n}  {text}")
                elif art == "aufwand_fertig":
                    self._aufwand_ende(*inhalt)
                elif art == "einblenden_fertig":
                    self._einblenden_ende(*inhalt)
                elif art == "dopplung_fortschritt":
                    i, n, text = inhalt
                    self.fortschritt.config(maximum=max(n, 1), value=i)
                    self._setze_status(f"Prüfbäume mit Ableitungsbäumen abgleichen: Bild {i}/{n}  {text}")
                elif art == "dopplung_fertig":
                    self._dopplung_ende(*inhalt)
        except queue.Empty:
            pass
        self._after_id = self.root.after(100, self._pruefe_queue)

    def _aufteilung_setzen(self, anteil=2 / 3):
        """Trennlinie zwischen Bildbereich und rechter Spalte einmalig beim Start auf den Anteil `anteil` der Breite setzen."""
        if getattr(self, "_aufteilung_gesetzt", False):
            return
        self.root.update_idletasks()
        b = self._haupt.winfo_width()
        if b < 200:                                   # Fenster noch nicht aufgebaut
            self.root.after(200, self._aufteilung_setzen)
            return
        self._haupt.sashpos(0, int(b * anteil))
        self._aufteilung_gesetzt = True

    def _zeige_aufnahme(self, a):
        self.aufn = a
        self.kronen_korr = vk.kronenkorrekturen_fuer(a)
        self._verbinden_start = None
        self.objekt_labels = None
        self.merkmale = None
        self._masken_schluessel = None
        self.rois_loeschen(neu_zeichnen=False)
        h, w = a.stapel.shape[1:]
        self.ax_rgb.clear(); self.ax_idx.clear()
        self.training_artists, self.masken_artists = [], []
        self.im_rgb = self.ax_rgb.imshow(vk.rgb_anzeige(a.kronenstapel, a.kanalindex), interpolation="nearest")
        self.ax_rgb.set_title(f"{a.name} – {vk.rgb_art(a.kanalindex)[1]}" + (
            (" (Panchro: nur Kronen)" if a.maskenstapel is not None else " (Panchro-geschärft)") if a.geschaerft
            else " (nur Anzeige)"))
        verfuegbar = [i for i in vk.INDIZES if vk.index_verfuegbar(a.kanalindex, i)]
        self.cb_index.config(values=verfuegbar)
        hinweis = []
        if self.var_index.get() not in verfuegbar:
            hinweis.append(f"{self.var_index.get()} braucht {', '.join(vk.fehlende_kanaele(a.kanalindex, self.var_index.get()))}"
                           f" – auf {verfuegbar[0]} gewechselt")
            self.var_index.set(verfuegbar[0])
            self._schwellen_laden()
        if a.meta.get("fehlende_kanaele"):
            hinweis.append(f"Kanal fehlt: {', '.join(a.meta['fehlende_kanaele'])} – nur {len(verfuegbar)} von "
                           f"{len(vk.INDIZES)} Indizes berechenbar")
        if self.var_panchro.get() and not a.geschaerft:
            hinweis.append("kein Panchro-Kanal in dieser Aufnahme – ungeschärft geladen")
        if a.geschaerft:
            p = a.meta["panchro"]
            hinweis.append(f"mit Panchro geschärft (Faktor {p['faktor']}, {p['feinausrichtung']})"
                           + ("; Indizes aus den Original-Kanälen, Panchro nur für Maske/Kronen"
                              if a.maskenstapel is not None else "; Indizes aus den geschärften Kanälen"))
        self._kanal_hinweise = "; ".join(hinweis)
        cmap = matplotlib.colormaps["RdYlGn"].copy()
        cmap.set_bad("#bdbdbd")
        self.im_idx = self.ax_idx.imshow(np.zeros((h, w)), cmap=cmap, interpolation="nearest")
        if self.cbar is None:
            self.cbar = self.fig.colorbar(self.im_idx, ax=self.ax_idx, shrink=0.85)
        else:
            self.cbar.update_normal(self.im_idx)
        for ax in (self.ax_rgb, self.ax_idx):
            ax.set_xticks([]); ax.set_yticks([])
        self.toolbar.update()                       # Zoom-Historie zurücksetzen
        self.lbl_daten.config(text=f"{a.quelle}\nOrdner: {a.ordner}\nGröße: {w} × {h} px"
                                   + (f"\nHinweis: {self._kanal_hinweise}" if self._kanal_hinweise else ""))
        self._setze_status(f"{a.name} geladen.")
        self._einblend["schluessel"] = None
        self._zeichne_trainingsflaechen()
        self.aktualisieren()
        self._einblenden_berechnen()
        if self._kanal_hinweise:
            self._setze_status(f"{a.name} geladen – {self._kanal_hinweise}.")

    # ------------------------------------------------------------------ Masken
    def _schwelle(self):
        try:
            return round(float(self.var_schwelle.get()), 3)
        except (tk.TclError, ValueError):
            return 0.4

    def _verfeinerung(self):
        """(an/aus, Lückenanteil 0..1) der Maskenverfeinerung."""
        try:
            anteil = min(max(round(float(self.var_luecke.get()), 1), 5.0), 80.0) / 100
        except (tk.TclError, ValueError):
            anteil = vk.VERFEIN_LUECKE_ANTEIL
        return bool(self.var_verfeinern.get()), anteil

    def _vorgabe(self, fuer_ordner=False):
        """Maskenvorgabe aus der aktuellen Einstellung (None = keine Maske)."""
        v = self._vorgabe_ohne_verfeinerung(fuer_ordner)
        if v is not None:
            v.verfeinern, v.luecke_anteil = self._verfeinerung()
        return v

    def _vorgabe_ohne_verfeinerung(self, fuer_ordner=False):
        art = self.var_maskenart.get()
        if art.startswith("Vegetation"):
            return vk.Maskenvorgabe("Vegetation", schwelle=self._schwelle())
        if art.startswith("Bäume"):
            if self.modell.rf is None:
                if fuer_ordner or self.aufn is not None:
                    messagebox.showwarning("Baummaske", "Das Baummodell ist noch nicht berechnet.\n\n"
                                           "Zuerst Beispielflächen einzeichnen und „Modell berechnen“ klicken "
                                           "oder ein gespeichertes Modell laden.")
                self.var_maskenart.set(MASKEN[0])
                return None
            return vk.Maskenvorgabe("Baum", modell=self.modell, modellpfad=self.modellpfad)
        return None

    def _merkmale(self):
        if self.merkmale is None:
            self.merkmale = vk.baum_merkmale(self.aufn.kronenstapel, self.aufn.kanalindex)
        return self.merkmale

    def _berechne_maske(self, vorgabe):
        if vorgabe is None:
            return None
        schluessel = (id(self.aufn), vorgabe.art, vorgabe.schwelle if vorgabe.art == "Vegetation" else self.modell_version,
                      vorgabe.verfeinern, vorgabe.luecke_anteil if vorgabe.verfeinern else None)
        if schluessel != self._masken_schluessel:
            self.verfein_info = {}
            if vorgabe.art == "Baum":
                if self.modell.flaechen and self.modell.geschaerft != self.aufn.geschaerft:
                    messagebox.showwarning(
                        "Baummodell passt nicht zur Auflösung",
                        "Das Baummodell wurde an " + ("geschärften" if self.modell.geschaerft else "ungeschärften")
                        + " Aufnahmen berechnet, diese Aufnahme ist " + ("geschärft" if self.aufn.geschaerft else
                                                                         "ungeschärft") + ".\n\nDie Pixelgröße "
                        "unterscheidet sich (Faktor 2) – Textur- und Größenmerkmale passen nicht. Die Maske wird "
                        "trotzdem berechnet, ist aber unzuverlässig. Besser ein eigenes Modell berechnen.")
                self._setze_status("Berechne Baummaske …")
                self.root.config(cursor="watch"); self.root.update_idletasks()
                self.maske = vorgabe.berechne(self.aufn, self._merkmale(), info=self.verfein_info)
                self.root.config(cursor="")
            else:
                self.maske = vorgabe.berechne(self.aufn, info=self.verfein_info)
            self._masken_schluessel = schluessel
        return self.maske

    # ------------------------------------------------------------------ Auswertung
    def aktualisieren(self):
        if self.aufn is None:
            return
        a, idx = self.aufn, self.var_index.get()
        d = vk.INDIZES[idx]
        self.index_werte = vk.berechne_index(a.stapel, a.kanalindex, idx)
        vorgabe = self._vorgabe()
        try:
            maske = self._berechne_maske(vorgabe)
        except ValueError as e:
            self.root.config(cursor="")
            self._setze_status(f"Maske nicht berechenbar: {e}")
            vorgabe, maske = None, None
        mname = vorgabe.name if vorgabe else ""

        anzeige = self.index_werte.copy()
        if maske is not None:
            anzeige[~maske] = np.nan
        if self.var_skala.get().startswith("fest") or not np.isfinite(anzeige).any():
            vmin, vmax = d["skala"]
        else:
            vmin, vmax = np.nanpercentile(anzeige, [2, 98])
        schw = self.schwellen_werte.get(idx) if idx in self.schwellen_aktiv else None
        self.klassen = vk.klassifiziere(self.index_werte, schw) if schw else None
        if self.klassen is not None and self.var_klassenkarte.get():
            karte = self.klassen.astype(np.float32)
            karte[(self.klassen == vk.KLASSE_UNGUELTIG) | (~maske if maske is not None else False)] = np.nan
            zwei = zwei_klassen(schw)
            if zwei:                                   # ab 0.18: nur gestresst / vital, ohne Übergang
                karte[karte == vk.KLASSE_VITAL] = 1
                cmap = ListedColormap([SCHWELLEN_FARBEN[0], SCHWELLEN_FARBEN[2]])
            else:
                cmap = ListedColormap(SCHWELLEN_FARBEN)
            cmap.set_bad("#bdbdbd")
            self.im_idx.set_cmap(cmap)
            self.im_idx.set_data(np.ma.masked_invalid(karte))
            self.im_idx.set_clim(-0.5, 1.5 if zwei else 2.5)
            self.cbar.update_normal(self.im_idx)
            if zwei:
                self.cbar.set_ticks([0, 1], labels=[f"gestresst\n< {schw.gestresst:.3f}",
                                                    f"vital\n≥ {schw.vital:.3f}"])
            else:
                self.cbar.set_ticks([0, 1, 2], labels=[f"gestresst\n< {schw.gestresst:.3f}", "Übergang",
                                                       f"vital\n≥ {schw.vital:.3f}"])
            self.cbar.set_label(f"{idx}-Klassen")
        else:
            cmap = matplotlib.colormaps[d["cmap"]].copy()
            cmap.set_bad("#bdbdbd")
            self.im_idx.set_cmap(cmap)
            self.im_idx.set_data(np.ma.masked_invalid(anzeige))
            self.im_idx.set_clim(vmin, vmax)
            self.cbar.update_normal(self.im_idx)        # Farbleiste an neues Bild/neue Skala koppeln
            self.cbar.set_ticks(AutoLocator())
            self.cbar.set_label(idx)
        self.ax_idx.set_title(idx + (f" – Maske {vorgabe.beschreibung().split(':')[0]}" if vorgabe else ""))
        self.lbl_formel.config(text=f"{idx} = {d['formel']}")
        self.lbl_quelle.config(text=f"nach {d['quelle']}")
        self.lbl_maskeninfo.config(text="" if vorgabe is None else
                                   f"Maske: {vorgabe.beschreibung()}\nAnteil im Bild: {maske.mean() * 100:.1f} %")

        # Maskenumriss im RGB-Bild
        for art in self.masken_artists:
            try:
                art.remove()
            except (ValueError, NotImplementedError, AttributeError):
                pass
        self.masken_artists = []
        if maske is not None and self.var_umriss.get() and 0 < maske.mean() < 1:
            cs = self._einblendung(self.ax_rgb.contour(maske.astype(np.uint8), levels=[0.5], colors="yellow",
                                                       linewidths=0.9))
            self.masken_artists.append(cs)

        reg = vk.regionen(self.index_werte.shape, maske, mname, self.rois)
        self.tab.delete(*self.tab.get_children())
        for n, m in reg:
            s = vk.statistik(self.index_werte[m])
            self.tab.insert("", tk.END, values=[n, f"{s['Pixel']:,}".replace(",", ".")]
                            + [f"{s[k]:.4f}" for k in vk.STAT_SPALTEN[1:]])

        # Histogramm
        ax = self.ax_hist
        ax.clear()
        bins = np.linspace(*d["bereich"], 201)
        gueltig = np.isfinite(self.index_werte)
        ax.hist(self.index_werte[gueltig], bins=bins, color="#9e9e9e", alpha=0.6,
                label="Gesamtbild (gültige Pixel)", density=True)
        if maske is not None and (maske & gueltig).any():
            ax.hist(self.index_werte[maske & gueltig], bins=bins, color="#2e7d32", alpha=0.6, label=mname, density=True)
        regdict = dict(reg)
        for i, roi in enumerate(self.rois):
            m = regdict[f"{roi['name']} ∩ {mname}" if maske is not None else roi["name"]]
            w = self.index_werte[m & gueltig]
            if w.size:
                ax.hist(w, bins=bins, histtype="step", linewidth=1.6, color=ROI_FARBEN[i % len(ROI_FARBEN)],
                        label=roi["name"], density=True)
        self._eingabe_schliessen()      # offenes Eingabefeld gehört zur alten Darstellung
        self.linien = {}
        if schw and zwei_klassen(schw):              # ab 0.18: 2 Klassen -> eine Schwelle in der Legende
            self.linien["gestresst"] = ax.axvline(schw.gestresst, color=SCHWELLEN_FARBEN[0], linestyle="--",
                                                  linewidth=1.8, label="_nolegend_")
            self.linien["vital"] = ax.axvline(schw.vital, color=SCHWELLEN_FARBEN[2], linestyle=(0, (2, 4)),
                                              linewidth=1.8,
                                              label=f"Schwelle {schw.vital:.3f}: darunter gestresst, ab hier vital "
                                                    "(ziehen / anklicken)")
        elif schw:
            self.linien["gestresst"] = ax.axvline(schw.gestresst, color=SCHWELLEN_FARBEN[0], linestyle="--",
                                                  linewidth=1.8, label=f"gestresst < {schw.gestresst:.3f} (ziehen / anklicken)")
            self.linien["vital"] = ax.axvline(schw.vital, color=SCHWELLEN_FARBEN[2], linestyle="--", linewidth=1.8,
                                              label=f"vital ≥ {schw.vital:.3f} (ziehen / anklicken)")
            vmin, vmax = min(vmin, schw.gestresst), max(vmax, schw.vital)
        self._zeige_klassen(idx, schw, maske, mname, reg)
        ax.set_xlim(vmin - 0.05, vmax + 0.05)
        ax.set_xlabel(idx)
        ax.set_ylabel("relative Häufigkeit")
        leg = ax.legend(loc="upper left", fontsize=8)
        self._legende_texte = {}       # "gestresst"/"vital" -> Legendentext (anklickbar zum Eintippen)
        for txt in leg.get_texts():
            for k, vorsatz in (("gestresst", "gestresst <"), ("vital", "vital ≥"), ("beide", "Schwelle ")):
                if txt.get_text().startswith(vorsatz):
                    self._legende_texte[k] = txt
        ax.grid(alpha=0.3)
        self._mpl_thema()
        self.canvas.draw_idle()
        vi = getattr(self, "verfein_info", None) if vorgabe is not None and vorgabe.verfeinern else None
        if vi and vi.get("nir_schwelle") is not None:
            self._setze_status(
                f"Maske „{vorgabe.name}“ verfeinert: {vi['anteil_vorher'] * 100:.1f} % → {vi['anteil_nachher'] * 100:.1f} % "
                f"des Bildes (Lücken entfernt {vi['entfernt_anteil_bild'] * 100:.1f} %, Ränder ergänzt "
                f"{vi['hinzu_anteil_bild'] * 100:.1f} %; NIR-Schwelle {vi['nir_schwelle']:.3f} = "
                f"{vorgabe.luecke_anteil * 100:.0f} % von P90 {vi['nir_p90_maske']:.3f}).")
        elif vorgabe is not None and vorgabe.art == "Baum":
            self._setze_status(f"Baummaske: {maske.mean() * 100:.1f} % des Bildes als Baum klassifiziert.")

    # ------------------------------------------------------------------ Schwellwerte
    def _aktive_schwellen(self):
        return {i: self.schwellen_werte[i] for i in self.schwellen_aktiv if i in self.schwellen_werte}

    def _schwellen_laden(self):
        """Werte des angezeigten Index in die Eingabefelder übernehmen."""
        idx = self.var_index.get()
        self.chk_schw.config(text=f"Schwellwerte für {idx}:")
        lit = vk.LITERATUR_ORIENTIERUNG.get(idx)
        self.lbl_literatur.config(text=(f"Literatur zur Orientierung ({idx}): {lit}. Für Stress in dichten Kronen nicht "
                                        "geeignet – Schwellen besser aus Referenzbäumen ableiten.") if lit else
                                  f"Literatur: für {idx} keine Grenzwerte in den verwendeten Quellen.")
        sw = self.schwellen_werte.get(idx)
        self.var_schw_an.set(idx in self.schwellen_aktiv)
        if sw:
            self.var_s_gestresst.set(round(sw.gestresst, 3))
            self.var_s_vital.set(round(sw.vital, 3))
            self.var_s_anteil.set(round(sw.anteil_markierung * 100, 1))
            self.var_s_kronen.set(sw.kronenabstand_px)
            self.var_kronen_nir.set(sw.kronen_nir)
            self.var_kronen_raster.set(sw.kronen_raster)
            self.var_baumregel.set(vk.BAUMREGELN.get(sw.baumregel, vk.BAUMREGELN["anteil"]))

    def _baumregel_alle(self):
        """Ab 0.20.2: Die Baumregel gilt für ALLE Indizes mit Schwellen (vorher nur für den angezeigten – führte zu
        gemischten Regeln, wenn erst „für alle Indizes übernehmen“ und danach die Regel umgestellt wurde)."""
        regel = self._baumregel()
        geaendert = [i for i, sw in self.schwellen_werte.items() if sw.baumregel != regel]
        for i in geaendert:
            self.schwellen_werte[i] = dataclasses.replace(self.schwellen_werte[i], baumregel=regel)
        self._schwellen_uebernehmen()
        if geaendert:
            self._setze_status(f"Baumregel „{vk.BAUMREGELN[regel]}“ für alle Indizes mit Schwellen gesetzt "
                               f"({', '.join(geaendert)} geändert).")

    def _baumregel(self):
        """Schlüssel der gewählten Baumregel ("anteil" / "median")."""
        return next((k for k, v in vk.BAUMREGELN.items() if v == self.var_baumregel.get()), "anteil")

    def _schwellen_startwerte(self):
        """Startwerte: 10. und 30. Perzentil der aktuellen Maske (bzw. des Bildes) – nur als Ausgangspunkt."""
        if self.aufn is None or self.index_werte is None:
            return
        w = self.index_werte
        if self.maske is not None and self._masken_schluessel is not None:
            w = w[self.maske]
        w = w[np.isfinite(w)]
        if not w.size:
            return
        p10, p30 = (float(v) for v in np.percentile(w, [10, 30]))
        self.var_s_gestresst.set(round(p10, 2))
        self.var_s_vital.set(round(p30, 2))
        self.var_schw_an.set(True)
        self._schwellen_uebernehmen(herkunft=f"Startwerte P10/P30 aus {self.aufn.name} (bildrelativ)")
        self._setze_status(f"Startwerte aus diesem Bild: gestresst < {p10:.2f} (P10), vital ≥ {p30:.2f} (P30). "
                           "Das sind relative Werte – für die Auswertung feste, begründete Schwellen festlegen.")

    def _schwellen_umschalten(self):
        idx = self.var_index.get()
        if self.var_schw_an.get():
            if idx not in self.schwellen_werte:
                self._schwellen_startwerte()
                return
            self.schwellen_aktiv.add(idx)
        else:
            self.schwellen_aktiv.discard(idx)
        self.aktualisieren()

    def _schwellen_uebernehmen(self, herkunft=None):
        idx = self.var_index.get()
        try:
            alt = self.schwellen_werte.get(idx)
            g, v = round(float(self.var_s_gestresst.get()), 4), round(float(self.var_s_vital.get()), 4)
            if herkunft is None:   # Herkunft bleibt erhalten, solange die Schwellen selbst nicht verändert wurden
                unveraendert = alt and abs(alt.gestresst - g) < 0.005 and abs(alt.vital - v) < 0.005
                herkunft = alt.herkunft if unveraendert else "manuell"
                if unveraendert:          # Anzeige ist gerundet – gespeicherte, genaue Werte behalten
                    g, v = alt.gestresst, alt.vital
            sw = vk.Schwellen(g, v, round(float(self.var_s_anteil.get()), 2) / 100, int(self.var_s_kronen.get()),
                              herkunft, bool(self.var_kronen_nir.get()), bool(self.var_kronen_raster.get()),
                              self._baumregel())
        except (tk.TclError, ValueError) as e:
            self._setze_status(f"Schwellwerte ungültig: {e}")
            return
        if self.schwellen_werte.get(idx) == sw and (idx in self.schwellen_aktiv) == self.var_schw_an.get():
            return
        self.schwellen_werte[idx] = sw
        if self.var_schw_an.get():
            self.schwellen_aktiv.add(idx)
        self.aktualisieren()

    def _zeige_klassen(self, idx, schw, maske, mname, reg):
        for art in self.schwellen_artists:
            try:
                art.remove()
            except (ValueError, NotImplementedError, AttributeError):
                pass
        self.schwellen_artists = []
        self.tab_kl.delete(*self.tab_kl.get_children())
        self.objekte = None
        self.objekt_labels = None
        if schw is None:
            self.lbl_klassen.config(text="")
            self.lbl_objekte.config(text="Schwellwerte aus – in der unteren Leiste je Index einschalten.")
            return
        self.lbl_klassen.config(text=(f"Klassen {idx}: gestresst < {schw.vital:.3f} ≤ vital (2 Klassen)" if zwei_klassen(schw)
                                      else f"Klassen {idx}: gestresst < {schw.gestresst:.2f} ≤ Übergang < "
                                           f"{schw.vital:.2f} ≤ vital"))
        for n, m in reg:
            a = vk.klassenanteile(self.klassen, m)
            self.tab_kl.insert("", tk.END, values=[n, f"{a['Pixel']:,}".replace(",", ".")]
                               + ([f"{a[k] * 100:.1f}" for k in ("gestresst", "Übergang", "vital")] if a["Pixel"]
                                  else ["–"] * 3))
        if maske is None:
            self.lbl_objekte.config(text="Bewertung je Baum: Maske „Bäume (Modell)“ oder „Vegetation“ wählen.")
            return
        info = {}
        lab, obj = vk.bewerte_objekte(self.index_werte, self.klassen, maske, schw,
                                      self.aufn.kronenstapel[self.aufn.kanalindex["NIR"]], self.kronen_korr, info)
        self.objekte = obj
        self.objekt_labels = lab
        r = info.get("raster")
        trennung = (f", Pflanzraster {r['abstand_px']:.0f}/{r['abstand2_px']:.0f} px" if r else
                    (" – kein Pflanzraster erkennbar" if schw.kronen_raster else ""))
        if self.kronen_korr:
            trennung += f", {len(self.kronen_korr)} Korrektur(en) von Hand"
        anz = {k: [o["nr"] for o in obj if o["klasse"] == k]
               for k in (vk.KLASSE_GESTRESST, vk.KLASSE_UEBERGANG, vk.KLASSE_VITAL)}
        gestresst = anz[vk.KLASSE_GESTRESST]
        self.lbl_objekte.config(text=(
            f"Bäume (Objekte der Maske „{mname}“, ab {vk.OBJEKT_MIN_PX} px"
            + (f", Kronen getrennt mit Abstand {schw.kronenabstand_px} px"
               + (" (Form + NIR)" if schw.kronen_nir else " (Form)") if schw.kronenabstand_px else "")
            + trennung
            + f"): {len(obj)} – gestresst {len(gestresst)}, "
            + ("" if zwei_klassen(schw) else f"Übergang {len(anz[vk.KLASSE_UEBERGANG])}, ")
            + f"vital {len(anz[vk.KLASSE_VITAL])}\n"
            + ((f"Regel (Median je Baum): gestresst, wenn Median < {schw.gestresst:.3f}, sonst vital")
               if schw.baumregel == "median" and zwei_klassen(schw) else
               (f"Regel (Median je Baum): gestresst, wenn Median < {schw.gestresst:.3f}; vital, wenn Median ≥ "
                f"{schw.vital:.3f}; sonst Übergang") if schw.baumregel == "median" else
               (f"Regel: gestresst, wenn ≥ {schw.anteil_markierung * 100:.0f} % der Pixel gestresst; sonst vital, wenn "
                f"≥ {vk.OBJEKT_VITAL_ANTEIL * 100:.0f} % vital; sonst Übergang"))
            + (f"\nGestresst: Nr. " + ", ".join(map(str, gestresst[:30])) + (" …" if len(gestresst) > 30 else "")
               if gestresst else "")))
        if self.var_baumfarben.get() and obj:
            self._zeige_baumfarben(lab, obj)
        for k in self.kronen_korr:                     # Korrekturen von Hand anzeigen
            if k["art"] == "teilen":
                x, y = k["xy"]
                self.schwellen_artists.append(self._einblendung(self.ax_rgb.plot(
                    [x], [y], marker="+", ms=12, mew=2.5, color="#ffffff", zorder=4)[0]))
            elif k["art"] == "schnitt":
                (x1, y1), (x2, y2) = k["xy"]
                self.schwellen_artists.append(self._einblendung(self.ax_rgb.plot(
                    [x1, x2], [y1, y2], "-", lw=2.5, color="#ff3030", zorder=4)[0]))
            else:
                (x1, y1), (x2, y2) = k["xy"]
                self.schwellen_artists.append(self._einblendung(self.ax_rgb.plot(
                    [x1, x2], [y1, y2], "-o", ms=4, lw=2, color="#ffffff", zorder=4)[0]))
        if self.var_nummern.get():
            for o in obj:
                fc = SCHWELLEN_FARBEN[o["klasse"]] if o["klasse"] in (0, 1, 2) else "#333333"
                t = self._einblendung(self.ax_rgb.text(o["x"], o["y"], str(o["nr"]), fontsize=7, ha="center", va="center",
                                     fontweight="bold", color="black" if o["klasse"] == 1 else "white",
                                     bbox=dict(boxstyle="round,pad=0.15", lw=0, fc=fc, alpha=0.9)))
                self.schwellen_artists.append(t)

    def _zeige_baumfarben(self, lab, obj):
        """Bäume im RGB-Bild halbtransparent in der Klassenfarbe füllen, Baumgrenzen kräftiger."""
        kl = vk.objekt_klassenbild(lab, obj)
        farben = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in SCHWELLEN_FARBEN], np.uint8)
        rgba = np.zeros(kl.shape + (4,), np.uint8)
        baum = kl != vk.KLASSE_UNGUELTIG
        rgba[baum, :3] = farben[kl[baum]]
        rgba[baum, 3] = 100                                       # Füllung ≈ 40 % Deckkraft
        grenze = np.zeros(kl.shape, bool)                          # Grenzen zwischen Bäumen / zum Hintergrund
        grenze[:, 1:] |= lab[:, 1:] != lab[:, :-1]
        grenze[1:, :] |= lab[1:, :] != lab[:-1, :]
        grenze = cv2.dilate(grenze.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        rand = grenze & baum
        rgba[rand, 3] = 230
        xlim, ylim = self.ax_rgb.get_xlim(), self.ax_rgb.get_ylim()   # Zoom erhalten
        h, w = kl.shape
        bild = self.ax_rgb.imshow(rgba, interpolation="nearest", extent=(-0.5, w - 0.5, h - 0.5, -0.5), zorder=2)
        self.ax_rgb.set_xlim(xlim); self.ax_rgb.set_ylim(ylim)
        self.schwellen_artists.append(self._einblendung(bild))

    # ------------------------------------------------------------------ Interaktion
    def _klick(self, ev):
        if (self.aufn is not None and ev.inaxes in (self.ax_rgb, self.ax_idx) and not self.toolbar.mode
                and ev.button == 1 and self.var_zeichnen.get() in ("k_teilen", "k_verbinden")):
            self._kronenkorrektur_klick(ev)
            return
        if self.aufn is None or ev.inaxes not in (self.ax_rgb, self.ax_idx) or self.var_zeichnen.get() != "aus":
            return
        if self.toolbar.mode or ev.button != 1:     # Zoom/Pan der Werkzeugleiste aktiv oder andere Taste
            return
        x, y = int(round(ev.xdata)), int(round(ev.ydata))
        st, k = self.aufn.stapel, self.aufn.kanalindex
        if not (0 <= y < st.shape[1] and 0 <= x < st.shape[2]):
            return
        zeilen = [f"Pixel x = {x}, y = {y}", "", "Reflektanz:"]
        for n in vk.KANALNAMEN:
            zeilen.append(f"  {n:<9} {st[k[n], y, x]:8.4f}" if n in k else f"  {n:<9}  fehlt")
        zeilen.append("Indizes:")
        for i in vk.INDIZES:
            if not vk.index_verfuegbar(k, i):
                zeilen.append(f"  {i:<9}  – (Kanal fehlt)")
                continue
            w = vk.berechne_index(st[:, y:y + 1, x:x + 1], k, i)[0, 0]
            zeilen.append(f"  {i:<9} {w:8.4f}" if np.isfinite(w) else f"  {i:<9}  ungültig")
        if self.klassen is not None and self.klassen[y, x] != vk.KLASSE_UNGUELTIG:
            zeilen.append(f"Klasse ({self.var_index.get()}): {vk.KLASSENNAMEN[int(self.klassen[y, x])]}")
        if self.maske is not None and self._masken_schluessel is not None:
            zeilen.append(f"Maske:     {'ja' if self.maske[y, x] else 'nein'}")
        self.txt_pixel.delete("1.0", tk.END)
        self.txt_pixel.config(height=len(zeilen))
        self.txt_pixel.insert("1.0", "\n".join(zeilen))

    @staticmethod
    def _einblendung(art):
        """Einblendung (Text, Umriss, Polygon) am Bildrand abschneiden und aus der Layoutberechnung nehmen.
        Sonst verkleinert das automatische Layout beim Zoomen die Bildachsen, um Beschriftungen außerhalb
        des sichtbaren Ausschnitts Platz zu machen."""
        try:
            art.set_clip_on(True)
        except AttributeError:
            pass
        art.set_in_layout(False)
        return art

    # ------------------------------------------------------------------ Zoomen / Verschieben
    def _bildgrenzen(self):
        h, w = self.aufn.stapel.shape[1:]
        return (-0.5, w - 0.5), (-0.5, h - 0.5)

    @staticmethod
    def _begrenzen(lo, hi, g_lo, g_hi):
        """Ausschnitt [lo, hi] in die Bildgrenzen schieben bzw. auf das ganze Bild begrenzen."""
        breite = hi - lo
        if breite >= g_hi - g_lo:
            return g_lo, g_hi
        if lo < g_lo:
            lo, hi = g_lo, g_lo + breite
        if hi > g_hi:
            lo, hi = g_hi - breite, g_hi
        return lo, hi

    def _setze_ausschnitt(self, x0, x1, y0, y1):
        """x0 < x1, y0 < y1 in Bildkoordinaten; die y-Achse bleibt nach unten gerichtet (Bildzeilen)."""
        (gx0, gx1), (gy0, gy1) = self._bildgrenzen()
        x0, x1 = self._begrenzen(x0, x1, gx0, gx1)
        y0, y1 = self._begrenzen(y0, y1, gy0, gy1)
        self.ax_idx.set_xlim(x0, x1)                 # Achsen sind gekoppelt (RGB + Index)
        self.ax_idx.set_ylim(y1, y0)
        self.canvas.draw_idle()

    def _mausrad(self, ev):
        if self.aufn is None or ev.inaxes not in (self.ax_rgb, self.ax_idx) or ev.xdata is None:
            return
        f = 1 / 1.3 if ev.button == "up" else 1.3
        x0, x1 = sorted(ev.inaxes.get_xlim())
        y0, y1 = sorted(ev.inaxes.get_ylim())
        if f < 1 and (x1 - x0) * f < 20:              # stärkste Vergrößerung: ≈ 20 px Bildbreite
            return
        cx, cy = ev.xdata, ev.ydata
        self._setze_ausschnitt(cx + (x0 - cx) * f, cx + (x1 - cx) * f, cy + (y0 - cy) * f, cy + (y1 - cy) * f)

    def _pan_start(self, ev):
        if self.aufn is None or ev.button != 3 or ev.inaxes not in (self.ax_rgb, self.ax_idx):
            return
        ax = ev.inaxes
        self._pan = (ev.x, ev.y, sorted(ax.get_xlim()), sorted(ax.get_ylim()), ax.bbox.width, ax.bbox.height)
        self.canvas.get_tk_widget().config(cursor="fleur")

    def _pan_bewegen(self, ev):
        if self._pan is None:
            return
        sx, sy, (x0, x1), (y0, y1), bw, bh = self._pan
        dx = (ev.x - sx) * (x1 - x0) / bw
        dy = (ev.y - sy) * (y1 - y0) / bh            # Bildschirm-y nach oben, Bildzeilen nach unten
        self._setze_ausschnitt(x0 - dx, x1 - dx, y0 + dy, y1 + dy)

    # ------------------------------------------------------------------ Schwellenlinien ziehen
    def _linie_treffer(self, ev, toleranz_px=6):
        """Welche Schwellenlinie liegt unter dem Mauszeiger? ('gestresst', 'vital', 'beide' oder None)"""
        if not self.linien or ev.inaxes is not self.ax_hist or ev.x is None:
            return None
        abst = {k: abs(self.ax_hist.transData.transform((l.get_xdata()[0], 0))[0] - ev.x)
                for k, l in self.linien.items()}
        nah = [k for k, d in abst.items() if d <= toleranz_px]
        if not nah:
            return None
        g, v = (self.linien[k].get_xdata()[0] for k in ("gestresst", "vital"))
        if len(nah) == 2:
            return "beide" if abs(g - v) < 1e-9 else min(nah, key=abst.get)
        return nah[0]

    def _schwellentexte(self):
        """Anklickbare Schwellenangaben: Histogramm-Legende und Beschriftung der Farbskala (Klassenkarte)."""
        texte = []
        if not self.linien:
            return texte
        if self._legende_texte:
            texte += list(self._legende_texte.items())
        if self.cbar is not None and self.klassen is not None and self.var_klassenkarte.get():
            zwei = zwei_klassen(self.schwellen_werte.get(self.var_index.get()))
            for txt in self.cbar.ax.yaxis.get_ticklabels():
                s = txt.get_text()
                if s.startswith("gestresst"):
                    texte.append(("beide" if zwei else "gestresst", txt))
                elif s.startswith("vital"):
                    texte.append(("beide" if zwei else "vital", txt))
        return texte

    def _schwellentext_treffer(self, ev):
        """Liegt der Mauszeiger auf einer Schwellenangabe (Legende oder Farbskala)? -> (welche, Text) oder None"""
        if ev.x is None:
            return None
        r = self.canvas.get_renderer()
        for k, txt in self._schwellentexte():
            if txt.get_visible() and txt.get_window_extent(r).contains(ev.x, ev.y):
                return k, txt
        return None

    def _schwelle_eintippen(self, welche, txt):
        """Eingabefeld direkt über der angeklickten Schwellenangabe öffnen; Enter übernimmt, Esc bricht ab."""
        self._eingabe_schliessen()
        bb = txt.get_window_extent(self.canvas.get_renderer())
        widget = self.canvas.get_tk_widget()
        hoehe = self.fig.bbox.height                       # Matplotlib zählt y von unten, Tk von oben
        alt = self.linien["gestresst" if welche == "beide" else welche].get_xdata()[0]
        var = tk.StringVar(value=f"{alt:.3f}")
        ent = ttk.Entry(widget, textvariable=var, width=8, justify=tk.RIGHT)
        ent.place(x=bb.x0, y=hoehe - bb.y1 - 2)
        ent.focus_set()
        ent.select_range(0, tk.END)
        self._schwellen_eingabe = ent
        self._setze_status(f"Schwelle „{'gestresst/vital' if welche == 'beide' else welche}“ ({self.var_index.get()}) "
                           "eingeben – Enter übernimmt, Esc bricht ab.")

        def uebernehmen(_e=None):
            if self._schwellen_eingabe is not ent:
                return
            try:
                wert = round(float(var.get().strip().replace(",", ".")), 4)
            except ValueError:
                self._setze_status(f"„{var.get()}“ ist keine Zahl – bitte z. B. 0,85 oder 0.85 eingeben.")
                ent.focus_set(); ent.select_range(0, tk.END)
                return
            lo, hi = vk.INDIZES[self.var_index.get()]["bereich"]
            g = float(self.linien["gestresst"].get_xdata()[0])
            v = float(self.linien["vital"].get_xdata()[0])
            if not lo <= wert <= hi:
                fehler = f"Wert {wert} liegt außerhalb des Indexbereichs {lo} … {hi}."
            elif welche == "gestresst" and wert > v:
                fehler = f"„gestresst <“ ({wert}) darf nicht größer sein als „vital ≥“ ({v:.3f})."
            elif welche == "vital" and wert < g:
                fehler = f"„vital ≥“ ({wert}) darf nicht kleiner sein als „gestresst <“ ({g:.3f})."
            else:
                fehler = None
            if fehler:
                self._setze_status(fehler + " Bitte korrigieren oder mit Esc abbrechen.")
                ent.focus_set(); ent.select_range(0, tk.END)
                return
            self._eingabe_schliessen()
            if welche == "beide":                       # 2-Klassen-Schema: beide Schwellen gemeinsam
                if abs(wert - g) < 1e-9:
                    return
                g = v = wert
            elif abs(wert - (g if welche == "gestresst" else v)) < 1e-9:
                return
            elif welche == "gestresst":
                g = wert
            else:
                v = wert
            self.var_s_gestresst.set(round(g, 4))
            self.var_s_vital.set(round(v, 4))
            self._schwellen_uebernehmen(herkunft="manuell (Wert eingetippt)")
            self._setze_status(f"Schwellen {self.var_index.get()} übernommen: gestresst < {g:.3f}, vital ≥ {v:.3f}")

        ent.bind("<Return>", uebernehmen)
        ent.bind("<KP_Enter>", uebernehmen)
        ent.bind("<Escape>", lambda e: (self._eingabe_schliessen(), self._setze_status("Eingabe abgebrochen.")))
        ent.bind("<FocusOut>", lambda e: self._eingabe_schliessen())

    def _eingabe_schliessen(self):
        ent, self._schwellen_eingabe = self._schwellen_eingabe, None
        if ent is not None:
            try:
                ent.destroy()
            except tk.TclError:
                pass

    def _linie_druck(self, ev):
        if ev.button != 1 or self.toolbar.mode:
            return
        treffer = self._schwellentext_treffer(ev)
        if treffer:
            self._schwelle_eintippen(*treffer)
            return
        welche = self._linie_treffer(ev)
        if welche:
            g, v = (self.linien[k].get_xdata()[0] for k in ("gestresst", "vital"))
            self._linie_zug = (welche, g, v, ev.xdata)

    def _linie_bewegen(self, ev):
        widget = self.canvas.get_tk_widget()
        if self._linie_zug is None:
            if self._pan is None:     # nur Mauszeiger anpassen
                widget.config(cursor="hand2" if self._schwellentext_treffer(ev) else
                              "sb_h_double_arrow" if self._linie_treffer(ev) else "")
            return
        if ev.inaxes is not self.ax_hist or ev.xdata is None:
            return
        welche, g0, v0, x0 = self._linie_zug
        lo, hi = vk.INDIZES[self.var_index.get()]["bereich"]
        x = float(np.clip(ev.xdata, lo, hi))
        if welche == "gestresst":
            g, v = min(x, v0), v0
        elif welche == "vital":
            g, v = g0, max(x, g0)
        else:                          # beide gemeinsam (2-Klassen-Schema)
            g = v = x
        self.linien["gestresst"].set_xdata([g, g])
        self.linien["vital"].set_xdata([v, v])
        self.canvas.draw_idle()
        self._setze_status(f"Schwellen {self.var_index.get()}: gestresst < {g:.3f}, vital ≥ {v:.3f} "
                           "– loslassen zum Übernehmen")

    def _linie_los(self, ev):
        if self._linie_zug is None:
            return
        welche, g0, v0, _ = self._linie_zug
        self._linie_zug = None
        g = round(float(self.linien["gestresst"].get_xdata()[0]), 3)
        v = round(float(self.linien["vital"].get_xdata()[0]), 3)
        if abs(g - g0) < 1e-6 and abs(v - v0) < 1e-6:
            return
        self.var_s_gestresst.set(g)
        self.var_s_vital.set(v)
        self._schwellen_uebernehmen(herkunft="manuell (im Histogramm verschoben)")
        self._setze_status(f"Schwellen {self.var_index.get()} übernommen: gestresst < {g:.3f}, vital ≥ {v:.3f}")

    def _pan_ende(self, ev):
        if self._pan is not None and ev.button == 3:
            self._pan = None
            self.canvas.get_tk_widget().config(cursor="")

    def ganzes_bild(self):
        if self.aufn is None:
            return
        (gx0, gx1), (gy0, gy1) = self._bildgrenzen()
        self._setze_ausschnitt(gx0, gx1, gy0, gy1)

    def _zeichenmodus(self):
        modus = self.var_zeichnen.get()
        if modus != "aus" and self.toolbar.mode:
            self.toolbar.zoom() if "zoom" in str(self.toolbar.mode) else self.toolbar.pan()
        for s in self.rechteck_sel:
            s.set_active(modus == "roi")
        for s in self.lasso_sel:
            s.set_active(modus in ("baum", "kein", "ref_v", "ref_g"))
        texte = {"aus": "Zeichnen aus – Klick ins Bild zeigt Pixelwerte.",
                 "roi": "ROI: Rechteck im RGB- oder Indexbild aufziehen.",
                 "baum": "Beispiel „Baum“: Baumkrone mit gedrückter linker Maustaste umfahren.",
                 "kein": "Beispiel „kein Baum“: Gras/Boden/Schatten/Weg mit gedrückter linker Maustaste umfahren.",
                 "ref_v": "Referenz „vital“: sicher vitale Krone umfahren (bei aktiver Maske zählen nur Maskenpixel). "
                          "Klick in einen Referenzbaum löscht ihn.",
                 "ref_g": "Referenz „geschädigt“: sicher geschädigte Krone/Kronenteil umfahren (bei aktiver Maske nur "
                          "Maskenpixel). Klick in einen Referenzbaum löscht ihn.",
                 "k_teilen": "Krone teilen: mit gedrückter linker Maustaste eine Linie über die Stelle ziehen, an der "
                             "zwei Kronen zusammengewachsen sind (rote Schnittlinie). Nur klicken = zusätzliche "
                             "Kronenmitte. Klick auf eine Korrektur löscht sie. Wird je Bild gespeichert.",
                 "k_verbinden": "Kronen verbinden: in zwei Objekte klicken, die zu einem Baum gehören. "
                                "Klick auf eine Korrektur löscht sie. Wird je Bild gespeichert."}
        self._verbinden_start = None
        self._setze_status(texte[modus])
        if modus in ("k_teilen", "k_verbinden") and self.objekt_labels is None:
            self._setze_status(texte[modus] + "  –  Hinweis: Bäume werden erst angezeigt, wenn eine Maske gewählt und "
                               "die Schwellwerte für den Index eingeschaltet sind.")

    # ------------------------------------------------------------------ Kronenkorrektur von Hand (Version 0.13)
    def _korrektur_treffer(self, ev, toleranz_px=10):
        """Index der Korrektur (Kreuz, Schnitt- oder Verbindungslinie) unter dem Mauszeiger oder None (ab 0.18)."""
        tr = ev.inaxes.transData
        p = np.array([ev.x, ev.y], float)
        bester, best_d = None, toleranz_px
        for i, k in enumerate(self.kronen_korr):
            pts = [k["xy"]] if k["art"] == "teilen" else k["xy"]
            a = tr.transform(np.array(pts[0], float))
            b = tr.transform(np.array(pts[-1], float))
            ab = b - a
            s = 0.0 if not ab.any() else float(np.clip(np.dot(p - a, ab) / np.dot(ab, ab), 0, 1))
            d = float(np.hypot(*(a + s * ab - p)))
            if d <= best_d:
                bester, best_d = i, d
        return bester

    def _kronenkorrektur_klick(self, ev):
        x, y = float(ev.xdata), float(ev.ydata)
        h, w = self.aufn.stapel.shape[1:]
        if not (0 <= x < w and 0 <= y < h):
            return
        i = self._korrektur_treffer(ev)               # ab 0.18: Klick auf eine Korrektur löscht sie
        if i is not None:
            k = self.kronen_korr.pop(i)
            self._verbinden_start = None
            namen = {"teilen": "Kronenmitte", "schnitt": "Schnittlinie", "verbinden": "Verbindung"}
            self._kronen_korr_speichern(f"{namen.get(k['art'], k['art'])} entfernt.")
            return
        lab = self.objekt_labels
        if lab is None:
            self._setze_status("Keine Bäume angezeigt – zuerst Maske wählen und Schwellwerte einschalten.")
            return
        objekt = int(lab[int(round(y)), int(round(x))])
        if self.var_zeichnen.get() == "k_teilen":
            # ab 0.18: erst beim Loslassen entscheiden – Linie gezogen = Schnitt, nur geklickt = Kronenmitte
            linie = self.ax_rgb.plot([x, x], [y, y], "-", lw=2.5, color="#ff3030", zorder=5)[0]
            self._teilen_zug = (x, y, ev.x, ev.y, self._einblendung(linie), objekt)
            self.canvas.draw_idle()
            return
        if not objekt:
            self._setze_status("Klick liegt außerhalb der Bäume (Maske) – bitte in eine Krone klicken.")
            return
        if self._verbinden_start is None:
            self._verbinden_start = (round(x, 1), round(y, 1), objekt)
            self._setze_status("Kronen verbinden: jetzt in das zweite Objekt klicken.")
            return
        x1, y1, o1 = self._verbinden_start
        self._verbinden_start = None
        if o1 == objekt:
            self._setze_status("Beide Klicks liegen im selben Objekt – nichts verbunden.")
            return
        self.kronen_korr.append({"art": "verbinden", "xy": [[x1, y1], [round(x, 1), round(y, 1)]]})
        self._kronen_korr_speichern("Kronen verbunden.")

    def _teilen_bewegen(self, ev):
        if self._teilen_zug is None or ev.inaxes not in (self.ax_rgb, self.ax_idx) or ev.xdata is None:
            return
        x0, y0, _, _, linie, _ = self._teilen_zug
        linie.set_data([x0, ev.xdata], [y0, ev.ydata])
        self.canvas.draw_idle()

    def _teilen_los(self, ev):
        if self._teilen_zug is None or ev.button != 1:
            return
        x0, y0, sx, sy, linie, objekt = self._teilen_zug
        self._teilen_zug = None
        linie.remove()
        if ev.xdata is None or ev.inaxes not in (self.ax_rgb, self.ax_idx) or np.hypot(ev.x - sx, ev.y - sy) < 8:
            if not objekt:
                self.canvas.draw_idle()
                self._setze_status("Klick liegt außerhalb der Bäume (Maske) – für eine Kronenmitte in eine Krone "
                                   "klicken, zum Trennen eine Linie über die Verbindungsstelle ziehen.")
                return
            self.kronen_korr.append({"art": "teilen", "xy": [round(x0, 1), round(y0, 1)]})
            self._kronen_korr_speichern("Kronenmitte gesetzt (die Grenze zur Nachbarkrone sucht die Software selbst).")
            return
        x1, y1 = float(ev.xdata), float(ev.ydata)
        self.kronen_korr.append({"art": "schnitt",
                                 "xy": [[round(x0, 1), round(y0, 1)], [round(x1, 1), round(y1, 1)]]})
        self._kronen_korr_speichern("Schnittlinie gesetzt. Trennt sie die Krone nicht, die Linie über die ganze "
                                    "Verbindungsstelle bis in den Hintergrund ziehen.")

    def kronenkorrekturen_loeschen(self):
        if self.aufn is None or not self.kronen_korr:
            self._setze_status("Keine Kronenkorrektur für dieses Bild vorhanden.")
            return
        if not messagebox.askyesno("Kronenkorrekturen löschen",
                                   f"Alle {len(self.kronen_korr)} Kronenkorrektur(en) für {self.aufn.name} löschen?",
                                   parent=self.root):
            return
        self.kronen_korr = []
        self._verbinden_start = None
        self._kronen_korr_speichern("Alle Kronenkorrekturen dieses Bildes gelöscht.")

    def _kronen_korr_speichern(self, text):
        try:
            vk.speichere_kronenkorrekturen(self.aufn.ordner, self.aufn.name, self.kronen_korr, self.aufn.geschaerft)
        except OSError as e:
            messagebox.showerror("Kronenkorrektur", f"Korrektur konnte nicht gespeichert werden:\n{e}")
            return
        self.aktualisieren()
        self._setze_status(f"{text} {len(self.kronen_korr)} Korrektur(en) für {self.aufn.name} "
                           f"(gespeichert in {vk.AUSWERTUNG_UNTERORDNER}\\{vk.KRONEN_KORREKTUR_DATEI}).")

    def kronenkorrektur_zurueck(self):
        if self.aufn is None or not self.kronen_korr:
            self._setze_status("Keine Kronenkorrektur für dieses Bild vorhanden.")
            return
        k = self.kronen_korr.pop()
        self._kronen_korr_speichern(f"Letzte Korrektur ({k['art']}) zurückgenommen.")

    def _roi_fertig(self, e_press, e_release):
        if self.aufn is None:
            return
        h, w = self.aufn.stapel.shape[1:]
        x0, x1 = sorted((e_press.xdata, e_release.xdata))
        y0, y1 = sorted((e_press.ydata, e_release.ydata))
        box = (max(0, int(round(x0))), max(0, int(round(y0))), min(w, int(round(x1))), min(h, int(round(y1))))
        if box[2] - box[0] < 1 or box[3] - box[1] < 1:
            return
        nr = len(self.rois) + 1
        farbe = ROI_FARBEN[(nr - 1) % len(ROI_FARBEN)]
        self.rois.append({"name": f"ROI {nr}", "box": box})
        for ax in (self.ax_rgb, self.ax_idx):
            r = Rectangle((box[0] - 0.5, box[1] - 0.5), box[2] - box[0], box[3] - box[1], fill=False,
                          edgecolor=farbe, linewidth=1.8)
            ax.add_patch(self._einblendung(r))
            t = self._einblendung(ax.text(box[0], box[1] - 4, f"ROI {nr}", color=farbe, fontsize=9,
                                          fontweight="bold", va="bottom"))
            self.roi_artists += [r, t]
        self._setze_status(f"ROI {nr}: x {box[0]}–{box[2]}, y {box[1]}–{box[3]} "
                           f"({(box[2] - box[0]) * (box[3] - box[1]):,} px)".replace(",", "."))
        self.aktualisieren()

    def rois_loeschen(self, neu_zeichnen=True):
        for art in self.roi_artists:
            try:
                art.remove()
            except (ValueError, NotImplementedError):
                pass
        self.roi_artists, self.rois = [], []
        if neu_zeichnen:
            self.aktualisieren()

    # ------------------------------------------------------------------ Baummodell
    def _flaeche_unter_klick(self, flaechen, x, y):
        """Kleinste Fläche (Referenz- oder Beispielfläche) des angezeigten Bildes, die den Punkt enthält (ab 0.18.1)."""
        from matplotlib.path import Path
        treffer = []
        for f in flaechen:
            if vk.gleiche_aufnahme(f, self.aufn) and Path(f["xy"]).contains_point((x, y)):
                xy = np.asarray(f["xy"], float)
                flaeche = 0.5 * abs(np.dot(xy[:, 0], np.roll(xy[:, 1], 1)) - np.dot(xy[:, 1], np.roll(xy[:, 0], 1)))
                treffer.append((flaeche, f))
        return min(treffer, key=lambda z: z[0])[1] if treffer else None

    def _flaeche_per_klick_loeschen(self, modus, x, y):
        """Klick (ohne Umfahren) in eine Referenz- bzw. Beispielfläche löscht sie (ab 0.18.1)."""
        if modus in ("ref_v", "ref_g"):
            f = self._flaeche_unter_klick(self.referenzen.flaechen, x, y)
            if f is None:
                self._setze_status("Kein Referenzbaum an dieser Stelle. Zum Einzeichnen die Krone mit gedrückter "
                                   "Maustaste umfahren; ein Klick in einen Referenzbaum löscht ihn.")
                return
            self.referenzen.entfernen(f["nr"])
            self._zeichne_trainingsflaechen()
            self.canvas.draw_idle()
            self._referenz_anzeige()
            self._setze_status(f"Referenz {('V' if f['klasse'] else 'G')}{f['nr']} "
                               f"({vk.REF_KLASSEN[f['klasse']]}, {f['aufnahme']}) gelöscht. "
                               "Referenzdatei danach neu speichern.")
            return
        f = self._flaeche_unter_klick(self.modell.flaechen, x, y)
        if f is None:
            self._setze_status("Keine Beispielfläche an dieser Stelle. Zum Einzeichnen umfahren; ein Klick in eine "
                               "Beispielfläche löscht sie.")
            return
        self.modell.flaeche_entfernen(f["nr"])
        self._zeichne_trainingsflaechen()
        self.canvas.draw_idle()
        self._modell_anzeige(geaendert=self.modell.rf is not None)
        self._setze_status(f"Beispielfläche {f['nr']} ({'Baum' if f['klasse'] else 'kein Baum'}, {f['aufnahme']}) "
                           "gelöscht. Danach „Modell berechnen“.")

    def _lasso_fertig(self, verts):
        if self.aufn is None or not len(verts):
            return
        modus = self.var_zeichnen.get()
        v = np.asarray(verts, float)
        sv = self.ax_rgb.transData.transform(v)        # Ausdehnung in Bildschirmpixeln
        if len(verts) < 3 or (np.ptp(sv[:, 0]) < 6 and np.ptp(sv[:, 1]) < 6):
            if modus in ("ref_v", "ref_g", "baum", "kein"):
                self._flaeche_per_klick_loeschen(modus, float(v[0, 0]), float(v[0, 1]))
            return
        h, w = self.aufn.stapel.shape[1:]
        xy = np.clip(np.asarray(verts), [0, 0], [w - 1, h - 1])
        if modus in ("ref_v", "ref_g"):
            klasse = 1 if modus == "ref_v" else 0
            maske = self.maske if self._masken_schluessel is not None else None
            mname = self._vorgabe().name if maske is not None and self._vorgabe() else ""
            n = self.referenzen.hinzufuegen(self.aufn, xy, klasse, maske, mname)
            if n == 0:
                self._setze_status("Referenzfläche enthält keine gültigen (Masken-)Pixel.")
                return
            treffer = self._einblend_treffer(xy)
            if treffer:
                neu = self.referenzen.flaechen[-1]
                if not messagebox.askyesno("Baum schon vorhanden?", (
                        "Dieser Baum ist wahrscheinlich bereits eingezeichnet:\n\n" + "\n".join(treffer[:5]) +
                        "\n\nDerselbe Baum darf nicht zugleich Ableitungs- und Prüfbaum sein und nicht doppelt "
                        "gezählt werden.\n\nTrotzdem behalten?")):
                    self.referenzen.entfernen(neu["nr"])
                    self._zeichne_trainingsflaechen()
                    self.canvas.draw_idle()
                    self._referenz_anzeige()
                    self._setze_status("Referenz nicht übernommen (Baum schon vorhanden).")
                    return
            self._zeichne_trainingsflaechen()
            self.canvas.draw_idle()
            self._referenz_anzeige()
            self._setze_status(f"Referenz „{vk.REF_KLASSEN[klasse]}“ hinzugefügt ({n} Pixel"
                               + (f", nur Maske {mname}" if mname else "") + ").")
            return
        klasse = 1 if modus == "baum" else 0
        try:
            n = self.modell.flaeche_hinzufuegen(self.aufn, self._merkmale(), xy, klasse)
        except ValueError as e:
            messagebox.showerror("Beispielfläche nicht hinzugefügt", str(e))
            return
        if n == 0:
            self._setze_status("Fläche zu klein – bitte größer umfahren.")
            return
        self._zeichne_trainingsflaechen()
        self.canvas.draw_idle()
        self._modell_anzeige(geaendert=True)
        self._setze_status(f"Beispielfläche „{'Baum' if klasse else 'kein Baum'}“ hinzugefügt ({n} Pixel). "
                           "Nach dem Einzeichnen „Modell berechnen“ klicken.")

    def _zeichne_trainingsflaechen(self):
        for art in self.training_artists:
            try:
                art.remove()
            except (ValueError, NotImplementedError):
                pass
        self.training_artists = []
        if self.aufn is None:
            return
        for f in self.modell.flaechen:
            if not vk.gleiche_aufnahme(f, self.aufn):
                continue
            for ax in (self.ax_rgb, self.ax_idx):
                p = Polygon(f["xy"], closed=True, fill=False, edgecolor=KLASSEN_FARBE[f["klasse"]], linewidth=1.6,
                            linestyle="-" if f["klasse"] else "--")
                ax.add_patch(self._einblendung(p))
                self.training_artists.append(p)
        for f in self.referenzen.flaechen:
            if not vk.gleiche_aufnahme(f, self.aufn):
                continue
            for ax in (self.ax_rgb, self.ax_idx):
                p = Polygon(f["xy"], closed=True, fill=False, edgecolor=REF_FARBE[f["klasse"]], linewidth=2.0,
                            linestyle="-" if f["klasse"] else ":")
                ax.add_patch(self._einblendung(p))
                t = self._einblendung(ax.text(np.mean([q[0] for q in f["xy"]]), np.mean([q[1] for q in f["xy"]]),
                            ("V" if f["klasse"] else "G") + str(f["nr"]), color=REF_FARBE[f["klasse"]], fontsize=8,
                            fontweight="bold", ha="center", va="center"))
                self.training_artists += [p, t]
        # ab 0.20: hinterlegte Ableitungsbäume und eigene Referenzen aus benachbarten Aufnahmen (übertragen)
        if self.var_einblenden.get() and self._einblend["schluessel"] == self._aufn_schluessel():
            for e in self._einblend["flaechen"]:
                f = e["flaeche"]
                abl = e["art"] == "ableitung"
                farbe = HINTERLEGT_FARBE if abl else REF_FARBE[f["klasse"]]
                text = ("A·" if abl else "") + ("V" if f["klasse"] else "G") + str(f["nr"]) + ("" if abl else "*")
                for ax in (self.ax_rgb, self.ax_idx):
                    p = Polygon(e["xy"], closed=True, fill=False, edgecolor=farbe, linewidth=1.6 if abl else 1.2,
                                linestyle=(0, (4, 3)))
                    ax.add_patch(self._einblendung(p))
                    m = np.mean(e["xy"], axis=0)
                    tx = self._einblendung(ax.text(m[0], m[1], text, color=farbe, fontsize=8, fontweight="bold",
                                                   ha="center", va="center"))
                    self.training_artists += [p, tx]

    # ------------------------------------------------------------------ Referenzflächen -> Schwellen
    def _referenz_anzeige(self):
        v, g = self.referenzen.anzahl()
        bilder = len({(f["ordner"], f["aufnahme"]) for f in self.referenzen.flaechen})
        name = os.path.basename(self.referenzpfad) if self.referenzpfad else "ungespeichert"
        self.lbl_ref.config(text=f"[{name}] {v} vital / {g} geschädigt in {bilder} Bild(ern)"
                                 + ("  – empfohlen: je ≥ 5 Flächen aus mehreren Bildern" if min(v, g) < 5 else ""))

    def letzte_referenz_entfernen(self):
        if not self.referenzen.flaechen:
            return
        f = self.referenzen.flaechen[-1]
        self.referenzen.entfernen(f["nr"])
        self._zeichne_trainingsflaechen()
        self.canvas.draw_idle()
        self._referenz_anzeige()
        self._setze_status(f"Referenz {f['nr']} ({vk.REF_KLASSEN[f['klasse']]}, {f['aufnahme']}) entfernt.")

    def referenzen_speichern(self):
        if not self.referenzen.flaechen:
            messagebox.showinfo("Referenzen speichern", "Noch keine Referenzflächen eingezeichnet.")
            return
        start = os.path.join(self.wurzel or START_ORDNER, vk.AUSWERTUNG_UNTERORDNER)
        os.makedirs(start, exist_ok=True)
        pfad = filedialog.asksaveasfilename(title="Referenzflächen speichern", initialdir=start,
                                            initialfile="Referenzbaeume.joblib", defaultextension=".joblib",
                                            filetypes=[("Referenzflächen", "*.joblib")])
        if not pfad:
            return
        self.referenzen.speichern(pfad)
        self.referenzpfad = os.path.normpath(pfad)
        self._referenz_anzeige()
        self._setze_status(f"Referenzflächen gespeichert: {pfad}")

    def referenzen_laden(self):
        pfad = filedialog.askopenfilename(title="Referenzflächen laden", initialdir=self.wurzel or START_ORDNER,
                                          filetypes=[("Referenzflächen", "*.joblib")])
        if not pfad:
            return
        try:
            self.referenzen = vk.Referenzen.laden(pfad)
        except Exception as e:
            messagebox.showerror("Referenzen können nicht geladen werden", str(e))
            return
        self.referenzpfad = os.path.normpath(pfad)
        self._zeichne_trainingsflaechen()
        self.canvas.draw_idle()
        self._referenz_anzeige()
        self._einblenden_berechnen()

    def referenzen_hinzuladen(self):
        """Eine oder mehrere Referenzdateien zu den vorhandenen Flächen hinzufügen (statt sie zu ersetzen)."""
        pfade = filedialog.askopenfilenames(title="Referenzflächen hinzuladen (Mehrfachauswahl möglich)",
                                            initialdir=self.wurzel or START_ORDNER,
                                            filetypes=[("Referenzflächen", "*.joblib")])
        if not pfade:
            return
        neu = doppelt = 0
        fehler = []
        for pfad in pfade:
            try:
                n, d = self.referenzen.zusammenfuehren(vk.Referenzen.laden(pfad))
                neu, doppelt = neu + n, doppelt + d
            except Exception as e:
                fehler.append(f"{os.path.basename(pfad)}: {e}")
        if neu:
            self.referenzpfad = None          # Sammlung entspricht keiner Datei mehr -> als neue Datei speichern
        self._zeichne_trainingsflaechen()
        self.canvas.draw_idle()
        self._referenz_anzeige()
        text = (f"{neu} Referenzfläche(n) aus {len(pfade) - len(fehler)} Datei(en) hinzugefügt"
                + (f", {doppelt} bereits vorhandene übersprungen" if doppelt else "") + ".")
        if neu:
            text += " Zum Sichern „Referenzen speichern …“ verwenden (z. B. als neue Datei)."
        self._setze_status(text)
        self._einblenden_berechnen()
        if fehler:
            messagebox.showerror("Nicht alle Dateien geladen", "\n".join(fehler))

    def referenzen_auswerten(self):
        v, g = self.referenzen.anzahl()
        if not v or not g:
            messagebox.showinfo("Schwellen aus Referenzen",
                                "Bitte zuerst mindestens je eine Referenzfläche „vital“ und „geschädigt“ einzeichnen "
                                "(Zeichnen: „Referenz: vital“ / „Referenz: geschädigt“).\n\nEmpfohlen: je ≥ 5 Flächen "
                                "aus mehreren Bildern, nur sicher erkennbare Kronen.")
            return
        ergebnisse, ohne = [], []
        for i in vk.INDIZES:
            try:
                ergebnisse.append(self.referenzen.auswerten(i))
            except ValueError:
                ohne.append(i)
        if ohne:
            self._setze_status(f"Ohne gültige Referenzwerte (Kanal fehlt?): {', '.join(ohne)}")
        fenster = tk.Toplevel(self.root)
        fenster.configure(bg=self._farbe("hintergrund"))
        fenster.title("Schwellen aus Referenzbäumen")
        fenster.geometry("1150x520")
        ttk.Label(fenster, padding=6, wraplength=1100, text=(
            f"{v} vitale und {g} geschädigte Referenzflächen. AUC = Wahrscheinlichkeit, dass ein vitales Pixel einen "
            "höheren Wert hat als ein geschädigtes (0,5 = keine Trennung, 1,0 = perfekt). Youden-Schwelle = beste "
            "Einzelgrenze (max. Sensitivität + Spezifität − 1). „Flächen richtig“: Median je Referenzfläche mit der "
            "Youden-Schwelle eingeordnet. Sortiert nach AUC.")).pack(anchor="w")
        spalten = ["Index", "AUC", "Median vital", "Median geschädigt", "Youden-Schwelle", "J", "P5 vital",
                   "P95 geschädigt", "Flächen richtig"]
        tab = ttk.Treeview(fenster, columns=spalten, show="headings", height=len(ergebnisse))
        for c in spalten:
            tab.heading(c, text=c)
            tab.column(c, width=110 if c != "Index" else 80, anchor="e" if c != "Index" else "w")
        for e in sorted(ergebnisse, key=lambda e: -e["AUC"]):
            tab.insert("", tk.END, iid=e["Index"], values=[
                e["Index"], f"{e['AUC']:.3f}" + ("" if e["Richtung_ok"] else " (umgekehrt)"),
                f"{e['Median_vital']:.3f}", f"{e['Median_geschaedigt']:.3f}", f"{e['Youden_Schwelle']:.3f}",
                f"{e['Youden_J']:.2f}", f"{e['P5_vital']:.3f}", f"{e['P95_geschaedigt']:.3f}",
                f"{e['Flaechen_richtig']}/{e['Flaechen_gesamt']}"])
        tab.pack(fill=tk.BOTH, expand=True, padx=6)
        if self.var_index.get() in tab.get_children():
            tab.selection_set(self.var_index.get())
        unten = ttk.Frame(fenster, padding=6)
        unten.pack(fill=tk.X)
        schema = tk.StringVar(value="3")
        ttk.Label(unten, text="Schema:").pack(side=tk.LEFT)
        ttk.Radiobutton(unten, text="3 Klassen (gestresst < P5 vital, vital ≥ P95 geschädigt, dazwischen Übergang)",
                        value="3", variable=schema).pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(unten, text="2 Klassen (Youden-Schwelle)", value="2", variable=schema).pack(side=tk.LEFT, padx=4)
        knoepfe = ttk.Frame(fenster, padding=6)
        knoepfe.pack(fill=tk.X)

        def uebernehmen(indizes):
            ok, fehler = [], []
            for i in indizes:
                try:
                    sw, _ = self.referenzen.schwellen(i, schema.get(), round(float(self.var_s_anteil.get()), 2) / 100,
                                                      int(self.var_s_kronen.get()))
                    sw.kronen_nir = bool(self.var_kronen_nir.get())
                    sw.kronen_raster = bool(self.var_kronen_raster.get())
                    sw.baumregel = self._baumregel()
                except ValueError as e:
                    fehler.append(str(e))
                    continue
                self.schwellen_werte[i] = sw
                ok.append(i)
            idx = self.var_index.get()
            if idx in ok:
                self.schwellen_aktiv.add(idx)
            self._schwellen_laden()
            self.aktualisieren()
            self._setze_status(f"Schwellen aus Referenzen übernommen für: {', '.join(ok) or '–'}"
                               + (f"  |  nicht übernommen: {len(fehler)}" if fehler else ""))
            if fehler:
                messagebox.showwarning("Nicht übernommen", "\n".join(fehler), parent=fenster)

        def csv_speichern():
            start = os.path.join(self.wurzel or START_ORDNER, vk.AUSWERTUNG_UNTERORDNER)
            os.makedirs(start, exist_ok=True)
            pfad = filedialog.asksaveasfilename(parent=fenster, title="Referenzauswertung speichern", initialdir=start,
                                                initialfile="Referenzauswertung.csv", defaultextension=".csv",
                                                filetypes=[("CSV", "*.csv")])
            if pfad:
                vk.referenzen_als_csv(ergebnisse, pfad)
                self._setze_status(f"Referenzauswertung gespeichert: {pfad}")

        ttk.Button(knoepfe, text="Für ausgewählten Index übernehmen",
                   command=lambda: uebernehmen(tab.selection() or [self.var_index.get()])).pack(side=tk.LEFT)
        ttk.Button(knoepfe, text="Für alle Indizes übernehmen (nur AUC ≥ 0,5)",
                   command=lambda: uebernehmen(list(vk.INDIZES))).pack(side=tk.LEFT, padx=6)
        ttk.Button(knoepfe, text="Tabelle als CSV speichern …", command=csv_speichern).pack(side=tk.LEFT, padx=6)
        ttk.Button(knoepfe, text="Baumebene: Schwellen aus Baummedianen …",
                   command=lambda: self.baum_schwellen_starten(fenster)).pack(side=tk.LEFT, padx=6)
        ttk.Button(knoepfe, text="Schließen", command=fenster.destroy).pack(side=tk.RIGHT)
        self._ref_fenster = (fenster, tab, schema, uebernehmen)

    # ------------------------------------------------------------------ Prüfung an Prüfbäumen
    # ------------------------------------------------------------------ Ableitungsbäume hinterlegen (0.20)
    def _aufn_schluessel(self):
        a = self.aufn
        return None if a is None else (os.path.normcase(os.path.normpath(a.ordner)), a.name, bool(a.geschaerft))

    def _hinterlegen(self, pfade):
        h = vk.Referenzen.laden(pfade[0])
        for q in pfade[1:]:
            h.zusammenfuehren(vk.Referenzen.laden(q))
        self.hinterlegt = h
        self.hinterlegt_pfade = [os.path.normpath(q) for q in pfade]

    def ableitung_hinterlegen(self):
        """Ableitungsbäume als feste Vergleichsgrundlage laden: Sie werden in jeder Aufnahme eingeblendet (auch aus
        überlappenden Aufnahmen und anderen Sets übertragen) und bei der Prüfung an Prüfbäumen abgeglichen."""
        if self.hinterlegt.flaechen and not messagebox.askyesno(
                "Ableitung hinterlegen", f"Es sind bereits {len(self.hinterlegt.flaechen)} Ableitungsbäume hinterlegt "
                f"({', '.join(os.path.basename(q) for q in self.hinterlegt_pfade)}).\n\nErsetzen? "
                "(„Nein“ entfernt die Hinterlegung.)"):
            self.hinterlegt, self.hinterlegt_pfade = vk.Referenzen(), []
            self._einblenden_berechnen()
            self._setze_status("Hinterlegte Ableitungsbäume entfernt.")
            return
        pfade = filedialog.askopenfilenames(
            title="Ableitungsbäume hinterlegen (Referenzdatei[en] der Ableitung – werden nur eingeblendet)",
            initialdir=self.wurzel or START_ORDNER, filetypes=[("Referenzflächen", "*.joblib")])
        if not pfade:
            return
        try:
            self._hinterlegen(list(pfade))
        except Exception as e:
            messagebox.showerror("Ableitungsbäume können nicht geladen werden", str(e))
            return
        self.var_einblenden.set(True)
        v, g = self.hinterlegt.anzahl()
        self._setze_status(f"Ableitungsbäume hinterlegt: {v} vital, {g} geschädigt "
                           f"({', '.join(os.path.basename(q) for q in self.hinterlegt_pfade)}). Sie werden weiß "
                           "gestrichelt eingeblendet (A·V/A·G), eigene Referenzen aus Nachbarbildern farbig gestrichelt (*).")
        self._einblenden_berechnen()

    def _einblenden_berechnen(self):
        """Überträgt hinterlegte Ableitungsbäume und eigene Referenzen anderer Aufnahmen in die angezeigte Aufnahme
        (im Hintergrund; nahe Aufnahmen per GPS, Abgleich per Bildmerkmalen)."""
        self._einblend["lauf"] += 1
        lauf = self._einblend["lauf"]
        a = self.aufn
        if a is None or not self.var_einblenden.get():
            self._einblend.update(schluessel=None, flaechen=[], ohne=[], fertig=lauf)
            if a is not None:
                self._zeichne_trainingsflaechen()
                self.canvas.draw_idle()
            return
        schl = self._aufn_schluessel()
        abl = list(self.hinterlegt.flaechen)
        eigen = [f for f in self.referenzen.flaechen if not vk.gleiche_aufnahme(f, a)]
        if not abl and not eigen:
            self._einblend.update(schluessel=schl, flaechen=[], ohne=[], fertig=lauf)
            self._zeichne_trainingsflaechen()
            self.canvas.draw_idle()
            return
        ids_abl = {id(f) for f in abl}

        def arbeit():
            try:
                aus, ohne = vk.flaechen_uebertragen(abl + eigen, a.ordner, a.name, a.geschaerft, ziel_aufn=a)
                for e in aus:
                    e["art"] = "ableitung" if id(e["flaeche"]) in ids_abl else "eigen"
                self.q.put(("einblenden_fertig", (lauf, schl, aus, ohne, None)))
            except Exception as e:
                traceback.print_exc()
                self.q.put(("einblenden_fertig", (lauf, schl, [], [], str(e))))
        threading.Thread(target=arbeit, daemon=True).start()

    def _einblenden_ende(self, lauf, schl, aus, ohne, fehler):
        if lauf != self._einblend["lauf"] or schl != self._aufn_schluessel():
            return                                   # inzwischen anderes Bild angezeigt
        self._einblend.update(schluessel=schl, flaechen=aus, ohne=ohne, fertig=lauf)
        self._zeichne_trainingsflaechen()
        self.canvas.draw_idle()
        if fehler:
            self._setze_status(f"Einblenden nicht möglich: {fehler}")
            return
        n_abl = sum(1 for e in aus if e["art"] == "ableitung")
        n_eig = len(aus) - n_abl
        if aus or ohne:
            text = (f"Eingeblendet: {n_abl} Ableitungsbaum/-bäume, {n_eig} eigene Referenz(en) aus Nachbarbildern"
                    + (f" (aus {', '.join(sorted({e['quelle'] for e in aus}))})" if aus else ""))
            if ohne:
                text += (f". Nicht abgleichbar (selbst vergleichen): "
                         + ", ".join(f"{vk._set_name(o)} {n}" for o, n, _ in ohne[:6]))
            self._setze_status(text)

    def _einblend_treffer(self, xy):
        """Eingeblendete Bäume, auf denen ein neuer Umriss liegt (Texte für die Warnung)."""
        if not self.var_einblenden.get() or self._einblend["schluessel"] != self._aufn_schluessel():
            return []
        aus = []
        for e in self._einblend["flaechen"]:
            _, gleich = vk.umrisse_gleicher_baum(np.asarray(xy, float), e["xy"])
            if gleich:
                f = e["flaeche"]
                aus.append(("Ableitungsbaum " if e["art"] == "ableitung" else "eigene Referenz ")
                           + f"{'V' if f['klasse'] else 'G'}{f['nr']} ({vk.REF_KLASSEN[f['klasse']]}, {e['quelle']})")
        return aus

    def schwellen_pruefen(self):
        """Prüft alle festgelegten Schwellen (je Index) an getrennten Prüfbäumen (eigene Referenzdatei[en])."""
        if self.stapel_laeuft:
            messagebox.showinfo("Schwellen prüfen", "Es läuft gerade eine Auswertung. Bitte warten oder abbrechen.")
            return
        schwellen = {i: self.schwellen_werte[i] for i in vk.INDIZES if i in self.schwellen_werte}
        if not schwellen:
            messagebox.showinfo("Schwellen prüfen",
                                "Es sind noch keine Schwellwerte festgelegt.\n\nZuerst Schwellen festlegen, z. B. über "
                                "„Schwellen aus Referenzen …“ mit den Ableitungsbäumen, dann hier die Prüfbäume laden.")
            return
        vorgabe = self._vorgabe(fuer_ordner=True)
        if vorgabe is None:
            messagebox.showinfo("Schwellen prüfen", "Für die Prüfung je Baum wird eine Maske benötigt. "
                                                    "Bitte „Bäume (Modell)“ (empfohlen) oder „Vegetation“ wählen.")
            return
        pfade = filedialog.askopenfilenames(
            title="Prüfbäume laden (Referenzdatei[en], die NICHT zur Ableitung der Schwellen verwendet wurden)",
            initialdir=self.wurzel or START_ORDNER, filetypes=[("Referenzflächen", "*.joblib")])
        if not pfade:
            return
        try:
            pruefung = vk.Referenzen.laden(pfade[0])        # eine Datei: Nummern wie in der Datei
            for p in pfade[1:]:
                pruefung.zusammenfuehren(vk.Referenzen.laden(p))
        except Exception as e:
            messagebox.showerror("Prüfbäume können nicht geladen werden", str(e))
            return
        v, g = pruefung.anzahl()
        if not pruefung.flaechen:
            messagebox.showinfo("Schwellen prüfen", "Die Datei enthält keine Referenzflächen.")
            return
        # ab 0.20: Abgleich über Bilder und Sets hinweg (im Hintergrund), danach Rückfrage und Start
        vergleich = self.hinterlegt if self.hinterlegt.flaechen else self.referenzen
        ableitung_name = (", ".join(os.path.basename(q) for q in self.hinterlegt_pfade) if self.hinterlegt.flaechen
                          else (self.referenzpfad or "(ungespeichert/keine)"))
        self.stapel_laeuft = True
        self.abbruch.clear()
        self.btn_stapel.config(state=tk.DISABLED)
        self.btn_abbruch.config(state=tk.NORMAL)
        self._pruef_vorbereitung = {"pruefung": pruefung, "pfade": [os.path.normpath(q) for q in pfade],
                                    "vorgabe": vorgabe, "schwellen": dict(schwellen), "ableitung": ableitung_name,
                                    "mit_ableitung": bool(vergleich.flaechen)}

        def arbeit():
            try:
                dopp = vk.referenz_dopplungen(vergleich, pruefung, abbrechen=self.abbruch.is_set,
                                              fortschritt=lambda x: self.q.put(("dopplung_fortschritt", x)))
                self.q.put(("dopplung_fertig", (dopp, None)))
            except Exception as e:
                traceback.print_exc()
                self.q.put(("dopplung_fertig", (None, str(e))))
        threading.Thread(target=arbeit, daemon=True).start()

    def _dopplung_ende(self, dopp, fehler):
        self.stapel_laeuft = False
        self.btn_stapel.config(state=tk.NORMAL)
        self.btn_abbruch.config(state=tk.DISABLED)
        self.fortschritt.config(value=0)
        vb = self._pruef_vorbereitung
        pruefung = vb["pruefung"]
        if self.abbruch.is_set():
            self._setze_status("Prüfung abgebrochen.")
            return
        if fehler:
            if not messagebox.askyesno("Abgleich nicht möglich", f"Der Abgleich der Prüfbäume ist fehlgeschlagen:\n"
                                       f"{fehler}\n\nOhne Abgleich prüfen?"):
                return
            dopp = {"ableitung": [], "innerhalb": [], "fraglich": [], "ohne_abgleich": []}
        v, g = pruefung.anzahl()
        bilder = len({(f["ordner"], f["aufnahme"]) for f in pruefung.flaechen})
        regeln = sorted({vk.BAUMREGELN.get(s.baumregel, s.baumregel) for s in vb["schwellen"].values()})
        text = (f"Prüfbäume: {v} vital, {g} geschädigt in {bilder} Bild(ern).\n"
                + (f"⚠ UNTERSCHIEDLICHE BAUMREGELN je Index: {', '.join(regeln)} – Baumregel einmal neu wählen "
                   "(gilt dann für alle Indizes).\n" if len(regeln) > 1 else f"Baumregel: {regeln[0]}\n")
                + f"Abgeglichen mit: {vb['ableitung']}\n"
                f"Maske: {vb['vorgabe'].beschreibung()}\n"
                f"Indizes mit Schwellen: {', '.join(vb['schwellen'])}\n"
                + ("Herkunft der Schwellen: Pixel der Referenzflächen – empfohlen ist „Baumebene: Schwellen aus "
                   "Baummedianen …“ (passt zur Baumregel „Median je Baum“).\n"
                   if any(s.herkunft.startswith("Referenzflächen") for s in vb["schwellen"].values()) else "")
                + "\n"
                "Für jede Prüffläche wird der Baum mit der größten Überdeckung bewertet "
                "(gleiche Maske, Kronentrennung und Baumregel wie in der Auswertung).")
        if not vb["mit_ableitung"]:
            text += ("\n\nHinweis: Keine Ableitungsbäume geladen oder hinterlegt – geprüft wurde nur, ob Prüfbäume "
                     "doppelt vorkommen.")
        if dopp["ohne_abgleich"]:
            text += (f"\n\n{len(dopp['ohne_abgleich'])} nahe Bildpaar(e) ließen sich nicht abgleichen (selbst "
                     "vergleichen): " + ", ".join(f"{a} ↔ {b}" for a, b, _ in dopp["ohne_abgleich"][:4]))
        ausschliessen = []
        if dopp["ableitung"] or dopp["innerhalb"]:
            ausschliessen = list({id(d["pruef"]): d["pruef"] for d in dopp["ableitung"]}.values())
            ausschliessen += [d["b"] for d in dopp["innerhalb"] if not any(d["b"] is x for x in ausschliessen)]
            text += (f"\n\n⚠ Dopplungen gefunden:\n{vk.dopplungen_text(dopp)}\n\n"
                     f"„Ja“ = {len(ausschliessen)} doppelte Prüfbäume ausschließen und prüfen\n"
                     "„Nein“ = alle prüfen (Ergebnis zu optimistisch)\n„Abbrechen“ = nicht prüfen")
            antwort = messagebox.askyesnocancel("Schwellen an Prüfbäumen prüfen", text)
            if antwort is None:
                return
            if not antwort:
                ausschliessen = []
        else:
            text += "\n\nKeine sicheren Dopplungen mit Ableitungsbäumen und keine doppelt eingezeichneten Prüfbäume."
            if dopp.get("fraglich"):
                text += "\n\n" + vk.dopplungen_text(dopp)
            if not messagebox.askyesno("Schwellen an Prüfbäumen prüfen", text + "\n\nStarten?"):
                return
        if ausschliessen:
            gefiltert = vk.Referenzen()
            gefiltert.flaechen = [f for f in pruefung.flaechen if not any(f is x for x in ausschliessen)]
            pruefung = gefiltert
        vorgabe, schwellen = vb["vorgabe"], vb["schwellen"]
        self.stapel_laeuft = True
        self.abbruch.clear()
        self.btn_stapel.config(state=tk.DISABLED)
        self.btn_abbruch.config(state=tk.NORMAL)
        self._pruef_kontext = {"pfade": vb["pfade"], "vorgabe": vorgabe, "schwellen": dict(schwellen),
                               "ueberschneidungen": [(d["pruef"]["nr"], d["abl"]["nr"]) for d in dopp["ableitung"]],
                               "dopplungen": vk.dopplungen_protokoll(dopp),
                               "ausgeschlossen": [{"nr": f["nr"], "aufnahme": f["aufnahme"],
                                                   "set": vk._set_name(f["ordner"])} for f in ausschliessen],
                               "ableitung": vb["ableitung"]}

        def arbeit():
            try:
                erg = vk.pruefe_schwellen(pruefung, vorgabe, schwellen, abbrechen=self.abbruch.is_set,
                                          fortschritt=lambda x: self.q.put(("pruef_fortschritt", x)))
                self.q.put(("pruef_fertig", (erg, None)))
            except Exception as e:
                traceback.print_exc()
                self.q.put(("pruef_fertig", (None, str(e))))
        threading.Thread(target=arbeit, daemon=True).start()

    # ------------------------------------------------------------------ Schwellen aus Baummedianen (Version 0.17)
    def baum_schwellen_starten(self, eltern=None):
        """Schwellen für die Baumregel „Median je Baum“ aus den Baummedianen der geladenen Referenzbäume."""
        if self.stapel_laeuft:
            messagebox.showinfo("Schwellen aus Baummedianen", "Es läuft gerade eine Auswertung.", parent=eltern)
            return
        v, g = self.referenzen.anzahl()
        if v < 2 or g < 2:
            messagebox.showinfo("Schwellen aus Baummedianen", "Es werden mindestens je 2 vitale und geschädigte "
                                "Referenzbäume benötigt (empfohlen: je ≥ 10).", parent=eltern)
            return
        vorgabe = self._vorgabe(fuer_ordner=True)
        if vorgabe is None:
            messagebox.showinfo("Schwellen aus Baummedianen", "Für die Bäume wird eine Maske benötigt. Bitte "
                                "„Bäume (Modell)“ wählen – wie in der späteren Auswertung.", parent=eltern)
            return
        basis = {}
        for i in vk.INDIZES:
            try:
                s, _ = self.referenzen.schwellen(i, "2", round(float(self.var_s_anteil.get()), 2) / 100,
                                                 int(self.var_s_kronen.get()))
            except ValueError:
                continue
            s.kronen_nir = bool(self.var_kronen_nir.get())
            s.kronen_raster = bool(self.var_kronen_raster.get())
            basis[i] = s
        if not basis:
            messagebox.showinfo("Schwellen aus Baummedianen", "Für keinen Index lassen sich Schwellen ableiten.",
                                parent=eltern)
            return
        bilder = len({(f["ordner"], f["aufnahme"]) for f in self.referenzen.flaechen})
        if not messagebox.askyesno("Schwellen aus Baummedianen", (
                f"{v} vitale und {g} geschädigte Referenzbäume aus {bilder} Bild(ern).\n\n"
                f"Jede Referenzfläche wird dem Baum mit der größten Überdeckung zugeordnet – mit derselben Maske und "
                f"Kronentrennung wie in der Auswertung:\nMaske: {vorgabe.beschreibung()}\nKronentrennung: "
                + ("Pflanzraster" if self.var_kronen_raster.get() else f"Abstand {self.var_s_kronen.get()} px")
                + "\n\nDie Mediane dieser Bäume ergeben je Index die Youden-Schwelle (2 Klassen, Baumregel "
                  "„Median je Baum“).\n\nNur die Ableitungsbäume laden – Prüfbäume NICHT, die dienen danach zur "
                  "Kontrolle („Schwellen an Prüfbäumen prüfen …“).\n\nStarten?"), parent=eltern):
            return
        self.stapel_laeuft = True
        self.abbruch.clear()
        self.btn_stapel.config(state=tk.DISABLED)
        self.btn_abbruch.config(state=tk.NORMAL)
        ref = self.referenzen

        def arbeit():
            try:
                erg = vk.baum_schwellen(ref, vorgabe, basis, abbrechen=self.abbruch.is_set,
                                        fortschritt=lambda t: self.q.put(("baumschw_fortschritt", t)))
                self.q.put(("baumschw_fertig", (erg, vorgabe, None)))
            except Exception as e:
                traceback.print_exc()
                self.q.put(("baumschw_fertig", (None, vorgabe, str(e))))
        threading.Thread(target=arbeit, daemon=True).start()

    def _baum_schwellen_ende(self, erg, vorgabe, fehlertext):
        self.stapel_laeuft = False
        self.btn_stapel.config(state=tk.NORMAL)
        self.btn_abbruch.config(state=tk.DISABLED)
        self.fortschritt.config(value=0)
        if fehlertext:
            messagebox.showerror("Schwellen aus Baummedianen", fehlertext)
            return
        ergebnisse, neu, fehler = erg
        self._setze_status(f"Schwellen aus Baummedianen berechnet für {len(neu)} Indizes"
                           + (f" – Hinweise: {len(fehler)}" if fehler else ""))
        fenster = tk.Toplevel(self.root)
        fenster.configure(bg=self._farbe("hintergrund"))
        fenster.title("Schwellen aus Baummedianen (Baumregel „Median je Baum“)")
        fenster.geometry("1150x480")
        ttk.Label(fenster, padding=6, wraplength=1100, text=(
            "Je Index: Youden-Schwelle aus den Medianen der Ableitungsbäume (vital: Median ≥ Schwelle). J = Sensitivität "
            "+ Spezifität − 1 auf Baumebene (1 = alle Ableitungsbäume getrennt), AUC Baum = Anteil richtig geordneter "
            "Paare. Spannweiten der Baummediane zeigen die Lücke zwischen den Klassen. Zum Vergleich: Pixel-Schwelle "
            "aus „Schwellen aus Referenzen“. Kontrolle anschließend an getrennten Prüfbäumen. Sortiert nach J, AUC."
            + ("\nHinweise: " + "; ".join(f"{a}: {m}" for a, m in fehler[:6]) if fehler else ""))).pack(anchor="w")
        sp = ["Index", "Schwelle", "J", "AUC Baum", "Bäume v/g", "kein Baum", "Median vital", "Median geschädigt",
              "Pixel-Schwelle"]
        tab = ttk.Treeview(fenster, columns=sp, show="headings", height=min(len(ergebnisse), 12))
        for c in sp:
            tab.heading(c, text=c)
            tab.column(c, width=140 if c.startswith("Median") else 95, anchor="w" if c == "Index" else "e")
        for e in sorted(ergebnisse, key=lambda e: (-e["Youden_J"], -e["AUC_Baum"])):
            tab.insert("", tk.END, iid=e["Index"], values=[
                e["Index"], f"{e['Schwelle']:.3f}", f"{e['Youden_J']:.2f}", f"{e['AUC_Baum']:.2f}",
                f"{e['Baeume_vital']}/{e['Baeume_geschaedigt']}", e["Kein_Baum"],
                f"{e['Median_vital_min']:.3f} – {e['Median_vital_max']:.3f}",
                f"{e['Median_geschaedigt_min']:.3f} – {e['Median_geschaedigt_max']:.3f}", f"{e['Pixel_Schwelle']:.3f}"])
        tab.pack(fill=tk.BOTH, expand=True, padx=6)
        knoepfe = ttk.Frame(fenster, padding=6)
        knoepfe.pack(fill=tk.X)

        def uebernehmen(indizes):
            ok = [i for i in indizes if i in neu]
            for i in ok:
                self.schwellen_werte[i] = neu[i]
            if self.var_index.get() in ok:
                self.schwellen_aktiv.add(self.var_index.get())
            self._schwellen_laden()
            self.aktualisieren()
            self._setze_status(f"Schwellen aus Baummedianen übernommen (Baumregel „Median je Baum“) für: "
                               f"{', '.join(ok) or '–'}")

        def csv_speichern():
            start = os.path.join(self.wurzel or START_ORDNER, vk.AUSWERTUNG_UNTERORDNER)
            os.makedirs(start, exist_ok=True)
            pfad = filedialog.asksaveasfilename(parent=fenster, title="Schwellen aus Baummedianen speichern",
                                                initialdir=start, initialfile="Schwellen_Baummediane.csv",
                                                defaultextension=".csv", filetypes=[("CSV", "*.csv")])
            if pfad:
                vk.baum_schwellen_als_csv(ergebnisse, pfad, {
                    "software": vk.VERSION, "erstellt": vk._dt.datetime.now().isoformat(timespec="seconds"),
                    "referenzdatei": self.referenzpfad or "(ungespeichert)", "maske": vorgabe.protokoll(),
                    "schwellen": {i: s.protokoll() for i, s in neu.items()}, "hinweise": fehler})
                self._setze_status(f"Gespeichert: {pfad} (+ _Parameter.json)")

        ttk.Button(knoepfe, text="Für ausgewählten Index übernehmen",
                   command=lambda: uebernehmen(tab.selection() or [self.var_index.get()])).pack(side=tk.LEFT)
        ttk.Button(knoepfe, text="Für alle Indizes übernehmen",
                   command=lambda: uebernehmen(list(neu))).pack(side=tk.LEFT, padx=6)
        ttk.Button(knoepfe, text="Tabelle als CSV speichern …", command=csv_speichern).pack(side=tk.LEFT, padx=6)
        ttk.Button(knoepfe, text="Schließen", command=fenster.destroy).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ Kanalanalyse (Version 0.12)
    def kanalanalyse(self):
        """Trennung je Kanal/Index (zwischen vs. innerhalb der Bäume), Korrelation, PCA und Kanalsätze an den
        geladenen Referenzbäumen. Fehlende Kanalwerte (Dateien vor 0.12) werden vorher aus den Bildern ergänzt."""
        if self.stapel_laeuft:
            messagebox.showinfo("Kanalanalyse", "Es läuft gerade eine Auswertung. Bitte warten oder abbrechen.")
            return
        v, g = self.referenzen.anzahl()
        if v + g < 3:
            messagebox.showinfo("Kanalanalyse", "Bitte zuerst Referenzbäume laden oder einzeichnen "
                                                "(empfohlen: je ≥ 5 vitale und geschädigte Bäume).")
            return
        offen = [f for f in self.referenzen.flaechen if "kanaele" not in f]
        if not offen:
            self._kanalanalyse_ende(None, [])
            return
        vorgabe = None
        if any(f.get("maske", "keine") != "keine" for f in offen):
            vorgabe = self._vorgabe(fuer_ordner=True)
            if vorgabe is None:
                messagebox.showinfo("Kanalanalyse", "Die Referenzflächen wurden mit Maske eingezeichnet. Zum "
                                                    "Ergänzen der Kanalwerte bitte dieselbe Maske wählen "
                                                    "(meist „Bäume (Modell)“ mit dem verwendeten Baummodell).")
                return
        bilder = len({(f["ordner"], f["aufnahme"]) for f in offen})
        text = (f"{len(offen)} Referenzfläche(n) stammen aus einer älteren Datei und enthalten noch keine Kanalwerte.\n\n"
                f"Sie werden aus {bilder} Bild(ern) ergänzt"
                + (f" mit der Maske:\n{vorgabe.beschreibung()}" if vorgabe else " (ohne Maske)") +
                ".\n\nDanach am besten „Referenzen speichern …“, damit das Ergänzen nicht wiederholt werden muss.\n\n"
                "Starten?")
        if not messagebox.askyesno("Kanalanalyse", text):
            return
        self.stapel_laeuft = True
        self.abbruch.clear()
        self.btn_stapel.config(state=tk.DISABLED)
        self.btn_abbruch.config(state=tk.NORMAL)
        self._kanal_vorgabe = vorgabe

        def arbeit():
            try:
                n, fehler = vk.ergaenze_kanalwerte(self.referenzen, vorgabe, abbrechen=self.abbruch.is_set,
                                                   fortschritt=lambda t: self.q.put(("kanal_fortschritt", t)))
                self.q.put(("kanal_fertig", (n, fehler)))
            except Exception as e:
                traceback.print_exc()
                self.q.put(("kanal_fertig", (None, [("—", str(e))])))
        threading.Thread(target=arbeit, daemon=True).start()

    def _kanalanalyse_ende(self, ergaenzt, fehler):
        if self.stapel_laeuft:
            self.stapel_laeuft = False
            self.btn_stapel.config(state=tk.NORMAL)
            self.btn_abbruch.config(state=tk.DISABLED)
            self.fortschritt.config(value=0)
        if fehler:
            messagebox.showwarning("Kanalanalyse", "Nicht alle Kanalwerte konnten ergänzt werden:\n\n"
                                   + "\n".join(f"{a}: {m}" for a, m in fehler[:15]))
        try:
            erg = vk.kanalanalyse(self.referenzen)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Kanalanalyse", str(e))
            return
        if ergaenzt:
            self._setze_status(f"Kanalwerte für {ergaenzt} Referenzfläche(n) ergänzt – zum Sichern „Referenzen "
                               "speichern …“.")
        self._kanalanalyse_fenster(erg)

    def _kanalanalyse_fenster(self, erg):
        fenster = tk.Toplevel(self.root)
        fenster.configure(bg=self._farbe("hintergrund"))
        fenster.title("Kanalanalyse an den Referenzbäumen")
        fenster.geometry("1250x640")
        gruppen = list(dict.fromkeys(z["Gruppe"] for z in erg["trennung"]))
        oben = ttk.Frame(fenster, padding=6)
        oben.pack(fill=tk.X)
        ttk.Label(oben, text="Gruppe:").pack(side=tk.LEFT)
        var_gruppe = tk.StringVar(value=gruppen[0])
        cb = ttk.Combobox(oben, values=gruppen, textvariable=var_gruppe, state="readonly", width=12)
        cb.pack(side=tk.LEFT, padx=4)
        ttk.Label(oben, style="Hinweis.TLabel", wraplength=1050, text=(
            "„alle“ = alle geladenen Referenzbäume; je Set getrennt, weil Sonnenstand und DLS-Kalibrierung nur "
            "innerhalb eines Flugs vergleichbar sind. Jeder Baum zählt mit gleich vielen Pixeln.")).pack(side=tk.LEFT)
        nb = ttk.Notebook(fenster)
        nb.pack(fill=tk.BOTH, expand=True, padx=6)

        def tabelle(eltern, spalten, breiten=None):
            rahmen = ttk.Frame(eltern)
            tab = ttk.Treeview(rahmen, columns=spalten, show="headings")
            sb = ttk.Scrollbar(rahmen, orient=tk.VERTICAL, command=tab.yview)
            tab.configure(yscrollcommand=sb.set)
            for i, c in enumerate(spalten):
                tab.heading(c, text=c)
                tab.column(c, width=(breiten or {}).get(c, 95), anchor="w" if i == 0 else "e")
            tab.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            rahmen.pack(fill=tk.BOTH, expand=True)
            return tab

        def zahl(v, n=3):
            return "–" if v is None or (isinstance(v, float) and not np.isfinite(v)) else (
                f"{v:.{n}f}" if isinstance(v, float) else str(v))

        # Reiter 1: Trennung
        r1 = ttk.Frame(nb, padding=4)
        nb.add(r1, text="Trennung je Kanal/Index")
        ttk.Label(r1, wraplength=1180, text=(
            "ICC = Anteil der Streuung, der auf Unterschiede zwischen den Bäumen entfällt (hoch = Bäume unterscheiden "
            "sich stark bei wenig Streuung im Baum). Abstand = Unterschied vital − geschädigt (Baummittel) in "
            "Einheiten der Streuung innerhalb eines Baums. d und AUC auf Baumebene. Sortiert nach Abstand."
        )).pack(anchor="w")
        sp1 = ["Merkmal", "Art", "Abstand (Std innen)", "Cohen d", "AUC Baum", "ICC",
               "Std zwischen", "Std innen", "Mittel vital", "Mittel geschädigt", "Bäume v/g"]
        t1 = tabelle(r1, sp1, {"Merkmal": 90, "Art": 60})
        # Reiter 2: Korrelation
        r2 = ttk.Frame(nb, padding=4)
        nb.add(r2, text="Korrelation der Kanäle")
        kan = [vk.KANAL_ANZEIGE[k] for k in erg["info"]["kanaele"]]
        ttk.Label(r2, wraplength=1180, text=(
            "Pearson-Korrelation zwischen den Kanälen: oben je Pixel, unten zwischen den Baummittelwerten. "
            "Werte nahe 1 = die Kanäle zeigen weitgehend dasselbe.")).pack(anchor="w")
        t2 = tabelle(r2, ["Ebene", "Kanal"] + kan)
        # Reiter 3: PCA
        r3 = ttk.Frame(nb, padding=4)
        nb.add(r3, text="PCA")
        ttk.Label(r3, wraplength=1180, text=(
            "Hauptkomponentenanalyse der standardisierten Kanäle. Anteil = erklärte Varianz; Spalten der Kanäle = "
            "Ladungen (Korrelation von Kanal und Komponente).")).pack(anchor="w")
        t3 = tabelle(r3, ["Ebene", "Komponente", "Anteil %", "kumuliert %"] + kan)
        # Reiter 4: Kanalsätze
        r4 = ttk.Frame(nb, padding=4)
        nb.add(r4, text="Kanalsätze")
        ttk.Label(r4, wraplength=1180, text=(
            "Erklärte Varianz = wie gut die 5 Kanäle linear aus dem Kanalsatz vorhersagbar sind (Mittel der R²; "
            "1 = kein Informationsverlust). R² NIR / R² Red Edge = Vorhersage des weggelassenen Kanals. "
            "LDA = lineare Diskriminanzanalyse, je Baum ausgelassen geprüft (Mehrheit der Pixel); "
            "k-means = Übereinstimmung zweier Cluster der Baummittel mit vital/geschädigt. "
            "„ohne Blau“ = Kanäle wie bei der DJI Mavic 3M (Näherung, andere Bandlagen).")).pack(anchor="w")
        sp4 = ["Kanalsatz", "Kanäle", "Erkl. Varianz Pixel", "Erkl. Varianz Baum", "R² NIR (Pixel)",
               "R² Red Edge (Pixel)", "LDA Treffer Baum", "k-means Baum"]
        t4 = tabelle(r4, sp4, {"Kanäle": 200})
        # Reiter 5: Rechenaufwand (erst nach „Rechenaufwand messen …“)
        r5 = ttk.Frame(nb, padding=4)
        nb.add(r5, text="Rechenaufwand")
        lbl5 = ttk.Label(r5, wraplength=1180, text=(
            "Noch nicht gemessen – unten „Rechenaufwand messen …“ (dauert einige Minuten). Datenmenge der Rohdateien "
            "und des Reflektanzstapels je Aufnahme; Vorverarbeitung = Zeit je Kanal (aus Rohbildern gemessen) x "
            "Kanalzahl (Hochrechnung); Random Forest (wie Baummodell) und LDA auf den Reflektanzen des Kanalsatzes, "
            "geprüft über ganze Bäume (5-fach), Zeiten mit einem Rechenkern."))
        lbl5.pack(anchor="w")
        sp5 = ["Kanalsatz", "Kanäle", "MB roh/Aufn.", "MB Stapel/Aufn.", "Vorverarb. s/Aufn.", "RF Treffer Baum",
               "RF ausgewogen", "RF Training s", "RF s/Mio px", "LDA Treffer Baum", "LDA Training s", "LDA s/Mio px"]
        t5 = tabelle(r5, sp5, {"Kanäle": 200})
        aufwand = {"erg": None}

        def fuellen(*_):
            gname = var_gruppe.get()
            for t in (t1, t2, t3, t4):
                t.delete(*t.get_children())
            zt = [z for z in erg["trennung"] if z["Gruppe"] == gname]
            for z in sorted(zt, key=lambda z: -(z.get("Abstand_in_Std_innen") or 0)):
                t1.insert("", tk.END, values=[
                    z["Merkmal"], z["Art"], zahl(z.get("Abstand_in_Std_innen"), 2), zahl(z.get("Cohen_d_Baum"), 2),
                    zahl(z.get("AUC_Baum")),
                    zahl(z["ICC"]), zahl(z["Std_zwischen_Baeumen"], 4), zahl(z["Std_innerhalb_Baum"], 4),
                    zahl(z.get("Mittel_vital"), 4), zahl(z.get("Mittel_geschaedigt"), 4),
                    f"{z.get('Baeume_vital', '–')}/{z.get('Baeume_geschaedigt', '–')}"])
            for z in erg["korrelation"]:
                if z["Gruppe"] == gname:
                    t2.insert("", tk.END, values=[z["Ebene"], z["Kanal"]] + [zahl(z[k], 2) for k in kan])
            for z in erg["pca"]:
                if z["Gruppe"] == gname:
                    t3.insert("", tk.END, values=[z["Ebene"], z["Komponente"], f"{z['Anteil'] * 100:.1f}",
                                                  f"{z['Anteil_kumuliert'] * 100:.1f}"] + [zahl(z[k], 2) for k in kan])
            for z in erg["kanalsaetze"]:
                if z["Gruppe"] == gname:
                    t4.insert("", tk.END, values=[
                        z["Kanalsatz"], z["Kanaele"], zahl(z["Erklaerte_Varianz_Pixel"]),
                        zahl(z["Erklaerte_Varianz_Baum"]), zahl(z.get("R2_NIR_Pixel")),
                        zahl(z.get("R2_Red Edge_Pixel")), zahl(z.get("LDA_Trefferquote_Baum"), 2),
                        zahl(z.get("kMeans_Uebereinstimmung_Baum"), 2)])

            t5.delete(*t5.get_children())
            for z in (aufwand["erg"] or {}).get("zeilen", []):
                if z["Gruppe"] == gname:
                    t5.insert("", tk.END, values=[
                        z["Kanalsatz"], z["Kanaele"], zahl(z.get("MB_roh_je_Aufnahme"), 1),
                        zahl(z.get("MB_Stapel_je_Aufnahme"), 1),
                        zahl(z.get("Vorverarbeitung_s_je_Aufnahme_hochgerechnet"), 2),
                        zahl(z.get("RF_Treffer_Baum"), 2), zahl(z.get("RF_Treffer_ausgewogen"), 2),
                        zahl(z.get("RF_Training_s"), 2), zahl(z.get("RF_Vorhersage_s_je_Mio_Pixel"), 2),
                        zahl(z.get("LDA_Treffer_Baum"), 2), zahl(z.get("LDA_Training_s"), 4),
                        zahl(z.get("LDA_Vorhersage_s_je_Mio_Pixel"), 4)])

        cb.bind("<<ComboboxSelected>>", fuellen)
        fuellen()
        knoepfe = ttk.Frame(fenster, padding=6)
        knoepfe.pack(fill=tk.X)

        def aufwand_fertig(ra):
            aufwand["erg"] = ra
            r = ra["info"]["rechner"]
            lbl5.config(text=(f"Gemessen mit {vk.VERSION} auf {r['prozessor']} ({r['kerne_logisch']} logische Kerne, "
                              f"gerechnet mit 1 Kern), scikit-learn {r['scikit_learn']}. Vorverarbeitung je Kanal: "
                              + ", ".join(f"{v['Set']} {v['Vorverarbeitung_s_je_Kanal']:.2f} s"
                                          for v in ra["vorverarbeitung"] if "Vorverarbeitung_s_je_Kanal" in v)
                              + ". Vorverarbeitung je Kanalsatz = Hochrechnung; Treffer über ganze Bäume geprüft."))
            fuellen()
            nb.select(r5)

        def aufwand_messen():
            if self.stapel_laeuft:
                messagebox.showinfo("Rechenaufwand", "Es läuft gerade eine Auswertung.", parent=fenster)
                return
            if not messagebox.askyesno("Rechenaufwand", (
                    "Gemessen werden Datenmenge, Vorverarbeitung (je Set eine Aufnahme aus den Rohbildern) und "
                    "Random Forest/LDA je Kanalsatz. Das dauert einige Minuten (Test: 30 Bäume ≈ 2 min).\n\n"
                    "Für vergleichbare Zeiten währenddessen keine anderen rechenintensiven Programme nutzen.\n\n"
                    "Starten?"), parent=fenster):
                return
            self.stapel_laeuft = True
            self.abbruch.clear()
            self.btn_stapel.config(state=tk.DISABLED)
            self.btn_abbruch.config(state=tk.NORMAL)
            self._aufwand_rueckruf = aufwand_fertig

            def arbeit():
                try:
                    ra = vk.rechenaufwand(self.referenzen, abbrechen=self.abbruch.is_set,
                                          fortschritt=lambda x: self.q.put(("aufwand_fortschritt", x)))
                    self.q.put(("aufwand_fertig", (ra, None)))
                except InterruptedError:
                    self.q.put(("aufwand_fertig", (None, "Abgebrochen.")))
                except Exception as e:
                    traceback.print_exc()
                    self.q.put(("aufwand_fertig", (None, str(e))))
            threading.Thread(target=arbeit, daemon=True).start()

        ttk.Button(knoepfe, text="Rechenaufwand messen …", command=aufwand_messen).pack(side=tk.LEFT, padx=(0, 6))

        def csv_speichern():
            start = os.path.join(self.wurzel or START_ORDNER, vk.AUSWERTUNG_UNTERORDNER)
            os.makedirs(start, exist_ok=True)
            pfad = filedialog.asksaveasfilename(parent=fenster, title="Kanalanalyse speichern (mehrere CSV-Dateien)",
                                                initialdir=start, initialfile="Kanalanalyse.csv",
                                                defaultextension=".csv", filetypes=[("CSV", "*.csv")])
            if not pfad:
                return
            protokoll = {"software": vk.VERSION, "erstellt": vk._dt.datetime.now().isoformat(timespec="seconds"),
                         "referenzdatei": self.referenzpfad or "(ungespeichert)",
                         "maske_beim_ergaenzen": (self._kanal_vorgabe.protokoll()
                                                  if getattr(self, "_kanal_vorgabe", None) else "nicht nötig/keine")}
            dateien = vk.kanalanalyse_als_csv(erg, pfad, protokoll)
            if aufwand["erg"]:
                dateien += vk.rechenaufwand_als_csv(aufwand["erg"], pfad, protokoll)
            self._setze_status(f"Kanalanalyse gespeichert: {len(dateien)} Dateien in {os.path.dirname(pfad)}")

        ttk.Button(knoepfe, text="Als CSV speichern …", command=csv_speichern).pack(side=tk.LEFT)
        ttk.Button(knoepfe, text="Schließen", command=fenster.destroy).pack(side=tk.RIGHT)

    def _aufwand_ende(self, ra, fehlertext):
        self.stapel_laeuft = False
        self.btn_stapel.config(state=tk.NORMAL)
        self.btn_abbruch.config(state=tk.DISABLED)
        self.fortschritt.config(value=0)
        if fehlertext:
            self._setze_status("Rechenaufwand: " + fehlertext)
            if fehlertext != "Abgebrochen.":
                messagebox.showerror("Rechenaufwand", fehlertext)
            return
        self._setze_status("Rechenaufwand gemessen – Reiter „Rechenaufwand“; „Als CSV speichern …“ sichert alles.")
        try:
            self._aufwand_rueckruf(ra)
        except tk.TclError:
            messagebox.showinfo("Rechenaufwand", "Das Fenster der Kanalanalyse wurde geschlossen – bitte neu öffnen "
                                                 "und erneut messen.")

    def _pruefung_ende(self, erg, fehlertext):
        self.stapel_laeuft = False
        self.btn_stapel.config(state=tk.NORMAL)
        self.btn_abbruch.config(state=tk.DISABLED)
        if fehlertext:
            self._setze_status("Prüfung fehlgeschlagen.")
            messagebox.showerror("Prüfung fehlgeschlagen", fehlertext)
            return
        zeilen, summe, fehler = erg
        abgebrochen = any(m.startswith("abgebrochen") for _, m in fehler)
        fehler = [(n, m) for n, m in fehler if not m.startswith("abgebrochen")]
        kx = self._pruef_kontext
        self._setze_status(f"Prüfung {'abgebrochen' if abgebrochen else 'fertig'}: "
                           + "; ".join(f"{s['Index']} {s['Vital_richtig'] + s['Geschaedigt_richtig']}/"
                                       f"{s['Vital_n'] + s['Geschaedigt_n']}" for s in summe))
        fenster = tk.Toplevel(self.root)
        fenster.configure(bg=self._farbe("hintergrund"))
        fenster.title("Prüfung der Schwellen an Prüfbäumen")
        fenster.geometry("1200x640")
        kopf = (f"Prüfbäume: {', '.join(os.path.basename(p) for p in kx['pfade'])}   |   Schwellen abgeleitet aus: "
                f"{os.path.basename(kx['ableitung'])}\nMaske: {kx['vorgabe'].beschreibung()}\n"
                "Soll: Referenz „vital“ → Baum „vital“, Referenz „geschädigt“ → Baum „gestresst“. „Übergang“ zählt nicht "
                "als richtig. Ausgewogene Trefferquote = Mittel der Trefferquoten beider Gruppen.")
        if kx.get("ausgeschlossen"):
            kopf += (f"\n{len(kx['ausgeschlossen'])} doppelte Prüfbäume ausgeschlossen (derselbe Baum wie ein "
                     "Ableitungsbaum oder doppelt eingezeichnet).")
        elif kx["ueberschneidungen"] or (kx.get("dopplungen") or {}).get("pruef_doppelt"):
            kopf += (f"\n⚠ Dopplungen nicht ausgeschlossen: {len(kx['ueberschneidungen'])} Prüfbaum/-bäume = "
                     f"Ableitungsbaum, {len(kx['dopplungen']['pruef_doppelt'])} doppelt eingezeichnet – Ergebnis zu "
                     "optimistisch.")
        if abgebrochen:
            kopf += "\n⚠ Abgebrochen – nur ein Teil der Prüfbäume ist ausgewertet."
        if fehler:
            kopf += "\n⚠ Nicht geladen: " + "; ".join(f"{n}: {m}" for n, m in fehler[:5])
        ttk.Label(fenster, text=kopf, padding=6, wraplength=1160, justify=tk.LEFT).pack(anchor="w")

        sp1 = ["Index", "Schwellen", "Baumregel", "vital richtig", "vital Übergang", "vital falsch",
               "geschädigt richtig", "geschädigt Übergang", "geschädigt falsch", "kein Baum", "Treffer", "ausgewogen"]
        t1 = ttk.Treeview(fenster, columns=sp1, show="headings", height=min(len(summe), 11))
        for c in sp1:
            t1.heading(c, text=c)
            t1.column(c, width=150 if c == "Schwellen" else 88, anchor="w" if c in ("Index", "Schwellen") else "e")
        prozent = lambda x: "–" if x != x else f"{x * 100:.0f} %"
        for s in sorted(summe, key=lambda s: -(s["Ausgewogene_Trefferquote"]
                                               if s["Ausgewogene_Trefferquote"] == s["Ausgewogene_Trefferquote"] else -1)):
            t1.insert("", tk.END, values=[
                s["Index"], f"< {s['gestresst_unter']:.3f} / ≥ {s['vital_ab']:.3f}",
                ("Median" if s.get("Baumregel") == vk.BAUMREGELN["median"] else f"{s['Baum_gestresst_ab'] * 100:.0f} %"),
                f"{s['Vital_richtig']}/{s['Vital_n']}", s["Vital_Uebergang"], s["Vital_falsch"],
                f"{s['Geschaedigt_richtig']}/{s['Geschaedigt_n']}", s["Geschaedigt_Uebergang"], s["Geschaedigt_falsch"],
                s["Kein_Baum"], prozent(s["Trefferquote"]), prozent(s["Ausgewogene_Trefferquote"])])
        t1.pack(fill=tk.X, padx=6)

        ttk.Label(fenster, text="Je Prüffläche (Doppelklick: Bild öffnen):", padding=(6, 8, 6, 2)).pack(anchor="w")
        rahmen = ttk.Frame(fenster)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=6)
        sp2 = ["Index", "Nr", "Soll", "Bild", "Baum", "Überdeckung", "Klasse", "Ergebnis", "gestresst", "vital", "Median"]
        t2 = ttk.Treeview(rahmen, columns=sp2, show="headings")
        for c in sp2:
            t2.heading(c, text=c)
            t2.column(c, width=200 if c == "Bild" else 80, anchor="w" if c in ("Index", "Soll", "Bild", "Klasse", "Ergebnis") else "e")
        sb = ttk.Scrollbar(rahmen, orient=tk.VERTICAL, command=t2.yview)
        t2.configure(yscrollcommand=sb.set)
        t2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self._tabellen_tags(t2)
        ziele = {}
        for k, z in enumerate(zeilen):
            iid = t2.insert("", tk.END, tags=(z["Ergebnis"],), values=[
                z["Index"], z["Pruefflaeche"], z["Soll"], f"{os.path.basename(z['Ordner'])}\\{z['Aufnahme']}",
                z["Baum_Nr"], f"{z['Ueberdeckung'] * 100:.0f} %", z["Klasse"], z["Ergebnis"],
                f"{z['Anteil_gestresst'] * 100:.0f} %" if "Anteil_gestresst" in z else "",
                f"{z['Anteil_vital'] * 100:.0f} %" if "Anteil_vital" in z else "",
                f"{z['Median']:.3f}" if "Median" in z else ""])
            ziele[iid] = (z["Ordner"], z["Aufnahme"], z["Index"], bool(z.get("Panchro_geschaerft")))

        def bild_oeffnen(_e=None):
            sel = t2.selection()
            if not sel:
                return
            ordner, name, idx, geschaerft = ziele[sel[0]]
            if geschaerft != self.var_panchro.get():      # Fläche wurde in dieser Auflösung eingezeichnet
                self.var_panchro.set(geschaerft)
                vk.setze_panchro_schaerfen(geschaerft)
            treffer = [i for i, (o, n) in enumerate(self.liste)
                       if n == name and os.path.normcase(o) == os.path.normcase(ordner)]
            if treffer:
                self.pos = treffer[0]
            else:                      # Bild nicht in der aktuellen Liste -> Ordner dieser Aufnahme öffnen
                self.wurzel = ordner
                self.liste = [(ordner, n) for n in vk.liste_aufnahmen(ordner)]
                self.pos = next((i for i, (_, n) in enumerate(self.liste) if n == name), 0)
            self.var_index.set(idx)
            self._lade()
        t2.bind("<Double-1>", bild_oeffnen)

        def csv_speichern():
            start = os.path.join(self.wurzel or START_ORDNER, vk.AUSWERTUNG_UNTERORDNER)
            os.makedirs(start, exist_ok=True)
            pfad = filedialog.asksaveasfilename(parent=fenster, title="Prüfergebnis speichern", initialdir=start,
                                                initialfile="Pruefung_Schwellen.csv", defaultextension=".csv",
                                                filetypes=[("CSV", "*.csv")])
            if not pfad:
                return
            protokoll = {"software": vk.VERSION, "erstellt": vk._dt.datetime.now().isoformat(timespec="seconds"),
                         "pruefbaeume": kx["pfade"], "schwellen_abgeleitet_aus": kx["ableitung"],
                         "maske": kx["vorgabe"].protokoll(),
                         "schwellen": {i: s.protokoll() for i, s in kx["schwellen"].items()},
                         "ueberschneidungen_pruefung_ableitung": kx["ueberschneidungen"],
                         "dopplungen": kx.get("dopplungen"), "doppelte_ausgeschlossen": kx.get("ausgeschlossen"),
                         "regel": "Prüffläche -> Baum mit größter Überdeckung; Soll vital -> vital, geschädigt -> gestresst",
                         "nicht_geladen": fehler, "abgebrochen": abgebrochen}
            vk.pruefung_als_csv(zeilen, summe, pfad, protokoll)
            self._setze_status(f"Prüfergebnis gespeichert: {pfad} (+ _Zusammenfassung.csv, _Parameter.json)")

        knoepfe = ttk.Frame(fenster, padding=6)
        knoepfe.pack(fill=tk.X)
        ttk.Button(knoepfe, text="Als CSV speichern …", command=csv_speichern).pack(side=tk.LEFT)
        ttk.Button(knoepfe, text="Ausgewähltes Bild öffnen", command=bild_oeffnen).pack(side=tk.LEFT, padx=6)
        ttk.Button(knoepfe, text="Schließen", command=fenster.destroy).pack(side=tk.RIGHT)
        self._pruef_fenster = (fenster, t1, t2, csv_speichern)

    def _modell_anzeige(self, geaendert=False):
        baum, kein = self.modell.anzahl()
        bilder = len({(f["ordner"], f["aufnahme"]) for f in self.modell.flaechen})
        if self.modell.rf is None:
            zustand = "nicht berechnet"
        else:
            i = self.modell.info
            zustand = (f"berechnet, Genauigkeit {i['ausgewogene_genauigkeit'] * 100:.1f} % "
                       f"(Baum {i['trefferquote_baum'] * 100:.0f} %, kein Baum {i['trefferquote_kein_baum'] * 100:.0f} %)")
            if geaendert:
                zustand += " – neue Flächen noch nicht berücksichtigt"
        name = os.path.basename(self.modellpfad) if self.modellpfad else "ungespeichert"
        self.lbl_modell.config(text=f"[{name}] {baum} Baum- / {kein} Kein-Baum-Flächen in {bilder} Bild(ern); {zustand}")

    def trainieren(self):
        try:
            self._setze_status("Berechne Baummodell (inkl. Kreuzvalidierung) …")
            self.root.config(cursor="watch"); self.root.update_idletasks()
            info = self.modell.trainieren()
        except Exception as e:
            self.root.config(cursor="")
            messagebox.showerror("Modell kann nicht berechnet werden", str(e))
            return
        self.root.config(cursor="")
        self.modell_version += 1
        self._modell_anzeige()
        merk = ", ".join(f"{n} ({v:.2f})" for n, v in info["wichtigste_merkmale"][:5])
        tsd = lambda z: f"{z:,}".replace(",", ".")
        messagebox.showinfo("Baummodell berechnet", (
            f"{info['flaechen_baum']} Baum- und {info['flaechen_kein_baum']} Kein-Baum-Flächen "
            f"({tsd(info['pixel_baum'])} / {tsd(info['pixel_kein_baum'])} Pixel) "
            f"aus {len(info['aufnahmen'])} Bild(ern).\n\n"
            f"Kreuzvalidierung ({info['kreuzvalidierung']}):\n"
            f"  Trefferquote Baum: {info['trefferquote_baum'] * 100:.1f} %\n"
            f"  Trefferquote kein Baum: {info['trefferquote_kein_baum'] * 100:.1f} %\n"
            f"  ausgewogene Genauigkeit: {info['ausgewogene_genauigkeit'] * 100:.1f} %\n\n"
            f"Wichtigste Merkmale: {merk}\n\n"
            "Die Maske jetzt in mehreren Bildern visuell prüfen und bei Fehlern gezielt weitere Flächen "
            "einzeichnen und neu berechnen."))
        if not self.var_maskenart.get().startswith("Bäume"):
            self.var_maskenart.set(MASKEN[2])
        self.aktualisieren()

    def letzte_flaeche_entfernen(self):
        if not self.modell.flaechen:
            return
        f = self.modell.flaechen[-1]
        self.modell.flaeche_entfernen(f["nr"])
        self._zeichne_trainingsflaechen()
        self.canvas.draw_idle()
        self._modell_anzeige(geaendert=self.modell.rf is not None)
        self._setze_status(f"Fläche {f['nr']} ({'Baum' if f['klasse'] else 'kein Baum'}, {f['aufnahme']}) entfernt.")

    def modell_speichern(self):
        if self.modell.rf is None:
            messagebox.showinfo("Modell speichern", "Bitte zuerst „Modell berechnen“ klicken.")
            return
        start = os.path.join(self.wurzel or START_ORDNER, vk.AUSWERTUNG_UNTERORDNER)
        os.makedirs(start, exist_ok=True)
        pfad = filedialog.asksaveasfilename(title="Baummodell speichern", initialdir=start,
                                            initialfile="Baummodell.joblib", defaultextension=".joblib",
                                            filetypes=[("Baummodell", "*.joblib")])
        if not pfad:
            return
        self.modell.speichern(pfad)
        self.modellpfad = os.path.normpath(pfad)
        self._modell_anzeige()
        self._setze_status(f"Baummodell gespeichert: {pfad} (+ _Info.json)")

    def modell_laden(self):
        pfad = filedialog.askopenfilename(title="Baummodell laden", initialdir=self.wurzel or START_ORDNER,
                                          filetypes=[("Baummodell", "*.joblib")])
        if not pfad:
            return
        try:
            self.modell = vk.Baummodell.laden(pfad)
        except Exception as e:
            messagebox.showerror("Modell kann nicht geladen werden", str(e))
            return
        self.modellpfad = os.path.normpath(pfad)
        self.modell_version += 1
        self._masken_schluessel = None
        self._modell_anzeige()
        self._zeichne_trainingsflaechen()
        self.var_maskenart.set(MASKEN[2])
        self.aktualisieren()

    def modell_neu(self):
        if self.modell.flaechen and not messagebox.askyesno(
                "Neues Modell", "Alle Beispielflächen des aktuellen Modells verwerfen?\n"
                                "(Gespeicherte Modelldateien bleiben erhalten.)"):
            return
        self.modell, self.modellpfad = vk.Baummodell(), ""
        self.modell_version += 1
        self._masken_schluessel = None
        if self.var_maskenart.get().startswith("Bäume"):
            self.var_maskenart.set(MASKEN[0])
        self._zeichne_trainingsflaechen()
        self._modell_anzeige()
        self.aktualisieren()

    # ------------------------------------------------------------------ Export
    def exportieren(self):
        if self.aufn is None:
            messagebox.showinfo("Export", "Zuerst eine Aufnahme laden.")
            return
        vorgabe = self._vorgabe()
        dunkel = self.var_dunkel.get()
        try:
            if dunkel:
                self._mpl_thema(False)                 # Abbildung für die Arbeit immer hell speichern
            ziel = vk.exportiere(self.aufn, self.var_index.get(), vorgabe, self.rois, figur=self.fig,
                                 pixelwerte=self.var_pixelexport.get(), maske=self._berechne_maske(vorgabe),
                                 schwellen=self._aktive_schwellen())
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Export fehlgeschlagen", str(e))
            return
        finally:
            if dunkel:
                self._mpl_thema(True)
                self.canvas.draw_idle()
        self._setze_status(f"Exportiert nach {ziel}")
        if messagebox.askyesno("Export abgeschlossen", f"Ergebnisse gespeichert in:\n{ziel}\n\nOrdner öffnen?"):
            os.startfile(ziel)

    # ------------------------------------------------------------------ Ordnerauswertung
    def ordner_auswerten(self):
        if self.stapel_laeuft:
            return
        vorgabe = self._vorgabe(fuer_ordner=True)
        if self.var_maskenart.get().startswith("Bäume") and vorgabe is None:
            return
        if vorgabe is not None and vorgabe.art == "Baum" and not self.modellpfad:
            if not messagebox.askyesno("Baummodell nicht gespeichert",
                                       "Das Baummodell ist noch nicht gespeichert. Für die Nachvollziehbarkeit "
                                       "sollte es vorher gespeichert werden (das Protokoll verweist auf die Datei).\n\n"
                                       "Trotzdem ohne Speichern fortfahren?"):
                return
        wurzel = filedialog.askdirectory(title="Ordner auswerten (alle Aufnahmen, auch in Unterordnern)",
                                         initialdir=self.wurzel or START_ORDNER, mustexist=True)
        if not wurzel:
            return
        wurzel = os.path.normpath(wurzel)
        liste = vk.liste_aufnahmen_rekursiv(wurzel)
        if not liste:
            messagebox.showinfo("Keine Aufnahmen", f"In {wurzel} wurden keine Aufnahmen gefunden.")
            return
        ordner = sorted({o for o, _ in liste})
        roh = sum(1 for o, n in liste
                  if not os.path.exists(os.path.join(o, vk.REFLEKTANZ_UNTERORDNER, f"{n}_reflektanz.tif")))
        je_bild = 1.0 if vorgabe is not None and vorgabe.art == "Baum" else 0.0
        dauer = (roh * 4.5 + (len(liste) - roh) * 0.5 + len(liste) * je_bild) / 60
        text = (f"{len(liste)} Aufnahmen in {len(ordner)} Ordner(n).\n"
                f"Davon {roh} aus Rohbildern (≈ 4,5 s je Aufnahme, ggf. einmalig ≈ 2 min Ausrichtung je Ordner).\n"
                f"Geschätzte Dauer: ≈ {max(dauer, 1):.0f} min.\n\n"
                f"Indizes: {', '.join(vk.INDIZES)}\n"
                f"Regionen: Gesamtbild" + (f" und {vorgabe.beschreibung()}" if vorgabe else "") + "\n"
                f"Indexraster speichern: {('ja, ' + self.var_index.get()) if self.var_raster.get() else 'nein'}\n"
                + ("Schwellwerte: " + "; ".join(f"{i}: gestresst < {sw.gestresst:.2f}, vital ≥ {sw.vital:.2f}, "
                                                + ("Baumregel Median je Baum" if sw.baumregel == "median" else
                                                   f"Baum gestresst ab {sw.anteil_markierung * 100:.0f} %")
                                                for i, sw in self._aktive_schwellen().items())
                   if self._aktive_schwellen() else "Schwellwerte: keine") + "\n\n"
                f"Ergebnis: {os.path.join(wurzel, vk.AUSWERTUNG_UNTERORDNER)}\n\nStarten?")
        if not messagebox.askyesno("Ordner auswerten", text):
            return
        self.stapel_laeuft = True
        self.abbruch.clear()
        self.fortschritt.config(maximum=len(liste), value=0)
        self.btn_stapel.config(state=tk.DISABLED)
        self.btn_abbruch.config(state=tk.NORMAL)
        raster = self.var_raster.get()
        raster_index = [self.var_index.get()]
        schwellen = self._aktive_schwellen()

        def arbeit():
            try:
                erg = vk.werte_ordner_aus(wurzel, vorgabe, raster=raster, raster_indizes=raster_index, schwellen=schwellen,
                                          abbrechen=self.abbruch.is_set,
                                          fortschritt=lambda t: self.q.put(("stapel_fortschritt", t)))
                self.q.put(("stapel_fertig", (erg, None)))
            except Exception as e:
                traceback.print_exc()
                self.q.put(("stapel_fertig", (None, str(e))))
        threading.Thread(target=arbeit, daemon=True).start()

    def _stapel_ende(self, erg, fehlertext):
        self.stapel_laeuft = False
        self.btn_stapel.config(state=tk.NORMAL)
        self.btn_abbruch.config(state=tk.DISABLED)
        if fehlertext:
            self._setze_status("Ordnerauswertung fehlgeschlagen.")
            messagebox.showerror("Ordnerauswertung fehlgeschlagen", fehlertext)
            return
        csv_pfad, ok, fehler = erg
        abgebrochen = any(m.startswith("abgebrochen") for _, m in fehler)
        fehler = [(n, m) for n, m in fehler if not m.startswith("abgebrochen")]
        zustand = "abgebrochen" if abgebrochen else "fertig"
        self._setze_status(f"Ordnerauswertung {zustand}: {ok} Aufnahmen → {csv_pfad}")
        if abgebrochen:
            messagebox.showinfo("Ordnerauswertung abgebrochen", f"Abgebrochen nach {ok} Aufnahmen.\n"
                                f"Die bis dahin ausgewerteten Aufnahmen stehen in:\n{csv_pfad}")
            return
        text = f"{ok} Aufnahmen ausgewertet.\nErgebnis:\n{csv_pfad}"
        if fehler:
            text += f"\n\n{len(fehler)} nicht ausgewertet:\n" + "\n".join(f"• {n}: {m}" for n, m in fehler[:12])
            if len(fehler) > 12:
                text += "\n… (vollständige Liste in der Parameterdatei)"
        if messagebox.askyesno("Ordnerauswertung abgeschlossen", text + "\n\nOrdner öffnen?"):
            os.startfile(os.path.dirname(csv_pfad))

    def _setze_status(self, text):
        self.status.config(text=text)

    # ------------------------------------------------------------------ Darstellung hell / dunkel
    def _farbe(self, name):
        return THEMEN[bool(getattr(self, "var_dunkel", None) and self.var_dunkel.get())][name]

    def _thema_umschalten(self):
        speichere_einstellung("darkmode", bool(self.var_dunkel.get()))
        self._thema_anwenden()

    def _thema_anwenden(self):
        """Farben für Bedienelemente (ttk), klassische Tk-Elemente, Nebenfenster und Abbildungen setzen."""
        dunkel = bool(self.var_dunkel.get())
        c = THEMEN[dunkel]
        st = ttk.Style()
        if dunkel:
            st.theme_use("clam")          # „vista“ lässt sich nicht umfärben
            st.configure(".", background=c["hintergrund"], foreground=c["text"], fieldbackground=c["feld"],
                         bordercolor=c["rand"], lightcolor=c["rand"], darkcolor=c["rand"], troughcolor=c["feld"],
                         selectbackground=c["auswahl"], selectforeground=c["auswahl_text"], insertcolor=c["text"],
                         arrowcolor=c["text"])
            st.map(".", background=[("disabled", c["hintergrund"]), ("active", c["rand"])],
                   foreground=[("disabled", c["hinweis"])])
            for w in ("TButton", "TCheckbutton", "TRadiobutton", "TMenubutton"):
                st.map(w, background=[("pressed", c["auswahl"]), ("active", c["rand"])],
                       indicatorcolor=[("selected", c["auswahl"]), ("!selected", c["feld"])])
            st.configure("TButton", background=c["feld"])
            st.configure("TEntry", fieldbackground=c["feld"], foreground=c["text"])
            st.configure("TSpinbox", fieldbackground=c["feld"], foreground=c["text"], arrowcolor=c["text"])
            st.configure("TCombobox", fieldbackground=c["feld"], foreground=c["text"], arrowcolor=c["text"])
            st.map("TCombobox", fieldbackground=[("readonly", c["feld"])], foreground=[("readonly", c["text"])],
                   selectbackground=[("readonly", c["feld"])], selectforeground=[("readonly", c["text"])])
            st.configure("Treeview", background=c["feld"], fieldbackground=c["feld"], foreground=c["text"])
            st.map("Treeview", background=[("selected", c["auswahl"])], foreground=[("selected", c["auswahl_text"])])
            st.configure("Treeview.Heading", background=c["hintergrund"], foreground=c["text"])
            st.map("Treeview.Heading", background=[("active", c["rand"])])
            st.configure("TProgressbar", background=c["auswahl"], troughcolor=c["feld"])
        else:
            st.theme_use(self._hell_theme)
        st.configure("Hinweis.TLabel", foreground=c["hinweis"])
        # Aufklappliste der Comboboxen (klassisches Tk-Widget)
        for k, v in (("background", c["feld"]), ("foreground", c["text"]), ("selectBackground", c["auswahl"]),
                     ("selectForeground", c["auswahl_text"])):
            self.root.option_add(f"*TCombobox*Listbox.{k}", v)
        self.root.configure(bg=c["hintergrund"])
        self._tk_widgets_faerben(self.root, c)
        if getattr(self, "_pruef_fenster", None):
            try:
                self._tabellen_tags(self._pruef_fenster[2])
            except tk.TclError:
                pass
        self._mpl_thema(dunkel)
        self.canvas.draw_idle()

    def _tk_widgets_faerben(self, w, c):
        """Klassische Tk-Elemente (Text, Toplevel, Werkzeugleiste der Abbildung) umfärben."""
        for kind in w.winfo_children():
            klasse = kind.winfo_class()
            try:
                if klasse == "Text":
                    kind.configure(background=c["pixel_feld"], foreground=c["text"], insertbackground=c["text"],
                                   selectbackground=c["auswahl"])
                elif klasse == "Toplevel":
                    kind.configure(bg=c["hintergrund"])
                elif klasse in ("Frame", "Canvas") and not kind.winfo_class().startswith("T"):
                    kind.configure(bg=c["hintergrund"])
                elif klasse in ("Button", "Checkbutton", "Label"):
                    kind.configure(bg=c["hintergrund"], fg=c["text"], activebackground=c["rand"],
                                   activeforeground=c["text"])
                    if klasse == "Checkbutton":
                        kind.configure(selectcolor=c["feld"])
            except tk.TclError:
                pass
            self._tk_widgets_faerben(kind, c)
        if w is self.toolbar:
            for knopf in self.toolbar.winfo_children():   # Symbole passend zur Hintergrundhelligkeit neu zeichnen
                try:
                    self.toolbar._set_image_for_button(knopf)
                except (AttributeError, tk.TclError):
                    pass

    def _tabellen_tags(self, baum):
        baum.tag_configure("falsch", foreground=self._farbe("falsch"))
        baum.tag_configure("Übergang", foreground=self._farbe("uebergang"))
        baum.tag_configure("kein Baum", foreground=self._farbe("kein_baum"))

    def _mpl_thema(self, dunkel=None):
        """Abbildung (Figur, Achsen, Beschriftungen, Legende, Farbskala) im hellen oder dunklen Thema."""
        if dunkel is None:
            dunkel = bool(self.var_dunkel.get())
        c = THEMEN[dunkel]
        matplotlib.rcParams.update({"text.color": c["text"], "axes.labelcolor": c["text"], "xtick.color": c["text"],
                                    "ytick.color": c["text"], "axes.edgecolor": c["rand"],
                                    "axes.facecolor": c["achse"], "figure.facecolor": c["figur"],
                                    "legend.facecolor": c["achse"], "legend.edgecolor": c["rand"],
                                    "grid.color": c["gitter"]})
        self.fig.set_facecolor(c["figur"])
        for ax in self.fig.axes:
            ax.set_facecolor(c["achse"])
            ax.tick_params(colors=c["text"], which="both")
            for s in ax.spines.values():
                s.set_edgecolor(c["rand"])
            for txt in (ax.title, ax.xaxis.label, ax.yaxis.label):
                txt.set_color(c["text"])
            for linie in ax.get_xgridlines() + ax.get_ygridlines():
                linie.set_color(c["gitter"])
            leg = ax.get_legend()
            if leg is not None:
                leg.get_frame().set_facecolor(c["achse"])
                leg.get_frame().set_edgecolor(c["rand"])
                for txt in leg.get_texts():
                    txt.set_color(c["text"])


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
