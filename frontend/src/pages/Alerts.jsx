import React from "react";
import AlertCard from "../components/AlertCard";
import { PageHeader, Panel, Pill } from "../components/small";
import { timeAgo } from "../utils";

const STATUS_TONE = { sent: "ok", dry_run: "ok", suppressed: "neutral", no_subscribers: "warn", failed: "bad" };

export default function Alerts({ data, actions }) {
  const pending = data.alerts.filter((a) => a.verification === "pending");
  const rest = data.alerts.filter((a) => a.verification !== "pending");

  return (
    <div>
      <PageHeader title="Alerts" subtitle="Wildlife conflict warnings and what was sent to villagers" />

      {pending.length > 0 && (
        <Panel title={`🧑‍🌾 Awaiting ranger confirmation (${pending.length})`}>
          <p className="hint">
            Detections below 85% confidence are held back so false alarms do not train villagers to ignore the system.
          </p>
          {pending.map((alert) => (
            <AlertCard key={alert.id} alert={alert} large onVerify={actions.verify} busy={actions.busy} />
          ))}
        </Panel>
      )}

      <div className="content-grid even">
        <Panel title="Alert history">
          {rest.length === 0 ? (
            <p className="empty">No alerts yet</p>
          ) : (
            rest.map((alert) => <AlertCard key={alert.id} alert={alert} large />)
          )}
        </Panel>

        <Panel title="📨 Messages sent">
          {data.notifications.length === 0 ? (
            <p className="empty">Nothing sent yet. Run a scenario or simulate an emergency to try it.</p>
          ) : (
            data.notifications.map((n) => (
              <details key={n.id} className="sms-row">
                <summary>
                  <span>
                    <b>{n.tier}</b> · {n.animal} · {n.village}{" "}
                    <Pill tone={n.channel === "sms" || !n.channel ? "neutral" : "ok"}>{n.channel || "sms"}</Pill>
                  </span>
                  <span className="sms-meta">
                    <Pill tone={STATUS_TONE[n.status]}>{n.status.replace("_", " ")}</Pill>
                    {n.recipients > 0 && <small>{n.recipients} recipients</small>}
                    <small>{timeAgo(n.timestamp)}</small>
                  </span>
                </summary>
                <p className="sms-text">{n.message}</p>
                <p className="sms-text">{n.message_local}</p>
                {n.error && <p className="sms-text error">{n.error}</p>}
              </details>
            ))
          )}
        </Panel>
      </div>
    </div>
  );
}
