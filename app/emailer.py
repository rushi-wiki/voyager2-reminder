import smtplib
from datetime import date, datetime, timezone
from email.mime.image import MIMEImage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid
from html import escape
from dotenv import load_dotenv
import os
import uuid

from .distance_fetcher import SPACECRAFT
from .postcards import POSTCARD_DIR, postcard_for
from .visuals import render_map

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT") or 587)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL")

# Public base URL of this service, used to build links in emails.
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://voyager2-reminder.fly.dev").rstrip("/")

KM_PER_AU = 149597870.7
LIGHT_SPEED_KM_S = 299792.458
SECONDS_PER_DAY = 86400
LIGHT_DAY_KM = LIGHT_SPEED_KM_S * SECONDS_PER_DAY

DISTANCE_UNITS = {
    "light_second": LIGHT_SPEED_KM_S,
    "light_minute": LIGHT_SPEED_KM_S * 60,
    "light_hour": LIGHT_SPEED_KM_S * 3600,
}

# Each spacecraft has its own colour, so you can tell them apart at a glance.
STYLE = {
    "voyager_1": {"accent": "#f4b860", "rgb": (244, 184, 96), "launch": date(1977, 9, 5)},
    "voyager_2": {"accent": "#6fd3ff", "rgb": (111, 211, 255), "launch": date(1977, 8, 20)},
}

BACKGROUND = "#05060e"
CARD = "#10132a"
PANEL = "#181c3a"
LINE = "#2a2f4f"
TEXT = "#f2f3fa"
SOFT = "#c3c7dc"
FAINT = "#9195ad"

# Email clients (Gmail, Outlook) ignore flexbox, grid, animations and
# backdrop-filter, so templates use tables, inline styles and solid
# bgcolor fallbacks. Images travel inside the email as attachments, so they
# show up without relying on any outside host.

def _preheader(text):
    """Hidden preview line shown next to the subject in the inbox."""
    return (
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;'
        f'mso-hide:all;">{escape(text)}</div>'
    )

def _signal_time(seconds):
    """Format a duration the way the email's main number reads: 23h 57m 40s."""
    total = round(seconds)
    return f"{total // 3600}h {total % 3600 // 60:02d}m {total % 60:02d}s"

def _plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"

def _reply_time(seconds):
    total_minutes = round(seconds / 60)
    days = total_minutes // 1440
    hours = total_minutes % 1440 // 60
    parts = [_plural(days, "day")] if days else []
    if hours:
        parts.append(_plural(hours, "hour"))
    if total_minutes % 60:
        parts.append(_plural(total_minutes % 60, "minute"))
    return " ".join(parts)

def _time_in_flight(launch, today):
    months = (today.year - launch.year) * 12 + today.month - launch.month
    if today.day < launch.day:
        months -= 1
    return months // 12, months % 12

def _speed_line(name, position):
    """Explain the Earth-relative speed, which swings with Earth's orbit."""
    own = position["sun_km_s"]
    gap = position["earth_km_s"]
    if gap < 0:
        return (
            f"Earth is catching up for now: the gap is shrinking by {-gap:.1f} km/s, "
            f"even though {name} is leaving the Sun behind at {own:.1f} km/s."
        )
    orbit = gap - own
    if orbit >= 0:
        return (
            f"The gap to Earth is growing by {gap:.1f} km/s: "
            f"{own:.1f} from {name}, {orbit:.1f} from Earth's orbit."
        )
    return (
        f"The gap to Earth is growing by {gap:.1f} km/s: {name} moves at {own:.1f}, "
        f"and Earth's orbit is taking back {-orbit:.1f}."
    )

def _lead(spacecraft, name, signal_s, light_days):
    reply = f"Send a hello now and the earliest reply lands {_reply_time(signal_s * 2)} from now."
    if light_days:
        days = "a full day" if light_days == 1 else f"{light_days} full days"
        first = f"A signal from {name} now takes {days} to reach Earth."
        if spacecraft == "voyager_1" and light_days == 1:
            first += " No spacecraft has ever been this far from home."
        return f"{first} {reply}"
    remaining = round(SECONDS_PER_DAY - signal_s % SECONDS_PER_DAY)
    if remaining <= 3600:
        return f"Only {remaining // 60}m {remaining % 60:02d}s short of a full light-day. {reply}"
    return f"Everything we hear from {name} left it {signal_s / 3600:.0f} hours ago. {reply}"

def _dsn_line(name, contact):
    if not contact:
        return ""
    return (
        f"{contact['station']}'s {contact['dish']} dish is receiving {name} "
        f"at {contact['rate_bps']:,.0f} bits per second."
    )

def _stat(value, label, accent):
    return f"""
                    <td width="33%" valign="top" style="padding:10px 6px;text-align:center;">
                        <div style="font-size:18px;line-height:22px;font-weight:bold;color:{accent};">{escape(value)}</div>
                        <div style="font-size:11px;line-height:14px;color:{SOFT};padding-top:2px;">{escape(label)}</div>
                    </td>"""

def _progress(signal_s, accent):
    """How far along the road to the next whole light-day from Earth."""
    done = signal_s / SECONDS_PER_DAY
    target = int(done) + 1
    percent = min(99.9, (done - int(done)) * 100)
    # A bar that has barely started, as just after a milestone, has nothing to say
    if percent < 5:
        return ""
    label = "one light-day" if target == 1 else f"{target} light-days"
    filled = min(99, max(1, round(percent)))
    empty = f'<td width="{100 - filled}%" bgcolor="{LINE}" style="background-color:{LINE};font-size:0;line-height:0;">&nbsp;</td>'
    return f"""
        <tr>
            <td style="padding:0 22px 16px 22px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
                    <td style="font-size:12px;color:{SOFT};padding-bottom:5px;">The road to {label} from Earth</td>
                    <td align="right" style="font-size:12px;font-weight:bold;color:{accent};padding-bottom:5px;">{percent:.1f}%</td>
                </tr></table>
                <table role="presentation" width="100%" height="6" cellpadding="0" cellspacing="0" border="0" style="height:6px;"><tr>
                    <td width="{filled}%" bgcolor="{accent}" style="background-color:{accent};font-size:0;line-height:0;height:6px;">&nbsp;</td>{empty}
                </tr></table>
            </td>
        </tr>"""

def _row(label, text, accent):
    return f"""
        <tr>
            <td style="padding:9px 22px;border-top:1px solid {LINE};font-size:13px;line-height:19px;color:{SOFT};"><span style="color:{accent};font-weight:bold;">{escape(label)}</span><br>{escape(text)}</td>
        </tr>"""

def _postcard(card, accent):
    return f"""
        <tr>
            <td style="padding:0 22px 16px 22px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PANEL}" style="background-color:{PANEL};border-radius:10px;">
                <tr><td style="padding:0;">
                    <img src="cid:postcard" width="516" alt="{escape(card['alt'])}" style="display:block;width:100%;max-width:516px;height:auto;border:0;border-radius:10px 10px 0 0;">
                </td></tr>
                <tr><td style="padding:11px 14px 13px 14px;">
                    <div style="font-size:11px;color:{accent};padding-bottom:3px;">From the Voyager archive</div>
                    <div style="font-family:Georgia,'Times New Roman',serif;font-size:17px;line-height:22px;color:{TEXT};padding-bottom:4px;">{escape(card['title'])}</div>
                    <div style="font-size:13px;line-height:19px;color:{SOFT};">{escape(card['story'])}</div>
                    <div style="font-size:11px;color:{FAINT};padding-top:6px;">Image: NASA/JPL</div>
                </td></tr>
                </table>
            </td>
        </tr>"""

def _footer(next_text, unsubscribe_url):
    unsubscribe = ""
    if unsubscribe_url:
        unsubscribe = (
            f'<br><a href="{escape(unsubscribe_url)}" '
            f'style="color:{SOFT};text-decoration:underline;">Unsubscribe</a>'
        )
    return f"""
        <tr>
            <td style="padding:12px 22px 18px 22px;border-top:1px solid {LINE};color:{FAINT};font-size:11px;line-height:16px;">
                {escape(next_text)}<br>
                Live data from NASA JPL Horizons and Deep Space Network Now.{unsubscribe}
            </td>
        </tr>"""

def build_update(spacecraft, unit, position, previous_sun_km=None, twin_name=None,
                 twin_position=None, contact=None, light_days=None, unsubscribe_url=None,
                 today=None):
    """Build the subject, HTML, plain text and images for one spacecraft update."""
    name = SPACECRAFT[spacecraft]["name"]
    style = STYLE[spacecraft]
    accent = style["accent"]
    unit_km = DISTANCE_UNITS[unit]
    unit_label = unit.replace("_", "-")
    count = int(position["sun_km"] // unit_km)
    signal_s = position["earth_km"] / LIGHT_SPEED_KM_S
    signal = _signal_time(signal_s)
    au = position["sun_km"] / KM_PER_AU
    billion_km = position["earth_km"] / 1e9
    years, months = _time_in_flight(style["launch"], today or datetime.now(timezone.utc).date())

    if light_days:
        days = "one light-day" if light_days == 1 else f"{light_days} light-days"
        subject = f"{name} is now {days} from Earth"
    else:
        # Round down, so the subject never claims a full light-day too early
        whole_minutes = int(signal_s // 60)
        subject = f"{name} passed {unit_label} {count:,}, signal now {whole_minutes // 60}h {whole_minutes % 60:02d}m from Earth"

    lead = _lead(spacecraft, name, signal_s, light_days)
    card = postcard_for(spacecraft, count, milestone=bool(light_days))

    moved = ""
    if previous_sun_km:
        moved_km = position["sun_km"] - previous_sun_km
        moved = f"{moved_km / 1e6:,.1f} million km farther from the Sun than in your last update."
    speed = _speed_line(name, position)
    heard = _dsn_line(name, contact)
    twin = ""
    if twin_name and twin_position:
        twin = f"{twin_name}'s signal takes {_signal_time(twin_position['earth_km'] / LIGHT_SPEED_KM_S)}, on a different heading."
    next_days = (unit_km - position["sun_km"] % unit_km) / position["sun_km_s"] / SECONDS_PER_DAY
    next_when = f"in about {next_days:.0f} days" if next_days >= 1.5 else "soon"
    next_text = f"Next update at {unit_label} {count + 1:,}, {next_when}."

    rows = "".join(
        _row(label, text, accent)
        for label, text in [
            ("Heard right now", heard),
            ("Since last time", moved),
            ("Why the number is changing", speed),
            ("Meanwhile, its twin", twin),
        ]
        if text
    )

    badge = ""
    if light_days:
        badge = f"""
        <tr>
            <td style="padding:16px 22px 0 22px;font-size:12px;font-weight:bold;color:{accent};">Milestone reached</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light dark">
    <meta name="supported-color-schemes" content="light dark">
    <title>{escape(subject)}</title>
</head>
<body bgcolor="{BACKGROUND}" style="margin:0;padding:0;background-color:{BACKGROUND};">
    {_preheader(f"Its signal takes {signal} to reach Earth. This time: {card['title']}.")}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{BACKGROUND}" style="background-color:{BACKGROUND};">
    <tr><td align="center" style="padding:12px 6px;">
    <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" bgcolor="{CARD}" style="width:100%;max-width:560px;background-color:{CARD};border-radius:14px;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:{TEXT};">
        <tr>
            <td style="padding:0;">
                <img src="cid:map" width="560" alt="Map showing {escape(name)} and its twin far beyond the planets, at {au:.1f} AU from the Sun" style="display:block;width:100%;max-width:560px;height:auto;border:0;border-radius:14px 14px 0 0;">
            </td>
        </tr>{badge}
        <tr>
            <td style="padding:{'4px' if light_days else '16px'} 22px 0 22px;color:{accent};font-size:13px;font-weight:bold;">{escape(name)} &middot; <span style="color:{SOFT};font-weight:normal;">{escape(unit_label.capitalize())} {count:,} from the Sun</span></td>
        </tr>
        <tr>
            <td style="padding:4px 22px 0 22px;font-family:Consolas,Menlo,'Courier New',monospace;font-size:34px;line-height:40px;font-weight:bold;color:{TEXT};">{signal}</td>
        </tr>
        <tr>
            <td style="padding:0 22px 10px 22px;color:{SOFT};font-size:13px;">for its signal to reach Earth</td>
        </tr>
        <tr>
            <td style="padding:0 22px 14px 22px;font-family:Georgia,'Times New Roman',serif;font-size:15px;line-height:22px;color:{TEXT};">{escape(lead)}</td>
        </tr>
        <tr>
            <td style="padding:0 22px 12px 22px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PANEL}" style="background-color:{PANEL};border-radius:10px;"><tr>{_stat(f"{au:.1f}", "AU from the Sun", accent)}{_stat(f"{billion_km:.1f}", "billion km from Earth", accent)}{_stat(f"{years}y {months}m", "in flight", accent)}
                </tr></table>
            </td>
        </tr>{_progress(signal_s, accent)}{_postcard(card, accent)}{rows}{_footer(next_text, unsubscribe_url)}
    </table>
    </td></tr>
    </table>
</body>
</html>
"""

    text_lines = [f"{name}: its signal takes {signal} to reach Earth", "", lead, ""]
    text_lines += [
        f"{au:.1f} AU from the Sun, {billion_km:.1f} billion km from Earth, "
        f"{_plural(years, 'year')} and {_plural(months, 'month')} in flight.",
        "",
    ]
    text_lines += [line for line in [heard, moved, speed, twin] if line]
    text_lines += ["", f"From the Voyager archive: {card['title']}", card["story"]]
    text_lines += ["", next_text, "Live data from NASA JPL Horizons and Deep Space Network Now."]
    if unsubscribe_url:
        text_lines += ["", f"Unsubscribe: {unsubscribe_url}"]

    images = {
        "map": render_map(name, position, style["rgb"], twin_name, twin_position),
        "postcard": (POSTCARD_DIR / card["image"]).read_bytes(),
    }

    return {"subject": subject, "html": html, "text": "\n".join(text_lines) + "\n", "images": images}

def unsubscribe_url_for(user):
    return f"{APP_BASE_URL}/unsubscribe?token={user.unsubscribe_token}"

def _send(msg, unsubscribe_url=None):
    if unsubscribe_url:
        # RFC 8058 one-click unsubscribe, required by Gmail and Yahoo for bulk senders
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

def send_verification_email(to_email, verify_url):
    """Send a confirmation email with a one-click verify link."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Confirm your Voyager subscription"
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email

    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background-color:#0b0d1a;">
    {_preheader("One click and you'll start getting Voyager 1 and Voyager 2 updates.")}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0b0d1a" style="background-color:#0b0d1a;">
    <tr><td align="center" style="padding:40px 12px;">
    <table role="presentation" width="480" cellpadding="0" cellspacing="0" border="0" bgcolor="#151933" style="width:100%;max-width:480px;background-color:#151933;border-radius:16px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;color:#ffffff;">
        <tr>
            <td align="center" style="padding:40px 30px;">
                <div style="font-size:48px;line-height:56px;">🚀</div>
                <div style="font-size:22px;letter-spacing:1px;padding:10px 0 20px 0;">Confirm your subscription</div>
                <div style="font-size:15px;color:#d8daea;line-height:24px;">
                    Click below to confirm you want Voyager 1 and Voyager 2 updates.
                    You won't get any further emails until you do.
                </div>
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:28px auto 0 auto;">
                <tr><td align="center" bgcolor="#667eea" style="border-radius:999px;background-color:#667eea;">
                    <a href="{escape(verify_url)}" style="display:inline-block;padding:12px 28px;color:#ffffff;font-weight:bold;text-decoration:none;border-radius:999px;">Confirm subscription</a>
                </td></tr>
                </table>
                <div style="font-size:12px;color:#7d8199;padding-top:32px;">If you didn't sign up, just ignore this email.</div>
            </td>
        </tr>
    </table>
    </td></tr>
    </table>
</body>
</html>
"""
    text = (
        f"Confirm your Voyager subscription by opening this link:\n\n"
        f"{verify_url}\n\n"
        f"If you didn't sign up, ignore this email."
    )

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    _send(msg)


def send_update(to_email, update, unsubscribe_url=None):
    """Send an update built by build_update, with a plain text fallback"""
    # related holds the images that the HTML part refers to by Content-ID
    msg = MIMEMultipart("related")
    msg["Subject"] = update["subject"]
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    # Each update stands alone. Unique IDs, with no reply headers, discourage
    # mail clients from stacking updates into one conversation.
    msg["Message-ID"] = make_msgid(domain=(FROM_EMAIL or "").rpartition("@")[2] or None)
    msg["X-Entity-Ref-ID"] = str(uuid.uuid4())

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(update["text"], "plain"))
    body.attach(MIMEText(update["html"], "html"))
    msg.attach(body)

    for name, data in update["images"].items():
        image = MIMEImage(data, "jpeg")
        image.add_header("Content-ID", f"<{name}>")
        image.add_header("Content-Disposition", "inline", filename=f"{name}.jpg")
        msg.attach(image)

    _send(msg, unsubscribe_url)
