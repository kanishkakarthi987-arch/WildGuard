import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { PageHeader, Panel, Pill, Stat, TierBadge } from "../components/small";
import { timeAgo } from "../utils";

const pct = (v) => (v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`);
const minutes = (v) => (v === null || v === undefined ? "n/a" : `${v} min`);

function IncidentForm({ data, actions, onLogged }) {
  const villages = data.config.villages.map((v) => v.name);
  const [village, setVillage] = useState(villages[0]);
  const [animal, setAnimal] = useState("");
  const [notes, setNotes] = useState("");

  const submit = () =>
    actions.run(
      () => api.logIncident({ village, notes: notes.trim() || undefined, ...(animal ? { animal } : {}) }),
      "Could not log the incident",
      { describe: () => `Incident logged for ${village}.`, onResult: onLogged }
    );

  return (
    <Panel title="📝 Log a real incident">
      <p className="hint">
        An incident is an animal that actually reached a village. Evaluation compares your alerts against
        these, so log them honestly, including the ones the system missed.
      </p>
      <label>Village</label>
      <select value={village} onChange={(e) => setVillage(e.target.value)}>
        {villages.map((v) => <option key={v}>{v}</option>)}
      </select>
      <label>Animal (optional)</label>
      <select value={animal} onChange={(e) => setAnimal(e.target.value)}>
        <option value="">Unknown</option>
        <option>Elephant</option>
        <option>Leopard</option>
      </select>
      <label>Notes (optional)</label>
      <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={300} placeholder="Crop damage near the east field" />
      <div className="button-row">
        <button className="btn primary" disabled={actions.busy} onClick={submit}>Log incident now</button>
      </div>
    </Panel>
  );
}

export default function Evaluation({ data, actions }) {
  const [windowMin, setWindowMin] = useState(180);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.evaluation(windowMin).then((r) => { setReport(r); setError(""); }).catch((e) => setError(e.message));
  }, [windowMin]);

  // Reload when the window changes or when anything new is written (alerts or events change).
  useEffect(load, [load, data.notifications.length, data.statistics.total_sightings]);

  const r = report;
  return (
    <div>
      <PageHeader
        title="Evaluation"
        subtitle="How good are the warnings? An alert is correct if an incident in the same village follows within the window."
      >
        <label className="inline-field">
          Window
          <select value={windowMin} onChange={(e) => setWindowMin(Number(e.target.value))}>
            <option value={60}>60 min</option>
            <option value={180}>3 hours</option>
            <option value={360}>6 hours</option>
            <option value={720}>12 hours</option>
          </select>
        </label>
      </PageHeader>

      {error && <div className="error-banner">Could not load the evaluation: {error}</div>}

      {r && (
        <>
          <div className="stats-grid">
            <Stat title="Precision" value={pct(r.precision)} icon="🎯" tone="green" />
            <Stat title="Recall (incidents warned)" value={pct(r.recall)} icon="📣" tone="blue" />
            <Stat title="Median lead time" value={minutes(r.median_lead_minutes)} icon="⏱️" tone="orange" />
            <Stat title="False alarms / week" value={r.false_alarms_per_week ?? "n/a"} icon="🔕" tone="red" />
          </div>

          <div className="content-grid even">
            <Panel title="Summary">
              <div className="kv">
                <span>Alerts sent</span><b>{r.alerts}</b>
                <span>Correct / false</span><b>{r.true_alerts} / {r.false_alerts}</b>
                <span>Incidents logged</span><b>{r.incidents}</b>
                <span>Shortest lead time</span><b>{minutes(r.min_lead_minutes)}</b>
                <span>Duplicates suppressed</span><b>{r.suppressed_duplicates}</b>
                <span>Data span</span><b>{r.span_days} day(s)</b>
              </div>
              <h3 className="subhead">By tier</h3>
              <div className="kv">
                {Object.entries(r.by_tier).map(([tier, t]) => (
                  <React.Fragment key={tier}>
                    <span><TierBadge tier={tier} /></span>
                    <b>{t.alerts} alert(s), precision {pct(t.precision)}</b>
                  </React.Fragment>
                ))}
              </div>
              <h3 className="subhead">Detections by verification</h3>
              <div className="kv">
                {Object.entries(r.verification).map(([k, v]) => (
                  <React.Fragment key={k}><span>{k}</span><b>{v}</b></React.Fragment>
                ))}
              </div>
              {r.incidents === 0 && (
                <p className="hint warn-text">
                  No incidents logged yet, so precision and recall cannot be measured. Run the "mixed" scenario
                  in the Simulation Lab (it logs ground truth) or log real incidents here.
                </p>
              )}
            </Panel>

            <IncidentForm data={data} actions={actions} onLogged={load} />
          </div>

          <div className="content-grid even">
            <Panel title="Alerts and outcomes">
              {r.alert_rows.length === 0 ? (
                <p className="empty">No alerts in this window yet.</p>
              ) : (
                r.alert_rows.map((a) => (
                  <div key={a.id} className="outcome-row">
                    <span><TierBadge tier={a.tier} /> {a.animal} · {a.village}</span>
                    <span className="outcome-meta">
                      <Pill tone={a.correct ? "ok" : "bad"}>{a.correct ? `correct, ${minutes(a.lead_minutes)} early` : "false alarm"}</Pill>
                      <small>{timeAgo(a.timestamp)}</small>
                    </span>
                  </div>
                ))
              )}
            </Panel>
            <Panel title="Incidents and whether they were warned">
              {r.incident_rows.length === 0 ? (
                <p className="empty">No incidents logged.</p>
              ) : (
                r.incident_rows.map((i) => (
                  <div key={i.id} className="outcome-row">
                    <span>{i.village}{i.animal ? ` · ${i.animal}` : ""}{i.notes ? ` · ${i.notes}` : ""}</span>
                    <span className="outcome-meta">
                      <Pill tone={i.warned ? "ok" : "bad"}>{i.warned ? `warned ${minutes(i.lead_minutes)} early` : "missed"}</Pill>
                      <small>{timeAgo(i.timestamp)}</small>
                    </span>
                  </div>
                ))
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
