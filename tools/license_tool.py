#!/usr/bin/env python3
"""Công cụ phía nhà phát hành: tạo cặp khoá RSA và phát hành license.

    python tools/license_tool.py keygen --out keys/
    python tools/license_tool.py issue --key keys/private.pem \\
        --hwid CEE741E5-... --customer "Anh Văn" --expires 2027-01-01

Public key in ra ở bước keygen cần được nhúng vào bản build client qua biến môi
trường SUBAI_PUBLIC_KEY (hoặc gán thẳng vào src/security_guard.PUBLIC_KEY_PEM).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.security_guard import issue_license  # noqa: E402


def cmd_keygen(args: argparse.Namespace) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    private = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    (out / "private.pem").write_bytes(private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    (out / "public.pem").write_bytes(private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    print(f"Đã tạo khoá tại {out}/ - GIỮ KÍN private.pem, không commit lên git.")
    return 0


def cmd_issue(args: argparse.Namespace) -> int:
    private_pem = Path(args.key).read_bytes()
    key = issue_license(private_pem, args.hwid, args.customer, args.expires)
    print(key)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SubAI license tool")
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="Tạo cặp khoá RSA 4096")
    keygen.add_argument("--out", default="keys", help="Thư mục lưu khoá")
    keygen.set_defaults(func=cmd_keygen)

    issue = sub.add_parser("issue", help="Phát hành license cho một máy")
    issue.add_argument("--key", required=True, help="Đường dẫn private.pem")
    issue.add_argument("--hwid", required=True, help='HWID của khách, "*" = mọi máy')
    issue.add_argument("--customer", required=True, help="Tên khách hàng")
    issue.add_argument("--expires", default="", help="Ngày hết hạn YYYY-MM-DD (trống = vĩnh viễn)")
    issue.set_defaults(func=cmd_issue)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
