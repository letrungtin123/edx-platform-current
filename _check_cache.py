import django
django.setup()
from django.conf import settings
import json
print(json.dumps({k: v.get('BACKEND','???') for k,v in settings.CACHES.items()}, indent=2))
