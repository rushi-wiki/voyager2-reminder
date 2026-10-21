import secrets
from html import escape

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr
from . import models, database
from . import scheduler
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from .distance_fetcher import get_voyager2_distance_from_earth
from .emailer import (
    APP_BASE_URL,
    send_email,
    send_verification_email,
    unsubscribe_url_for,
)

database.migrate()
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()
scheduler.start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

class UserIn(BaseModel):
    email: EmailStr
    unit: str

@app.post("/register", status_code=202)
def register(user: UserIn):
    db: Session = database.SessionLocal()
    if db.query(models.User).filter_by(email=user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    if user.unit not in ["light_second", "light_minute", "light_hour"]:
        raise HTTPException(status_code=400, detail="Invalid unit")

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

    return {"message": "Check your inbox to confirm your subscription."}


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
    db.commit()
    return HTMLResponse(
        f"""<html><body style="font-family:sans-serif;text-align:center;padding:60px 20px;background:#0a0a0a;color:#fff;">
        <div style="font-size:60px">🚀</div>
        <h1 style="font-weight:300">You're confirmed</h1>
        <p>You'll get an email each time Voyager 2 moves another {user.unit.replace('_', ' ')}.</p>
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
        f"""<p>Stop Voyager 2 updates to {escape(user.email)}?</p>
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
    return _page("You're unsubscribed", "<p>You won't get any more Voyager 2 emails. Safe travels!</p>")

@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    db: Session = database.SessionLocal()
    user = db.query(models.User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    db: Session = database.SessionLocal()
    user = db.query(models.User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": user}

@app.post("/users/{user_id}/notify")
def notify_user(user_id: int):
    db: Session = database.SessionLocal()
    user = db.query(models.User).filter_by(id=user_id).first()
    current_distance = get_voyager2_distance_from_earth()
    print(f"Current distance: {current_distance}")
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    send_email(
        user.email, 
        f"Voyager 2 moved {user.unit.replace('_', ' ')}", 
        unit=user.unit,
        distance_km=current_distance,
        previous_distance_km=user.last_notified_distance,
        unsubscribe_url=unsubscribe_url_for(user),
    )
    return {"message": "User notified"}

@app.get("/jobs")
def get_jobs():
    return {"jobs": scheduler.get_jobs()}
