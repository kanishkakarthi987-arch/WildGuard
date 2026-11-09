export const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

// ---------------------------------------------------------------------------
// Ranger (admin) token. Kept in localStorage so a refresh does not sign you out.
// Storage can be blocked (private windows), so every access is wrapped.
// ---------------------------------------------------------------------------

const TOKEN_KEY = "wildguard.adminToken";

function readStoredToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

let token = readStoredToken();

export const auth = {
  get: () => token,
  set(value) {
    token = value;
    try {
      localStorage.setItem(TOKEN_KEY, value);
    } catch {
      /* the token still works for this tab */
    }
  },
  clear() {
    token = "";
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing to clear */
    }
  }
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const { tokenOverride, ...init } = options;
  const adminToken = tokenOverride ?? token;
  // Multipart uploads must let the browser set the Content-Type (it adds the boundary).
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        ...(adminToken ? { "X-Admin-Token": adminToken } : {}),
        ...init.headers
      }
    });
  } catch {
    throw new ApiError("Backend unreachable", 0);
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep the status text */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json();
}

const post = (path, body) =>
  request(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

const withDevice = (path, deviceId) => `${path}?device_id=${encodeURIComponent(deviceId)}`;

// Optional extras must never break the main dashboard refresh.
export const soft = (promise, fallback) => promise.catch(() => fallback);

export const mediaUrl = (name) => (name ? `${API_BASE}/api/media/${name}` : null);

export const api = {
  health: () => request("/api/health"),
  config: () => request("/api/config"),
  sightings: () => request("/api/sightings?limit=200"),
  statistics: () => request("/api/statistics"),
  alerts: () => request("/api/alerts?limit=30"),
  predictions: () => request("/api/predict"),
  sensors: () => request("/api/sensors"),
  notifications: () => request("/api/notifications?limit=30"),
  tracks: () => request("/api/tracks?minutes=180"),
  groundReadings: () => request("/api/ground-readings?minutes=60"),
  riskZones: () => request("/api/risk-zones"),
  feed: () => request("/api/ingest/feed?limit=40"),
  devices: () => request("/api/devices"),
  detector: () => request("/api/detector"),
  evaluation: (windowMin) => request(`/api/evaluation?window_min=${windowMin}`),
  incidents: () => request("/api/incidents"),
  demoStatus: () => request("/api/demo/status"),

  // Returns true if the backend accepts this token, false if it rejects it.
  async checkToken(candidate) {
    try {
      await request("/api/auth/check", { tokenOverride: candidate });
      return true;
    } catch (err) {
      if (err.status === 401) return false;
      throw err;
    }
  },

  simulate: (body) => post("/api/simulate", body),
  emergency: () => post("/api/simulate-emergency"),
  verify: (id, action) => post(`/api/events/${id}/verify`, { action }),

  // Ingestion from the dashboard: the ranger token stands in for a device key (device_id in the query).
  uploadCamera(deviceId, file, { species, confidence, lat, lon } = {}) {
    const form = new FormData();
    form.append("file", file);
    if (species) form.append("species", species);
    if (confidence !== undefined && confidence !== "") form.append("confidence", String(confidence));
    if (lat !== undefined && lat !== "") form.append("lat", String(lat));
    if (lon !== undefined && lon !== "") form.append("lon", String(lon));
    return request(withDevice("/api/ingest/camera", deviceId), { method: "POST", body: form });
  },
  sendGps: (deviceId, fixes) => post(withDevice("/api/ingest/gps", deviceId), { fixes }),
  sendSensor: (deviceId, readings) => post(withDevice("/api/ingest/sensor", deviceId), { readings }),

  provisionDevice: (body) => post("/api/devices", body),
  logIncident: (body) => post("/api/incidents", body),
  startScenario: (body) => post("/api/demo/scenario", body)
};
