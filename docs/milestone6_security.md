# Authentication, authorization and data security

Current delivery uses React and the same-origin FastAPI adapter. The assessment
below retains the original security milestone scope; current transport details
are documented alongside its preserved service controls.

## Assessment before database changes

The Milestone 5 application is a trusted-local single-user prototype. Shared cached
repositories/pipelines have no identity context. Public document queries, review and
policy services, retained sources and exports can access all records. Typed operators
are unverified. Revision checks and immutable SQLite history protect normal application
operations but not a person with filesystem/SQL administrator access. Original database
and earlier evaluations must remain untouched during development.

Threats: guessed document IDs and forged reviewer names; cross-department searches and
aggregations; privilege escalation through cached contexts or account edits; stolen or
expired sessions; unauthenticated download/media URLs; malicious filenames, corrupted
uploads, oversized rendering; document prompt injection; provider errors leaking OCR or
credentials; direct database modification; unsafe cleanup of active/audited sources.

Priority plan, before any schema change:

1. Add backed-up identity/session/security-event tables without rewriting historical
   records. Use Argon2id, random opaque sessions stored as hashes, expiration, lockout,
   deactivation and one-time local CLI administrator bootstrap. No browser first-user
   takeover or shared/default administrator password.
2. Introduce a default-deny authenticated repository context. Server-only internal
   capabilities support migrations/workers/regression fixtures; they are never accepted
   from browser fields, query strings or session claims. Revalidate accounts/sessions
   on each protected service call. Scope reads before filters/aggregations and authorize
   each mutation and linked resource. Label legacy actors without inventing identities.
3. Protect exports/source delivery on an authenticated localhost HTTP endpoint with
   short-lived, one-use grants bound to valid sessions and fresh resource authorization.
   Never expose protected data through public static or media URLs. Use authenticated
   delivery for source files, exports and sensitive previews.
4. Add a login/account experience, role-aware navigation and guided policy controls.
   Remove shared user-scoped caches and clear all session data on logout/identity changes.
5. Strengthen source hash checks, explicit AI consent, bounded inputs and injection
   warnings. Restrict retention cleanup to closed, expired, unreferenced sources; preserve
   document/model/audit rows. Record safe security metadata only.
6. Test backend adversarial access, all prior regressions, copied-database migration and
   actual administrator/reviewer/unauthorized-account browser sessions. Bind servers to
   localhost, preserve original hashes, report exact results and remaining limitations.

## Prototype boundaries

The trust boundary is between browser users and server application services. OS users who
can read the database, server memory, keys or execute privileged Python remain outside
this boundary; secure Windows account permissions and encrypted storage are required.
Local authentication lacks OIDC/MFA, TLS termination, distributed rate limiting and
production session infrastructure. A public deployment requires those controls and an
independent security review. SQLite append-only triggers are not cryptographic protection.

Password hashing follows the maintained argon2-cffi PasswordHasher defaults (Argon2id):
https://argon2-cffi.readthedocs.io/en/stable/api.html.
The React application uses an HttpOnly, SameSite=strict session cookie and
server-side session validation. Refresh retains valid authentication; expiry, logout
or account changes require a new login. The local HTTP prototype does not set the
cookie Secure flag; public deployment requires TLS and an appropriate cookie policy.
No public deployment or compliance claim is part of this increment.

## Implemented identity and session controls

The maintained argon2-cffi 25.1 PasswordHasher creates Argon2id hashes with independently
random salts. Passwords must contain 12–128 characters. Account names are unique,
case-insensitive, immutable 3–64 character identifiers. No default accounts are inserted
by migration. First administrator setup is a one-time local command with getpass input:

```
uv run --python 3.14.6 python scripts/manage_security.py bootstrap
```

Choose your own account name and password at the prompts; neither is supplied as a CLI
password argument or printed. This command intentionally migrates the configured local
database with consistent backups before creating the account. The development audit uses
copies only; no account was created in the original database. Browser setup cannot claim
the first administrator. Local server/OS operator authority is the bootstrap trust anchor.

Opaque 256-bit random sessions are stored only as SHA-256 hashes. Tokens are not usernames,
client-supplied role claims or predictable IDs. Each protected request rechecks current
account activation, role, scope, revocation, absolute expiration (one hour) and idle timeout
(15 minutes). Account changes/password changes revoke all existing sessions. Logout
revokes its session, clears the session cookie and returns the React interface to
sign-in. Browser refresh revalidates the cookie against the server. The token is not
stored in localStorage. Already received browser data/downloads cannot be revoked remotely.

Failed login counters are persisted for normalized account-name hashes and a global
local-server bucket. Five failures per account or thirty global failures during fifteen
minutes impose a fifteen-minute limit; error responses do not reveal account existence.
These limits can be abused for local denial of service; a distributed/IP-aware scheme
and MFA are deferred. Password rehashing follows maintained-library recommendations.
Administrators create individual accounts and explicit manager/auditor department scope.
Account access changes use optimistic revisions; the last active administrator cannot
be disabled/demoted. Forgotten-password recovery is not implemented; controlled local
operator recovery requires a future dedicated tool rather than shared credentials.

## Permission matrix

| Role | Authorized documents | Review/mutation | Policies/users/intake | Exports/source | Analytics |
|---|---|---|---|---|---|
| Administrator | All | Guarded review, claim and reassignment | Policy lifecycle, accounts, ingestion/batches, retention | Authorized exports/source | All |
| Operations Manager | No raw document lookup | None | None | Scoped summary JSON only | Explicit assigned department summaries; no supplier names or duplicate identifiers |
| Finance Reviewer | Finance-owned cases; POs referenced by Finance invoices | Finance-owned cases only; no cross-team reassignment | None | Scoped documents/source | Same authorized scope |
| Procurement Reviewer | Procurement-owned cases; appropriate PO-related invoices | Procurement-owned cases only | None | Scoped documents/source | Same authorized scope |
| Expense Reviewer | Expense Processing-owned cases | Owned department only | None | Scoped documents/source | Same authorized scope |
| Legal Reviewer | Legal-owned cases/contracts | Owned department only | None | Scoped documents/source | Same authorized scope |
| Auditor | Read-only records/history in explicitly assigned departments | None | None | No sensitive export/source download | Scoped summaries |

Primary ownership is review_cases.team, including administrative reassignment. Finance
can read POs linked from Finance invoices; Procurement can read referenced invoices with
unresolved PO status or a Procurement-owned linked PO. These related-read exceptions do
not grant review authority outside primary ownership. A reviewer cannot mutate a case
claimed/assigned to another reviewer; only an administrator can reassign it to an active
authenticated reviewer with appropriate team scope. Typed actor forgery is rejected.
High-value or other non-low-risk approvals remain blocked, even for administrators; no
high-value override was introduced. Administrative policy reevaluation retains earlier
restrictions, opens fresh review, and preserves PO dependency safeguards.

All public document lists/lookups, search, operational queries, financial aggregations,
filtered exports, review actions and audit history enforce these scopes in backend code.
Missing sessions, unsupported roles, unknown IDs and inaccessible IDs deny access.
Account flags and role checks are not taken from browser/session display values. Shared
user-scoped repository/pipeline caches were removed. Navigation hiding is supplemental.
Raw SQL connection access is denied to ordinary repository contexts. Private SQL helpers
and a server-only INTERNAL object support migrations, deterministic verification and local
CLI/test fixtures; that object is never accepted from request fields, query parameters or
environment switches. Someone executing privileged Python or editing SQLite remains an
OS/server administrator outside the browser-user boundary.

Corrections retain original OCR and pinned policy versions. Nonadministrators cannot
supply forged OCR or switch policy versions. Invalid correction evidence prevents PO
comparison from revealing unrelated PO details. Schema, evidence, contract, anomaly and
routing checks remain deterministic; the policy engine itself is privileged computation.

## Downloads, storage, external AI and retention

The FastAPI adapter issues 30-second, single-use random download grants bound to
hashed auth sessions and the requesting browser session.
Redemption checks expiration/replay, live session/account, current role and document scope,
then generates the current export or reads a server-stored source. Caller-supplied paths,
hashes and document links are ignored: source metadata is fetched by item ID. Resolved
containment, symlink checks, size bounds and SHA-256 integrity are checked before bytes
are served. Responses use no-store, nosniff, no-referrer and attachment disposition;
request URLs are never logged. Expired, revoked and replayed grants return generic 403.
An administrator and authorized reviewers can export only their current document scope;
manager JSON contains summary-only authorized aggregates; auditors have no sensitive
exports. Downloaded files already legitimately received remain outside server revocation.

The React application and protected download endpoints share loopback HTTP on port
8000 by default (`IDP_WEB_PORT` selects another port). The download service's auxiliary
local HTTP adapter remains available to existing service tests and compatibility
clients; it is not required to run the React application. Grant material must never
be shared or logged. Public deployment requires TLS, hardened transport and abuse
limits. Windows account permissions/BitLocker or equivalent must protect SQLite,
backups and retained files; application RBAC does not encrypt them.

Existing signature/byte/page/pixel/archive limits are retained. Files are bounded
to 20 MB each, 50 files and 100 MB total per submission. FastAPI checks bounded
request lengths and same-origin mutations; invalid files fail before OCR. Intake is
administrator-only: classification cannot be used to turn a departmental upload into a
cross-department discovery channel. Single/batch service entrypoints require explicit
external Groq consent; local CLI workers are privileged operator commands. Classification
omits recognized financial identifier patterns, while extraction receives supported,
bounded OCR necessary for requested fields/evidence. OCR is wrapped as untrusted data,
never executable instructions. Instruction-like content conservatively causes a high-risk
review signal. This heuristic is not complete prompt-injection detection or a calibrated
model; unchanged evidence/validation/routing checks remain the final protection. Provider
failures remain bounded and sanitized; session credentials are never sent to the model.

Retention is conservative: there is no automatic deletion. Original/model/audit rows are
never deleted. Sources linked to documents, active cases, processing originals, review
events or dependent invoices remain preserved. Only expired, unlinked failed sources
with all five retry attempts exhausted are candidates for explicit administrator cleanup.
Containment/hash checks precede nonrecursive deletion; case/attempt/audit rows remain.
File deletion and SQLite commit are not a single atomic filesystem transaction; storage
failure during cleanup is a residual risk. Legal-hold/retention lifecycle administration
and encrypted archives are deferred.

## Audit and additive migration

security-v1 creates users, auth_sessions, login_limits, security_events, event_identities
and download_grants plus indexes and append-only security/identity triggers. Populated
databases receive a consistent DATABASE.before_security_v1.TIMESTAMP.db backup. Existing
document, processing, policy and review tables/values are not rewritten. Earlier missing
batch/review/policy migrations still run in order, each with its own backup. No historical
actor is relabeled as authenticated. New event_identities rows link authenticated review,
draft and activation events to immutable user IDs; review actor_kind distinguishes
authenticated_user, prototype_operator and system. Human correction provenance identifies
authenticated account IDs. Intervention analytics counts both historical prototype and
new authenticated events without fabricating missing historical measurements.

Security events record successful/failed login, logout, denied operations, forged actors,
account changes, policy changes, blocked approval and sensitive exports/downloads, using
safe event metadata only. Passwords, raw session/grant tokens, API keys and OCR are never
written to that log. Events can be read by administrators. SQLite triggers prevent normal
updates/deletes; filesystem/SQL administrators can still alter schema/data. Audit history
is not cryptographically tamper-proof or certified compliant.

## Verification and remaining limits

Run through Python 3.14.6 and uv:

```
uv run --python 3.14.6 python scripts/run_tests.py
uv run --python 3.14.6 python -m unittest discover -s tests -v
```

Earlier regression fixtures/local evaluation workers now use an explicit privileged
server capability. Their processing assertions remain unchanged; authenticated tests
separately exercise default-deny repository contexts and backend permissions. Browser
UAT uses isolated synthetic documents/accounts, not production data or live Groq. Exact
executed totals, browser evidence, failures/unverified items and original-copy migration
results are reported under results/milestone6_20261014/; generated files remain ignored.

Residual risks: no MFA/OIDC, public TLS deployment, distributed throttling, disk encryption,
cryptographic audit, antivirus/sandboxed parser, full prompt-injection detection, password
recovery, legal holds or production certification. Uploaded parser code runs in-process
under bounded size/dimension rules. Secure Windows permissions, trusted local machine and
patched dependencies remain essential. Document data already rendered in the browser or
downloaded cannot be recalled on logout/deactivation. No public deployment occurred.
