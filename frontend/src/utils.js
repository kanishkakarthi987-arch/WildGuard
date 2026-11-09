export const RISK_COLORS = {
  CRITICAL: "#7f1d1d",
  HIGH: "#dc2626",
  MODERATE: "#f59e0b",
  LOW: "#16a34a"
};

export const TIER_COLORS = {
  Imminent: "#7f1d1d",
  Warning: "#dc2626",
  Watch: "#d97706"
};

export const riskColor = (risk) => RISK_COLORS[risk] || RISK_COLORS.LOW;
export const animalIcon = (animal) => (animal === "Elephant" ? "🐘" : "🐆");

export const formatEta = (minutes) => {
  if (minutes === null || minutes === undefined) return "No approach predicted";
  if (minutes === 0) return "At village now";
  return `${minutes} min`;
};

// Backend timestamps look like "2026-10-03 09:30:00" in the SERVER's local time, with no zone.
// The server reports its UTC offset in /api/config so a browser in another time zone still shows
// correct "5 min ago" values instead of being off by hours.
let serverOffsetMin = null;
export const setServerOffset = (minutes) => {
  serverOffsetMin = Number.isFinite(minutes) ? minutes : null;
};

export function parseTs(ts) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/.exec(String(ts));
  if (m && serverOffsetMin !== null) {
    const utc = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
    return new Date(utc - serverOffsetMin * 60000);
  }
  return new Date(String(ts).replace(" ", "T")); // no offset known: assume the browser's own zone
}

export function timeAgo(ts) {
  const minutes = Math.round((Date.now() - parseTs(ts).getTime()) / 60000);
  if (!Number.isFinite(minutes)) return "";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

const STATUS_TEXT = {
  dry_run: "alert logged (dry run)",
  sent: "SMS sent",
  suppressed: "duplicate alert suppressed",
  no_subscribers: "no subscribers in that village",
  failed: "SMS failed"
};

// One-line toast text for a simulate / verify response.
export function summarize(result) {
  const event = result.event;
  const head = `${animalIcon(event.animal)} ${event.animal} · risk ${event.risk}`;
  let tail;
  if (event.verification === "pending") {
    tail = "low confidence, waiting for ranger confirmation";
  } else if (event.alert_tier) {
    tail = `${event.alert_tier} for ${event.target_village}, ETA ${formatEta(event.eta_minutes)}`;
  } else {
    tail = "no village threatened";
  }
  const note = result.notification
    ? ` · ${STATUS_TEXT[result.notification.status] || result.notification.status}`
    : "";
  return `${head} · ${tail}${note}`;
}
