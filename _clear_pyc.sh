#!/bin/bash
find /openedx/edx-platform/lms/djangoapps/landa_library/__pycache__ -name "*.pyc" -delete
echo "CLEARED pyc cache"
