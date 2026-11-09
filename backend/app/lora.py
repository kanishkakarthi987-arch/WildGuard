"""Compact binary frames for LoRa / LoRaWAN uplinks, where every byte costs airtime.

A LoRaWAN network server (ChirpStack, The Things Network) forwards uplinks to
POST /api/ingest/lora as hex strings. All numbers are big-endian.

  byte 0      version, 1
  byte 1      kind: 1 = GPS fix, 2 = ground reading, 3 = camera detection
  bytes 2-3   lora_id of the device (set when the device is provisioned)
  bytes 4-7   unix time in seconds, UTC

  GPS fix (18 bytes)     8-11 latitude  int32, degrees * 1e6
                         12-15 longitude int32, degrees * 1e6
                         16 species, 17 animal number (the collared animal is "E-<number>")
  Ground reading (11)    8 sensor kind: 1 seismic, 2 acoustic, 3 pir, 4 fence
                         9-10 value uint16, value * 100
  Detection (11)         8 species, 9 confidence 0-100, 10 count

Species: 1 = Elephant, 2 = Leopard. This format is this project's own; it is not a standard.
Tested here with encode/decode round trips and the API, not with real LoRa hardware.
"""

from __future__ import annotations

import struct
from datetime import datetime

from . import db, ingest

VERSION = 1
KIND_GPS, KIND_GROUND, KIND_DETECTION = 1, 2, 3
SPECIES = {1: "Elephant", 2: "Leopard"}
SPECIES_CODE = {v: k for k, v in SPECIES.items()}
SENSOR_KINDS = {1: "seismic", 2: "acoustic", 3: "pir", 4: "fence"}
SENSOR_CODE = {v: k for k, v in SENSOR_KINDS.items()}
DEVICE_KIND = {KIND_GPS: "collar", KIND_GROUND: "ground", KIND_DETECTION: "camera"}

_HEADER = struct.Struct(">BBHI")


# ------------------------------------------------------------------ encoding


def _header(kind: int, lora_id: int, unix: int) -> bytes:
    return _HEADER.pack(VERSION, kind, lora_id, unix)


def encode_gps(lora_id: int, unix: int, lat: float, lon: float, species: str, animal_no: int) -> bytes:
    return _header(KIND_GPS, lora_id, unix) + struct.pack(
        ">iiBB", round(lat * 1e6), round(lon * 1e6), SPECIES_CODE[species], animal_no
    )


def encode_ground(lora_id: int, unix: int, kind: str, value: float) -> bytes:
    return _header(KIND_GROUND, lora_id, unix) + struct.pack(">BH", SENSOR_CODE[kind], round(value * 100))


def encode_detection(lora_id: int, unix: int, species: str, confidence: float, count: int = 1) -> bytes:
    return _header(KIND_DETECTION, lora_id, unix) + struct.pack(
        ">BBB", SPECIES_CODE[species], round(confidence * 100), count
    )


# ------------------------------------------------------------------ decoding


def decode(frame: bytes) -> dict:
    """Parse one frame into a plain dict. Raises ValueError on anything malformed."""
    if len(frame) < _HEADER.size:
        raise ValueError("frame too short")
    version, kind, lora_id, unix = _HEADER.unpack_from(frame)
    if version != VERSION:
        raise ValueError(f"unsupported frame version {version}")
    body = frame[_HEADER.size:]
    out = {"kind": kind, "lora_id": lora_id, "timestamp": datetime.fromtimestamp(unix)}
    if kind == KIND_GPS:
        if len(body) != 10:
            raise ValueError("GPS frame must be 18 bytes")
        lat, lon, species, number = struct.unpack(">iiBB", body)
        if species not in SPECIES:
            raise ValueError(f"unknown species code {species}")
        out.update(lat=lat / 1e6, lon=lon / 1e6, species=SPECIES[species], animal_id=f"{SPECIES[species][0]}-{number}")
    elif kind == KIND_GROUND:
        if len(body) != 3:
            raise ValueError("ground frame must be 11 bytes")
        sensor, value = struct.unpack(">BH", body)
        if sensor not in SENSOR_KINDS:
            raise ValueError(f"unknown sensor kind {sensor}")
        out.update(sensor_kind=SENSOR_KINDS[sensor], value=value / 100)
    elif kind == KIND_DETECTION:
        if len(body) != 3:
            raise ValueError("detection frame must be 11 bytes")
        species, confidence, count = struct.unpack(">BBB", body)
        if species not in SPECIES or confidence > 100 or count < 1:
            raise ValueError("bad detection fields")
        out.update(species=SPECIES[species], confidence=confidence / 100, count=count)
    else:
        raise ValueError(f"unknown frame kind {kind}")
    return out


def process(frames_hex: list[str]) -> list[dict]:
    """Decode and ingest each frame. One bad frame never blocks the rest of the batch."""
    results = []
    for index, text in enumerate(frames_hex):
        try:
            try:
                frame = bytes.fromhex(text.strip())
            except ValueError:
                raise ValueError("not valid hex") from None
            parsed = decode(frame)
            device = db.get_device_by_lora_id(parsed["lora_id"])
            if device is None:
                raise ValueError(f"no device has lora_id {parsed['lora_id']}")
            if device["kind"] != DEVICE_KIND[parsed["kind"]]:
                raise ValueError(f"{device['id']} is a {device['kind']} device, frame is for a {DEVICE_KIND[parsed['kind']]}")

            if parsed["kind"] == KIND_GPS:
                outcome = ingest.ingest_gps(device, [{
                    "animal_id": parsed["animal_id"], "species": parsed["species"],
                    "lat": parsed["lat"], "lon": parsed["lon"], "timestamp": parsed["timestamp"],
                }])
            elif parsed["kind"] == KIND_GROUND:
                outcome = ingest.ingest_sensor(device, [{
                    "kind": parsed["sensor_kind"], "value": parsed["value"], "timestamp": parsed["timestamp"],
                }])
            else:
                outcome = ingest.ingest_detection(
                    device, species=parsed["species"], confidence=parsed["confidence"],
                    ts=ingest.parse_ts(parsed["timestamp"]), count=parsed["count"],
                )
            results.append({"index": index, "ok": True, "device": device["id"], "kind": DEVICE_KIND[parsed["kind"]]})
        except (ValueError, ingest.IngestError) as exc:  # IngestError is a ValueError, listed for clarity
            results.append({"index": index, "ok": False, "error": str(exc)})
    return results
