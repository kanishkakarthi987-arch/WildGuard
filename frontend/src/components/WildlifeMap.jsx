import React, { useMemo, useState } from "react";
import {
  MapContainer, TileLayer, Marker, Popup, Circle, CircleMarker, Polyline, Rectangle
} from "react-leaflet";
import { animalIcon, formatEta, parseTs, riskColor, timeAgo } from "../utils";

// Number(null) is 0, so null must be rejected explicitly or collars without a fixed position
// would be drawn at (null, null) and crash Leaflet.
const num = (v) => (v === null || v === undefined || v === "" ? NaN : Number(v));
const validCoord = (item) => Number.isFinite(num(item?.lat)) && Number.isFinite(num(item?.lon));

const ZONE_COLORS = { HIGH: "#dc2626", MODERATE: "#f59e0b", LOW: "#16a34a" };
const SPECIES_COLORS = { Elephant: "#1d4ed8", Leopard: "#a21caf", Unknown: "#6b7280" };
const KIND_COLORS = { camera: "#2563eb", ground: "#7c3aed", collar: "#0d9488" };
const LEVEL_RANK = { LOW: 0, MEDIUM: 1, HIGH: 2 };

const LAYERS = [
  ["zones", "Risk zones"],
  ["tracks", "Animal tracks"],
  ["devices", "Sensors"],
  ["detections", "Detections"],
  ["paths", "Predicted paths"]
];

/** Strongest recent ground reading per device, so a sensor can light up when it is triggered. */
function strongestByDevice(readings) {
  const best = {};
  for (const r of readings) {
    const rank = LEVEL_RANK[r.level] ?? 0;
    const current = best[r.device_id];
    if (!current || rank > current.rank || (rank === current.rank && r.ts > current.ts)) {
      best[r.device_id] = { rank, level: r.level, kind: r.kind, value: r.value, ts: r.ts };
    }
  }
  return best;
}

export default function WildlifeMap({
  config,
  sightings,
  predictions,
  tracks = [],
  devices = [],
  readings = [],
  zones = { cells: [] },
  hours = 24,
  className = "map"
}) {
  const [on, setOn] = useState({ zones: true, tracks: true, devices: true, detections: true, paths: true });
  const toggle = (key) => setOn((all) => ({ ...all, [key]: !all[key] }));

  const cutoff = Date.now() - hours * 3600 * 1000;
  const visible = useMemo(
    () => sightings.filter((s) => validCoord(s) && parseTs(s.timestamp).getTime() >= cutoff),
    [sightings, cutoff]
  );
  const visibleIds = useMemo(() => new Set(visible.map((s) => s.id)), [visible]);
  const paths = predictions.filter((p) => visibleIds.has(p.event_id) && p.path?.length);
  const hot = useMemo(() => strongestByDevice(readings), [readings]);
  const placed = devices.filter(validCoord);

  return (
    <>
      <div className="layer-bar">
        {LAYERS.map(([key, label]) => (
          <label key={key} className={`layer-chip${on[key] ? " on" : ""}`}>
            <input type="checkbox" checked={on[key]} onChange={() => toggle(key)} />
            {label}
          </label>
        ))}
        {on.zones && zones.night !== undefined && (
          <span className="layer-note">
            {zones.night ? "🌙 night weighting on" : "☀️ daytime"} · {zones.sources ?? 0} past events used
          </span>
        )}
      </div>

      <MapContainer center={[config.forest.lat, config.forest.lon]} zoom={12} className={className}>
        <TileLayer attribution="&copy; OpenStreetMap" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />

        {on.zones &&
          zones.cells.map((cell, i) => (
            <Rectangle
              key={`z${i}`}
              bounds={[
                [cell.lat - zones.half_lat, cell.lon - zones.half_lon],
                [cell.lat + zones.half_lat, cell.lon + zones.half_lon]
              ]}
              pathOptions={{
                stroke: false,
                fillColor: ZONE_COLORS[cell.level] || ZONE_COLORS.LOW,
                fillOpacity: Math.min(0.5, 0.1 + cell.risk * 0.45),
                interactive: false
              }}
            />
          ))}

        <Circle
          center={[config.forest.lat, config.forest.lon]}
          radius={config.forest.radius_m}
          pathOptions={{ color: "green", fillOpacity: 0.03, weight: 1, interactive: false }}
        />

        {config.villages.map((village) => {
          const radii = Object.values(village.threat_radius_by_species || {});
          const threat = (radii.length ? Math.max(...radii) : village.threat_radius_km) * 1000;
          return (
            <React.Fragment key={village.name}>
              <Circle
                center={[village.lat, village.lon]}
                radius={threat}
                pathOptions={{ color: "red", fillOpacity: 0.08, weight: 1 }}
              />
              <Circle
                center={[village.lat, village.lon]}
                radius={1500}
                pathOptions={{ color: "orange", fillOpacity: 0.03, weight: 1, interactive: false }}
              />
              <Marker position={[village.lat, village.lon]}>
                <Popup>
                  🏠 <b>{village.name}</b>
                  <br />
                  Alert radius:
                  {Object.entries(village.threat_radius_by_species || {}).map(([sp, km]) => (
                    <span key={sp}>
                      <br />
                      {animalIcon(sp)} {sp} {km} km
                    </span>
                  ))}
                </Popup>
              </Marker>
            </React.Fragment>
          );
        })}

        {on.devices &&
          placed.map((d) => {
            const trigger = hot[d.id];
            const alive = d.status === "ONLINE";
            return (
              <React.Fragment key={d.id}>
                {trigger && trigger.rank >= 1 && (
                  <CircleMarker
                    center={[d.lat, d.lon]}
                    radius={trigger.rank === 2 ? 16 : 12}
                    pathOptions={{
                      color: trigger.rank === 2 ? "#dc2626" : "#f59e0b",
                      fillOpacity: 0.12,
                      weight: 2,
                      interactive: false
                    }}
                  />
                )}
                <CircleMarker
                  center={[d.lat, d.lon]}
                  radius={5}
                  pathOptions={{
                    color: alive ? KIND_COLORS[d.kind] || "#374151" : "#9ca3af",
                    fillColor: alive ? KIND_COLORS[d.kind] || "#374151" : "#d1d5db",
                    fillOpacity: 0.9,
                    weight: 1
                  }}
                >
                  <Popup>
                    <b>{d.kind === "camera" ? "📷" : "📡"} {d.id}</b>
                    <br />
                    {d.type} · {alive ? "online" : "offline"}
                    <br />
                    Battery {d.battery}% · {d.last_seen ? `seen ${timeAgo(d.last_seen)}` : "never seen"}
                    {trigger && (
                      <>
                        <br />
                        Last reading: {trigger.kind} {trigger.value} ({trigger.level})
                      </>
                    )}
                  </Popup>
                </CircleMarker>
              </React.Fragment>
            );
          })}

        {on.tracks &&
          tracks.map((t) => {
            const pts = t.points.filter(validCoord);
            if (pts.length < 1) return null;
            const color = SPECIES_COLORS[t.species] || SPECIES_COLORS.Unknown;
            const last = pts[pts.length - 1];
            return (
              <React.Fragment key={t.track_id}>
                {pts.length > 1 && (
                  <Polyline positions={pts.map((p) => [p.lat, p.lon])} pathOptions={{ color, weight: 3, opacity: 0.8 }} />
                )}
                <CircleMarker
                  center={[last.lat, last.lon]}
                  radius={6}
                  pathOptions={{ color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 }}
                >
                  <Popup>
                    <b>{animalIcon(t.species)} {t.track_id}</b>
                    <br />
                    {t.species} · via {t.source}
                    <br />
                    {pts.length} fixes · last {timeAgo(last.t)}
                  </Popup>
                </CircleMarker>
              </React.Fragment>
            );
          })}

        {on.paths &&
          paths.map((p) => (
            <Polyline
              key={`path-${p.event_id}`}
              positions={[[p.current_lat, p.current_lon], ...p.path.map((q) => [q.lat, q.lon])]}
              pathOptions={{ color: p.will_reach ? "#dc2626" : "#6b7280", weight: 3, dashArray: "6 8" }}
            />
          ))}

        {on.detections &&
          visible.map((s) => (
            <Circle
              key={s.id}
              center={[Number(s.lat), Number(s.lon)]}
              radius={s.risk === "CRITICAL" ? 300 : s.risk === "HIGH" ? 220 : 120}
              pathOptions={{ color: riskColor(s.risk), fillOpacity: 0.35 }}
            >
              <Popup>
                <b>
                  {animalIcon(s.animal)} {s.animal}
                </b>
                <br />
                Source: {s.source}
                <br />
                Confidence: {Math.round((Number(s.confidence) || 0) * 100)}%
                <br />
                Risk: {s.risk} ({s.risk_score})
                <br />
                Heading: {s.direction} at {s.speed_kmh} km/h
                <br />
                {s.distance_km} km from {s.nearest_village}
                <br />
                {s.will_reach
                  ? `Reaches ${s.target_village} in ${formatEta(s.eta_minutes)}`
                  : "No village in its path"}
                {s.alert_tier && (
                  <>
                    <br />
                    Alert tier: {s.alert_tier}
                  </>
                )}
                {s.anomaly && (
                  <>
                    <br />
                    ⚠ Unusual movement
                  </>
                )}
              </Popup>
            </Circle>
          ))}
      </MapContainer>
    </>
  );
}
