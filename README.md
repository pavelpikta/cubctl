# cubctl

CLI and Python library for the [CUB REST API](https://cub.rip/developer/) (cub.rip).

## Quick start

```bash
pip install cubctl
cubctl --help
```

Development install from this repo:

```bash
pip install -e ".[dev]"
cubctl --help
# or: python -m cubctl --help
```

The package lives under `src/cubctl/`. From the repo root, `cubctl` is available after `pip install -e .` (or `PYTHONPATH=src python -m cubctl`).

## Concepts (AWS-style)

| Term | CLI flag | Config | Description |
|------|----------|--------|-------------|
| **Account slot** | `--account src\|target` | `account_src` / `account_target` | Saved API token + default profile ID (like AWS named profiles, fixed as `src` and `target` for migrations) |
| **CUB profile** | `--profile ID` | per-slot `profile` field | User profile within an account (Pavel, DEVOPS, …). Many commands need an explicit profile ID |

Credential chain (highest priority first):

1. `--account src|target` (+ optional `--profile` override)
2. `--token` (+ optional `--profile`)
3. `CUB_TOKEN` / `CUB_PROFILE` environment variables
4. Default slot: `CUB_ACCOUNT` env or `account_src`

Global flags (before or after the subcommand):

```bash
cubctl --account src --profile 311483 bookmarks all --type book
cubctl bookmarks all --account src --profile 311483 --type book
```

## Install

```bash
pip install cubctl
pip install "cubctl[test]"   # optional: pytest for running tests
```

From source:

```bash
pip install -e ".[dev]"
cubctl --help
```

## Authentication (device/add)

CUB uses **device-based login** — the same flow as Lampa:

1. Open [cub.rip/add](https://cub.rip/add) while logged in to your CUB account
2. Copy the **6-digit code** shown on the page
3. Exchange it for a token via `POST device/add`

```bash
cubctl device add 123456 --save   # saves to src account slot in config
cubctl auth 123456 --save         # alias; prefer accounts setup for src + target
```

For **src + target** account slots:

```bash
cubctl accounts setup   # reads accounts.env in repo root
cubctl accounts show
```

Credentials live in **`~/.cub/config.json`** — account tokens, default slot, and saved profile names. Manage with `cubctl config`:

```bash
cubctl config show                              # accounts + profiles (no tokens)
cubctl config path
cubctl config set default-account src
cubctl config profile sync --account src        # fetch profile names from API → config
cubctl config profile list --account src
cubctl config profile set --account src --name Pavel --id 311483
cubctl config profile default --account src --name Pavel
cubctl bookmarks all --account src --profile Pavel   # name resolved from config
```

Example `~/.cub/config.json`:

```json
{
  "default_account": "src",
  "account_src": {
    "token": "...",
    "profile": "311483",
    "email": "user@example.com",
    "profiles": {
      "Pavel": "311483",
      "Kids": "311484"
    }
  },
  "account_target": {
    "token": "...",
    "profile": "796529",
    "profiles": { "Main": "796529" }
  }
}
```

The client sends these headers on every authenticated request:

| Header    | Purpose                          |
|-----------|----------------------------------|
| `token`   | API access token (required)      |
| `profile` | Profile ID (required for some)   |

## Environment variables

| Variable           | Description                              | Default                |
|--------------------|------------------------------------------|------------------------|
| `CUB_TOKEN`        | API token                                | —                      |
| `CUB_PROFILE`      | CUB profile ID                           | —                      |
| `CUB_ACCOUNT`      | Default account slot: `src` or `target`  | `src` when configured  |
| `CUB_CODE_SRC`     | Device code for src slot (setup)         | —                      |
| `CUB_CODE_TARGET`  | Device code for target slot (setup)      | —                      |
| `CUB_FROM_TOKEN`   | Source token for migration               | —                      |
| `CUB_TO_TOKEN`     | Target token for migration               | —                      |
| `CUB_BASE_URL`     | API base URL                             | `https://cub.rip/api/` |
| `CUB_CONFIG_DIR`   | Config directory                         | `~/.cub`               |

`accounts.env` is auto-loaded at startup when present (see `accounts.env.example`).

## Public vs authenticated commands

These work **without** a token:

```bash
cubctl collections top-collectors
cubctl collections list --category new
cubctl collections roll
cubctl collections view 123
cubctl reactions get movie_539972
cubctl reactions add movie_539972 think
cubctl users find --email user@example.com
```

All other subcommands require `--account src|target`, `--token`, or `accounts setup`.

### Credential resolution

Every authenticated subcommand accepts:

| Flag | Env | Config |
|------|-----|--------|
| `--account src\|target` | `CUB_ACCOUNT` | `account_src` / `account_target` |
| `--token` | `CUB_TOKEN` | — (explicit override only) |
| `--profile` | `CUB_PROFILE` | slot `profile` or `profiles` map |

Order: `--account` → explicit `--token` → `account_src` → error with setup hint.

## Profiles

List and resolve CUB profile IDs by name:

```bash
cubctl profiles all --account src
cubctl profiles pick --account src --name Pavel
cubctl profiles pick --account target --name DEVOPS
```

Use the returned `id` with `--profile` or `--from-profile` / `--to-profile`.

## Bookmarks

The API has **documented filter types** (`book`, `history`, `like`, `wath`) and **internal types** returned with `--full 1` (`viewed`, `scheduled`, `look`, `thrown`, …).

```bash
# Category counts (matches Lampa UI totals)
cubctl bookmarks counts --account src --profile 311483

# List by type
cubctl bookmarks all --account src --profile 311483 --type history

# All internal types (~400 items)
cubctl bookmarks all --account src --profile 311483 --full 1
```

## Premium

Timeline endpoints require [CUB Premium](https://cub.rip/premium): `timeline/all`, `changelog`, `dump`, `update`.

## Backup (JSON v2)

Full profile snapshot including all bookmark internal types, timeline, and optional notifications.

```bash
cubctl backup create --account src --profile 311483
cubctl backup restore --account target --profile 796529 -i backup.json --dry-run
cubctl backup restore --account target --profile 796529 -i backup.json
```

Equivalent: `migrate export` / `migrate import` (same JSON format).

## Account slots (src / target)

```bash
cp accounts.env.example accounts.env
# edit CUB_CODE_SRC, CUB_CODE_TARGET, optional CUB_ACCOUNT=src
cubctl accounts setup
```

```bash
cubctl bookmarks all --account src --type book
cubctl migrate run \
  --from src --from-profile 311483 \
  --to target --to-profile 796529 \
  --dry-run
```

## Migration

Copy **all bookmark types** + timeline (+ optional notifications) between profiles or account slots.

**Always specify profile IDs** — saved slots store the main profile from login, not named profiles like Pavel.

```bash
# Preview
cubctl migrate run \
  --from src --from-profile 311483 \
  --to target --to-profile 796529 \
  --dry-run

# Run with progress
cubctl migrate run \
  --from src --from-profile 311483 \
  --to target --to-profile 796529 \
  --include bookmarks,timeline,notifications \
  --progress

# Export / import (offline)
cubctl migrate export --from src --from-profile 311483 -o pavel.json
cubctl migrate import --to target --to-profile 796529 -i pavel.json --progress
```

| Flag | Description |
|------|-------------|
| `--from` / `--to` | Account slot: `src` or `target` |
| `--from-profile` / `--to-profile` | CUB profile ID within each slot |
| `--include bookmarks,timeline,notifications` | What to migrate |
| `--merge skip` | Skip existing items (default) |
| `--merge overwrite` | Overwrite timeline entries |
| `--dry-run` | Counts only, no writes |
| `--progress` | Print each import step to stderr |
| `--quiet` | Compact JSON (export: summary only) |
| `--delay SECS` | Pause between API writes (rate limiting) |

Same account slot, two CUB profiles (one token):

```bash
cubctl migrate run --from-profile 311484 --to-profile 311483 --dry-run
```

## Security notes

- Tokens are stored in plain text in `~/.cub/config.json` (local CLI tool).
- `users give --password` passes the password on the command line (visible in shell history). Prefer env vars in scripts.

## Tests

```bash
pip install -e ".[test]"
pytest tests/test_unit.py tests/test_migration.py tests/test_cli.py -m "not integration"
pytest tests -m integration   # live API; needs CUB_TEST_DEVICE_CODE
```

## Project layout

```
lampa-cub-cli/
├── README.md
├── pyproject.toml
├── requirements.txt
├── accounts.env.example
├── tests/
└── src/cubctl/
    ├── cli.py           # command dispatch
    ├── cli_helpers.py   # auth resolution, progress, public commands
    ├── client.py
    ├── migration.py
    └── api_spec.json
```

```bash
pip install -e ".[dev]" && cubctl --help
```

## Publish to PyPI

### Recommended: Trusted Publisher (no long-lived token)

PyPI exchanges a short-lived token with GitHub via OIDC. You do **not** need `PYPI_API_TOKEN` in GitHub Secrets when this is configured.

**1. PyPI** — [Account → Publishing](https://pypi.org/manage/account/publishing/) (or project → Publishing after the first release)

Add a **GitHub** trusted publisher:

| Field | Value |
|-------|--------|
| Owner | `pavelpikta` |
| Repository | `lampa-cub-cli` |
| Workflow name | `publish.yml` |
| Environment | `pypi` *(optional but matches this repo’s workflow)* |

For the **first upload**, you can add a [pending publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/) before the `cubctl` project exists on PyPI.

**2. GitHub** — repo [Settings → Environments](https://github.com/pavelpikta/lampa-cub-cli/settings/environments)

Create environment **`pypi`** (optional protections: required reviewers, branch rules).

No repository secret is required for trusted publishing.

**3. Release**

```bash
git tag v1.0.0
git push origin v1.0.0
# GitHub → Releases → Draft new release from tag v1.0.0 → Publish
```

Or run **Actions → publish → Run workflow** manually.

The workflow uses [`pypa/gh-action-pypi-publish`](https://github.com/marketplace/actions/pypi-publish) with `id-token: write` (see `.github/workflows/publish.yml`).

### Alternative: API token + secret

If you prefer a classic token instead of trusted publishing:

1. PyPI → Account settings → API tokens → create token (scope: entire account or project `cubctl`)
2. GitHub → Settings → Secrets and variables → Actions → **`PYPI_API_TOKEN`**
3. Replace the publish step in `publish.yml` with:

```yaml
      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: twine upload dist/*
```

Remove `id-token: write` if you use only the token method.

### Manual upload (local)

```bash
pip install build twine
python -m build
twine check dist/*
twine upload dist/*
# Username: __token__  Password: pypi-Ag... (API token)
```
