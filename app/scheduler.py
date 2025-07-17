from apscheduler.schedulers.background import BackgroundScheduler
from .distance_fetcher import get_voyager2_distance_from_earth
from .database import SessionLocal
from .models import User
from .emailer import send_email

DISTANCE_UNITS = {
    "light_second": 299792.458,
    "light_minute": 299792.458 * 60,
    "light_hour": 299792.458 * 3600,
}

scheduler = BackgroundScheduler()

def check_and_notify():
    db = SessionLocal()
    current_distance = get_voyager2_distance_from_earth()

    users = db.query(User).all()
    for user in users:
        unit_km = DISTANCE_UNITS.get(user.unit)
        if not unit_km:
            continue

        if (current_distance - user.last_notified_distance) >= unit_km:
            send_email(
                user.email,
                f"Voyager 2 moved {user.unit.replace('_', ' ')}",
                unit=user.unit,
                distance_km=current_distance
            )
            user.last_notified_distance = current_distance

    db.commit()
    db.close()

def start():
    scheduler.add_job(check_and_notify, 'interval', hours=4, id='voyager_check')
    scheduler.start()

def get_jobs():
    """Return information about scheduled jobs"""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'name': job.name,
            'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
            'trigger': str(job.trigger)
        })
    return jobs