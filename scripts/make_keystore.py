"""生成固定的 APK 签名密钥（PKCS12）。

跑一次，把输出的 base64 存进 GitHub Secrets，以后每次 CI 都用它签。
签名固定之后，新版本可以覆盖安装，数据不用卸载重装。

python scripts/make_keystore.py
"""

import base64
import datetime
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

ALIAS = "ta"
PASSWORD = "ta-signing-2026"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "signing", "ta.p12")


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "ta"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ta"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=10000))
        .sign(key, hashes.SHA256())
    )

    data = pkcs12.serialize_key_and_certificates(
        ALIAS.encode(),
        key,
        cert,
        None,
        serialization.BestAvailableEncryption(PASSWORD.encode()),
    )
    with open(OUT, "wb") as f:
        f.write(data)

    b64 = base64.b64encode(data).decode()
    print("keystore:", OUT)
    print("alias:", ALIAS)
    print("password:", PASSWORD)
    print("bytes:", len(data))
    print("base64:", len(b64))
    with open(os.path.join(os.path.dirname(OUT), "ta.p12.b64"), "w") as f:
        f.write(b64)


if __name__ == "__main__":
    main()
