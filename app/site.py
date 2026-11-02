import threading
import time
from datetime import datetime, timezone

from .distance_fetcher import SPACECRAFT, get_dsn_contact, get_position
from .emailer import STYLE, build_content, render_card
from .postcards import POSTCARD_DIR, POSTCARDS
from .visuals import render_map

# JPL and the DSN feed are public services, so visitors share one recent copy
# of the data instead of each page view calling them.
REFRESH_AFTER_S = 15 * 60
UNIT = "light_minute"

_snapshot = None
_refresh_lock = threading.Lock()

POSTCARD_IMAGES = {card["image"] for cards in POSTCARDS.values() for card in cards}

def _refresh():
    global _snapshot
    positions = {key: get_position(key) for key in SPACECRAFT}
    # Keep the last good data if JPL is unreachable for either spacecraft
    if not all(positions.values()):
        return
    contacts = {key: get_dsn_contact(key) for key in SPACECRAFT}
    maps = {}
    for key, position in positions.items():
        twin_key = next(k for k in SPACECRAFT if k != key)
        maps[key] = render_map(
            SPACECRAFT[key]["name"], position, STYLE[key]["rgb"],
            SPACECRAFT[twin_key]["name"], positions[twin_key],
        )
    _snapshot = {
        "fetched_at": time.time(),
        "positions": positions,
        "contacts": contacts,
        "maps": maps,
    }

def _refresh_in_background():
    try:
        _refresh()
    except Exception as e:
        print(f"Page data refresh failed: {e}")
    finally:
        _refresh_lock.release()

def get_snapshot():
    """Recent data, refreshed behind the scenes so visitors rarely wait."""
    if _snapshot is None:
        # The very first visitor has nothing to show yet, so wait for the data
        with _refresh_lock:
            if _snapshot is None:
                try:
                    _refresh()
                except Exception as e:
                    print(f"Page data refresh failed: {e}")
    elif time.time() - _snapshot["fetched_at"] > REFRESH_AFTER_S and _refresh_lock.acquire(blocking=False):
        threading.Thread(target=_refresh_in_background, daemon=True).start()
    return _snapshot

def get_map(spacecraft):
    snapshot = get_snapshot()
    if not snapshot:
        return None
    return snapshot["maps"].get(spacecraft)

def _web_colors(spacecraft):
    return {
        "background": "var(--background)",
        "card": "var(--card)",
        "panel": "var(--panel)",
        "line": "var(--line)",
        "text": "var(--text)",
        "soft": "var(--soft)",
        "faint": "var(--faint)",
        "accent": f"var(--{spacecraft.replace('_', '-')})",
    }

def _cards(snapshot):
    version = int(snapshot["fetched_at"])
    cards = []
    for key, position in snapshot["positions"].items():
        twin_key = next(k for k in SPACECRAFT if k != key)
        content = build_content(
            key, UNIT, position,
            twin_name=SPACECRAFT[twin_key]["name"],
            twin_position=snapshot["positions"][twin_key],
            contact=snapshot["contacts"][key],
        )
        cards.append(
            render_card(
                content,
                _web_colors(key),
                f"/images/map/{key}.jpg?v={version}",
                f"/images/postcards/{content['card']['image']}",
            )
        )
    return cards

STYLES = """
:root {
  color-scheme: light dark;
  --background: #f3f4f9;
  --card: #ffffff;
  --panel: #eef0f8;
  --line: #d9dce9;
  --text: #14172b;
  --soft: #474c66;
  --faint: #626781;
  --voyager-1: #99590a;
  --voyager-2: #0a6a99;
  --button: #14172b;
  --button-text: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --background: #05060e;
    --card: #10132a;
    --panel: #181c3a;
    --line: #2a2f4f;
    --text: #f2f3fa;
    --soft: #c3c7dc;
    --faint: #9195ad;
    --voyager-1: #f4b860;
    --voyager-2: #6fd3ff;
    --button: #f2f3fa;
    --button-text: #10132a;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--background);
  color: var(--text);
  font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
}
main { max-width: 1160px; margin: 0 auto; padding: 24px 16px 32px; }
header { max-width: 560px; margin: 0 auto 18px; }
h1 { font-family: Georgia, 'Times New Roman', serif; font-weight: normal; font-size: 30px; line-height: 36px; margin: 0 0 6px; }
.intro { margin: 0; color: var(--soft); font-size: 15px; line-height: 22px; }
.subscribe { max-width: 560px; margin: 0 auto 20px; background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; }
.subscribe label { display: block; font-size: 15px; font-weight: 600; margin-bottom: 3px; }
.subscribe .hint { margin: 0 0 11px; color: var(--soft); font-size: 13px; line-height: 19px; }
.fields { display: flex; gap: 8px; flex-wrap: wrap; }
.subscribe input[type=email] { flex: 1 1 200px; min-width: 0; height: 42px; padding: 0 12px; font: inherit; color: var(--text); background: var(--background); border: 1px solid var(--line); border-radius: 8px; }
.subscribe button { flex: 0 0 auto; height: 42px; padding: 0 18px; font: inherit; font-weight: 600; color: var(--button-text); background: var(--button); border: 0; border-radius: 8px; cursor: pointer; }
.subscribe button:disabled { opacity: 0.6; cursor: default; }
.subscribe input:focus-visible, .subscribe button:focus-visible { outline: 2px solid var(--voyager-2); outline-offset: 2px; }
.message { margin: 10px 0 0; font-size: 13px; line-height: 19px; color: var(--soft); min-height: 19px; }
.trap { position: absolute; left: -9999px; }
.cards { display: grid; grid-template-columns: minmax(0, 560px); justify-content: center; gap: 20px; align-items: start; }
@media (min-width: 1160px) { .cards { grid-template-columns: repeat(2, minmax(0, 560px)); } }
.updated { text-align: center; margin: 20px 0 0; color: var(--faint); font-size: 12px; }
.unavailable { max-width: 560px; margin: 0 auto; text-align: center; color: var(--soft); }
"""

SCRIPT = """
const form = document.getElementById('subscribe');
const message = document.getElementById('message');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  message.textContent = 'Sending...';
  try {
    const response = await fetch('/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: form.email.value, company: form.company.value}),
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok) {
      message.textContent = data.message;
      form.reset();
    } else if (response.status === 422) {
      message.textContent = 'That email address does not look right. Check it and try again.';
    } else {
      message.textContent = data.detail || 'That did not work. Try again in a moment.';
    }
  } catch (error) {
    message.textContent = 'That did not work. Check your connection and try again.';
  }
  button.disabled = false;
});
"""

def render_page():
    snapshot = get_snapshot()
    if snapshot:
        updated = datetime.fromtimestamp(snapshot["fetched_at"], timezone.utc).strftime("%d %b %Y, %H:%M UTC")
        body = (
            f'<div class="cards">{"".join(f"<article>{card}</article>" for card in _cards(snapshot))}</div>'
            f'<p class="updated">Data updated {updated}</p>'
        )
    else:
        body = '<p class="unavailable">NASA\'s data is out of reach right now. Check back soon.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Voyager, right now</title>
<meta name="description" content="Where Voyager 1 and Voyager 2 are today, from live NASA data. Subscribe to get an email as they travel farther.">
<style>{STYLES}</style>
</head>
<body>
<main>
<header>
<h1>Voyager, right now</h1>
<p class="intro">The two farthest spacecraft ever launched are still talking to us. Here's where they are today.</p>
</header>
<form class="subscribe" id="subscribe">
<label for="email">Get these updates by email</label>
<p class="hint">One email each time a Voyager travels another light-minute, about one a week in total.</p>
<div class="fields">
<input type="email" id="email" name="email" required autocomplete="email" placeholder="you@example.com">
<input class="trap" type="text" name="company" tabindex="-1" autocomplete="off" aria-hidden="true">
<button type="submit">Subscribe</button>
</div>
<p class="message" id="message" role="status"></p>
<noscript><p class="message">Subscribing needs JavaScript turned on.</p></noscript>
</form>
{body}
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""
