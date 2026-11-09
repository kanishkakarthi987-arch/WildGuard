import React, { useCallback, useRef, useState } from "react";
import { api, auth } from "./api";
import Sidebar from "./components/Sidebar";
import SignInModal from "./components/SignInModal";
import { ToastHost } from "./components/small";
import { useWildGuard } from "./hooks/useWildGuard";
import Alerts from "./pages/Alerts";
import Dashboard from "./pages/Dashboard";
import Evaluation from "./pages/Evaluation";
import LiveFeed from "./pages/LiveFeed";
import MapPage from "./pages/MapPage";
import Predictions from "./pages/Predictions";
import Sensors from "./pages/Sensors";
import Simulation from "./pages/Simulation";
import { summarize } from "./utils";

const PAGE_COMPONENTS = {
  dashboard: Dashboard,
  map: MapPage,
  live: LiveFeed,
  simulation: Simulation,
  alerts: Alerts,
  sensors: Sensors,
  predictions: Predictions,
  evaluation: Evaluation
};

let toastId = 0;

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [signedIn, setSignedIn] = useState(Boolean(auth.get()));
  const [signInReason, setSignInReason] = useState(null); // null = closed
  const { data, error, loaded, live, refresh } = useWildGuard();

  const dismiss = useCallback((id) => setToasts((all) => all.filter((t) => t.id !== id)), []);

  const toast = useCallback(
    (text, kind = "info") => {
      const id = ++toastId;
      setToasts((all) => [...all, { id, text, kind }]);
      setTimeout(() => dismiss(id), 6000);
    },
    [dismiss]
  );

  const signOut = useCallback(() => {
    auth.clear();
    setSignedIn(false);
  }, []);

  // Runs a ranger action. Without a token it opens the sign-in box instead of failing with a 401,
  // and runs the action once the ranger has signed in, so nothing has to be clicked twice.
  const pendingAction = useRef(null);

  // opts: describe(result) -> toast text, kind(result) -> "alert" | "info", onResult(result).
  // Returns the result, or undefined if the action failed or is waiting for sign-in.
  const run = useCallback(
    async (call, failure, opts = {}) => {
      if (!auth.get()) {
        pendingAction.current = { call, failure, opts };
        setSignInReason("Sign in with the ranger token to do this.");
        return undefined;
      }
      setBusy(true);
      try {
        const result = await call();
        await refresh();
        const text = (opts.describe || summarize)(result);
        const kind = opts.kind ? opts.kind(result) : result?.event?.alert_tier ? "alert" : "info";
        toast(text, kind);
        if (opts.onResult) opts.onResult(result);
        return result;
      } catch (err) {
        if (err.status === 401) {
          signOut();
          setSignInReason("The ranger token was rejected. Sign in again.");
        } else {
          toast(`${failure}: ${err.message}`, "error");
        }
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast, signOut]
  );

  const actions = {
    busy,
    run,
    simulate: (form) => run(() => api.simulate(form), "Simulation failed"),
    emergency: () => run(() => api.emergency(), "Emergency simulation failed"),
    verify: (id, action) => run(() => api.verify(id, action), "Verification failed")
  };

  if (!loaded) {
    return (
      <div className="loading-screen">
        <div className="loading-logo">🐾</div>
        <h1>WildGuard</h1>
        <p>Connecting to the early-warning backend…</p>
      </div>
    );
  }

  if (!data.config) {
    return (
      <div className="loading-screen">
        <div className="loading-logo">🔌</div>
        <h1>Backend unreachable</h1>
        <p>
          {error}. Start it with: uvicorn app.main:app --reload (from the backend folder). Retrying
          automatically.
        </p>
      </div>
    );
  }

  const Page = PAGE_COMPONENTS[page];

  return (
    <div className="app">
      <Sidebar
        page={page}
        setPage={setPage}
        backendError={error}
        live={live}
        pending={data.statistics.pending_verification || 0}
        signedIn={signedIn}
        onSignIn={() => setSignInReason("")}
        onSignOut={signOut}
      />
      <main className="main">
        {error && (
          <div className="error-banner">
            Lost connection to the backend ({error}). Showing the last data received.
          </div>
        )}
        <Page data={data} actions={actions} />
      </main>
      <ToastHost toasts={toasts} dismiss={dismiss} />
      {signInReason !== null && (
        <SignInModal
          reason={signInReason}
          onClose={() => {
            pendingAction.current = null; // cancelled: do not run it later
            setSignInReason(null);
          }}
          onSuccess={() => {
            setSignedIn(true);
            setSignInReason(null);
            toast("Signed in as ranger.");
            const pending = pendingAction.current;
            pendingAction.current = null;
            if (pending) run(pending.call, pending.failure, pending.opts);
          }}
        />
      )}
    </div>
  );
}
