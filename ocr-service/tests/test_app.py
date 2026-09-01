import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import app as ocr_app  # noqa: E402


@pytest.fixture
def client():
    ocr_app.app.config["TESTING"] = True
    with ocr_app.app.test_client() as c:
        yield c


def test_missing_file_returns_400(client):
    resp = client.post("/ocr", data={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_empty_filename_returns_400(client):
    data = {"file": (io.BytesIO(b""), "")}
    resp = client.post("/ocr", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_pdf_joins_text_from_all_pages(client):
    fake_pages = [object(), object()]
    with patch.object(ocr_app, "convert_from_bytes", return_value=fake_pages) as mock_convert, \
         patch.object(ocr_app.pytesseract, "image_to_string", side_effect=["page one", "page two"]) as mock_ocr:
        data = {"file": (io.BytesIO(b"%PDF-1.4 fake"), "decision.pdf")}
        resp = client.post("/ocr", data=data, content_type="multipart/form-data")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["text"] == "page one\npage two"
    assert mock_convert.called
    assert mock_ocr.call_count == 2


def test_image_runs_single_ocr_pass(client):
    with patch.object(ocr_app, "Image") as mock_image_cls, \
         patch.object(ocr_app.pytesseract, "image_to_string", return_value="scanned text") as mock_ocr:
        mock_image_cls.open.return_value = object()
        data = {"file": (io.BytesIO(b"\x89PNG fake"), "scan.png")}
        resp = client.post("/ocr", data=data, content_type="multipart/form-data")

    assert resp.status_code == 200
    assert resp.get_json()["text"] == "scanned text"
    mock_ocr.assert_called_once()


def test_ocr_exception_returns_500(client):
    with patch.object(ocr_app, "convert_from_bytes", side_effect=RuntimeError("poppler missing")):
        data = {"file": (io.BytesIO(b"%PDF-1.4 fake"), "decision.pdf")}
        resp = client.post("/ocr", data=data, content_type="multipart/form-data")

    assert resp.status_code == 500
    assert "poppler missing" in resp.get_json()["error"]
