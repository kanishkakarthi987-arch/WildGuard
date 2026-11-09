import React, { useEffect, useRef, useState } from "react";
import { api, auth } from "../api";

export default function SignInModal({ reason, onClose, onSuccess }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const input = useRef(null);

  useEffect(() => {
    input.current?.focus();
    const onKey = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async (event) => {
    event.preventDefault();
    const candidate = value.trim();
    if (!candidate) return;
    setChecking(true);
    setError("");
    try {
      if (await api.checkToken(candidate)) {
        auth.set(candidate);
        onSuccess();
      } else {
        setError("That token was not accepted.");
      }
    } catch (err) {
      setError(`Could not reach the backend: ${err.message}`);
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal" onSubmit={submit} onMouseDown={(e) => e.stopPropagation()}>
        <h2>Ranger sign-in</h2>
        <p className="hint">
          {reason ||
            "Simulating events, confirming alerts and managing subscribers need the ranger token."}
        </p>
        <p className="hint">
          The backend terminal prints “Admin token source” on start. If it shows a file path, open
          that file (normally <code>backend/data/admin_token.txt</code>) and paste the token. Or set
          your own with <code>WILDGUARD_ADMIN_TOKEN</code> in <code>backend/.env</code>.
        </p>

        <label htmlFor="ranger-token">Ranger token</label>
        <input
          id="ranger-token"
          ref={input}
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        {error && <p className="form-error">{error}</p>}

        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={checking || !value.trim()}>
            {checking ? "Checking…" : "Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}
