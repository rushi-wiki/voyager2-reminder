import secrets
import time
from collections import defaultdict, deque
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, EmailStr
from . import models, database
from . import scheduler
from . import site
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from .distance_fetcher import SPACECRAFT
from .emailer import APP_BASE_URL, send_verification_email
from .postcards import POSTCARD_DIR

database.migrate()
models.Base.metadata.create_all(bind=database.engine)
_startup_db = database.SessionLocal()
models.backfill_subscriptions(_startup_db)
_startup_db.close()

app = FastAPI()
scheduler.start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

CHECK_INBOX = "Check your inbox to confirm your subscription."

# A public form that sends email needs limits, or anyone could use it to send
# confirmation emails to strangers and use up the Brevo allowance.
SIGNUPS_PER_IP_PER_HOUR = 5
SIGNUPS_PER_DAY = 100
_signups_by_ip = defaultdict(deque)
_signups_today = deque()

def _allow_signup(ip):
    now = time.time()
    by_ip = _signups_by_ip[ip]
    while by_ip and now - by_ip[0] > 3600:
        by_ip.popleft()
    while _signups_today and now - _signups_today[0] > 86400:
        _signups_today.popleft()
    if len(by_ip) >= SIGNUPS_PER_IP_PER_HOUR or len(_signups_today) >= SIGNUPS_PER_DAY:
        return False
    by_ip.append(now)
    _signups_today.append(now)
    return True

class UserIn(BaseModel):
    email: EmailStr
    unit: str = "light_minute"
    company: str = ""  # Hidden from people, so only bots fill it in

@app.get("/", response_class=HTMLResponse)
def home():
    return site.render_page()

@app.get("/api/latest")
def latest():
    data = site.latest_data()
    if not data:
        raise HTTPException(status_code=503, detail="NASA data is out of reach right now")
    return data

@app.get("/trajectories.json")
def trajectories():
    return FileResponse(site.TRAJECTORIES, media_type="application/json", headers={"Cache-Control": "public, max-age=86400"})

@app.get("/images/map/{spacecraft}.jpg")
def map_image(spacecraft: str):
    image = site.get_map(spacecraft) if spacecraft in SPACECRAFT else None
    if not image:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=900"})

@app.get("/images/postcards/{name}")
def postcard_image(name: str):
    if name not in site.POSTCARD_IMAGES:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(POSTCARD_DIR / name, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

@app.post("/register", status_code=202)
def register(user: UserIn, request: Request):
    if user.unit not in ["light_second", "light_minute", "light_hour"]:
        raise HTTPException(status_code=400, detail="Invalid unit")

    # Answer bots as if it worked, so they don't learn to avoid the trap field
    if user.company:
        return {"message": CHECK_INBOX}

    # Fly.io puts the visitor's real address in this header
    ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "unknown")
    if not _allow_signup(ip):
        raise HTTPException(status_code=429, detail="Too many sign-ups right now. Try again later.")

    db: Session = database.SessionLocal()
    # Same answer either way, so the form can't reveal who is subscribed
    if db.query(models.User).filter_by(email=user.email).first():
        return {"message": CHECK_INBOX}

    token = secrets.token_urlsafe(32)
    new_user = models.User(email=user.email, unit=user.unit, verify_token=token)
    db.add(new_user)
    db.commit()

    verify_url = f"{APP_BASE_URL}/verify?token={token}"
    try:
        send_verification_email(user.email, verify_url)
    except Exception:
        db.delete(new_user)
        db.commit()
        raise HTTPException(status_code=502, detail="Could not send verification email; please try again.")

    return {"message": CHECK_INBOX}


@app.get("/verify", response_class=HTMLResponse)
def verify(token: str):
    db: Session = database.SessionLocal()
    user = db.query(models.User).filter_by(verify_token=token).first()
    if not user:
        return HTMLResponse(
            """<html><body style="font-family:sans-serif;text-align:center;padding:60px 20px;background:#0a0a0a;color:#fff;">
            <h1>Invalid or expired link</h1>
            <p>This confirmation link is no longer valid.</p>
            </body></html>""",
            status_code=400,
        )
    user.verified = True
    user.verify_token = None
    models.subscribe_to_all(user)
    db.commit()
    return HTMLResponse(
        f"""<html><body style="font-family:sans-serif;text-align:center;padding:60px 20px;background:#0a0a0a;color:#fff;">
        <div style="font-size:60px">🚀</div>
        <h1 style="font-weight:300">You're confirmed</h1>
        <p>You'll get an email each time Voyager 1 or Voyager 2 moves another {user.unit.replace('_', ' ')}.</p>
        </body></html>"""
    )

def _page(title, body, status_code=200):
    return HTMLResponse(
        f"""<html><body style="font-family:sans-serif;text-align:center;padding:60px 20px;background:#0a0a0a;color:#fff;">
        <div style="font-size:60px">🚀</div>
        <h1 style="font-weight:300">{title}</h1>
        {body}
        </body></html>""",
        status_code=status_code,
    )

@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(token: str):
    # A GET only shows a confirm button, so link scanners that prefetch
    # URLs in emails can't unsubscribe people by accident.
    db: Session = database.SessionLocal()
    user = db.query(models.User).filter_by(unsubscribe_token=token).first()
    if not user:
        return _page("Already unsubscribed", "<p>This address isn't subscribed anymore.</p>")
    return _page(
        "Unsubscribe?",
        f"""<p>Stop Voyager updates to {escape(user.email)}?</p>
        <form method="post" action="/unsubscribe?token={token}">
            <button type="submit" style="padding:12px 28px;border:0;border-radius:999px;background:#667eea;color:#fff;font-size:16px;cursor:pointer;">Unsubscribe</button>
        </form>""",
    )

@app.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str):
    # Also handles RFC 8058 one-click requests sent by mail clients
    db: Session = database.SessionLocal()
    user = db.query(models.User).filter_by(unsubscribe_token=token).first()
    if user:
        db.delete(user)
        db.commit()
    return _page("You're unsubscribed", "<p>You won't get any more Voyager emails. Safe travels!</p>")

@app.get("/jobs")
def get_jobs():
    return {"jobs": scheduler.get_jobs()}
