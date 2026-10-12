"""Text extraction through the real worker: what reaches the segments."""

from __future__ import annotations

import shutil

import pymupdf
import pytest
from conftest import LETTER, make_clean_pdf, make_scanned_pdf
from fastapi.testclient import TestClient

from app.pipeline.ocr import tesseract

HAS_OCR = tesseract.available(shutil.which("tesseract"))


@pytest.fixture()
def client(app_env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def run_job(client, app_env, path) -> tuple[dict, list[dict]]:
    from app.worker import JobRunner

    with open(path, "rb") as f:
        r = client.post("/api/jobs", files={"file": (path.name, f, "application/pdf")}, data={"choice": "fast"})
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    JobRunner(app_env).run(job_id)
    return client.get(f"/api/jobs/{job_id}").json(), client.get(f"/api/jobs/{job_id}/segments").json()


def build_mixed_pdf(tmp_path) -> pymupdf.Document:
    """Page 1: a scan with an eOffice footer. Page 2: a Unicode letter with a Kruti Dev letterhead."""
    doc = pymupdf.open(str(make_scanned_pdf(tmp_path / "scan.pdf", LETTER)))
    doc[0].insert_text((40, 830), "Generated from eOffice by RAKESH KUMAR, on 12/03/2026 05:30 PM", fontsize=7)
    doc.insert_pdf(pymupdf.open(str(make_clean_pdf(tmp_path / "clean.pdf", LETTER))))
    page = doc[1]
    page.insert_text((60, 40), "fcgkj ljdkj] lwpuk izkoS/kfdh foHkkx", fontname="tiro", fontsize=14)
    for xref, _ext, _type, base, *_ in page.get_fonts():
        if "times" in base.lower():
            doc.xref_set_key(xref, "BaseFont", "/KrutiDev010")
    return doc


def test_legacy_gibberish_never_reaches_a_segment(client, app_env, tmp_path, monkeypatch):
    # Without OCR the page falls back to its own text: the Kruti Dev part must be left out.
    monkeypatch.setattr(tesseract, "available", lambda cmd: False)
    path = tmp_path / "mixed.pdf"
    build_mixed_pdf(tmp_path).save(str(path))
    job, segs = run_job(client, app_env, path)
    assert job["status"] == "done", job
    assert job["pages"][1]["kind"] == "legacy"
    assert not any("fcgkj" in s["source"] or "ljdkj" in s["source"] for s in segs)
    assert any("ज्ञापांक" in s["source"] for s in segs if s["page_no"] == 2)


@pytest.mark.skipif(not HAS_OCR, reason="tesseract with hin+eng not installed")
def test_scan_with_footer_is_ocred_and_keeps_its_numbers(client, app_env, tmp_path):
    path = tmp_path / "mixed.pdf"
    build_mixed_pdf(tmp_path).save(str(path))
    job, segs = run_job(client, app_env, path)
    assert job["status"] == "done", job
    assert job["pages"][0]["kind"] == "scan" and job["pages"][0]["method"] == "ocr-tesseract"
    assert job["pages"][1]["kind"] == "legacy" and job["pages"][1]["method"] == "ocr-tesseract"
    page1 = " ".join(s["source"] for s in segs if s["page_no"] == 1)
    for number in ("1234/2026", "12.03.2026", "25.03.2026", "5,00,000/-"):
        assert number in page1, (number, page1)
    assert not any("fcgkj" in s["source"] for s in segs)
