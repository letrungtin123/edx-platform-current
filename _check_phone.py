import django; django.setup()
from django.contrib.auth.models import User
u = User.objects.get(username='landassociates')
profile = u.profile
print('phone_number:', getattr(profile, 'phone_number', 'NO_FIELD'))
print('Profile fields:', [f.name for f in profile._meta.fields])
