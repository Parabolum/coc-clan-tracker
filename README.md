# CoC Clan Tracker

Ein Clan-Punktetracker mit periodischem Import aus der offiziellen Supercell-API. Lokal lässt er sich mit Python starten oder auf einem Linux-Server mit Docker Compose samt HTTPS-Reverse-Proxy betreiben.

## Linux-Server mit Docker Compose

Voraussetzungen: Docker Engine mit Docker Compose Plugin. Docker startet nur den Tracker; der Webserver oder Reverse-Proxy wird separat eingerichtet, wenn du die Seite öffentlich bereitstellen möchtest.

1. Nur `compose.yaml` und eine neu erstellte `.env` auf den Server kopieren. `.env.example` aus dem Repository kannst du als Vorlage verwenden; benenne die Kopie auf dem Server in `.env` um.
2. In `.env` `CLAN_TAG`, `COC_API_TOKEN` und ein starkes `ADMIN_PASSWORD` eintragen. Optional `SUPPORT_DISCORD` mit dem Discord-Namen für den Website-Kontakt setzen. Diesen Wert nur auf dem Server in `.env` eintragen, nicht ins Repository. Den API-Schlüssel ebenfalls nicht ins Repository kopieren. Die öffentliche ausgehende IP des Servers muss im Supercell Developer Portal für den API-Schlüssel freigegeben sein.
3. Wenn du den Tracker später öffentlich freigibst, richte Domain, DNS, HTTPS und Reverse-Proxy separat ein. Der Container-Port ist standardmäßig nur auf `127.0.0.1:8001` des Servers erreichbar.
4. Im Ordner mit diesen beiden Dateien starten:

   ```sh
   docker compose up -d
   ```

Compose lädt dabei das veröffentlichte Image aus der GitHub Container Registry (GHCR) und startet den Tracker im Hintergrund. Der Container startet automatisch nach einem Serverneustart. Auf dem Server erreichst du ihn lokal unter `http://127.0.0.1:8001`; für einen Reverse-Proxy kannst du dorthin weiterleiten. Die SQLite-Datei bleibt im Docker-Volume `tracker_data` erhalten.

Nützliche Befehle:

```sh
docker compose ps
docker compose logs -f tracker
docker compose pull
docker compose up -d
```

Wenn du später einen Reverse-Proxy installierst, leite die Domain auf `127.0.0.1:8001` weiter. Bei Caddy wäre das im Caddyfile zum Beispiel `tracker.example.com { reverse_proxy 127.0.0.1:8001 }`; DNS sowie öffentliche Erreichbarkeit der benötigten Ports müssen dann passend eingerichtet werden.

## Starten

1. Python 3.11+ installieren.
2. Im Projektordner ausführen:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env
   uvicorn app.main:app --reload
   ```

3. `http://127.0.0.1:8001` öffnen.

Die Admin-Seite erreichst du über `http://127.0.0.1:8001/admin`. Vor der ersten Anmeldung in `.env` `ADMIN_USERNAME` und ein eigenes starkes `ADMIN_PASSWORD` setzen. Die Beispielwerte aus `.env.example` sind Platzhalter und müssen ersetzt werden.

Für echte Daten `CLAN_TAG` und `COC_API_TOKEN` in `.env` eintragen. Den API-Token niemals in den Browser-Code oder ein öffentliches Repository schreiben. API-Tokens werden im Supercell Developer Portal erstellt; dort muss die Server-IP für den Token zugelassen sein.

## Funktionen

- responsives Dashboard mit Rangliste, Ereignisübersicht und Punktestand pro Spieler
- FastAPI-Backend und SQLite-Speicher für Spieler sowie nachvollziehbare Punktebuchungen
- konfigurierbare Beispielregeln in `app/scoring.py`
- serverseitige CoC-API-Anbindung mit automatischer Synchronisierung (standardmäßig alle 5 Minuten)
- geschützte Admin-Seite für manuelle Punktebuchungen, getrennte Aktivitätsprotokolle, Mitgliederstatus, Abwesenheiten und Kommentare

## Datenabdeckung

Der Importjob synchronisiert Mitglieder und Spenden, erfasst laufende Kriege und verbucht deren Spielergebnisse nach Kriegsende. CWL-Kriege werden über die War-Tags der aktuellen CWL-Gruppe ermittelt und nach Abschluss verbucht. Raid-Saisons werden importiert und Spielerangriffe nach Saisonabschluss mit der einstellbaren Regel in `app/scoring.py` bewertet. Ereignisse und Punktebuchungen werden dedupliziert.

Die offiziellen Raid-Saisonwerte enthalten Angriffe, persönliche Angriffsgrenze und Bonusangriffsgrenze. Entsprechend der Tabelle gibt es -1 bei null Angriffen, +1 bei allen möglichen Angriffen und 0 bei teilweise genutzten Angriffen. Clan-Spiele werden indirekt über den kumulativen „Games Champion“-Erfolgswert der Spielerprofile erfasst: Der Tracker speichert einen Monats-Ausgangswert und vergleicht ihn nach Monatsende mit dem neuen Wert. Der Zähler wird als Fortschrittswert ausgelesen. Ergebnisse werden nur für aktuell bestätigte Clanmitglieder verbucht. Neue Mitglieder erhalten beim Beitritt einen eigenen Ausgangswert; wenn sie im gewerteten Monat beigetreten sind und 0 Punkte erzielt haben, erhalten sie keinen Malus. Der Dienst muss für einen gültigen Monats-Ausgangswert spätestens vor Monatsmitte laufen; fehlt ein rechtzeitiger Ausgangswert, wird für das Mitglied kein automatischer Clan-Spiele-Eintrag erzeugt, statt einen falschen Malus zu vergeben. Der Endstand wird ab dem 3. des Folgemonats abgerufen, damit die API Zeit hat, den letzten Fortschritt zu veröffentlichen.

Die Punktregeln: CK 2 Angriffe +1, 1 Angriff 0, 0 Angriffe bei Teilnahme -2; CWL -4 je vergessenem Angriff und ein einmaliger Saisonbonus nach Gesamtsternen (14–17: +1, 18–20: +2, 21: +4); Spenden +1 je 1.000; Clan-Spiele 10.000+ Punkte +3, 4.000–9.999 +1, 1–3.999 0 und 0 Punkte -3 (außer bei Beitritt im gewerteten Monat: 0 Punkte); Inaktivität ab 7 Tagen ohne jegliche Aktivität (Clankrieg, CWL, Raids, Spenden, Clan-Spiele, XP oder Spielfortschritt) -1 Punkt pro Tag (außer bei eingetragener Abmeldung).

## API

- `GET /api/health` – Status
- `GET /api/dashboard` – Rangliste und letzte Buchungen
- `GET /api/members/{player_tag}` – Punktebuchungen für einen Spieler
- `/admin` – Admin-Oberfläche (HTTP-Basic-Anmeldung aus `.env`)
- `POST /api/admin/adjustments` – geschützte manuelle Punktebuchung
- `POST /api/admin/sync` – geschützte sofortige Synchronisierung
- `GET /docs` – interaktive API-Dokumentation
