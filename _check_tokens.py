import django
django.setup()
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute(
        "SELECT id, token, user_id, expires FROM oauth2_provider_accesstoken ORDER BY id DESC LIMIT 3"
    )
    for row in cursor.fetchall():
        tid, token, uid, exp = row
        print(f"id={tid} user_id={uid} expires={exp} token_prefix={token[:30]}... len={len(token)}")
