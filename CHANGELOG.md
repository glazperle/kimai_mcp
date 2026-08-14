# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Every project create/update carrying a date, and every date-filtered project listing, raised
  `AttributeError`.** `ProjectEditForm.start`/`end` and `ProjectFilter.start`/`end` are declared
  `str` ("Format: YYYY-MM-DD"), but `create_project`, `update_project` and `get_projects` called
  `.isoformat()` on them, so anything setting a project timeframe failed outright with
  `'str' object has no attribute 'isoformat'`. The calls were also redundant:
  `model_dump()` had already placed those strings in the payload. Removed.
  - Same root cause as the timesheet issue below — a model declaring one type while the code
    assumes another — but a separate code path, so it is fixed separately.
  - Documented while verifying against a live instance: Kimai accepts a date-only `YYYY-MM-DD`
    when *creating* a project, but the PATCH form rejects it with "Please enter a valid date."
    and requires the full `YYYY-MM-DDTHH:MM:SS` form. The model comment said only the former.

- **`timer action=active` failed on every response** ([#24](https://github.com/glazperle/kimai_mcp/issues/24)).
  `GET /timesheets/active` and `GET /timesheets/recent` are declared as `TimesheetCollectionExpanded`
  in Kimai's `src/API/TimesheetController.php`. That schema carries the `Expanded` serializer group,
  so `project`, `activity` and `user` arrive as objects rather than ids. Both were parsed with
  `TimesheetEntity`, whose relations are typed `int`, so Pydantic rejected the entire response with
  three `int_type` errors — the request itself had succeeded, the data was only ever visible inside
  the error. The expansion is recursive (the project carries its customer, and the activity carries
  a project which carries that customer again), so coercing the three top-level fields back to ids
  would not have been enough.
  - New `TimesheetExpanded`, `ProjectExpanded` and `ActivityExpanded` models describe the `Expanded`
    schemas. `TimesheetEntity` keeps describing the `Not_Expanded` ones (`GET /timesheets`,
    `GET /timesheets/{id}`, create, update) and is unchanged. `client.get_active_timesheets()` and
    `client.get_recent_timesheets()` now return `TimesheetExpanded`.
  - `timer action=active` now names the relations it already had in hand: it prints
    `Customer / Project` and the activity name instead of interpolating bare ids.
  - `timer action=recent` was never affected — its handler builds a `TimesheetFilter` and calls
    `get_timesheets()`, so it reads the plain collection endpoint. The defect in
    `get_recent_timesheets()` was latent and is fixed alongside it.
  - `scripts/audit_api_models.py` reported clean throughout, because it mapped every Timesheet alias
    onto `TimesheetEntity` and compares field *names* only: an `activity` that arrives as an object
    still has the right name. The `Expanded` aliases now point at the new models, and
    `TimesheetExpanded` is mapped for the first time. A type-level assertion on relation fields would
    catch this class of gap in general; that is left as a follow-up.

### Added

- **Automatic Kimai onboarding for OIDC logins** (`--auto-provision`, `provisioning.py`). Until now
  every user had to exist in `users.json` before they could sign in, together with an API token an
  administrator first clicked together in Kimai's web UI — two manual steps before a new colleague
  can use the connector at all. With the flag set, an OIDC identity that matches no configured user
  is resolved against Kimai's own user list and Kimai mints that user's personal API token on the
  spot, so signing in with the identity provider is the only step a user ever performs.
  - Matching runs six rules from strongest to weakest and stops at the first that matches. **Every
    rule must produce exactly one candidate**; a rule that hits several users aborts with
    "ambiguous" instead of guessing, because a wrong match would hand one employee another
    employee's token. The minted token is checked against `/api/users/me` and discarded if it
    resolves to a different user — but that guards a wrong *token*, not a wrong *match*, which is
    why the two name-based heuristics only run with `--provision-match fuzzy`. The default,
    `normalized`, compares emails, usernames and address local parts with umlaut/diacritic folding
    (`anna.vondorf` == `Anna von Dorf`); `exact` restricts it to full equality. The folded
    comparison requires an address of at least two name parts, because a single given name is not
    an identifier: `max@corp.example` must not be matched to a colleague whose Kimai alias is
    `Max` or whose address is `max@partner.example`. Those produce exactly one candidate, so the
    ambiguity guard cannot catch them — the rule itself has to refuse.
  - **Off by default and strictly additive.** Every failure mode — no match, ambiguous match,
    plugin missing, admin token without permission, Kimai unreachable — answers with the same
    generic "not authorized" page the OIDC callback already returned, with the reason server-side
    in the log only. Enabling it cannot change behaviour for a deployment that works today.
  - Provisioned users live in memory, like the OAuth access and refresh tokens; `--provision-store
    FILE` keeps them across restarts (plaintext tokens, written `0600`). Re-provisioning is
    idempotent — tokens are replaced by name — so a restart without the store costs one Kimai call
    at the next sign-in and leaves no dead tokens in the user's profile. A hand-written
    `users.json` entry always wins over a stored one.
  - Configuration mirrors the `--oidc-*` family: `--provision-kimai-url`, `--provision-admin-token`,
    `--provision-token-name`, `--provision-match`, `--provision-store`, `--provision-ssl-verify`,
    each with a `KIMAI_MCP_PROVISION_*` environment variable. A half-configured feature aborts at
    startup instead of silently rejecting every first sign-in.
- **`kimai-plugin/ApiTokenBundle`** — a small Kimai plugin supplying the endpoint Kimai lacks:
  `POST /api/users/{id}/api-token` (plus `GET` for metadata). Core Kimai can only *delete* tokens
  through the API; creating one is a web-form action, so the alternative would have been driving an
  admin web session through that HTML form. The plugin reuses Kimai's own `api-token` voter, i.e.
  it grants nothing the Kimai UI would not — the calling token needs `api-token_other_profile`
  (ROLE_SUPER_ADMIN by default). Requires Kimai 2.65+, is part of neither the Python package nor
  the Docker image, and has no automated tests: this repository's CI has no PHP toolchain.
- `KimaiClient.create_api_token()` / `get_api_tokens()` and the `AccessTokenInfo` /
  `AccessTokenCreated` models — the client side of that plugin.
- `UsersConfig.load(allow_empty=True)` and `UsersConfig.add_user()`. Without the first, a
  provisioning-only deployment could not boot at all: both loaders and `initialize_users()`
  insisted on at least one user existing before anybody had signed in.

## [2.16.0] - 2026-08-11

Ports the server to MCP Python SDK 2.x, catches up with Kimai 2.62 - 2.65, and fixes a group of defects a review of the port surfaced. Several of them are long-standing and silent: the tool reported success while the field never reached Kimai.

### Fixed

- **Aliased fields passed by their Python name were silently dropped.** No model set `populate_by_name`, so Pydantic ignored the field name and `model_dump(by_alias=True)` left the field out entirely. Four call sites were affected: `absence action=create` with `halfDay` **booked a full day** off the user's vacation quota; `rate action=add` dropped `isFixed` and `internalRate`, so a fixed rate was **created as an hourly one**; `timesheet action=create` never sent `break`, the field CLAUDE.md documented as supported; and `order_by` was dropped from customer, project and activity listings, so results came back sorted by Kimai's default column while `order=DESC` still applied. Every case answered "created"/"updated" as if it had worked. All models now derive from a `KimaiModel` base that accepts both spellings; the wire format is unchanged.
- **Tool arguments are validated against the tool schema again.** SDK 1.x ran `jsonschema.validate(arguments, inputSchema)` server-side and answered `Input validation error: ...`; SDK 2.x dropped it (jsonschema is client-side only there), and the constructor-based handler registration inherits that. Since the entity `data` sub-schemas are `additionalProperties: false` while the Pydantic forms ignore extras, a typo like `{"langauge": "de"}` sent an **empty PATCH** and reported `Updated Customer: ...`. `tools/registry.py::validate_arguments` restores the check for both transports.
- **OIDC: `require_verified_email` was a no-op with real IdPs.** The guard skipped the unverified `email` claim and then accepted the same address from `preferred_username`/`upn` one iteration later. Entra ID, Keycloak, Auth0 and Okta all emit those next to `email`, so an IdP account with an unverified address could map to another user's slug. A token whose `email` claim is not asserted as verified is now rejected for identity mapping entirely. Deployments whose `identity_claims` do not include `email`, and tokens that carry no `email` claim at all, are unaffected, as is the `--oidc-allow-unverified-email` opt-out.
- **Rotating a refresh token orphaned the old access token.** It stayed in the token store while both pairing maps dropped it, so `revoke_token` could no longer reach it and it kept authenticating until its TTL expired, one unrevocable bearer token per refresh. Revocation now terminates access as documented.
- **On-demand session initialization produced a permanently broken endpoint.** A user whose startup init failed (Kimai briefly unreachable) got a fresh `StreamableHTTPSessionManager` whose `run()` was never entered, which answers `Task group is not initialized` on every request, and the session was then cached in that state. Session managers now run in their own supervised task, which is also what anyio requires: the task that enters the manager's task group has to be the one that exits it. The corresponding test drives a real request through the healed session instead of only asserting that an attribute is set.
- **`session_idle_timeout` is set to 30 minutes.** SDK 2.x added it and defaults it to `None`, which reclaims a session only when its transport crashes, so a cleanly closed session leaked a transport and a task on every reconnect.
- **Exceptions could escape `_call_tool` as protocol errors.** `_ensure_client()` ran outside the try block, so a failure constructing the HTTP client (e.g. an unreadable CA bundle passed to `--ssl-verify`) surfaced as a JSON-RPC error rather than the `is_error` result of #18, and every later call failed the same way.
- **A mixed-offset date filter failed the whole timesheet listing.** The year-breakdown heuristic subtracts the two bounds; with one bound carrying a UTC offset and the other not, that raises `TypeError`, which the `ValueError`-only suppression introduced with the ruff cleanup did not catch. The heuristic is best effort again and simply leaves the breakdown off.
- **Multi-chunk absence creation hid API errors.** Splitting a long absence wrapped `KimaiAPIError` into a plain tool error, discarding the status code, the validation details and the 403 permission hint that the single-chunk path reports.
- **`analyze_project_team` answered with interpreter errors** such as `Error: 'begin'` for a missing argument, because required arguments were read above the try block.
- **A rejected conditional field now explains itself.** Kimai builds its API forms from the enabled features, so `break` only exists on the timesheet form when "Break time" is on (Settings > Timesheet). Since the alias fix above means the field is now really sent, an instance with that setting off answers `This form should not contain extra fields.` without naming a field. `format_api_error()` says what to do about it, and the tool schema states the requirement. Found by running the write paths against a real instance that has break time disabled.

### Added

- **MCP protocol revision 2026-07-28.** With SDK 2.x the server speaks the current revision and still serves every earlier one from the same code, so 2025-era clients (including current Claude Desktop builds) and 2026-era clients both work without configuration. (#21)
- **The complete customer field set.** `language` and `invoiceEmail` are new in Kimai 2.63 ([kimai/kimai#5857](https://github.com/kimai/kimai/pull/5857), [#5855](https://github.com/kimai/kimai/pull/5855)), but the model stopped at the `Default` serializer group in general, so `vatId`, the structured address (`addressLine1`-`3`, `postCode`, `city`), `contact`, `email`, `buyerReference` and the budget fields were parsed away even on `action=get`. All of them are now read and rendered, and `language`/`invoiceEmail` are writable on `create`/`update` (the customer `data` schema is `additionalProperties: false`, so they need explicit schema entries to be sendable at all).
- **`metaFields` on listings.** Kimai puts them in the `Default` group, so every list response carries them, but only the `*Extended` models declared the field: custom fields were dropped from every `list` result for customers, projects and activities. The base models parse them now.
- **The fields every other model was dropping**, found by auditing the models against Kimai's own schema definitions and confirmed against a live 2.65 instance: `teams` on customers, projects and activities (who has access, previously invisible); `start`, `end`, `orderDate`, `orderNumber`, `parentTitle` and the budget on projects; `parentTitle`, `teams` and the budget on activities; `email`, `accountNumber`, `avatar`, `systemAccount`, `initials`, `language`, `locale`, `timezone` on users; `invoiceFilename` on invoices; `memberships` on the user entity. Projects and activities now show the customer/project name, the timeframe, the order number, the budget and the teams; customers show their teams. `color-safe` and `apiToken` stay unmodelled on purpose, documented in `models.py` and in both audit scripts.
- **`scripts/audit_api_models.py`** compares the models against Kimai's schema definitions (`nelmio_api_doc.yaml` plus the entity sources at a given tag) with no instance needed, and **`scripts/verify_against_kimai.py`** checks the same against a running server using GET requests only, so it is safe to point at production. Both exit non-zero on a gap; run them after each Kimai release. This replaces the placeholder snippet that used to stand in for API-compliance testing.
- **Full-detail customer listings**: `entity type=customer action=list filters={"full": true}` maps to the `full=1` parameter added in Kimai 2.62, which adds exactly `vatId` and the structured address. It needs the `details_customer` permission and Kimai silently returns the short form without it rather than failing. `language` and `metaFields` come back without `full` (they are in `Default`), while `email`, `contact`, `invoiceEmail`, `buyerReference` and the budget are `Customer_Entity` only and never appear in a listing regardless of `full`.
- **`tests/test_mcp_protocol.py`**: drives both transports through a real in-memory MCP client session (connect, `tools/list`, `tools/call`, every error path, unknown tool, advertised capability and version) across both protocol eras, 28 cases. Issue #21 was a crash in `__init__`, which no handler-level unit test could ever see; this closes that gap for future SDK bumps.
- **`tests/test_review_regressions.py`**: one test per defect listed above, each stating the observable failure it prevents.
- CI smoke-tests the console scripts **and constructs both servers**, since `--help` exits in `parse_args()` before any server object exists and would not have caught #21. The matrix now also covers Python 3.11 and 3.14 (3.14 is what the published Docker image runs).

### Changed

- **Requires `mcp>=2.0,<3`.** Handlers are registered through the `Server(...)` constructor (`on_list_tools`/`on_call_tool`) instead of the removed decorators, take `(ctx, params)`, and return `ListToolsResult`/`CallToolResult`. SDK 2.x no longer wraps a bare content list, so both transports pass handler output through the new `tool_result()` helper. Protocol model fields are snake_case now (`input_schema`, `is_error`); the tool definitions and `error_result()` follow suit. The `mcp.server.auth.*` surface used by `oauth.py` and `StreamableHTTPSessionManager` are unchanged, so OAuth 2.1, DCR, PKCE and the legacy slug endpoints behave exactly as before.
- `team_access action=revoke` documents that **Kimai 2.65** additionally requires the `permissions` permission on the target customer/project/activity; a token that could revoke on 2.64 may now receive a 403 (the existing permission hint covers it).
- `entity type=user action=set_preferences` documents that **Kimai 2.63** guards work-contract preferences more strictly, so a 403 means a missing permission, as opposed to the 404 that signals an un-initialized contract on Kimai < 2.61.
- Documentation is tracked against Kimai 2.65, and the local API-documentation export referenced in CLAUDE.md is flagged as a December 2025 snapshot.
- **The lint baseline is declared in `pyproject.toml` instead of being whatever the tool defaults to.** A `[tool.ruff]` section now records the line length, keeps ruff's default rule set as the base, and extends it with `C4`, `N`, `PT` and `PTH` (20 findings fixed: `open()` to `Path.open()`, tuple parametrize names, compound asserts, a shouting local constant). The families left out (`ANN`, `D`, `TRY`, `EM`, `ARG`, `TID`) are listed with the reason and the finding count each would add, so excluding them is a recorded decision rather than an accident.
- `fastapi` dropped from the `[server]` extra: the deleted SSE server was its only importer, the streamable server is plain Starlette (which `mcp` brings) plus uvicorn.
- The German absence labels used by the attendance report are the ones from `AbsenceAnalytics` instead of a byte-identical private copy, so the two reports cannot drift apart.

### Removed

- **The SSE server and its `kimai-mcp-server` command.** It had been documented as deprecated and **non-functional** since v2.12.0: the SSE transport was dropped from the MCP specification in favour of Streamable HTTP, and the transport wiring in `sse_server.py` was already broken, so the command printed a warning and could not serve a client. (The MCP SDK does still ship `mcp.server.sse`; the removal is about this project's dead code, not about the SDK.) Use `kimai-mcp-streamable` for remote access. The `SessionManager`/`SessionConfig` helpers in `security.py` are removed with it, since only the SSE server used them. The `docker-compose.yml` service keeps its name and is unaffected: it runs `kimai-mcp-streamable`.

## [2.15.1] - 2026-08-11

Hotfix release: new installations were broken. No functional changes to the tools.

### Fixed

- **Server no longer crashes on startup with MCP SDK 2.0.0.** The dependency was declared as `mcp>=1.27.0` without an upper bound, so a fresh install resolved to SDK 2.0.0 (released 2026-07-28), whose low-level `Server` no longer has the `list_tools()`/`call_tool()` decorators. `KimaiMCPServer.__init__` therefore died with `AttributeError: 'Server' object has no attribute 'list_tools'` before the MCP handshake, and every client reported the server as failed. The dependency is now capped at `mcp>=1.27.0,<2`. The port to the SDK 2.x API (and with it protocol revision 2026-07-28) follows in 2.16.0. (#21)
- **CI was red on every pull request.** ruff 0.16.0 grew its default rule set from 59 to 413 rules; with no ruff configuration and no version pin (`ruff>=0.1.0`) the workflow always installed the newest release, so `ruff check src/` reported 806 findings and blocked unrelated PRs, including Dependabot's.

### Changed

- **The new ruff defaults are now the project's lint baseline.** 786 findings were auto-fixed (PEP 604 unions, builtin generics, import order, f-string conversions); the remaining 51 were fixed or suppressed at the individual site with a stated reason, so a new blind `except Exception` still shows up in CI. ruff is pinned to `>=0.16,<0.17`. (2.16.0 adds the explicit `[tool.ruff]` section on top of this.)
- **Dependency majors are capped** (`mcp<2`, `httpx<1`, `pydantic<3`, `python-dotenv<2`). Dependabot only files a PR when it can change a constraint, so with lower bounds only it never reported a single Python update for this project, which is how the breaking `mcp` 2.0 release went unnoticed until it broke installs.
- **Strict `YYYY-MM-DD` parsing lives in one place** (`tools/dates.py`) instead of being copy-pasted across `absence_manager` and `calendar_meta`. As a side effect, `absence action=create` with an unparsable `date`/`end` now returns a proper tool error instead of letting a raw `ValueError` escape.
- Timestamps that intentionally use local time (Claude Desktop config backup name, absence attendance "today", timer elapsed calculation) say so explicitly instead of relying on a naive `datetime.now()`.
- CI lints `tests/` as well and runs Python 3.13 in addition to 3.10 and 3.12; `actions/setup-python` bumped to v7. (#20)
- `requirements.txt` removed: no workflow or Dockerfile used it and it still pinned `mcp>=0.9.0`, contradicting `pyproject.toml`.

## [2.15.0] - 2026-06-30

### Changed

- **In-handler tool errors are now reported with `isError=true`.** v2.14.0 only marked caught exceptions; this extends the same behavior to the validation, unknown-action/type, and unsupported-operation conditions that handlers previously returned as a normal `Error: ...` `TextContent` (e.g. missing required parameters, invalid date formats, "Invoice creation is not supported", "Users cannot be deleted", unknown tool). Handlers now `raise ToolError` (new `tools/errors.py`), which both transports' `_call_tool` convert to a `CallToolResult(isError=True)` via the shared `error_result()` helper. The error message text is unchanged. (#18)
- Batch operations that partially succeed (the `✓ Succeeded / ✗ Failed` summaries) and informational output (e.g. the timesheet `user_guide`, "No absences found") remain successful results, since they are not tool failures.

## [2.14.0] - 2026-06-30

### Fixed

- **`entity` create/update raised `'MetaField' object has no attribute 'get'`** for projects, customers, and activities with custom meta fields. `create`/`update` return the `*Extended` models, whose `meta_fields` holds `MetaField` objects rather than dicts; the `serialize_*` branch was inverted and called dict's `.get()` on them. The entity is created before serialization, so the write succeeded despite the error. `list`/`get` were unaffected. (#17)
- **Tool execution errors are now reported with `isError=true`** so programmatic MCP clients can detect failures. Both transports (`server.py` and `streamable_http_server.py`) previously caught exceptions into a plain `TextContent` and returned a successful `CallToolResult` (`isError` unset), so a proxying gateway could not distinguish a `404`/crash from a normal payload. A shared `error_result()` helper now returns `CallToolResult(isError=True)` from the caught-exception paths and the streamable "client not initialized" guard, preserving the existing `format_api_error` message. (#18)

## [2.13.1] - 2026-06-19

Build and CI maintenance only; no functional or API changes.

### Fixed

- **Dockerfile is now resilient to Python base-image bumps.** The production stage copied installed packages from a hardcoded `/usr/local/lib/python3.11/site-packages` path, so any base-image bump (e.g. the Dependabot `python:3.11-slim` → `python:3.14-slim` update) broke the build with `"/usr/local/lib/python3.11/site-packages": not found`. The stage now copies `/usr/local` wholesale, which is version-agnostic, and the base image is bumped to `python:3.14-slim`.

### Changed

- **CI/CD action versions bumped** via Dependabot (#16): `actions/checkout` v4 → v7, `actions/setup-python` v5 → v6, `actions/upload-artifact` v4 → v7, `actions/download-artifact` v4 → v8, `docker/setup-buildx-action` v3 → v4, `docker/login-action` v3 → v4, `docker/metadata-action` v5 → v6, `docker/build-push-action` v5 → v7.

## [2.13.0] - 2026-06-19

Adds an optional OIDC federated-login backend for the Streamable HTTP server (#14) and refines the Work Contract setup guidance ([kimai/kimai#5751](https://github.com/kimai/kimai/issues/5751)). No breaking changes; the default `local` login behavior is unchanged.

### Added

- **Optional OIDC federated login for the Streamable HTTP server.** The server stays the OAuth 2.1 authorization server toward Claude.ai (same opaque tokens, DCR, PKCE) but can delegate the **login step** to any standard OpenID Connect provider (Microsoft Entra ID / Azure AD, Keycloak, Auth0, Google, Okta, …): `/authorize` redirects to the provider, the returned `id_token` is verified (JWKS signature, `iss`/`aud`/`exp`/`nonce`) and mapped to a configured user.
  - Enabled with `--auth-backend oidc`; configured via `--oidc-issuer`, `--oidc-client-id`, optional `--oidc-client-secret` (prefer `KIMAI_MCP_OIDC_CLIENT_SECRET`), `--oidc-scopes` (default `openid email profile`), `--oidc-identity-claim` (default `email`), `--oidc-discovery-url`. All have `KIMAI_MCP_OIDC_*` env equivalents.
  - Map each identity to a Kimai user via the new `oidc_identity` field in `users.json` (or `KIMAI_USER_<SLUG>_OIDC_IDENTITY`), matched case-insensitively against the identity claim.
  - Redirect URI to register at the provider: `<public-url>/oauth/oidc/callback`. Requires the `[server]` extra (pulls in `PyJWT[crypto]`). While OIDC is active, the built-in slug login form is not exposed.
  - When mapping by `email`, the `id_token` must assert `email_verified: true` (override with `--oidc-allow-unverified-email` for providers that only issue verified emails).

### Changed

- **`entity` `set_preferences` 404 hint** now leads with the real fix: upgrade Kimai to the release containing the work-contract auto-init fix (**≥ 2.61.0**, [kimai/kimai#5894](https://github.com/kimai/kimai/pull/5894)), which initializes work-contract preferences automatically. The Kimai-UI workaround is kept as a fallback for older servers (< 2.61.0). When the failing request includes `hours_per_week`, the hint adds that this preference is not auto-initialized (set `work_contract_type="week"` first).
- **Docs** (`CLAUDE.md`, `examples/usage_examples.md`) note that on Kimai ≥ 2.61.0 `set_preferences` works without configuring the work contract in the UI first, including the `hours_per_week` caveat.

## [2.12.1] - 2026-06-12

Follow-up patch addressing the points left open in 2.12.0. No breaking changes.

### Fixed

- **OAuth refresh tokens** now preserve their resource/audience binding across rotations (previously dropped to `None` after the first refresh) and are rejected when presented with a mismatched `client_id` (cross-client misuse).
- **OAuth client store** is no longer unbounded: dynamically registered clients are evicted after 30 days of inactivity (last-seen renewed on use) or once their secret expires; the state file is rewritten once after pruning.
- **Streamable HTTP server** now (re)initializes a user session on demand. A configured user whose startup init failed (e.g. Kimai briefly unreachable) no longer stays in a permanent error loop until the next restart; the endpoint returns 503 (was 403) while no session can be established.

### Changed (internal, no behavior change)

- Both servers now share a single tool registry (`tools/registry.py`) for the tool list and name→handler dispatch, removing the duplicated dispatch tables that could drift apart.
- `meta` tool uses a uniform handler map; invoice is no longer a special case.
- Comment client methods consolidated (8 → 4, parameterized by entity); `user_discovery` reuses the shared `execute_batch` helper.

## [2.12.0] - 2026-06-12

### Upgrade Notes

Nothing breaks for existing setups, but please note:

- **Dependency bump**: `mcp>=1.27.0` is now required (was `>=0.9.0`). `pip install --upgrade kimai-mcp` handles this automatically.
- **Streamable HTTP server**: Your existing `/mcp/{slug}` URLs keep working, but they are now deprecated in favor of OAuth 2.1 (see below). The server logs a warning at startup if a slug has low entropy — treat slug URLs like passwords or migrate to OAuth. Use `--disable-legacy-slugs` to turn slug URLs off entirely.
- **users.json**: The `kimai_user_id` field never had any effect and has been removed. Files that still contain it keep loading (the field is ignored). Slugs must match `[a-zA-Z0-9_-]+`; anything else is now rejected at startup.
- **SSE server (`kimai-mcp-server`) is deprecated**: It was non-functional (broken transport wiring) and now prints a deprecation warning. Migrate remote setups to `kimai-mcp-streamable`.
- **`--kimai-user` / `KIMAI_DEFAULT_USER` is deprecated**: It never had any effect; it is still accepted but ignored (with a warning). Remove it from your configs.
- **Error output format changed**: API errors returned to the MCP client now include the HTTP status, validation details, and a permission hint on 403. Only relevant if you parse error strings.
- **Kimai server version requirements for new features**: the `comment` tool requires Kimai 2.57+, invoice meta fields require Kimai 2.56+. Everything else works with older Kimai versions as before.

### Added

- **OAuth 2.1 for the Streamable HTTP server** (Claude.ai Connectors)
  - New protected `/mcp` endpoint (no slug) with Bearer-token authentication
  - Dynamic Client Registration, mandatory PKCE (S256), refresh-token rotation
  - Login form at `/oauth/login` (user slug + new per-user `auth_secret` in users.json or `KIMAI_USER_<SLUG>_AUTH_SECRET`)
  - New CLI options / env vars: `--public-url` (`KIMAI_MCP_PUBLIC_URL`), `--trusted-proxy` (`KIMAI_MCP_TRUSTED_PROXIES`), `--disable-legacy-slugs` (`KIMAI_MCP_DISABLE_LEGACY_SLUGS`), `--oauth-state-file` (`KIMAI_MCP_OAUTH_STATE_FILE`)
- **New `comment` tool** (12th tool): list/create/delete/pin comments on projects and customers (Kimai 2.57+)
- **Invoice meta fields**: `meta` tool now supports `entity: "invoice"` (Kimai 2.56+); all fields are sent in a single request
- Dispatch smoke tests covering every tool action against a spec'd client mock, plus OAuth/security test suites

### Fixed

- **Five completely broken tool actions** (called non-existent client methods or wrong signatures): `timesheet export_toggle`, `timesheet batch_export`, `absence batch_approve`, `entity invoice list`, `entity holiday list`, and `meta update` (passed a list where the API client expects single fields)
- `entity holiday list` / holiday calendar returned 400 from Kimai because dates were sent date-only; they now use full ISO datetime (verified against Kimai 2.60.0)
- `timer active` crashed with a timezone error as soon as a timer was running
- Tool outputs contained literal `\n` text instead of line breaks (~270 occurrences)
- Rate listing never showed internal rate and fixed/hourly type; absence listing never showed end date and half-day flag (wrong attribute names)
- `entity project list` ignored the `term` search filter
- Broken JSON schema keyword (`allOff`) disabled conditional validation in the `entity` tool
- Auto-pagination in the client was unreachable from the `timesheet` tool and ignored singular entity filters
- MCP handshake reported hardcoded version 2.0.0 instead of the package version
- httpx client leak when a user session failed to initialize (Streamable HTTP server)
- Rate-limiter and enumeration-protection cleanup never ran (unbounded memory growth)
- `X-Forwarded-For` was trusted unconditionally, allowing rate-limit bypass; now only honored behind a configured `--trusted-proxy`

### Changed

- Centralized error handling: API errors now reach the client with status code, validation details, and a 403 permission hint (relevant since Kimai 2.57/2.58 enforce permissions more strictly)
- Performance: `user_scope="all"` operations (absences, statistics, attendance, bulk lock/unlock) now run user lookups and per-user requests in parallel; shared user-discovery helper replaces six duplicated code paths; `config type=all` fetches in parallel; tag listing filters server-side
- `analyze_project_team` stops fetching at the dataset limit instead of discarding data afterwards, and searches projects server-side

### Deprecated

- SSE server (`kimai-mcp-server`) — non-functional, use `kimai-mcp-streamable`
- `--kimai-user` / `KIMAI_DEFAULT_USER` — never had any effect
- `/mcp/{slug}` URLs on the Streamable HTTP server — use OAuth at `/mcp`

### Removed

- `kimai_user_id` from users.json / `KIMAI_USER_*_USER_ID` env vars (dead configuration)
- `sse-starlette` dependency (unused)

## [2.11.3] - 2026-04-21

### Fixed

- Timesheet list no longer crashes when `begin`/`end` filters are missing (#12, #13)

## [2.11.2] - 2026-01-07

### Fixed

- Version is imported from `__init__.py` instead of being hardcoded in `server.py`

## [2.11.1] - 2026-01-01

### Changed

- Better work contract error handling

## [2.10.0] - 2025-12-31

### Added

- **User Preferences Management** - New `set_preferences` action for user entities in the `entity` tool
  - Configure work contracts (weekly or daily hours)
  - Set vacation days and public holiday groups
  - Define contract start/end dates
  - Set user rates (hourly/internal)
  - Supports both "week" type (total hours) and "day" type (per-weekday hours)
- New client method `update_user_preferences()` for PATCH `/api/users/{id}/preferences`
- New `UserPreference` Pydantic model for preference name-value pairs
- Documentation for all work contract preferences in `examples/usage_examples.md`

### Changed

- `entity` tool now accepts `preferences` parameter for user type with `set_preferences` action

## [2.9.0] - 2025-12-30

### Added

- **Comprehensive Security Module** - New `security.py` with enterprise-grade security features
  - **Rate Limiting**: Token bucket algorithm to prevent DoS and brute-force attacks (configurable via `--rate-limit-rpm`)
  - **Session Management**: Maximum concurrent sessions and TTL-based expiration (configurable via `--max-sessions`, `--session-ttl`)
  - **Security Headers**: Automatic X-Content-Type-Options, X-Frame-Options, X-XSS-Protection headers
  - **Enumeration Protection**: Random delays on 404 responses and automatic blocking after excessive failed requests
- New CLI arguments for security configuration:
  - `--rate-limit-rpm`: Requests per minute per IP (default: 60, 0 to disable)
  - `--max-sessions`: Maximum concurrent sessions (default: 100, SSE server only)
  - `--session-ttl`: Session timeout in seconds (default: 3600, SSE server only)
  - `--require-https`: Enforce HTTPS connections (SSE server only)
- Environment variable support: `RATE_LIMIT_RPM`, `MAX_SESSIONS`, `SESSION_TTL`, `REQUIRE_HTTPS`
- Unit tests for all security components in `tests/test_security.py`

### Changed

- **CORS Security Fix**: `allow_credentials=False` when using wildcard origins (`*`) to prevent credential theft
- **Removed X-Session-ID Header**: Session IDs no longer exposed in HTTP response headers

### Removed

- **`/users` Endpoint** (Streamable HTTP Server): Removed to prevent user/endpoint enumeration attacks
- **User slugs in `/health` response** (Streamable HTTP Server): Now only returns `user_count` instead of full user list

### Security

- Fixed potential session hijacking via overly permissive CORS configuration
- Fixed unbounded session growth that could lead to memory exhaustion
- Fixed timing-based user enumeration via 404 response times
- Added protection against brute-force attacks on MCP endpoints

### Migration Notes

- The `/users` endpoint is no longer available - administrators should track user slugs separately
- Health check response format changed: `users` array replaced with `user_count` integer
- Rate limiting is enabled by default (60 req/min) - set `--rate-limit-rpm=0` to disable

## [2.8.0] - 2025-12-30

### Added

- **Streamable HTTP Server for Claude.ai Connectors** - New `streamable_http_server.py` enables integration with Claude.ai custom connectors
  - Works with Claude.ai web and mobile apps
  - Multi-user support with per-user endpoints (`/mcp/{user_slug}`)
  - Server-side Kimai credential management via `users.json`
- **User Configuration System** - New `user_config.py` for managing multiple user credentials
  - JSON-based configuration file (`config/users.json`)
  - Support for per-user Kimai URL, token, and settings
- New CLI entry point `kimai-mcp-streamable` for running the Streamable HTTP server
- Example configuration template `config/users.example.json`

### Changed

- Docker default command changed from `kimai-mcp-server` to `kimai-mcp-streamable`
- Docker Compose now mounts `config/users.json` for user configuration

### Migration Notes

- Existing SSE server users: No changes required, use `kimai-mcp-server`
- Docker users: Default behavior changed to Streamable HTTP - override CMD if SSE is preferred

## [2.7.0] - 2025-12-29

### Added
- **Remote MCP Server with HTTP/SSE Transport** - New `sse_server.py` enables remote deployment of the MCP server, allowing multiple clients to connect via HTTP/SSE
- **Per-Client Kimai Authentication** - Each client can now use their own Kimai credentials when connecting to the remote server
- **Docker Support** - Complete Docker deployment with multi-architecture images (amd64/arm64)
  - New `Dockerfile` for containerized deployment
  - New `docker-compose.yml` for easy orchestration
  - GitHub Actions workflow for automatic Docker image publishing to GHCR
- **Deployment Documentation** - Comprehensive guide in `DEPLOYMENT.md` for remote server setup
- **Release Process Documentation** - Step-by-step release guide in `RELEASING.md`
- New CLI entry point `kimai-mcp-server` for running the SSE server

### Changed
- Added `[server]` optional dependencies in `pyproject.toml` for FastAPI, Uvicorn, and SSE-Starlette

## [2.6.0] - 2024-12-XX

### Added
- Batch operations for absences, timesheets, and entities
- Auto-split for absences exceeding 30-day limit
- Attendance action to show who is present today
- Absence analytics and improved permission handling

### Fixed
- Filter attendance to show only active employees
- Auto-split year-crossing absences for Kimai compatibility

## [2.5.x] - 2024-12-XX

### Added
- Attendance tracking features
- CLI improvements with `--help`, `--version`, and `--setup` wizard

### Fixed
- Correct `user_scope='all'` handling for timesheets and absences

## [2.3.x] - 2024-XX-XX

### Added
- Consolidated tools architecture (73 tools → 10 tools)
- Universal entity handler for CRUD operations
- Smart user selection with `user_scope` enum

### Changed
- 87% reduction in tool count while maintaining all functionality
