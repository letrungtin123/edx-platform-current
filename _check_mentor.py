import django; django.setup()
from django.contrib.auth.models import User
u = User.objects.get(username='mentor1')
profile = u.profile
print(f'name: {profile.name}')
print(f'phone_number: {profile.phone_number}')
print(f'bio: {profile.bio}')
print(f'profile_image_uploaded_at: {profile.profile_image_uploaded_at}')
