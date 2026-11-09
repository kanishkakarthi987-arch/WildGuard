import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { PageHeader, Panel, Pipeline } from "../components/small";

const SOURCES = ["Camera Trap", "GPS Collar", "Acoustic Sensor", "PIR Sensor"];
const MOVEMENTS = ["Toward Village", "Away From Village", "Parallel To Boundary"];

const MODES = [
  ["mixed", "Mixed day (6 animals: approach, veer off, loiter)", "Best for evaluation: some warnings are right, some are false alarms."],
  ["approach", "One animal walks into the village", "A real incident. A good system warns in time."],
  ["veer", "One animal heads in, then turns away", "No incident. A good system cancels or de-escalates."],
  ["loiter", "One animal wanders near the forest edge", "No incident. Tests whether the system stays quiet."]
];

function ScenarioPanel({ data, actions }) {
  const [form, setForm] = useState({ mode: "mixed", species: "Elephant", village: data.config.villages[0].name, speed: 10 });
  const [status, setStatus] = useState({ running: false, message: "idle", step: 0, total: 0 });
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const poll = useCallback(() => api.demoStatus().then(setStatus).catch(() => {}), []);

  useEffect(() => {
    poll();
    const timer = setInterval(poll, 1500);
    return () => clearInterval(timer);
  }, [poll]);

  const start = () =>
    actions.run(
      () => api.startScenario({ ...form, speed: Number(form.speed) }),
      "Could not start the scenario",
      { describe: () => "Scenario started. Watch the Live Feed and Map.", onResult: poll }
    );

  const single = form.mode !== "mixed";
  const progress = status.total ? Math.round((status.step / status.total) * 100) : 0;
  const note = MODES.find(([id]) => id === form.mode)?.[2];

  return (
    <Panel title="🎬 Realistic scenario">
      <p className="hint">
        Plays a full timeline through the real ingest endpoints: GPS fixes, ground-sensor readings and camera
        detections, with ground-truth incidents logged for the Evaluation page.
      </p>
      <label>Scenario</label>
      <select value={form.mode} onChange={set("mode")}>
        {MODES.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
      <p className="hint">{note}</p>

      {single && (
        <div className="two-col">
          <div>
            <label>Species</label>
            <select value={form.species} onChange={set("species")}>
              <option>Elephant</option>
              <option>Leopard</option>
            </select>
          </div>
          <div>
            <label>Village</label>
            <select value={form.village} onChange={set("village")}>
              {data.config.villages.map((v) => <option key={v.name}>{v.name}</option>)}
            </select>
          </div>
        </div>
      )}

      <label>Playback speed: {form.speed}× real time</label>
      <input type="range" min="1" max="60" value={form.speed} onChange={set("speed")} />

      <button className="btn primary" disabled={actions.busy || status.running} onClick={start}>
        {status.running ? "Running…" : "▶ Start scenario"}
      </button>

      {(status.running || status.step > 0) && (
        <div className="scenario-status">
          <div className="battery-bar"><div style={{ width: `${progress}%` }} /></div>
          <small>
            {status.kind ? `${status.kind}: ` : ""}step {status.step} of {status.total} · {status.message}
          </small>
        </div>
      )}
    </Panel>
  );
}

export default function Simulation({ data, actions }) {
  const [form, setForm] = useState({
    animal: "Elephant",
    source: "Camera Trap",
    camera_id: data.config.cameras[0]?.id || "CAM-01",
    movement: "Toward Village"
  });
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  return (
    <div>
      <PageHeader
        title="Simulation Lab"
        subtitle="Generate events to demonstrate and test the pipeline. Real devices send data through the ingest API: register them on the Devices page, then watch the Live Feed."
      />
      <div className="simulation-grid">
        <div>
          <ScenarioPanel data={data} actions={actions} />
          <Panel title="🧪 Single synthetic detection">
            <label>Species</label>
            <select value={form.animal} onChange={set("animal")}>
              <option>Elephant</option>
              <option>Leopard</option>
            </select>

            <label>Detection source</label>
            <select value={form.source} onChange={set("source")}>
              {SOURCES.map((s) => <option key={s}>{s}</option>)}
            </select>

            <label>Camera / sensor location</label>
            <select value={form.camera_id} onChange={set("camera_id")}>
              {data.config.cameras.map((c) => <option key={c.id}>{c.id}</option>)}
            </select>

            <label>Intended movement</label>
            <select value={form.movement} onChange={set("movement")}>
              {MOVEMENTS.map((m) => <option key={m}>{m}</option>)}
            </select>

            <button className="btn primary" disabled={actions.busy} onClick={() => actions.simulate(form)}>
              {actions.busy ? "Processing…" : "🚀 Simulate detection"}
            </button>
            <button className="btn danger" disabled={actions.busy} onClick={actions.emergency}>
              🚨 Simulate emergency
            </button>
          </Panel>
        </div>

        <Panel title="🔄 Processing pipeline">
          <Pipeline />
          <p className="hint">
            Camera, collar and ground-sensor data are fused per animal. The Kalman filter estimates speed and
            heading, the risk score and alert tier follow, low-confidence detections wait for a ranger, and
            SMS goes out in English and Tamil (with voice calls for Warning and Imminent).
          </p>
        </Panel>
      </div>
    </div>
  );
}
