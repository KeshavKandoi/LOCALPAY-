from app.services.webhooks import sign_payload, verify_signature


def test_hmac_sha256_matches_known_test_vector() -> None:
    secret = b"\x0b" * 20
    payload = b"Hi There"
    expected = "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
    assert sign_payload(payload, secret) == expected
    assert verify_signature(payload, secret, expected)
    assert not verify_signature(payload, secret, "é" * 64)
