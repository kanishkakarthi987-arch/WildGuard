"""Alert dispatch: messages in English and Tamil, de-duplication, and the delivery channels.

Channels
  sms     every subscriber of the village          (dry_run | fast2sms | twilio)
  voice   subscribers flagged `voice`, Warning and Imminent only
          (feature phones and people who cannot read SMS)   (dry_run | twilio)
  beacon  a siren / LED controller on a webhook, Warning and Imminent only

"dry_run" records what would be sent without contacting anyone. The live providers have not
been exercised against the real services from this code: check each provider's current API,
sender registration (DLT in India) and Tamil text-to-speech support before relying on them.
"""

import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from xml.sax.saxutils import escape

from . import config, db
from .risk import TIER_RANK

log = logging.getLogger("wildguard.notify")

ANIMAL_TA = {"Elephant": "யானை", "Leopard": "சிறுத்தை"}
TIER_TA = {"Watch": "கவனம்", "Warning": "எச்சரிக்கை", "Imminent": "அவசரம்"}

ACTION_EN = {
    "Watch": "Stay alert and avoid forest paths after dark.",
    "Warning": "Keep children and livestock indoors. Avoid forest paths.",
    "Imminent": "Go indoors now. Keep lights on and do not approach the animal.",
}
ACTION_TA = {
    "Watch": "விழிப்புடன் இருங்கள், இரவில் காட்டுப் பாதைகளைத் தவிர்க்கவும்.",
    "Warning": "குழந்தைகளையும் கால்நடைகளையும் வீட்டிற்குள் வைத்திருங்கள். காட்டுப் பாதைகளைத் தவிர்க்கவும்.",
    "Imminent": "உடனே வீட்டிற்குள் செல்லுங்கள். விளக்குகளை எரிய விடுங்கள், விலங்கை நெருங்க வேண்டாம்.",
}

VALID_PHONE = re.compile(r"^[6-9]\d{9}$")
VOICE_LANG = {"en": "en-IN", "ta": "ta-IN"}


def build_messages(animal, village, tier, distance_km, eta_minutes):
    animal_ta = ANIMAL_TA.get(animal, animal)
    if eta_minutes is None:
        when_en, when_ta = "Its heading is not known yet, stay alert.", "அதன் திசை இன்னும் தெரியவில்லை, விழிப்புடன் இருங்கள்."
    elif eta_minutes == 0:
        when_en, when_ta = "It is at the village now.", "இப்போது கிராமத்தில் உள்ளது."
    else:
        when_en = f"Expected at the village in about {eta_minutes} min."
        when_ta = f"சுமார் {eta_minutes} நிமிடங்களில் கிராமத்தை அடையலாம்."
    en = (
        f"[WildGuard {tier.upper()}] {animal} detected {distance_km:.1f} km from {village}. "
        f"{when_en} {ACTION_EN[tier]}"
    )
    ta = (
        f"[WildGuard {TIER_TA[tier]}] {village} அருகே {animal_ta} "
        f"கண்டறியப்பட்டது ({distance_km:.1f} கி.மீ). {when_ta} {ACTION_TA[tier]}"
    )
    return en, ta


def spoken(text: str) -> str:
    """The same message without the [WildGuard TIER] tag, for text-to-speech."""
    return re.sub(r"^\[[^\]]*\]\s*", "", text)


# ----------------------------------------------------------------- providers


def _valid(numbers):
    return [n for n in numbers if VALID_PHONE.match(n)]


def _send_fast2sms(numbers, message):
    """Returns (ok, error). Not tested against the live API."""
    valid = _valid(numbers)
    if not valid:
        return True, None  # nothing real to send (the seeded placeholder numbers)
    body = json.dumps({"route": "q", "message": message, "numbers": ",".join(valid)}).encode()
    request = urllib.request.Request(
        "https://www.fast2sms.com/dev/bulkV2",
        data=body,
        headers={"authorization": config.FAST2SMS_API_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode())
        if payload.get("return"):
            return True, None
        return False, str(payload.get("message", "provider rejected the request"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return False, str(exc)


def _twilio_post(path: str, fields: dict):
    """One Twilio REST call (form-encoded, basic auth). Returns (ok, error). Not tested live."""
    url = f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/{path}.json"
    token = base64.b64encode(f"{config.TWILIO_ACCOUNT_SID}:{config.TWILIO_AUTH_TOKEN}".encode()).decode()
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(fields).encode(), headers={"Authorization": f"Basic {token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            return True, None
    except urllib.error.HTTPError as exc:
        return False, f"Twilio HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}"
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, str(exc)


def _twilio_configured() -> bool:
    return bool(config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and config.TWILIO_FROM)


def _twilio_sms(numbers, message):
    ok, error = True, None
    for number in _valid(numbers):
        sent, err = _twilio_post("Messages", {"To": f"+91{number}", "From": config.TWILIO_FROM, "Body": message})
        if not sent:
            ok, error = False, err
    return ok, error


def _twilio_call(numbers, text, language):
    twiml = f'<Response><Say language="{VOICE_LANG[language]}">{escape(text)}</Say></Response>'
    ok, error = True, None
    for number in _valid(numbers):
        sent, err = _twilio_post("Calls", {"To": f"+91{number}", "From": config.TWILIO_FROM, "Twiml": twiml})
        if not sent:
            ok, error = False, err
    return ok, error


def _post_json(url: str, payload: dict):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            return True, None
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, str(exc)


# ------------------------------------------------------------------ channels


def _send_sms(base, subscribers, en, ta):
    record = {**base, "channel": "sms", "provider": config.NOTIFY_PROVIDER, "recipients": len(subscribers)}
    provider = config.NOTIFY_PROVIDER
    if provider == "dry_run":
        log.info("DRY RUN SMS to %d subscribers of %s: %s", len(subscribers), base["village"], en)
        return db.add_notification({**record, "status": "dry_run"})
    if provider == "fast2sms" and not config.FAST2SMS_API_KEY:
        return db.add_notification({**record, "status": "failed", "error": "FAST2SMS_API_KEY is not set"})
    if provider == "twilio" and not _twilio_configured():
        return db.add_notification({**record, "status": "failed", "error": "Twilio settings are incomplete"})
    if provider not in ("fast2sms", "twilio"):
        return db.add_notification({**record, "status": "failed", "error": f"unknown NOTIFY_PROVIDER {provider!r}"})

    send = _send_fast2sms if provider == "fast2sms" else _twilio_sms
    ok, error = True, None
    for language, text in (("en", en), ("ta", ta)):
        numbers = [s["phone"] for s in subscribers if s["language"] == language]
        if numbers:
            sent, err = send(numbers, text)
            if not sent:
                ok, error = False, err
    return db.add_notification({**record, "status": "sent" if ok else "failed", "error": error})


def _send_voice(base, subscribers, en, ta):
    listeners = [s for s in subscribers if s.get("voice")]
    if not listeners:
        return None
    record = {**base, "channel": "voice", "provider": config.VOICE_PROVIDER, "recipients": len(listeners)}
    provider = config.VOICE_PROVIDER
    if provider == "dry_run":
        log.info("DRY RUN voice call to %d subscribers of %s", len(listeners), base["village"])
        return db.add_notification({**record, "status": "dry_run"})
    if provider != "twilio":
        return db.add_notification({**record, "status": "failed", "error": f"unknown VOICE_PROVIDER {provider!r}"})
    if not _twilio_configured():
        return db.add_notification({**record, "status": "failed", "error": "Twilio settings are incomplete"})
    ok, error = True, None
    for language, text in (("en", spoken(en)), ("ta", spoken(ta))):
        numbers = [s["phone"] for s in listeners if s["language"] == language]
        if numbers:
            sent, err = _twilio_call(numbers, text, language)
            if not sent:
                ok, error = False, err
    return db.add_notification({**record, "status": "sent" if ok else "failed", "error": error})


def _send_beacon(base, en):
    if not config.BEACON_WEBHOOK_URL:
        return None
    record = {**base, "channel": "beacon", "provider": "webhook", "recipients": 1}
    ok, error = _post_json(
        config.BEACON_WEBHOOK_URL, {"village": base["village"], "tier": base["tier"], "message": en}
    )
    return db.add_notification({**record, "status": "sent" if ok else "failed", "error": error})


def dispatch(event_id, event, tier, village, eta_minutes, distance_km, when=None):
    """Send (or dry-run) a tiered alert for `village`. Always logs a row.

    Returns the SMS record, with `voice` and `beacon` records attached when those fired.
    """
    en, ta = build_messages(event["animal"], village, tier, distance_km, eta_minutes)
    when = when or datetime.now()
    base = {
        "timestamp": db.fmt(when),
        "event_id": event_id,
        "village": village,
        "animal": event["animal"],
        "tier": tier,
        "message": en,
        "message_local": ta,
        "recipients": 0,
        "error": None,
    }

    # Alert-fatigue guard: a repeat alert at the same or a lower tier is suppressed.
    for earlier in db.recent_notifications(village, event["animal"], config.DEDUP_WINDOW_MIN, ref=when):
        if TIER_RANK.get(earlier["tier"], 0) >= TIER_RANK[tier]:
            # One suppressed row per event and tier, not one per GPS fix.
            return db.find_notification(event_id, tier, "suppressed") or db.add_notification(
                {**base, "channel": "sms", "provider": config.NOTIFY_PROVIDER, "status": "suppressed"}
            )

    subscribers = db.list_subscribers(village)
    if not subscribers:
        return db.add_notification(
            {**base, "channel": "sms", "provider": config.NOTIFY_PROVIDER, "status": "no_subscribers"}
        )

    sms = _send_sms(base, subscribers, en, ta)
    if tier in config.VOICE_TIERS:
        sms["voice"] = _send_voice(base, subscribers, en, ta)
        sms["beacon"] = _send_beacon(base, en)
    return sms
