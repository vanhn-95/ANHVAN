"""Test HWID và xác thực license."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src import security_guard


@pytest.fixture
def rsa_keys():
    crypto = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    assert crypto  # dùng để bỏ qua test khi thiếu thư viện
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest.fixture
def signed_env(monkeypatch, rsa_keys):
    private_pem, public_pem = rsa_keys
    monkeypatch.setattr(security_guard, "PUBLIC_KEY_PEM", public_pem)
    monkeypatch.setattr(security_guard, "DEV_MODE", False)
    return private_pem


class TestHwid:
    def test_stable_between_calls(self):
        assert security_guard.get_hwid() == security_guard.get_hwid()

    def test_format(self):
        hwid = security_guard.get_hwid()
        parts = hwid.split("-")
        assert len(parts) == 4
        assert all(len(p) == 8 for p in parts)
        assert hwid == hwid.upper()


class TestLicense:
    def test_valid_license_accepted(self, signed_env):
        key = security_guard.issue_license(signed_env, "HW-1", "Khách A")
        info = security_guard.verify_license(key, hwid="HW-1")
        assert info.valid
        assert info.customer == "Khách A"

    def test_license_bound_to_other_machine_rejected(self, signed_env):
        key = security_guard.issue_license(signed_env, "HW-1", "Khách A")
        info = security_guard.verify_license(key, hwid="HW-2")
        assert not info.valid
        assert "máy khác" in info.reason

    def test_wildcard_hwid_accepted_anywhere(self, signed_env):
        key = security_guard.issue_license(signed_env, "*", "Site license")
        assert security_guard.verify_license(key, hwid="BAT-KY").valid

    def test_expired_license_rejected(self, signed_env):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        key = security_guard.issue_license(signed_env, "HW-1", "A", expires=yesterday)
        info = security_guard.verify_license(key, hwid="HW-1")
        assert not info.valid
        assert "hết hạn" in info.reason

    def test_future_expiry_accepted(self, signed_env):
        future = (date.today() + timedelta(days=30)).isoformat()
        key = security_guard.issue_license(signed_env, "HW-1", "A", expires=future)
        info = security_guard.verify_license(key, hwid="HW-1")
        assert info.valid
        assert info.expires == date.fromisoformat(future)

    def test_tampered_payload_rejected(self, signed_env):
        import base64
        import json

        key = security_guard.issue_license(signed_env, "HW-1", "A")
        _, signature = key.split(".")
        forged = json.dumps(
            {"customer": "Hacker", "expires": "", "hwid": "HW-2"},
            separators=(",", ":"), sort_keys=True,
        ).encode()
        forged_b64 = base64.urlsafe_b64encode(forged).decode().rstrip("=")
        info = security_guard.verify_license(f"{forged_b64}.{signature}", hwid="HW-2")
        assert not info.valid
        assert "Chữ ký" in info.reason

    def test_garbage_key_rejected(self, signed_env):
        info = security_guard.verify_license("khong-phai-license", hwid="HW-1")
        assert not info.valid

    def test_empty_key_rejected_when_dev_mode_off(self, signed_env):
        info = security_guard.verify_license("", hwid="HW-1")
        assert not info.valid
        assert "Chưa nhập" in info.reason

    def test_dev_mode_allows_empty_key(self, monkeypatch):
        monkeypatch.setattr(security_guard, "DEV_MODE", True)
        assert security_guard.verify_license("", hwid="HW-1").valid
