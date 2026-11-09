import React, { useState } from "react";
import { api } from "../api";
import { PageHeader, Panel, Pill, Stat } from "../components/small";
import { timeAgo } from "../utils";

const ICONS = {
  "Thermal Camera": "🌡️",
  "IR Camera": "📷",
  "GPS Collar": "📍",
  "Acoustic Sensor": "🔊",
  "Perimeter Sensor": "🚧"
};

const KIND_LABEL = { camera: "Camera", collar: "GPS collar", ground: "Ground sensor" };
const DEFAULT_TYPE = { camera: "IR Camera", collar: "GPS Collar", ground: "Acoustic Sensor" };
const TYPES_BY_KIND = {
  camera: ["IR Camera", "Thermal Camera"],
  collar: ["GPS Collar"],
  ground: ["Acoustic Sensor", "Perimeter Sensor"]
};

function ProvisionPanel({ actions, onKey }) {
  const [form, setForm] = useState({ id: "", kind: "camera", type: "IR Camera", lat: "", lon: "", lora_id: "" });
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const pickKind = (e) => setForm({ ...form, kind: e.target.value, type: DEFAULT_TYPE[e.target.value] });

  const valid = /^[A-Za-z0-9_-]{2,32}$/.test(form.id);

  const submit = (rotate) =>
    actions.run(
      () =>
        api.provisionDevice({
          id: form.id.trim(),
          kind: form.kind,
          type: form.type,
          rotate,
          ...(form.lat !== "" && form.lon !== "" ? { lat: Number(form.lat), lon: Number(form.lon) } : {}),
          ...(form.lora_id !== "" ? { lora_id: Number(form.lora_id) } : {})
        }),
      "Could not register the device",
      {
        describe: (r) => `${r.device.id} registered. Copy its API key now, it is shown only once.`,
        onResult: (r) => onKey(r)
      }
    );

  return (
    <Panel title="➕ Register a device">
      <p className="hint">
        Each real camera, collar or ground sensor gets its own API key. Cameras and ground sensors
        need a fixed location. Collars report their own position.
      </p>
      <div className="two-col">
        <div>
          <label>Device ID</label>
          <input value={form.id} onChange={set("id")} placeholder="CAM-06" maxLength={32} />
        </div>
        <div>
          <label>Kind</label>
          <select value={form.kind} onChange={pickKind}>
            {Object.entries(KIND_LABEL).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </div>
        <div>
          <label>Model</label>
          <select value={form.type} onChange={set("type")}>
            {TYPES_BY_KIND[form.kind].map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label>LoRa short ID (optional)</label>
          <input value={form.lora_id} onChange={set("lora_id")} inputMode="numeric" placeholder="1-65535" />
        </div>
        <div>
          <label>Latitude</label>
          <input value={form.lat} onChange={set("lat")} inputMode="decimal" disabled={form.kind === "collar"} />
        </div>
        <div>
          <label>Longitude</label>
          <input value={form.lon} onChange={set("lon")} inputMode="decimal" disabled={form.kind === "collar"} />
        </div>
      </div>
      <div className="button-row">
        <button className="btn primary" disabled={!valid || actions.busy} onClick={() => submit(false)}>
          Register and issue key
        </button>
        <button className="btn ghost" disabled={!valid || actions.busy} onClick={() => submit(true)}>
          Replace existing key
        </button>
      </div>
    </Panel>
  );
}

function KeyReveal({ issued, onClose }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(issued.api_key);
      setCopied(true);
    } catch {
      /* clipboard can be blocked; the key is selectable below */
    }
  };
  return (
    <div className="key-reveal">
      <b>API key for {issued.device.id}</b>
      <code>{issued.api_key}</code>
      <p>
        Shown once and never stored, only its hash is. Put it in the device's
        <code> WILDGUARD_API_KEY</code> setting and send it as the <code>X-API-Key</code> header.
      </p>
      <div className="button-row">
        <button className="btn primary small" onClick={copy}>{copied ? "Copied" : "Copy key"}</button>
        <button className="btn ghost small" onClick={onClose}>I saved it, hide</button>
      </div>
    </div>
  );
}

export default function Sensors({ data, actions }) {
  const s = data.sensors;
  const [issued, setIssued] = useState(null);

  return (
    <div>
      <PageHeader
        title="Sensor Network"
        subtitle="A device counts as online only if it reported recently. Silence means offline."
      />

      <div className="stats-grid">
        <Stat title="Total Devices" value={s.total ?? 0} icon="📡" tone="blue" />
        <Stat title="Online" value={s.online ?? 0} icon="🟢" tone="green" />
        <Stat title="Offline" value={s.offline ?? 0} icon="🔴" tone="red" />
        <Stat
          title="LoRa gateway"
          value={data.health.lora_enabled ? "Enabled" : "Off"}
          icon="📶"
          tone={data.health.lora_enabled ? "green" : "orange"}
        />
      </div>

      {issued && <KeyReveal issued={issued} onClose={() => setIssued(null)} />}

      <div className="content-grid">
        <Panel title="Devices">
          <div className="sensor-grid two">
            {(s.sensors || []).map((sensor) => (
              <div className="sensor-card" key={sensor.id}>
                <div className="sensor-icon">{ICONS[sensor.type] || "📡"}</div>
                <div className="sensor-body">
                  <h3>{sensor.id}</h3>
                  <p>
                    {sensor.type} · {KIND_LABEL[sensor.kind] || sensor.kind}
                    {sensor.lora_id ? ` · LoRa #${sensor.lora_id}` : ""}
                  </p>
                  <Pill tone={sensor.status === "ONLINE" ? "ok" : "bad"}>● {sensor.status}</Pill>{" "}
                  <Pill tone={sensor.has_key ? "ok" : "warn"}>{sensor.has_key ? "has API key" : "no API key"}</Pill>
                  <div className="battery">
                    <div className="battery-bar">
                      <div style={{ width: `${sensor.battery}%` }} />
                    </div>
                    <small>
                      {sensor.battery}%{sensor.last_seen ? ` · seen ${timeAgo(sensor.last_seen)}` : " · never seen"}
                    </small>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <ProvisionPanel actions={actions} onKey={setIssued} />
      </div>
    </div>
  );
}
