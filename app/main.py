import secrets
import time
from collections import defaultdict, deque
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, EmailStr
from . import models, database, push
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

# Standard browser protections. The page's own script and styles are inline,
# so those are allowed, but nothing may load from or post to anywhere else.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response

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

class PushKeys(BaseModel):
    p256dh: str
    auth: str

class PushIn(BaseModel):
    endpoint: str
    keys: PushKeys

class PushOut(BaseModel):
    endpoint: str

@app.post("/push/subscribe", status_code=201)
def push_subscribe(subscription: PushIn, request: Request):
    if not push.enabled():
        raise HTTPException(status_code=503, detail="Notifications aren't available right now.")
    if not push.is_allowed_endpoint(subscription.endpoint):
        raise HTTPException(status_code=400, detail="That browser's notification service isn't supported.")
    ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "unknown")
    if not _allow_signup(ip):
        raise HTTPException(status_code=429, detail="Too many sign-ups right now. Try again later.")

    db: Session = database.SessionLocal()
    try:
        saved = db.query(models.PushSubscription).filter_by(endpoint=subscription.endpoint).first()
        if saved:
            saved.p256dh = subscription.keys.p256dh
            saved.auth = subscription.keys.auth
        else:
            saved = models.PushSubscription(
                endpoint=subscription.endpoint,
                p256dh=subscription.keys.p256dh,
                auth=subscription.keys.auth,
            )
            db.add(saved)
        db.commit()
        # A real one straight away, so people know it works
        try:
            push.send(saved, "Notifications are on", "You'll hear when a Voyager passes each new light-minute.")
        except Exception as e:
            print(f"Welcome notification failed: {type(e).__name__}")
            db.delete(saved)
            db.commit()
            raise HTTPException(status_code=502, detail="Could not reach your browser's notification service. Try again.")
    finally:
        db.close()
    return {"message": "Notifications are on."}

class PushProblem(BaseModel):
    stage: str = ""
    detail: str = ""
    permission: str = ""
    standalone: bool = False
    worker: bool = False
    push_manager: bool = False

PROBLEM_REPORTS_PER_IP_PER_HOUR = 10
_problem_reports = defaultdict(deque)

def _clean(text, limit=120):
    # Only plain characters reach the log, so a report can't forge log lines
    return "".join(c for c in text[:limit] if c.isalnum() or c in " :._-()'")

@app.post("/push/problem", status_code=204)
def push_problem(problem: PushProblem, request: Request):
    """Logs why a browser couldn't turn notifications on. Nothing personal is kept."""
    ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "unknown")
    now = time.time()
    reports = _problem_reports[ip]
    while reports and now - reports[0] > 3600:
        reports.popleft()
    if len(reports) < PROBLEM_REPORTS_PER_IP_PER_HOUR:
        reports.append(now)
        agent = request.headers.get("user-agent", "")
        browser = "Android Chrome" if "Android" in agent and "Chrome" in agent else ("iPhone" if "iPhone" in agent else "other")
        print(
            f"Push problem: stage={_clean(problem.stage, 20)} detail={_clean(problem.detail)} "
            f"permission={_clean(problem.permission, 12)} standalone={problem.standalone} "
            f"worker={problem.worker} push_manager={problem.push_manager} browser={browser}"
        )
    return Response(status_code=204)

@app.post("/push/unsubscribe")
def push_unsubscribe(subscription: PushOut):
    db: Session = database.SessionLocal()
    try:
        db.query(models.PushSubscription).filter_by(endpoint=subscription.endpoint).delete()
        db.commit()
    finally:
        db.close()
    return {"message": "Notifications are off."}

@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse(site.MANIFEST, media_type="application/manifest+json")

@app.get("/sw.js")
def service_worker():
    # Never cached, so browsers always notice a new version of the app
    return Response(site.SERVICE_WORKER, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

@app.get("/icons/{name}")
def icon(name: str):
    if name not in site.ICON_FILES:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(site.ICON_DIR / name, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})

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


INVALID_LINK = "<p>This confirmation link is no longer valid.</p>"

@app.get("/verify", response_class=HTMLResponse)
def verify_page(token: str):
    # Opening the link only shows a button. Mail scanners open links in emails
    # automatically, so confirming on open would subscribe people who never asked.
    db: Session = database.SessionLocal()
    try:
        user = db.query(models.User).filter_by(verify_token=token).first()
    finally:
        db.close()
    if not user:
        return _page("Invalid or expired link", INVALID_LINK, status_code=400)
    return _page(
        "Confirm your subscription",
        f"""<p>Get Voyager updates at {escape(user.email)}?</p>
        <form method="post" action="/verify?token={escape(token)}">
            <button type="submit" style="padding:12px 28px;border:0;border-radius:999px;background:#667eea;color:#fff;font-size:16px;cursor:pointer;">Confirm</button>
        </form>""",
    )

@app.post("/verify", response_class=HTMLResponse)
def verify(token: str):
    db: Session = database.SessionLocal()
    try:
        user = db.query(models.User).filter_by(verify_token=token).first()
        if not user:
            return _page("Invalid or expired link", INVALID_LINK, status_code=400)
        user.verified = True
        user.verify_token = None
        models.subscribe_to_all(user)
        db.commit()
        unit = user.unit.replace("_", " ")
    finally:
        db.close()
    return _page(
        "You're confirmed",
        f"<p>You'll get an email each time Voyager 1 or Voyager 2 moves another {escape(unit)}.</p>",
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
