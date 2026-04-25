import os
import secrets

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr
from . import models, database
from . import scheduler
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from .distance_fetcher import get_voyager2_distance_from_earth
from .emailer import send_email, send_verification_email

models.Base.metadata.create_all(bind=database.engine)

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://voyager2-reminder.fly.dev").rstrip("/")

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
        distance_km=current_distance
    )
    return {"message": "User notified"}

@app.get("/jobs")
def get_jobs():
    return {"jobs": scheduler.get_jobs()}
