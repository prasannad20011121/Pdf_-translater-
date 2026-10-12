"""API: Host/Origin protection, id validation, uploads, timestamps, glossary import and
the database migration."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def upload(client, path, choice="auto", **kwargs):
    with open(path, "rb") as f:
        return client.post("/api/jobs", files={"file": (path.name, f, "application/pdf")},
                           data={"choice": choice}, **kwargs)


# ---- Host and Origin ------------------------------------------------------------------

@pytest.mark.parametrize("host", ["127.0.0.1:8080", "localhost:8080", "[::1]:8080", "127.0.0.1", "LOCALHOST:9000"])
def test_local_host_names_are_allowed(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["attacker.example", "attacker.example:8080", "127.0.0.1.nip.io:8080",
                                  "localhost.attacker.example", "127.0.0.1:80x", "[::1", "::1"])
def test_other_host_names_are_rejected(client, host):
    """A DNS-rebinding page arrives with its own host name: it must get nothing."""
    r = client.get("/api/jobs", headers={"Host": host})
    assert r.status_code == 400
    assert r.headers["x-content-type-options"] == "nosniff"


def test_cross_site_writes_are_blocked(client, pdfs):
    evil = {"Origin": "http://attacker.example"}
    assert client.post("/api/glossary", json={"hindi": "निविदा", "english": "bribe"}, headers=evil).status_code == 403
    files = {"file": ("g.csv", "निविदा,bribe\n".encode(), "text/csv")}
    assert client.post("/api/glossary/import", files=files, headers=evil).status_code == 403
    assert upload(client, pdfs["clean"], headers=evil).status_code == 403
    assert client.post("/api/models/gemma4-e2b/download", headers=evil).status_code == 403
    assert client.post("/api/glossary", json={"hindi": "क", "english": "x"},
                       headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/glossary", json={"hindi": "क", "english": "x"},
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/glossary").json() == []  # nothing got through


def test_same_origin_writes_work(client):
    for origin in ("http://127.0.0.1:8080", "http://localhost:8080", "http://[::1]:8080"):
        r = client.post("/api/glossary", json={"hindi": "निविदा", "english": "Tender"},
                        headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 200
    # Reads don't need an Origin check (the Host check already protects them).
    assert client.get("/api/glossary", headers={"Origin": "http://attacker.example"}).status_code == 200


def test_host_name_parsing():
    from app.main import host_name

    assert host_name("127.0.0.1:8080") == "127.0.0.1"
    assert host_name("[::1]:8080") == "::1" and host_name("[::1]") == "::1"
    assert host_name("Localhost") == "localhost"
    assert host_name("") is None and host_name(None) is None
    assert host_name("[::1]x") is None and host_name("host:port") is None


# ---- ids never reach the file system unchecked -------------------------------------------------

def test_bad_job_ids_never_reach_the_file_system(client, app_env, monkeypatch):
    from app import config

    touched = []
    real = config.Settings.job_dir
    monkeypatch.setattr(config.Settings, "job_dir", lambda self, job_id: touched.append(job_id) or real(self, job_id))
    for path in ("/api/jobs/%5C%5Cattacker.example%5Cshare/pages/1.png",
                 "/api/jobs/..%5C..%5Cwindows/pages/1.png",
                 "/api/jobs/ABCDEF/download/docx",
                 f"/api/jobs/{'g' * 32}/segments"):
        assert client.get(path).status_code == 404, path
    assert client.delete("/api/jobs/%5C%5Cattacker.example%5Cshare").status_code == 404
    assert touched == []


def test_page_numbers_are_checked(client, pdfs):
    job = upload(client, pdfs["clean"]).json()
    assert client.get(f"/api/jobs/{job['id']}/pages/0.png").status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/pages/-1.png").status_code in (404, 422)
    assert client.get(f"/api/jobs/{job['id']}/pages/2.png").status_code == 404  # 1-page PDF
    assert client.get(f"/api/jobs/{'0' * 32}/pages/1.png").status_code == 404


def test_spa_paths_are_checked_before_touching_the_disk():
    from app.main import _safe_relative

    assert _safe_relative("assets/index.js") and _safe_relative("favicon.svg")
    for bad in ("\\\\attacker.example\\share\\x.js", "C:/Windows/win.ini", "../app.db", "a/../../b", "/etc/passwd", "a\x00b"):
        assert not _safe_relative(bad), bad


def test_spa_route_with_a_unc_path_does_not_stat_it(client, monkeypatch):
    from pathlib import Path

    seen = []
    real = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda self: seen.append(str(self)) or real(self))
    client.get("/%5C%5Cattacker.example%5Cshare%5Cx.js")
    assert not any("attacker" in s for s in seen)


# ---- uploads -----------------------------------------------------------------------------------

def test_upload_writes_the_file_before_the_job_is_visible(client, app_env, pdfs, monkeypatch):
    """The worker must never see a queued job whose PDF is not fully on disk."""
    from app import main
    from app.worker import next_job_id

    real_replace = main.os.replace
    seen = {}

    def replace(src, dst):
        seen["visible_before_file"] = next_job_id()
        real_replace(src, dst)

    monkeypatch.setattr(main.os, "replace", replace)
    r = upload(client, pdfs["clean"])
    assert r.status_code == 200
    job_id = r.json()["id"]
    assert seen["visible_before_file"] is None
    assert next_job_id() == job_id
    job_dir = app_env.job_dir(job_id)
    assert (job_dir / "source.pdf").read_bytes() == pdfs["clean"].read_bytes()
    assert not (job_dir / "source.pdf.part").exists()


def test_failed_upload_leaves_no_folder(client, app_env, pdfs, monkeypatch):
    from app import main

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(main.os, "replace", boom)
    with pytest.raises(OSError):
        upload(client, pdfs["clean"])
    assert list(app_env.jobs_dir.iterdir()) == []


# ---- timestamps -------------------------------------------------------------------------------

def test_timestamps_carry_a_utc_offset(client, pdfs):
    created = upload(client, pdfs["clean"]).json()
    fetched = client.get(f"/api/jobs/{created['id']}").json()
    listed = client.get("/api/jobs").json()[0]
    for data in (created, fetched, listed):
        for key in ("created_at", "updated_at"):
            parsed = datetime.fromisoformat(data[key])
            assert parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0, data[key]
    now = datetime.now(timezone.utc)
    assert abs((now - datetime.fromisoformat(fetched["created_at"])).total_seconds()) < 120


def test_iso_utc_handles_naive_and_aware_datetimes():
    from datetime import timedelta

    from app.main import iso_utc

    assert iso_utc(None) is None
    assert iso_utc(datetime(2026, 10, 11, 12, 0)) == "2026-10-11T12:00:00+00:00"
    ist = timezone(timedelta(hours=5, minutes=30))
    assert iso_utc(datetime(2026, 10, 11, 17, 30, tzinfo=ist)) == "2026-10-11T12:00:00+00:00"


# ---- glossary import -------------------------------------------------------------------------

def test_excel_ansi_csv_is_reported_and_does_not_overwrite_terms(client):
    client.post("/api/glossary", json={"hindi": "निविदा", "english": "Tender"})
    client.post("/api/glossary", json={"hindi": "दिनांक", "english": "Date"})
    # What Excel's "CSV (Comma delimited)" makes of Hindi: question marks.
    ansi = "hindi,english,note\n??????,Tender Notice,\n??????,Dated,\n".encode("cp1252")
    r = client.post("/api/glossary/import", files={"file": ("g.csv", ansi, "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 0 and body["skipped"] == 2
    assert body["errors"] and "CSV UTF-8" in body["errors"][0]
    terms = {t["hindi"]: t["english"] for t in client.get("/api/glossary").json()}
    assert terms == {"निविदा": "Tender", "दिनांक": "Date"}


def test_non_utf8_csv_is_rejected_with_a_hint(client):
    data = "hindi,english\nनिविदा,Tender café\n".encode().replace("é".encode(), b"\xe9")
    r = client.post("/api/glossary/import", files={"file": ("g.csv", data, "text/csv")})
    assert r.status_code == 400 and "CSV UTF-8" in r.json()["detail"]


def test_utf16_unicode_text_from_excel_is_imported(client):
    data = "hindi\tenglish\tnote\r\nनिविदा\tTender\t\r\nज्ञापांक\tMemo No.\tletters\r\n".encode("utf-16")
    r = client.post("/api/glossary/import", files={"file": ("g.txt", data, "text/plain")})
    assert r.status_code == 200 and r.json() == {"imported": 2, "skipped": 0, "errors": []}
    terms = {t["hindi"]: t for t in client.get("/api/glossary").json()}
    assert terms["ज्ञापांक"]["english"] == "Memo No." and terms["ज्ञापांक"]["note"] == "letters"


def test_utf8_csv_with_bad_rows_imports_the_good_ones(client):
    data = "\ufeffhindi,english\nनिविदा,Tender\n,missing hindi\nHello,World\nदिनांक,Date\n".encode()
    r = client.post("/api/glossary/import", files={"file": ("g.csv", data, "text/csv")})
    body = r.json()
    assert body["imported"] == 2 and body["skipped"] == 2 and len(body["errors"]) == 2
    assert body["errors"][0].startswith("Row 3")


def test_oversized_csv_is_rejected(client):
    from app.main import MAX_GLOSSARY_BYTES

    data = b"a" * (MAX_GLOSSARY_BYTES + 10)
    r = client.post("/api/glossary/import", files={"file": ("g.csv", data, "text/csv")})
    assert r.status_code == 413


# ---- corrections on a job being deleted ---------------------------------------------------------

def test_correction_on_a_job_being_deleted_is_refused(client, app_env, pdfs):
    from app.worker import JobRunner

    job = upload(client, pdfs["clean"]).json()
    runner = JobRunner(app_env)
    runner.stage_extract(job["id"])
    seg = client.get(f"/api/jobs/{job['id']}/segments").json()[0]
    assert client.delete(f"/api/jobs/{job['id']}").json() == {"status": "cancelling"}
    assert client.patch(f"/api/segments/{seg['id']}", json={"text": "x"}).status_code == 404


# ---- database migration -----------------------------------------------------------------------

OLD_JOBS_TABLE = """
CREATE TABLE jobs (
    id VARCHAR(32) NOT NULL PRIMARY KEY, filename VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
    status VARCHAR(16) NOT NULL, stage VARCHAR(16) NOT NULL, stage_progress FLOAT NOT NULL,
    message TEXT NOT NULL, error TEXT, choice VARCHAR(16) NOT NULL, careful_reread BOOLEAN NOT NULL,
    model_requested VARCHAR(64), model_used VARCHAR(64), draft_model VARCHAR(64),
    page_count INTEGER NOT NULL, pages_done INTEGER NOT NULL, eta_seconds FLOAT,
    draft_ready_at DATETIME, final_ready_at DATETIME, outputs_stale BOOLEAN NOT NULL,
    counts JSON NOT NULL, notes JSON NOT NULL
)
"""


def test_old_database_gets_the_new_columns(app_env):
    from app import db

    db.reset_engine()
    con = sqlite3.connect(app_env.db_path)
    con.execute(OLD_JOBS_TABLE)
    con.execute(
        "INSERT INTO jobs VALUES ('" + "a" * 32 + "', 'old.pdf', '2026-10-01 08:00:00.000000', "
        "'2026-10-01 08:00:00.000000', 'done', 'done', 1.0, 'Final ready', NULL, 'auto', 0, NULL, NULL, "
        "NULL, 1, 1, 0, NULL, NULL, 0, '{}', '[]')"
    )
    con.commit()
    con.close()

    from app.main import app

    with TestClient(app) as client:
        jobs = client.get("/api/jobs").json()
        assert [j["id"] for j in jobs] == ["a" * 32]
        assert jobs[0]["created_at"] == "2026-10-01T08:00:00+00:00"
        assert client.delete(f"/api/jobs/{'a' * 32}").json() == {"status": "deleted"}

    con = sqlite3.connect(app_env.db_path)
    columns = {row[1] for row in con.execute("PRAGMA table_info(jobs)")}
    con.close()
    assert {"cancel_requested", "edit_version", "final_fallback"} <= columns
    assert db.migrate(db.get_engine()) == []  # running it again changes nothing
