import React from "react";
import { mediaUrl } from "../api";
import { animalIcon, formatEta, timeAgo } from "../utils";
import { Pill, RiskBadge, TierBadge } from "./small";

export default function AlertCard({ alert, large = false, onVerify, busy = false }) {
  const pending = alert.verification === "pending";
  return (
    <div className={`alert-card${large ? " large" : ""}`}>
      {alert.image ? (
        <a href={mediaUrl(alert.image)} target="_blank" rel="noreferrer" className="alert-photo" title="Open the camera image">
          <img src={mediaUrl(alert.image)} alt={`${alert.animal} camera capture`} loading="lazy" />
        </a>
      ) : (
        <div className="alert-icon">{animalIcon(alert.animal)}</div>
      )}

      <div className="alert-content">
        <div className="alert-heading">
          <strong>{alert.animal === "Unknown" ? "Ground-sensor trigger" : `${alert.animal} movement detected`}</strong>
          <span className="badges">
            <TierBadge tier={alert.alert_tier} />
            <RiskBadge risk={alert.risk} />
          </span>
        </div>

        <p>
          {alert.location} · {alert.distance_km} km from {alert.nearest_village || "village"}
          {alert.target_village && alert.eta_minutes !== null && alert.eta_minutes !== undefined && (
            <> · reaches {alert.target_village} in {formatEta(alert.eta_minutes)}</>
          )}
        </p>

        <small>
          {alert.source ? `${alert.source} · ` : ""}{alert.direction} · score {alert.risk_score} · {timeAgo(alert.timestamp)}
          {alert.anomaly && <> · <Pill tone="warn">unusual movement</Pill></>}
          {pending && <> · <Pill tone="warn">awaiting ranger ({Math.round(alert.confidence * 100)}% confidence)</Pill></>}
          {alert.verification === "confirmed" && <> · <Pill tone="ok">ranger confirmed</Pill></>}
          {alert.verification === "rejected" && <> · <Pill>rejected</Pill></>}
        </small>

        {pending && onVerify && (
          <div className="verify-row">
            <button className="btn primary small" disabled={busy} onClick={() => onVerify(alert.id, "confirm")}>
              Confirm and send alert
            </button>
            <button className="btn ghost small" disabled={busy} onClick={() => onVerify(alert.id, "reject")}>
              Reject
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
