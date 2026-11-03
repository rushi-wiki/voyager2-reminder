import os
import tempfile
from datetime import date

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
    # Opening the link alone must not subscribe anyone
    page = client.get(f"/verify?token={token}")
    assert page.status_code == 200
    assert 'method="post"' in page.text
    db.expire_all()
    assert db.query(User).filter_by(email="new@example.com").one().verified is False

    assert client.post(f"/verify?token={token}").status_code == 200
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
    monkeypatch.setattr(site, "get_dsn_contacts", lambda: {})
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


def test_page_uses_tabs_with_one_spacecraft_showing_first(page_data):
    html = client.get("/").text
    assert 'role="tablist"' in html
    assert 'id="tab-voyager_1" aria-controls="panel-voyager_1" aria-selected="true"' in html
    assert 'id="tab-voyager_2" aria-controls="panel-voyager_2" aria-selected="false"' in html
    assert 'id="panel-voyager_1" aria-labelledby="tab-voyager_1" class="panel" data-craft="voyager-1">' in html
    assert 'id="panel-voyager_2" aria-labelledby="tab-voyager_2" class="panel" data-inactive data-craft="voyager-2">' in html


def test_page_has_a_live_distance_counter_for_each_spacecraft(page_data):
    html = client.get("/").text
    assert html.count('data-field="odometer"') == 2
    assert "km from Earth, growing by 31.5 km every second" in html


def test_counter_says_when_the_gap_is_shrinking(page_data, monkeypatch):
    monkeypatch.setattr(page_data, "get_position", lambda key: position(1432.5, earth_km_s=-8.2))
    assert "km from Earth, shrinking by 8.2 km every second" in client.get("/").text


def test_latest_data_lets_an_open_page_stay_current(page_data):
    data = client.get("/api/latest").json()
    assert set(data["craft"]) == {"voyager_1", "voyager_2"}
    craft = data["craft"]["voyager_1"]
    assert craft["count"] == 1432
    assert craft["next"].startswith("Next email at light-minute 1,433")
    assert craft["next"].endswith("The numbers here stay live.")
    assert "Next email at light-minute 1,433" in client.get("/").text


def test_latest_data_reports_an_outage(monkeypatch):
    from app import site

    monkeypatch.setattr(site, "_snapshot", None)
    monkeypatch.setattr(site, "get_position", lambda key: None)
    assert client.get("/api/latest").status_code == 503


def test_dish_feed_refreshes_more_often_than_positions(page_data, monkeypatch):
    client.get("/")
    calls = []
    monkeypatch.setattr(page_data, "get_dsn_contacts", lambda: calls.append(1) or {"voyager_1": {"station": "Madrid", "dish": "DSS63", "rate_bps": 160.0}})
    page_data._refresh_lock.acquire()
    page_data._refresh_in_background(page_data._refresh_contacts)
    assert calls == [1]
    assert "Madrid" in client.get("/api/latest").json()["craft"]["voyager_1"]["heard"]


def test_a_failed_dish_lookup_keeps_what_we_knew(page_data, monkeypatch):
    client.get("/")
    monkeypatch.setattr(page_data, "get_dsn_contacts", lambda: {"voyager_1": {"station": "Madrid", "dish": "DSS63", "rate_bps": 160.0}})
    page_data._refresh_contacts()
    monkeypatch.setattr(page_data, "get_dsn_contacts", lambda: None)
    page_data._refresh_contacts()
    assert "Madrid" in client.get("/api/latest").json()["craft"]["voyager_1"]["heard"]


def test_real_trajectories_are_served_and_match_history():
    import math

    response = client.get("/trajectories.json")
    assert response.status_code == 200
    bodies = response.json()["bodies"]
    assert set(bodies) == {"voyager_1", "voyager_2", "Earth", "Jupiter", "Saturn", "Uranus", "Neptune"}

    def at(body, day):
        i = next(n for n, t in enumerate(body["t"]) if t >= day)
        return body["x"][i], body["y"][i]

    # Voyager 2 met Neptune in August 1989, and Voyager 1 is past 170 AU by now
    flyby = (date(1989, 8, 25) - date(1977, 8, 20)).days
    assert math.dist(at(bodies["voyager_2"], flyby), at(bodies["Neptune"], flyby)) < 0.5
    now = (date(2026, 11, 2) - date(1977, 8, 20)).days
    assert 171 < math.hypot(*at(bodies["voyager_1"], now)) < 174


def test_page_offers_the_journey_without_loading_it_up_front(page_data):
    html = client.get("/").text
    assert 'id="journey"' in html
    assert "<dialog" not in html
    assert html.count('title="Press the map to watch the journey"') == 2
    assert "Watch the real journey" not in html
    assert "voyager_1" in html and '"t":[' not in html


def test_page_script_has_valid_syntax():
    import shutil
    import subprocess

    from app import site

    if not shutil.which("node"):
        pytest.skip("Node.js isn't available")
    result = subprocess.run(["node", "--check", "-"], input=site.SCRIPT, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_page_keeps_its_wide_screen_layout():
    from app import site

    assert "@media (min-width: 900px)" in site.STYLES
    assert '"intro signup" "content content"' in site.STYLES
    assert "minmax(0, 7fr) minmax(0, 5fr)" in site.STYLES


def test_light_is_the_default_with_a_dark_switch(page_data):
    html = client.get("/").text
    assert "prefers-color-scheme" not in html
    assert ':root[data-theme="dark"]' in html
    assert 'id="theme-toggle"' in html
    assert "Dark mode<" not in html


def test_map_tile_keeps_one_size_when_the_journey_plays():
    from app import site

    assert "min-height: 330px" not in site.STYLES
    assert ".map.playing { min" not in site.STYLES
    assert "object-fit: contain" in site.STYLES


def test_animation_uses_the_same_geometry_as_the_map_picture():
    from app import site, visuals

    assert f"const MAP_WIDTH = {visuals.WIDTH};" in site.SCRIPT
    assert f"const MAP_HEIGHT = {visuals.HEIGHT};" in site.SCRIPT
    assert f"const MAP_SUN_X = {visuals.SUN_X};" in site.SCRIPT
    assert f"const MAP_PX_PER_SQRT_AU = {visuals.PX_PER_SQRT_AU};" in site.SCRIPT


def test_the_app_can_be_installed(page_data):
    html = client.get("/").text
    assert 'rel="manifest"' in html
    manifest = client.get("/manifest.webmanifest")
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    data = manifest.json()
    assert data["display"] == "standalone"
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for icon in data["icons"]:
        response = client.get(icon["src"])
        assert response.status_code == 200
        assert response.content[:4] == b"\x89PNG"
    worker = client.get("/sw.js")
    assert "javascript" in worker.headers["content-type"]
    assert worker.headers["cache-control"] == "no-cache"
    assert client.get("/icons/secret.txt").status_code == 404


def test_page_scripts_have_valid_syntax_including_the_worker():
    import shutil
    import subprocess

    from app import site

    if not shutil.which("node"):
        pytest.skip("Node.js isn't available")
    result = subprocess.run(["node", "--check", "-"], input=site.SERVICE_WORKER, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_controls_are_icons_with_labels_for_screen_readers(page_data):
    html = client.get("/").text
    assert 'id="journey-play" data-state="play" aria-label="Play"' in html
    assert 'aria-label="Subscribe"' in html
    assert ">Subscribe<" not in html
    assert ">Pause<" not in html


def test_year_comes_first_so_it_never_shifts(page_data):
    html = client.get("/").text
    assert '<span id="journey-year"></span><span id="journey-month"></span>' in html


def test_the_journey_starts_at_zero_with_no_rewind():
    from app import site

    assert "rewind" not in site.SCRIPT.lower()
    assert "progress = stillOnly ? 1 : 0;" in site.SCRIPT


@pytest.fixture
def push_on(db, monkeypatch):
    from app import models, push

    db.query(models.PushSubscription).delete()
    db.query(models.PushState).delete()
    db.commit()
    main._signups_by_ip.clear()
    main._signups_today.clear()
    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "public")
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "private")
    sent = []
    monkeypatch.setattr(push, "send", lambda subscription, title, body: sent.append((subscription.endpoint, title, body)) or True)
    return sent


PUSH_BODY = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "k", "auth": "a"}}


def test_subscribing_to_notifications_sends_a_welcome(db, push_on):
    from app import models

    assert client.post("/push/subscribe", json=PUSH_BODY).status_code == 201
    assert db.query(models.PushSubscription).count() == 1
    assert push_on[0][1] == "Notifications are on"
    assert client.post("/push/subscribe", json=PUSH_BODY).status_code == 201
    db.expire_all()
    assert db.query(models.PushSubscription).count() == 1
    assert client.post("/push/unsubscribe", json={"endpoint": PUSH_BODY["endpoint"]}).status_code == 200
    db.expire_all()
    assert db.query(models.PushSubscription).count() == 0


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/x",
        "https://evil.example.com/x",
        "https://fcm.googleapis.com.evil.example/x",
        "https://169.254.169.254/latest",
        "https://localhost/x",
    ],
)
def test_notifications_only_go_to_real_push_services(db, push_on, endpoint):
    response = client.post("/push/subscribe", json=dict(PUSH_BODY, endpoint=endpoint))
    assert response.status_code == 400
    assert push_on == []


def test_notifications_fire_once_per_light_minute_and_ignore_old_news(db, push_on):
    from app import models, push

    db.add(models.PushSubscription(endpoint=PUSH_BODY["endpoint"], p256dh="k", auth="a"))
    db.commit()
    push.notify_subscribers(db, "voyager_1", position(1432.5))
    assert push_on == []
    push.notify_subscribers(db, "voyager_1", position(1432.9))
    assert push_on == []
    push.notify_subscribers(db, "voyager_1", position(1433.1))
    assert [m[1] for m in push_on] == ["Voyager 1 passed light-minute 1,433"]
    push.notify_subscribers(db, "voyager_1", position(1433.2))
    assert len(push_on) == 1


def test_light_day_notification_fires_once_despite_earth_dip(db, push_on):
    from app import models, push

    db.add(models.PushSubscription(endpoint=PUSH_BODY["endpoint"], p256dh="k", auth="a"))
    db.commit()
    push.notify_subscribers(db, "voyager_1", position(1432.1, earth_km=LIGHT_DAY_KM * 0.999))
    push.notify_subscribers(db, "voyager_1", position(1432.2, earth_km=LIGHT_DAY_KM * 1.0001))
    assert [m[1] for m in push_on] == ["Voyager 1 is now one light-day from Earth"]
    push.notify_subscribers(db, "voyager_1", position(1432.3, earth_km=LIGHT_DAY_KM * 0.9999))
    push.notify_subscribers(db, "voyager_1", position(1432.4, earth_km=LIGHT_DAY_KM * 1.0002))
    assert len(push_on) == 1


def test_gone_browsers_are_removed(db, push_on, monkeypatch):
    from app import models, push

    db.add(models.PushSubscription(endpoint=PUSH_BODY["endpoint"], p256dh="k", auth="a"))
    db.commit()
    push.notify_subscribers(db, "voyager_1", position(1432.5))
    monkeypatch.setattr(push, "send", lambda subscription, title, body: False)
    push.notify_subscribers(db, "voyager_1", position(1433.5))
    assert db.query(models.PushSubscription).count() == 0


def test_a_broken_notification_never_stops_the_emails(db, sent, monkeypatch):
    from app import push

    add_user(db)
    def boom(*args):
        raise RuntimeError("push service down")
    monkeypatch.setattr(push, "notify_subscribers", boom)
    run_check(monkeypatch, position(1432.5))
    assert len(sent) == 1


def test_real_encryption_works_with_generated_keys(monkeypatch):
    # The real library and real keys, stopping only at the network
    import base64
    from types import SimpleNamespace

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app import push

    def b64(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    server = ec.generate_private_key(ec.SECP256R1())
    raw = server.private_numbers().private_value.to_bytes(32, "big")
    browser = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", b64(raw))
    posted = []

    class FakeResponse:
        status_code = 201
        text = ""
        headers = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        posted.append((url, data, headers))
        return FakeResponse()

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    subscription = SimpleNamespace(endpoint=PUSH_BODY["endpoint"], p256dh=b64(browser), auth=b64(b"0123456789abcdef"))
    assert push.send(subscription, "Title", "Body") is True
    url, data, headers = posted[0]
    assert url == PUSH_BODY["endpoint"]
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["authorization"].startswith("vapid ")
    assert b"Title" not in data


def test_map_picture_uses_the_animations_planets():
    from app import visuals

    x, y = visuals._planet_position("Neptune")
    assert 29 < (x * x + y * y) ** 0.5 < 31


def test_bad_confirmation_links_are_refused(db):
    assert client.get("/verify?token=nope").status_code == 400
    assert client.post("/verify?token=nope").status_code == 400


def test_responses_carry_security_headers(page_data):
    response = client.get("/")
    csp = response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["strict-transport-security"].startswith("max-age=")
    assert "content-security-policy" in client.get("/api/latest").headers


def test_requirements_are_pinned():
    from pathlib import Path

    lines = [line for line in Path("requirements.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert lines and all("==" in line for line in lines)
