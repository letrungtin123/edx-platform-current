import os
import django

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lms.envs.devstack")
django.setup()

from openedx.core.djangoapps.notifications.models import Notification
from common.djangoapps.student.models import CourseEnrollment

print("--- Notifications ---")
nots = Notification.objects.order_by('-created')[:10]
print(f"Total Notifications: {Notification.objects.count()}")
for n in nots:
    print(f"[{n.id}] User:{n.user_id} Course:{n.course_id} App:{n.app_name} Type:{n.notification_type} Web:{n.web} Context:{n.content_context}")

print("\n--- Enrollments cho course-v1:LAndA+000000+2022 ---")
enrolls = CourseEnrollment.objects.filter(course_id='course-v1:LAndA+000000+2022', is_active=True)
print(f"Total Active Enrollments: {enrolls.count()}")
for e in enrolls:
    print(f"User:{e.user_id} is_active:{e.is_active}")
