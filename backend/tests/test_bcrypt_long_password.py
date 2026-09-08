"""
Regression test for the bcrypt/passlib version-pin issue.

`requirements.txt` used to pin `bcrypt>=4.0.0` with no upper bound.
passlib 1.7.4 (the latest release) detects its bcrypt backend version via
`bcrypt.__about__.__version__`, which bcrypt removed starting in 4.1. From
4.1 through 4.3 this only produces a harmless logged warning, but bcrypt
5.0.0 changes its own 72-byte-password handling in a way passlib can no
longer detect, so `hash_password()` / `verify_password()` raise
`ValueError: password cannot be longer than 72 bytes` instead of passlib
transparently truncating as it's supposed to — breaking login for any
password over 72 bytes, and breaking the H2 enumeration-timing dummy hash
(which is deliberately long).

This test doesn't check which bcrypt version is installed (that's an
implementation detail) — it checks the OBSERVABLE BEHAVIOR the pin exists
to protect: hashing/verifying a long password must never raise. If someone
loosens the pin in requirements.txt and CI installs a bcrypt version with
this incompatibility, this test fails immediately regardless of the exact
version resolved.

Run:  cd backend && pytest tests/test_bcrypt_long_password.py -v
"""
from app.core.security import dummy_password_hash, hash_password, verify_password


class TestLongPasswordHandling:
    def test_hashing_a_password_over_72_bytes_does_not_raise(self):
        long_password = "a" * 100  # bcrypt's real limit is 72 bytes
        # Must not raise ValueError("password cannot be longer than 72 bytes").
        hashed = hash_password(long_password)
        assert hashed

    def test_verifying_a_long_password_does_not_raise(self):
        long_password = "x" * 200
        hashed = hash_password(long_password)
        assert verify_password(long_password, hashed) is True

    def test_verifying_wrong_long_password_returns_false_not_raise(self):
        long_password = "y" * 150
        hashed = hash_password(long_password)
        assert verify_password("z" * 150, hashed) is False

    def test_dummy_hash_used_for_enumeration_mitigation_does_not_raise(self):
        """H2's enumeration mitigation deliberately verifies against a fixed
        dummy hash for unknown-user logins — this must never raise either,
        or H2 regresses right alongside this bug."""
        dummy = dummy_password_hash()
        # Should safely return False, never raise.
        assert verify_password("any-attempted-password", dummy) is False

    def test_requirements_txt_pins_bcrypt_below_5(self):
        """Belt-and-suspenders: also guard the actual pin in requirements.txt
        so a future edit can't silently drop the upper bound."""
        import pathlib

        req_path = pathlib.Path(__file__).resolve().parents[1] / "requirements.txt"
        content = req_path.read_text()
        bcrypt_lines = [line for line in content.splitlines() if line.strip().startswith("bcrypt")]
        assert bcrypt_lines, "No bcrypt line found in requirements.txt"
        assert "<5.0.0" in bcrypt_lines[0] or "<5" in bcrypt_lines[0], (
            f"bcrypt pin in requirements.txt no longer caps below 5.0.0: {bcrypt_lines[0]!r}"
        )
