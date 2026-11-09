import React from "react";
import { riskColor, TIER_COLORS } from "../utils";

export function Stat({ title, value, icon, tone = "green" }) {
  return (
    <div className="stat-card">
      <div className={`stat-icon ${tone}`}>{icon}</div>
      <div>
        <span className="stat-title">{title}</span>
        <strong className="stat-value">{value}</strong>
      </div>
    </div>
  );
}

export function RiskBadge({ risk }) {
  return (
    <span className="badge" style={{ background: riskColor(risk) }}>
      {risk}
    </span>
  );
}

export function TierBadge({ tier }) {
  if (!tier) return null;
  return (
    <span className="badge" style={{ background: TIER_COLORS[tier] }}>
      {tier.toUpperCase()}
    </span>
  );
}

export function Pill({ children, tone = "neutral" }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

export function Panel({ title, badge, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <div className="panel-title">
          <h2>{title}</h2>
          {badge}
        </div>
      )}
      {children}
    </section>
  );
}

export function Pipeline() {
  const steps = [
    ["📷", "Camera Detection"],
    ["📍", "GPS Tracking"],
    ["📡", "Sensor Fusion"],
    ["🧠", "Risk Analysis"],
    ["🔮", "Movement Prediction"],
    ["🚨", "Alert Generation"]
  ];
  return (
    <div className="pipeline">
      {steps.map(([icon, title], index) => (
        <React.Fragment key={title}>
          <div className="pipeline-step">
            <div>{icon}</div>
            <span>{title}</span>
          </div>
          {index < steps.length - 1 && <div className="pipeline-arrow">→</div>}
        </React.Fragment>
      ))}
    </div>
  );
}

export function ToastHost({ toasts, dismiss }) {
  return (
    <div className="toast-host">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast ${toast.kind}`} onClick={() => dismiss(toast.id)}>
          {toast.text}
        </div>
      ))}
    </div>
  );
}
