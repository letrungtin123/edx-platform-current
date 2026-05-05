#!/bin/bash
curl -s -H "Authorization: Bearer vlnrlweDoyMYFwIRGF9uxv1lFsLNJC" \
  "http://local.openedx.io/api/courses/v1/courses/course-v1:LAndA2+000002+2026/mentors/" \
  | python3 -m json.tool
