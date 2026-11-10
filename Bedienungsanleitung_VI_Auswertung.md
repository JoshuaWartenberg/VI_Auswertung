# Bedienungsanleitung VI-Auswertung

Stand: Version 0.20.3 (09.11.2026)

## 1. Zweck

VI-Auswertung ist eine Desktop-Software zur pixel- und baumweisen Auswertung von Vegetationsindizes aus Einzelaufnahmen der Multispektralkamera MicaSense RedEdge-P. Sie rechnet die Rohbilder mit dem Sonnenlichtsensor DLS 2 in Reflektanz um, richtet die Kanäle deckungsgleich aus, berechnet elf Vegetationsindizes, grenzt die Baumkronen ab und bewertet jeden Baum als vital oder gestresst. Schwellwerte werden aus eingezeichneten Referenzbäumen abgeleitet und an getrennten Prüfbäumen kontrolliert. Eine Kanalanalyse zeigt, welche Kanäle und Indizes vitale und geschädigte Bäume am besten trennen. Alle Ergebnisse werden mit einem Parameterprotokoll gespeichert.

## 2. Installation

**Voraussetzungen:** Windows, Python 3 (getestet mit Python 3.14) und folgende Pakete:

| Paket | Zweck | getestete Version |
|---|---|---|
| numpy | Rechnen mit Bildern | 2.5.3 |
| opencv-python | Entzerrung, Ausrichtung, Bildverarbeitung | 5.0.0 |
| tifffile, imagecodecs | Lesen und Schreiben der TIFF-Dateien | 2026.9.20, 2026.8.16 |
| matplotlib | Darstellung | 3.11.2 |
| scikit-learn, scipy, joblib | Baummodell, Statistik, Speichern | 1.9.1, 1.18.1, 1.6.0 |

Installation der Pakete in der Eingabeaufforderung: `pip install numpy opencv-python tifffile imagecodecs matplotlib scikit-learn scipy joblib` (oder `pip install -r requirements.txt` im Programmordner). Tkinter für die Oberfläche ist in Python enthalten.

**Programmdateien** (alle im selben Ordner):

| Datei | Inhalt |
|---|---|
| `vi_auswertung.py` | Oberfläche |
| `vi_kern.py` | Rechenkern ohne Oberfläche |
| `multispektral_stapeln.py` | geprüfte Vorverarbeitung (Radiometrie, Entzerrung, Ausrichtung), wird vom Rechenkern eingebunden |
| `VI_Auswertung starten.bat` | Start per Doppelklick |

**Start:** Doppelklick auf `VI_Auswertung starten.bat` oder `python vi_auswertung.py` im Programmordner.

**Systemvoraussetzungen und Grenzen der Lauffähigkeit:**

| Punkt | Voraussetzung |
|---|---|
| Betriebssystem | Windows (getestet). Unter macOS oder Linux sollte der Start mit `python vi_auswertung.py` grundsätzlich funktionieren, ist aber nicht getestet; die Startdatei `.bat` gilt nur für Windows |
| Python | Python 3 mit den oben genannten Paketen. Getestet nur mit Python 3.14 und den angegebenen Paketversionen; ältere Versionen (etwa ab Python 3.10) sind wahrscheinlich geeignet, aber nicht geprüft |
| Bildschirm | Breite von mindestens etwa 1400 Pixeln, sonst sind Knöpfe am rechten Rand der Werkzeugleisten abgeschnitten |
| Arbeitsspeicher | etwa 8 GB empfohlen, vor allem für Aufnahmen mit panchromatischem Kanal (doppelt so feines Raster) |
| Schreibrechte | Die Software legt neben dem Programm den Ordner `Sitzung` an und schreibt in die Datenordner (`VI_Auswertung` mit Ausrichtung, Kronenkorrekturen, Exporten). Von CD oder einem schreibgeschützten Datenträger daher vorher auf die Festplatte kopieren |
| Daten | nur Aufnahmen der MicaSense RedEdge-P mit Messwerten des Sonnenlichtsensors DLS 2 in den Metadaten; andere Kameras werden nicht unterstützt |
| Programmdateien | `vi_auswertung.py`, `vi_kern.py` und `multispektral_stapeln.py` müssen im selben Ordner liegen |

Erste Prüfung auf einem neuen Rechner: ZIP entpacken, `pip install -r requirements.txt`, Software starten, eine Aufnahme öffnen. Erscheinen Echtfarbenbild und Indexkarte, ist die Installation vollständig.

## 3. Daten

- **Aufnahmen:** Rohbilder der RedEdge-P mit den Dateien `IMG_XXXX_1.tif` bis `IMG_XXXX_5.tif` (fünf Spektralkanäle) bzw. zusätzlich `IMG_XXXX_6.tif` (panchromatischer Kanal). Welche Datei welcher Kanal ist, liest die Software aus den Metadaten.
- **DLS 2:** Die Bestrahlungsstärke des Sonnenlichtsensors muss in den Metadaten stehen. Ohne sie ist keine Reflektanz berechenbar (die Software meldet das beim Laden).
- **Ordner:** Ein Aufnahmeordner der Kamera (z. B. `0026SET\000`). Beim Öffnen können auch übergeordnete Ordner gewählt werden (ein ganzes Set oder ein Flugtag), alle Unterordner mit Aufnahmen werden gefunden.
- **Ausrichtung:** Beim ersten Öffnen eines Ordners schätzt die Software die Ausrichtung der Kanäle aus zehn Aufnahmen und speichert sie in `<Ordner>\VI_Auswertung\Ausrichtung.json` (einmalig etwa 2 Minuten). Danach wird sie wiederverwendet.
- **Reflektanzbilder:** Liegen im Ordner `Reflektanz_5Kanal` bereits Reflektanzbilder des Vorverarbeitungsskripts, werden diese direkt gelesen (schneller, identische Werte).

## 4. Oberfläche im Überblick

Die Bedienelemente stehen in sechs Zeilen über dem Bild:

| Zeile | Inhalt |
|---|---|
| 1 | Kanäle, Panchro schärfen, nur Kronen, Aufnahme öffnen, Ordner öffnen, ◀ ▶ und Bildnummer, Index, Farbskala, Ganzes Bild |
| 2 | Maske, Schwelle, verfeinern, Umriss im RGB, ROIs löschen, mit ROI-Pixeln, Exportieren, Ordner auswerten, Indexraster speichern, Fortschritt, Abbrechen |
| 3 | Zeichnen: aus/Pixelabfrage, ROI, Beispiel Baum, Beispiel kein Baum, Referenz vital, Referenz geschädigt, Krone teilen, Kronen verbinden, ↶ Kronenkorrektur, Korrekturen im Bild löschen |
| 4 | Baummodell: Modell berechnen, Letzte Fläche entfernen, Modell speichern, Modell laden, Neues Modell; Anzeige: Klassenkarte, Bäume einfärben, Baumnummern |
| 5 | Schwellwerte: ein/aus, gestresst, vital, Baum gestresst ab, Baumregel, Kronen trennen (Abstand), an NIR ausrichten, Pflanzraster, Startwerte |
| 6 | Referenzbäume: Schwellen aus Referenzen, Kanalanalyse, Letzte Referenz entfernen, Referenzen speichern/laden/hinzuladen, An Prüfbäumen prüfen, Zahl der geladenen Referenzbäume |

Darunter links das Echtfarbenbild und die Indexkarte mit Histogramm (beim Start 2/3 der Fensterbreite; die Trennlinie zur rechten Spalte lässt sich mit der Maus verschieben), rechts Formel, Statistiktabellen, Klassenanteile, Bewertung je Baum und die Pixelabfrage. Unten die Statuszeile mit **Alles zurücksetzen …** und **Darkmode**.

**Navigation im Bild:** Mausrad = zoomen, rechte Maustaste gedrückt halten = verschieben, **Ganzes Bild** = Ansicht zurücksetzen. Mit Zeichnen „aus“ zeigt ein Klick ins Bild die Reflektanz aller Kanäle und alle Indexwerte des Pixels.

## 5. Bedienung Schritt für Schritt

### 5.1 Aufnahmen öffnen

1. **Kanäle** wählen: meist „automatisch“. Für Sets mit panchromatischem Kanal „6 Kanäle (mit Panchro)“.
2. **Aufnahme öffnen …** (eine beliebige Datei der Aufnahme) oder **Ordner öffnen …** (auch übergeordnete Ordner).
3. Mit **◀ ▶** blättern. In das Feld der Bildnummer kann eine laufende Nummer (z. B. 57) oder ein Aufnahmename (z. B. IMG_0018) eingetippt und mit Enter bestätigt werden.

### 5.2 Index anzeigen

- **Index** wählen. Verfügbar sind NDVI, NDRE, ReNDVI und GNDVI (Kernindizes der Arbeit) sowie BNDVI, SAVI, EVI, EVI2, VARI, NGRDI und GLI. Rechts stehen Formel und Quelle.
- **Farbskala:** „fest (je Index)“ für vergleichbare Darstellungen, „automatisch (P2–P98)“ für mehr Kontrast im einzelnen Bild.
- Graue Pixel in der Indexkarte sind ungültig (zu kleiner Nenner, negative Reflektanz) oder liegen außerhalb der Maske.

### 5.3 Maske wählen

- **Maske „Vegetation (NDVI ≥ Schwelle)“:** einfache Trennung von Vegetation und Boden. Trennt Bäume nicht von Gras.
- **Maske „Bäume (Modell)“:** Baumkronen über ein angelerntes Baummodell (Random Forest). Dafür zuerst ein Modell laden (**Modell laden …**) oder anlernen (5.4).
- **verfeinern:** zieht die Kronengrenzen am NIR-Kanal in voller Auflösung nach und entfernt dunkle Lücken (Boden, Schatten) zwischen den Kronen. Der Wert „Lücken < … % NIR“ legt fest, ab welcher Helligkeit (Anteil am 90. Perzentil der Maske) ein Pixel als Lücke gilt, Vorgabe 30 %.
- **Umriss im RGB:** zeigt die Maske als gelben Umriss im Echtfarbenbild.

### 5.4 Baummodell anlernen

1. 3–5 unterschiedliche Aufnahmen wählen (Bildmitte und -rand, Licht und Schatten, mit geschädigten Bäumen).
2. Zeichnen **„Beispiel: Baum“**: Kronen etwas innerhalb des Rands mit gedrückter linker Maustaste umfahren. Geschädigte Bäume bzw. Kronenteile bewusst einschließen.
3. Zeichnen **„Beispiel: kein Baum“**: alles umfahren, was nicht Baum ist (Gras, Boden, Schatten, Wege, Folie, Dächer).
4. Je Klasse etwa 10–20 Flächen, verteilt auf die Bilder. Unsichere Stellen weglassen. Eine falsche Fläche löschen: im Modus „Beispiel: Baum“ oder „Beispiel: kein Baum“ einmal in die Fläche **klicken** (ohne zu umfahren); **Letzte Fläche entfernen** löscht die zuletzt gezeichnete.
5. **Modell berechnen** und die Meldung prüfen (Trefferquote je Klasse, ausgewogene Genauigkeit). Dann in Bildern außerhalb des Trainings kontrollieren und Fehler mit neuen Flächen korrigieren.
6. **Modell speichern …** – die Datei `<Name>.joblib` und eine Beschreibung `<Name>_Info.json` werden angelegt.

Für Aufnahmen, die mit dem panchromatischen Kanal geschärft geladen werden (5.10), ist ein eigenes Modell nötig, weil sich die Pixelgröße ändert.

### 5.5 Bäume bewerten

1. Häkchen **„Schwellwerte für <Index>“** setzen. Die Schwellen gelten je Index.
2. **gestresst <** und **vital ≥** eintragen. Gleiche Werte ergeben zwei Klassen (empfohlen), verschiedene Werte drei Klassen mit „Übergang“ dazwischen. Die Schwellen lassen sich auch im Histogramm verschieben oder dort bzw. an der Farbskala anklicken und eintippen. Besser ist die Ableitung aus Referenzbäumen (5.7).
3. **Baumregel** wählen. Sie gilt ab Version 0.20.2 für **alle** Indizes mit Schwellen (die Statuszeile nennt die geänderten Indizes):
   - „Median je Baum“: Baum gestresst, wenn der Median seiner Indexwerte unter der Schwelle liegt (empfohlen).
   - „Anteil gestresster Pixel“: Baum gestresst, wenn mindestens „Baum gestresst ab … %“ seiner Pixel gestresst sind.
4. **Kronen trennen:** Abstand der Kronenmitten in Pixeln (0 = zusammenhängende Flächen bleiben ein Baum). **an NIR ausrichten** legt die Grenzen in dunkle Bereiche zwischen den Kronen.
5. **Pflanzraster:** schätzt je Bild den Pflanzverband (Reihen und Abstände) und setzt je Rasterpunkt eine Kronenmitte. Trennt auch Kronen, die sich ohne Schattenlinie berühren. Ist kein Raster erkennbar, gilt der Kronenabstand. Der erkannte Rasterabstand steht unter der Baumbewertung.
6. Ergebnis: Die Bäume werden im Echtfarbenbild in ihrer Klassenfarbe eingefärbt (rot gestresst, orange Übergang, grün vital) und in Leserichtung nummeriert. Rechts stehen Anzahl je Klasse und die Nummern der gestressten Bäume.

**Kronen von Hand korrigieren** (vorher „Bäume einfärben“ einschalten, damit die Kronengrenzen zu sehen sind):

- **Krone teilen:** Zeichnen **„Krone teilen“** und mit gedrückter linker Maustaste eine **Linie über die Stelle ziehen, an der zwei Kronen zusammengewachsen sind** – am besten von Hintergrund zu Hintergrund quer über die Verbindung (rote Schnittlinie). Die Krone wird entlang der Linie getrennt; die Pixel unter der Linie gehen danach an die nächstgelegene Krone zurück. Nur **klicken** (ohne Ziehen) setzt stattdessen eine zusätzliche Kronenmitte (weißes Kreuz) – dafür in die Mitte des Baums klicken, der keine eigene Krone hat, nicht auf die Berührungsstelle.
- **Kronen verbinden:** nacheinander in zwei Objekte klicken, die zu einem Baum gehören (weiße Verbindungslinie).
- **Korrektur löschen:** im Modus „Krone teilen“ oder „Kronen verbinden“ auf ein Kreuz oder eine Linie klicken. **↶ Kronenkorrektur** nimmt die letzte Korrektur zurück, **Korrekturen im Bild löschen …** alle Korrekturen des angezeigten Bildes (mit Rückfrage).

Die Korrekturen werden je Bild in `<Aufnahmeordner>\VI_Auswertung\Kronenkorrekturen.json` gespeichert und gelten auch für Export, Ordnerauswertung und Prüfung.

### 5.6 Referenzbäume einzeichnen

1. Maske wie in der späteren Auswertung einstellen (meist „Bäume (Modell)“, verfeinert).
2. Zeichnen **„Referenz: vital“** bzw. **„Referenz: geschädigt“** und sicher erkennbare Kronen umfahren. Bei aktiver Maske zählen nur Maskenpixel. **Falsch eingezeichnet** (z. B. als vital statt geschädigt)? Im Modus „Referenz: vital“ oder „Referenz: geschädigt“ einmal in den Referenzbaum **klicken** (ohne zu umfahren) – er wird gelöscht, egal welche Klasse er hat; danach richtig neu einzeichnen und die Referenzdatei erneut speichern. **Letzte Referenz entfernen** löscht den zuletzt gezeichneten.
3. Zwei getrennte Sammlungen anlegen und getrennt speichern (**Referenzen speichern …**):
   - **Ableitungsbäume** (Schwellen ableiten), je Set mindestens etwa 10 vitale und 10 geschädigte,
   - **Prüfbäume** (Kontrolle), je Set mindestens etwa 8 + 8, andere Bäume als bei der Ableitung.
4. Bäume aus mehreren Bildern wählen. Derselbe Baum darf nicht in beiden Sammlungen vorkommen – auch nicht in einem überlappenden Nachbarbild oder in einem zweiten Flug über dieselbe Fläche (z. B. 0026SET und 0028SET).
   **Hilfe beim Einzeichnen der Prüfbäume:** **Ableitung hinterlegen …** (Zeile Referenzbäume) und die Datei(en) der Ableitungsbäume wählen. Die hinterlegten Bäume werden nicht verändert, sondern in jedem angezeigten Bild **weiß gestrichelt** eingeblendet (Beschriftung „A·V3“, „A·G4“) – auch wenn sie in einem anderen, überlappenden Bild oder Set eingezeichnet wurden. Zusätzlich erscheinen die eigenen Referenzen aus Nachbarbildern farbig gestrichelt mit Stern („V3*“), damit kein Prüfbaum doppelt eingezeichnet wird. Wird ein neuer Baum auf einen eingeblendeten gezeichnet, fragt die Software nach, ob er trotzdem behalten werden soll. Häkchen **einblenden** schaltet die Anzeige aus und ein. Das Übertragen dauert beim ersten Mal je Nachbarbild einige Sekunden (Statuszeile); Nachbarbilder, die sich nicht abgleichen lassen, nennt die Statuszeile – dort selbst vergleichen. Die Hinterlegung bleibt beim nächsten Start erhalten; erneutes **Ableitung hinterlegen …** → „Nein“ entfernt sie.
5. **Referenzen hinzuladen …** fügt weitere Dateien hinzu (z. B. aus mehreren Ordnern); **Referenzen laden …** ersetzt die aktuelle Sammlung.

Woran „vital“ und „geschädigt“ erkannt wurden, sollte notiert werden.

### 5.7 Schwellen aus Referenzbäumen ableiten

1. Ableitungsbäume laden, **Schwellen aus Referenzen …** öffnen. Die Tabelle zeigt je Index die Trennschärfe auf Pixelebene (AUC) und die Youden-Schwelle.
2. **Empfohlen: „Baumebene: Schwellen aus Baummedianen …“.** Jede Referenzfläche wird dem Baum mit der größten Überdeckung zugeordnet (gleiche Maske und Kronentrennung wie in der Auswertung), aus den Baummedianen wird je Index die Youden-Schwelle berechnet. Das Ergebnisfenster zeigt Schwelle, J (1 = alle Ableitungsbäume getrennt), AUC und die Spannweiten der Baummediane.
3. **Für ausgewählten Index übernehmen** bzw. **Für alle Indizes übernehmen.** Die Schwellen werden mit Herkunft gespeichert (2 Klassen, Baumregel „Median je Baum“). Mit **Tabelle als CSV speichern …** werden sie dokumentiert.

**Achtung:** Die Knöpfe unten im Fenster „Schwellen aus Referenzen“ übernehmen **Pixelschwellen**. Für die Baumregel „Median je Baum“ passen die Schwellen aus **„Baumebene: Schwellen aus Baummedianen …“** (Punkt 2). Die Prüfung an Prüfbäumen weist darauf hin, wenn Pixelschwellen verwendet werden oder die Baumregeln je Index verschieden sind.

Alternativ übernimmt das Fenster „Schwellen aus Referenzen“ selbst Pixelschwellen nach Schema „2 Klassen (Youden-Schwelle)“ oder „3 Klassen“ (gestresst < 5. Perzentil der vitalen, vital ≥ 95. Perzentil der geschädigten Pixel).

### 5.8 Schwellen an Prüfbäumen prüfen

1. Schwellen wie in 5.7 festlegen, Maske und Kronentrennung wie in der Auswertung einstellen.
2. **An Prüfbäumen prüfen …** und die Datei(en) der Prüfbäume wählen. Vor dem Start gleicht die Software die Prüfbäume mit den Ableitungsbäumen ab (hinterlegte Ableitung, sonst die geladenen Referenzen) – auch über überlappende Bilder und Sets hinweg – und sucht doppelt eingezeichnete Prüfbäume. Als **sicher derselbe Baum** gilt eine Überdeckung von mindestens 50 % nach dem Übertragen; Treffer mit 30–50 % werden als **fraglich** gemeldet (oft der Nachbarbaum, weil sich die Kronenspitzen zwischen zwei Blickwinkeln verschieben) – diese selbst vergleichen, sie werden nicht ausgeschlossen. Werden sichere Dopplungen gefunden, werden sie aufgelistet: **Ja** schließt die doppelten Prüfbäume aus, **Nein** prüft alle (Ergebnis dann zu optimistisch), **Abbrechen** prüft nicht. Ausgeschlossene Bäume stehen im Ergebnisfenster und im Protokoll.
3. Ergebnis je Index: richtige, „Übergang“ und falsche vitale bzw. geschädigte Prüfbäume, „kein Baum“ (Fläche außerhalb der Maske), Trefferquote und ausgewogene Trefferquote. Ein Doppelklick auf eine Zeile der Tabelle je Prüffläche (oder **Ausgewähltes Bild öffnen**) zeigt das Bild mit dem Index. Speichern als CSV mit Protokoll.

### 5.9 Kanalanalyse

**Kanalanalyse …** (Zeile Referenzbäume) wertet die geladenen Referenzbäume aus. Ältere Referenzdateien ohne Kanalwerte werden vorher aus den Bildern ergänzt (Maske wie beim Einzeichnen wählen; danach Referenzen speichern). Fünf Reiter:

- **Trennung je Kanal/Index:** Abstand vital − geschädigt in Einheiten der Streuung innerhalb eines Baums, Cohens d und AUC auf Baumebene, ICC (Anteil der Streuung zwischen den Bäumen).
- **Korrelation der Kanäle:** je Pixel und zwischen Baummittelwerten.
- **PCA:** erklärte Varianz und Ladungen der Hauptkomponenten.
- **Kanalsätze:** RGB, RGB+NIR, „ohne Blau“ (Grün, Rot, Red Edge, NIR – Kanäle wie bei der DJI Mavic 3M, als Näherung) und alle 5 Kanäle – wie gut die weggelassenen Kanäle vorhersagbar sind (R²) und wie gut die Kanalsätze vital und geschädigt trennen (lineare Diskriminanzanalyse mit Auslassen je Baum, k-means).

- **Rechenaufwand:** erst nach **Rechenaufwand messen …** (unten im Fenster). Je Kanalsatz: Datenmenge der Rohdateien und des Reflektanzstapels je Aufnahme, Vorverarbeitungszeit je Aufnahme (je Set wird eine Aufnahme aus den Rohbildern geladen und die Zeit je Kanal gemessen; Wert je Kanalsatz hochgerechnet) sowie Trefferquote, Trainingszeit und Vorhersagezeit je 1 Mio. Pixel eines Random Forest (Einstellungen wie das Baummodell) und der LDA, geprüft über ganze Bäume. Die Messung läuft im Hintergrund (bei 30 Bäumen etwa 2 Minuten) und kann mit **Abbrechen** beendet werden. Währenddessen keine anderen rechenintensiven Programme nutzen, sonst sind die Zeiten zu hoch. Die Zeiten gelten für den verwendeten Rechner (steht im Protokoll); für den Vergleich der Kanalsätze zählen die Verhältnisse.

Die Gruppe „alle“ oder ein einzelnes Set wählen (Vergleiche möglichst innerhalb eines Flugs). **Als CSV speichern …** schreibt vier Tabellen und ein Protokoll, nach einer Messung zusätzlich `_Rechenaufwand.csv`, `_Vorverarbeitung.csv` und `_Rechenaufwand_Parameter.json`.

### 5.10 Panchromatischer Kanal

Nur für Aufnahmen mit sechster Datei: **Kanäle „6 Kanäle (mit Panchro)“**, **Panchro schärfen** und **nur Kronen** anhaken. Die Aufnahme wird dann im doppelt so feinen Raster geladen: Maske, Kronentrennung und Anzeige nutzen das geschärfte Bild, Indizes und Statistik die unveränderten Spektralkanäle. Ohne „nur Kronen“ werden auch die Indizes aus den geschärften Kanälen berechnet (verändert die Spektralwerte). Pixelangaben (z. B. Kronenabstand) gelten im feinen Raster doppelt.

### 5.11 Einzelne Aufnahme exportieren

- **ROI (Rechteck):** Rechtecke in Echtfarbenbild oder Indexkarte aufziehen. Sie erscheinen als eigene Regionen in der Statistik (auch geschnitten mit der Maske). **ROIs löschen** entfernt sie.
- **Exportieren** schreibt nach `<Aufnahmeordner>\VI_Auswertung\IMG_XXXX\` die Indexraster, die Maske, die Statistik aller Indizes und Regionen, bei Schwellen die Klassenbilder und eine Tabelle je Baum, die aktuelle Ansicht als Bild und das Parameterprotokoll. **ROI-Pixelwerte mit exportieren** schreibt zusätzlich alle Pixelwerte der ROIs.

### 5.12 Ganzen Ordner auswerten

1. Maske und Schwellen (eingeschaltet) wie gewünscht einstellen.
2. **Ordner auswerten …** und einen Ordner wählen (auch übergeordnet). Die Software zeigt Anzahl, Datenquelle und geschätzte Dauer (etwa 4,5 s je Aufnahme aus Rohbildern).
3. Ergebnis in `<Ordner>\VI_Auswertung\`: `Ordnerauswertung_<Datum_Uhrzeit>.csv` (je Aufnahme, Index und Region Aufnahmezeit, GPS-Position, Statistik und bei Schwellen die Bewertung) und `…_Parameter.json`. **Indexraster speichern** legt zusätzlich die Raster eines Index je Aufnahme ab. **Abbrechen** hinterlässt eine gültige Teilauswertung.

## 6. Empfohlener Ablauf für ein neues Set

1. Ordner öffnen, einige Bilder sichten (Maske „keine“, Index NDVI).
2. Baummodell laden oder anlernen (5.4), Maske „Bäume (Modell)“ mit „verfeinern“.
3. Schwellwerte einschalten, **Pflanzraster** an, Baumregel „Median je Baum“; Kronen prüfen und von Hand korrigieren (5.5).
4. Ableitungs- und Prüfbäume einzeichnen und getrennt speichern (5.6).
5. Ableitungsbäume laden → Schwellen aus Baummedianen ableiten und übernehmen (5.7).
6. Schwellen an den Prüfbäumen prüfen (5.8). Den Index nach den Ableitungsbäumen bzw. der Kreuzvalidierung wählen, nicht nach dem Ergebnis an den Prüfbäumen, da dieses sonst zu günstig ausfällt.
7. Optional: Kanalanalyse mit allen Referenzbäumen (5.9).
8. Ordner auswerten (5.12). Protokolle und CSV-Dateien aufbewahren.

## 7. Ausgabedateien

| Datei | Ort | Inhalt |
|---|---|---|
| `Ausrichtung.json`, `Ausrichtung_Panchro.json` | `<Aufnahmeordner>\VI_Auswertung\` | Kanalausrichtung je Ordner |
| `Kronenkorrekturen.json` | `<Aufnahmeordner>\VI_Auswertung\` | Korrekturen der Kronentrennung von Hand, je Aufnahme |
| `IMG_XXXX_<Index>.tif` | Export | Indexraster (Gleitkomma, ungültig = NaN) |
| `IMG_XXXX_Maske_<Art>.tif` | Export | Maske (1 = Baum bzw. Vegetation) |
| `IMG_XXXX_Statistik.csv` | Export | Statistik je Index und Region, mit Klassenanteilen |
| `IMG_XXXX_<Index>_Klassen.tif`, `_Baumklassen.tif` | Export | Klasse je Pixel bzw. je Baum (0 gestresst, 1 Übergang, 2 vital, 255 ungültig) |
| `IMG_XXXX_<Index>_Objekte.csv` | Export | je Baum Nummer, Fläche, Lage, Mittel, Median, Klassenanteile, Klasse |
| `IMG_XXXX_<Index>_Ansicht.png`, `IMG_XXXX_Parameter.json` | Export | Ansicht und Protokoll aller Einstellungen |
| `Ordnerauswertung_<Zeit>.csv` + `_Parameter.json` | `<Ordner>\VI_Auswertung\` | Ergebnis der Ordnerauswertung |
| `<Name>.joblib`, `<Name>_Info.json` | frei wählbar | Baummodell bzw. Referenzbäume |
| `Pruefung_Schwellen.csv`, `Schwellen_Baummediane.csv`, `Kanalanalyse_*.csv` | frei wählbar | Prüfung, Baumschwellen, Kanalanalyse (je mit `_Parameter.json`) |

CSV-Dateien sind mit Semikolon getrennt und UTF-8-kodiert (lassen sich in Excel öffnen).

## 8. Arbeitsstand und Zurücksetzen

Beim Schließen des Fensters merkt sich die Software den Arbeitsstand: Ordner und Aufnahme, alle Einstellungen, Schwellen je Index sowie Baummodell und Referenzbäume (als Sicherungskopie im Ordner `Sitzung` neben dem Programm). Beim nächsten Start wird er wiederhergestellt. **Alles zurücksetzen …** verwirft diesen Arbeitsstand und startet leer; selbst gespeicherte Modell- und Referenzdateien, Exporte und Kronenkorrekturen bleiben erhalten.

## 9. Hinweise und Grenzen

- **Kalibrierung nur über den DLS 2:** Absolute Reflektanzwerte sind unsicher, Vergleiche innerhalb eines Flugs sind belastbarer als zwischen Flugtagen. Für künftige Flüge Aufnahmen des Kalibrierpanels vor und nach jedem Flug.
- **Sonnenstand und Schatten** beeinflussen die Werte. Schwellen und Vergleiche möglichst je Flug.
- **Einzelaufnahmen** sind nicht georeferenziert. Derselbe Baum kann in überlappenden Bildern mehrfach vorkommen.
- **Baummodell und Kronentrennung** sind nicht fehlerfrei; die Ergebnisse visuell prüfen und Kronen bei Bedarf korrigieren.
- Kleine Referenzstichproben ergeben unsichere Schwellen und Trefferquoten.

## 10. Häufige Probleme

| Meldung / Problem | Lösung |
|---|---|
| „keine passenden Aufnahmen gefunden“ | Kanalzahl prüfen (z. B. „6 Kanäle“ bei Sets mit Panchro) |
| fehlende DLS-Daten | Set ohne Sonnenlichtsensor-Werte, keine Reflektanz berechenbar |
| „Vorverarbeitungsskript nicht gefunden“ | `multispektral_stapeln.py` neben `vi_kern.py` legen |
| Bäume werden nicht angezeigt | Maske wählen und Schwellwerte für den Index einschalten |
| Baummodell passt nicht | Modell wurde an geschärften bzw. ungeschärften Bildern angelernt – passendes Modell laden |
| Programm reagiert langsam | Erstes Öffnen eines Ordners schätzt die Ausrichtung (einmalig etwa 2 min) |
| Einstellungen sollen weg | **Alles zurücksetzen …** |
| `ModuleNotFoundError: No module named …` beim Start | Paket fehlt: `pip install -r requirements.txt` im Programmordner ausführen |
| Doppelklick auf die `.bat` öffnet kurz ein Fenster und schließt es | Python ist nicht installiert oder nicht im Suchpfad; Python installieren (Option „Add Python to PATH“) |
| Knöpfe am rechten Rand fehlen | Fenster maximieren bzw. größeren Bildschirm verwenden (mind. ca. 1400 Pixel Breite) |
| Fehlermeldung beim Speichern, Arbeitsstand wird nicht gemerkt | keine Schreibrechte im Programm- oder Datenordner (z. B. CD, schreibgeschützter Stick) – Ordner auf die Festplatte kopieren |

Programmierung: Claude Code (Anthropic) nach Vorgaben des Verfassers; technische Dokumentation der Entscheidungen und Tests: `Dokumentation_VI_Auswertung.md`.
