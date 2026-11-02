from apscheduler.schedulers.background import BackgroundScheduler
from .distance_fetcher import SPACECRAFT, get_dsn_contact, get_position
from . import push
from .database import SessionLocal
from .models import Subscription, User
from .emailer import DISTANCE_UNITS, LIGHT_DAY_KM, build_update, send_update, unsubscribe_url_for

scheduler = BackgroundScheduler()

def _whole_units(distance_km, unit_km):
    return int(distance_km // unit_km)

def _light_day_reached(position, subscription):
    """The new light-day count, the first time Earth distance passes it.

    Earth distance dips for months each year as Earth's orbit catches up with
    the spacecraft, so it is compared with the farthest distance seen. The
    first check only records a starting point, so nobody is told about a
    milestone that was passed long ago.
    """
    farthest = subscription.farthest_earth_km
    if not farthest:
        return None
    days = _whole_units(position["earth_km"], LIGHT_DAY_KM)
    return days if days > _whole_units(farthest, LIGHT_DAY_KM) else None

def check_and_notify():
    db = SessionLocal()
    try:
        positions = {key: get_position(key) for key in SPACECRAFT}
        for key, position in positions.items():
            # Skip this round if JPL is unreachable; the next check catches up
            if position is None:
                continue
            twin_key = next(k for k in SPACECRAFT if k != key)
            contact = get_dsn_contact(key)

            # Notifications must never get in the way of the emails
            try:
                push.notify_subscribers(db, key, position)
            except Exception as e:
                db.rollback()
                print(f"Notifications failed: {type(e).__name__}")

            subscriptions = (
                db.query(Subscription)
                .join(User)
                .filter(User.verified == True, Subscription.spacecraft == key)
                .all()
            )
            for subscription in subscriptions:
                user = subscription.user
                unit_km = DISTANCE_UNITS.get(user.unit)
                if not unit_km:
                    continue

                light_days = _light_day_reached(position, subscription)
                crossed = (
                    _whole_units(position["sun_km"], unit_km)
                    > _whole_units(subscription.last_notified_km, unit_km)
                )
                if light_days or crossed:
                    unsubscribe_url = unsubscribe_url_for(user)
                    try:
                        update = build_update(
                            key,
                            user.unit,
                            position,
                            previous_sun_km=subscription.last_notified_km,
                            twin_name=SPACECRAFT[twin_key]["name"],
                            twin_position=positions[twin_key],
                            contact=contact,
                            light_days=light_days,
                            unsubscribe_url=unsubscribe_url,
                        )
                        send_update(user.email, update, unsubscribe_url)
                    except Exception as e:
                        # Leave this subscriber's state alone so the next check
                        # retries, and carry on with everyone else.
                        print(f"Sending to user {user.id} failed: {e}")
                        continue
                    subscription.last_notified_km = position["sun_km"]

                subscription.farthest_earth_km = max(
                    subscription.farthest_earth_km, position["earth_km"]
                )
                # Commit per subscriber so a later crash can't cause a repeat email
                db.commit()
    finally:
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
