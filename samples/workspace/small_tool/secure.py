import hashlib


def token(secret):
    """بصمة سر — خوارزمية قديمة عمدًا."""
    return hashlib.md5(secret).hexdigest()
