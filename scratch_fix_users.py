import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lms.envs.production")
import django
django.setup()

from django.contrib.auth.models import User
from common.djangoapps.student.models import UserProfile

print('Fixing emails...')
users_without_email = User.objects.filter(email='')
for u in users_without_email:
    u.email = f'user_{u.id}@la.local'
    u.save()
    print(f'Fixed email for {u.username}')

print('Fixing profiles...')
users_without_profile = User.objects.exclude(id__in=UserProfile.objects.values_list('user_id', flat=True))
for u in users_without_profile:
    UserProfile.objects.create(user=u, name=u.username)
    print(f'Created profile for {u.username}')
