"""Server-side animal detection with Ultralytics YOLO (optional dependency).

The default COCO model (yolov8n.pt) detects elephants but has no leopard class. For leopards,
point WILDGUARD_MODEL at weights fine-tuned on camera-trap images (for example from LILA BC).
Any class whose name contains "elephant", "leopard" or "panther" is mapped to a species.

Edge devices can run this same model locally and send only the detections to
/api/ingest/detection, which is the better design on poor connections.
"""

from __future__ import annotations

import importlib.util
import io
import threading
from pathlib import Path

from . import config

SPECIES_BY_NAME = {"elephant": "Elephant", "leopard": "Leopard", "panther": "Leopard"}

_model = None
_lock = threading.Lock()


class DetectorUnavailable(RuntimeError):
    pass


def species_for(label: str) -> str | None:
    lowered = label.lower()
    for key, species in SPECIES_BY_NAME.items():
        if key in lowered:
            return species
    return None


def is_installed() -> bool:
    return importlib.util.find_spec("ultralytics") is not None


def _weights_path() -> str:
    path = Path(config.DETECTOR_MODEL)
    if path.is_absolute() or path.exists():
        return str(path)
    return str(config.BASE_DIR / "models" / path.name)


def _load():
    global _model
    with _lock:
        if _model is None:
            if not is_installed():
                raise DetectorUnavailable(
                    "Ultralytics is not installed. Run: pip install -r requirements-ml.txt "
                    "(or send detections from an edge device, or label the upload manually)."
                )
            from ultralytics import YOLO

            weights = _weights_path()
            Path(weights).parent.mkdir(parents=True, exist_ok=True)
            _model = YOLO(weights)
        return _model


def info() -> dict:
    mapped = []
    if _model is not None:
        mapped = sorted(
            {species_for(name) for name in _model.names.values() if species_for(name)}
        )
    return {
        "installed": is_installed(),
        "loaded": _model is not None,
        "model": config.DETECTOR_MODEL,
        "species_detected": mapped,
        "note": "Default COCO weights detect elephants only. Use custom weights for leopards.",
    }


def detect(image_bytes: bytes) -> list[dict]:
    """Return wildlife detections [{species, confidence, box, label}], best first."""
    from PIL import Image

    model = _load()
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    detections = []
    for result in model.predict(image, conf=config.DETECTOR_MIN_CONF, verbose=False):
        for box in result.boxes:
            label = result.names[int(box.cls[0])]
            species = species_for(label)
            if species:
                detections.append({
                    "species": species,
                    "confidence": round(float(box.conf[0]), 2),
                    "label": label,
                    "box": [round(float(v), 1) for v in box.xyxy[0].tolist()],
                })
    return sorted(detections, key=lambda d: d["confidence"], reverse=True)
