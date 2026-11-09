# WildGuard

Early warning for human-wildlife conflict. It takes camera-trap images, GPS collar fixes and ground-sensor readings, predicts where an elephant or leopard is heading, and sends tiered alerts to villages in English and Tamil.

**Status: working prototype.** The ingestion, prediction, risk scoring, alert tiers, de-duplication, ranger verification, risk zones and evaluation are real logic, covered by 63 automated tests. The dashboard fills with simulated data on first run. Not yet tried against real hardware, real YOLO inference, live SMS/voice providers or real animal data (see Known limits).

## How it works

1. **Input** arrives from any of these. All of them go through the same analysis.
   - a camera-trap image (YOLO on the server) or a detection sent by an edge camera
   - GPS collar fixes
   - ground sensors (seismic, acoustic, PIR)
   - LoRa/LoRaWAN uplinks (compact binary frames)
   - the Simulation Lab and demo scenarios
2. A **Kalman filter** smooths the track and estimates speed and heading. If the path enters a village's threat radius (elephant 0.5 km, leopard 0.4 km) within 3 hours, the ETA is computed from the geometry.
3. **Sensor fusion** adds ground readings within 1 km and 10 minutes of the animal.
4. A **risk score** (0-100) combines proximity, confidence, sensor activity, recent sightings, night-time and whether the animal is heading in. Elephants and leopards have separate profiles.
5. The alert tier is **Watch**, **Warning** or **Imminent**, from risk level and ETA.
6. Detections under 85% confidence wait for a **ranger to confirm** before anything is sent.
7. Repeat alerts for the same village and species within 30 minutes are **suppressed** at the same or a lower tier (alert-fatigue guard).
8. An **Isolation Forest** per species flags unusual movement.
9. A **risk-zone grid** shows where conflict is most likely (a transparent heuristic, not a trained model).
10. The **Evaluation** page compares alerts with logged incidents: precision, recall, lead time and false alarms per week.

## Run it

Backend, in one terminal (Windows PowerShell):

```powershell
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Frontend, in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. API docs are at http://127.0.0.1:8000/docs.

On macOS/Linux use `source venv/bin/activate` and `cp` instead.

The first start creates `backend/data/` and seeds it. Delete that folder to reset.

### Ranger sign-in

Reading is open. Anything that changes state (simulate, confirm or reject an alert, add subscribers, register devices, log incidents, run demo scenarios) needs the admin token, which the dashboard asks for.

- Set `WILDGUARD_ADMIN_TOKEN` in `backend/.env`, or leave it empty.
- If empty, the first start creates a random token in `backend/data/admin_token.txt`.

### Try it in two minutes

1. Sign in with the admin token.
2. Open **Simulation Lab** and start a scenario. Choose "mixed", which runs approaching, veering and loitering animals through the real pipeline.
3. Watch **Live Feed**, **Movement Map** and **Alerts** update on their own.
4. Open **Evaluation** to see precision, lead time and false alarms per week.

## Connecting real devices

Register a device (Devices page, or `POST /api/devices`). Its API key is shown once and only a hash is stored. Then:

| Device | Route | Header |
|---|---|---|
| Camera image | `POST /api/ingest/camera` (multipart) | `X-API-Key` |
| Edge camera detection | `POST /api/ingest/detection` | `X-API-Key` |
| GPS collar | `POST /api/ingest/gps` | `X-API-Key` |
| Ground sensor | `POST /api/ingest/sensor` | `X-API-Key` |
| LoRaWAN network server | `POST /api/ingest/lora` | `X-Gateway-Key` |

Each route accepts only its own device kind. LoRa is off until `WILDGUARD_GATEWAY_KEY` is set.

Server-side camera detection needs `pip install -r requirements-ml.txt`. Without it, send a `species` label with the image or run the model on the camera.

## Alerts

`NOTIFY_PROVIDER=dry_run` and `VOICE_PROVIDER=dry_run` (the defaults) record each message without contacting anyone. Seeded subscriber numbers are placeholders that cannot reach a real phone.

- **SMS:** `fast2sms` or `twilio`, for every subscriber of the village.
- **Voice:** `twilio`, for subscribers who opted in, at Warning and Imminent only.
- **Beacon:** `BEACON_WEBHOOK_URL` receives a JSON POST for a siren or LED, at Warning and Imminent only.

**The live providers have not been tested against the real services.** In India, bulk SMS usually needs DLT-registered sender IDs and templates, and Tamil text-to-speech support differs by provider, so check each provider's current docs and try your own number first. Have a Tamil speaker review the Tamil wording in `notify.py` before real use.

## Tests

```powershell
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
```

## Project layout

```
backend/app/
  main.py        routes only
  config.py      villages, cameras, thresholds, species profiles, env
  geo.py         distance, bearing, projection
  predictor.py   Kalman filter, ETA to village
  risk.py        risk score, alert tiers
  anomaly.py     Isolation Forest
  fusion.py      combine ground readings with a track
  pipeline.py    shared analysis for every input path
  ingest.py      camera, collar, sensor and detection ingestion
  lora.py        binary LoRa frames
  detector.py    optional YOLO
  notify.py      EN/TA messages, dedup, SMS / voice / beacon
  riskzones.py   risk-zone grid
  evaluation.py  precision, recall, lead time, false alarms per week
  scenario.py    scripted demo movements
  service.py     simulator and ranger verification
  auth.py        admin token and device keys
  db.py, bus.py, schemas.py, sensors.py, seed.py
backend/tests/   63 tests
frontend/src/    api.js, hooks/, components/, pages/, styles/
```

## Known limits

- Everything on the dashboard at first run is simulated. Replace those inputs with real feeds (Movebank GPS, LILA BC camera-trap data) before drawing conclusions.
- The LoRa frame format is this project's own. Check it against your node firmware. It has not been tested on real LoRa hardware.
- YOLO inference is untested here. The stock COCO model knows elephants but not leopards, so a leopard model needs training or downloading.
- The Kalman filter assumes roughly constant velocity over a few minutes. It does not model terrain, fences or water.
- Risk weights, tier thresholds and the risk-zone grid are hand-set heuristics. Tune them against real incident records.
- The Isolation Forest learns from synthetic history until real data replaces it.
- Evaluation numbers on the demo data only show the pipeline works. They say nothing about real-world accuracy.
- Access control is a shared admin token and per-device keys. Put the API behind HTTPS before exposing it beyond your own network.
