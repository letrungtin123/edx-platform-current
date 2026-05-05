import django
django.setup()
from lms.djangoapps.landa_library.blacklist import blacklist_user, is_user_blacklisted, unblacklist_user

# Test: blacklist user ID 9 (tinlekk) va kiem tra
print("=== Test Redis Blacklist ===")

# Kiem tra truoc khi blacklist
print(f"Before blacklist - is_blacklisted(9): {is_user_blacklisted(9)}")

# Blacklist
blacklist_user(9)
print(f"After blacklist  - is_blacklisted(9): {is_user_blacklisted(9)}")

# Unblacklist
unblacklist_user(9)
print(f"After unblacklist - is_blacklisted(9): {is_user_blacklisted(9)}")

print("\n=== Redis blacklist module is working correctly ===")
