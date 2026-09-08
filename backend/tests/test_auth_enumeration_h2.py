"""
Regression tests for the login user-enumeration fix (bug H2).

The "user does not exist" login path ran a dummy bcrypt verify to equalise
response timing — but the dummy hash was malformed
(`$2b$12$dummyhashfortimingattackprevention000000000000`, whose 46-char tail
is not a valid 53-char bcrypt payload). passlib rejects a malformed hash almost
instantly instead of doing real bcrypt work, so the not-found path was much
faster than a genuine wrong-password check — a timing oracle for enumerating
which emails are registered.

The fix (`security.dummy_password_hash`) returns a cached, VALID bcrypt hash so
`verify_password` performs the same work on both paths.

Run:  cd backend && pytest tests/test_auth_enumeration_h2.py -v
"""

from app.core.security import dummy_password_hash, verify_password


def test_dummy_hash_is_a_valid_bcrypt_hash():
    h = dummy_password_hash()
    assert h.startswith(("$2a$", "$2b$", "$2y$"))
    # payload after "$2<ver>$<cost>$" must be a full 53-char bcrypt block
    assert len(h.split("$")[-1]) == 53


def test_verify_against_dummy_returns_false_without_raising():
    """THE H2 assertion: a real bcrypt verify runs and returns False rather
    than short-circuiting on a malformed hash (which leaked timing)."""
    assert verify_password("any-attacker-password", dummy_password_hash()) is False


def test_dummy_hash_is_cached():
    # Memoised so it costs exactly one bcrypt hash per process.
    assert dummy_password_hash() is dummy_password_hash()