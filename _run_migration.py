import django; django.setup()
from django.core.management import call_command
import sys, io

# Show migrations
out = io.StringIO()
call_command('showmigrations', 'landa_library', stdout=out, stderr=out)
print("=== SHOWMIGRATIONS ===")
print(out.getvalue())

# Run migrate
out2 = io.StringIO()
call_command('migrate', 'landa_library', stdout=out2, stderr=out2, verbosity=2)
print("=== MIGRATE ===")
print(out2.getvalue())
print("=== DONE ===")
