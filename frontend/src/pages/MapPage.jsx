import React, { useState } from "react";
import WildlifeMap from "../components/WildlifeMap";
import { PageHeader, Panel } from "../components/small";

export default function MapPage({ data }) {
  const [hours, setHours] = useState(24);
  return (
    <div>
      <PageHeader title="Wildlife Movement Map" subtitle="Risk zones, collar and camera tracks, ground sensors, detections and predicted paths (dashed)">
        <label className="inline-field">
          Show
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            <option value={6}>Last 6 hours</option>
            <option value={24}>Last 24 hours</option>
            <option value={24 * 7}>Last 7 days</option>
          </select>
        </label>
      </PageHeader>
      <Panel className="map-panel">
        <WildlifeMap
          config={data.config}
          sightings={data.sightings}
          predictions={data.predictions}
          tracks={data.tracks}
          devices={data.sensors.sensors}
          readings={data.readings}
          zones={data.zones}
          hours={hours}
          className="map large-map"
        />
      </Panel>
    </div>
  );
}
