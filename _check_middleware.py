import django
django.setup()
from django.conf import settings
for i, m in enumerate(settings.MIDDLEWARE):
    if 'landa' in m.lower() or 'blacklist' in m.lower() or 'standing' in m.lower():
        print(f"  [{i}] {m}")
print(f"\nTotal middleware: {len(settings.MIDDLEWARE)}")
