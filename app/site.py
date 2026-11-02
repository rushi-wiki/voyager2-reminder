import json
import threading
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .distance_fetcher import SPACECRAFT, get_dsn_contacts, get_position
from .emailer import STYLE, build_content, light_day_progress
from .postcards import POSTCARDS
from .visuals import render_map

# JPL and the DSN feed are public services, so visitors share one recent copy
# of the data instead of each page view calling them.
REFRESH_AFTER_S = 15 * 60
# The dish feed changes often and is one small request. Spacecraft positions change
# smoothly, so the page carries them forward itself between NASA updates.
CONTACTS_REFRESH_AFTER_S = 60
UNIT = "light_minute"

_snapshot = None
_refresh_lock = threading.Lock()

TRAJECTORIES = Path(__file__).parent / "trajectories.json"

POSTCARD_IMAGES = {card["image"] for cards in POSTCARDS.values() for card in cards}

def _refresh():
    global _snapshot
    positions = {key: get_position(key) for key in SPACECRAFT}
    # Keep the last good data if JPL is unreachable for either spacecraft
    if not all(positions.values()):
        return
    contacts = get_dsn_contacts() or {}
    maps = {}
    for key, position in positions.items():
        twin_key = next(k for k in SPACECRAFT if k != key)
        maps[key] = render_map(
            SPACECRAFT[key]["name"], position, STYLE[key]["rgb"],
            SPACECRAFT[twin_key]["name"], positions[twin_key],
        )
    _snapshot = {
        "fetched_at": time.time(),
        "contacts_at": time.time(),
        "positions": positions,
        "contacts": contacts,
        "maps": maps,
    }

def _refresh_contacts():
    global _snapshot
    contacts = get_dsn_contacts()
    # Try again later if the feed fails, keeping what we last knew until then
    _snapshot = dict(_snapshot, contacts=contacts or _snapshot["contacts"], contacts_at=time.time())

def _refresh_in_background(work=_refresh):
    try:
        work()
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
    elif time.time() - _snapshot["fetched_at"] > REFRESH_AFTER_S:
        if _refresh_lock.acquire(blocking=False):
            threading.Thread(target=_refresh_in_background, daemon=True).start()
    elif time.time() - _snapshot["contacts_at"] > CONTACTS_REFRESH_AFTER_S:
        if _refresh_lock.acquire(blocking=False):
            threading.Thread(target=_refresh_in_background, args=(_refresh_contacts,), daemon=True).start()
    return _snapshot

def get_map(spacecraft):
    snapshot = get_snapshot()
    if not snapshot:
        return None
    return snapshot["maps"].get(spacecraft)

def _content(key, snapshot):
    twin_key = next(k for k in SPACECRAFT if k != key)
    return build_content(
        key, UNIT, snapshot["positions"][key],
        twin_name=SPACECRAFT[twin_key]["name"],
        twin_position=snapshot["positions"][twin_key],
        contact=snapshot["contacts"].get(key),
    )

def _next_text(content):
    # Emails go out at each light-minute, but these numbers don't wait for that
    return content["next_text"].replace("Next update", "Next email") + " The numbers here stay live."

def _rate_note(rate):
    direction = "growing" if rate >= 0 else "shrinking"
    return f"km from Earth, {direction} by {abs(rate):.1f} km every second"

def _updated_text(snapshot):
    updated = datetime.fromtimestamp(snapshot["fetched_at"], timezone.utc).strftime("%H:%M UTC, %d %b %Y")
    return f"Live. Latest NASA data at {updated}"

def latest_data():
    """What an open page needs to keep itself current."""
    snapshot = get_snapshot()
    if not snapshot:
        return None
    craft = {}
    for key, position in snapshot["positions"].items():
        content = _content(key, snapshot)
        craft[key] = {
            "earth_km": position["earth_km"],
            "earth_km_s": position["earth_km_s"],
            "count": content["count"],
            "au": f"{content['au']:.1f}",
            "lead": content["lead"],
            "heard": content["heard"],
            "speed": content["speed"],
            "twin": content["twin"],
            "next": _next_text(content),
            "rate_note": _rate_note(position["earth_km_s"]),
        }
    return {"at": snapshot["fetched_at"], "updated": _updated_text(snapshot), "craft": craft}

def _detail(label, field, text):
    hidden = "" if text else " hidden"
    return f'<div class="detail"{hidden}><h3>{escape(label)}</h3><p data-field="{field}">{escape(text)}</p></div>'

def _panel(key, content, position, snapshot, active):
    """One spacecraft, with the same facts as its email, arranged for a wider screen."""
    css_name = key.replace("_", "-")
    card = content["card"]
    version = int(snapshot["fetched_at"])
    rate = position["earth_km_s"]

    progress = ""
    light_day = light_day_progress(content["signal_s"])
    if light_day:
        label, percent = light_day
        progress = f"""
        <div class="progress">
          <div class="progress-label"><span>The road to <span data-field="progress-target">{label}</span> from Earth</span><strong data-field="progress">{percent:.1f}%</strong></div>
          <div class="progress-track"><div class="progress-fill" data-field="progress-fill" style="width:{min(99.5, percent):.1f}%"></div></div>
        </div>"""

    return f"""<div role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}" class="panel"{"" if active else " data-inactive"} data-craft="{css_name}">
  <figure class="tile map">
    <button type="button" class="journey-open" data-journey>&#9654; Watch the real journey</button>
    <img data-journey src="/images/map/{key}.jpg?v={version}" width="1120" height="620" alt="Map showing {escape(content['name'])} and its twin far beyond the planets, at {content['au']:.1f} AU from the Sun">
  </figure>
  <section class="tile readout">
    <p class="eyebrow"><strong>{escape(content['name'])}</strong> &middot; {escape(content['unit_label'].capitalize())} {content['count']:,} from the Sun</p>
    <p class="signal" data-field="signal">{content['signal']}</p>
    <p class="signal-note">for its signal to reach Earth</p>
    <p class="lead" data-field="lead">{escape(content['lead'])}</p>
    <div class="odometer">
      <span class="odometer-value" data-field="odometer">{position['earth_km']:,.0f}</span>
      <span class="odometer-note" data-field="rate_note">{_rate_note(rate)}</span>
    </div>
    <div class="stats">
      <div><strong data-field="au">{content['au']:.1f}</strong><span>AU from the Sun</span></div>
      <div><strong data-field="billion">{content['billion_km']:.1f}</strong><span>billion km from Earth</span></div>
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
    {_detail("Heard right now", "heard", content['heard'])}
    {_detail("Why the number is changing", "speed", content['speed'])}
    {_detail("Meanwhile, its twin", "twin", content['twin'])}
    <p class="next" data-field="next">{escape(_next_text(content))}</p>
  </section>
</div>"""

def _tabs(snapshot):
    """One spacecraft at a time. Without JavaScript, the page shows both in turn."""
    buttons = []
    panels = []
    for i, (key, position) in enumerate(snapshot["positions"].items()):
        content = _content(key, snapshot)
        buttons.append(
            f'<button type="button" role="tab" id="tab-{key}" aria-controls="panel-{key}" '
            f'aria-selected="{"true" if i == 0 else "false"}" tabindex="{0 if i == 0 else -1}" class="tab {key.replace("_", "-")}">'
            f'<span class="tab-name">{escape(content["name"])}</span><span class="tab-signal" data-tab-signal="{key}">{content["signal"]}</span></button>'
        )
        panels.append(_panel(key, content, position, snapshot, i == 0))
    return (
        '<div class="toolbar">'
        f'<div role="tablist" aria-label="Choose a spacecraft" class="tabs">{"".join(buttons)}</div>'
        f'<p class="updated" id="updated">{_updated_text(snapshot)}</p>'
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

.map { position: relative; }
.map img { cursor: pointer; }
html:not(.js) .journey-open { display: none; }
.journey-open { position: absolute; top: 10px; left: 10px; z-index: 1; min-height: 38px; padding: 0 13px; font: inherit; font-size: 13px; font-weight: 600; color: #10132a; background: #f2f3fa; border: 0; border-radius: 8px; cursor: pointer; }
.journey-open:hover { background: #ffffff; }
.journey-open:focus-visible { outline: 2px solid #6fd3ff; outline-offset: 2px; }
#journey { width: min(1160px, calc(100vw - 32px)); max-width: none; height: min(760px, calc(100dvh - 32px)); max-height: none; padding: 0; color: #f2f3fa; background: #070913; border: 1px solid #2a2f4f; border-radius: 14px; overflow: hidden; }
#journey[open] { display: flex; flex-direction: column; }
#journey::backdrop { background: rgba(3, 4, 12, 0.78); }
.journey-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px 10px 16px; border-bottom: 1px solid #2a2f4f; }
.journey-head h2 { font-family: Georgia, 'Times New Roman', serif; font-weight: normal; font-size: 18px; line-height: 24px; }
.journey-note { color: #9195ad; font-size: 12px; line-height: 16px; }
.journey-stage { position: relative; flex: 1 1 auto; min-height: 0; }
#journey canvas { display: block; position: absolute; inset: 0; width: 100%; height: 100%; }
.journey-readout { position: absolute; top: 12px; right: 16px; text-align: right; pointer-events: none; text-shadow: 0 1px 4px #000; }
#journey-date { font-size: 24px; line-height: 30px; font-family: Georgia, 'Times New Roman', serif; }
#journey-caption { max-width: 300px; min-height: 40px; font-size: 14px; line-height: 20px; color: #c3c7dc; }
.journey-status { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 24px; text-align: center; color: #c3c7dc; }
.journey-status:empty { display: none; }
.journey-controls { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-top: 1px solid #2a2f4f; }
.journey-controls input { flex: 1 1 auto; min-width: 0; accent-color: #f4b860; height: 28px; }
.journey-button { flex: 0 0 auto; min-width: 44px; min-height: 40px; padding: 0 12px; font: inherit; font-size: 14px; color: #f2f3fa; background: #181c3a; border: 1px solid #2a2f4f; border-radius: 8px; cursor: pointer; }
.journey-button:hover { background: #2a2f4f; }
.journey-button:focus-visible, .journey-controls input:focus-visible { outline: 2px solid #6fd3ff; outline-offset: 2px; }

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

// Keep the page current with little traffic: ask the server once a minute, and
// between answers carry the distance forward at its current speed.
const LIGHT_KM_S = 299792.458;
const DAY_S = 86400;
let latest = JSON.parse(document.getElementById('latest-data').textContent);
const shownCount = {};
function fieldsFor(key) {
  return document.getElementById('panel-' + key);
}
function setField(panel, name, value) {
  const element = panel.querySelector(`[data-field="${name}"]`);
  if (element) element.textContent = value;
  return element;
}
function signalTime(seconds) {
  const total = Math.round(seconds);
  const pad = (n) => String(n).padStart(2, '0');
  return `${Math.floor(total / 3600)}h ${pad(Math.floor(total % 3600 / 60))}m ${pad(total % 60)}s`;
}
function tick() {
  if (!latest) return;
  const elapsed = Date.now() / 1000 - latest.at;
  Object.entries(latest.craft).forEach(([key, craft]) => {
    const panel = fieldsFor(key);
    const km = craft.earth_km + craft.earth_km_s * elapsed;
    const seconds = km / LIGHT_KM_S;
    const signal = signalTime(seconds);
    setField(panel, 'odometer', Math.round(km).toLocaleString('en-US'));
    setField(panel, 'signal', signal);
    setField(panel, 'billion', (km / 1e9).toFixed(1));
    document.querySelector(`[data-tab-signal="${key}"]`).textContent = signal;
    const done = seconds / DAY_S;
    const percent = Math.min(99.9, (done - Math.floor(done)) * 100);
    setField(panel, 'progress', percent.toFixed(1) + '%');
    const fill = panel.querySelector('[data-field="progress-fill"]');
    if (fill) fill.style.width = Math.min(99.5, percent).toFixed(1) + '%';
  });
}
function apply(data) {
  latest = data;
  document.getElementById('updated').textContent = data.updated;
  Object.entries(data.craft).forEach(([key, craft]) => {
    const panel = fieldsFor(key);
    ['lead', 'speed', 'twin', 'next', 'rate_note', 'au'].forEach((name) => setField(panel, name, craft[name]));
    const heard = setField(panel, 'heard', craft.heard);
    heard.parentElement.hidden = !craft.heard;
    // A new light-minute brings a new photo and story, which come from the server
    if (shownCount[key] === undefined) shownCount[key] = craft.count;
    if (craft.count !== shownCount[key]) location.reload();
  });
  tick();
}
async function poll() {
  if (document.hidden) return;
  try {
    const response = await fetch('/api/latest');
    if (response.ok) apply(await response.json());
  } catch (error) {
    // The counters keep running, and the next minute tries again
  }
}
if (latest) {
  apply(latest);
  setInterval(tick, 1000);
  setInterval(poll, 60000);
  document.addEventListener('visibilitychange', poll);
}

// The journey animation only downloads its data when someone asks to watch it
const journey = document.getElementById('journey');
const canvas = document.getElementById('journey-canvas');
const scrub = document.getElementById('journey-scrub');
const playButton = document.getElementById('journey-play');
const statusText = document.getElementById('journey-status');
const EPOCH = Date.UTC(1977, 7, 20);
const DAY_MS = 86400000;
const WARP_DAYS = (Date.UTC(1990, 5, 1) - EPOCH) / DAY_MS;
const WARP_AT = 0.62; // The busy years of flybys get most of the running time
const RUN_MS = 34000;
const dayOf = (year, month, day) => (Date.UTC(year, month - 1, day) - EPOCH) / DAY_MS;
const EVENTS = [
  [0, 'Voyager 2 launches first, on a slower route.'],
  [dayOf(1977, 9, 5), 'Voyager 1 launches 16 days later, on a faster route.'],
  [dayOf(1979, 3, 5), 'Voyager 1 flies past Jupiter, which swings it onward.'],
  [dayOf(1979, 7, 9), 'Voyager 2 flies past Jupiter.'],
  [dayOf(1980, 11, 12), "Voyager 1 flies past Saturn and turns up, out of the planets' plane."],
  [dayOf(1981, 8, 25), 'Voyager 2 flies past Saturn, heading on to Uranus.'],
  [dayOf(1986, 1, 24), 'Voyager 2 reaches Uranus, the first spacecraft ever to get there.'],
  [dayOf(1989, 8, 25), 'Voyager 2 reaches Neptune. No spacecraft has been back to either planet.'],
  [dayOf(1990, 2, 14), 'Voyager 1 looks back and takes the Pale Blue Dot photo.'],
  [dayOf(2012, 8, 25), "Voyager 1 leaves the Sun's influence for interstellar space."],
  [dayOf(2018, 11, 5), 'Voyager 2 follows it into interstellar space.'],
  [dayOf(2026, 11, 18), 'Voyager 1 reaches one light-day from Earth.'],
];
const PLANETS = [
  ['Earth', 1, '#6fb7ff', 3], ['Jupiter', 5.2, '#e0b184', 5], ['Saturn', 9.6, '#e9d28f', 4.5],
  ['Uranus', 19.2, '#9fe3e6', 4], ['Neptune', 30.1, '#7f9cff', 4],
];
const CRAFT = [['voyager_1', 'Voyager 1', '#f4b860'], ['voyager_2', 'Voyager 2', '#6fd3ff']];
let paths = null;
let progress = 0;
let playing = false;
let lastFrame = 0;
let view = null;
const todayDays = () => (Date.now() - EPOCH) / DAY_MS;
function dayAt(p) {
  if (p <= WARP_AT) return (p / WARP_AT) * WARP_DAYS;
  return WARP_DAYS + ((p - WARP_AT) / (1 - WARP_AT)) * (todayDays() - WARP_DAYS);
}
function positionAt(body, day) {
  const t = body.t;
  if (day < t[0]) return null;
  let low = 0;
  let high = t.length - 1;
  if (day >= t[high]) return [body.x[high], body.y[high]];
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if (t[middle] <= day) low = middle; else high = middle;
  }
  const f = (day - t[low]) / (t[high] - t[low]);
  return [body.x[low] + (body.x[high] - body.x[low]) * f, body.y[low] + (body.y[high] - body.y[low]) * f];
}
function makeView() {
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const today = todayDays();
  const ends = CRAFT.map(([key]) => positionAt(paths[key], today));
  const angles = ends.map(([x, y]) => Math.atan2(y, x));
  const gap = Math.atan2(Math.sin(angles[1] - angles[0]), Math.cos(angles[1] - angles[0]));
  const middle = angles[0] + gap / 2;
  // Point the spacecraft along the longer side of the screen
  const rotate = (width >= height ? 0 : -Math.PI / 2) - middle;
  const unit = (x, y) => {
    const radius = Math.sqrt(Math.hypot(x, y));
    const angle = Math.atan2(y, x) + rotate;
    return [radius * Math.cos(angle), -radius * Math.sin(angle)];
  };
  const box = [[0, 0], ...ends.map(([x, y]) => unit(x, y))];
  const xs = box.map((b) => b[0]);
  const ys = box.map((b) => b[1]);
  const margin = 58;
  const k = Math.min(
    (width - margin * 2) / (Math.max(...xs) - Math.min(...xs)),
    (height - margin * 2) / Math.max(Math.max(...ys) - Math.min(...ys), 1),
  );
  const originX = (width - (Math.max(...xs) + Math.min(...xs)) * k) / 2;
  const originY = (height - (Math.max(...ys) + Math.min(...ys)) * k) / 2;
  let seed = 7;
  const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const stars = Array.from({length: 170}, () => [random() * width, random() * height, random() * 1.1 + 0.3, random() * 0.5 + 0.2]);
  view = {
    scale, width, height, k, originX, originY, stars,
    place: (x, y) => {
      const [ux, uy] = unit(x, y);
      return [originX + ux * k, originY + uy * k];
    },
    ring: (au) => Math.sqrt(au) * k,
  };
}
function draw() {
  if (!paths || !view) return;
  const c = canvas.getContext('2d');
  const {scale, width, height, originX, originY, stars, place, ring} = view;
  const day = dayAt(progress);
  c.setTransform(scale, 0, 0, scale, 0, 0);
  c.fillStyle = '#070913';
  c.fillRect(0, 0, width, height);
  stars.forEach(([x, y, r, a]) => {
    c.fillStyle = `rgba(226, 230, 255, ${a})`;
    c.fillRect(x, y, r, r);
  });

  c.lineWidth = 1;
  c.strokeStyle = 'rgba(190, 170, 228, 0.55)';
  c.setLineDash([5, 6]);
  c.beginPath();
  c.arc(originX, originY, ring(120), 0, Math.PI * 2);
  c.stroke();
  c.setLineDash([]);
  c.font = '12px "Segoe UI", Roboto, Arial, sans-serif';
  c.textAlign = 'center';
  c.fillStyle = 'rgba(205, 188, 240, 0.9)';
  const edge = place(...positionAt(paths.voyager_1, todayDays()).map((v, i, all) => v / Math.hypot(...all) * 120));
  c.fillText("Edge of the Sun's influence", edge[0], Math.max(16, edge[1] - 14));

  PLANETS.forEach(([, au]) => {
    c.strokeStyle = 'rgba(134, 146, 196, 0.32)';
    c.beginPath();
    c.arc(originX, originY, ring(au), 0, Math.PI * 2);
    c.stroke();
  });

  const glow = c.createRadialGradient(originX, originY, 1, originX, originY, 30);
  glow.addColorStop(0, 'rgba(255, 214, 140, 0.95)');
  glow.addColorStop(1, 'rgba(255, 190, 90, 0)');
  c.fillStyle = glow;
  c.beginPath();
  c.arc(originX, originY, 30, 0, Math.PI * 2);
  c.fill();
  c.fillStyle = '#fff1cf';
  c.beginPath();
  c.arc(originX, originY, 4, 0, Math.PI * 2);
  c.fill();

  c.textAlign = 'left';
  PLANETS.forEach(([name, , color, size]) => {
    const at = positionAt(paths[name], day);
    if (!at) return;
    const [x, y] = place(...at);
    c.fillStyle = color;
    c.beginPath();
    c.arc(x, y, size, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = 'rgba(222, 226, 245, 0.85)';
    c.font = '11px "Segoe UI", Roboto, Arial, sans-serif';
    if (name !== 'Earth') c.fillText(name, x + size + 3, y + 4);
  });

  CRAFT.forEach(([key, name, color]) => {
    const body = paths[key];
    const head = positionAt(body, day);
    if (!head) return;
    c.strokeStyle = color;
    c.lineWidth = 1.8;
    c.beginPath();
    let started = false;
    for (let i = 0; i < body.t.length && body.t[i] <= day; i++) {
      const [x, y] = place(body.x[i], body.y[i]);
      if (started) c.lineTo(x, y); else c.moveTo(x, y);
      started = true;
    }
    const [hx, hy] = place(...head);
    if (started) c.lineTo(hx, hy);
    c.stroke();
    const halo = c.createRadialGradient(hx, hy, 1, hx, hy, 15);
    halo.addColorStop(0, color);
    halo.addColorStop(1, 'rgba(0, 0, 0, 0)');
    c.fillStyle = halo;
    c.beginPath();
    c.arc(hx, hy, 15, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = color;
    c.beginPath();
    c.arc(hx, hy, 4, 0, Math.PI * 2);
    c.fill();
    const au = Math.hypot(...head).toFixed(1);
    c.font = '600 13px "Segoe UI", Roboto, Arial, sans-serif';
    const onLeft = hx > width - 112;
    c.textAlign = onLeft ? 'right' : 'left';
    const labelX = hx + (onLeft ? -10 : 10);
    const labelY = key === 'voyager_1' ? hy + 18 : hy - 16;
    c.fillText(name, labelX, labelY);
    c.font = '11px "Segoe UI", Roboto, Arial, sans-serif';
    c.fillStyle = 'rgba(222, 226, 245, 0.85)';
    c.fillText(`${au} AU`, labelX, labelY + 14);
    c.textAlign = 'left';
  });

  const date = new Date(EPOCH + day * DAY_MS);
  document.getElementById('journey-date').textContent = date.toLocaleDateString('en-GB', {month: 'long', year: 'numeric', timeZone: 'UTC'});
  let caption = '';
  EVENTS.forEach(([eventDay, text]) => { if (eventDay <= day) caption = text; });
  document.getElementById('journey-caption').textContent = caption;
  scrub.value = Math.round(progress * 1000);
}
function setPlaying(value) {
  playing = value;
  playButton.textContent = value ? 'Pause' : (progress >= 1 ? 'Replay' : 'Play');
  if (value) {
    lastFrame = performance.now();
    requestAnimationFrame(frame);
  }
}
function frame(now) {
  if (!playing || !journey.open) return;
  progress = Math.min(1, progress + (now - lastFrame) / RUN_MS);
  lastFrame = now;
  draw();
  if (progress >= 1) setPlaying(false); else requestAnimationFrame(frame);
}
async function openJourney() {
  journey.showModal();
  if (!paths) {
    statusText.textContent = 'Loading the journey...';
    try {
      const response = await fetch('/trajectories.json');
      if (!response.ok) throw new Error('unavailable');
      paths = (await response.json()).bodies;
      statusText.textContent = '';
    } catch (error) {
      statusText.textContent = 'The journey could not load. Close this and try again.';
      return;
    }
  }
  makeView();
  // Without motion, start at today's positions and let people drag through time
  const stillOnly = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  progress = stillOnly ? 1 : 0;
  draw();
  setPlaying(!stillOnly);
}
document.querySelectorAll('[data-journey]').forEach((element) => element.addEventListener('click', openJourney));
document.getElementById('journey-close').addEventListener('click', () => journey.close());
journey.addEventListener('click', (event) => { if (event.target === journey) journey.close(); });
journey.addEventListener('close', () => setPlaying(false));
playButton.addEventListener('click', () => {
  if (playing) return setPlaying(false);
  if (progress >= 1) progress = 0;
  setPlaying(true);
});
scrub.addEventListener('input', () => {
  progress = Number(scrub.value) / 1000;
  setPlaying(false);
  draw();
});
window.addEventListener('resize', () => {
  if (journey.open && paths) {
    makeView();
    draw();
  }
});

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

    latest = json.dumps(latest_data()).replace("<", "\\u003c")
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
<dialog id="journey" aria-labelledby="journey-title">
<div class="journey-head">
<div><h2 id="journey-title">The journey so far</h2><p class="journey-note">Real paths and planet positions from NASA JPL, seen from above. Distances compressed.</p></div>
<button type="button" class="journey-button" id="journey-close">Close</button>
</div>
<div class="journey-stage">
<canvas id="journey-canvas" role="img" aria-label="Animation of Voyager 1 and Voyager 2 travelling from Earth past the planets, from 1977 to today"></canvas>
<div class="journey-readout"><div id="journey-date"></div><div id="journey-caption" aria-live="polite"></div></div>
<div class="journey-status" id="journey-status"></div>
</div>
<div class="journey-controls">
<button type="button" class="journey-button" id="journey-play">Play</button>
<input type="range" id="journey-scrub" min="0" max="1000" value="0" aria-label="Move through time">
</div>
</dialog>
<script id="latest-data" type="application/json">{latest}</script>
<script>{SCRIPT}</script>
</body>
</html>
"""
