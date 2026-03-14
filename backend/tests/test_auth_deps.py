import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth_dependencies import create_jwt, decode_jwt


def test_create_and_decode_jwt():
    token = create_jwt(signer_id=42, display_name="Alice")
    payload = decode_jwt(token)
    assert payload["sub"] == 42
    assert payload["name"] == "Alice"
    assert "exp" in payload
    assert "iat" in payload


def test_decode_invalid_jwt():
    payload = decode_jwt("invalid.token.here")
    assert payload is None
