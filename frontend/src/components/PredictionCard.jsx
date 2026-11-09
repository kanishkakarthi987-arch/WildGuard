import React from "react";
import { animalIcon, formatEta, riskColor } from "../utils";
import { Pill, TierBadge } from "./small";

export default function PredictionCard({ prediction }) {
  const p = prediction;
  return (
    <div className="prediction-card">
      <div className="animal-title">
        <span>{animalIcon(p.animal)}</span>
        <b>{p.animal}</b>
        <TierBadge tier={p.alert_tier} />
      </div>

      <div className="prediction-info">
        <div>
          Heading
          <strong>{p.direction}</strong>
        </div>
        <div>
          Speed
          <strong>
            {p.speed_kmh} km/h <small>±{p.speed_sigma_kmh}</small>
          </strong>
        </div>
        <div>
          {p.will_reach ? "Will reach" : "Nearest village"}
          <strong>{p.predicted_zone}</strong>
        </div>
        <div>
          ETA
          <strong>{formatEta(p.eta_minutes)}</strong>
        </div>
        <div>
          Closest approach
          <strong>{p.closest_approach_km} km</strong>
        </div>
        <div>
          Risk
          <strong style={{ color: riskColor(p.risk) }}>
            {p.risk} ({p.risk_score})
          </strong>
        </div>
      </div>

      {p.anomaly && <Pill tone="warn">unusual movement for this species</Pill>}
    </div>
  );
}
