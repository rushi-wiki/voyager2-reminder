import secrets

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base
from .distance_fetcher import SPACECRAFT

def new_token():
    return secrets.token_urlsafe(32)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    unit = Column(String)  # e.g., "light_second", "light_hour"
    last_notified_distance = Column(Float, default=0.0)  # unused since subscriptions were added
    verified = Column(Boolean, default=False, nullable=False)
    verify_token = Column(String, nullable=True, index=True)
    unsubscribe_token = Column(String, nullable=True, index=True, default=new_token)
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")

class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "spacecraft"),)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    spacecraft = Column(String, nullable=False)  # a key of SPACECRAFT
    last_notified_km = Column(Float, default=0.0, nullable=False)  # distance from the Sun
    farthest_earth_km = Column(Float, default=0.0, nullable=False)
    user = relationship("User", back_populates="subscriptions")

def subscribe_to_all(user):
    for spacecraft in SPACECRAFT:
        user.subscriptions.append(Subscription(spacecraft=spacecraft))

def backfill_subscriptions(db):
    """Move users from before subscriptions existed onto both spacecraft.

    They signed up when every update was a near-identical light-second email,
    so they also move to the light-minute cadence. This only runs once per
    user: anyone choosing light seconds later already has subscriptions.
    """
    users = db.query(User).filter(User.verified == True, ~User.subscriptions.any()).all()
    for user in users:
        if user.unit == "light_second":
            user.unit = "light_minute"
        subscribe_to_all(user)
    db.commit()

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String, unique=True, index=True, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)

class PushState(Base):
    """What notification subscribers last heard about each spacecraft."""
    __tablename__ = "push_state"
    spacecraft = Column(String, primary_key=True)
    last_km = Column(Float, nullable=False)  # distance from the Sun
    farthest_earth_km = Column(Float, nullable=False)
