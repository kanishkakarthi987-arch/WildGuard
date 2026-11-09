import React from "react";
import PredictionCard from "../components/PredictionCard";
import { PageHeader, Panel } from "../components/small";

export default function Predictions({ data }) {
  return (
    <div>
      <PageHeader
        title="Movement Predictions"
        subtitle="A Kalman filter smooths each track, estimates velocity, and projects it toward the villages."
      />
      <Panel>
        {data.predictions.length === 0 ? (
          <p className="empty">No predictions available.</p>
        ) : (
          <div className="prediction-grid">
            {data.predictions.map((p) => (
              <PredictionCard key={p.event_id} prediction={p} />
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
