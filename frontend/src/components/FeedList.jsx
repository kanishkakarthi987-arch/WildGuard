import React from "react";
import { timeAgo } from "../utils";
import { Pill } from "./small";

const KIND_ICON = { camera: "📷", gps: "📍", collar: "📍", sensor: "📡", ground: "📡", lora: "📶" };
const STATUS_TONE = {
  accepted: "ok",
  no_wildlife: "neutral",
  duplicate: "neutral",
  rejected: "bad",
  error: "bad"
};

/** One line per thing a device sent. This is the proof that data is really arriving. */
export default function FeedList({ rows }) {
  if (!rows.length) {
    return <p className="empty">Nothing received yet. Upload an image, send a GPS fix, or run a scenario.</p>;
  }
  return (
    <div className="feed-list">
      {rows.map((row) => (
        <div key={row.id} className="feed-row">
          <span className="feed-icon">{KIND_ICON[row.kind] || "•"}</span>
          <div className="feed-body">
            <b>{row.device_id || "unknown device"}</b>
            <span>{row.summary}</span>
          </div>
          <div className="feed-meta">
            <Pill tone={STATUS_TONE[row.status] || "neutral"}>{String(row.status).replace("_", " ")}</Pill>
            <small>{timeAgo(row.timestamp)}</small>
          </div>
        </div>
      ))}
    </div>
  );
}
