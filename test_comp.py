import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lms.envs.tutor.production")
django.setup()

from django.contrib.auth.models import User
from opaque_keys.edx.keys import CourseKey
from completion.models import BlockCompletion
from student.models import StudentModule

user = User.objects.get(username="tinlekk")
course_key = CourseKey.from_string("course-v1:LAndA+000000+2022")

print("User:", user.username)
print("Course:", str(course_key))

completions = BlockCompletion.objects.filter(user=user, context_key=course_key)
print("Total BlockCompletion for course:", completions.count())
for c in completions[:5]:
    print(c.block_key, c.completion)

sm = StudentModule.objects.filter(student=user, course_id=course_key)
print("Total StudentModule for course:", sm.count())
for m in sm[:5]:
    print(m.module_state_key, m.state)
