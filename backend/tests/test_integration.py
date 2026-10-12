"""Seams between the worker, the engines, the text pipeline and the API."""

import unicodedata

import pytest
from fastapi.testclient import TestClient

from app.pipeline.translate.base import SPLIT, TRUNCATED
from app.pipeline.validate import AMBER, check
from app.worker import _engine_flags, _with_flags

SRC = "निविदा की अंतिम तिथि 25.03.2026 तक बढ़ाई गई है।"
GOOD = "The last date of the tender has been extended to 25.03.2026."


class _Engine:
    last_flags = [{TRUNCATED}, {SPLIT}]


def test_engine_flags_are_padded_to_the_batch():
    assert _engine_flags(_Engine(), 3) == [{TRUNCATED}, {SPLIT}, set()]
    assert _engine_flags(object(), 2) == [set(), set()]


def test_truncated_output_is_worth_a_check():
    result = _with_flags(check(SRC, GOOD), {TRUNCATED})
    assert result.issues == {"truncated": AMBER} and result.confidence == "amber"
    assert _with_flags(check(SRC, GOOD), {SPLIT}).confidence == "green"


@pytest.fixture()
def client(app_env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_glossary_terms_are_stored_in_one_unicode_form(client):
    decomposed = "ब" + "ढ" + "़" + "ाई"          # ढ + nukta
    precomposed = "ब" + "ढ़" + "ाई"               # ढ़ as one code point
    client.post("/api/glossary", json={"hindi": precomposed, "english": "increase"})
    client.post("/api/glossary", json={"hindi": decomposed, "english": "extension"})
    terms = client.get("/api/glossary").json()
    assert len(terms) == 1  # the same word, however it was typed
    assert terms[0]["hindi"] == unicodedata.normalize("NFC", precomposed)
    assert terms[0]["english"] == "extension"


def test_importing_the_model_store_itself_is_refused(client, app_env):
    r = client.post("/api/models/import", json={"path": str(app_env.models_dir)})
    assert r.status_code == 400


def test_tips_no_longer_promise_notifications_with_the_tab_closed(client):
    from app.main import TIPS

    assert not any("close this page" in t for t in TIPS)
