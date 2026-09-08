"""
Regression test for the device allow-list matching bug (Medium):

`upload_alerts` used to reduce every allow-list entry AND every incoming
matched_term down to just its first DNS label (`.split(".")[0]`) and
compare labels. This both:

- over-suppresses: an allow-list entry "chat.example.com" reduces to
  "chat", which then ALSO matches a completely unrelated domain like
  "chat.some-other-site.com" (same first label, different domain).
- under-suppresses: allow-listing "google.com" (label "google") should
  cover "mail.google.com" too, but that reduces to label "mail" != "google",
  so it's NOT suppressed even though it's clearly a subdomain of the
  allowed domain.

Fixed with a proper "is this the domain, or a subdomain of it" suffix
check instead of first-label comparison.

Run:  cd backend && pytest tests/test_device_allowlist_matching.py -v
"""
import inspect

from app.api.v1.devices import devices as devices_mod


def _is_allowed(matched_term: str, allowed_domains: list[str]) -> bool:
    """Extracted copy of the fixed matching logic, for direct unit testing
    (the real function is a closure inside upload_alerts)."""
    candidate = matched_term.lower().strip(".")
    return any(candidate == allow or candidate.endswith("." + allow) for allow in [a.lower().strip(".") for a in allowed_domains])


class TestAllowlistDomainMatching:
    def test_exact_match_is_allowed(self):
        assert _is_allowed("whatsapp.com", ["whatsapp.com"]) is True

    def test_subdomain_of_allowed_domain_is_allowed(self):
        """THE under-suppression assertion: allow-listing google.com must
        cover mail.google.com too."""
        assert _is_allowed("mail.google.com", ["google.com"]) is True

    def test_unrelated_domain_sharing_first_label_is_not_allowed(self):
        """THE over-suppression assertion: allow-listing chat.example.com
        must NOT accidentally cover chat.some-other-site.com just because
        both happen to start with 'chat'."""
        assert _is_allowed("chat.some-other-site.com", ["chat.example.com"]) is False

    def test_similar_looking_domain_is_not_allowed(self):
        """'googleimposter.com' must not match an allow-list entry for
        'google.com' just because it starts with a similar string."""
        assert _is_allowed("googleimposter.com", ["google.com"]) is False

    def test_case_insensitive(self):
        assert _is_allowed("WhatsApp.COM", ["whatsapp.com"]) is True

    def test_trailing_dot_normalized(self):
        assert _is_allowed("whatsapp.com.", ["whatsapp.com"]) is True

    def test_no_allowlist_entries_means_nothing_is_allowed(self):
        assert _is_allowed("whatsapp.com", []) is False

    def test_unrelated_domain_with_no_relationship_is_not_allowed(self):
        assert _is_allowed("facebook.com", ["whatsapp.com"]) is False


class TestUploadAlertsSourceUsesProperDomainMatching:
    def test_source_no_longer_splits_to_first_label_only(self):
        source = inspect.getsource(devices_mod.upload_alerts)
        # Look for the actual buggy code pattern (a live expression), not
        # mere mentions of it in a comment explaining the historical fix.
        code_lines = [
            line for line in source.splitlines()
            if not line.strip().startswith("#") and '.split(".")[0]' in line
        ]
        assert not code_lines, (
            f"upload_alerts still executes first-DNS-label splitting in live code: {code_lines!r} — "
            "this is exactly the over/under-suppression bug (still present)."
        )

    def test_source_uses_a_suffix_style_subdomain_check(self):
        source = inspect.getsource(devices_mod.upload_alerts)
        assert 'endswith("." ' in source or 'endswith("."' in source, (
            "upload_alerts doesn't appear to use a proper subdomain "
            "(suffix) check for allow-list matching."
        )
