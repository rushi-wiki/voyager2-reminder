from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from . import models, database
from . import scheduler
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from .distance_fetcher import get_voyager2_distance_from_earth
from .emailer import send_email

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

@app.post("/register")
def register(user: UserIn):
    db: Session = database.SessionLocal()
    if db.query(models.User).filter_by(email=user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    if user.unit not in ["light_second", "light_minute", "light_hour"]:
        raise HTTPException(status_code=400, detail="Invalid unit")

    new_user = models.User(email=user.email, unit=user.unit)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User registered", "user": user}

@app.get("/users")
def get_users():
    db: Session = database.SessionLocal()
    users = db.query(models.User).all()
    return {"users": users}

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
