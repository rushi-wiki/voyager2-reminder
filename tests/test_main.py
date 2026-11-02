import os
import tempfile

import pytest

_db_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_dir}/test.db"

from fastapi.testclient import TestClient

from app import database, distance_fetcher, emailer, main, models, scheduler
from app.emailer import LIGHT_DAY_KM, LIGHT_SPEED_KM_S, build_update, send_update
from app.postcards import POSTCARD_DIR, POSTCARDS, postcard_for
from app.models import Subscription, User

client = TestClient(main.app)

LIGHT_MINUTE_KM = LIGHT_SPEED_KM_S * 60
JPEG_START = bytes([0xFF, 0xD8])

HORIZONS_TEXT = """
$$SOE
2461346.500000000 = A.D. 2026-Nov-02 00:00:00.0000 TDB
 X = 1.0E+09 Y =-2.0E+10 Z = 1.5E+10
 VX= 1.0E+01 VY= 2.0E+01 VZ= 3.0E+00
 LT= 8.626E+04 RG= 2.586010322E+10 RR= 3.149873E+01
$$EOE
"""

DSN_XML = """<dsn>
<station name="gdscc" friendlyName="Goldstone"/>
<dish name="DSS14"><downSignal active="true" dataRate="1000" spacecraft="MRO"/><target name="MRO"/></dish>
<station name="mdscc" friendlyName="Madrid"/>
<dish name="DSS63">
  <downSignal active="false" dataRate="9" spacecraft="VGR2"/>
  <downSignal active="true" dataRate="160" spacecraft="VGR1"/>
  <target name="VGR1"/>
</dish>
</dsn>"""


def position(sun_minutes, earth_km=None, earth_km_s=31.5):
    return {
        "earth_km": earth_km if earth_km is not None else LIGHT_DAY_KM * 0.5,
        "earth_km_s": earth_km_s,
        "sun_km": sun_minutes * LIGHT_MINUTE_KM,
        "sun_km_s": 16.9,
        "sun_x_km": -3.0e9,
        "sun_y_km": -2.0e10,
    }


@pytest.fixture
def db(monkeypatch):
    session = database.SessionLocal()
    session.query(Subscription).delete()
    session.query(User).delete()
    session.commit()
    monkeypatch.setattr(scheduler, "get_dsn_contact", lambda key: None)
    yield session
    session.close()


@pytest.fixture
def sent(monkeypatch):
    emails = []
    monkeypatch.setattr(
        scheduler, "send_update", lambda to, update, url=None: emails.append((to, update))
    )
    return emails


def add_user(db, email="a@example.com", unit="light_minute"):
    user = User(email=email, unit=unit, verified=True)
    models.subscribe_to_all(user)
    db.add(user)
    db.commit()
    return user


def run_check(monkeypatch, voyager_1, voyager_2=None):
    positions = {"voyager_1": voyager_1, "voyager_2": voyager_2}
    monkeypatch.setattr(scheduler, "get_position", lambda key: positions[key])
    scheduler.check_and_notify()


def test_parse_range():
    assert distance_fetcher.parse_range(HORIZONS_TEXT) == (2.586010322e10, 31.49873, 1.0e9, -2.0e10)
    assert distance_fetcher.parse_range("no table here") is None


def test_parse_dsn_contact():
    assert distance_fetcher.parse_dsn_contact(DSN_XML, "VGR1") == {
        "station": "Madrid",
        "dish": "DSS63",
        "rate_bps": 160.0,
    }
    # An inactive signal doesn't count as being heard
    assert distance_fetcher.parse_dsn_contact(DSN_XML, "VGR2") is None


def test_emails_once_per_light_minute(db, sent, monkeypatch):
    add_user(db)
    run_check(monkeypatch, position(1432.5))
    assert len(sent) == 1
    assert "Voyager 1 passed light-minute 1,432" in sent[0][1]["subject"]

    run_check(monkeypatch, position(1432.9))
    assert len(sent) == 1

    run_check(monkeypatch, position(1433.1))
    assert len(sent) == 2


def test_keeps_emailing_while_earth_distance_shrinks(db, sent, monkeypatch):
    add_user(db)
    run_check(monkeypatch, position(100.5, earth_km=LIGHT_DAY_KM * 0.5))
    run_check(monkeypatch, position(101.5, earth_km=LIGHT_DAY_KM * 0.49, earth_km_s=-8.2))
    assert len(sent) == 2
    assert "Earth is catching up" in sent[1][1]["html"]


def test_light_day_email_is_sent_once_despite_earth_dip(db, sent, monkeypatch):
    add_user(db)
    run_check(monkeypatch, position(1432.1, earth_km=LIGHT_DAY_KM * 0.999))
    assert len(sent) == 1

    # Crossing sends a milestone even without a new light-minute
    run_check(monkeypatch, position(1432.2, earth_km=LIGHT_DAY_KM * 1.0001))
    assert len(sent) == 2
    assert sent[1][1]["subject"] == "Voyager 1 is now one light-day from Earth"

    # Dropping back under and crossing again isn't news
    run_check(monkeypatch, position(1432.3, earth_km=LIGHT_DAY_KM * 0.9999))
    run_check(monkeypatch, position(1432.4, earth_km=LIGHT_DAY_KM * 1.0002))
    assert len(sent) == 2


def test_first_check_does_not_announce_old_milestones(db, sent, monkeypatch):
    add_user(db)
    run_check(monkeypatch, position(1500.5, earth_km=LIGHT_DAY_KM * 1.2))
    assert len(sent) == 1
    assert "light-day" not in sent[0][1]["subject"]


def test_tracks_each_spacecraft_separately(db, sent, monkeypatch):
    add_user(db)
    run_check(monkeypatch, position(1432.5), position(1200.5))
    assert sorted(update["subject"].split(" passed")[0] for _, update in sent) == [
        "Voyager 1",
        "Voyager 2",
    ]
    twin_lines = [update["html"] for _, update in sent]
    assert "Voyager 2&#x27;s signal takes" in twin_lines[0]


def test_jpl_outage_sends_nothing_and_loses_nothing(db, sent, monkeypatch):
    add_user(db)
    run_check(monkeypatch, None)
    assert sent == []
    run_check(monkeypatch, position(1432.5))
    assert len(sent) == 1


def test_failed_send_is_retried_and_does_not_block_others(db, monkeypatch):
    add_user(db, "bad@example.com")
    add_user(db, "good@example.com")
    delivered = []

    def flaky(to, update, url=None):
        if to == "bad@example.com" and not delivered.count("recovered"):
            raise OSError("smtp down")
        delivered.append(to)

    monkeypatch.setattr(scheduler, "send_update", flaky)
    run_check(monkeypatch, position(1432.5))
    assert delivered == ["good@example.com"]

    delivered.append("recovered")
    run_check(monkeypatch, position(1432.6))
    assert delivered == ["good@example.com", "recovered", "bad@example.com"]


def test_unverified_users_get_nothing(db, sent, monkeypatch):
    user = add_user(db)
    user.verified = False
    db.commit()
    run_check(monkeypatch, position(1432.5))
    assert sent == []


def test_backfill_moves_existing_users_once(db):
    old = User(email="old@example.com", unit="light_second", verified=True)
    pending = User(email="pending@example.com", unit="light_second", verified=False)
    db.add_all([old, pending])
    db.commit()

    models.backfill_subscriptions(db)
    assert old.unit == "light_minute"
    assert sorted(s.spacecraft for s in old.subscriptions) == ["voyager_1", "voyager_2"]
    assert pending.unit == "light_second"
    assert pending.subscriptions == []

    # Someone choosing light seconds afterwards keeps that choice
    old.unit = "light_second"
    db.commit()
    models.backfill_subscriptions(db)
    assert old.unit == "light_second"
    assert len(old.subscriptions) == 2


def test_register_verify_and_unsubscribe(db, monkeypatch):
    main._signups_by_ip.clear()
    main._signups_today.clear()
    links = []
    monkeypatch.setattr(main, "send_verification_email", lambda to, url: links.append(url))

    response = client.post("/register", json={"email": "new@example.com", "unit": "light_minute"})
    assert response.status_code == 202
    token = links[0].split("token=")[1]
    assert client.get(f"/verify?token={token}").status_code == 200

    db.expire_all()
    user = db.query(User).filter_by(email="new@example.com").one()
    assert sorted(s.spacecraft for s in user.subscriptions) == ["voyager_1", "voyager_2"]

    assert client.post(f"/unsubscribe?token={user.unsubscribe_token}").status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(email="new@example.com").count() == 0
    assert db.query(Subscription).count() == 0


def test_register_rejects_bad_input(db):
    response = client.post("/register", json={"email": "x@example.com", "unit": "parsec"})
    assert response.status_code == 400


@pytest.mark.parametrize(
    "method,path",
    [("get", "/users/1"), ("delete", "/users/1"), ("post", "/users/1/notify")],
)
def test_user_id_endpoints_are_gone(db, method, path):
    assert getattr(client, method)(path).status_code == 404


def test_update_content(monkeypatch):
    update = build_update(
        "voyager_1",
        "light_minute",
        {
            "earth_km": 86400 * LIGHT_SPEED_KM_S - 140 * LIGHT_SPEED_KM_S,
            "earth_km_s": 31.5,
            "sun_km": 1432.3 * LIGHT_MINUTE_KM,
            "sun_km_s": 16.9,
            "sun_x_km": -3.0e9,
            "sun_y_km": -2.5e10,
        },
        previous_sun_km=1431.3 * LIGHT_MINUTE_KM,
        twin_name="Voyager 2",
        twin_position=position(1200, earth_km=72134 * LIGHT_SPEED_KM_S),
        contact={"station": "Madrid", "dish": "DSS63", "rate_bps": 160.0},
        unsubscribe_url="https://example.com/unsubscribe?token=abc",
    )
    assert update["subject"] == "Voyager 1 passed light-minute 1,432, signal now 23h 57m from Earth"
    assert "23h 57m 40s" in update["html"]
    assert "Only 2m 20s short of a full light-day" in update["html"]
    assert "1 day 23 hours 55 minutes" in update["text"]
    assert "16.9 from Voyager 1, 14.6 from Earth" in update["text"]
    assert "18.0 million km" in update["text"]
    assert "Madrid's DSS63 dish is receiving Voyager 1 at 160 bits per second" in update["text"]
    assert "Voyager 2's signal takes 20h 02m 14s" in update["text"]
    assert "Unsubscribe: https://example.com/unsubscribe?token=abc" in update["text"]
    assert 'src="cid:map"' in update["html"]
    assert 'src="cid:postcard"' in update["html"]
    assert update["images"]["map"][:2] == JPEG_START
    assert update["images"]["postcard"][:2] == JPEG_START
    for unsupported in ("display:flex", "display:grid", "backdrop-filter", "animation"):
        assert unsupported not in update["html"]


def test_every_postcard_has_its_image_and_text():
    for cards in POSTCARDS.values():
        for card in cards:
            assert (POSTCARD_DIR / card["image"]).stat().st_size > 1000
            assert card["alt"] and card["title"] and card["story"]


def test_postcards_change_every_update_and_milestones_use_the_first():
    seen = {postcard_for("voyager_1", count)["image"] for count in range(6)}
    assert len(seen) == len(POSTCARDS["voyager_1"])
    assert postcard_for("voyager_1", 3, milestone=True)["image"] == "pale-blue-dot.jpg"


def test_map_copes_with_any_relative_position():
    for x, y in [(1e10, 0), (-1e10, 0), (0, 1e10), (0, -1e10)]:
        data = build_update("voyager_2", "light_minute", dict(position(1200.5), sun_x_km=x, sun_y_km=y),
                            twin_name="Voyager 1", twin_position=position(1432.5))["images"]["map"]
        assert data[:2] == JPEG_START


def test_milestone_wording(monkeypatch):
    update = build_update("voyager_1", "light_minute", position(1441.5, earth_km=LIGHT_DAY_KM * 1.00001), light_days=1)
    assert update["subject"] == "Voyager 1 is now one light-day from Earth"
    assert "Milestone reached" in update["html"]
    assert "No spacecraft has ever been this far" in update["html"]
    assert "The Pale Blue Dot" in update["html"]


def test_sent_message_carries_images_inline(monkeypatch):
    captured = []

    class FakeSMTP:
        def __init__(self, host, port):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, msg):
            captured.append(msg)

    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)
    update = build_update("voyager_1", "light_minute", position(1432.5), unsubscribe_url="https://example.com/u")
    send_update("a@example.com", update, "https://example.com/u")

    msg = captured[0]
    assert msg.get_content_type() == "multipart/related"
    assert msg["List-Unsubscribe"] == "<https://example.com/u>"
    parts = msg.get_payload()
    assert parts[0].get_content_type() == "multipart/alternative"
    assert [p["Content-ID"] for p in parts[1:]] == ["<map>", "<postcard>"]
    assert all(p.get_content_type() == "image/jpeg" for p in parts[1:])
    assert all(p["Content-Disposition"].startswith("inline") for p in parts[1:])


def test_each_update_gets_its_own_identity(monkeypatch):
    captured = []

    class FakeSMTP:
        def __init__(self, host, port):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, msg):
            captured.append(msg)

    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)
    first = build_update("voyager_1", "light_minute", position(1432.5))
    second = build_update("voyager_1", "light_minute", position(1433.5))
    send_update("a@example.com", first)
    send_update("a@example.com", second)

    assert first["subject"] != second["subject"]
    assert captured[0]["Message-ID"] != captured[1]["Message-ID"]
    assert captured[0]["X-Entity-Ref-ID"] != captured[1]["X-Entity-Ref-ID"]
    for msg in captured:
        assert msg["In-Reply-To"] is None
        assert msg["References"] is None


def test_design_declares_both_colour_schemes():
    html = build_update("voyager_1", "light_minute", position(1432.5))["html"]
    assert '<meta name="color-scheme" content="light dark">' in html
    assert 'bgcolor="#05060e"' in html


@pytest.fixture
def page_data(monkeypatch):
    from app import site

    positions = {"voyager_1": position(1432.5, earth_km=LIGHT_DAY_KM * 0.998), "voyager_2": position(1200.5)}
    monkeypatch.setattr(site, "_snapshot", None)
    monkeypatch.setattr(site, "get_position", lambda key: positions[key])
    monkeypatch.setattr(site, "get_dsn_contact", lambda key: None)
    return site


def test_page_shows_the_same_update_as_the_email(page_data):
    html = client.get("/").text
    assert "Voyager, right now" in html
    assert 'id="subscribe"' in html
    emailed = build_update(
        "voyager_1", "light_minute", position(1432.5, earth_km=LIGHT_DAY_KM * 0.998),
        twin_name="Voyager 2", twin_position=position(1200.5),
    )
    for phrase in (
        "Voyager 1", "Voyager 2", "Light-minute 1,432", "Light-minute 1,200",
        "for its signal to reach Earth", "AU from the Sun", "From the Voyager archive",
    ):
        assert phrase in html
    assert re_lead(emailed["html"]) in html
    assert "cid:" not in html


def re_lead(html):
    import re

    return re.search(r"font-size:15px;line-height:22px;[^>]*>([^<]+)<", html).group(1)


def test_page_images_are_served(page_data):
    html = client.get("/").text
    assert client.get("/images/map/voyager_1.jpg").content[:2] == JPEG_START
    for name in page_data.POSTCARD_IMAGES:
        assert f"/images/postcards/{name}" in html or client.get(f"/images/postcards/{name}").status_code == 200
    image = client.get("/images/postcards/golden-record.jpg")
    assert image.status_code == 200
    assert image.content[:2] == JPEG_START


@pytest.mark.parametrize(
    "path",
    ["/images/map/voyager_3.jpg", "/images/postcards/secret.txt", "/images/postcards/..%2Fpostcards.py"],
)
def test_only_known_images_are_served(page_data, path):
    assert client.get(path).status_code == 404


def test_page_survives_nasa_being_unreachable(monkeypatch):
    from app import site

    monkeypatch.setattr(site, "_snapshot", None)
    monkeypatch.setattr(site, "get_position", lambda key: None)
    response = client.get("/")
    assert response.status_code == 200
    assert "out of reach" in response.text
    assert 'id="subscribe"' in response.text


def test_page_keeps_old_data_during_an_outage(page_data, monkeypatch):
    client.get("/")
    before = page_data._snapshot
    monkeypatch.setattr(page_data, "get_position", lambda key: None)
    monkeypatch.setattr(page_data, "_snapshot", dict(before, fetched_at=0))
    page_data._refresh_lock.acquire()
    page_data._refresh_in_background()
    assert page_data._snapshot["positions"] == before["positions"]
    assert "Light-minute 1,432" in client.get("/").text


@pytest.fixture
def signup(db, monkeypatch):
    main._signups_by_ip.clear()
    main._signups_today.clear()
    links = []
    monkeypatch.setattr(main, "send_verification_email", lambda to, url: links.append((to, url)))
    return links


def test_form_signup_defaults_to_light_minutes(db, signup):
    response = client.post("/register", json={"email": "form@example.com", "company": ""})
    assert response.status_code == 202
    assert db.query(User).filter_by(email="form@example.com").one().unit == "light_minute"
    assert len(signup) == 1


def test_existing_address_gets_the_same_answer_and_no_email(db, signup):
    add_user(db, "known@example.com")
    response = client.post("/register", json={"email": "known@example.com"})
    assert response.status_code == 202
    assert response.json()["message"] == main.CHECK_INBOX
    assert signup == []


def test_bots_filling_the_hidden_field_are_ignored(db, signup):
    response = client.post("/register", json={"email": "bot@example.com", "company": "Acme"})
    assert response.status_code == 202
    assert db.query(User).filter_by(email="bot@example.com").count() == 0
    assert signup == []


def test_signups_are_limited_per_address(db, signup):
    headers = {"fly-client-ip": "203.0.113.9"}
    for i in range(main.SIGNUPS_PER_IP_PER_HOUR):
        assert client.post("/register", json={"email": f"u{i}@example.com"}, headers=headers).status_code == 202
    assert client.post("/register", json={"email": "more@example.com"}, headers=headers).status_code == 429
    other = client.post("/register", json={"email": "other@example.com"}, headers={"fly-client-ip": "203.0.113.10"})
    assert other.status_code == 202


def test_signups_have_a_daily_ceiling(db, signup, monkeypatch):
    monkeypatch.setattr(main, "SIGNUPS_PER_DAY", 2)
    for i in range(2):
        client.post("/register", json={"email": f"d{i}@example.com"}, headers={"fly-client-ip": f"203.0.113.{i}"})
    response = client.post("/register", json={"email": "d3@example.com"}, headers={"fly-client-ip": "203.0.113.50"})
    assert response.status_code == 429
