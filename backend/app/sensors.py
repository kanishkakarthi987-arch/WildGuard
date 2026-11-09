"""Simulated ground-sensor readings and how they feed the risk score."""

import random


def generate_sensors(animal, rng=random, now_str=""):
    if animal == "Elephant":
        acoustic = rng.choice(["HIGH", "HIGH", "MEDIUM"])
        vibration = rng.choice(["HIGH", "MEDIUM"])
    elif animal == "Leopard":
        acoustic = rng.choice(["LOW", "MEDIUM"])
        vibration = rng.choice(["LOW", "MEDIUM"])
    else:
        acoustic = rng.choice(["LOW", "MEDIUM", "HIGH"])
        vibration = rng.choice(["LOW", "MEDIUM", "HIGH"])
    return {
        "temperature": round(rng.uniform(24, 32), 1),
        "motion": rng.choice(["DETECTED", "DETECTED", "NORMAL"]),
        "vibration": vibration,
        "acoustic": acoustic,
        "pir": rng.choice(["TRIGGERED", "NORMAL", "TRIGGERED"]),
        "battery": rng.randint(70, 99),
        "timestamp": now_str,
    }


_LEVEL = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def sensor_activity(animal, data):
    """Elephants are loud and heavy (acoustic/seismic); leopards show up on PIR/motion."""
    if animal == "Elephant":
        level = max(_LEVEL.get(data.get("acoustic"), 0), _LEVEL.get(data.get("vibration"), 0))
        return ["LOW", "MEDIUM", "HIGH"][level]
    hits = int(data.get("pir") == "TRIGGERED") + int(data.get("motion") == "DETECTED")
    return ["LOW", "MEDIUM", "HIGH"][hits]
