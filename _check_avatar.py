import django; django.setup()
from django.contrib.auth.models import User
u = User.objects.get(username='mentor1')
print(f'profile_image_uploaded_at: {u.profile.profile_image_uploaded_at}')

from openedx.core.djangoapps.profile_images.images import get_profile_image_urls_for_user
img_data = get_profile_image_urls_for_user(u)
for k, v in img_data.items():
    print(f'{k}: {v}')
