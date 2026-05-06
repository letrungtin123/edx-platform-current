from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

for c in CourseOverview.objects.all()[:5]:
    print(f'Course {c.id}: {c.course_image_url}')
