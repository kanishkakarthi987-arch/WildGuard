import React from "react";
import AlertCard from "../components/AlertCard";
import PredictionCard from "../components/PredictionCard";
import WildlifeMap from "../components/WildlifeMap";
import FeedList from "../components/FeedList";
import { PageHeader, Panel, Stat } from "../components/small";

export default function Dashboard({ data, actions }) {
  const { statistics: s, alerts, predictions, config, sightings } = data;
  return (
    <div>
      <PageHeader title="WildGuard" subtitle="Predictive wildlife early-warning system">
        <button className="btn danger" onClick={actions.emergency} disabled={actions.busy}>
          🚨 Simulate Emergency
        </button>
      </PageHeader>

      <div className="stats-grid">
        <Stat title="Total Sightings" value={s.total_sightings ?? 0} icon="🐾" tone="blue" />
        <Stat title="Elephants" value={s.elephants ?? 0} icon="🐘" tone="green" />
        <Stat title="Leopards" value={s.leopards ?? 0} icon="🐆" tone="orange" />
        <Stat title="High Risk Events" value={s.high_risk_events ?? 0} icon="🚨" tone="red" />
        <Stat title="Alerts Sent" value={s.alerts_sent ?? 0} icon="📨" tone="blue" />
        <Stat title="Awaiting Ranger" value={s.pending_verification ?? 0} icon="🧑‍🌾" tone="orange" />
        <Stat title="Unusual Movement" value={s.anomalies ?? 0} icon="⚠️" tone="orange" />
        <Stat title="Sensors Online" value={s.active_sensors ?? 0} icon="📡" tone="green" />
      </div>

      <div className="content-grid">
        <Panel title="Live Wildlife Map" className="map-panel" badge={<span className="live">● LIVE</span>}>
          <WildlifeMap
            config={config}
            sightings={sightings}
            predictions={predictions}
            tracks={data.tracks}
            devices={data.sensors.sensors}
            readings={data.readings}
            zones={data.zones}
            hours={24}
          />
        </Panel>

        <Panel title="Active Alerts">
          {alerts.length === 0 ? (
            <p className="empty">No active alerts</p>
          ) : (
            alerts.slice(0, 5).map((alert) => <AlertCard key={alert.id} alert={alert} />)
          )}
        </Panel>
      </div>

      <div className="content-grid even">
        <Panel title="Live ingest" badge={<span className="live">● {data.feed.length} recent</span>}>
          <FeedList rows={data.feed.slice(0, 8)} />
        </Panel>
        <Panel title="Ground sensors (last hour)">
          {data.readings.length === 0 ? (
            <p className="empty">No ground-sensor readings in the last hour.</p>
          ) : (
            <div className="reading-list">
              {data.readings.slice(-8).reverse().map((r) => (
                <div key={`${r.device_id}-${r.ts}-${r.kind}`} className="reading-row">
                  <b>{r.device_id}</b>
                  <span>{r.kind} {r.value}</span>
                  <span className={`pill ${r.level === "HIGH" ? "bad" : r.level === "MEDIUM" ? "warn" : ""}`}>
                    {r.level}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Latest Predictions">
        {predictions.length === 0 ? (
          <p className="empty">No predictions available.</p>
        ) : (
          <div className="prediction-grid">
            {predictions.slice(0, 3).map((p) => (
              <PredictionCard key={p.event_id} prediction={p} />
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
