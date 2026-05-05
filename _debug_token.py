import django
django.setup()
from django.db import connection
from django.utils import timezone

# Token from FE-5173 (full 30 chars from DB)
token = "iXvaCJAmiOYphiDNlPv4mWH2Xj1UuB"

print(f"Token to search: {token}")
print(f"Token length: {len(token)}")
print(f"Now: {timezone.now()}")

with connection.cursor() as cursor:
    cursor.execute(
        "SELECT user_id, expires FROM oauth2_provider_accesstoken WHERE token = %s LIMIT 1",
        [token]
    )
    row = cursor.fetchone()
    print(f"DB result: {row}")

    # Also check with LIKE
    cursor.execute(
        "SELECT user_id, expires, token FROM oauth2_provider_accesstoken WHERE token LIKE %s LIMIT 5",
        [token[:20] + '%']
    )
    rows = cursor.fetchall()
    print(f"LIKE results: {rows}")

    # Check if token column is hashed
    cursor.execute(
        "DESCRIBE oauth2_provider_accesstoken"
    )
    for col in cursor.fetchall():
        if 'token' in col[0].lower() or 'hash' in col[0].lower():
            print(f"Column: {col}")
