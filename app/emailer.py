import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from html import escape
from dotenv import load_dotenv
import os

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
EARTH_MOON_KM = 384400

# Email clients (Gmail, Outlook) ignore flexbox, grid, animations and
# backdrop-filter, so templates use tables, inline styles and solid
# bgcolor fallbacks behind any gradients.

def _preheader(text):
    """Hidden preview line shown next to the subject in the inbox."""
    return (
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;'
        f'mso-hide:all;">{escape(text)}</div>'
    )

def _stat_row(label, value, last=False):
    border = "" if last else "border-bottom:1px solid #2a2f4a;"
    return f"""
                <tr>
                    <td style="padding:12px 0;{border}color:#b8bcd0;font-size:14px;">{label}</td>
                    <td align="right" style="padding:12px 0;{border}color:#8fa2ff;font-size:16px;font-weight:bold;">{value}</td>
                </tr>"""

def _change_line(distance_km, previous_distance_km):
    """Describe how far Voyager 2 moved since the subscriber's last update."""
    if not previous_distance_km:
        return ""
    delta_km = distance_km - previous_distance_km
    moon_trips = abs(delta_km) / EARTH_MOON_KM
    direction = "farther from" if delta_km >= 0 else "closer to"
    return (
        f"Since your last update it's <strong>{abs(delta_km):,.0f} km</strong> "
        f"{direction} Earth, about {moon_trips:,.0f} trips to the Moon."
    )

def _footer(unsubscribe_url):
    unsubscribe = ""
    if unsubscribe_url:
        unsubscribe = (
            f'<br><a href="{escape(unsubscribe_url)}" '
            'style="color:#8fa2ff;text-decoration:underline;">Unsubscribe</a>'
        )
    return f"""
        <tr>
            <td align="center" style="padding:24px 30px 32px 30px;border-top:1px solid #2a2f4a;color:#7d8199;font-size:12px;line-height:18px;">
                You're getting this because you subscribed to Voyager 2 distance updates.<br>
                Data courtesy of NASA JPL Horizons System.{unsubscribe}
            </td>
        </tr>"""

def create_html_template(unit, distance_km, previous_distance_km=None, unsubscribe_url=None):
    """Create the HTML email for a Voyager 2 distance update"""
    distance_million_km = distance_km / 1e6
    distance_au = distance_km / KM_PER_AU
    light_hours = distance_km / LIGHT_SPEED_KM_S / 3600
    unit_label = unit.replace("_", " ")
    change = _change_line(distance_km, previous_distance_km)
    change_row = ""
    if change:
        change_row = f"""
        <tr>
            <td style="padding:0 30px 10px 30px;color:#d8daea;font-size:15px;line-height:22px;text-align:center;">{change}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Voyager 2 Update</title>
</head>
<body style="margin:0;padding:0;background-color:#0b0d1a;">
    {_preheader(f"Voyager 2 is now {distance_au:.2f} AU from Earth. Your signal would take {light_hours:.1f} hours to reach it.")}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0b0d1a" style="background-color:#0b0d1a;">
    <tr><td align="center" style="padding:24px 12px;">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" bgcolor="#151933" style="width:100%;max-width:600px;background-color:#151933;border-radius:16px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;color:#ffffff;">
        <tr>
            <td align="center" bgcolor="#5a67d8" style="padding:36px 30px;background-color:#5a67d8;background-image:linear-gradient(45deg,#667eea 0%,#764ba2 100%);border-radius:16px 16px 0 0;">
                <div style="font-size:48px;line-height:56px;">🚀</div>
                <div style="font-size:26px;letter-spacing:2px;color:#ffffff;">VOYAGER 2</div>
                <div style="font-size:13px;letter-spacing:1px;color:#e6e8ff;padding-top:6px;">DEEP SPACE EXPLORER</div>
            </td>
        </tr>
        <tr>
            <td style="padding:32px 30px 12px 30px;text-align:center;">
                <div style="color:#8fa2ff;font-size:22px;padding-bottom:10px;">🌌 Journey Update</div>
                <div style="color:#d8daea;font-size:16px;line-height:24px;">Voyager 2 has traveled another <strong style="color:#8fa2ff;">{unit_label}</strong> through the cosmos!</div>
            </td>
        </tr>{change_row}
        <tr>
            <td style="padding:16px 30px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#1d2244" style="background-color:#1d2244;border-left:4px solid #667eea;border-radius:10px;">
                <tr><td style="padding:20px 24px;">
                    <div style="color:#8fa2ff;font-size:17px;padding-bottom:8px;">📍 Current Position</div>
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{_stat_row("Distance from Earth", f"{distance_million_km:,.2f} million km")}{_stat_row("In Astronomical Units", f"{distance_au:.2f} AU")}{_stat_row("Light travel time", f"{light_hours:.2f} hours", last=True)}
                    </table>
                </td></tr>
                </table>
            </td>
        </tr>
        <tr>
            <td style="padding:16px 30px 32px 30px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#1f1a3a" style="background-color:#1f1a3a;border-radius:10px;">
                <tr><td style="padding:20px 24px;">
                    <div style="color:#b49be0;font-size:16px;padding-bottom:10px;">🛰️ Mission Status</div>
                    <div style="color:#d8daea;font-size:14px;line-height:22px;">Launched in 1977, Voyager 2 continues its incredible journey through interstellar space, carrying humanity's message to the stars on the Golden Record.</div>
                </td></tr>
                </table>
            </td>
        </tr>{_footer(unsubscribe_url)}
    </table>
    </td></tr>
    </table>
</body>
</html>
"""

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
    msg["Subject"] = "Confirm your Voyager 2 subscription"
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email

    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background-color:#0b0d1a;">
    {_preheader("One click and you'll start getting Voyager 2 distance updates.")}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0b0d1a" style="background-color:#0b0d1a;">
    <tr><td align="center" style="padding:40px 12px;">
    <table role="presentation" width="480" cellpadding="0" cellspacing="0" border="0" bgcolor="#151933" style="width:100%;max-width:480px;background-color:#151933;border-radius:16px;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;color:#ffffff;">
        <tr>
            <td align="center" style="padding:40px 30px;">
                <div style="font-size:48px;line-height:56px;">🚀</div>
                <div style="font-size:22px;letter-spacing:1px;padding:10px 0 20px 0;">Confirm your subscription</div>
                <div style="font-size:15px;color:#d8daea;line-height:24px;">
                    Click below to confirm you want Voyager 2 distance updates.
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
        f"Confirm your Voyager 2 subscription by opening this link:\n\n"
        f"{verify_url}\n\n"
        f"If you didn't sign up, ignore this email."
    )

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    _send(msg)


def send_email(to_email, subject, unit=None, distance_km=None,
               previous_distance_km=None, unsubscribe_url=None):
    """Send an HTML email with a plain text fallback"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email

    # Create HTML content
    if unit and distance_km:
        html_content = create_html_template(
            unit, distance_km, previous_distance_km, unsubscribe_url
        )
        change = _change_line(distance_km, previous_distance_km)
        change = change.replace("<strong>", "").replace("</strong>", "")
        text_content = (
            "Voyager 2 Distance Update\n\n"
            f"Voyager 2 has traveled another {unit.replace('_', ' ')} through space!\n"
            + (f"{change}\n" if change else "")
            + "\n"
            f"Current distance from Earth: {distance_km / 1e6:,.2f} million km\n"
            f"In Astronomical Units: {distance_km / KM_PER_AU:.2f} AU\n"
            f"Light travel time: {distance_km / LIGHT_SPEED_KM_S / 3600:.2f} hours\n\n"
            "This incredible spacecraft continues its journey through interstellar space,\n"
            "carrying humanity's message to the stars.\n\n"
            "Data courtesy of NASA JPL Horizons System.\n"
        )
    else:
        # Fallback for other types of emails
        html_content = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #333;">{escape(subject)}</h2>
    <p>Thank you for subscribing to Voyager 2 updates!</p>
</body>
</html>
"""
        text_content = f"{subject}\n\nThank you for subscribing to Voyager 2 updates!\n"

    if unsubscribe_url:
        text_content += f"\nUnsubscribe: {unsubscribe_url}\n"

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))
    _send(msg, unsubscribe_url)
