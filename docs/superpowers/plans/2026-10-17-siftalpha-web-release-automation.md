# SiftAlpha Web Release Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build reproducible ARM64 website images from the user-approved SiftAlpha release branch and establish a least-privilege, digest-only deployment interface without replacing the live website during implementation.

**Architecture:** The release branch first makes the currently deployed hybrid runtime reproducible by adding only Task 009's non-business production runtime layer to the accepted `ebd23f4…` website tree. A GitHub Actions push workflow then tests and publishes ARM64 GHCR images with provenance metadata. A root-owned, fixed-target web-admin tool manages only the SiftAlpha web service through an adopted Compose definition, while `rdc-agent` retains no Docker Socket access.

**Tech Stack:** Django 5.2, Vue/Vite, Docker Buildx, GitHub Actions, GHCR, Docker Compose v5, Bash, Python stdlib `sqlite3`, Oracle Cloud Ubuntu ARM64.

**Spec:** `docs/superpowers/specs/2026-10-17-siftalpha-web-release-automation-design.md`

## Global Constraints

- Work only on `release/siftalpha-web-v1`, the user-approved exception to the normal latest-`main` branch rule; retain `ebd23f4248219fb70fe457ac800d5603fbf47ef1` as the business-code baseline.
- Do not merge, update, close, or rebase any existing PR; do not modify `main`.
- Do not modify website business logic, trading logic, market providers, indicators, Chan.py, private Formula source, UI behavior, Cloudflare, Crypto, Coolify, VPN, Agent, or unrelated containers.
- Preserve `longbridge==5.2.0`; append only the production runtime dependencies required for Gunicorn/WhiteNoise, never copy Task 009's obsolete `longbridge==0.2.74` pin.
- GitHub Actions first phase builds automatically only after a push to `release/siftalpha-web-v1`; do not rely on `workflow_dispatch` while the workflow is absent from the default branch.
- Use `ghcr.io/kuashan/siftalpha-web@sha256:<digest>` for all deployment candidates; never deploy `latest` or a mutable tag.
- Never include secrets, Docker credentials, database contents, Formula source, tokens, sessions, or production environment files in Git or command output.
- `rdc-agent` must remain outside the Docker group and unable to access `/var/run/docker.sock`; it may invoke only `/usr/local/sbin/siftalpha-web-admin` through sudo.
- No actual production website replacement, Compose cutover, database migration, Cloudflare change, or real rollback is permitted during this implementation. The first cutover needs separate user authorization.

## Review Focus

1. A source commit that has the website business tree but lacks the Task 009 runtime files must fail the parity contract rather than silently building a different runtime; Task 1 owns this test.
2. A mutable tag, another GHCR repository, malformed digest, non-ARM64 manifest, or OCI revision that differs from the supplied build record must be rejected before deployment; Tasks 2 and 3 own these tests.
3. An SQLite backup that passes an integrity check but cannot be restored must fail preflight; Task 3 restores it into a root-only temporary database and checks it again.
4. A first Compose migration whose health probe fails must retain and restart the original `docker run` container with its original local image, configuration, and data volume; Task 3 owns the isolated Docker contract test.
5. A caller that supplies an extra command, path, image name, environment variable, or direct Docker command must not gain broader host control; Tasks 3 and 4 pin the strict parser and Socket-denial checks.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `.dockerignore` | Exclude local databases, media, logs, backups, environments, and Node/Python build state from image context. |
| `deployment/web/Dockerfile` | Reproducible Linux ARM64-compatible website build; no runtime secrets or migrations. |
| `docker/healthcheck.py` | Local, data-free container health probe for `/healthz/`. |
| `quant_site/settings.py` | Task 009 production settings semantics only: environment-driven debug/hosts/database/static/HTTPS policy and WhiteNoise. |
| `quant_site/urls.py`, `core/views.py` | Minimal data-free `/healthz/` route used only by operational checks. |
| `requirements.txt` | Retain existing dependencies, append Gunicorn and WhiteNoise only. |
| `core/test_deployment.py` | Django contracts for production settings, static assets, health and formula runtime prerequisites. |
| `.github/workflows/siftalpha-web-arm64.yml` | Release-branch push CI, ARM64 GHCR build, provenance and immutable build record. |
| `scripts/verify_web_release_workflow.py` | Deterministic source-contract checker for workflow trigger, permissions, tags, labels and non-deploy boundary. |
| `deployment/web-admin/siftalpha-web-admin` | Root-only fixed-target command dispatcher; no arbitrary Docker/shell interface. |
| `deployment/web-admin/lib/siftalpha-web-admin-lib.sh` | Testable command, digest, backup, snapshot, health and rollback functions. |
| `deployment/web-admin/compose.yaml.template` | Fixed website Compose definition used only after root-owned adoption; no secrets. |
| `deployment/web-admin/siftalpha-web-admin.conf.example` | Non-secret fixed-target configuration schema and exact path/permission documentation. |
| `deployment/web-admin/rdc-agent-sudoers` | One-command sudoers template for the web-admin tool. |
| `deployment/web-admin/install-web-admin.sh` | Root-run installer with explicit `--check` and `--install` modes; never starts/replaces the website. |
| `deployment/web-admin/tests/test_web_admin.sh` | Linux fake-Docker contract test for parser, backup/restore, preflight and legacy rollback paths. |
| `docs/operations/siftalpha-web-releases.md` | Operator/Work runbook: candidate verification, user approval, preflight, deploy, rollback, boundaries and evidence. |

### Task 1: Make the accepted website runtime reproducible without changing business behavior

**Files:**
- Create: `.dockerignore`, `deployment/web/Dockerfile`, `docker/healthcheck.py`, `core/test_deployment.py`
- Modify: `requirements.txt`, `quant_site/settings.py`, `quant_site/urls.py`, `core/views.py`, `.env.example`
- Reference source only: `e6bbbf7f42edc36b1c58cfd0a414e429e30cf503` for Task 009 deployment semantics

**Interfaces:**
- Consumes: accepted website tree `ebd23f4…`; Task 009's environment-variable names and healthcheck semantics.
- Produces: `GET /healthz/ -> {"status": "ok"}`, environment-driven production settings, and `deployment/web/Dockerfile` runnable with `/data` mounted and no database migration command.

- [ ] **Step 1: Write the parity and production-runtime Django contract tests**

Add `core/test_deployment.py` tests that assert: `DJANGO_DEBUG=0` requires explicit allowed hosts; `/healthz/` is public and returns exactly `{"status": "ok"}`; `VITE_APP_BASE_URL` production assets remain under `/static/`; the Dockerfile contains Gunicorn, one worker, Node runtime and no `migrate`; production settings contain the documented environment keys; and Formula execution still has Node available.

- [ ] **Step 2: Run the new contract tests and verify they fail on the current release baseline**

Run: `python manage.py test core.test_deployment -v 2`

Expected: FAIL because the `ebd23f4…` tree lacks the production runtime/healthcheck files and environment-driven production settings.

- [ ] **Step 3: Add only the Task 009 production runtime layer**

Port Task 009's production settings helpers, WhiteNoise middleware, `/healthz/` view/route, healthcheck and multi-stage Docker shape. Keep all existing `ebd23f4…` application routes and code. Append `gunicorn==23.0.0` and `whitenoise==6.9.0` to `requirements.txt`; retain `longbridge==5.2.0`. Add a `.dockerignore` that excludes every ignored private/runtime category, including database files, local backups, media, logs, `.env*`, Node modules, Vite output, Python caches and private keys.

- [ ] **Step 4: Run targeted regression and build checks**

Run:

```powershell
python manage.py check
python manage.py test core.test_deployment -v 2
python manage.py makemigrations --check
Push-Location frontend; npm ci; npm run build; Pop-Location
git diff --check
```

Expected: checks pass; `makemigrations --check` reports no changes; no database is written or added to Git.

- [ ] **Step 5: Commit the reproducible runtime layer**

```powershell
git add .dockerignore deployment/web/Dockerfile docker/healthcheck.py requirements.txt quant_site/settings.py quant_site/urls.py core/views.py core/test_deployment.py .env.example
git commit -m "build: make SiftAlpha web runtime reproducible"
```

### Task 2: Add the release-branch ARM64 GHCR build pipeline and traceable provenance

**Files:**
- Create: `.github/workflows/siftalpha-web-arm64.yml`, `scripts/verify_web_release_workflow.py`
- Modify: `core/test_deployment.py`

**Interfaces:**
- Consumes: Task 1 Dockerfile and health endpoint.
- Produces: a GitHub Actions run on `push` to `release/siftalpha-web-v1`, with `IMAGE`, `DIGEST`, `SOURCE_COMMIT`, `RUN_ID`, `RUN_URL`, `PLATFORM=linux/arm64` and attestation metadata in its summary/manifest artifact.

- [ ] **Step 1: Write workflow source-contract tests**

Extend `core/test_deployment.py` and implement `scripts/verify_web_release_workflow.py` to assert that the workflow: triggers only from `push` to `release/siftalpha-web-v1` in phase one; has no deploy/SSH/server steps; uses Buildx with `linux/arm64`; uses `packages: write`, `attestations: write`, and `id-token: write`; publishes only `ghcr.io/kuashan/siftalpha-web`; emits full SHA tags but records a Digest; attaches OCI source/revision/version/run-id/ref labels; produces provenance; and does not use `latest`.

- [ ] **Step 2: Run workflow contract checks and verify they fail before the workflow exists**

Run: `python scripts/verify_web_release_workflow.py`

Expected: FAIL because `.github/workflows/siftalpha-web-arm64.yml` is absent.

- [ ] **Step 3: Implement the phase-one push workflow**

Create the workflow with checkout, Python/Django checks, Node `npm ci`/build/tests, Buildx ARM64 build/push and GitHub provenance attestation. Do not add `workflow_dispatch` in this phase. Supply labels derived from `github.sha`, `github.run_id`, `github.server_url`, `github.repository`, `github.workflow`, `github.ref_name` and the fixed V1.0.0 version. Upload a JSON build-manifest artifact containing exactly the image repository, Digest, full commit SHA, Run ID, Run URL, ref and platform; write the same non-secret facts to `$GITHUB_STEP_SUMMARY`.

- [ ] **Step 4: Verify static workflow contracts locally**

Run:

```powershell
python scripts/verify_web_release_workflow.py
python manage.py test core.test_deployment -v 2
git diff --check
```

Expected: PASS; workflow has no server credential, deployment, Cloudflare or database action.

- [ ] **Step 5: Commit the build pipeline**

```powershell
git add .github/workflows/siftalpha-web-arm64.yml scripts/verify_web_release_workflow.py core/test_deployment.py
git commit -m "ci: build SiftAlpha web ARM64 release images"
```

### Task 3: Implement and test the fixed-target web-admin control plane

**Files:**
- Create: `deployment/web-admin/siftalpha-web-admin`, `deployment/web-admin/lib/siftalpha-web-admin-lib.sh`, `deployment/web-admin/compose.yaml.template`, `deployment/web-admin/siftalpha-web-admin.conf.example`, `deployment/web-admin/rdc-agent-sudoers`, `deployment/web-admin/install-web-admin.sh`, `deployment/web-admin/tests/test_web_admin.sh`

**Interfaces:**
- Consumes: `deploy sha256:<64 lowercase hex>` candidate identity from Task 2 and root-only server configuration constants.
- Produces: `/usr/local/sbin/siftalpha-web-admin {status|health|preflight|deploy|rollback}` after later root installation; it returns only sanitized status/backup metadata and exits nonzero on every invalid precondition.

- [ ] **Step 1: Write fake-Docker and SQLite contract tests**

Create `deployment/web-admin/tests/test_web_admin.sh` for Ubuntu/GitHub Actions. With a fake Docker/Compose/Curl command path and temporary root-like directories, test: allowed commands parse; extra arguments and bad digests reject; an external repository/tag cannot reach a Docker invocation; direct environment override cannot change configured paths; valid preflight verifies ARM64 and matching OCI source/revision/run-id fields; backup copies a SQLite fixture via Python `sqlite3.Connection.backup()`; restore-check opens a separate restored fixture and passes integrity; backup failure removes `.partial`; and failed first adoption restores the retained legacy container without deleting its data bind.

- [ ] **Step 2: Run the shell contract test and verify it fails before the tool exists**

Run: `bash deployment/web-admin/tests/test_web_admin.sh`

Expected: FAIL because the tool/library/config template is absent.

- [ ] **Step 3: Implement the root-owned fixed-target tool and templates**

Implement a small Bash dispatcher that sources only `/etc/siftalpha-web-admin.conf`, sets a fixed PATH and umask, and invokes Docker with argument arrays. Its parser accepts only `status`, `health`, `preflight <digest>`, `deploy <digest>` and `rollback`; digest matching is exactly `^sha256:[0-9a-f]{64}$`. The configuration fixes `IMAGE_REPOSITORY=ghcr.io/kuashan/siftalpha-web`, the production data bind, `127.0.0.1:19091`, container names, backup/rollback directories and root env-file path; no caller-provided configuration is accepted.

Implement preflight label/architecture/disk/health/data checks and root-only temporary backup/restore verification. Implement deployment snapshots that preserve the original legacy `docker run` container and local image. On first Compose cutover failure, stop/remove only the candidate Compose container and restart that untouched legacy container. Never run migrations, cleanup, or volume deletion. The installer must create files with the modes specified by the design, run `visudo -cf` on the staged sudoers file, and have a `--check` mode that does not change server state.

- [ ] **Step 4: Run Linux tool tests and static safety scan**

Run:

```bash
bash deployment/web-admin/tests/test_web_admin.sh
grep -RInE 'eval|docker[[:space:]]+system[[:space:]]+prune|rm[[:space:]]+-rf|docker[[:space:]]+sock' deployment/web-admin
```

Expected: test PASS; scan finds no executable use of `eval`, Docker prune, recursive deletion or Socket permission grant. A matching explanatory comment is acceptable only if the test makes it non-executable.

- [ ] **Step 5: Commit the controlled deployment interface**

```powershell
git add deployment/web-admin
git commit -m "ops: add least-privilege SiftAlpha web admin tool"
```

### Task 4: Document, build, and perform non-disruptive isolated acceptance

**Files:**
- Create: `docs/operations/siftalpha-web-releases.md`
- Modify: `docs/superpowers/specs/2026-10-17-siftalpha-web-release-automation-design.md`

**Interfaces:**
- Consumes: Tasks 1–3, GitHub Actions digest/build manifest, and the fixed `siftalpha-web-admin` CLI.
- Produces: an evidence-backed operational runbook and non-disruptive acceptance report; no website deployment.

- [ ] **Step 1: Write the runbook and its source-contract test**

Document the exact future sequence: retrieve successful run metadata; compare user-supplied Digest with manifest/summary/OCI labels/provenance; obtain separate user deployment approval; run preflight; record backup/snapshot; deploy; run health; perform user browser acceptance; use rollback only with separate approval. Document first-adoption legacy rollback and explicitly state that no migration or database restore is automatic. Add a source contract in `core/test_deployment.py` that requires these safety words/commands and bans `latest` deployment examples.

- [ ] **Step 2: Run all local regression checks**

Run:

```powershell
python manage.py check
python manage.py test core
python manage.py makemigrations --check
Push-Location frontend; npm ci; npm run test:indicators; npm run test:realtime; npm run test:chart; npm run build; Pop-Location
git diff --check
```

Expected: all checks pass; no new migration; Git status contains no database, backup, log, credential or Formula export.

- [ ] **Step 3: Push the release branch and obtain the real ARM64 build evidence**

Run: `git push origin release/siftalpha-web-v1`

Expected: the release-branch push starts `SiftAlpha Web CI and ARM64`; record its actual successful Run ID, full source commit, GHCR image address and immutable Digest. A failed build stops this plan before any server-side installation.

- [ ] **Step 4: Install only the management capability and validate it without a website cutover**

On Oracle, after user approval for this implementation phase, install the root-owned tool/config/templates with the existing website configuration manually verified. Do not call `deploy` or `rollback`. Verify: modes/owners and `visudo -cf`; `rdc-agent` can call web-admin `status` and `health`; `rdc-agent docker ps` remains denied; malformed/foreign Digest preflight rejects; valid built Digest preflight verifies architecture, labels and root-only backup/restore check; before/after inventories prove SiftAlpha website, Crypto, Options Monitor, Cloudflare and all other containers remained running and unchanged.

- [ ] **Step 5: Commit documentation and implementation evidence**

```powershell
git add docs/operations/siftalpha-web-releases.md docs/superpowers/specs/2026-10-17-siftalpha-web-release-automation-design.md core/test_deployment.py
git commit -m "docs: document SiftAlpha web release operations"
git push origin release/siftalpha-web-v1
```

Record server-only evidence in the completion report, not in Git: root-only file paths/modes, test result, current website container identity, Actions Run ID, commit, image Digest, preflight result, and confirmation that no deployment occurred.

## Final Verification Checklist

- [ ] `git diff --check` passes.
- [ ] `python manage.py check` passes.
- [ ] `python manage.py test core` passes.
- [ ] `python manage.py makemigrations --check` reports no changes.
- [ ] `npm ci`, all three existing frontend test scripts and `npm run build` pass.
- [ ] GitHub Actions produces one actual successful `linux/arm64` GHCR image with full Commit, Run ID/URL, Digest, labels and provenance.
- [ ] `rdc-agent` can call only the website admin tool; direct Docker Socket access remains denied.
- [ ] Valid/invalid preflight and SQLite backup/restore checks pass without a website restart.
- [ ] No production container replacement, database migration, actual rollback, Cloudflare change, Crypto change, or business-code change occurred.
