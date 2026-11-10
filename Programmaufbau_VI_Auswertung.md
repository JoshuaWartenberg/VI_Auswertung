# Aufbau und Programmcode der Software VI-Auswertung

## 1. Überblick

Die Software ist in Python geschrieben und in zwei Teile gegliedert: einen Rechenkern ohne Oberfläche (`vi_kern.py`) und die Oberfläche (`vi_auswertung.py`, Tkinter und matplotlib). Die radiometrische Korrektur, Entzerrung und Kanalausrichtung werden nicht neu programmiert, sondern aus dem zuvor geprüften Vorverarbeitungsskript `multispektral_stapeln.py` übernommen; Software und Skript liefern dadurch identische Reflektanzen. Der Rechenkern lässt sich auch ohne Oberfläche verwenden, z. B. `a = vi_kern.lade_aufnahme(ordner, "IMG_0100")` und `vi_kern.berechne_index(a.stapel, a.kanalindex, "NDVI")`.

## 2. Verarbeitungskette und zentrale Funktionen

| Schritt | Funktion(en) in `vi_kern.py` | Inhalt |
|---|---|---|
| Aufnahmen finden | `liste_aufnahmen_rekursiv`, `rohaufnahmen` | Rohbilder je Aufnahme, Kanalzuordnung aus den Metadaten |
| Laden und Vorverarbeiten | `lade_aufnahme`, `ausrichtung_fuer_ordner`, `stapelmodul` | Rohwert → Strahldichte → Reflektanz (DLS 2), Entzerrung, Ausrichtung auf Red Edge (ECC-Homographie, je Ordner geschätzt) |
| Panchromatischer Kanal | `schaerfen_sfim`, `pan_feinausrichtung` | Schärfung nach SFIM; bei „nur Kronen“ nur für Maske und Kronen, Indizes aus den Original-Kanälen |
| Vegetationsindizes | `INDIZES`, `berechne_index` | 11 Indizes als Quotienten, Maskierung ungültiger Pixel |
| Masken | `vegetationsmaske`, `Baummodell`, `baum_merkmale`, `verfeinere_maske`, `Maskenvorgabe` | NDVI-Schwelle oder Random-Forest-Baummaske mit Textur- und Umgebungsmerkmalen, Verfeinerung am NIR |
| Kronentrennung | `objekt_labels`, `schaetze_pflanzraster`, `lade_kronenkorrekturen` | Wasserscheide auf „Kronenhöhe“ (Randabstand + NIR), Kronenmitten aus dem Pflanzraster (Autokorrelation), Korrekturen von Hand (Schnittlinie, Kronenmitte, Verbinden) |
| Bewertung je Baum | `Schwellen`, `klassifiziere`, `bewerte_objekte` | Pixelklassen, Baumregel „Median je Baum“ oder „Anteil gestresster Pixel“, Nummerierung in Leserichtung |
| Referenzbäume | `Referenzen` (`auswerten`, `schwellen`) | Trennschärfe (AUC), Youden-Schwelle auf Pixelebene |
| Schwellen auf Baumebene | `baum_schwellen` | Youden-Schwelle aus den Baummedianen der Ableitungsbäume |
| Prüfung | `pruefe_schwellen` | Bewertung getrennter Prüfbäume mit Maske, Kronentrennung und Schwellen der Auswertung |
| Abgleich über Bilder | `flaechen_uebertragen`, `referenz_dopplungen`, `umrisse_gleicher_baum` | Referenzbäume per GPS-Nähe und Bildmerkmalen (SIFT, Homographie) in andere Aufnahmen übertragen; doppelte Ableitungs-/Prüfbäume finden |
| Kanalanalyse | `kanalanalyse`, `ergaenze_kanalwerte` | ICC, Abstand, Cohens d, AUC; Korrelation, PCA; Kanalsätze RGB / RGB+NIR / ohne Blau / alle 5 (R², LDA, k-means) |
| Rechenaufwand | `rechenaufwand`, `rechenaufwand_als_csv` | Datenmenge, Vorverarbeitungszeit je Kanal, Random Forest und LDA je Kanalsatz (Trefferquote, Trainings- und Vorhersagezeit, ein Rechenkern) |
| Ausgabe | `exportiere`, `werte_ordner_aus`, `*_als_csv` | Raster, Statistik, Tabellen je Baum, Ordnerauswertung, Parameterprotokolle |

Die Oberfläche (`vi_auswertung.py`, Klasse `App`) ruft diese Funktionen auf, zeigt Bilder, Karten, Histogramme und Tabellen an, nimmt Zeichnungen (ROIs, Trainings-, Referenzflächen, Kronenkorrekturen) entgegen, führt lange Rechnungen im Hintergrund aus und speichert den Arbeitsstand.

## 3. Abhängigkeiten

Python 3 (getestet 3.14), numpy, opencv-python, tifffile, imagecodecs, matplotlib, scikit-learn, scipy, joblib; Tkinter (in Python enthalten).

## 4. Digitaler Anhang

Der vollständige Programmcode liegt der Arbeit als digitaler Anhang bei (Ordner bzw. ZIP-Archiv `Digitaler_Anhang`). Er enthält die unten aufgeführten Programmdateien, die Startdatei, eine Paketliste (`requirements.txt`), diese Bedienungsanleitung und die technische Dokumentation mit den Entwicklungsentscheidungen und Testergebnissen. Die Prüfsummen (SHA-256, erste 16 Zeichen) belegen, dass die Dateien dem hier beschriebenen Stand entsprechen.

Die Software wurde mit dem KI-Werkzeug Claude Code nach Vorgaben des Verfassers programmiert und von ihm getestet (vgl. Anhang A1).
