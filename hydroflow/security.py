import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta

ITERATIONS = 600_000


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def future(hours=12):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")


def hash_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("Пароль должен содержать от 12 до 128 символов")
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${key}"


def verify_password(password, encoded):
    try:
        algorithm, count, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not isinstance(password, str) or len(password) > 128:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(count)).hex()
        return hmac.compare_digest(expected, actual)
    except (ValueError, AttributeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()
