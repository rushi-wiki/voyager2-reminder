import threading
import time
from datetime import datetime, timezone
from html import escape

from .distance_fetcher import SPACECRAFT, get_dsn_contact, get_position
from .emailer import STYLE, build_content, light_day_progress
from .postcards import POSTCARDS
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

def _detail(label, text):
    if not text:
        return ""
    return f'<div class="detail"><h3>{escape(label)}</h3><p>{escape(text)}</p></div>'

def _panel(key, content, position, snapshot, active):
    """One spacecraft, with the same facts as its email, arranged for a wider screen."""
    css_name = key.replace("_", "-")
    card = content["card"]
    version = int(snapshot["fetched_at"])
    rate = position["earth_km_s"]
    direction = "growing" if rate >= 0 else "shrinking"

    progress = ""
    light_day = light_day_progress(content["signal_s"])
    if light_day:
        label, percent = light_day
        progress = f"""
        <div class="progress">
          <div class="progress-label"><span>The road to {label} from Earth</span><strong>{percent:.1f}%</strong></div>
          <div class="progress-track"><div class="progress-fill" style="width:{min(99.5, percent):.1f}%"></div></div>
        </div>"""

    return f"""<div role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}" class="panel"{"" if active else " data-inactive"} data-craft="{css_name}">
  <figure class="tile map">
    <img src="/images/map/{key}.jpg?v={version}" width="1120" height="620" alt="Map showing {escape(content['name'])} and its twin far beyond the planets, at {content['au']:.1f} AU from the Sun">
  </figure>
  <section class="tile readout">
    <p class="eyebrow"><strong>{escape(content['name'])}</strong> &middot; {escape(content['unit_label'].capitalize())} {content['count']:,} from the Sun</p>
    <p class="signal">{content['signal']}</p>
    <p class="signal-note">for its signal to reach Earth</p>
    <p class="lead">{escape(content['lead'])}</p>
    <div class="odometer">
      <span class="odometer-value" data-km="{position['earth_km']:.0f}" data-rate="{rate:.4f}" data-at="{version}">{position['earth_km']:,.0f}</span>
      <span class="odometer-note">km from Earth, {direction} by {abs(rate):.1f} km every second</span>
    </div>
    <div class="stats">
      <div><strong>{content['au']:.1f}</strong><span>AU from the Sun</span></div>
      <div><strong>{content['billion_km']:.1f}</strong><span>billion km from Earth</span></div>
      <div><strong>{content['years']}y {content['months']}m</strong><span>in flight</span></div>
    </div>{progress}
  </section>
  <article class="tile story">
    <img src="/images/postcards/{card['image']}" alt="{escape(card['alt'])}" loading="lazy">
    <div class="story-text">
      <p class="eyebrow">From the Voyager archive</p>
      <h2>{escape(card['title'])}</h2>
      <p>{escape(card['story'])}</p>
      <p class="credit">Image: NASA/JPL</p>
    </div>
  </article>
  <section class="tile details">
    {_detail("Heard right now", content['heard'])}
    {_detail("Why the number is changing", content['speed'])}
    {_detail("Meanwhile, its twin", content['twin'])}
    <p class="next">{escape(content['next_text'])}</p>
  </section>
</div>"""

def _tabs(snapshot):
    """One spacecraft at a time. Without JavaScript, the page shows both in turn."""
    buttons = []
    panels = []
    for i, (key, position) in enumerate(snapshot["positions"].items()):
        twin_key = next(k for k in SPACECRAFT if k != key)
        content = build_content(
            key, UNIT, position,
            twin_name=SPACECRAFT[twin_key]["name"],
            twin_position=snapshot["positions"][twin_key],
            contact=snapshot["contacts"][key],
        )
        buttons.append(
            f'<button type="button" role="tab" id="tab-{key}" aria-controls="panel-{key}" '
            f'aria-selected="{"true" if i == 0 else "false"}" tabindex="{0 if i == 0 else -1}" class="tab {key.replace("_", "-")}">'
            f'<span class="tab-name">{escape(content["name"])}</span><span class="tab-signal">{content["signal"]}</span></button>'
        )
        panels.append(_panel(key, content, position, snapshot, i == 0))
    updated = datetime.fromtimestamp(snapshot["fetched_at"], timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    return (
        '<div class="toolbar">'
        f'<div role="tablist" aria-label="Choose a spacecraft" class="tabs">{"".join(buttons)}</div>'
        f'<p class="updated">NASA data from {updated}</p>'
        f'</div>{"".join(panels)}'
    )

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
body { margin: 0; background: var(--background); color: var(--text); font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
p, h1, h2, h3, figure { margin: 0; }
.page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
  display: grid;
  gap: 14px;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "intro" "content" "signup";
}
.intro { grid-area: intro; }
h1 { font-family: Georgia, 'Times New Roman', serif; font-weight: normal; font-size: 28px; line-height: 34px; }
.intro p { margin-top: 3px; color: var(--soft); font-size: 14px; line-height: 20px; }
.signup-link { display: inline-block; margin-top: 4px; color: var(--text); font-size: 14px; line-height: 24px; }
.content { grid-area: content; min-width: 0; }

.subscribe { grid-area: signup; background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; scroll-margin-top: 12px; }
.subscribe label { display: block; font-size: 13px; line-height: 18px; color: var(--soft); margin-bottom: 7px; }
.subscribe label strong { color: var(--text); }
.fields { display: flex; gap: 8px; }
.subscribe input[type=email] { flex: 1 1 auto; min-width: 0; height: 38px; padding: 0 11px; font: inherit; font-size: 14px; color: var(--text); background: var(--background); border: 1px solid var(--line); border-radius: 8px; }
.subscribe button { flex: 0 0 auto; height: 38px; padding: 0 15px; font: inherit; font-size: 14px; font-weight: 600; color: var(--button-text); background: var(--button); border: 0; border-radius: 8px; cursor: pointer; }
.subscribe button:disabled { opacity: 0.6; cursor: default; }
.message { margin-top: 7px; font-size: 13px; line-height: 18px; color: var(--soft); }
.message:empty { display: none; }
.trap { position: absolute; left: -9999px; }

.toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px 14px; margin-bottom: 12px; }
.tabs { display: none; gap: 4px; padding: 4px; background: var(--panel); border-radius: 11px; flex: 1 1 100%; }
.js .tabs { display: flex; }
.tab { flex: 1 1 0; min-width: 0; min-height: 46px; padding: 4px 16px; font: inherit; color: var(--soft); background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
.tab-name { display: block; font-size: 14px; line-height: 18px; font-weight: 600; }
.tab-signal { display: block; font-family: Consolas, Menlo, 'Courier New', monospace; font-size: 12px; line-height: 16px; }
.tab:hover { color: var(--text); }
.tab[aria-selected="true"] { background: var(--card); color: var(--text); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.18); }
.tab.voyager-1[aria-selected="true"] .tab-name { color: var(--voyager-1); }
.tab.voyager-2[aria-selected="true"] .tab-name { color: var(--voyager-2); }
.tab:focus-visible, .subscribe input:focus-visible, .subscribe button:focus-visible { outline: 2px solid var(--voyager-2); outline-offset: 2px; }
.updated { color: var(--faint); font-size: 12px; line-height: 16px; }

.panel { display: grid; gap: 12px; grid-template-columns: minmax(0, 1fr); margin-bottom: 12px; }
.js .panel[data-inactive] { display: none; }
.panel[data-craft="voyager-1"] { --accent: var(--voyager-1); }
.panel[data-craft="voyager-2"] { --accent: var(--voyager-2); }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; min-width: 0; }
.map { background: #070913; border-color: #070913; }
.map img { display: block; width: 100%; height: 100%; object-fit: cover; }

.readout { padding: 16px; display: flex; flex-direction: column; }
.eyebrow { font-size: 13px; line-height: 18px; color: var(--soft); }
.eyebrow strong { color: var(--accent); }
.signal { margin-top: 4px; font-family: Consolas, Menlo, 'Courier New', monospace; font-weight: bold; font-size: 36px; line-height: 42px; }
.signal-note { color: var(--soft); font-size: 13px; line-height: 18px; }
.lead { margin-top: 10px; font-family: Georgia, 'Times New Roman', serif; font-size: 15px; line-height: 22px; }
.odometer { margin-top: 12px; padding-top: 11px; border-top: 1px solid var(--line); }
.odometer-value { display: block; font-family: Consolas, Menlo, 'Courier New', monospace; font-size: 19px; line-height: 24px; font-weight: bold; font-variant-numeric: tabular-nums; color: var(--accent); }
.odometer-note { display: block; font-size: 12px; line-height: 17px; color: var(--soft); }
.stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-top: 12px; padding: 9px 6px; background: var(--panel); border-radius: 9px; text-align: center; }
.stats strong { display: block; font-size: 17px; line-height: 22px; color: var(--accent); }
.stats span { display: block; font-size: 11px; line-height: 14px; color: var(--soft); }
.progress { margin-top: 12px; }
.progress-label { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; line-height: 16px; color: var(--soft); margin-bottom: 5px; }
.progress-label strong { color: var(--accent); }
.progress-track { height: 6px; border-radius: 3px; background: var(--line); overflow: hidden; }
.progress-fill { height: 100%; border-radius: 3px; background: var(--accent); }

.story { display: flex; flex-direction: column; }
.story > img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: #000; }
.story-text { padding: 13px 16px 14px; }
.story-text .eyebrow { font-size: 12px; color: var(--accent); }
.story h2 { margin-top: 2px; font-family: Georgia, 'Times New Roman', serif; font-weight: normal; font-size: 19px; line-height: 25px; }
.story-text p:not(.eyebrow):not(.credit) { margin-top: 4px; font-size: 14px; line-height: 21px; color: var(--soft); }
.credit { margin-top: 7px; font-size: 11px; color: var(--faint); }

.details { padding: 3px 16px; }
.detail { padding: 10px 0; border-bottom: 1px solid var(--line); }
.detail h3 { font-size: 13px; line-height: 18px; color: var(--accent); }
.detail p { margin-top: 1px; font-size: 13px; line-height: 19px; color: var(--soft); }
.next { padding: 10px 0; font-size: 12px; line-height: 17px; color: var(--faint); }
.unavailable { padding: 40px 16px; text-align: center; color: var(--soft); }

@media (min-width: 900px) {
  .page {
    padding: 20px 24px;
    column-gap: 32px;
    row-gap: 16px;
    grid-template-columns: minmax(0, 1fr) 400px;
    grid-template-areas: "intro signup" "content content";
    align-items: center;
  }
  .signup-link { display: none; }
  .toolbar { margin-bottom: 14px; }
  .tabs { flex: 0 0 360px; }
  .panel { gap: 14px; grid-template-columns: minmax(0, 7fr) minmax(0, 5fr); align-items: stretch; }
  .signal { font-size: 42px; line-height: 48px; }
  .progress { margin-top: auto; padding-top: 12px; }
  .story { flex-direction: row; }
  .story > img { width: 44%; aspect-ratio: auto; min-height: 100%; }
  .story-text { flex: 1 1 0; min-width: 0; align-self: center; }
}
"""

SCRIPT = """
const tabs = [...document.querySelectorAll('[role=tab]')];
function selectTab(tab, focus) {
  tabs.forEach((other) => {
    const selected = other === tab;
    other.setAttribute('aria-selected', selected);
    other.tabIndex = selected ? 0 : -1;
    document.getElementById(other.getAttribute('aria-controls')).toggleAttribute('data-inactive', !selected);
  });
  if (focus) tab.focus();
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => {
    selectTab(tab);
    history.replaceState(null, '', '#' + tab.id.replace('tab-', ''));
  });
  tab.addEventListener('keydown', (event) => {
    const step = {ArrowRight: 1, ArrowLeft: -1}[event.key];
    if (step) selectTab(tabs[(index + step + tabs.length) % tabs.length], true);
  });
});
const linked = location.hash.length > 1 && document.getElementById('tab-' + location.hash.slice(1));
if (linked) selectTab(linked);

// Between NASA updates, carry the distance forward at its current speed
const counters = [...document.querySelectorAll('.odometer-value')];
function tick() {
  const now = Date.now() / 1000;
  counters.forEach((counter) => {
    const km = Number(counter.dataset.km) + Number(counter.dataset.rate) * (now - Number(counter.dataset.at));
    counter.textContent = Math.round(km).toLocaleString('en-US');
  });
}
tick();
setInterval(tick, 1000);

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
        body = _tabs(snapshot)
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
<script>document.documentElement.classList.add('js');</script>
</head>
<body>
<main class="page">
<header class="intro">
<h1>Voyager, right now</h1>
<p>The two farthest spacecraft ever launched are still talking to us.</p>
<a class="signup-link" href="#subscribe">Get these updates by email</a>
</header>
<section class="content">{body}</section>
<form class="subscribe" id="subscribe">
<label for="email"><strong>Get these updates by email.</strong> One each time a Voyager travels another light-minute, about one a week.</label>
<div class="fields">
<input type="email" id="email" name="email" required autocomplete="email" placeholder="you@example.com">
<input class="trap" type="text" name="company" tabindex="-1" autocomplete="off" aria-hidden="true">
<button type="submit">Subscribe</button>
</div>
<p class="message" id="message" role="status"></p>
<noscript><p class="message">Subscribing needs JavaScript turned on.</p></noscript>
</form>
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""
