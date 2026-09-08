"""
Regression tests for the document upload MIME validation bug (Medium):

`upload_document` validated the CLIENT-SUPPLIED `mime_type` parameter
(sourced from the HTTP `Content-Type` header on the multipart upload,
which any browser/script fully controls) against an allowlist — but never
checked what the file's bytes actually were. An attacker could label an
HTML/JS file (or any malicious content) "application/pdf" and it would
sail straight through the allowlist check, later served back with that
same fake-but-trusted type via `download_document`.

Fixed by sniffing the file's real type from its own bytes
(`_sniff_mime_type`, using magic-byte detection) and validating/storing
THAT instead of the client's claim.

Run:  cd backend && pytest tests/test_document_mime_sniffing.py -v
"""
import io
import zipfile

from app.services.documents import ALLOWED_MIME_TYPES, _sniff_mime_type

# ── Real file fixtures (built in-memory, not touching disk) ────────────────
REAL_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
REAL_PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 32
REAL_JPEG = bytes.fromhex("ffd8ffe0") + b"\x00" * 32
REAL_OLE2_DOC = bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 64
MALICIOUS_HTML = b"<html><body><script>alert(document.cookie)</script></body></html>"
MALICIOUS_SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
PLAIN_TEXT = b"just some plain text, nothing special"


def _build_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        zf.writestr("word/document.xml", "<document/>")
    return buf.getvalue()


def _build_plain_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "hi")
    return buf.getvalue()


class TestSniffMimeType:
    def test_real_pdf_is_detected(self):
        assert _sniff_mime_type(REAL_PDF) == "application/pdf"

    def test_real_png_is_detected(self):
        assert _sniff_mime_type(REAL_PNG) == "image/png"

    def test_real_jpeg_is_detected(self):
        assert _sniff_mime_type(REAL_JPEG) == "image/jpeg"

    def test_real_docx_is_detected(self):
        assert _sniff_mime_type(_build_docx()) == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    def test_legacy_ole2_doc_is_detected(self):
        assert _sniff_mime_type(REAL_OLE2_DOC) == "application/msword"

    def test_malicious_html_is_not_identified_as_any_document_type(self):
        """THE core assertion: HTML masquerading as a document must sniff
        to None (unrecognized), not be waved through."""
        assert _sniff_mime_type(MALICIOUS_HTML) is None

    def test_malicious_svg_is_not_identified_as_any_document_type(self):
        assert _sniff_mime_type(MALICIOUS_SVG) is None

    def test_plain_text_is_not_identified_as_any_document_type(self):
        assert _sniff_mime_type(PLAIN_TEXT) is None

    def test_generic_zip_without_office_structure_is_not_docx(self):
        """A zip file is not automatically treated as a Word document just
        because docx happens to be zip-based."""
        sniffed = _sniff_mime_type(_build_plain_zip())
        assert sniffed != "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def test_empty_content_is_not_identified(self):
        assert _sniff_mime_type(b"") is None


class TestSpoofingIsBlocked:
    """The actual attack scenario: claim a benign Content-Type, upload
    something else entirely."""

    def test_html_claiming_to_be_pdf_does_not_sniff_as_pdf(self):
        # This is what the OLD code trusted: the client's declared header.
        declared_but_fake = "application/pdf"
        actual_sniffed = _sniff_mime_type(MALICIOUS_HTML)
        assert actual_sniffed != declared_but_fake
        assert actual_sniffed not in ALLOWED_MIME_TYPES or actual_sniffed is None

    def test_svg_claiming_to_be_png_does_not_sniff_as_png(self):
        declared_but_fake = "image/png"
        actual_sniffed = _sniff_mime_type(MALICIOUS_SVG)
        assert actual_sniffed != declared_but_fake

    def test_unrecognized_content_would_be_rejected_by_the_allowlist_gate(self):
        """Simulates the actual gate in upload_document: None or anything
        outside ALLOWED_MIME_TYPES must fail the check."""
        for payload in (MALICIOUS_HTML, MALICIOUS_SVG, PLAIN_TEXT, b"\x00\x01\x02garbage"):
            sniffed = _sniff_mime_type(payload)
            passes_gate = sniffed is not None and sniffed in ALLOWED_MIME_TYPES
            assert not passes_gate, f"Payload {payload[:30]!r} incorrectly passed the MIME allowlist gate"

    def test_all_genuinely_allowed_types_pass_the_gate(self):
        """Regression safety: legitimate files must still work."""
        for payload in (REAL_PDF, REAL_PNG, REAL_JPEG, REAL_OLE2_DOC, _build_docx()):
            sniffed = _sniff_mime_type(payload)
            assert sniffed is not None and sniffed in ALLOWED_MIME_TYPES, (
                f"Legitimate payload was rejected: sniffed as {sniffed!r}"
            )
