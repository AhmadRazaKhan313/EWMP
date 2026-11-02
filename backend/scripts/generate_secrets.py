"""Prints fresh random secrets for .env.production. Nothing is written to disk.

    python scripts/generate_secrets.py

Paste the values into your production .env (never commit that file).
"""
import secrets


def token(n: int = 48) -> str:
    return secrets.token_urlsafe(n)


if __name__ == "__main__":
    print(f"SECRET_KEY={token()}")
    print(f"AGENT_SECRET_KEY={token()}")
    print(f"ENCRYPTION_KEY={token(32)}")
    print(f"SUPER_ADMIN_PASSWORD={token(18)}")
    print(f"POSTGRES_PASSWORD={token(24)}")
