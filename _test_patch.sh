#!/bin/bash
curl -s -X PATCH \
  -H "Authorization: Bearer vlnrlweDoyMYFwIRGF9uxv1lFsLNJC" \
  -H "Content-Type: application/merge-patch+json" \
  -d '{"name":"Land Associates","bio":"","gender":"","country":"","level_of_education":"","phone_number":"","language_proficiencies":[],"year_of_birth":1995}' \
  http://local.openedx.io/api/user/v1/accounts/landassociates
