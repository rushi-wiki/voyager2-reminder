from sqlalchemy import Column, Integer, String, Float, Boolean
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    unit = Column(String)  # e.g., "light_second", "light_hour"
    last_notified_distance = Column(Float, default=0.0)
    verified = Column(Boolean, default=False, nullable=False)
    verify_token = Column(String, nullable=True, index=True)
