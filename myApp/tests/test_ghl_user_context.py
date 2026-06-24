import base64
import hashlib
import json
from django.test import SimpleTestCase
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from myApp.integrations.ghl import user_context


def _evp_bytes_to_key(password: bytes, salt: bytes, key_len=32, iv_len=16):
    d = b""
    prev = b""
    while len(d) < key_len + iv_len:
        prev = hashlib.md5(prev + password + salt).digest()
        d += prev
    return d[:key_len], d[key_len : key_len + iv_len]


def _cryptojs_encrypt(plaintext: str, secret: str) -> str:
    """Mirror CryptoJS AES.encrypt(str, passphrase) -> OpenSSL Salted__ format."""
    salt = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    key, iv = _evp_bytes_to_key(secret.encode(), salt)
    data = plaintext.encode("utf-8")
    pad = 16 - (len(data) % 16)
    data += bytes([pad]) * pad
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = enc.update(data) + enc.finalize()
    return base64.b64encode(b"Salted__" + salt + ct).decode()


class UserContextTests(SimpleTestCase):
    SECRET = "test-shared-secret"

    def test_decrypts_valid_blob(self):
        payload = {"locationId": "LOC123", "email": "a@b.com", "type": "location"}
        blob = _cryptojs_encrypt(json.dumps(payload), self.SECRET)
        ctx = user_context.decrypt(blob, self.SECRET)
        self.assertEqual(ctx.location_id, "LOC123")
        self.assertEqual(ctx.email, "a@b.com")

    def test_invalid_base64_returns_none(self):
        self.assertIsNone(user_context.decrypt("not-base64!!", self.SECRET))

    def test_tampered_ciphertext_returns_none(self):
        blob = _cryptojs_encrypt('{"locationId":"X"}', self.SECRET)
        raw = base64.b64decode(blob)
        # Flip a byte in the ciphertext region (after the 16-byte Salted__+salt header).
        tampered = raw[:17] + bytes([raw[17] ^ 0xFF]) + raw[18:]
        self.assertIsNone(
            user_context.decrypt(base64.b64encode(tampered).decode(), self.SECRET)
        )

    def test_non_dict_json_returns_none(self):
        blob = _cryptojs_encrypt("[1, 2, 3]", self.SECRET)
        self.assertIsNone(user_context.decrypt(blob, self.SECRET))

    def test_wrong_secret_returns_none(self):
        blob = _cryptojs_encrypt('{"locationId":"X"}', self.SECRET)
        self.assertIsNone(user_context.decrypt(blob, "wrong-secret"))
