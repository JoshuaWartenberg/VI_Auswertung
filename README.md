# VI-Auswertung

Software zur Bachelorarbeit **„Auswahl und Evaluierung geeigneter Spektralkanäle zur KI-gestützten Vitalitätsanalyse im Weihnachtsbaumanbau“** (Joshua Wartenberg, Fachhochschule Westküste, 2026).

Die Software verarbeitet Multispektralaufnahmen einer Drohne (DJI Mavic 3M) zu Reflektanzbildern, berechnet Vegetationsindizes und vergleicht deren Eignung zur Unterscheidung vitaler und geschädigter Bäume anhand eingezeichneter Referenzflächen.

Dieses Repository enthält dieselbe Version wie der digitale Anhang der Arbeit (Version 0.20.3).

## Dateien

| Datei | Inhalt |
|---|---|
| `vi_auswertung.py` | Oberfläche (Tkinter, matplotlib) |
| `vi_kern.py` | Rechenkern ohne Oberfläche |
| `multispektral_stapeln.py` | Vorverarbeitung: Radiometrie (DLS 2), Entzerrung, Kanalausrichtung |
| `VI_Auswertung starten.bat` | Start per Doppelklick (Windows) |
| `Bedienungsanleitung_VI_Auswertung.md` | Bedienung |
| `Programmaufbau_VI_Auswertung.md` | Aufbau des Programms |
| `Dokumentation_VI_Auswertung.md` | Technische Dokumentation (Entscheidungen, Formeln, Testergebnisse je Version) |

## Start

```
pip install -r requirements.txt
python vi_auswertung.py
```

Unter Windows alternativ Doppelklick auf `VI_Auswertung starten.bat`. Die Bedienung ist in `Bedienungsanleitung_VI_Auswertung.md` beschrieben.

Die in den Skripten eingetragenen Ordnerpfade beziehen sich auf den Rechner des Verfassers. Fehlen sie, beginnt die Ordnerauswahl im Benutzerordner und `multispektral_stapeln.py` wird neben `vi_kern.py` gesucht.

Die Drohnenaufnahmen und Referenzdaten der Arbeit sind nicht Teil dieses Repositorys.

## Nutzung

Alle Rechte vorbehalten. Der Code ist zur Nachvollziehbarkeit der Bachelorarbeit öffentlich einsehbar. Eine Nutzung, Veränderung oder Weitergabe ist nur nach Absprache mit dem Verfasser gestattet.
