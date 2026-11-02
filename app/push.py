import json
import os
from urllib.parse import urlparse

from .emailer import APP_BASE_URL, DISTANCE_UNITS, LIGHT_DAY_KM, LIGHT_SPEED_KM_S
from .distance_fetcher import SPACECRAFT
from .models import PushState, PushSubscription

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
UNIT_KM = DISTANCE_UNITS["light_minute"]

# The server sends requests to the address a browser gives it, so only accept the
# browser makers' push services. Otherwise anyone could point it at any address.
ALLOWED_PUSH_HOSTS = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "updates.push.services.mozilla.com",
    ".push.apple.com",
    ".notify.windows.com",
)

def enabled():
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)

def is_allowed_endpoint(endpoint):
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    if parsed.scheme != "https":
        return False
    return any(host == allowed or (allowed.startswith(".") and host.endswith(allowed)) for allowed in ALLOWED_PUSH_HOSTS)

def send(subscription, title, body):
    """Send one notification. Returns False if the browser has gone away for good."""
    # Loaded only when sending, since this library is large for a small machine
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps({"title": title, "body": body, "url": "/"}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": APP_BASE_URL},
            ttl=86400,
            timeout=20,
        )
    except WebPushException as e:
        status = e.response.status_code if e.response is not None else None
        if status in (404, 410):
            return False
        print(f"Notification failed with status {status}")
    return True

def _signal_text(earth_km):
    minutes = int(earth_km / LIGHT_SPEED_KM_S // 60)
    return f"{minutes // 60}h {minutes % 60:02d}m"

def message_for(spacecraft, position, previous_sun_km, farthest_earth_km):
    """The notification this position calls for, as (title, body), or None."""
    name = SPACECRAFT[spacecraft]["name"]
    days = int(position["earth_km"] // LIGHT_DAY_KM)
    if days > int(farthest_earth_km // LIGHT_DAY_KM):
        distance = "one light-day" if days == 1 else f"{days} light-days"
        return f"{name} is now {distance} from Earth", f"Its signal now takes {_signal_text(position['earth_km'])} to reach us."
    minutes = int(position["sun_km"] // UNIT_KM)
    if minutes > int(previous_sun_km // UNIT_KM):
        return f"{name} passed light-minute {minutes:,}", f"Its signal now takes {_signal_text(position['earth_km'])} to reach Earth."
    return None

def notify_subscribers(db, spacecraft, position):
    """Tell subscribers about a new light-minute or light-day, once for everyone."""
    state = db.query(PushState).filter_by(spacecraft=spacecraft).first()
    if state is None:
        # Only record a starting point, so nobody hears about old news
        db.add(PushState(spacecraft=spacecraft, last_km=position["sun_km"], farthest_earth_km=position["earth_km"]))
        db.commit()
        return

    message = message_for(spacecraft, position, state.last_km, state.farthest_earth_km)
    state.farthest_earth_km = max(state.farthest_earth_km, position["earth_km"])
    if message:
        state.last_km = position["sun_km"]
        # Save first, so a crash partway can't repeat it to everyone at the next check
        db.commit()
        if enabled():
            for subscription in db.query(PushSubscription).all():
                try:
                    if not send(subscription, *message):
                        db.delete(subscription)
                except Exception as e:
                    print(f"Notification failed: {type(e).__name__}")
    db.commit()
