"""Khoá bản quyền theo HWID và xác thực chữ ký RSA.

Client chỉ có PUBLIC key nên không thể tự phát hành license; private key nằm ở
phía nhà phát hành. License có dạng ``<payload_b64>.<signature_b64>`` với payload
là JSON gồm hwid, hạn dùng và tên khách hàng.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import subprocess
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .utils import module_available

# Public key của nhà phát hành. Thay bằng key thật khi build bản thương mại;
# để trống thì mọi license đều bị coi là không hợp lệ (trừ chế độ dev bên dưới).
PUBLIC_KEY_PEM = os.environ.get("SUBAI_PUBLIC_KEY", "").encode("utf-8")

# Chế độ dev: bỏ qua kiểm tra license khi chạy mã nguồn, dùng cho phát triển.
DEV_MODE = os.environ.get("SUBAI_DEV_MODE", "1") == "1"


@dataclass
class LicenseInfo:
    valid: bool
    reason: str = ""
    customer: str = ""
    hwid: str = ""
    expires: Optional[date] = None

    @property
    def status_text(self) -> str:
        if not self.valid:
            return f"Không hợp lệ - {self.reason}"
        if self.expires:
            return f"Hợp lệ tới {self.expires.isoformat()} ({self.customer})"
        return f"Hợp lệ vĩnh viễn ({self.customer})"


def get_hwid() -> str:
    """Định danh phần cứng ổn định, cùng máy luôn ra cùng chuỗi."""
    parts = [platform.machine(), platform.system()]

    if platform.system() == "Windows":
        parts.append(_windows_serial())
    elif platform.system() == "Darwin":
        parts.append(_macos_serial())
    else:
        machine_id = Path("/etc/machine-id")
        dbus_id = Path("/var/lib/dbus/machine-id")
        for candidate in (machine_id, dbus_id):
            try:
                parts.append(candidate.read_text(encoding="utf-8").strip())
                break
            except OSError:
                continue

    if len(parts) < 3:  # không lấy được serial -> rơi về MAC address
        parts.append(f"{uuid.getnode():012x}")

    digest = hashlib.sha256("|".join(p for p in parts if p).encode("utf-8")).hexdigest()
    return "-".join(digest[i:i + 8] for i in range(0, 32, 8)).upper()


def _windows_serial() -> str:
    if module_available("wmi"):
        try:
            import wmi  # noqa: PLC0415

            client = wmi.WMI()
            board = client.Win32_BaseBoard()[0].SerialNumber
            cpu = client.Win32_Processor()[0].ProcessorId
            return f"{board}{cpu}"
        except Exception:
            pass
    try:
        out = subprocess.run(
            ["wmic", "csproduct", "get", "uuid"], capture_output=True, text=True, timeout=10
        ).stdout
        return out.split("\n")[1].strip() if "\n" in out else ""
    except Exception:
        return ""


def _macos_serial() -> str:
    try:
        out = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2]
    except Exception:
        pass
    return ""


def verify_license(key: str, hwid: Optional[str] = None, today: Optional[date] = None) -> LicenseInfo:
    """Kiểm tra license key với public key đã nhúng."""
    hwid = hwid or get_hwid()
    today = today or datetime.now().date()
    key = (key or "").strip()

    if not key:
        if DEV_MODE:
            return LicenseInfo(True, customer="Developer Mode", hwid=hwid)
        return LicenseInfo(False, reason="Chưa nhập license key.", hwid=hwid)

    try:
        payload_b64, signature_b64 = key.split(".", 1)
        payload_raw = base64.urlsafe_b64decode(_pad(payload_b64))
        signature = base64.urlsafe_b64decode(_pad(signature_b64))
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        return LicenseInfo(False, reason="Định dạng license key sai.", hwid=hwid)

    if not _verify_signature(payload_raw, signature):
        return LicenseInfo(False, reason="Chữ ký không khớp (key giả hoặc đã bị sửa).", hwid=hwid)

    licensed_hwid = str(payload.get("hwid", ""))
    if licensed_hwid not in ("*", hwid):
        return LicenseInfo(False, reason="License cấp cho máy khác.", hwid=hwid)

    expires: Optional[date] = None
    if payload.get("expires"):
        try:
            expires = date.fromisoformat(str(payload["expires"]))
        except ValueError:
            return LicenseInfo(False, reason="Ngày hết hạn trong license không hợp lệ.", hwid=hwid)
        if expires < today:
            return LicenseInfo(False, reason=f"License hết hạn ngày {expires}.", hwid=hwid)

    return LicenseInfo(
        valid=True,
        customer=str(payload.get("customer", "Khách hàng")),
        hwid=hwid,
        expires=expires,
    )


def _pad(value: str) -> str:
    return value + "=" * (-len(value) % 4)


def _verify_signature(payload: bytes, signature: bytes) -> bool:
    if not PUBLIC_KEY_PEM:
        return False
    try:
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import padding  # noqa: PLC0415

        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
        public_key.verify(
            signature,
            payload,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False


def issue_license(private_key_pem: bytes, hwid: str, customer: str, expires: str = "") -> str:
    """Phát hành license (chạy ở phía nhà phát hành, cần private key)."""
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import padding  # noqa: PLC0415

    payload = json.dumps(
        {"hwid": hwid, "customer": customer, "expires": expires},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")

    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    signature = private_key.sign(
        payload,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")  # noqa: E731
    return f"{encode(payload)}.{encode(signature)}"
