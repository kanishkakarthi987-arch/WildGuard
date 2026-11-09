import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_BASE, soft } from "../api";
import { setServerOffset } from "../utils";

const EMPTY = {
  config: null,
  sightings: [],
  statistics: {},
  alerts: [],
  predictions: [],
  sensors: { sensors: [] },
  notifications: [],
  tracks: [],
  readings: [],
  zones: { cells: [] },
  feed: [],
  health: {}
};

const FALLBACK_POLL_MS = 10000; // used only when the live stream is unavailable
const SAFETY_POLL_MS = 60000; // slow catch-up even while the stream is healthy
const BURST_DEBOUNCE_MS = 250; // collapse a burst of writes into one refresh

/**
 * Loads everything the dashboard shows and keeps it fresh.
 *
 * The backend pushes a Server-Sent Event each time anything is written (camera upload,
 * GPS fix, sensor reading, simulation, ranger action), so new detections appear within
 * a second with no constant polling. If the stream drops, the browser reconnects by
 * itself and a polling fallback keeps the data moving in the meantime.
 *
 * live: "connecting" | "live" | "reconnecting" | "polling"
 */
export function useWildGuard() {
  const [data, setData] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [live, setLive] = useState("connecting");
  const [lastUpdate, setLastUpdate] = useState(null);
  const configRef = useRef(null);
  const inFlight = useRef(false);
  const queued = useRef(false);

  const refresh = useCallback(async () => {
    // If a refresh is already running, remember that another one was asked for.
    if (inFlight.current) {
      queued.current = true;
      return;
    }
    inFlight.current = true;
    try {
      if (!configRef.current) {
        configRef.current = await api.config();
        setServerOffset(configRef.current.utc_offset_minutes);
      }
      const [
        sightings, statistics, alerts, predictions, sensors, notifications,
        tracks, readings, zones, feed, health
      ] = await Promise.all([
        api.sightings(),
        api.statistics(),
        api.alerts(),
        api.predictions(),
        api.sensors(),
        api.notifications(),
        // Extras: a failure here (for example an older backend) must not blank the dashboard.
        soft(api.tracks(), []),
        soft(api.groundReadings(), []),
        soft(api.riskZones(), { cells: [] }),
        soft(api.feed(), []),
        soft(api.health(), {})
      ]);
      setData({
        config: configRef.current,
        sightings,
        statistics,
        alerts,
        predictions,
        sensors,
        notifications,
        tracks,
        readings,
        zones,
        feed,
        health
      });
      setError(null);
      setLastUpdate(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      inFlight.current = false;
      setLoaded(true);
      if (queued.current) {
        queued.current = false;
        refresh();
      }
    }
  }, []);

  useEffect(() => {
    let stream = null;
    let debounce = null;
    let cancelled = false;

    const onWrite = () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        if (!cancelled) refresh();
      }, BURST_DEBOUNCE_MS);
    };

    refresh();

    if (typeof EventSource === "undefined") {
      setLive("polling");
    } else {
      stream = new EventSource(`${API_BASE}/api/stream`);
      stream.onopen = () => {
        setLive("live");
        refresh(); // catch anything written while the stream was down
      };
      stream.onmessage = onWrite;
      stream.onerror = () => {
        setLive("reconnecting"); // EventSource retries on its own, every few seconds
        refresh(); // find out right away whether the backend is really down (shows the banner)
      };
    }

    const timer = setInterval(
      refresh,
      stream ? SAFETY_POLL_MS : FALLBACK_POLL_MS
    );

    return () => {
      cancelled = true;
      clearTimeout(debounce);
      clearInterval(timer);
      if (stream) stream.close();
    };
  }, [refresh]);

  return { data, error, loaded, live, lastUpdate, refresh };
}
