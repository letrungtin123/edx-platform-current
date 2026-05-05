
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lms.envs.production")
django.setup()

from django.contrib.auth import get_user_model
from opaque_keys.edx.keys import CourseKey
from lms.djangoapps.course_blocks.api import get_course_blocks
from openedx.core.djangoapps.content.block_structure.transformers import BlockStructureTransformers
from lms.djangoapps.course_api.blocks.transformers.block_completion import BlockCompletionTransformer

User = get_user_model()
user = User.objects.get(username='landassociates')
course_key = CourseKey.from_string('course-v1:edX+DemoX+Demo_Course')

# Get blocks with completion
blocks = get_course_blocks(user, course_key, include_completion=True)
root_block = blocks.get_xblock_field(course_key, 'completion')
print(f"Completion for {course_key}: {root_block}")

# Also check how to get it from transformer field
completion = BlockCompletionTransformer.get_block_completion(blocks, course_key)
print(f"Transformer completion: {completion}")
