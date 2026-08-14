# ApiTokenBundle (Kimai plugin)

Adds the one REST endpoint Kimai is missing: **creating** a personal API token for a user.

Kimai's own API can only delete tokens (`DELETE /api/users/api-token/{id}`); creating one is a
web-form action (`ProfileController::createAccessToken`, route `user_profile_access_token`).
Without this plugin, automated onboarding would have to drive an admin **web session** through
that HTML form (CSRF token, login throttling, 2FA and all) and would break on any Kimai UI
change. This bundle exposes the same operation, with the same permission check, as a normal API
endpoint.

Used by the Kimai MCP server (`src/kimai_mcp/provisioning.py`, enabled with `--auto-provision`) to
give every user who signs in through the configured OIDC provider their own Kimai token
automatically, so nobody has to copy a token by hand.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/users/{id}/api-token` | Token metadata of that user (`id`, `name`, `lastUsage`, `expiresAt`); never the token value |
| `POST` | `/api/users/{id}/api-token` | Creates a token and returns it **once**, `201` |

`POST` body (all fields optional):

```json
{
  "name": "Kimai MCP (auto)",
  "expiresAt": "2027-01-01",
  "replaceExisting": true
}
```

* `name`: 2–50 characters, shown in the user's profile (default: `API token`).
* `expiresAt`: `Y-m-d` or ISO 8601, must be in the future; omitted means no expiry.
* `replaceExisting`: replaces that user's existing tokens **with the same name**, so
  re-provisioning does not pile up dead tokens. The new token is created before the old ones
  are deleted, and both happen in one transaction, so an interrupted request can never leave
  the user without a working token; minting one is an admin operation they could not repeat
  themselves. Note that Kimai's only unique constraint is on the token value, not on
  (user, name), so several tokens may legitimately share a name.

Response:

```json
{
  "id": 42,
  "name": "Kimai MCP (auto)",
  "lastUsage": null,
  "expiresAt": null,
  "token": "0f89a9b2a4124faebfd89"
}
```

## Permissions

Both endpoints require the `api-token` voter for the target profile, i.e. the calling API token
must belong to a user with `api-token_other_profile`, which in Kimai's default role mapping only
**ROLE_SUPER_ADMIN** has (`PROFILE_OTHER` in `config/packages/kimai.yaml`). Callers can always
manage their own tokens (`api-token_own_profile`). This is exactly the check
`UserController::deleteApiToken()` performs, so the plugin grants no permission that the Kimai UI
would not.

## Installation

```bash
# on the Kimai host, as the vhost user
cp -r ApiTokenBundle <kimai>/var/plugins/
chown -R <vhost-user>:<vhost-group> <kimai>/var/plugins/ApiTokenBundle
php bin/console kimai:reload --env=prod
```

Verify:

```bash
curl -X POST -H "Authorization: Bearer <super-admin-token>" \
     -H "Content-Type: application/json" \
     -d '{"name":"probe","replaceExisting":true}' \
     https://<kimai>/api/users/<user-id>/api-token
# then confirm the token belongs to that user, and clean up:
curl -H "Authorization: Bearer <new-token>" https://<kimai>/api/users/me
curl -X DELETE -H "Authorization: Bearer <new-token>" https://<kimai>/api/users/api-token/<id>
```

The endpoints also appear in Kimai's Swagger UI (`/api/doc`) under the *User* tag.

## Compatibility

Requires Kimai **2.65.0** (`extra.kimai.require: 26500`) or newer. It relies on three stable
internals: the `AccessToken` entity, `AccessTokenRepository`, and the `api-token` voter attribute.
After a Kimai upgrade, re-run the verification call above; the MCP server treats a `404`/`403`
from this endpoint as "auto-provisioning unavailable" and answers the sign-in with its usual
"not authorized" page, so a broken plugin degrades onboarding rather than breaking the server.
The server also probes for this bundle at startup (`--auto-provision`) and logs an explicit error
naming this file when it is missing.

## Test coverage

There is none, and the CI of this repository cannot supply any: it is a Python project, so it runs
`ruff` and `pytest` and has no PHP toolchain or Kimai checkout to test a bundle against. The
Python side is covered (`tests/test_provisioning.py`, `tests/test_api_tokens.py`), the PHP side is
verified by the manual `curl` sequence above. Treat a Kimai major upgrade as a reason to re-run it.
