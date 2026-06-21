from app.models.inbound import fingerprint_match_keys


def test_hysteria2_alias_preserves_address() -> None:
    original = "hysteria2|node1.example.com|hysteria||443|tls|"
    keys = fingerprint_match_keys(original)
    assert "hysteria|node1.example.com|hysteria||443|tls|" in keys