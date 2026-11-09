import React from "react";

export const PAGES = [
  ["dashboard", "🏠", "Dashboard"],
  ["map", "🗺️", "Movement Map"],
  ["live", "📥", "Live Feed"],
  ["alerts", "🚨", "Alerts"],
  ["predictions", "🔮", "Predictions"],
  ["sensors", "📡", "Devices"],
  ["evaluation", "📊", "Evaluation"],
  ["simulation", "🧪", "Simulation Lab"]
];

function connectionStatus(backendError, live) {
  if (backendError) return { tone: "offline", text: "Backend offline" };
  if (live === "live") return { tone: "online", text: "Live" };
  if (live === "polling") return { tone: "warn", text: "Updating every 10 s" };
  if (live === "reconnecting") return { tone: "warn", text: "Reconnecting…" };
  return { tone: "warn", text: "Connecting…" };
}

export default function Sidebar({ page, setPage, backendError, live, pending, signedIn, onSignIn, onSignOut }) {
  const status = connectionStatus(backendError, live);
  return (
    <aside className="sidebar">
      <div className="logo">
        <div className="logo-icon">🐾</div>
        <div>
          <strong>WildGuard</strong>
          <small>Wildlife Intelligence</small>
        </div>
      </div>

      <nav>
        {PAGES.map(([id, icon, label]) => (
          <button
            key={id}
            className={page === id ? "nav-item active" : "nav-item"}
            onClick={() => setPage(id)}
          >
            <span>{icon}</span>
            <em>{label}</em>
            {id === "alerts" && pending > 0 && <b className="nav-count">{pending}</b>}
          </button>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <div className="system-status">
          <span className={`dot ${status.tone}`}>●</span>
          {status.text}
        </div>

        <button className="ranger-button" onClick={signedIn ? onSignOut : onSignIn}>
          {signedIn ? "🧑‍🌾 Ranger · sign out" : "🔒 Ranger sign-in"}
        </button>

        <small>Prototype v6.0</small>
      </div>
    </aside>
  );
}
