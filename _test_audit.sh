#!/bin/bash
# Test: create category → check audit log
curl -s -X POST -H "Authorization: Bearer vlnrlweDoyMYFwIRGF9uxv1lFsLNJC" -H "Content-Type: application/json" -d '{"name":"Test Audit"}' "http://local.openedx.io/api/landa/admin/categories/"
echo ""
echo "=== AUDIT LOGS ==="
curl -s -H "Authorization: Bearer vlnrlweDoyMYFwIRGF9uxv1lFsLNJC" "http://local.openedx.io/api/landa/admin/audit-logs/" | python3 -m json.tool
