import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, auth } from "../api";
import FeedList from "../components/FeedList";
import { PageHeader, Panel, Pill } from "../components/small";
import { summarize } from "../utils";

const SENSOR_KINDS = [
  ["seismic", "Seismic (mm/s)", "0.8"],
  ["acoustic", "Acoustic (dB)", "72"],
  ["pir", "PIR motion (1 = triggered)", "1"],
  ["fence", "Fence break (1 = broken)", "1"]
];

const devicesOfKind = (data, kind) => data.sensors.sensors.filter((d) => d.kind === kind);
const isImage = (file) => file.type.startsWith("image/");

/** "id,species,timestamp,lat,lon" lines (header optional) -> GPS fixes. Returns {fixes, problems}. */
function parseCsv(text) {
  const fixes = [];
  const problems = [];
  text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line, i) => {
      const cells = line.split(",").map((c) => c.trim());
      if (i === 0 && /animal|species|lat/i.test(line) && Number.isNaN(Number(cells[cells.length - 1]))) return;
      if (cells.length < 4) {
        problems.push(`Line ${i + 1}: expected animal_id,species,[timestamp,]lat,lon`);
        return;
      }
      const lon = Number(cells[cells.length - 1]);
      const lat = Number(cells[cells.length - 2]);
      const timestamp = cells.length >= 5 ? cells[2] : undefined;
      const species = /^leopard$/i.test(cells[1]) ? "Leopard" : /^elephant$/i.test(cells[1]) ? "Elephant" : null;
      if (!species || !Number.isFinite(lat) || !Number.isFinite(lon)) {
        problems.push(`Line ${i + 1}: needs species Elephant or Leopard and numeric lat/lon`);
        return;
      }
      fixes.push({ animal_id: cells[0], species, lat, lon, ...(timestamp ? { timestamp } : {}) });
    });
  return { fixes, problems };
}

function CameraPanel({ data, actions, detector }) {
  const cameras = devicesOfKind(data, "camera");
  const [deviceId, setDeviceId] = useState(cameras[0]?.id || "");
  const [label, setLabel] = useState("auto"); // auto | Elephant | Leopard
  const [confidence, setConfidence] = useState("0.9");
  const [files, setFiles] = useState([]);
  const [results, setResults] = useState({});
  const [dragging, setDragging] = useState(false);
  const input = useRef(null);

  const previews = useMemo(
    () => files.map((file) => ({ file, url: URL.createObjectURL(file) })),
    [files]
  );
  useEffect(() => () => previews.forEach((p) => URL.revokeObjectURL(p.url)), [previews]);

  const addFiles = (list) => {
    const images = Array.from(list).filter(isImage);
    if (images.length) {
      setFiles((all) => [...all, ...images].slice(0, 20));
      setResults({});
    }
  };

  const send = () =>
    actions.run(
      async () => {
        const out = [];
        for (let i = 0; i < files.length; i++) {
          const file = files[i];
          setResults((r) => ({ ...r, [i]: { state: "uploading" } }));
          try {
            const manual = label !== "auto";
            const res = await api.uploadCamera(deviceId, file, {
              species: manual ? label : undefined,
              confidence: manual ? confidence : undefined
            });
            setResults((r) => ({ ...r, [i]: { state: "done", res } }));
            out.push(res);
          } catch (err) {
            if (err.status === 401) throw err; // let the app ask for the token again
            setResults((r) => ({ ...r, [i]: { state: "error", text: err.message } }));
          }
        }
        return out;
      },
      "Upload failed",
      {
        describe: (all) => {
          const events = all.flatMap((r) => r.results || []).filter((r) => r.event);
          if (!events.length) return `${all.length} image(s) processed, no elephant or leopard found.`;
          return `${all.length} image(s): ${events.length} detection(s). ${summarize(events[events.length - 1])}`;
        },
        kind: (all) => (all.some((r) => (r.results || []).some((x) => x.event?.alert_tier)) ? "alert" : "info")
      }
    );

  const detectorNote = !detector
    ? null
    : detector.installed
      ? `YOLO ready (${detector.model}${detector.loaded ? ", loaded" : ", loads on first image"}). ${detector.note}`
      : "YOLO is not installed on the server, so choose a species below to label images yourself (or install requirements-ml.txt).";

  return (
    <Panel title="📷 Camera trap upload">
      {detectorNote && (
        <p className={`hint ${detector?.installed ? "" : "warn-text"}`}>{detectorNote}</p>
      )}

      <label>Camera</label>
      <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
        {cameras.map((c) => (
          <option key={c.id} value={c.id}>{c.id} · {c.type}</option>
        ))}
      </select>

      <label>Species</label>
      <select value={label} onChange={(e) => setLabel(e.target.value)}>
        <option value="auto">Auto-detect with the model</option>
        <option>Elephant</option>
        <option>Leopard</option>
      </select>
      {label !== "auto" && (
        <>
          <label>Confidence for the manual label</label>
          <input type="number" min="0" max="1" step="0.01" value={confidence} onChange={(e) => setConfidence(e.target.value)} />
        </>
      )}

      <div
        className={`dropzone${dragging ? " over" : ""}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
      >
        <input
          ref={input}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}
        />
        <b>Drop camera-trap images here</b>
        <span>or click to choose, up to 20 at a time</span>
      </div>

      {previews.length > 0 && (
        <div className="upload-list">
          {previews.map(({ file, url }, i) => {
            const r = results[i];
            const events = (r?.res?.results || []).filter((x) => x.event);
            return (
              <div key={`${file.name}-${i}`} className="upload-row">
                <img src={url} alt="" />
                <div className="upload-body">
                  <b>{file.name}</b>
                  {!r && <small>ready</small>}
                  {r?.state === "uploading" && <small>uploading and detecting…</small>}
                  {r?.state === "error" && <small className="error-text">{r.text}</small>}
                  {r?.state === "done" && r.res.detections.length === 0 && (
                    <small>No elephant or leopard found in this image.</small>
                  )}
                  {r?.state === "done" && r.res.detections.map((d, k) => (
                    <small key={k}>{d.species} {Math.round(d.confidence * 100)}%</small>
                  ))}
                  {events.map((x, k) => (
                    <small key={k} className="upload-event">{summarize(x)}</small>
                  ))}
                </div>
                {r?.state === "done" && <Pill tone={events.length ? "ok" : "neutral"}>{events.length ? "ingested" : "no wildlife"}</Pill>}
              </div>
            );
          })}
        </div>
      )}

      <div className="button-row">
        <button className="btn primary" disabled={!files.length || !deviceId || actions.busy} onClick={send}>
          {actions.busy ? "Sending…" : `Send ${files.length || ""} image${files.length === 1 ? "" : "s"}`}
        </button>
        {files.length > 0 && (
          <button className="btn ghost" disabled={actions.busy} onClick={() => { setFiles([]); setResults({}); }}>
            Clear
          </button>
        )}
      </div>
    </Panel>
  );
}

function GpsPanel({ data, actions }) {
  const collars = devicesOfKind(data, "collar");
  const [deviceId, setDeviceId] = useState(collars[0]?.id || "");
  const [animalId, setAnimalId] = useState("E-102");
  const [species, setSpecies] = useState("Elephant");
  const [lat, setLat] = useState(String(data.config.forest.lat));
  const [lon, setLon] = useState(String(data.config.forest.lon));
  const [csv, setCsv] = useState("");
  const parsed = useMemo(() => parseCsv(csv), [csv]);

  const describe = (r) => {
    const reaching = (r.results || []).filter((x) => x.event?.alert_tier);
    return `${r.accepted} GPS fix(es) accepted.` + (reaching.length ? ` ${summarize(reaching[reaching.length - 1])}` : "");
  };
  const kind = (r) => ((r.results || []).some((x) => x.event?.alert_tier) ? "alert" : "info");

  const sendOne = () =>
    actions.run(
      () => api.sendGps(deviceId, [{ animal_id: animalId.trim(), species, lat: Number(lat), lon: Number(lon) }]),
      "GPS send failed",
      { describe, kind }
    );
  const sendCsv = () =>
    actions.run(() => api.sendGps(deviceId, parsed.fixes), "GPS send failed", { describe, kind });

  const okOne = deviceId && animalId.trim() && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon));

  return (
    <Panel title="📍 GPS collar fixes">
      <p className="hint">
        Collars normally upload buffered fixes in bursts over LoRa or GSM. A few fixes in a row give the
        predictor a track to work with.
      </p>
      <label>Collar</label>
      <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
        {collars.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
      </select>

      <div className="two-col">
        <div>
          <label>Animal ID</label>
          <input value={animalId} onChange={(e) => setAnimalId(e.target.value)} maxLength={40} />
        </div>
        <div>
          <label>Species</label>
          <select value={species} onChange={(e) => setSpecies(e.target.value)}>
            <option>Elephant</option>
            <option>Leopard</option>
          </select>
        </div>
        <div>
          <label>Latitude</label>
          <input value={lat} onChange={(e) => setLat(e.target.value)} inputMode="decimal" />
        </div>
        <div>
          <label>Longitude</label>
          <input value={lon} onChange={(e) => setLon(e.target.value)} inputMode="decimal" />
        </div>
      </div>
      <div className="button-row">
        <button className="btn primary" disabled={!okOne || actions.busy} onClick={sendOne}>Send fix</button>
      </div>

      <label>Or paste a track (CSV: animal_id,species,timestamp,lat,lon; a Movebank export works after trimming)</label>
      <textarea
        rows={4}
        value={csv}
        placeholder={"E-102,Elephant,2026-10-05 05:10:00,12.6620,80.1010\nE-102,Elephant,2026-10-05 05:25:00,12.6590,80.1008"}
        onChange={(e) => setCsv(e.target.value)}
      />
      {parsed.problems.length > 0 && <small className="error-text">{parsed.problems.slice(0, 3).join(" · ")}</small>}
      <div className="button-row">
        <button className="btn ghost" disabled={!parsed.fixes.length || !deviceId || actions.busy} onClick={sendCsv}>
          Send {parsed.fixes.length || ""} fix{parsed.fixes.length === 1 ? "" : "es"} from CSV
        </button>
      </div>
    </Panel>
  );
}

function GroundPanel({ data, actions }) {
  const sensors = devicesOfKind(data, "ground");
  const [deviceId, setDeviceId] = useState(sensors[0]?.id || "");
  const [kind, setKind] = useState("seismic");
  const [value, setValue] = useState("0.8");

  const pick = (k) => {
    setKind(k);
    setValue(SENSOR_KINDS.find(([id]) => id === k)[2]);
  };

  const send = () =>
    actions.run(() => api.sendSensor(deviceId, [{ kind, value: Number(value) }]), "Sensor send failed", {
      describe: (r) =>
        `${r.accepted} reading(s) accepted.` +
        (r.triggers?.length ? ` ${r.triggers.length} unverified trigger(s) raised, waiting for a camera or ranger.` : ""),
      kind: (r) => (r.triggers?.length ? "alert" : "info")
    });

  return (
    <Panel title="📡 Ground sensor reading">
      <p className="hint">
        A strong reading with no camera or collar to explain it becomes a low-confidence trigger that waits
        for ranger confirmation.
      </p>
      <label>Sensor</label>
      <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
        {sensors.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.type}</option>)}
      </select>
      <label>Reading</label>
      <select value={kind} onChange={(e) => pick(e.target.value)}>
        {SENSOR_KINDS.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
      <label>Value</label>
      <input value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal" />
      <div className="button-row">
        <button
          className="btn primary"
          disabled={!deviceId || !Number.isFinite(Number(value)) || value === "" || actions.busy}
          onClick={send}
        >
          Send reading
        </button>
      </div>
    </Panel>
  );
}

export default function LiveFeed({ data, actions }) {
  const [detector, setDetector] = useState(null);
  const loadDetector = useCallback(() => api.detector().then(setDetector).catch(() => setDetector(null)), []);
  useEffect(() => { loadDetector(); }, [loadDetector, data.feed.length]);

  const signedIn = Boolean(auth.get());
  return (
    <div>
      <PageHeader
        title="Live Feed"
        subtitle="Send data in the same ways real devices do. Everything goes through the production ingest endpoints."
      />
      {!signedIn && (
        <div className="info-banner">
          Uploading from the dashboard needs the ranger token. Real devices use their own API keys
          (register them on the Devices page).
        </div>
      )}

      <div className="content-grid even">
        <CameraPanel data={data} actions={actions} detector={detector} />
        <div>
          <GpsPanel data={data} actions={actions} />
          <GroundPanel data={data} actions={actions} />
        </div>
      </div>

      <Panel title="Ingest feed" badge={<span className="live">● live</span>}>
        <FeedList rows={data.feed} />
      </Panel>
    </div>
  );
}
