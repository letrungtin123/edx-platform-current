#!/bin/bash
cd /openedx/edx-platform
echo "=== SHOWMIGRATIONS ==="
python manage.py lms showmigrations landa_library 2>&1
echo "=== TRY MIGRATE ==="
python manage.py lms migrate landa_library 2>&1
echo "=== DONE ==="
