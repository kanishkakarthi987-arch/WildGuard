import React from "react";
import ReactDOM from "react-dom/client";

import "./leafletSetup";
import App from "./App";
import "./styles/app.css";
import "./styles/live.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
