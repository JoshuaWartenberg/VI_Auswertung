# Dokumentation: Software zur pixelweisen Auswertung von Vegetationsindizes (VI-Auswertung)

Erstellt am: 2026-10-31 · aktuell Version 0.20.3 (0.2: Ordner, 0.3: Baummaske, 0.4: weitere Indizes, Zoomen, 0.5: Schwellwerte, 0.6: Schwellen aus Referenzbäumen, 0.7: Bäume nach Klassen einfärben, 0.8: Maskenverfeinerung und Kronentrennung mit NIR, 0.8.1: Bildnummer eingeben, Referenzen hinzuladen, 0.9: Schwellen an Prüfbäumen prüfen, 0.9.1: Schwellen im Histogramm eintippen, 0.9.2: auch an der Farbskala, 0.10: Kanalzahl wählbar, Panchro-Schärfung, 0.10.1: Beschriftung Baummodell, 0.11: Darkmode, 0.12: Kanalanalyse an Referenzbäumen, 0.13: Kronentrennung über Pflanzraster und Korrektur von Hand, 0.14: Panchro nur für Maske und Kronen, 0.14.1: Baumnummern in Leserichtung, 0.15: Arbeitsstand merken, Alles zurücksetzen, 0.16: Baumregel Median je Baum, 0.17: Schwellen aus Baummedianen, 0.17.1: portabel, Anleitung, Anhang, 0.18: Schnittlinie, Korrekturen einzeln löschen, Legende 2/3 Klassen, Leisten für 1536 px, Aufteilung 2/3, 0.18.1: Referenz- und Beispielflächen per Klick löschen, 0.19: Rechenaufwand je Kanalsatz, Kanalsatz ohne Blau, Holm-Korrektur, 0.20: Ableitung hinterlegen und einblenden, Dopplungsabgleich bei der Prüfung, 0.20.1: Abgleich im Grünkanal, sicher/fraglich, 0.20.2: Baumregel für alle Indizes, Warnungen bei der Prüfung, 0.20.3: Welch-Test und Holm-Korrektur entfernt)
Ordner: `C:\Users\joshu\OneDrive\Bachelorarbeit\Software\VI_Auswertung\`
Kamera: MicaSense RedEdge-P mit DLS 2 (Einzelaufnahmen, keine Orthomosaike)

| Datei | Inhalt |
|---|---|
| `vi_auswertung.py` | Oberfläche (Tkinter + matplotlib) |
| `vi_kern.py` | Rechenkern ohne Oberfläche: Laden, Indizes, Masken, Statistik, Export |
| `VI_Auswertung starten.bat` | Start per Doppelklick |
| `Dokumentation_VI_Auswertung.md` | diese Datei |

---

## 1. Ziel

Eine kleine Software als erster Baustein des Auswerte-Workflows:

1. eine Einzelaufnahme (5 Kanäle) laden,
2. einen Vegetationsindex auswählen (NDVI, NDRE, ReNDVI, GNDVI),
3. den Index pixelweise berechnen und als Karte und Histogramm darstellen,
4. Pixel einzeln abfragen und Untersuchungsflächen (ROIs) statistisch vergleichen,
5. Ergebnisse nachvollziehbar exportieren (Raster, Statistik, Parameterprotokoll, Abbildung).

## 2. Getroffene Entscheidungen

| Frage | Entscheidung | Begründung |
|---|---|---|
| Eingangsdaten | **Einzelaufnahmen** statt Orthomosaik | Wunsch des Nutzers: keine photogrammetrische Vorverarbeitung (WebODM) nötig |
| Vorverarbeitung | **Keine eigene Neuimplementierung.** Radiometrie, Entzerrung und Kanalausrichtung werden direkt aus `multispektral_stapeln.py` (Flugtag130726\0029SET\000) übernommen | Das Verfahren ist dort bereits geprüft und dokumentiert. Software und Stapelskript liefern dadurch nachweislich identische Reflektanzen (Abschnitt 5.1) |
| Pflicht-Vorverarbeitung bei Einzelaufnahmen | Rohwert → Reflektanz (DLS 2), Entzerrung, Kanalausrichtung erfolgen **automatisch beim Laden** | Ohne Kalibrierung sind Indizes nicht vergleichbar. Ohne Ausrichtung würden Pixel verschiedener Orte verrechnet (Versatz bis ~20 px) |
| Kalibrierung | **Nur DLS 2** (wie bisher) | In den Datensätzen gibt es keine Panelaufnahmen |
| Indizes | NDVI, NDRE, ReNDVI, GNDVI | Auswahl des Nutzers, Formeln wie in Kapitel 2.3 (Formel 5–8) |
| Maskierung ungültiger Pixel | identisch zu den QGIS-Projekten: \|Nenner\| < 0,01 oder Reflektanz < −0,02 → ungültig, Werte auf −1…1 begrenzt | Vergleichbarkeit mit den bisherigen QGIS-/WebODM-Auswertungen |
| Vegetationsmaske | optional, **NDVI ≥ Schwelle** (frei einstellbar, Vorgabe 0,40) | Boden/Schatten aus der Statistik ausschließen. Der Schwellwert ist eine methodische Entscheidung und wird deshalb protokolliert |
| Oberfläche | Tkinter + matplotlib (Desktop) | Ohne zusätzliche Installation lauffähig (alle Pakete vorhanden), Rechteckauswahl und Zoom sind eingebaut |

## 3. Vegetationsindizes

Alle vier Indizes sind normierte Differenzen zweier Reflektanzen ρ:

| Index | Formel | Kanäle RedEdge-P | Quelle (Arbeit) |
|---|---|---|---|
| NDVI | (ρ_NIR − ρ_Rot) / (ρ_NIR + ρ_Rot) | 842 / 668 nm | Rouse et al. 1974, Formel 5 |
| NDRE | (ρ_NIR − ρ_RE) / (ρ_NIR + ρ_RE) | 842 / 717 nm | Barnes et al. 2000, Formel 6 |
| ReNDVI | (ρ_RE − ρ_Rot) / (ρ_RE + ρ_Rot) | 717 / 668 nm | Wang 2021, Formel 7 |
| GNDVI | (ρ_NIR − ρ_Grün) / (ρ_NIR + ρ_Grün) | 842 / 560 nm | Gitelson et al. 1996, Formel 8 |

Die Kanäle werden über ihren Namen aus den Metadaten zugeordnet (`Camera:BandName`), nicht über die Dateinummer.

## 4. Verarbeitungsschritte

### 4.1 Laden einer Aufnahme

Man wählt eine beliebige Datei der Aufnahme (`IMG_XXXX_1.tif` … `_5.tif` oder `IMG_XXXX_reflektanz.tif`). Danach gilt:

1. **Reflektanzbild vorhanden** (`Reflektanz_5Kanal\IMG_XXXX_reflektanz.tif` aus dem Stapelskript): Es wird direkt gelesen
   (≈ 0,1–0,2 s).
2. **Sonst Rohbilder** (≈ 4,5 s pro Aufnahme), mit denselben Funktionen wie im Stapelskript:
   - Radianz nach dem MicaSense-Modell `L = V(x,y) · a1/g · (p − p_BL) / (t_e + a2·y − a3·t_e·y) / 2^16`
   - Reflektanz `ρ = π · L / E_DLS` je Aufnahme und Kanal
   - Entzerrung (Brennweite, Hauptpunkt, Verzeichnung aus den XMP-Daten)
   - Ausrichtung auf Red Edge mit Homographien und Zuschnitt auf den gemeinsamen gültigen Bereich (inkl. 2 px Sicherheitsrand)

   Woher die Homographien kommen (in dieser Reihenfolge):
   - `Reflektanz_5Kanal\Ausrichtung.txt` des Stapelskripts, falls vorhanden
   - `VI_Auswertung\Ausrichtung.json`, ein früher von dieser Software geschätzter Zwischenspeicher
   - sonst **neue Schätzung für den Ordner**, nach demselben Verfahren wie im Stapelskript: 10 Aufnahmen in Flughöhe,
     Gradienten-ECC, Blau über Grün, robuster Median, Ausreißerverwurf. Das dauert einmalig etwa 100 s. Das Ergebnis wird
     in `VI_Auswertung\Ausrichtung.json` gespeichert. Beschädigte Aufnahmen in der Stichprobe werden übersprungen.

Mit ◀/▶ blättert man durch alle Aufnahmen des Ordners.

### 4.2 Index, Maske, Statistik

- Der Index wird für jedes Pixel berechnet. Ungültige Pixel (siehe Abschnitt 2) werden NaN gesetzt und in der Karte grau dargestellt.
- **Farbskala:** „fest −0,2 … 1,0“ (Vorgabe, damit Bilder vergleichbar sind) oder „automatisch (P2–P98)“ für mehr Kontrast im Einzelbild.
- **Vegetationsmaske:** Pixel mit NDVI unter der Schwelle werden grau dargestellt und in einer eigenen Statistikzeile ausgeschlossen.
- **ROIs:** „ROI zeichnen“ einschalten und in der Indexkarte Rechtecke aufziehen. Für jede ROI erscheinen eine Zeile „ROI n“ und,
  bei aktiver Maske, eine Zeile „ROI n ∩ Vegetation“.
- **Statistik je Region:** Pixelanzahl, Mittelwert, Median, Standardabweichung (n−1), Min, P5, P25, P75, P95, Max.
- **Histogramm:** relative Häufigkeit. Grau = alle gültigen Pixel, grün = Vegetation, Linien = ROIs.
- **Pixelabfrage:** Ein Klick ins Bild zeigt die Reflektanz aller 5 Kanäle und alle 4 Indizes dieses Pixels.

### 4.3 Export

Der Button „Exportieren“ schreibt nach `<Aufnahmeordner>\VI_Auswertung\IMG_XXXX\`:

| Datei | Inhalt |
|---|---|
| `IMG_XXXX_<Index>.tif` (4 Dateien) | Indexraster Float32, ungültig = NaN, gleiche Pixelgeometrie wie das Reflektanzbild |
| `IMG_XXXX_Vegetationsmaske.tif` | nur bei aktiver Maske: 1 = Vegetation |
| `IMG_XXXX_Statistik.csv` | Statistik für **alle 4 Indizes** × alle Regionen (Semikolon-getrennt, UTF-8) |
| `IMG_XXXX_ROI_Pixelwerte.csv` | optional: je ROI-Pixel x, y, Reflektanz der 5 Kanäle, 4 Indizes, Maskenwert |
| `IMG_XXXX_Parameter.json` | Protokoll: Software-Version, Datenquelle, Formeln, Maskierung, Schwellwert, ROI-Koordinaten, DLS-Werte |
| `IMG_XXXX_<Index>_Ansicht.png` | die aktuelle Ansicht (Karte, Histogramm), 200 dpi |

## 5. Prüfung und Ergebnisse (Testlauf 2026-10-31)

### 5.1 Übereinstimmung mit dem Stapelskript

IMG_0100 aus `0029SET\000` wurde einmal aus dem vorhandenen Reflektanzbild und einmal komplett aus den Rohbildern geladen.
Größte Abweichung über alle Pixel und Kanäle: **1,3 · 10⁻⁵** (Rundung Float32), Bildgröße in beiden Fällen 1436 × 1066 px.

Die Indexstatistik stimmt exakt mit der Dokumentation des QGIS-Einzelbildprojekts überein:

| Index | Gültige Pixel | Min | Max | Mittelwert | Doku QGIS-Projekt (Mittel) |
|---|---|---|---|---|---|
| NDVI | 1.530.776 | 0,3083 | 0,9744 | 0,8715 | 0,8715 |
| NDRE | 1.530.776 | 0,1265 | 0,7237 | 0,4795 | 0,4795 |
| GNDVI | 1.530.776 | 0,3714 | 0,9225 | 0,7856 | 0,7856 |
| ReNDVI | 1.530.776 | 0,0674 | 0,9093 | 0,6880 | (neu) |

### 5.2 Beispiel Statistik mit Maske und ROIs (IMG_0100, NDRE, Maske NDVI ≥ 0,80)

| Region | Pixel | Mittel | Median | Std |
|---|---|---|---|---|
| Gesamtbild | 1.530.776 | 0,4795 | 0,4824 | 0,0559 |
| Vegetation | 1.337.609 | 0,4910 | 0,4897 | 0,0464 |
| ROI 1 (x 100–400, y 100–350) | 75.000 | 0,4921 | 0,4937 | 0,0511 |
| ROI 1 ∩ Vegetation | 67.242 | 0,5007 | 0,4991 | 0,0440 |

Kontrolle der Pixelabfrage (x = 250, y = 201): NIR 0,2125, Rot 0,0048 → NDVI = 0,2077 / 0,2173 = 0,956. Die Software zeigt 0,9555 ✓.
Der Export wurde vollständig geprüft (alle Dateien geschrieben, NDVI-Raster Mittel 0,8715). Die Testexporte wurden danach wieder gelöscht.

### 5.3 Ordner ohne vorverarbeitete Reflektanzbilder

| Ordner | Ausrichtung neu geschätzt | Gültige Schätzungen (Blau/Grün/Rot/NIR) | Versatz zu Red Edge (dx; dy) px | Ausschnitt |
|---|---|---|---|---|
| `Flugtag130726\0030SET\000` | ja, 103 s | 10 / 10 / 3 / 10 | Blau (2,9; 8,4), Grün (16,2; −13,1), Rot (5,1; 0,2), NIR (19,3; 0,2) | 1436 × 1066 |
| `0008SET\001` | ja | 10 / 10 / 10 / 10 | Blau (3,0; 7,1), Grün (13,6; −14,8), Rot (2,1; 0,2), NIR (18,3; −2,2) | 1438 × 1066 |

Die Versätze liegen in derselben Größenordnung wie in `0029SET\000` (Doku Stapelskript, Abschnitt 5). Bei 0030SET\000 hat der
Rotkanal nur 3 gültige Schätzungen. Das ist über der Mindestzahl von 2, sollte aber visuell kontrolliert werden (Farbsäume in der Echtfarbansicht).
Danach lädt eine Aufnahme dieses Ordners in ≈ 4,5 s (IMG_0050: NDVI-Mittel des Gesamtbilds 0,81).

### 5.4 Befunde zu den Datensätzen

- **`0007SET` (22.09.2026) enthält keine DLS-Daten** (`DLS:Serial = None`). Reflektanz ist dort nicht bestimmbar. Die Software
  meldet das sofort beim Laden, ohne vorher die Ausrichtung zu schätzen.
- **`0008SET\001` enthält beschädigte Dateien:** 98 Dateien mit 0 Byte, weitere sind abgeschnitten (z. B. `IMG_0346_1.tif`,
  „invalid offset to first page“). Betroffen sind Aufnahmen am Ende des Sets. Die Software meldet beim Laden „beschädigt oder unvollständig“.
- **In keinem Set gibt es Panelaufnahmen** (Sichtprüfung der ersten und letzten Aufnahmen jedes Sets).
- **`0029SET\000\Reflektanz_5Kanal\Ausrichtung.txt`** nennt den Ausschnitt 13:1083, 0:1440 (1440 × 1070 px). Die gespeicherten
  Reflektanzbilder haben aber 1436 × 1066 px. Die Angabe stammt vermutlich aus einem Lauf vor dem Einbau des 2-px-Sicherheitsrands.
  Die Homographien sind davon nicht betroffen. Die Software übernimmt deshalb nur die Homographien und berechnet den Zuschnitt
  neu. Das Ergebnis ist identisch mit den Reflektanzbildern (Abschnitt 5.1).

### 5.5 Korrekturen während der Entwicklung

- Zuschnitt aus `Ausrichtung.txt` führte zu 1440 × 1070 px statt 1436 × 1066 px. Jetzt wird er neu berechnet (s. o.).
- TIFF-Beschreibungen dürfen nur ASCII enthalten. Das Zeichen „−“ in der Formel ließ den Export abbrechen. Jetzt wird ein ASCII-Text verwendet.
- Beim Einbinden des Stapelskripts legte Python einen `__pycache__`-Ordner im Datenordner an. Er wurde gelöscht und wird nicht mehr erzeugt.

## 5a. Ergänzung Version 0.2 (2026-10-31): ganze Ordner laden und auswerten

**Anlass:** In Version 0.1 konnte man nur einzelne Dateien auswählen. Danach ließ sich zwar durch den Ordner blättern, aber
nicht ein Ordner direkt öffnen und auch nicht komplett auswerten.

**Neu:**

| Funktion | Beschreibung |
|---|---|
| **Ordner öffnen …** | Ordner wählen. Auch **übergeordnete Ordner** sind möglich (z. B. `0029SET` mit 000–003, ein ganzer Flugtag oder `Bilder`). Alle Unterordner mit Aufnahmen werden gefunden, ◀/▶ blättert über die Ordnergrenzen hinweg. Die Anzeige lautet z. B. `0029SET\001\IMG_0200 (201/1672)`. Die Unterordner `Reflektanz_5Kanal` und `VI_Auswertung` werden dabei nicht als eigene Bildordner gezählt. |
| **Ordner auswerten …** | Wertet **alle Aufnahmen** eines (auch übergeordneten) Ordners aus. Vorher werden Anzahl, Datenquelle und geschätzte Dauer angezeigt. Fortschrittsbalken, **Abbrechen** möglich. |
| **Indexraster speichern** | optional: bei der Ordnerauswertung zusätzlich die 4 Indexraster je Aufnahme speichern (`<Ordner>\VI_Auswertung\IMG_XXXX\`, ca. 18 MB je Aufnahme) |

**Ergebnis der Ordnerauswertung** in `<gewählter Ordner>\VI_Auswertung\`:
- `Ordnerauswertung_<Datum_Uhrzeit>.csv`: je Aufnahme × Index × Region eine Zeile mit Ordner, Aufnahme, **Aufnahmezeit, GPS-Position**,
  Pixelanzahl, Mittel, Median, Std, Min, P5, P25, P75, P95, Max und Status. Regionen sind Gesamtbild und, bei aktiver Maske,
  Vegetation mit dem eingestellten Schwellwert. ROIs gelten nicht, weil sie nur für ein Bild definiert sind. Die Datei wird
  zeilenweise geschrieben, ein Abbruch hinterlässt also eine gültige Teilauswertung. Defekte Aufnahmen erscheinen mit
  `FEHLER: …` und brechen den Lauf nicht ab.
- `Ordnerauswertung_<…>_Parameter.json`: Protokoll mit Ordnerliste, Anzahl, Fehlerliste, Formeln, Maskierung und Schwellwert.

Aufnahmezeit und GPS werden bei vorhandenen Reflektanzbildern jetzt auch aus deren GDAL-Metadaten gelesen (vorher nur bei Rohbildern).

**Tests (2026-10-31):**
- `Flugtag130726` als Ordner geöffnet: 10 Bildordner, **1672 Aufnahmen** gefunden. Gesamter Bestand `Bilder`: 19 Ordner, 3204 Aufnahmen.
  Blättern von `0029SET\000\IMG_0199` (Reflektanzbild) nach `0029SET\001\IMG_0200` (Rohbilder) funktioniert. Für
  `0029SET\001` wurde dabei die Ausrichtung einmalig geschätzt und in `0029SET\001\VI_Auswertung\Ausrichtung.json` gespeichert.
- Ordnerauswertung `0026SET` mit Vegetationsmaske NDVI ≥ 0,40: 36/36 Aufnahmen in **18,6 s**, 288 Zeilen (36 × 4 Indizes × 2 Regionen).
  NDVI-Mittel des Gesamtbilds je Aufnahme zwischen 0,456 und 0,814. Beispiel IMG_0000: Gesamtbild 0,6479, Vegetation 0,7981
  (1.074.282 von 1.529.710 Pixeln).
- Abbruch während der Auswertung von `0029SET\000`: Stopp nach 6 Aufnahmen, Teil-CSV mit 24 gültigen Zeilen, Meldung „abgebrochen“.
- Korrektur dabei: Der Fortschrittsbalken wird jetzt bei jedem Start zurückgesetzt, und ein Abbruch wird als Abbruch gemeldet
  statt als normales Ende.
- Die Test-CSV-Dateien wurden danach gelöscht.

**Hinweis zur Dauer:** Ordner ohne vorverarbeitete Reflektanzbilder brauchen ≈ 4,5 s je Aufnahme plus einmalig ≈ 2 min für die
Ausrichtung je Ordner. Der ganze Flugtag 130726 (1672 Aufnahmen, davon 200 als Reflektanzbild) dauert damit grob 2 h.

## 5b. Ergänzung Version 0.3 (2026-10-31): Baummaske

**Anlass:** Die Vegetationsmaske (NDVI ≥ Schwelle) trennt Pflanzen von Boden, aber nicht die Bäume vom Gras zwischen den
Reihen. Die Bestände unterscheiden sich stark (Sichtprüfung NIR/NDVI/NDRE/Textur):
- **0029SET:** kleine, junge Pflanzen in dichtem Gras. Die Bäume sind im NIR eher dunkler als das Gras, der NDVI trennt kaum.
- **0030SET:** Pflanzreihen mit Gras und Unkraut.
- **0026SET:** große Bäume auf Bändchengewebe, Schotter und Asphalt. Hier trennt schon der NDVI gut.

Ein fester Schwellwert für alle Bestände ist daher nicht möglich.

**Entscheidung:** Die Baummaske ist eine **überwachte Pixelklassifikation mit Random Forest** (scikit-learn), gefolgt von
morphologischer Nachbearbeitung.

| Frage | Entscheidung | Begründung |
|---|---|---|
| Verfahren | Random Forest, 150 Entscheidungsbäume, `min_samples_leaf = 5`, `class_weight = balanced` | Etabliertes, robustes Verfahren für Fernerkundungsklassifikation (Breiman 2001). Kommt ohne Normierung der Merkmale aus und liefert die Wichtigkeit der Merkmale |
| Trainingsdaten | Nutzer umfährt in der Oberfläche frei Flächen „Baum“ und „kein Baum“, in beliebig vielen Bildern | Der Nutzer kennt die Bäume. In 0029SET ist z. B. nicht ohne Ortskenntnis erkennbar, was Baum und was Grasbüschel ist |
| Merkmale (20) | Reflektanz der 5 Kanäle, 4 Indizes, Helligkeit; lokale Mittelwerte von NIR, NDVI, Helligkeit und lokale Standardabweichung von NIR und Helligkeit in 2 Fenstergrößen (σ ≈ 4,5 und 15 cm) | Spektrale Information **und** Textur/Umgebung. Nadelkronen sind strukturreicher als Gras |
| Auflösung der Klassifikation | halbe Auflösung (≈ 1,5 cm/px), danach auf volle Auflösung hochgerechnet | 4× schneller; für Kronenumrisse ausreichend |
| Nachbearbeitung | Schwelle 0,5 auf die Baumwahrscheinlichkeit, morphologisches Öffnen/Schließen (Radius 4 px), Objekte < 1500 px entfernen, Lücken < 1500 px füllen (≈ 0,09 m²) | Entfernt Einzelpixel-Rauschen, ergibt zusammenhängende Kronen |
| Genauigkeitsprüfung | **5-fache Kreuzvalidierung, gruppiert nach Trainingsfläche**; Trefferquote je Klasse und ausgewogene Genauigkeit | Benachbarte Pixel einer Fläche sind sehr ähnlich. Eine pixelweise Zufallsaufteilung würde die Genauigkeit überschätzen |
| Modell speichern | `.joblib` (Modell + alle Trainingsflächen mit Merkmalen) und `_Info.json` (lesbares Protokoll) | Modell kann später um Flächen ergänzt und neu trainiert werden; nachvollziehbar für die Arbeit |

Alle Parameter stehen oben im Rechenkern unter `BAUM_…`. Eine Änderung der Merkmalsparameter macht gespeicherte Modelle ungültig;
das wird beim Laden geprüft.

**Bedienung:**
1. Zeichenmodus **„Training: Baum“** wählen und Baumkronen mit gedrückter linker Maustaste umfahren, im RGB- oder Indexbild.
   Durchgezogene grüne Linie = Baum.
2. **„Training: kein Baum“**: alles umfahren, was nicht Baum ist (Gras, Boden, Schatten, Wege, Dächer). Gestrichelte rote Linie.
3. Das in **mehreren Bildern** wiederholen (◀/▶), besonders in Bildern, die anders aussehen.
4. **Trainieren**. Die Meldung zeigt die Kreuzvalidierung und die wichtigsten Merkmale. Danach steht die Maske auf „Bäume (Modell)“,
   und der Umriss erscheint gelb im RGB-Bild.
5. Maske in mehreren Bildern kontrollieren, bei Fehlern gezielt Flächen nachtragen und neu trainieren.
   „Letzte Fläche entfernen“ macht den letzten Strich rückgängig.
6. **Modell speichern …**, dann **Ordner auswerten** mit Maske „Bäume (Modell)“. Regionen sind dann Gesamtbild und Baum. Die
   CSV enthält zusätzlich die Spalte „Maskenanteil“ (Anteil der Baumpixel am Bild), das Parameterprotokoll Modellpfad und Kreuzvalidierung.

Die Maske lässt sich mit den ROIs kombinieren („ROI n ∩ Baum“) und wird beim Export als `IMG_XXXX_Maske_Baum.tif` gespeichert.

**Tests (2026-10-31, 0026SET; Trainingsflächen von mir zum Test gesetzt, nicht vom Nutzer):**

| Schritt | Ergebnis |
|---|---|
| Training nur aus IMG_0018 (5 Baum-, 5 Kein-Baum-Flächen) | Kreuzvalidierung 100 %. Maske IMG_0018: 64 % Baum, Umrisse passend. **IMG_0005: 89 % „Baum“, die Wiese wurde fälschlich als Baum erkannt.** Im Training gab es kein Gras als Gegenbeispiel |
| + 2 Grasflächen aus IMG_0005 als „kein Baum“ | Wiese korrekt ausgeschlossen, Bäume in IMG_0005 aber nur lückenhaft erkannt (26 %). Kreuzvalidierung 99,8 % (Baum 100 %, kein Baum 99,7 %) |
| + 3 Baumflächen aus IMG_0005 | IMG_0005: 58 % Baum, Umriss entlang der Kronen, Wiese ausgeschlossen; IMG_0018 unverändert 64 %. Kreuzvalidierung 99,98 % |
| NDVI IMG_0018 | Gesamtbild 0,685 · Baum 0,885 · Rest 0,325 |
| Laufzeit | Merkmale 0,2 s, Training ≈ 8 s (inkl. Kreuzvalidierung), Maske je Bild ≈ 0,7–1 s |
| Speichern / Laden | Maske nach dem Laden pixelgleich |
| Ordnerauswertung 0026SET mit Baummaske | 36 Aufnahmen in 46 s, 288 Zeilen. Baumanteil je Bild 14–64 %. NDVI-Mittel der Bäume 0,81–0,90 gegenüber Gesamtbild 0,46–0,81 |

**Folgerung:** Wichtiger als eine hohe Kreuzvalidierungsgenauigkeit ist, dass das Training alle vorkommenden Oberflächen und
Baumerscheinungen abdeckt. Die Kreuzvalidierung prüft nur die eingezeichneten Flächen. Die Maske muss deshalb zusätzlich
**visuell in Bildern geprüft werden, die nicht im Training waren**. Für die Arbeit empfiehlt sich je Flugtag bzw. Bestand ein
eigenes Modell, oder ein gemeinsames Modell mit Trainingsflächen aus allen Beständen.

**Weitere Korrekturen in Version 0.3:**
- **Kanalausrichtung `0032SET\000` schlug fehl** (Rot → Red Edge: zu wenige gültige Schätzungen). Jetzt wird Rot ersatzweise über
  Grün ausgerichtet, analog zum Blaukanal. Ergebnis 0032SET\000: Rot über Grün mit 7 gültigen Schätzungen, Versatz (6,7; 0,0) px,
  plausibel gegenüber 4–5 px in den anderen Sets. Der verwendete Weg steht in `Ausrichtung.json` („ausrichtungsweg“).
- **Farbleiste** zeigte nach einem Bildwechsel −0,1 … 0,1 statt der eingestellten Skala. Behoben.
- Neues Paket: **scikit-learn 1.9.1** (mit scipy 1.18.1, joblib 1.6.0) installiert. OpenCV 5 enthält kein ML-Modul mehr.
- Alle Testdateien (Modell, Export, CSV) wurden danach gelöscht.

## 5c. Ergänzung Version 0.4 (2026-10-31): weitere Indizes, Zoomen

### Weitere Vegetationsindizes

**Auswahl:** Alle Indizes, die in der Arbeit (Word-Datei und Obsidian-Notizen, v. a. Kapitel 3) erwähnt werden und sich mit
den 5 Kanälen der RedEdge-P **direkt** berechnen lassen (Vorgabe des Nutzers):

| Index | Formel (B Blau 475, G Grün 560, R Rot 668, RE Red Edge 717, N NIR 842 nm) | Originalquelle* | Erwähnt in der Arbeit | Anzeigeskala |
|---|---|---|---|---|
| BNDVI | (N − B) / (N + B) | – (verwendet u. a. von Klouček et al. 2024, Ecke et al. 2024) | 3.2.3, 4.4.3 | −0,2 … 1,0 |
| SAVI | 1,5 · (N − R) / (N + R + 0,5), L = 0,5 | Huete (1988) | 2.3/3.1 (Weinbau), Kampen et al. 2019 | −0,2 … 1,0 |
| EVI | 2,5 · (N − R) / (N + 6R − 7,5B + 1) | Huete et al. (2002) | Trubin et al. 2023, Niu et al. 2023 | −0,2 … 1,0 |
| EVI2 | 2,5 · (N − R) / (N + 2,4R + 1) | Jiang et al. (2008) | MacDonald et al. 2025 (3.3, 3.5) | −0,2 … 1,0 |
| VARI | (G − R) / (G + R − B) | Gitelson et al. (2002) | 2.1.3, Trubin et al. 2023 | −0,2 … 0,8 |
| NGRDI | (G − R) / (G + R) | Tucker (1979) | Huo et al. 2025 | −0,2 … 0,8 |
| GLI | (2G − R − B) / (2G + R + B), identisch mit VDVI | Louhaichi et al. (2001); VDVI: Wang et al. (2015) | Huo et al. 2025 (GLI), Kampen et al. 2019 (VDVI) | −0,2 … 0,8 |

\* Entscheidung 2026-10-31: In der Arbeit werden von den ergänzenden Indizes nur **GLI und VARI** verwendet. Ihre Formeln sind über bereits vorhandene Quellen belegt (huo2025, Tabelle PDF-S. 8; trubin2023, Tabelle 2, PDF-S. 5). SAVI wurde verworfen (enger Wertebereich, Bodenkorrektur bei dichter Vegetation kaum relevant), VDVI ist formelgleich mit GLI. Die übrigen Indizes bleiben in der Software verfügbar. Originalarbeiten werden bewusst nicht zusätzlich beschafft; huete2002, jiang2008, tucker1979 liegen im Vault, sind aber derzeit nicht verwendet.

**Nicht aufgenommen:**

| Index | Grund |
|---|---|
| PRI, CCI | benötigen 531 nm, kein Kanal der RedEdge-P |
| REIP | benötigt mehrere Kanäle im Red Edge (vgl. 2.2.2) |
| MRDWSI3 | auf Sentinel-2-Kanäle zugeschnitten (MAIA S2) |
| PSRI | original (R680 − R500)/R750. Mit der RedEdge-P nur näherungsweise (Blau 475 statt 500, Red Edge 717 statt 750 nm). Auf Wunsch des Nutzers nicht aufgenommen |
| CCCI | erfordert bestandsspezifisch kalibrierte NDRE-Grenzlinien je NDVI (Barnes et al. 2000), kein reiner Pixelindex |
| Blue Ratio, RENDVI (Kampen et al. 2019) | Definition in der Arbeit nicht angegeben; RENDVI entspricht je nach Definition NDRE oder ReNDVI |

**Umsetzung:** Jeder Index ist als Zähler/Nenner definiert, mit eigenem gültigen Wertebereich und eigener fester Farbskala.
Ungültig (NaN) ist ein Pixel bei \|Nenner\| < 0,01, bei Reflektanz < −0,02 in einem verwendeten Kanal oder bei einem Wert
außerhalb des gültigen Bereichs (SAVI ±1,5, alle anderen ±1). Bei den normierten Differenzen ist Letzteres nicht möglich,
ihre Ergebnisse sind deshalb **unverändert** (NDVI/NDRE/GNDVI von IMG_0100 weiter 0,8715 / 0,4795 / 0,7856).
Das Baummodell verwendet weiterhin nur die 4 Kernindizes als Merkmale, gespeicherte Modelle bleiben also gültig.

**Prüfung (0029SET\000\IMG_0100, 1.530.776 Pixel):** Alle Indizes stimmen am Pixel (250, 201) mit einer Handrechnung überein
(Abweichung < 10⁻⁵).

| Index | gültig | Mittel | P5 | P95 |
|---|---|---|---|---|
| BNDVI | 100 % | 0,933 | 0,868 | 0,966 |
| SAVI | 100 % | 0,401 | 0,297 | 0,482 |
| EVI | 100 % | 0,391 | 0,277 | 0,486 |
| EVI2 | 100 % | 0,389 | 0,278 | 0,481 |
| VARI | 99,84 % | 0,370 | 0,039 | 0,610 |
| NGRDI | 99,96 % | 0,307 | 0,031 | 0,512 |
| GLI | 100 % | 0,424 | 0,197 | 0,584 |

Bei VARI und NGRDI sind sehr dunkle Pixel ungültig (Nenner < 0,01). Die Anzeigeskala −0,2 … 0,8 für VARI/NGRDI/GLI
wurde nach diesen Werten gewählt.

**Export bei 11 Indizes:** Damit nicht unnötig Speicher belegt wird (≈ 4,5 MB je Indexraster und Bild):
- Einzelexport: Raster nur des **angezeigten** Index; die Statistik-CSV enthält weiterhin **alle** Indizes.
- Ordnerauswertung: Mit „Indexraster speichern“ wird ebenfalls nur der angezeigte Index gespeichert; die CSV enthält alle Indizes.

### Zoomen und Verschieben

| Aktion | Bedienung |
|---|---|
| Zoomen | **Mausrad** über dem RGB- oder Indexbild, zentriert auf den Mauszeiger (Faktor 1,3 je Schritt, bis ≈ 20 px Bildbreite) |
| Verschieben | **rechte Maustaste** gedrückt halten und ziehen |
| Zurücksetzen | Knopf **„Ganzes Bild“** |

- RGB- und Indexbild sind gekoppelt und zeigen immer denselben Ausschnitt.
- Zoomen und Verschieben funktionieren **in jedem Zeichenmodus**. Man kann also beim Einzeichnen von Trainingsflächen oder
  ROIs vergrößern und verschieben, ohne den Modus zu wechseln (Zeichnen = linke Maustaste).
- Der Ausschnitt bleibt innerhalb der Bildgrenzen.
- Bei starker Vergrößerung werden die Pixel ohne Glättung angezeigt (nächster Nachbar), sodass einzelne Pixel erkennbar sind.

**Tests:**
- 3 Zoomschritte um (500, 450): Ausschnitt 653 × 485 px, beide Bilder synchron.
- Verschieben und Begrenzung am Bildrand funktionieren.
- Rechtsklick löst keine Pixelabfrage aus.
- Eine Trainingsfläche im gezoomten Zustand wurde korrekt übernommen.
- „Ganzes Bild“ stellt 1435 × 1066 px wieder her.
- Testexporte wurden gelöscht.

**Korrektur (2026-11-01): Bild schrumpfte beim Zoomen.** Ursache: Beschriftungen im Bild (ROI-, Baum- und
Referenznummern) wurden nicht am Bildrand abgeschnitten. Lagen sie nach dem Zoomen außerhalb des Ausschnitts, verkleinerte
das automatische Layout (matplotlib „constrained layout“) die Bildachsen, um ihnen Platz zu machen (Test: Bildbreite
0,378 → 0,247 der Fensterbreite nach 4 Zoomschritten, zeitweise „axes sizes collapsed“). Lösung: Alle Einblendungen (Texte,
Umrisse, Polygone, ROI-Rechtecke) werden am Bildrand abgeschnitten und aus der Layoutberechnung genommen. Prüfung: Zoomen
an allen vier Bildecken und Verschieben über alle Ränder (36 Schritte) – Achsengröße unverändert, Ausschnitt bleibt im Bild.

## 5d. Vorgehen beim Training des Baummodells (Leitfaden, 2026-10-31)

**Anlass:** Frage des Nutzers, ob Bäume einzeln oder als zusammenhängende Fläche markiert werden sollen, wenn der Rest als
„kein Baum“ markiert wird. Die Empfehlungen folgen direkt aus der Funktionsweise der Software (Parameter in `vi_kern.py`).

### Wie die Software Trainingsflächen verwendet

| Eigenschaft | Umsetzung | Folge für das Einzeichnen |
|---|---|---|
| Klassenzuordnung | **Alle** Pixel innerhalb einer gezeichneten Fläche erhalten deren Klasse. Nicht umfahrene Pixel werden **nicht** verwendet, es gibt keinen impliziten „Rest“ | Eine Fläche über mehrere Kronen lernt Gras/Boden/Schatten dazwischen als „Baum“; „Rest als kein Baum“ korrigiert das nicht |
| Stichprobe je Fläche | max. 4000 Pixel je Fläche (`BAUM_MAX_PIXEL_JE_FLAECHE`), auf halber Auflösung (`BAUM_FAKTOR = 2`, ≈ 1,5 cm/px) | Eine sehr große Fläche bringt nicht mehr Information als eine mittelgroße; Vielfalt entsteht durch **viele** Flächen |
| Genauigkeitsprüfung | Kreuzvalidierung mit k = min(5, Anzahl Baumflächen, Anzahl Kein-Baum-Flächen) Gruppen; jede Fläche liegt vollständig in einer Gruppe | Mindestens 2 Flächen je Klasse (sonst Abbruch). Aussagekräftig erst ab ≈ 5–10 Flächen je Klasse |
| Klassengewicht | `class_weight = balanced` | Ungleiche Pixelzahlen der Klassen werden ausgeglichen; trotzdem beide Klassen ähnlich vielfältig erfassen |

### Empfohlenes Vorgehen

1. **Bilder wählen:** 3–5 Aufnahmen, die sich unterscheiden (Bildmitte/-rand, Licht/Schatten, dichte und lückige Bereiche,
   möglichst mit gestressten Bäumen). Bei mehreren Beständen/Flugtagen Bilder aus jedem.
2. **Zoomen:** Mausrad zum Heranzoomen, rechte Maustaste zum Verschieben (auch im Zeichenmodus).
3. **„Training: Baum“:** Kronen **etwas innerhalb des Kronenrands** umfahren; Randpixel mit Hintergrundanteil vermeiden.
   - Einzelne Bäume **einzeln** umfahren, wenn Gras oder Boden dazwischen liegt (z. B. 0029SET, 0030SET).
   - Eine größere Fläche über mehrere Kronen nur bei **geschlossenem Kronendach ohne Lücken** (z. B. 0026SET).
   - **Gestresste Bäume bzw. Kronenteile (braune/rote Triebe) bewusst einschließen.** Sonst fehlen sie in der Maske, und
     gerade die für die Vitalitätsanalyse wichtigen Pixel werden ausgeschlossen.
   - Nicht jeden Baum markieren; das Modell überträgt das Gelernte.
4. **„Training: kein Baum“:** alle vorkommenden Oberflächen einzeichnen: Gras, trockene Grasbüschel, offener Boden, Schatten
   zwischen den Reihen und Kronen, Wege, Folie/Gewebe, Dächer. Lücken zwischen Kronen nur dann, wenn sie nicht zur
   Baumfläche zählen sollen.
5. **Umfang:** ≈ 10–20 Flächen je Klasse, verteilt auf die gewählten Bilder.
6. **Unsichere Stellen weglassen:** Eine falsch markierte Fläche schadet mehr als eine fehlende. Das gilt besonders für
   0029SET, wo junge Bäume und Grasbüschel schwer zu unterscheiden sind.
7. **Trainieren** und die Meldung prüfen (Trefferquote je Klasse, ausgewogene Genauigkeit, wichtigste Merkmale).
8. **Kontrolle in Bildern außerhalb des Trainings:** gelber Umriss im RGB-Bild. Fehler gezielt mit einer neuen Fläche
   korrigieren (z. B. fälschlich erkannte Wiese als „kein Baum“) und neu trainieren. „Letzte Fläche entfernen“ macht die
   letzte Fläche rückgängig.
9. **Modell speichern**, bevor es in der Ordnerauswertung verwendet wird (das Protokoll verweist auf die Datei).

### Hinweise für die Arbeit

- Die Kreuzvalidierung prüft nur die eingezeichneten Flächen. Eine hohe Genauigkeit belegt **nicht**, dass das Modell auf
  allen Bildern richtig liegt; die visuelle Kontrolle (Schritt 8) gehört zur Methode und sollte beschrieben werden.
- Anzahl der Flächen je Klasse, verwendete Bilder und Kreuzvalidierung stehen in `<Modell>_Info.json` und können als Beleg
  in die Arbeit übernommen werden.
- Pro Bestand bzw. Flugtag ein eigenes Modell oder ein gemeinsames Modell mit Flächen aus allen Beständen; die Wahl sollte
  begründet werden.

## 5e. Ergänzung Version 0.5 (2026-10-31): Schwellwerte und Bewertung je Baum

**Anlass:** In der Indexkarte erschienen die meisten Bäume als „in Ordnung“. Teilweise geschädigte Kronen (braune/rote
Triebe) fallen im Mittelwert kaum auf, weil die gesunden Pixel überwiegen.

### Umsetzung

| Baustein | Umsetzung |
|---|---|
| Pixelklassen | Je Index zwei Schwellen: Wert < *gestresst* → **gestresst**; *gestresst* ≤ Wert < *vital* → **Übergang**; Wert ≥ *vital* → **vital** (gleiche Schwellen = 2 Klassen). Alle Indizes der Software steigen mit der Vitalität. Ungültige Pixel bleiben ohne Klasse |
| Schwellen je Index | werden je Index gemerkt; Klassifizierung je Index ein-/ausschaltbar. Prüfung: *vital* ≥ *gestresst* |
| Startwerte | Knopf „Startwerte P10/P30“: 10. und 30. Perzentil der aktuellen Maske. **Nur Ausgangspunkt** (bildrelativ, markiert immer ≈ 10 % als gestresst); für die Auswertung feste, begründete Schwellen festlegen |
| Baumobjekte | Zusammenhängende Flächen der aktuellen Maske (Baummodell oder Vegetation), ab 1500 px (≈ 0,09 m²) |
| Kronentrennung (optional) | Berührende Kronen bilden sonst ein gemeinsames Objekt. Mit „Kronen trennen, Abstand > 0“: Wasserscheiden-Segmentierung (OpenCV `watershed`) auf der Distanztransformation der Maske; Saatpunkte = lokale Maxima (Kronenmitten) mit dem angegebenen Mindestabstand in Pixeln |
| Markierung je Baum | Ein Objekt wird **markiert**, wenn der Anteil gestresster Pixel ≥ dem eingestellten Prozentsatz ist (Vorgabe 10 %) – unabhängig vom Mittelwert |
| Anzeige | Klassenkarte (rot/orange/grün) statt Farbverlauf; Schwellen als Linien im Histogramm; Klassenanteile je Region (Gesamtbild, Maske, ROIs) in eigener Tabelle; im RGB-Bild nummerierte Objekte, markierte rot umrandet; Pixelabfrage zeigt die Klasse |
| Export | `<IMG>_<Index>_Klassen.tif` (0 gestresst, 1 Übergang, 2 vital, 255 ungültig), `<IMG>_<Index>_Objekte.csv` (je Objekt Fläche, Lage, Mittel, Median, Klassenanteile, markiert); Statistik-CSV mit Spalten Anteil_gestresst/Uebergang/vital, Objekte, Objekte_markiert; Schwellen im Parameterprotokoll |
| Ordnerauswertung | gleiche Zusatzspalten für alle Indizes mit eingeschalteten Schwellen; Schwellen sind für alle Bilder **fest** (absolute Werte) und stehen im Parameterprotokoll |

### Tests (0026SET\000\IMG_0018, Maske Vegetation NDVI ≥ 0,6, NDVI-Schwellen 0,80 / 0,88, Markierung ab 10 %)

*Die Schwellen sind Testwerte, keine fachlich begründeten Grenzen.*

| Prüfung | Ergebnis |
|---|---|
| Klassenanteile Gesamtbild / Maske | gestresst 44,2 % / 11,1 %, Übergang 9,2 % / 14,6 %, vital 46,6 % / 74,2 %; Handrechnung (Anteil NDVI < 0,80) = 0,442 ✓ |
| Objekte ohne Kronentrennung | **2 Objekte** – das gesamte Kronendach ist ein zusammenhängendes Objekt (951.332 px) → Bewertung je Baum ohne Trennung in geschlossenen Beständen nicht sinnvoll |
| Objekte mit Kronentrennung 100 / 150 px | 25 / 21 Objekte, je 9 markiert; markiert werden v. a. Kronen mit sichtbar roten/braunen Trieben (linker Rand, unten). Die Trenngrenzen folgen den Kronen nur näherungsweise |
| Laufzeit Objektbewertung | 0,2–0,35 s je Bild |
| Index wechseln | Schwellen bleiben je Index erhalten; Index ohne Schwellen startet ausgeschaltet; Einschalten setzt Startwerte P10/P30 |
| Ungültige Eingabe (vital < gestresst) | abgewiesen mit Meldung |
| Export / Ordnerauswertung 0026SET | alle Dateien/Spalten vorhanden; 36 Bilder in 49 s |

### Hinweise für die Arbeit

- **Schwellen begründen:** z. B. aus Referenzbäumen (visuell sicher vitale bzw. geschädigte Kronen als ROIs, Verteilungen vergleichen) oder aus der Literatur. Bildrelative Startwerte (Perzentile) sind für Vergleiche zwischen Flügen ungeeignet.
- **Kronentrennung** ist eine Näherung (Wasserscheide auf der Maskenform); der Abstand sollte etwa dem Kronenradius entsprechen und visuell geprüft werden. Mit einer gut trainierten Baummaske (Schatten zwischen Kronen = „kein Baum“) werden die Grenzen besser.
- Die Markierungsregel (Anteil gestresster Pixel ≥ x %) ist eine eigene Festlegung und sollte als solche beschrieben werden.

## 5f. Ergänzung Version 0.6 (2026-10-31): Schwellen aus Literatur und Referenzbäumen

### Literaturprüfung

**Frage des Nutzers:** Lassen sich die Standard-Schwellen der Software aus der Literatur ableiten? Durchsucht wurden alle
68 PDFs im Vault (Indexwerte im Zusammenhang mit gesund/gestresst/abgestorben, Schwellen, Klassen).

| Index | Literaturangabe | Quelle (PDF-Seite) | Art der Grenze |
|---|---|---|---|
| NDVI | < 0 keine Vegetation, 0–0,33 ungesund, 0,33–0,66 gesund, > 0,66 sehr gesund | Wang 2021, S. 1 (DroneDeploy, „subjektiv“ gesetzt); Vera-Esmeraldas et al. 2025, S. 12 (Weinbau) | Vegetation/Boden, Ackerbau |
| NDVI | gesund 0,6–0,9, Stress < 0,4 | Nguyen et al. 2025, S. 2 (Ackerbau) | Ackerbau |
| NDVI | Balsamtanne Mittel ≈ 0,65 (0,50–0,80) | MacDonald et al. 2025, S. 8 (MicaSense Altum) | Wertebereich, keine Grenze |
| GNDVI | gesund 0,5–0,8, starker Stress < 0,3 | Nguyen et al. 2025, S. 3 | Ackerbau |
| EVI | gesund 0,2–0,8, schwaches Wachstum < 0,15 | Nguyen et al. 2025, S. 3 | Ackerbau |
| EVI2 | Balsamtanne Mittel ≈ 0,64 (0,52–0,75) | MacDonald et al. 2025, S. 9 | Wertebereich |
| ReNDVI | < 0,1 keine Vegetation; Rasen 0,2–0,5, Wald 0,5–0,85 | Wang 2021, S. 1, 15 | Vegetationsdichte |
| NGRDI | < 0,15 Waldboden (Maskierung) | Huo et al. 2025, S. 5 | Boden/Baum |
| NDRE, VARI, GLI, BNDVI, SAVI | keine Grenzwerte in den Quellen | – | – |

**Anwendung auf eigene Daten** (Pixel der Vegetationsmaske NDVI ≥ 0,6):

| Grenzen | 0026SET IMG_0018 (große Bäume) | 0029SET IMG_0100 (junge Bäume/Gras) |
|---|---|---|
| NDVI 0,33 / 0,66 (Wang; Vera-Esmeraldas) | 0,0 % gestresst, 97,6 % vital | 0,0 % / 99,0 % |
| NDVI 0,4 / 0,6 (Nguyen) | 0,0 % / 100 % | 0,0 % / 100 % |
| GNDVI 0,3 / 0,5 (Nguyen) | 0,0 % / 99,9 % | 0,0 % / 100 % |
| EVI 0,15 / 0,2 (Nguyen) | 5,7 % / 90,3 % | 0,0 % / 99,7 % |
| Wertebereich NDVI (P5/P50/P95) | 0,72 / 0,92 / 0,96 | 0,74 / 0,89 / 0,94 |

**Ergebnis:** Die Literaturgrenzen sind als Standard ungeeignet; sie stufen praktisch alle Baumpixel als vital ein. Gründe:
(1) Sie trennen Vegetation von Boden bzw. schwach bewachsenen Flächen in Acker- und Weinbau, nicht leichten Stress in dichten
Nadelkronen. (2) Sie sind sensor- und kalibrierabhängig; Wang (2021, S. 15) beobachtet bei RedEdge-Kameras ungewöhnlich
hohe NDVI-Werte, und die Balsamtannen bei MacDonald et al. (Altum) liegen niedriger als die eigenen Werte. (3) Für NDRE, VARI
und GLI enthalten die Quellen keine Stressgrenzen. Die Literaturwerte werden in der Software daher nur **zur Orientierung**
je Index angezeigt (`LITERATUR_ORIENTIERUNG`).

### Schwellen aus Referenzbäumen

| Schritt | Umsetzung |
|---|---|
| Referenzflächen | Zeichenmodi „Referenz: vital“ / „Referenz: geschädigt“ (Freihand). Bei aktiver Maske zählen nur Maskenpixel. Je Fläche max. 5000 Pixel (Stichprobe); gespeichert werden die Werte **aller** Indizes, Flächen aus beliebig vielen Bildern |
| Trennschärfe je Index | AUC = P(Wert vitales Pixel > Wert geschädigtes Pixel), berechnet über die Mann-Whitney-U-Statistik (scipy) |
| Youden-Schwelle | Schwelle t mit maximalem J = Sensitivität + Spezifität − 1 (Sensitivität: geschädigte Pixel < t; Spezifität: vitale Pixel ≥ t); ROC-Standardmaß |
| Flächenebene | Median jeder Referenzfläche mit der Youden-Schwelle eingeordnet → „Flächen richtig“ (robuster als Pixel, da Pixel einer Fläche nicht unabhängig sind) |
| Schema 3 Klassen (Vorgabe) | **gestresst** < P5 der vitalen Referenzpixel; **vital** ≥ P95 der geschädigten Referenzpixel; dazwischen **Übergang** = Überlappungsbereich beider Verteilungen. Ohne Überlappung: beide Schwellen = Youden |
| Schema 2 Klassen | gestresst < Youden-Schwelle ≤ vital |
| Richtungsprüfung | AUC < 0,5 (geschädigte Referenzen haben höhere Werte) → keine Übernahme mit Meldung |
| Protokoll | Herkunft der Schwellen (Referenzflächen, AUC, Youden, Regel) im Parameterprotokoll von Export und Ordnerauswertung; manuelle Änderung → Herkunft „manuell“ |
| Speichern | Referenzflächen als `.joblib`, Auswertungstabelle als CSV (`Referenzauswertung.csv`) – direkt verwendbar für Kapitel 4.4.2 |

### Tests

- **Synthetisch** (Normalverteilungen μ = 0,89 vs. 0,79, σ = 0,03): Youden-Schwelle 0,840 (erwartet ≈ 0,84), AUC 0,987,
  4/4 Flächen richtig.
- **0026SET IMG_0018**, je 3 grob gesetzte Rechtecke (grüne Kronen Mitte = vital, rot-braune Kronen links/unten =
  geschädigt) – *nur Technik-Test, keine fachlich geprüften Referenzen*: AUC VARI 0,818, NGRDI 0,790, ReNDVI 0,790,
  NDVI 0,772, GLI 0,757; NDRE/BNDVI 0,589; GNDVI, SAVI, EVI, EVI2 ≈ 0,47–0,49 (keine Trennung, nicht übernommen).
  VARI: Youden 0,565, Schema 3 → gestresst < 0,231, vital ≥ 0,702 (großer Überlappungsbereich).
- Speichern/Laden der Referenzen identisch; CSV mit 11 Indizes; Herkunft bleibt bei unveränderten Werten erhalten
  (Korrektur: Rundung der Anzeige führte zunächst zu „manuell“).
- Alle Testdateien wurden ausschließlich im Scratchpad-Ordner abgelegt; die Datenordner blieben unverändert.

### Ergänzung 2026-11-01: Schwellen im Histogramm verschieben

Die Schwellenlinien im Histogramm (rot gestrichelt = gestresst, grün gestrichelt = vital) lassen sich mit der linken
Maustaste ziehen. Der Mauszeiger wird über einer Linie zum Doppelpfeil. Beim Ziehen folgt die Linie der Maus und der Wert
steht in der Statuszeile. Beim Loslassen werden die Werte in die Eingabefelder übernommen und Klassenkarte,
Klassenanteile und Baummarkierung neu berechnet; die Herkunft wird als „manuell (im Histogramm verschoben)“ protokolliert.
„gestresst“ kann nicht über „vital“ hinaus geschoben werden; liegen beide aufeinander (2-Klassen-Schema), bewegen sie sich
gemeinsam. Rechte Maustaste und Klicks neben die Linien ändern nichts.
Test (0026SET IMG_0018, NDVI): gestresst 0,80 → 0,85 ergab gestresst 11,1 % → 18,3 % der Maske; vital 0,88 → 0,93 ergab
vital 74,2 % → 43,2 %; Begrenzung, gemeinsames Verschieben und Herkunftsprotokoll wie erwartet.

### Hinweise für die Arbeit

- **Referenzen:** nur sicher erkennbare Kronen (z. B. deutliche Nadelverfärbung bzw. eindeutig vitale Kronen), möglichst
  je ≥ 5 Flächen aus mehreren Bildern; Kriterium der Auswahl beschreiben (visuell im RGB, Feldbegehung …).
- **Zirkularität vermeiden:** Wenn Schwellen und Trennschärfe aus denselben Referenzflächen stammen, ist die Güte
  überschätzt. Besser: Referenzen in Ableitungs- und Prüfflächen aufteilen (z. B. nach Bildern).
- Die Youden-Schwelle ist ein Standardmaß der ROC-Analyse; eine eigene Quelle wird bewusst nicht ergänzt (Quellenumfang).

## 5g. Ergänzung Version 0.7 (2026-11-01): Bäume nach Klassen einfärben

Jeder Baum (Objekt der Maske) erhält eine Klasse: **gestresst**, wenn ≥ x % seiner Pixel gestresst sind (Eingabe „Baum
gestresst ab“); sonst **vital**, wenn ≥ 50 % seiner Pixel vital sind (`OBJEKT_VITAL_ANTEIL`, entspricht Median ≥ Schwelle
vital); sonst **Übergang**. Im RGB-Bild werden die Bäume halbtransparent in der Klassenfarbe gefüllt (rot/orange/grün),
Baumgrenzen kräftiger; der gelbe Maskenrand bleibt sichtbar (Schalter „Bäume einfärben“). Die Maske selbst hängt nicht
von den Schwellen ab (geprüft: Maske pixelgleich bei gestresst-Schwelle 0,70–0,95). Export: `<IMG>_<Index>_Baumklassen.tif`
(0/1/2, 255 = kein Baum), Spalte „Klasse“ in `Objekte.csv`; Statistik und Ordnerauswertung mit Objekte_gestresst /
Objekte_Uebergang / Objekte_vital (ersetzt „Objekte_markiert“). Test 0026SET-Kopie (NDVI 0,83/0,90, 10 %, Kronenabstand
100 px): IMG_0018 25 Bäume = 11 gestresst / 0 Übergang / 14 vital; Regel für alle Bäume nachgerechnet; Zoom bleibt beim
Neuberechnen erhalten. Tests nur in einer Kopie im Scratchpad.

## 5h. Ergänzung Version 0.8 (2026-11-01): Maske verfeinern, Kronengrenzen am NIR ausrichten

### Anlass

Mit dem neu trainierten Baummodell (11 + 18 Trainingsflächen, ausgewogene Genauigkeit 0,977) sitzen die Außenränder der
Maske in 0026SET ordentlich, aber **die dunklen Lücken zwischen den Kronen (Boden, Schatten, Unterwuchs) zählen fast
überall zum Baum**. Ursachen: Das Modell arbeitet auf halber Auflösung mit Umgebungsmerkmalen (Gauß-σ 4,5 und 15 cm),
die Wahrscheinlichkeit wird hochskaliert, geglättet (Radius 4 px) und Lücken < 1500 px werden gefüllt. Dadurch hing das
ganze Kronendach zusammen (IMG_0018: 2 Objekte ohne, 15 Objekte mit Kronentrennung 100 px; die Objekte liefen über
mehrere Kronen).

Werte in IMG_0018 (Mittel über 9 × 9 px):

| Stelle | NDVI | NIR | Rot |
|---|---|---|---|
| Krone, besonnt | 0,95 | 0,478 | 0,011 |
| Lücke zwischen Kronen | 0,89 | 0,078 | 0,005 |
| Schatten am Kronenrand | 0,86 | 0,100 | 0,008 |

→ Im NDVI unterscheiden sich Lücken kaum von Nadeln (Pflanzenmaterial im Schatten), im **NIR** sehr deutlich.
Die NIR-Verteilung innerhalb der Maske hat einen kleinen eigenen Gipfel bei 0,08–0,12 (≈ 5 % der Maske = Lücken)
und steigt danach gleichmäßig an (beschattete bis besonnte Nadeln).

### Verworfene Varianten (Test IMG_0018)

| Variante | Ergebnis |
|---|---|
| Random Forest im Randband in voller Auflösung | ändert nur 0,35–0,5 % der Pixel; die Umgebungsmerkmale dominieren, Lücken bleiben |
| Geführter Filter (guided filter) auf der Wahrscheinlichkeit, Führung NIR | glattere Ränder, Lücken bleiben |
| Otsu-Schwelle auf NIR innerhalb der Maske | Schwelle 0,354, schneidet auch beschattete Kronenseiten weg (Maske 57 % → 34 %) |
| Otsu auf log(NIR) | Schwelle 0,28, ebenfalls zu hoch (26 % der Maske entfernt) |
| relative Schwelle 40 % von P90 | Kronenränder werden bereits angeschnitten |

### Umsetzung (`verfeinere_maske` in `vi_kern.py`)

Schalter **„verfeinern, Lücken < x % NIR“** in der zweiten Leiste, gilt für Baum- und Vegetationsmaske, Vorgabe 30 %.

1. NIR leicht glätten (Gauß-σ 2 px).
2. **Lückenschwelle = x % des 90. Perzentils des NIR innerhalb der Maske** (relativ, damit unabhängig von Beleuchtung
   und Flug). Pixel darunter gelten als Lücke und werden entfernt.
3. Nur bei Baummaske: Die Maske darf um bis zu 6 px nach außen wachsen, wo das Modell eine Baumwahrscheinlichkeit
   ≥ 0,3 liefert und der NIR über der Schwelle liegt (Nadelspitzen am Rand).
4. Leichte Glättung (Öffnen/Schließen Radius 2 px statt 4 px), Splitter und Löcher < 300 px entfernen bzw. füllen.

Die Statuszeile zeigt je Bild den Maskenanteil vorher/nachher, entfernte und ergänzte Fläche und die NIR-Schwelle.
Laufzeit ≈ 0,05 s zusätzlich.

### Kronentrennung an NIR ausrichten (`objekt_labels`)

Schalter **„an NIR ausrichten“** neben dem Kronenabstand (Vorgabe: an). Statt nur der Distanz zum Maskenrand wird eine
„Kronenhöhe“ geflutet:

  Höhe = 0,5 · min(Distanz / (½ · Kronenabstand), 1) + 0,5 · min(NIR_geglättet / P95_NIR(Maske), 1),  NIR-Glättung σ = 4 px

Kronenmitten (Saatpunkte) sind damit Stellen, die weit vom Rand **und** hell sind; die Grenzen zwischen berührenden
Kronen verlaufen entlang dunkler, beschatteter Bereiche. Mindestabstand der Saatpunkte wie bisher = Kronenabstand.

### Tests (Kopie von 0026SET\000, IMG_0005/0018/0030; Modell `Baummodell.joblib` des Nutzers als Kopie)

| Prüfung | Ergebnis |
|---|---|
| Verfeinerung aus | Maske pixelgleich mit Version 0.7 ✓ |
| IMG_0018, Lücke 20 / 30 / 40 % | Maske 57,2 % → 56,7 / 54,7 / 51,0 % des Bildes; entfernt 1,6 / 3,3 / 6,8 %, ergänzt 1,1 / 0,9 / 0,6 % |
| Sichtprüfung 30 % | Lücken zwischen den Kronen sauber ausgeschnitten, Kronen und beschattete Seiten bleiben erhalten |
| Objekte (Kronenabstand 100 px) | alte Maske 15 · verfeinert, nur Form 32 (teils längliche Objekte) · **verfeinert + NIR 41 kompakte, kronenförmige Objekte** (vereinzelt eine Krone geteilt) |
| Klassen IMG_0018 (NDVI 0,83/0,90, 10 %) | 41 Bäume: 13 gestresst, 0 Übergang, 28 vital; Regel je Baum nachgerechnet ✓ |
| Ordnerauswertung (3 Bilder) | ohne Fehler; Bäume je Bild 36 / 41 / 40 |
| Parameterprotokoll | enthält Verfeinerung (alle Parameter) und Art der Kronentrennung ✓ |
| 0029SET\000\IMG_0100, Vegetationsmaske NDVI ≥ 0,4 | Schwelle 0,074 (30 % von 0,245) – nichts entfernt. Junge Bäume dort sind im NIR dunkler als Gras, aber weit über der Lückenschwelle; ohne Baummodell für 0029SET nicht weiter prüfbar |

### Prüfung mit den Referenzbäumen des Nutzers (`Bilder\VI_Auswertung\Referenzbaeume.joblib`, Kopie)

9 Referenzflächen (5 vital, 4 geschädigt) in 0026SET\000 IMG_0032/0033/0035, Baummodell `Bilder\VI_Auswertung\Baummodell.joblib`.
Kronenabstand 100 px. Für jede Referenzfläche wird der Baum (Objekt) mit der größten Überlappung bewertet.

**Pixelebene:** AUC und Youden-Schwellen aller 11 Indizes sind mit und ohne Verfeinerung identisch (z. B. NDVI 0,785,
VARI 0,842), da die Referenzflächen innerhalb der Kronen liegen und die Verfeinerung dort nichts ändert.
→ bereits abgeleitete Schwellen bleiben gültig.

**Baumebene, Anteil gestresster Pixel je Referenzbaum** (2-Klassen-Schema, Youden-Schwelle):

| Index | Maske | vitale Bäume | geschädigte Bäume | richtig bei „Baum gestresst ab“ 10 / 25 / 40 % |
|---|---|---|---|---|
| NDVI (< 0,915) | alt (0.7) | 0,17 – 0,42 | 0,29 – 0,42 | 4 / 6 / 6 von 9 |
| NDVI | verfeinert + NIR-Trennung | **0,07 – 0,19** | **0,29 – 0,65** | 5 / **9** / 7 von 9 |
| VARI (< 0,601) | alt (0.7) | 0,14 – 0,36 | 0,33 – 0,51 | 4 / 6 / 8 von 9 |
| VARI | verfeinert + NIR-Trennung | **0,09 – 0,18** | **0,41 – 0,72** | 5 / **9** / **9** von 9 |

→ Mit alter Maske überlappen vitale und geschädigte Bäume (Objekte enthielten Lücken/Schatten und Teile von Nachbarkronen).
Mit Verfeinerung und NIR-Trennung sind sie klar getrennt; ab 25 % werden alle 9 Referenzbäume richtig eingestuft.

**3-Klassen-Schema (P5 vital / P95 geschädigt):** Kein vitaler Baum wird „vital“ (NDVI vital ≥ 0,960 = P95 der
geschädigten; ≥ 50 % der Kronenpixel darüber erreicht kein Baum), vitale Bäume landen in „Übergang“ oder „gestresst“;
geschädigte immer „gestresst“. Das liegt an Schema + Baumregel, nicht an der Maske.

Einschränkungen: nur 9 Bäume aus einem Bestand; Schwellen und Prüfung beruhen auf denselben Referenzen (zirkulär).
Für die Arbeit Referenzen in Ableitungs- und Prüfbäume teilen.

### Hinweise für die Arbeit

- Die Verfeinerung setzt voraus, dass Lücken/Schatten **deutlich** dunkler sind als die Kronen (geschlossene Bestände
  wie 0026SET). Der Anteil x ist eine eigene Festlegung (Sichtprüfung) und muss im Protokoll bzw. in 4.3.3 stehen.
- Sehr dunkel beschattete Kronenteile können als Lücke herausfallen; die Klassenanteile je Baum beziehen sich dann
  auf den besser beleuchteten Teil der Krone (für Vitalitätsindizes eher vorteilhaft, da Schatten die Indizes verfälscht).
- Kronentrennung bleibt eine Näherung; Abstand ≈ Kronenradius, visuell prüfen.

## 5i. Ergänzung Version 0.8.1 (2026-11-01): Bildnummer eingeben, Referenzen hinzuladen

**Direkt zu einem Bild springen:** Die Bildnummer in der oberen Leiste ist ein Eingabefeld (Anzeige z. B. `22 /100`).
Hineinklicken (Inhalt wird markiert), eingeben, Enter:

| Eingabe | Wirkung |
|---|---|
| Zahl ohne führende Null, z. B. `57` | laufende Nummer in der aktuellen Liste (1 … N, über Ordnergrenzen hinweg) |
| Aufnahmename `IMG_0018`, `IMG_18` oder `0018` | diese Aufnahme; gibt es sie in mehreren Ordnern, zuerst im aktuellen Ordner |
| ungültig (z. B. Nummer > N) | Meldung in der Statuszeile, Bild bleibt; Esc stellt die Anzeige wieder her |

**Referenzen hinzuladen …** (fünfte Leiste): Eine oder mehrere Referenzdateien (Mehrfachauswahl) werden zu den
vorhandenen Flächen **hinzugefügt**, statt sie zu ersetzen („Referenzen laden …“ ersetzt weiterhin). Die Flächen werden
neu nummeriert; exakt gleiche Flächen (Ordner, Aufnahme, Klasse, Umriss) werden übersprungen und gemeldet. Danach gilt
die Sammlung als „ungespeichert“ und sollte mit „Referenzen speichern …“ (z. B. als neue Datei) gesichert werden.
Damit können Referenzen je Bestand getrennt angelegt und für die Schwellenableitung zusammengeführt werden.
Eingezeichnete Flächen bleiben beim Bild- und Ordnerwechsel erhalten (gespeichert mit Ordner und Aufnahme).

Tests (Kopie, zwei Ordner A/B mit 3 + 2 Aufnahmen): Sprung per Nummer und Name auch über die Ordnergrenze ✓, IMG_18 im
aktuellen Ordner bevorzugt ✓, ungültige Eingaben abgewiesen ✓, Blättern danach normal ✓. Referenzdatei des Nutzers
(Kopie) in zwei Teile geteilt: Teil 1 laden, dann Teil 2 + Teil 1 hinzuladen → 9 Flächen (5 vital / 4 geschädigt),
Nummern 1–9, Teil 1 als doppelt übersprungen, AUC NDVI identisch mit der Originaldatei (0,7878) ✓.

## 5j. Ergänzung Version 0.9 (2026-11-01): Schwellen an Prüfbäumen prüfen

**Zweck:** Schwellen, die aus Referenzbäumen abgeleitet wurden, an **anderen** Bäumen kontrollieren, damit Ableitung und
Prüfung nicht auf denselben Daten beruhen (Zirkularität, vgl. 5h).

**Vorgehen:**
1. Referenzbäume in zwei Dateien anlegen, z. B. `Referenzbaeume_0026_Ableitung.joblib` und
   `Referenzbaeume_0026_Pruefung.joblib` (Empfehlung je Set: ≈ 10 + 10 zur Ableitung, ≈ 5 + 5 zur Prüfung).
2. Ableitungsdatei laden → „Schwellen aus Referenzen …“ → Schwellen übernehmen (gewünschte Indizes).
3. Maske wie in der späteren Auswertung einstellen (Baummaske, ggf. „verfeinern“), Kronenabstand und „Baum gestresst ab“.
4. **„Schwellen an Prüfbäumen prüfen …“** (fünfte Leiste) → Prüfdatei(en) wählen (Mehrfachauswahl möglich).

**Umsetzung (`pruefe_schwellen` in `vi_kern.py`):**
- Geprüft werden **alle Indizes, für die Schwellen festgelegt sind** (nicht nur der angezeigte).
- Jede Aufnahme mit Prüfflächen wird einmal geladen; Maske, Kronentrennung und Baumregel wie in der Auswertung.
- Je Prüffläche wird der Baum (Objekt) mit der **größten Überdeckung** bewertet. Soll: Referenz „vital“ → Baum „vital“,
  Referenz „geschädigt“ → Baum „gestresst“. Ergebnis „richtig“, „falsch“, „Übergang“ (zählt nicht als richtig) oder
  „kein Baum“ (Fläche liegt nicht in der Maske).
- Kennzahlen je Index: richtig/Übergang/falsch je Gruppe, Trefferquote, **ausgewogene Trefferquote** (Mittel der Quoten
  beider Gruppen; robust bei ungleich vielen vitalen und geschädigten Prüfbäumen).
- **Zirkularitätswarnung:** Überschneidet sich eine Prüffläche im selben Bild mit einer der aktuell geladenen
  (Ableitungs-)Referenzen, warnt die Software vor dem Start und im Ergebnis. Derselbe Baum in einem anderen,
  überlappenden Bild wird **nicht** erkannt – bei der Auswahl darauf achten.
- Ergebnisfenster: Zusammenfassung je Index (sortiert nach ausgewogener Trefferquote) und Tabelle je Prüffläche
  (falsch rot, Übergang orange). Doppelklick bzw. „Ausgewähltes Bild öffnen“ springt zu der Aufnahme und stellt den Index ein.
- Export „Als CSV speichern …“: `Pruefung_Schwellen.csv` (je Prüffläche und Index), `…_Zusammenfassung.csv`,
  `…_Parameter.json` (Version, Prüf- und Ableitungsdatei, Maske, Schwellen mit Herkunft, Überschneidungen).
- Läuft im Hintergrund mit Fortschrittsbalken, „Abbrechen“ möglich.

**Tests** (Kopien; Referenzdatei des Nutzers je Klasse abwechselnd geteilt: Ableitung 3 vital / 2 geschädigt,
Prüfung 2 / 2; Baummaske verfeinert, Kronenabstand 100 px, Baum gestresst ab 25 %, 2-Klassen-Youden):

| Prüfung | Ergebnis |
|---|---|
| Schwellen aus Ableitung | NDVI < 0,917, ReNDVI < 0,804, VARI < 0,601 |
| Prüfbäume (unabhängig) | alle drei Indizes 4/4 richtig (vital 2/2, geschädigt 2/2); gestresste Pixel: vitale 8–23 %, geschädigte 31–53 % |
| Gegenprobe: Ableitungsdatei als Prüfdatei | Warnung „5 Prüfflächen überschneiden sich …“ erscheint ✓ |
| Nummern der Prüfflächen | wie in der Datei ✓ |
| CSV, Zusammenfassung, Protokoll | geschrieben, Werte stimmen mit dem Fenster überein ✓ |
| Bild aus der Tabelle öffnen | richtige Aufnahme (IMG_0035) und Index (VARI) ✓ |

*Die Testzahlen sind wegen der wenigen Bäume (4 Prüfbäume) nur ein Funktionsnachweis, kein Ergebnis für die Arbeit.*

## 5k. Ergänzung Version 0.9.1 (2026-11-02): Schwellen im Histogramm eintippen

**Zweck:** Schwellen auf einen genauen Wert setzen, ohne die Linie im Histogramm zu ziehen (Ziehen ist ungenau) und ohne
in die Eingabefelder der vierten Leiste zu wechseln.

**Bedienung:** In der Legende des Histogramms auf den Eintrag **„gestresst < …“** bzw. **„vital ≥ …“** klicken (der
Mauszeiger wird dort zur Hand). Direkt über dem Eintrag öffnet sich ein Eingabefeld mit dem aktuellen Wert (markiert).
Wert eintippen und **Enter** drücken; **Esc** oder Klick woanders bricht ab. Komma und Punkt werden akzeptiert.

**Umsetzung (`vi_auswertung.py`):**
- Legendeneinträge zeigen die Schwellen jetzt mit drei Nachkommastellen („… (ziehen / anklicken)“).
- Übernahme wie beim Ziehen: Eingabefelder der vierten Leiste, Klassenkarte, Klassenanteile und Baumbewertung werden
  aktualisiert; die Herkunft wird als **„manuell (im Histogramm eingegeben)“** protokolliert (ab 0.9.2: „manuell (Wert eingetippt)“).
- Prüfungen: keine Zahl, Wert außerhalb des Indexbereichs, „gestresst“ größer als „vital“ bzw. „vital“ kleiner als
  „gestresst“ → Hinweis in der Statuszeile, das Feld bleibt zur Korrektur offen. Gleicher Wert → keine Änderung (Herkunft
  bleibt erhalten).
- Wird das Histogramm neu gezeichnet (z. B. anderes Bild/Index), schließt sich ein offenes Eingabefeld.

**Test** (0026SET IMG_0018, NDVI, Start gestresst 0,80 / vital 0,90):

| Eingabe | Ergebnis |
|---|---|
| gestresst „0,75“ | gestresst < 0,750 übernommen, Herkunft „manuell (im Histogramm eingegeben)“ ✓ |
| vital „0.7“ (< gestresst) | abgelehnt mit Hinweis, Feld bleibt offen ✓ |
| vital „abc“ | abgelehnt mit Hinweis ✓ |
| vital „0.912“ | vital ≥ 0,912 übernommen, Eingabefelder 0,75 / 0,912 ✓ |
| gestresst „0.5“ + Esc | keine Änderung ✓ |
| Klick neben die Legende | kein Eingabefeld ✓ |

### Ergänzung Version 0.9.2 (2026-11-03): auch an der Farbskala eintippen

Bei eingeschalteter **Klassenkarte** stehen die Schwellen auch an der Farbskala neben dem Indexbild („gestresst < …“,
„vital ≥ …“). Diese Beschriftungen sind jetzt ebenfalls anklickbar und öffnen dasselbe Eingabefeld (gleiche Prüfungen,
gleiche Übernahme). „Übergang“ ist nicht anklickbar; bei ausgeschalteter Klassenkarte zeigt die Farbskala den
Farbverlauf ohne Schwellen und ist nicht anklickbar. Die Farbskala zeigt die Schwellen jetzt mit drei Nachkommastellen.
Herkunft im Protokoll für beide Wege: **„manuell (Wert eingetippt)“**.

Test (0026SET IMG_0018, NDVI): gestresst an der Farbskala „0,78“ ✓; vital „0.6“ abgelehnt, danach „0.905“ ✓; Esc ohne
Änderung ✓; Legende funktioniert weiter (vital „0.91“ ✓); Farbskala, Legende und Eingabefelder der Leiste zeigen
danach dieselben Werte (0,780 / 0,910) ✓; Klick auf „Übergang“ und Klassenkarte aus → kein Eingabefeld ✓.

## 5l. Ergänzung Version 0.10 (2026-11-03): Kanalzahl wählbar, Schärfen mit Panchro

**Anlass:** Die Sets 0002SET und 0003SET enthalten je Aufnahme 6 Dateien: die 5 Spektralkanäle und zusätzlich den
panchromatischen Kanal der RedEdge-P (`_6`, „Panchro“). Das Stapelskript akzeptiert nur Aufnahmen mit genau 5 Dateien;
die Kanalausrichtung fand deshalb keine Aufnahmen und brach ab. Außerdem können Sets mit nur 4 Kanälen vorkommen.

Metadaten von 0002SET\000\IMG_0100 (ausgelesen):

| Datei | Kanal | Wellenlänge / FWHM | Bildgröße | Brennweite |
|---|---|---|---|---|
| _1 … _5 | Blue, Green, Red, NIR, Red edge | 475 / 560 / 668 / 842 / 717 nm | 1456 × 1088 | 5,39 mm |
| _6 | Panchro | 634,5 nm, FWHM 463 nm (≈ 400–865 nm) | 2464 × 2056 | 10,23 mm |

Gleiche Pixelgröße auf dem Sensor, aber 1,9-fache Brennweite → Panchro-Pixel am Boden ≈ halb so breit
(≈ 0,4 statt 0,77 cm/px bei 12 m), Bildausschnitt etwas kleiner (≈ 89 % der Breite).

### Kanalzahl

- Oben links **„Kanäle:“** wählen, **bevor** ein Ordner geöffnet wird: *automatisch* (Standard), *4 Kanäle*, *5 Kanäle*
  oder *6 Kanäle (mit Panchro)*. Eine Aufnahme zählt, wenn genau die Dateien `_1 … _n` vorhanden sind. *Automatisch* nimmt
  je Ordner die häufigste Dateizahl. Unvollständige Aufnahmen werden wie bisher übersprungen.
- **Welche Datei welcher Kanal ist, wird aus den Metadaten gelesen** (`Camera:BandName`), nicht aus der Dateinummer.
  Damit funktionieren auch Sets mit 4 Kanälen, egal welcher fehlt.
- Passt die Kanalzahl nicht, nennt die Software die gefundenen Dateizahlen, z. B. „200 Aufnahme(n) mit 6 Dateien“.
- Ändert man die Einstellung bei geöffnetem Ordner, wird die Liste neu eingelesen und das aktuelle Bild neu geladen.
- Fertige Reflektanzbilder (`Reflektanz_5Kanal`) werden nur bei *automatisch* oder *5 Kanäle* verwendet.

**Fehlende Kanäle (4-Kanal-Sets):**
- Indizes, die den fehlenden Kanal brauchen, sind nicht wählbar. In Export, Ordnerauswertung und Pixelabfrage bleiben sie
  leer (ungültig, 0 Pixel). Ohne Blau entfallen z. B. BNDVI, EVI, VARI und GLI.
- Ohne Blau zeigt das linke Bild Falschfarben NIR/Rot/Grün statt Echtfarben (Titel nennt es).
- Das **Baummodell braucht alle 5 Kanäle** (Merkmale) und wird mit Hinweis abgelehnt; die Vegetationsmaske (NDVI)
  funktioniert. NIR ist Pflicht (Baumobjekte, Maskenverfeinerung).

**Ausrichtung für beliebige Kanalsätze:** Verfahren unverändert (Gradienten-ECC, Stichprobe in Flughöhe, Median), Plan nach
Kanalnamen: Referenz Red Edge (fehlt sie: NIR); Grün, NIR direkt; Rot direkt oder ersatzweise über Grün; Blau über Grün
(fehlt Grün: direkt). Bei allen 5 Kanälen ist das genau der Plan des Stapelskripts. `Ausrichtung.json` speichert die
Homographien jetzt je Kanalname (alte Dateien werden weiter gelesen).

### Panchro schärfen (optional, Standard aus)

Häkchen **„Panchro schärfen“** neben der Kanalwahl. Ohne Häkchen wird Panchro ignoriert (Quelle im Protokoll:
„Panchro (_6) nicht verwendet“). Mit Häkchen und vorhandenem Panchro:

1. Panchro wird wie die Spektralkanäle radiometrisch korrigiert (Vignettierung, Schwarzwert) und mit seinen eigenen
   Kameraparametern entzerrt.
2. **Ausrichtung auf die Spektralkanäle:** Startwert aus Brennweiten und Hauptpunkten (Maßstab 1,888); dann je Ordner
   eine Restausrichtung (Gradienten-ECC gegen das Mittel der Spektralkanäle, erst Verschiebung, dann affin; Median über die
   Stichprobe; gespeichert in `VI_Auswertung\Ausrichtung_Panchro.json`); dann **je Bild eine Feinausrichtung**
   (gleiches Verfahren, ausgehend vom Ordnerwert). Wird sie verworfen (Rest > 15 px oder Korrelation < 0,2), gilt der
   Ordnerwert; das steht im Protokoll.
3. **Schärfen nach SFIM** (Smoothing Filter-based Intensity Modulation, Liu 2000), ein Verhältnisverfahren wie Brovey:
   `MS_geschärft = MS_hochgerechnet · P / P_glatt`. P = Panchro auf einem Raster mit doppelter Auflösung,
   P_glatt = P auf MS-Pixelgröße gemittelt und wieder hochgerechnet. Ausgeschnitten wird der Bereich, in dem Panchro und
   alle Kanäle gültig sind (an MS-Pixelgrenzen).

**Warum dieses Verfahren:** Alle Kanäle eines Pixels werden mit demselben Faktor multipliziert. Dadurch
- bleibt der Mittelwert jedes MS-Pixels erhalten (Radiometrie),
- bleiben **NDVI, NDRE, ReNDVI, GNDVI, BNDVI und NGRDI pixelweise gleich** wie im bloß hochgerechneten MS-Bild – sie
  gewinnen also keine neue spektrale Information, nur ein feineres Raster; SAVI, EVI, EVI2, VARI und GLI ändern sich
  geringfügig (additive Konstanten bzw. Differenzen im Nenner),
- spielt die absolute Kalibrierung von Panchro keine Rolle (geht nur als Verhältnis ein).
Verfahren, die stärker „neue“ Details erzeugen, verändern die Spektralwerte; das wäre für die Indexauswertung nicht zu
begründen (Panchro ist bei 842 nm kaum noch empfindlich).

**Nutzen:** schärferes Anzeigebild, feinere Baummaske und Kronengrenzen.
**Kosten:** etwa 4-mal so viele Pixel; Laden ≈ 8–11 s statt ≈ 3,5 s je Bild (erstes Bild eines Ordners zusätzlich ≈ 60 s
für die Ordnerausrichtung).

**Pixelraster:** Geschärfte Aufnahmen haben ein anderes Pixelraster (doppelte Auflösung, anderer Ausschnitt). Deshalb:
- Trainings- und Referenzflächen speichern, ob sie im geschärften Bild eingezeichnet wurden (`geschaerft`), und werden nur
  im passenden Bild angezeigt. Die Prüfung an Prüfbäumen lädt jedes Bild in der Auflösung seiner Flächen; das
  Prüfergebnis hat die Spalte `Panchro_geschaerft`, und „Bild öffnen“ stellt das Häkchen passend ein.
- Ein Baummodell darf nur Flächen einer Auflösung enthalten (Fehlermeldung sonst). Wird ein Modell auf Aufnahmen der
  anderen Auflösung angewendet, warnt die Software: Textur- und Größenmerkmale (Fenster in Pixeln) passen dann nicht.
  **Für geschärfte Sets ein eigenes Modell trainieren.**
- Alle Pixelangaben (Kronenabstand, Mindestgröße der Objekte, Glättung) beziehen sich auf das jeweilige Raster. Für
  geschärfte Bilder z. B. den Kronenabstand verdoppeln.
- Protokolle: `kanaele`, `panchro_geschaerft` und `panchro` (Verfahren, Faktor, Ausrichtung, Ausschnitt) im
  Parameterprotokoll des Exports; `kanalzahl` und `panchro_schaerfen` in dem der Ordnerauswertung.

**Tests** (Kopien: 12 Aufnahmen aus 0002SET\000; 4-Kanal-Set simuliert aus 12 Aufnahmen von 0026SET\000 ohne Blau):

| Prüfung | Ergebnis |
|---|---|
| Kanalzahl 5 bei 6-Kanal-Set | 0 Aufnahmen, Hinweis „12 Aufnahme(n) mit 6 Dateien“ ✓ |
| automatisch / 6 | 12 Aufnahmen; Kanäle aus Metadaten _1 Blue … _5 Red edge, Panchro _6 erkannt ✓ |
| Ausrichtung 6-Kanal-Set (neu geschätzt) | Plan wie Stapelskript (Grün, NIR, Rot direkt auf Red Edge, Blau über Grün) ✓ |
| 5-Kanal-Set 0026 aus Rohbildern | max. Abweichung zum Reflektanzbild 5 · 10⁻⁵ – Verhalten unverändert ✓ |
| 4 Kanäle (ohne Blau) | Ausrichtung ohne Blau; NDVI 0,6849 (5 Kanäle: 0,6853); VARI/EVI nicht wählbar, Index wechselt automatisch auf NDVI; Falschfarben-Anzeige; Baummodell mit Hinweis abgelehnt; Ordnerauswertung ohne Fehler (VARI 0 Pixel) ✓ |
| Schärfen: Radiometrie | Mittel je Kanal MS vs. geschärft z. B. NIR 0,4299 / 0,4289; Median der Abweichung je MS-Pixelblock 2,0–2,8 % |
| Schärfen: NDVI | Mittel 0,8597 / 0,8598 ✓ |
| Schärfen: Detail | Panchro enthält ≈ 1,8–1,9 × so viel Feinstruktur wie das hochgerechnete MS-Bild (Bildvergleich) |
| Panchro-Ausrichtung | Ordner: 5 von 6 Stichproben gültig, Korrelation 0,51; je Bild verbessert sich die Kantenübereinstimmung (NCC) von 0,45–0,48 auf 0,48–0,72 ✓ |
| Oberfläche | Umschalten lädt neu; Referenz aus ungeschärftem Bild erscheint nicht im geschärften und umgekehrt; Prüfung lädt je Fläche die passende Auflösung ✓ |

Erkenntnis aus dem Test: Eine volle Homographie als Restausrichtung blieb teils im Startwert hängen (Kanten-NCC 0,41 statt
0,55) und brauchte 10–20 s je Bild; Verschiebung + affin ist robuster und braucht 2–5 s.

**Für die Arbeit:** Ob geschärft wird, muss im Methodenteil stehen (Verfahren, Faktor, Quelle). Für die Indexwerte
selbst bringt die Schärfung bei den normierten Differenzen keine zusätzliche Information; sie verbessert vor allem die
Abgrenzung der Kronen. Sets mit und ohne Schärfung nicht ungeprüft miteinander vergleichen.
*Quelle Liu (2000): Notiz `Notizen\Quellen\liu2000.md` angelegt (2026-11-03), PDF noch zu besorgen.*

## 5m. Ergänzung Version 0.10.1 (2026-11-03): Beschriftung des Baummodells

Die Bedienelemente des Baummodells heißen jetzt neutraler (Wunsch: „Training“ lässt eine KI vermuten). Verfahren und
Dateiformat sind unverändert; ältere Abschnitte dieser Dokumentation verwenden noch die alten Namen.

| bisher | jetzt |
|---|---|
| Zeichenmodus „Training: Baum“ / „Training: kein Baum“ | „Beispiel: Baum“ / „Beispiel: kein Baum“ |
| Knopf „Trainieren“ | „Modell berechnen“ |
| Trainingsfläche(n), „trainiert“ | Beispielfläche(n), „berechnet“ |

Intern (Funktionsnamen, Schlüssel `trainiert` im gespeicherten Modell) bleibt alles gleich, damit gespeicherte Modelle
weiter geladen werden.

**Hinweis für die Arbeit:** Fachlich bleibt es eine **überwachte Klassifikation mit Random Forest** (Breiman 2001), also
ein Verfahren des maschinellen Lernens. In der Fernerkundung heißen die eingezeichneten Flächen üblicherweise
„Trainingsgebiete“. Die neue Beschriftung betrifft nur die Oberfläche; im Methodenteil sollte das Verfahren mit seinem
Namen beschrieben werden.

## 5n. Ergänzung Version 0.11 (2026-11-03): Darkmode

- Schalter **„Darkmode“** rechts in der Statuszeile (unten). Die Wahl wird in `VI_Auswertung_Einstellungen.json`
  (Softwareordner) gespeichert und beim nächsten Start übernommen.
- Umgefärbt werden: alle Bedienelemente (im Darkmode ttk-Thema „clam“, da sich „vista“ nicht umfärben lässt; beim
  Zurückschalten wieder das Windows-Thema), Tabellen, Aufklapplisten, Pixelabfrage, Nebenfenster (Schwellen aus
  Referenzen, Prüfung), Werkzeugleiste der Abbildung (Symbole hell) sowie Abbildung, Achsen, Beschriftungen, Legende und
  Farbskala. Hinweistexte nutzen einen eigenen Stil (`Hinweis.TLabel`) statt fester Grautöne. Farben für „falsch“,
  „Übergang“ und „kein Baum“ in der Prüftabelle sind im Darkmode heller.
- Bildinhalte (RGB, Indexkarte, Klassenfarben) bleiben unverändert.
- **Export:** Die Ansicht (`…_Ansicht.png`) wird immer im hellen Thema gespeichert und danach wieder dunkel angezeigt
  (für Abbildungen in der Arbeit).

Test: Umschalten hell → dunkel → hell mit geladener Aufnahme (0026SET IMG_0000, Schwellen an), Screenshots beider
Zustände geprüft; Figurfarbe dunkel / beim Export / danach: #1e1f22 / weiß / #1e1f22 ✓; nach dem Zurückschalten wieder
Thema „vista“ ✓.

## 5o. Ergänzung Version 0.12 (2026-11-06): Kanalanalyse an den Referenzbäumen

### Anlass

Anmerkungen von Max (06.11.2026, Notiz `Notizen\Dokumentation\Anmerkungen Max 2026-11-06.md`):

1. Welche Kanäle bzw. Indizes zeigen die größten Unterschiede **zwischen** den Bäumen bei wenig Streuung **innerhalb**
   eines Baums? Diese sind am aussagekräftigsten.
2. Welche Kanäle zeigen dasselbe? Über Korrelation bzw. PCA begründen, welche man weglassen kann
   (nur RGB / RGB+NIR / alle).
3. Kein neuronales Netz nötig; Statistik, PCA oder k-means reichen.

### Getroffene Entscheidungen

| Frage | Entscheidung | Begründung |
|---|---|---|
| Datengrundlage | die geladenen **Referenzbäume** (vital/geschädigt) | Für die Trennung braucht es Bäume mit bekannter Klasse; je Referenzfläche = ein Baum |
| Kanalwerte | Referenzflächen speichern ab 0.12 zusätzlich die **Reflektanz je Kanal** (`kanaele`); ältere Dateien werden über `ergaenze_kanalwerte` aus den Bildern ergänzt (Umriss ∩ Maske, Stichprobe 5000 px, Zufallszahl = Flächennummer) | Indizes allein reichen für Korrelation/PCA der Kanäle nicht. Die ursprüngliche Pixelauswahl ist in alten Dateien nicht gespeichert, deshalb neue Stichprobe aus demselben Umriss |
| Indizes | aus **denselben** Pixeln wie die Kanäle berechnet (gemeinsam gültige Pixel) | Kanäle und Indizes sind so direkt vergleichbar |
| Gewichtung | je Baum gleich viele Pixel (`ANALYSE_PIXEL_JE_BAUM = 2000`) | Große Kronen sollen nicht überwiegen |
| Trennmaß zwischen/innerhalb | einfaktorielle Varianzanalyse mit dem Baum als Faktor: F, ICC(1); zusätzlich Klassenabstand in Einheiten der Streuung innerhalb der Bäume | entspricht Anmerkung 1; ICC ist unabhängig von der Pixelzahl |
| Test vital/geschädigt | auf **Baumebene** (Mittelwert je Baum): Cohens d, AUC, Welch-Test | Pixel eines Baums sind nicht unabhängig (räumliche Autokorrelation); Pixel-p-Werte wären viel zu optimistisch |
| Gruppen | „alle“ und **je Set** getrennt | Sonnenstand und DLS-Kalibrierung nur innerhalb eines Flugs vergleichbar (Anmerkungen 6 und 8) |
| Kanalsätze | RGB, RGB+NIR, alle 5 (`KANALSAETZE`) | Vorgabe aus Anmerkung 2 |
| Klassifikation | lineare Diskriminanzanalyse (LDA) mit Leave-one-tree-out und k-means (k = 2) auf den Baummitteln | Anmerkung 3: einfache Verfahren statt neuronalem Netz |

### Formeln

Für ein Merkmal (Kanal oder Index) mit k Bäumen, n_i Pixeln je Baum, Baummittel m_i und Gesamtmittel M:

- MS_zwischen = Σ n_i (m_i − M)² / (k − 1), MS_innerhalb = Σ_i Σ_j (x_ij − m_i)² / (N − k)
- F = MS_zwischen / MS_innerhalb
- n0 = (N − Σ n_i² / N) / (k − 1), **ICC(1) = (MS_zwischen − MS_innerhalb) / (MS_zwischen + (n0 − 1) · MS_innerhalb)**
  (Anteil der Gesamtvarianz, der auf Unterschiede zwischen den Bäumen entfällt)
- Std innerhalb = √MS_innerhalb; Verhältnis = Std der Baummittel / Std innerhalb
- **Abstand** = |Mittel(m_i vital) − Mittel(m_i geschädigt)| / Std innerhalb
- Cohens d auf Baumebene = Differenz der Klassenmittel der Baummittel / gepoolte Std der Baummittel
- AUC auf Baumebene = P(Baummittel vital > Baummittel geschädigt)
- Kanalsätze: R² der linearen Regression eines weggelassenen Kanals auf die Kanäle des Satzes;
  „erklärte Varianz“ = Mittel der R² über alle 5 Kanäle (enthaltene Kanäle = 1)
- PCA auf der Korrelationsmatrix (standardisierte Kanäle); Ladung = Eigenvektor · √Eigenwert

### Bedienung

Zeile „Referenzbäume“ → **„Kanalanalyse …“**. Fehlen Kanalwerte (ältere Datei), fragt die Software nach und ergänzt
sie mit der aktuell gewählten Maske (dieselbe wie beim Einzeichnen wählen, meist „Bäume (Modell)“). Danach
„Referenzen speichern …“, damit das Ergänzen nicht wiederholt werden muss. Das Fenster hat vier Reiter (Trennung,
Korrelation, PCA, Kanalsätze) und eine Auswahl der Gruppe („alle“ oder ein Set). „Als CSV speichern …“ schreibt
`<Name>_Trennung.csv`, `_Korrelation.csv`, `_PCA.csv`, `_Kanalsaetze.csv` und `_Parameter.json`.

### Ergebnis des ersten Laufs (06.11.2026)

Daten: Kopien von `Referenzbaeume_0026_Ableitung.joblib` (6 vital, 4 geschädigt) und
`Referenzbaeume_0028_Ableitung.joblib` (10/10), zusammen 30 Bäume aus 6 Bildern, beide Flüge am 10.07.2026
(Sonnenhöhe ≈ 58,6°). Kanalwerte nachträglich ergänzt mit `Baummodell.joblib`, Maske verfeinert (Lückenanteil
Standard); Laufzeit 19 s. Ausgaben im Scratchpad-Ordner (`kanaltest\`), Originaldateien unverändert.

**Trennung vital/geschädigt (alle 30 Bäume), sortiert nach Abstand:**

| Merkmal | Abstand (Std innen) | Cohens d | AUC Baum | p (Welch) | ICC |
|---|---|---|---|---|---|
| VARI | 1,46 | 4,86 | 1,000 | 2·10⁻⁹ | 0,39 |
| NDVI | 1,41 | 4,87 | 1,000 | 6·10⁻¹⁰ | 0,37 |
| NGRDI | 1,39 | 4,57 | 1,000 | 3·10⁻⁹ | 0,37 |
| ReNDVI | 1,35 | 4,22 | 1,000 | 5·10⁻⁹ | 0,36 |
| GLI | 1,17 | 3,81 | 1,000 | 1·10⁻⁸ | 0,31 |
| Rot (Kanal) | 1,13 | −1,93 | 0,040 | 1·10⁻⁴ | 0,40 |
| NDRE | 1,01 | 2,25 | 0,938 | 2·10⁻⁶ | 0,31 |
| Red Edge (Kanal) | 0,60 | −0,59 | 0,299 | 0,13 | 0,52 |
| BNDVI | 0,50 | 1,53 | 0,844 | 2·10⁻⁴ | 0,14 |
| GNDVI | 0,39 | 0,97 | 0,746 | 0,013 | 0,17 |
| NIR (Kanal) | 0,09 | −0,06 | 0,509 | 0,87 | 0,67 |

Je Set: in 0026SET und 0028SET dieselbe Spitzengruppe (VARI, NGRDI, NDVI, ReNDVI; d = 3,1 bis 6,4), NDRE jeweils
schwächer (d = 1,4 bzw. 2,7).

**Korrelation der Kanäle (alle):** Pixel: Grün–Red Edge 0,94, Red Edge–NIR 0,92, Grün–NIR 0,85, Rot mit den anderen
nur 0,50–0,67. Baummittel: Blau, Grün und Red Edge 0,96–0,99 untereinander.

**PCA (alle, Pixel):** PC1 80,6 % (alle Kanäle positiv = Helligkeit), PC2 12,0 % (vor allem Rot, Ladung 0,67),
PC1 + PC2 = 92,6 %. Baummittel: PC1 90,4 %, PC2 8,1 %.

**Kanalsätze (alle):**

| Kanalsatz | Erkl. Varianz Pixel | R² NIR (Pixel) | R² Red Edge (Pixel) | LDA Treffer Baum | k-means Baum |
|---|---|---|---|---|---|
| RGB | 0,934 | 0,738 | 0,931 | 0,63 | 0,60 |
| RGB+NIR | 0,993 | – | 0,966 | 0,83 | 0,60 |
| alle 5 | 1,000 | – | – | 0,90 | 0,60 |

### Einordnung (vorläufig)

- **ICC allein ist nicht das richtige Kriterium für die Vitalität:** Den höchsten ICC haben NIR und NIR-lastige Indizes
  (EVI, EVI2, SAVI; ICC ≈ 0,67), die vital und geschädigt aber gar nicht trennen. Die Bäume unterscheiden sich im NIR
  stark (Helligkeit, Kronenstruktur, Beleuchtung), nur eben nicht nach Vitalität. Für Anmerkung 1 ist deshalb der
  **Abstand** (Klassenunterschied relativ zur Streuung im Baum) maßgeblich; der ICC beschreibt nur, wie
  baumspezifisch ein Merkmal ist.
- **Rot trägt die Trennung:** Alle Spitzenindizes enthalten den Rotkanal, Rot allein trennt bereits deutlich
  (d = −1,9). Die geschädigten Referenzbäume sind vermutlich sichtbar verfärbt (fortgeschrittener Schaden).
- **Hypothese aus Anmerkung 9 hier nicht bestätigt:** NDVI trennt besser als NDRE (d 4,9 gegen 2,3). Eine Sättigung des
  NDVI zeigt sich bei diesen Bäumen nicht. Für frühe Schäden (noch grüne Bäume) kann das anders sein.
- **Kanäle zeigen weitgehend dasselbe:** Red Edge ist aus RGB+NIR zu 96,6 % (Pixel) bzw. 99,6 % (Baum) linear
  vorhersagbar, NIR aus RGB nur zu 73,8 %. Der NIR trägt also eigene Information, der Red Edge kaum zusätzliche
  lineare Information. Für die Klassifikation hilft der Red Edge trotzdem etwas (LDA 0,83 → 0,90).
- **k-means auf den Kanalmitteln findet die Vitalität nicht** (60 % in allen Sätzen): Die Cluster folgen der
  Helligkeit (PC1). Unüberwachte Verfahren bräuchten normierte Merkmale (Indizes) statt Reflektanzen.
- **Einschränkungen:** 30 Bäume aus einem Flugtag; Referenzbäume als „sicher erkennbar“ ausgewählt (eher deutliche
  Schäden); Kanalwerte nachträglich mit neuer Pixelstichprobe ergänzt; LDA-Trefferquote bei 30 Bäumen mit großer
  Unsicherheit (ein Baum = 3,3 Prozentpunkte).

## 5p. Ergänzung Version 0.13 (2026-11-06): Kronentrennung über das Pflanzraster, Korrektur von Hand

### Anlass

Hauptproblem der Maske laut Nutzer (06.11.2026): **zusammengewachsene Nachbarbäume**. Die bisherige Trennung
(Wasserscheide auf Maskenform + NIR, Mindestabstand der Kronenmitten) braucht eine Einschnürung oder eine dunkle
Schattenlinie zwischen den Kronen; wo sich Kronen breit und ohne Schatten berühren, bleiben sie ein Objekt oder werden
an falscher Stelle getrennt. Testbilder laut Nutzer: 0026SET, IMG_0018 und IMG_0020 (Kopien im Scratchpad).

### Getroffene Entscheidungen

| Frage | Entscheidung | Begründung |
|---|---|---|
| Vorwissen | **Pflanzraster** der Kultur nutzen (Schalter „Pflanzraster“, Standard aus) | Weihnachtsbäume stehen in Reihen mit festem Abstand; das Raster legt fest, wo Kronenmitten zu erwarten sind |
| Schätzung des Rasters | je Bild aus der Autokorrelation der geglätteten NIR-Helligkeit **innerhalb der Maske** | Erster Versuch mit der Maskenform fand nur ein grobes 200-px-Quadratraster und übersah den versetzten Verband; die Helligkeit bildet die Lage der Kronenmitten ab |
| Bäume abseits des Rasters | zusätzliche Kronenmitte an deutlichen Helligkeitsmaxima mit ≥ 0,5 · Rasterabstand zu allen Rastermitten | in IMG_0018 stand ein Baum außerhalb des Rasters und wurde sonst mit dem Nachbarn verbunden (Test mit 0,6: nicht erkannt) |
| Lücken im Raster | keine Kronenmitte, wenn im Umkreis (¼ Rasterabstand) weniger als 30 % Maske liegt | fehlende Bäume sollen den Nachbarn nicht teilen |
| Kein Raster erkennbar | bisheriges Verfahren mit „Kronen trennen, Abstand“ | sicherer Rückfall, z. B. bei unregelmäßigen Beständen |
| Korrektur von Hand | Zeichenmodi **„Krone teilen“** (Klick = zusätzliche Kronenmitte) und **„Kronen verbinden“** (zwei Klicks), Knopf „↶ Kronenkorrektur“ | automatische Trennung bleibt fehlerbehaftet; Korrekturen sind für Prüfbäume und Beispielbilder sinnvoll |
| Speicherung | `<Aufnahmeordner>\VI_Auswertung\Kronenkorrekturen.json`, je Aufnahme (geschärfte Bilder getrennt) | Korrekturen gelten dann auch in Ordnerauswertung, Export und Prüfung an Prüfbäumen; Punkte in Bildkoordinaten, daher unabhängig von Maskeneinstellungen |
| Höhenmodell (WebODM) | nicht verwendet | Auswertung auf Einzelaufnahmen; Übertragung des Oberflächenmodells auf jedes Bild zu aufwendig |

### Verfahren (`schaetze_pflanzraster`, `_raster_saatpunkte`, `objekt_labels` in `vi_kern.py`)

1. NIR auf halbe Auflösung verkleinern, glätten (σ = 12 px volle Auflösung), nur innerhalb der Maske, Mittelwert der
   Maske abziehen.
2. Autokorrelation über FFT, durch die Überlappungsfläche je Verschiebung geteilt, auf 1 bei Verschiebung 0 normiert.
3. Lokale Maxima > 0,08 mit ≥ 50 px Abstand; kürzester Vektor = a, nächster nicht kollinearer (Winkel > 35°) = b
   (b ≤ 2 · |a|). Sonst: kein Raster.
4. Phase: Rasterpunkte P = o + i·a + j·b; o in der Einheitszelle (Schritt ≈ 4 px) so gewählt, dass der Mittelwert der
   geglätteten „Kronenhöhe“ an den Rasterpunkten maximal ist (Kronenhöhe wie bisher: 0,5 · Randabstand + 0,5 · NIR).
5. Jeder Rasterpunkt wandert zum Maximum der Kronenhöhe im Umkreis 0,3 · Rasterabstand (innerhalb der Maske);
   Punkte näher als 0,5 · Rasterabstand werden zusammengefasst.
6. Zusätzliche Mitten abseits des Rasters (s. o.), Mitten für Maskenflächen ohne Mitte, Mitten aus „Krone teilen“.
7. Wasserscheide auf der Kronenhöhe; danach „Kronen verbinden“ (Label des zweiten Punkts → Label des ersten).

### Ergebnis an den Testbildern (0026SET, Maske `Baummodell.joblib`, verfeinert)

| Bild | Raster a / b (dy, dx in px) | Abstand | Kronenmitten | Objekte ≥ 1500 px (bisher, 100 px + NIR) | Rechenzeit |
|---|---|---|---|---|---|
| IMG_0018 | (96, −118) / (104, 116) | 152 / 156 px | 48 (1 abseits des Rasters) | 46 (44) | 0,7 s |
| IMG_0020 | (102, 112) / (100, −116) | 151 / 153 px | 47 | 44 (43) | 0,6 s |

Rasterabstand 152 px ≈ 1,17 m bei 0,77 cm/px; Reihenabstand (Periode in Bildhöhe) ≈ 200 px ≈ 1,5 m, versetzter
Verband. Die Kronenmitten liegen in der Sichtprüfung fast alle auf den Kronenmitten (Bild `IMG_0018_saat.png` im
Scratchpad). Die Objektgrenzen sind kompakter als bisher, einzelne große Kronen bleiben aber verbunden oder geteilt
(z. B. IMG_0020 oben links) – dafür ist die Korrektur von Hand gedacht. Die Objektzahl allein ist kein Gütemaß.

Oberflächentest (Kopie von IMG_0018): Pflanzraster erkannt (Anzeige „Pflanzraster 152/156 px“), Teilen 46 → 47,
Verbinden 47 → 46, Korrekturen nach Neuladen erhalten, Rückgängig wirksam.

Oberfläche: Die Knöpfe zum Baummodell stehen seit 0.13 in einer eigenen Zeile „Baummodell:“ unter der Zeichenleiste (sonst bei normaler Fensterbreite abgeschnitten); „Kanalanalyse …“ steht direkt nach „Schwellen aus Referenzen …“.

### Hinweise für die Arbeit

- Der Rasterabstand ist ein Messwert je Bild und kann in 4.2 (Bestand: Pflanzverband) und 4.3.3 (Kronentrennung)
  genannt werden.
- Wie viele Korrekturen von Hand nötig waren, sollte je ausgewertetem Set festgehalten werden (Anzahl in der
  JSON-Datei), damit die Güte der automatischen Trennung beschrieben werden kann.
- Pixelangaben gelten für ungeschärfte Bilder; in geschärften Bildern verdoppeln sich Abstände (das Raster wird je Bild
  neu geschätzt und passt sich an).

## 5q. Ergänzung Version 0.14 (2026-11-06): Panchro nur für Maske und Kronen

### Anlass

Anmerkung 4 von Max (06.11.2026): Den panchromatischen Kanal für die höhere Auflösung nutzen (Kronen abgrenzen,
Pansharpening), die Indizes aber auf den Original-Kanälen rechnen, weil Pansharpening die Spektralwerte verfälschen
kann.

### Getroffene Entscheidungen

| Frage | Entscheidung | Begründung |
|---|---|---|
| Was nutzt das geschärfte Bild? | Baummaske (Random Forest, Verfeinerung), Vegetationsmaske, Kronentrennung (NIR-Helligkeit, Pflanzraster) und RGB-Anzeige | Hier hilft die feinere Auflösung: schärfere Kronengrenzen, kleinere Lücken erkennbar |
| Woraus werden Indizes und Statistik berechnet? | aus den **Original-Spektralkanälen**, auf das feine Raster übertragen (jedes MS-Pixel = 2 × 2 feine Pixel, Werte unverändert) | Anmerkung 4; die Werte je Pixel bleiben exakt die gemessenen Reflektanzen |
| Raster der Auswertung | feines Raster (Faktor 2), damit Maske und Werte deckungsgleich sind | Ein Baumobjekt umfasst so genau die MS-Pixel(-anteile) innerhalb der feinen Kronengrenze |
| Bedienung | neues Häkchen **„nur Kronen“** neben „Panchro schärfen“ (Standard: an) | ohne Häkchen: bisheriges Verhalten (alles aus den SFIM-geschärften Kanälen) |
| Referenzflächen, Prüfung | Einstellung wird je Fläche gespeichert (`panchro_nur_kronen`) und beim Neuladen verwendet | Prüfung und Kanalanalyse rechnen mit denselben Werten wie beim Einzeichnen |
| Baummodell | weiterhin ein eigenes Modell für geschärfte Bilder nötig (Merkmale aus dem geschärften Bild) | Merkmalsfenster und Textur hängen von der Pixelgröße ab |

Umsetzung: `Aufnahme.maskenstapel` (geschärft) und `Aufnahme.kronenstapel` (Maske/Kronen/Anzeige) in `vi_kern.py`;
`Aufnahme.stapel` enthält bei „nur Kronen“ die Original-Kanäle im feinen Raster.

### Test (Kopie von 0002SET\000\IMG_0100, 6 Kanäle, vorhandene Panchro-Ausrichtung)

- Raster: MS 1066 × 1438 px → fein 2092 × 2594 px (Ausschnitt mit gültigem Panchro).
- **„nur Kronen“:** Spektralwerte im feinen Raster stimmen exakt mit den MS-Werten überein (jeder 2 × 2-Block = ein
  MS-Pixel), geprüft für alle 5 Kanäle.
- **Zum Vergleich SFIM (alle Werte geschärft):** Abweichung der Reflektanz je feinem Pixel gegenüber dem Original
  Median 3,5–4,6 %, P95 11,5–14,7 % (je nach Kanal). Indizes: mittlere Abweichung NDVI 0,005 (P95 0,016),
  NDRE 0,009 (0,023), SAVI 0,015 (0,038), EVI 0,021 (0,055). Normierte Differenzen ändern sich wenig, Indizes mit
  Konstanten (SAVI, EVI) und die Kanalwerte selbst deutlich.
- Kronentrennung im geschärften Bild: Pflanzraster 350/351 px (≈ 175 px im MS-Raster).
- Die Vegetationsmaske (NDVI ≥ 0,4) erfasst im Oktober in Fläche A fast das ganze Bild (99,5 %, Gras ist grün) –
  für 0002/0003 ist ein Baummodell für geschärfte Bilder nötig.
- Oberfläche: Titel „(Panchro: nur Kronen)“, Hinweis „Indizes aus den Original-Kanälen, Panchro nur für Maske/Kronen“,
  Indexbild im feinen Raster.

## 5r. Ergänzung Version 0.14.1 (2026-11-06): Baumnummern in Leserichtung

Anlass: Hinweis des Nutzers, die Nummerierung wirke willkürlich. Bisher folgten die Nummern der Reihenfolge, in der die
Kronenmitten gefunden wurden (mit Pflanzraster: nach Stärke der Kronenmitte sortiert, danach Bäume abseits des
Rasters und Klicks aus „Krone teilen“), also nicht der Lage im Bild.

Neu (`_nummerieren` in `vi_kern.py`): Nummern zeilenweise von oben nach unten, in jeder Zeile von links nach rechts.
Eine Zeile umfasst alle Bäume, deren Mitte weniger als einen halben Kronendurchmesser (Median der Bäume im Bild, aus
der Fläche berechnet) unter der Mitte des obersten Baums der Zeile liegt. Die Nummer hängt damit nur von der Lage ab.

Folgen: Baumnummern in Exporten und Prüfergebnissen ab 0.14.1 weichen von älteren Ausgaben ab. Kronenkorrekturen
(Punkte) und Referenzflächen (Umrisse) sind nicht betroffen. Bei versetztem Pflanzverband wechseln die Zeilen leicht
versetzt – die Nummern laufen dann im Zickzack durch die Doppelreihe. Test IMG_0018 (0026SET-Kopie): 46 Bäume, Nummern
in der Sichtprüfung zeilenweise lesbar.

## 5s. Ergänzung Version 0.15 (2026-11-06): Arbeitsstand merken, „Alles zurücksetzen …“

Wunsch des Nutzers: Nach dem Schließen dort weiterarbeiten, wo man aufgehört hat, und alles auf Knopfdruck leeren.

| Frage | Entscheidung |
|---|---|
| Wann gespeichert? | beim Schließen des Fensters (Fenster-X); läuft noch eine Auswertung, fragt die Software vorher |
| Was? | Ordner und angezeigte Aufnahme, Kanalzahl, Panchro-Einstellungen, Index, Farbskala, Maske (Art, Schwelle, Verfeinerung, Lückenanteil), Export-Häkchen, Schwellwerte je Index (inkl. Kronentrennung, Pflanzraster) und welche eingeschaltet sind, Anzeigeoptionen |
| Baummodell, Referenzflächen | als Sicherungskopie (`Baummodell_Sitzung.joblib`, `Referenzen_Sitzung.joblib`) – so bleiben auch ungespeicherte Beispiel- und Referenzflächen erhalten; der Name der zuletzt geladenen/gespeicherten Datei wird weiter angezeigt |
| Wo? | Ordner `Sitzung\` neben dem Programm (`Sitzung.json` + Sicherungskopien) |
| Nicht gespeichert | Zoom, ROIs, Zeichenmodus, offene Nebenfenster |
| Kronenkorrekturen | unverändert je Aufnahmeordner in `VI_Auswertung\Kronenkorrekturen.json` (schon immer dauerhaft) |
| Start | Arbeitsstand wird automatisch wiederhergestellt; Statuszeile „Sitzung vom … wiederhergestellt (Ordner, Aufnahme)“; fehlende Ordner/Dateien werden gemeldet |
| „Alles zurücksetzen …“ (unten rechts) | nach Rückfrage: löscht nur den gemerkten Arbeitsstand (Ordner `Sitzung\`) und baut die Oberfläche im Ausgangszustand neu auf. Erhalten bleiben selbst gespeicherte Modell-/Referenzdateien, Exporte, Kronenkorrekturen und der Darkmode |

Test (Sitzungsordner im Scratchpad, Kopie von 0026SET): Arbeitsstand mit IMG_0020, NDRE, Maske „Bäume (Modell)“
verfeinert, Pflanzraster, Schwellen NDRE, Baummodell und 10 Referenzflächen gespeichert; nach Neustart alles
wiederhergestellt; nach „Alles zurücksetzen“ Sitzungsordner leer, nächster Start im Ausgangszustand.

## 5t. Ergänzung Version 0.16 (2026-11-06): Baumregel „Median je Baum“

Anlass: Vergleich der Baumregeln für das 2-Klassen-Schema (Empfehlung in 4.3.3). Bisher wurde ein Baum „gestresst“,
wenn mindestens x % seiner Pixel gestresst sind (x frei festgelegt, bisher 25 %).

| Frage | Entscheidung |
|---|---|
| Neue Regel | **Median je Baum**: gestresst, wenn Median der Indexwerte des Baums < Schwelle „gestresst“; vital, wenn Median ≥ Schwelle „vital“; sonst Übergang (im 2-Klassen-Schema beide gleich → kein Übergang) |
| Bedienung | Auswahl „Baumregel“ in der Schwellwert-Zeile (ersetzt die Beschriftung „% gestresste Pixel = Baum gestresst“); „Baum gestresst ab“ gilt nur für die Anteilsregel |
| Speicherung | Feld `baumregel` in `Schwellen` (Standard „anteil“ – bisherige Ergebnisse unverändert), im Parameterprotokoll, in der Sitzung und in der Prüfung (Spalte „Baumregel“) |

### Test: Prüfung an 0028SET (Ableitung 10 vital + 10 geschädigt, Prüfung 5 + 5, keine Überschneidung)

Maske `Baummodell.joblib` verfeinert, Pflanzraster an, 2-Klassen-Schema, Schwelle = Youden der Referenzpixel.
Ergebnis je Index als „vital richtig + geschädigt richtig“ (je von 5):

| Index | Anteil ≥ 25 % | Median je Baum | Median, Schwelle aus Baummedianen der Ableitungsbäume |
|---|---|---|---|
| NDVI (0,931) | 1 + 5 | 3 + 5 | 3 + 5 (Schwelle 0,931) |
| ReNDVI (0,820) | 1 + 5 | 3 + 5 | 3 + 5 (0,810) |
| VARI (0,588) | 3 + 5 | 5 + 3 | **5 + 4** (0,642) |
| NDRE (0,422) | 4 + 4 | 5 + 1 | 5 + 2 (0,425) |
| GNDVI (0,755) | 1 + 5 | 5 + 1 | 1 + 5 (0,782) |

Ohne Pflanzraster ähnlich (NDVI Median 3 + 4, VARI 5 + 4 mit Baumschwelle).

Befund:
- Die **Anteilsregel mit 25 %** ist zu streng: vitale Prüfbäume werden überwiegend als gestresst eingestuft
  (NDVI 1 von 5). Die Median-Regel trifft die vitalen Bäume deutlich besser, bei NDVI/ReNDVI ohne Verlust bei den
  geschädigten. Insgesamt ist sie gleich gut oder besser (bestes Ergebnis VARI 9 von 10).
- Die **Ableitungsbäume** trennen sich auf Baumebene vollständig (Youden J = 1,00 für NDVI, ReNDVI, VARI); die
  Prüfbäume folgen dem nicht ganz (NDVI: 2 vitale Prüfbäume unter der Schwelle). Ursache ist also nicht die Art der
  Schwellenableitung, sondern die Streuung zwischen Bäumen bei sehr kleiner Stichprobe (1 Prüfbaum = 10 %-Punkte).
- Folgerung: Für eine belastbare Wahl von Regel und Index mehr Referenzbäume je Set (Ableitung ≥ 10 + 10, Prüfung
  ≥ 8 + 8) aus mehreren Bildern. Die Schwelle für die Median-Regel aus Baummedianen abzuleiten (gleiche Einheit wie
  in der Anwendung) ist methodisch stimmiger; in der Software bisher nur im Test (Skript), nicht als Funktion.

## 5u. Ergänzung Version 0.17 (2026-11-06): Schwellen aus Baummedianen

Anlass: Für die Baumregel „Median je Baum“ (5t) sollte die Schwelle auf derselben Einheit abgeleitet werden, auf der
sie angewendet wird – den Baummedianen – und nicht aus den Pixeln innerhalb der gezeichneten Umrisse (dort fehlen
Kronenrand und Schatten, die das Baumobjekt in der Auswertung enthält). Vor dem Einbau geprüft: Die Funktion gab es
noch nicht (nur im Testskript zu 5t).

| Frage | Entscheidung |
|---|---|
| Zuordnung Fläche → Baum | wie bei der Prüfung an Prüfbäumen: Baumobjekt mit der größten Überdeckung, gleiche Maske, Kronentrennung (inkl. Pflanzraster) und Kronenkorrekturen wie in der Auswertung (`pruefe_schwellen` wiederverwendet) |
| Schwelle | Youden auf Baumebene: vital, wenn Median ≥ t; Kandidaten = Mitten zwischen benachbarten sortierten Baummedianen (`_youden_baum`) |
| Ergebnis | 2 Klassen (gestresst = vital = t), Baumregel „median“, Herkunft mit Zahl der Bäume, J, AUC und Maske |
| Bedienung | im Fenster „Schwellen aus Referenzen …“ Knopf **„Baumebene: Schwellen aus Baummedianen …“**; läuft im Hintergrund (lädt jedes Bild einmal), Ergebnisfenster mit Übernehmen (ausgewählt/alle) und CSV + Parameterprotokoll |
| Unabhängigkeit | Hinweis im Startdialog: nur Ableitungsbäume laden; Kontrolle danach mit „Schwellen an Prüfbäumen prüfen …“ |

Ausgabe `Schwellen_Baummediane.csv`: Index, Bäume vital/geschädigt, kein Baum, Schwelle, Youden J, Sensitivität,
Spezifität, AUC Baum, Spannweiten der Baummediane je Klasse, Pixel-Schwelle zum Vergleich.

### Test (0028SET, Ableitung 10 + 10, Prüfung 5 + 5; Maske verfeinert, Pflanzraster an; Laufzeit 37 s)

| Index | Schwelle (Baum) | J | AUC Baum | Baummediane vital | geschädigt | Prüfung vital + geschädigt |
|---|---|---|---|---|---|---|
| NGRDI | 0,550 | 1,00 | 1,00 | 0,557–0,628 | 0,311–0,542 | **5/5 + 5/5** |
| VARI | 0,642 | 1,00 | 1,00 | 0,665–0,715 | 0,364–0,619 | 5/5 + 4/5 |
| GLI | 0,594 | 0,90 | 0,98 | 0,601–0,689 | 0,455–0,627 | 5/5 + 4/5 |
| NDVI | 0,931 | 1,00 | 1,00 | 0,933–0,953 | 0,870–0,929 | 3/5 + 5/5 |
| ReNDVI | 0,810 | 1,00 | 1,00 | 0,820–0,858 | 0,721–0,801 | 3/5 + 5/5 |
| NDRE | 0,413 | 0,70 | 0,89 | 0,420–0,545 | 0,351–0,521 | 5/5 + 1/5 |
| GNDVI | 0,782 | 0,60 | 0,83 | 0,756–0,832 | 0,712–0,830 | 1/5 + 5/5 |
| BNDVI | 0,962 | 0,90 | 0,95 | 0,954–0,969 | 0,944–0,962 | 1/5 + 5/5 |
| SAVI / EVI / EVI2 | 0,71–0,79 | 0,60 | 0,70 | breit überlappend | | 0/5 + 5/5 |

Schwellen stimmen mit dem Testskript aus 5t überein (VARI 0,642, NDVI 0,931, ReNDVI 0,810). Fenster als Bild geprüft.

Einordnung (vorläufig, sehr kleine Stichprobe): Die Indizes aus den sichtbaren Kanälen mit Rot (NGRDI, VARI, GLI)
übertragen sich am besten auf die Prüfbäume; NDVI und ReNDVI trennen die Ableitungsbäume ebenso perfekt, aber die
Lücke zwischen den Klassen ist schmal (NDVI 0,929 → 0,933), sodass zwei vitale Prüfbäume knapp darunter fallen.
Passt zum Befund der Kanalanalyse (5o): Rot trägt die Trennung, die geschädigten Referenzbäume sind sichtbar verfärbt.

## 5v. Ergänzung Version 0.17.1 (2026-11-07): Bedienungsanleitung, Anhang der Arbeit, digitaler Anhang

Anlass: Wunsch des Nutzers, die Software mit einer genauen Anleitung so zu dokumentieren, dass Dritte (z. B. der
Zweitprüfer) sie nutzen können, und Anleitung und Programmcode in den Anhang der Arbeit aufzunehmen. Entscheidung des
Nutzers zum Code (ca. 5 550 Zeilen, als Volltext etwa 70–80 Seiten): **Übersicht in Word, vollständiger Code als
digitaler Anhang**.

| Bestandteil | Datei / Ort |
|---|---|
| Bedienungsanleitung (Quelle) | `Bedienungsanleitung_VI_Auswertung.md` im Programmordner |
| Aufbau und Programmcode (Quelle) | `Programmaufbau_VI_Auswertung.md` im Programmordner |
| Anhang A2 / A3 in Word | `Bachelorarbeit.docx`, nach A1, zwischen den Textmarken `AnhangSoftware_Start` / `_Ende` |
| digitaler Anhang | `Bachelorarbeit\Digitaler_Anhang\VI_Auswertung\` und `Bachelorarbeit\Digitaler_Anhang.zip`: Programmcode, `multispektral_stapeln.py`, Startdatei, `requirements.txt`, Anleitung, Programmaufbau, diese Dokumentation, `LIESMICH.md` mit SHA-256-Prüfsummen |
| Werkzeug zum Aktualisieren | `Software\Anhang_Werkzeug\anhang_aktualisieren.py` (stellt den digitalen Anhang neu zusammen und ersetzt A2/A3 in Word; Sicherung in `Sicherungen`, Word muss geschlossen sein; danach Felder/Verzeichnisse aktualisiert und PDF-Kontrolle) |

**Nach jeder Software-Änderung:** Anleitung (und ggf. Programmaufbau) anpassen, dann `python anhang_aktualisieren.py`.

Portabilität (0.17.1): `multispektral_stapeln.py` wird zuerst am eingestellten Pfad (`STAPEL_SKRIPT`), sonst neben
`vi_kern.py` gesucht; der Startordner der Dateidialoge fällt auf den Benutzerordner zurück, wenn der OneDrive-Ordner
fehlt. Test: ZIP in einen leeren Ordner entpackt, Pfad `STAPEL_SKRIPT` auf einen nicht vorhandenen Pfad gesetzt →
Skript aus dem Programmordner geladen, IMG_0018 (0026SET-Kopie) aus Rohbildern verarbeitet (NDVI-Median 0,8593).

Word: A2 S. 64–74, A3 S. 75–76, Inhaltsverzeichnis des Anhangs mit A2/A3, 88 Seiten, 0 × „Fehler!“. Formatierung im
zweiten Lauf verbessert (keine Silbentrennung in Datei-/Befehlsnamen, Spaltenbreiten nach längstem Wort, Version ohne
doppeltes Datum).

## 5w. Ergänzung Version 0.18 (2026-11-07): Krone teilen per Linie, Korrekturen löschen, Legende, Oberfläche

Anlass (Rückmeldung des Nutzers beim Korrigieren der Kronen in 0026SET): „Krone teilen“ setzte nur ein Kreuz, die
Krone wurde nicht getrennt; gesetzte Kreuze ließen sich nicht gezielt entfernen; Teile der Oberfläche schienen
abgeschnitten; die Legende zeigte auch im 2-Klassen-Schema „Übergang“.

Ursache „nur ein Kreuz“ (nachgerechnet mit der Korrekturdatei des Nutzers, IMG_0016): Beide Kreuze lagen auf der
Berührungsstelle zweier Kronen. Ein Kreuz ist eine zusätzliche *Kronenmitte* für die Wasserscheide; auf der
Berührungsstelle erzeugt es nur zwei kleine Splitter (Objekt am Klickpunkt danach ohne Krone), die Kronen bleiben
unverändert. Erwartet hatte der Nutzer einen Schnitt an dieser Stelle.

| Frage | Entscheidung |
|---|---|
| Krone teilen | **Linie ziehen = Schnitt** (`{"art": "schnitt", "xy": [[x1, y1], [x2, y2]]}`): Maske entlang der Linie (Breite `SCHNITT_BREITE_PX` = 3 px) auf „kein Baum“, Kronentrennung wie bisher auf der geschnittenen Maske (Teile ohne Kronenmitte erhalten eine eigene), danach gehen die Linienpixel samt Grenzpixeln (Umkreis 2 px) an die nächste Krone (bis `SCHNITT_ZUORDNUNG_PX` = 6 px) zurück – keine Fläche geht verloren. **Nur klicken** (< 8 Bildschirmpixel Bewegung) = Kronenmitte wie bisher (alte Korrekturdateien bleiben gültig) |
| Löschen | Klick auf eine Korrektur (≤ 10 Bildschirmpixel von Kreuz bzw. Linie) im Modus Teilen/Verbinden löscht genau diese; Knopf **„Korrekturen im Bild löschen …“** (mit Rückfrage); „↶ Kronenkorrektur“ bleibt |
| Legende 2 Klassen | gestresst = vital: Klassenkarte nur Rot/Grün, Farbskala mit zwei Einträgen, im Histogramm ein Legendeneintrag „Schwelle t: darunter gestresst, ab hier vital“; Anklicken der Angaben ändert beide Schwellen gemeinsam; Textzeilen ohne „Übergang“. 3 Klassen unverändert |
| Oberfläche | Breite jeder Leiste bei 1536 px Bildschirmbreite (Laptop, 125 % Skalierung) gemessen – vorher abgeschnitten: Hinweis Zoomen (Zeile 1), „Abbrechen“ (Zeile 2), **„Bäume einfärben“, „Baumnummern“** (Schwellwertzeile), Zähler der Referenzbäume. Jetzt: Hinweis in der Statuszeile, kürzere Beschriftungen („mit ROI-Pixeln“, „An Prüfbäumen prüfen …“), Fortschrittsbalken schmaler, Anzeige-Häkchen in der Baummodell-Zeile, Zähler umbrochen; breiteste Leiste 1482 px |
| Aufteilung | Bildbereich (Bilder + Histogramm) beim Start auf 2/3 der Fensterbreite (Wunsch des Nutzers), Trennlinie weiter verschiebbar |

### Test (Kopie von IMG_0016, 0026SET; Baummodell.joblib, verfeinert, Kronenabstand 150 px)

| Prüfung | Ergebnis |
|---|---|
| Schnittlinie senkrecht x = 400, y 540–760 (Pflanzraster an / aus) | Krone an der Linie getrennt (links/rechts verschiedene Objekte), Laufzeit 0,6 / 0,5 s; nach der Rückgabe der Linienpixel 9 Maskenpixel mehr ohne Krone als vorher (an / aus: −140, d. h. Grenzpixel der Wasserscheide mit zugeordnet); Bild geprüft |
| Oberfläche, simulierte Maus | Linie ziehen → `schnitt` gespeichert; Klick in Krone → `teilen`; Klick auf Linie bzw. Kreuz → jeweils genau diese gelöscht; „Korrekturen im Bild löschen“ → Datei leer |
| Legende | 2 Klassen (0,931/0,931): Farbskala „gestresst < 0.931“ / „vital ≥ 0.931“, Histogramm ein Schwelleneintrag, Klickziele „beide“; 3 Klassen (0,90/0,94): wie bisher mit „Übergang“ |
| Leisten / Aufteilung | alle Leisten ≤ 1482 px bei 1536 px Bildschirm; Trennlinie bei 1024 von 1536 px (0,667) |

## 5x. Ergänzung Version 0.18.1 (2026-11-07): Referenz- und Beispielflächen per Klick löschen

Anlass: Frage des Nutzers, wie falsch als vital oder geschädigt eingezeichnete Bäume gelöscht werden können. Bisher
nur „Letzte Referenz entfernen“ bzw. „Letzte Fläche entfernen“ (jeweils die zuletzt gezeichnete).

| Frage | Entscheidung |
|---|---|
| Bedienung | Im Modus „Referenz: vital/geschädigt“ ein **Klick** (Lasso mit < 6 Bildschirmpixeln Ausdehnung) in eine Referenzfläche des angezeigten Bildes löscht sie – unabhängig von ihrer Klasse, damit eine falsch zugeordnete Fläche in jedem der beiden Modi gelöscht werden kann; genauso Beispielflächen des Baummodells in „Beispiel: Baum/kein Baum“ |
| Überlappende Flächen | die kleinste Fläche, die den Klickpunkt enthält |
| Danach | Hinweis in der Statuszeile: Referenzdatei neu speichern bzw. Modell neu berechnen (die Datei auf der Festplatte ändert sich erst beim Speichern) |

Test (Kopie von IMG_0016, simulierte Maus): zwei vitale Referenzen per Lasso eingezeichnet → Klick in V1 löscht V1,
Klick neben die Flächen löscht nichts (Hinweis), Klick in V2 im Modus „geschädigt“ löscht V2; Zähler aktualisiert.

## 5y. Ergänzung Version 0.19 (2026-11-08): Rechenaufwand je Kanalsatz, Kanalsatz „ohne Blau“, Holm-Korrektur

### Anlass

Ausarbeitung der Gerüste 4.4–4.5 (08.11.2026): Teilziel 2 der Leitfrage (Rechenaufwand für KI-Modelle, Kapitel 5.3)
wurde bisher nicht gemessen. Der Nutzer hat entschieden: Messung einbauen; Holm-Korrektur für die vielen gleichzeitig
geprüften Merkmale (Vorschlag Claude, weil der Nutzer die Frage noch nicht beurteilen konnte); zusätzlicher Kanalsatz
ohne Blaukanal (Kanäle der DJI Mavic 3M, die bei der LKSH genutzt wird; Bilder vor der Abgabe nicht zu erwarten).

### Getroffene Entscheidungen

| Frage | Entscheidung | Begründung |
|---|---|---|
| Was heißt „Rechenaufwand“? | drei Größen je Kanalsatz: **Datenmenge** (Rohdateien und Reflektanzstapel je Aufnahme), **Vorverarbeitungszeit** je Aufnahme, **Klassifikator** (Trainings- und Vorhersagezeit) | deckt Speicher, Vorverarbeitung und das eigentliche KI-Modell ab |
| Vorverarbeitung | je Set eine Aufnahme aus den Rohbildern laden (zweiter Lauf, Ausrichtung schon geschätzt), Zeit je Kanal = Gesamtzeit / Kanalzahl; je Kanalsatz **hochgerechnet** | jeder Kanal wird einzeln radiometrisch korrigiert, entzerrt und ausgerichtet; eine Teilmenge ohne Red Edge (Bezugskanal der Ausrichtung) lässt sich nicht getrennt laden |
| Klassifikator | **Random Forest** mit den Einstellungen des Baummodells (150 Bäume, min. 5 Pixel je Blatt, √m Merkmale, Klassengewichte ausgeglichen), Merkmale = Reflektanzen des Kanalsatzes, Ziel vital/geschädigt je Pixel; zum Vergleich **LDA** | RF ist das in der Arbeit bereits verwendete KI-Verfahren; kein neuronales Netz (Max Nr. 3) |
| Prüfung | **GroupKFold** (5 Falten) über ganze Bäume, Baum = Mehrheit seiner Pixel; Trefferquote und ausgewogene Trefferquote | Pixel eines Baums nicht auf Lern- und Prüfteil verteilen; Leave-one-tree-out wäre mit RF zu langsam |
| Pixel | 300 je Baum (`AUFWAND_PIXEL_JE_BAUM`) | Laufzeit; jeder Baum gleich gewichtet |
| Zeitmessung | ein Rechenkern (`n_jobs = 1`); Training = Mittel über die Falten; Vorhersage = Median aus 3 Wiederholungen auf 200 000 Pixeln, umgerechnet auf 1 Mio. Pixel; Rechnerangaben im Protokoll | vergleichbar, unabhängig von der Auslastung paralleler Kerne |
| Kanalsatz „ohne Blau“ | Grün, Rot, Red Edge, NIR (`KANALSAETZE`) | Kanäle wie bei der DJI Mavic 3M (Grün 560, Rot 650, RE 730, NIR 860 nm); **nur Näherung**, weil die Bandlagen abweichen (RedEdge-P: Rot 668, RE 717, NIR 842 nm) |
| Mehrfachtests | **Holm-Korrektur** der Welch-p-Werte aller Merkmale einer Gruppe (`holm`), Spalte `p_Holm_Baum` | 16 Merkmale je Gruppe; ohne Korrektur würde ein Merkmal mit größerer Wahrscheinlichkeit zufällig „signifikant“; Holm ist einfach und hält das Gesamtfehlerniveau ein, ohne Annahmen über die Abhängigkeit der Tests |
| Oberfläche | eigener Knopf **„Rechenaufwand messen …“** im Fenster der Kanalanalyse, Hintergrund-Thread mit Fortschritt und Abbrechen, Reiter „Rechenaufwand“; CSV-Export zusammen mit der Kanalanalyse | Messung dauert Minuten, die restliche Kanalanalyse bleibt schnell |

### Formeln

- Holm: p-Werte aufsteigend p₍₁₎ ≤ … ≤ p₍ₘ₎; p_adj₍ᵢ₎ = max_{j ≤ i} min(1, (m − j + 1) · p₍ⱼ₎)
- Datenmenge Stapel je Aufnahme = Kanalzahl · Pixel · 4 Byte (float32)
- Vorverarbeitung je Kanalsatz = Kanalzahl · (gemessene Zeit je Aufnahme / 5)
- Vorhersagezeit je 1 Mio. Pixel = gemessene Zeit für 200 000 Pixel · 5

### Tests (Kopie der 30 Referenzbäume aus 0026SET/0028SET vom 06.11., Scratchpad)

- Holm gegen Handrechnung: p = (0,01; 0,04; NaN; 0,03; 0,005) → (0,03; 0,06; NaN; 0,06; 0,02) ✓
- Kanalanalyse unverändert reproduziert (LDA RGB 0,63 / RGB+NIR 0,83 / alle 5 0,90; NDVI d = 4,87) ✓; neu „ohne Blau“:
  erklärte Varianz Pixel 0,956, LDA 0,90
- Rechenaufwand (Laufzeit 126 s; AMD64 Family 25 Model 80, 12 logische Kerne, gerechnet mit 1 Kern; Python 3.14.6,
  scikit-learn 1.9.1), Gruppe „alle“:

| Kanalsatz | MB roh/Aufn. | MB Stapel/Aufn. | Vorverarb. s/Aufn. (hochger.) | RF Treffer Baum | RF Training s | RF s/Mio px | LDA Treffer Baum |
|---|---|---|---|---|---|---|---|
| RGB | 9,5 | 18,4 | 2,4 | 0,97 | 0,91 | 9,8 | 0,70 |
| RGB+NIR | 12,7 | 24,5 | 3,2 | 0,97 | 1,23 | 9,1 | 0,80 |
| ohne Blau | 12,7 | 24,5 | 3,2 | 0,97 | 1,24 | 9,2 | 0,83 |
| alle 5 | 15,9 | 30,6 | 4,0 | 0,97 | 1,29 | 9,2 | 0,83 |

  Vorverarbeitung je Kanal: 0026SET 0,83 s, 0028SET 0,75 s (Bild 1435 × 1066 px; Rohdatei je Kanal 3,18 MB).
- Oberfläche: Kanalanalyse geöffnet, Knopf „Rechenaufwand messen …“ ausgelöst (Bestätigung simuliert), Tabellen
  ausgelesen: Spalte „p Holm“, Kanalsatz „ohne Blau“ und Reiter „Rechenaufwand“ gefüllt ✓. Ein zweiter Lauf parallel
  zur laufenden Software des Nutzers ergab 10–30 % höhere Zeiten (RF 10,3–11,6 s/Mio px) → Zeiten sind
  auslastungsabhängig, Messung ohne andere Last wiederholen. `Sitzung.json` und Einstellungen unverändert ✓.

### Einordnung (vorläufig)

- Datenmenge und Vorverarbeitung steigen **linear** mit der Kanalzahl (je Kanal ≈ 3,2 MB roh, 6,1 MB Stapel, ≈ 0,8 s).
- Die **Vorhersagezeit des Random Forest hängt kaum von der Kanalzahl ab** (≈ 9–10 s je Mio. Pixel auf einem Kern,
  ein Bild ≈ 1,5 Mio. Pixel); das Training wird mit mehr Kanälen etwas langsamer (0,9 → 1,3 s).
- Der Random Forest trennt schon mit RGB 29 von 30 Bäumen richtig; die LDA profitiert dagegen deutlich von NIR/Red
  Edge (0,70 → 0,83). Passt zu 5o: Rot trägt die Trennung bei sichtbar verfärbten Bäumen. Für frühe Schäden offen.
- Die LDA-Werte hier (5-fach über Bäume) weichen von denen im Reiter „Kanalsätze“ (Leave-one-tree-out) ab
  (RGB 0,70 statt 0,63) – unterschiedliche Prüfverfahren, in der Arbeit nur eines berichten oder beide benennen.
- Mit den endgültigen Referenzbäumen und ohne andere Last am Rechner wiederholen.

## 5z. Hilfsskript (2026-11-08): doppelte Referenzbäume über Bilder und Sets finden

Anlass: 0026SET und 0028SET zeigen dieselben Bäume (Flüge ≈ 15 min auseinander, Verfasser 08.11.). Ableitungsbäume
(0026) und Prüfbäume (0028) dürfen nicht derselbe Baum sein; die Software erkennt Überschneidungen nur im selben Bild.
Der Nutzer bat darum, seine Referenzdateien nach dem Einzeichnen auf Dopplungen zu prüfen.

Skript: `Software\Hilfsskripte\dopplungen_pruefen.py` (nicht Teil der Oberfläche, liest nur).
Aufruf: `python Software\Hilfsskripte\dopplungen_pruefen.py Datei1.joblib Datei2.joblib [--csv Ausgabe.csv]`

| Schritt | Umsetzung |
|---|---|
| Kandidaten | GPS der Bildmitten (Kanal 1); nur Paare < 16 m (Bild ≈ 11 × 8 m, GPS ± wenige m) |
| Abgleich | SIFT-Merkmale im NIR-Kanal des Reflektanzstapels (gleiches Raster wie die Umrisse), Verhältnistest 0,75, Homographie mit RANSAC (5 px), mindestens 25 übereinstimmende Punkte |
| Entscheidung | Umriss aus Bild A per Homographie nach Bild B übertragen; Überdeckung ≥ 30 % der kleineren Fläche oder Mittelpunkt im Umriss → derselbe Baum; im selben Bild direkte Überdeckung |
| Ausgabe | Liste der Paare (Datei, Set, Aufnahme, Nr., Klasse), Warnung bei widersprüchlicher Klasse, Liste der nahen Bildpaare ohne Abgleich (selbst vergleichen), optional CSV |

Test (Kopien von `Referenzbaeume_0026_Ableitung.joblib`, 10 + 10, und `Referenzbaeume_0026_Referenz.joblib`, 5 + 5;
15 Bildpaare, 8 abgeglichen): **6 Dopplungen**. Drei Bäume der Referenz-Datei (IMG_0008 Nr. 7, 9, 10) sind
Ableitungsbäume (IMG_0017 Nr. 3, 1, 4), dazu Dopplungen innerhalb der Referenz-Datei (IMG_0008 Nr. 8/9 = IMG_0035
Nr. 2/1). Klassen jeweils gleich. Sichtprüfung zweier Paare (Ausschnitte nebeneinander): eindeutig derselbe Baum,
Bild um ≈ 180° gedreht (gegenläufige Fluglinien). 7 nahe Paare (7–13 m, ein Paar 5,5 m) ohne ausreichende
Übereinstimmung (5–19 Punkte) → vermutlich wenig Überlappung; werden als „selbst vergleichen“ gemeldet.
Grenze: Bilder mit wenig Überlappung oder starker Bewegungsunschärfe lassen sich nicht abgleichen.

## 5za. Ergänzung Version 0.20 (2026-11-08): Ableitungsbäume hinterlegen und einblenden, Abgleich bei der Prüfung

Anlass: Wunsch des Nutzers nach dem Hilfsskript 5z: Die Dopplungsprüfung soll beim Prüfen an Prüfbäumen automatisch
laufen, und beim Einzeichnen der Prüfbäume sollen die Ableitungsbäume sichtbar sein (0026SET und 0028SET zeigen
dieselben Bäume; Ableitung in 0026, Prüfung in 0028).

| Frage | Entscheidung | Begründung |
|---|---|---|
| Verfahren | wie Hilfsskript 5z (GPS < 16 m, SIFT im NIR-Kanal, Homographie mit RANSAC ≥ 25 Punkte, Überdeckung ≥ 30 % der kleineren Fläche oder Mittelpunkt im Umriss), als Kernfunktionen `flaechen_uebertragen`, `referenz_dopplungen`, `umrisse_gleicher_baum` | geprüft; ein Verfahren für Anzeige und Prüfung |
| Zwischenspeicher | GPS, SIFT-Merkmale (max. 80 Aufnahmen) und Homographien je Bildpaar werden gemerkt | erneutes Einblenden/Prüfen in Sekundenbruchteilen statt Sekunden |
| Hinterlegen | eigener, nicht veränderbarer Satz `hinterlegt` (Knopf **Ableitung hinterlegen …**, Häkchen **einblenden**); Pfade im Arbeitsstand | die aktuelle Sammlung bleibt frei für die neuen Prüfbäume |
| Einblendung | Ableitungsbäume weiß gestrichelt „A·V/G Nr.“, eigene Referenzen aus Nachbarbildern farbig gestrichelt „V/G Nr.*“; Berechnung im Hintergrund, nur für das aktuell angezeigte Bild; Umrisse, deren Mitte außerhalb des Bildes liegt, entfallen | Prüfbäume weder auf Ableitungsbäume noch doppelt zeichnen |
| Warnung beim Zeichnen | neuer Umriss auf eingeblendetem Baum → Rückfrage „Trotzdem behalten?“ | Fehler sofort statt erst bei der Prüfung erkennen |
| Prüfung | vor dem Start Abgleich im Hintergrund (Fortschritt, Abbrechen); Vergleichsgrundlage: hinterlegte Ableitung, sonst geladene Referenzen; identische Flächen (dieselbe Datei) werden übergangen; Rückfrage Ja = ausschließen / Nein = alle / Abbrechen | ersetzt die bisherige Prüfung nur im selben Bild (`referenz_ueberschneidungen`) |
| Ausschluss | Prüfbäume, die ein Ableitungsbaum sind; bei doppelt eingezeichneten Prüfbäumen jeweils der zweite | jeder Baum zählt einmal |
| Protokoll | `dopplungen` (Verfahren, Paare, nahe Bilder ohne Abgleich), `doppelte_ausgeschlossen`; Hinweis im Ergebnisfenster | Nachvollziehbarkeit |

### Tests (Kopien der beiden 0026-Referenzdateien; Oberfläche per Skript, Abbildung der Software als Datei gespeichert)

- Kern: Ableitung (10 + 10) gegen Referenz-Datei (5 + 5): 4 Prüfbäume = Ableitungsbaum (IMG_0008 V7, V9, G10; IMG_0035 V1),
  2 doppelt eingezeichnet (IMG_0008 V8/V9 = IMG_0035 V2/V1) – deckt sich mit dem Hilfsskript (dort zusätzlich
  IMG_0035 V1 über IMG_0017 gefunden). Erster Lauf 3,6 s, zweiter 0,2 s (Zwischenspeicher). Dieselbe Datei als
  Ableitung und Prüfung: 0 Treffer gegen die Ableitung ✓.
- Einblendung in 0026 IMG_0008: 7 Ableitungsbäume aus IMG_0017 übertragen (einer außerhalb des Bildes entfällt),
  Lage im Bild geprüft ✓; Statuszeile nennt IMG_0024/0025 als nicht abgleichbar.
- **Über Sets:** 0026 IMG_0017 → 0028 IMG_0022 (GPS 0,7 m): alle 8 Umrisse liegen auf denselben Kronen (Bild nebeneinander geprüft) ✓.
- Zeichnen eines Referenzbaums auf A·G4 → Rückfrage, „Nein“ → nicht übernommen ✓; an freier Stelle keine Rückfrage ✓.
- Prüfung: Rückfrage listet die Dopplungen, „Ja“ → 5 Prüfbäume ausgeschlossen, Ergebnisfenster mit Hinweis, Protokoll
  mit `dopplungen` ✓. `Sitzung.json` und Einstellungen des Nutzers unverändert ✓.

Grenze: Nachbarbilder mit wenig Überlappung (Abstand ≳ 7 m) oder zu wenig Bildmerkmalen lassen sich nicht abgleichen;
sie werden gemeldet und müssen von Hand verglichen werden.

## 5zb. Ergänzung Version 0.20.1 (2026-11-08): Abgleich im Grünkanal, „sicher“ und „fraglich“

Anlass: Erster echter Einsatz (Prüfbäume 0026 und 0028 des Nutzers): 15–17 nahe Bildpaare ließen sich im NIR-Kanal
nicht abgleichen, darunter genau die 0028-Bilder am 0026-Streifen.

| Frage | Entscheidung | Begründung (Test) |
|---|---|---|
| Kanal | SIFT zuerst im **Grünkanal**, ersatzweise NIR (`DOPPEL_KANAELE`) | bei 5–10 m Abstand Grün 31–132 Übereinstimmungen, NIR 6–29 (Schatten/Kronenstruktur im Sichtbaren schärfer); Kontrollpaar 0,7 m in beiden > 1400 |
| Plausibilität | Homographie nur, wenn Maßstab 0,75–1,33 und Perspektivanteil < 5·10⁻⁴ | gleiche Flughöhe; verwirft Fehlzuordnungen (Beispiel: Maßstab 2,95 bei 37 Punkten) |
| Einstufung | **sicher** ab 50 % Überdeckung (wird ausgeschlossen), **fraglich** ab 30 % oder Mittelpunkt im Umriss (nur gemeldet) | Sichtprüfung aller 17 Treffer (übertragener Umriss über eingezeichnetem): 61–97 % eindeutig derselbe Baum; 31–46 % meist halb auf dem Nachbarbaum – Kronenspitzen verschieben sich zwischen zwei Blickwinkeln (Bäume ≈ 2 m hoch, 12 m Flughöhe) |
| Paare | jedes Paar aus beiden Richtungen, die höhere Überdeckung zählt | vorher teils doppelt/uneinheitlich gemeldet |

Ergebnis an den Dateien des Nutzers (Stand 14:57; Ableitung 10 + 10, Prüfung 0026 8 + 8, Prüfung 0028 8 + 8):
**kein Prüfbaum = Ableitungsbaum**; **12 sichere Dopplungen zwischen den Prüfbäumen** (9 Bäume in 0026 und 0028
zugleich eingezeichnet, in 0028 G18 = G31), 5 fragliche. Verschiedene Prüfbäume insgesamt: 9 vital, 12 geschädigt
(32 Flächen). 30 nahe Paare ohne Abgleich (meist Randüberlappung).

Maske: Referenzdateien speichern nur „Baum“, nicht ob verfeinert. Die Ableitungsdatei von 14:57 ist inhaltlich
identisch mit der vom 06./07.11. (Umrisse und Werte gleich). Maßgeblich für Schwellen auf Baumebene und Prüfung ist die
Maske beim Rechnen (im Protokoll): Prüfung 0026 (14:39) ohne, Prüfung 0028 (14:48) mit Verfeinerung.

## 5zc. Ergänzung Version 0.20.2 (2026-11-08): Baumregel für alle Indizes, Warnungen bei der Prüfung

Anlass: In der Prüfung 0026 des Nutzers (15:05) galt „Median je Baum“ nur für NDVI, für die übrigen 10 Indizes
„Anteil gestresster Pixel ≥ 10 %“ – alle vitalen Prüfbäume wurden dort „gestresst“. Ursache: Die Baumregel war je Index
gespeichert; das Auswahlfeld änderte nur den angezeigten Index, „Für alle Indizes übernehmen“ übernahm die Regel, die
beim Klick im Feld stand. Bei 0028 (15:08) stand beim Übernehmen bereits „Median“ → einheitlich.

| Frage | Entscheidung |
|---|---|
| Baumregel | gilt für alle Indizes mit Schwellen (`_baumregel_alle`, `dataclasses.replace`), Statuszeile nennt geänderte Indizes |
| Prüfung | Rückfrage nennt die Baumregel; Warnung bei gemischten Regeln und bei Pixelschwellen (Herkunft „Referenzflächen…“) mit Hinweis auf „Baumebene: Schwellen aus Baummedianen …“ |

Test: drei Indizes mit „Anteil“, Regel auf „Median“ umgestellt → alle drei „median“, Statuszeile korrekt; Sitzung unverändert ✓.

## 5zd. Hilfsskripte (2026-11-08): einheitliche Endauswertung, Kreuzvalidierung und Konfidenzintervalle

Anlass: Die Prüfungen des Nutzers (15:05/15:08) nutzten Pixelschwellen und in 0026 gemischte Baumregeln (5zc); die
Prüfbäume aus 0026 und 0028 enthielten 12 sichere Dopplungen (5zb). Auf die Frage des Nutzers, ob die Auswertung
aussagekräftig sei: kleine Stichprobe → Konfidenzintervalle und Kreuzvalidierung über alle Bäume ergänzt.

**`Software\Hilfsskripte\endauswertung_20261108.py`** (240 s): Schwellen aus Baummedianen der Ableitung (0026,
10 + 10), Prüfbäume 0026 + 0028 zusammengeführt, sichere Dopplungen entfernt (bei 0026/0028-Paaren bleibt die
0028-Fassung, innerhalb eines Sets die zuerst gezeichnete) → 10 vital + 12 geschädigt; Prüfung gesamt und je Set.
Einstellungen: Baummodell.joblib verfeinert (Lücken < 30 %), Pflanzraster, Kronenkorrekturen, Median je Baum.
Ausgaben in `Bilder\VI_Auswertung\Endauswertung_20261108\` (neuer Ordner; Eingabedateien nur gelesen):
`Schwellen_Baummediane.csv`, `Pruefung_alle_verschieden|nur_0026|nur_0028*.csv`, `Pruefbaeume_verschieden_0026_0028.joblib`,
`Endauswertung_Protokoll.json`.

**`Software\Hilfsskripte\kreuzvalidierung_konfidenz_20261108.py`** (117 s), je Index:

| Teil | Verfahren |
|---|---|
| Mediane | Median je Baum für alle 42 Bäume mit denselben Einstellungen (`pruefe_schwellen`) |
| A Prüfung | Youden-Schwelle aus den 20 Ableitungsbäumen → 22 Prüfbäume |
| B Kreuzvalidierung | Leave-one-tree-out über alle 42: Youden-Schwelle aus 41 Bäumen (`_youden_baum`), Einstufung des ausgelassenen |
| Intervalle | Sensitivität/Spezifität: Wilson (95 %); ausgewogene Trefferquote, AUC, Cohens d: Bootstrap 5000×, je Klasse mit Zurücklegen, Perzentil 2,5–97,5 %, Startwert 0 |
| Vergleich | McNemar exakt (Binomialtest der nur-einer-richtig-Fälle), bester Index gegen jeden anderen; Holm-Korrektur über 10 Vergleiche (nachgerechnet) |

Ergebnisse (Auszug; vollständig in `Kreuzvalidierung_Konfidenz.csv` und Notiz Kapitel 5):

| Index | AUC (KI) | KV ausgewogen (KI) | Prüfung ausgewogen (KI) |
|---|---|---|---|
| VARI | 0,959 (0,90–1,00) | 0,932 (0,86–1,00) | 0,792 (0,67–0,92) |
| NGRDI | 0,955 (0,88–1,00) | 0,909 (0,82–0,98) | 0,875 (0,75–1,00) |
| GLI | 0,950 (0,88–1,00) | 0,859 (0,74–0,95) | 0,775 (0,59–0,95) |
| ReNDVI | 0,945 (0,87–0,99) | 0,834 (0,71–0,93) | 0,767 (0,58–0,92) |
| NDRE | 0,873 (0,74–0,98) | 0,789 (0,67–0,90) | 0,833 (0,71–0,96) |
| NDVI | 0,950 (0,88–0,99) | 0,764 (0,62–0,88) | 0,767 (0,57–0,92) |
| GNDVI | 0,743 (0,58–0,88) | 0,477 (0,33–0,62) | 0,558 (0,37–0,75) |

McNemar gegen VARI nach Holm: nur GNDVI signifikant (p < 0,001); alle anderen p ≥ 0,14.
Einschätzung: Gruppen (stark: VARI, NGRDI, GLI, ReNDVI, NDVI; schwach: GNDVI, SAVI, EVI, EVI2) sind belastbar, eine
Rangfolge innerhalb der Spitzengruppe nicht. Bäume derselben Fläche sind räumlich abhängig → Intervalle eher zu schmal.

## 5ze. Hilfsskript (2026-11-08): Kanalanalyse und Rechenaufwand mit den 42 Bäumen

`Software\Hilfsskripte\kanalanalyse_aufwand_20261108.py` (185 s): Ableitung (10 + 10) + bereinigte Prüfbäume (10 + 12);
Kanalwerte aller 42 Flächen neu erfasst (`ergaenze_kanalwerte(..., alle=True)`, Umriss ∩ Baummaske verfeinert), dann
`kanalanalyse` und `rechenaufwand`. Ausgaben: `Endauswertung_20261108\Kanalanalyse_42_*.csv`, `_Rechenaufwand.csv`,
`_Vorverarbeitung.csv`, Parameterprotokolle, `Referenzbaeume_42_mit_Kanalwerten.joblib`.

Kernergebnisse (alle 42): Spitzengruppe NDVI, ReNDVI, VARI, NGRDI, GLI (Abstand 1,0–1,22 Std innen, d 3,4–3,9, AUC
0,99–1,00), NDRE d 1,85 / AUC 0,90, GNDVI d 0,92; Einzelkanäle: Rot d −1,96, NIR 0,71, Blau/Grün/Red Edge ≈ 0.
Korrelation Grün–Red Edge 0,91, Red Edge–NIR 0,88; PC1 74,2 %. Kanalsätze RF (5-fach über Bäume): RGB 0,88, RGB+NIR 0,90,
ohne Blau 0,93, alle 5 0,93; LDA je Baum ausgelassen 0,71 / 0,81 / 0,86 / 0,86; k-means 0,52–0,60.
Rechenaufwand: 0,69 s Vorverarbeitung und 3,18 MB Rohdaten je Kanal; RF-Vorhersage 10–12 s je Mio. Pixel unabhängig
von der Kanalzahl. Hinweis: AUC hier (Pixel im eingezeichneten Umriss) höher als in der Endauswertung (automatisch
abgegrenzte Kronen mit Rand/Schatten).

## 5zf. Hilfsskripte und Datenpflege (2026-11-09) – keine Programmänderung, Version unverändert

- **GPS-Abgleich der Sets** (`Software\Hilfsskripte\gps_sets_abgleich_20261109.py`, `gps_unterordner_0030_20261109.py`): GPS aller
  3602 Aufnahmen über `aufnahme_gps`; Median, Ausdehnung (P2–P98) und Anteil der Aufnahmen mit < 15 m Abstand zu einem anderen Set.
  Ergebnis: B = 0026 ⊂ 0028; C = 0007 = 0008; A (Hohenlockstedt) = drei getrennte Teilflächen A1 (0029, 0002), A2 (0030),
  A3 (0032); 0003 erfasst A3 und Teile von A2. Dateien in `Bilder\VI_Auswertung\GPS_Abgleich_20261109\`.
- **Flughöhen** (`gps_hoehen_sets_20261109.py`, Tag `GPSAltitude` des ersten Kanals): 13.07. durchgehend 73,6 m über NN, 29.10.
  0003 81,5/91,5 m, 0002 73,5/81,5/91,6 m → am 29.10. ca. 8 bzw. 18 m höher (Bestätigung durch Max ausstehend).
- **Bildpaare** (`bildpaare_0003_20261109.py`): Grünkanal an denselben GPS-Punkten 0032/0030 (13.07.) vs. 0003 (29.10.);
  SIFT zwischen den Terminen ohne verlässliche Treffer (≤ 3 passende Merkmale), Sichtvergleich bestätigt größere Höhe bei 0003.
- **0030SET/002 ließ sich nicht laden:** Alle TIFF-Dateien lesbar; `schaetze_ausrichtung` bricht ab mit „Ausrichtung für Kanal Red
  fehlgeschlagen (zu wenige gültige Schätzungen)“ (kontrastarme Aufnahmen, kleine Bäume im Unkraut). Behoben durch Übernahme von
  `0030SET/003/VI_Auswertung/Ausrichtung.json` (gleicher Flug, aktuelles Format, Feld `hinweis` ergänzt) nach
  `0030SET/002/VI_Auswertung/`. Test: IMG_0400/0500/0599 laden (Median-Reflektanz Blau 0,01, NIR 0,20–0,23).
  *Möglicher Ausbau (nicht umgesetzt):* Scheitert die Schätzung, automatisch die Ausrichtung eines Nachbarordners desselben Sets verwenden.
- Nachtrag Flughöhen: Max hat am 09.11. bestätigt, dass im Projekt 12, 20, 30 oder 40 m geflogen wird → 0002 = 12/20/30 m, 0003 = 20/30 m.

## 5zg. Version 0.20.3 (2026-11-09): Welch-Test und Holm-Korrektur entfernt

Anlass: Welch-Test, Holm-Korrektur (und McNemar) werden in der Bachelorarbeit nicht mehr verwendet (Entscheidung des Nutzers
am 09.11., Quellen gestrichen). Damit Programmcode, Anhang A2/A3 und Arbeit übereinstimmen, sind sie aus der Software entfernt.
Der Nutzer will sie nach der Arbeit ggf. wieder einbauen.

| Stelle | Änderung |
|---|---|
| `vi_kern._trennung` | `p_Welch_Baum` (scipy `ttest_ind`, Welch) entfernt |
| `vi_kern.holm` | Funktion entfernt, ebenso die Korrektur in `kanalanalyse` (`p_Holm_Baum`) und der Protokolleintrag `mehrfachtests` |
| Oberfläche, Reiter „Trennung je Kanal/Index“ | Spalten „p Welch“ und „p Holm“ und Erklärung entfernt |
| Bedienungsanleitung, Programmaufbau | entsprechend angepasst |

Wiederherstellen: alter Stand in `Sicherungen\Software\vi_kern_vor0203.py` und `vi_auswertung_vor0203.py` (Funktion `holm`,
Zeile mit `ttest_ind` in `_trennung`, Block „Mehrfachtests“ in `kanalanalyse`, Spalten in `vi_auswertung.py`).

Test: `py_compile` beider Dateien ✓. `kanalanalyse` mit `Endauswertung_20261108\Referenzbaeume_42_mit_Kanalwerten.joblib`:
48 Zeilen, Cohens d, AUC, ICC, Abstand und Mittelwerte stimmen mit `Kanalanalyse_42_Trennung.csv` (Version 0.20.2) überein
(größte Abweichung 5·10⁻⁵ = Rundung der CSV), keine p-Spalten mehr ✓. Alle übrigen Ergebnisse der Arbeit sind unberührt.
Die Hilfsskripte vom 08.11. bleiben unverändert (dokumentieren die Endauswertung, lesen `p_Holm_Baum` nur mit Ersatzwert).

## 6. Bedienung

Start: Doppelklick auf `VI_Auswertung starten.bat` oder in PowerShell:

```powershell
python "C:\Users\joshu\OneDrive\Bachelorarbeit\Software\VI_Auswertung\vi_auswertung.py"
```

1. Oben links **Kanäle** wählen (meist „automatisch“) und ggf. **Panchro schärfen** (Abschnitt 5l).
   **Aufnahme öffnen …** (beliebige Datei einer Aufnahme) oder **Ordner öffnen …** (auch übergeordnet). Mit ◀/▶ blättern.
   Für alle Aufnahmen auf einmal: **Ordner auswerten …** (Abschnitt 5a).
2. **Index** wählen. Bei Bedarf die **Vegetationsmaske** mit Schwellwert einschalten.
3. Zoomen/Verschieben über die Werkzeugleiste unter dem Bild. Für Pixelabfrage und ROIs Zoom/Pan wieder ausschalten.
4. **ROI zeichnen** einschalten und Rechtecke in der Indexkarte aufziehen. **ROIs löschen** setzt sie zurück
   (beim Wechsel der Aufnahme werden sie ebenfalls gelöscht).
5. **Exportieren** (optional mit ROI-Pixelwerten).

Benötigte Pakete (vorhanden): numpy, opencv-python-headless, tifffile, imagecodecs, matplotlib, scikit-learn (Baummaske). Tkinter ist in Python enthalten.

Einstellungen stehen oben in `vi_kern.py` im Block `EINSTELLUNGEN`: Pfad des Stapelskripts, Maskierungsgrenzen,
Anzahl der Aufnahmen für die Ausrichtungsschätzung, RGB-Skalierung.

**Ohne Oberfläche** (z. B. für spätere Stapelauswertung):

```python
import vi_kern as vk
a = vk.lade_aufnahme(r"...\0029SET\000", "IMG_0100")
ndvi = vk.berechne_index(a.stapel, a.kanalindex, "NDVI")
print(vk.statistik(ndvi))
```

## 7. Einschränkungen / Hinweise für die Arbeit

- **Nur DLS-Kalibrierung:** Die absolute Reflektanz hängt von der DLS-Messung ab. Relative Vergleiche innerhalb eines Flugs
  sind belastbarer als absolute Werte (vgl. Kapitel 2.2.4, Wang 2021). Für künftige Flüge: Panelaufnahmen vor und nach dem Flug.
- **Einzelbilder sind nicht georeferenziert:** ROIs sind Pixelrechtecke im jeweiligen Bild. Dieselbe Fläche muss in jedem Bild
  neu gesetzt werden. Für feste Parzellen über mehrere Bilder oder Termine ist ein Orthomosaik nötig.
- **Bildrand und Blickwinkel:** Am Bildrand wird schräger beobachtet als in der Bildmitte (BRDF-Effekte, Bildwinkel der RedEdge-P ca. 50°).
  Vergleiche möglichst mit Flächen in ähnlicher Bildposition.
- **Sättigung:** Gesättigte Rohpixel (≥ 65500) werden nicht maskiert. Laut Stapelskript betrifft das < 0,1 % der Pixel, meist
  Glanzpunkte auf Dächern. Beim Laden aus Rohbildern steht die Anzahl im Parameterprotokoll.
- **Vegetationsmaske:** Ein NDVI-Schwellwert trennt Vegetation von Boden, aber nicht Bäume von Gras zwischen den Reihen.
  Der gewählte Schwellwert muss in der Arbeit begründet werden.
- **Kapitel 4.3.3** der Notizen nennt bisher den QGIS-Rasterrechner als Implementierung der Indizes. Bei Verwendung dieser
  Software müsste die Methodenbeschreibung angepasst werden (noch nicht geändert).

## 8. Quellen

- MicaSense Image Processing (Radiometriemodell, Referenzimplementierung): https://github.com/micasense/imageprocessing
- Dokumentation des Stapelskripts: `Bilder\Flugtag130726\0029SET\000\Dokumentation_Kanalstapelung_Radiometrie.md`
- Index-Definitionen: Rouse et al. (1974), Barnes et al. (2000), Wang (2021), Gitelson et al. (1996). Siehe Kapitel 2.3 und
  die Quellennotizen im Obsidian-Vault.
- Breiman, L. (2001): Random Forests. Machine Learning 45, 5–32.
- Pedregosa et al. (2011): Scikit-learn: Machine Learning in Python. JMLR 12, 2825–2830.
- Evangelidis & Psarakis (2008): Parametric Image Alignment Using Enhanced Correlation Coefficient Maximization. IEEE TPAMI 30(10).
