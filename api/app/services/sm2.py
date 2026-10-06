"""SM2 public-key decryption, enough to read what JLCPCB's web API encrypts.

JLCPCB returns a buyer's street, building number and e-mail as
`{secret}04<hex>`: SM2 (GB/T 32918) on the recommended 256-bit curve, cipher
mode 1 (C1 || C3 || C2), the same `sm-crypto` scheme its web page decrypts in
the browser. The key pair comes from `secret/update`, the call that mints the
session's `secretkey` (`jlc_web.WebClient`), so the platform holds the private
key for exactly the responses it fetched.

Pure Python on purpose: SM3 is in `hashlib` (OpenSSL), and the curve
arithmetic is a few lines, so no new dependency enters the image. Only what
reading needs is here, plus `encrypt` so the tests can round-trip.
"""
from __future__ import annotations

import hashlib
import secrets

P = 0xFFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000FFFFFFFFFFFFFFFF
A = 0xFFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000FFFFFFFFFFFFFFFC
B = 0x28E9FA9E9D9F5E344D5A9E4BCF6509A7F39789F515AB8F92DDBCBD414D940E93
N = 0xFFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFF7203DF6B21C6052B53BBF40939D54123
G = (0x32C4AE2C1F1981195F9904466A39C9948FE30BBFF2660BE1715A4589334C74C7,
     0xBC3736A2F4F6779C59BDCEE36B692153D0A9877CC62A474002DF32E52139F0A0)


class SM2Error(ValueError):
    pass


def _sm3(data: bytes) -> bytes:
    return hashlib.new("sm3", data).digest()


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    return x3, (lam * (x1 - x3) - y1) % P


def _mul(k: int, point):
    out = None
    while k:
        if k & 1:
            out = _add(out, point)
        point = _add(point, point)
        k >>= 1
    return out


def _kdf(z: bytes, klen: int) -> bytes:
    out, counter = b"", 1
    while len(out) < klen:
        out += _sm3(z + counter.to_bytes(4, "big"))
        counter += 1
    return out[:klen]


def _on_curve(x: int, y: int) -> bool:
    return (y * y - (x * x * x + A * x + B)) % P == 0


def decrypt(cipher_hex: str, private_hex: str) -> bytes:
    """C1 || C3 || C2, hex, with or without the leading `04` of C1."""
    h = cipher_hex.strip().lower()
    if h.startswith("04") and (len(h) - 2) % 2 == 0 and len(h) > 2 + 128 + 64:
        h = h[2:]
    if len(h) <= 128 + 64:
        raise SM2Error("ciphertext too short")
    x1, y1 = int(h[:64], 16), int(h[64:128], 16)
    if not _on_curve(x1, y1):
        raise SM2Error("C1 is not on the curve")
    c3, c2 = bytes.fromhex(h[128:192]), bytes.fromhex(h[192:])
    x2, y2 = _mul(int(private_hex, 16), (x1, y1))
    bx, by = x2.to_bytes(32, "big"), y2.to_bytes(32, "big")
    t = _kdf(bx + by, len(c2))
    if not any(t):
        raise SM2Error("key derivation gave zeros")
    m = bytes(a ^ b for a, b in zip(c2, t))
    if _sm3(bx + m + by) != c3:
        raise SM2Error("C3 does not match: wrong key, or not this cipher mode")
    return m


def encrypt(message: bytes, public_hex: str) -> str:
    """For the tests: `04` || C1 || C3 || C2 in hex, as JLCPCB sends it."""
    h = public_hex.removeprefix("04")
    pub = (int(h[:64], 16), int(h[64:128], 16))
    while True:
        k = secrets.randbelow(N - 1) + 1
        x1, y1 = _mul(k, G)
        x2, y2 = _mul(k, pub)
        bx, by = x2.to_bytes(32, "big"), y2.to_bytes(32, "big")
        t = _kdf(bx + by, len(message))
        if any(t):
            break
    c2 = bytes(a ^ b for a, b in zip(message, t))
    c3 = _sm3(bx + message + by)
    return "04" + f"{x1:064x}{y1:064x}" + c3.hex() + c2.hex()


def keypair() -> tuple[str, str]:
    """(private_hex, public_hex) — for the tests."""
    d = secrets.randbelow(N - 1) + 1
    x, y = _mul(d, G)
    return f"{d:064x}", "04" + f"{x:064x}{y:064x}"
