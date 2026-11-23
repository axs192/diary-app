# diary-app

Family diary backend: weekly meal plans, shopping lists and per-person
calendars, shown on an iPad. This repo is currently a **spike**: a
hello-world FastAPI app used to prove the deployment pipeline.

## Licence

GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`); see
[LICENSE](LICENSE). The licence covers the code only. See
[NOTICE](NOTICE) for third-party content (including recipes imported from
sites such as BBC Good Food, which stay the property of their owners).

## Local development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env            # dummy values only; .env is git-ignored
uv run --env-file .env uvicorn --factory diary_app.app:create_app --reload
```

Checks (also run in CI):

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run bandit -q -r src
uv run python -m unittest
```

Code follows the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html),
enforced by ruff.

## Deploying to a Proxmox LXC

One-time setup, as root in the LXC.

First, create a normal admin account so day-to-day work (including deploys)
doesn't happen as root. Debian LXC templates often omit `sudo`:

```bash
apt update && apt install -y sudo
adduser admin                  # prompts for a password; pick any username
usermod -aG sudo admin
```

Then log in as `admin` and run the rest with `sudo -i` (or stay as root):

```bash
apt install -y git curl
# uv into /usr/local/bin so the service user can run it too
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

# System account with no password or login shell; home holds uv's cache
adduser --system --group --home /var/lib/diary --shell /usr/sbin/nologin diary

# Clone as the service user so file ownership is right from the start
install -d -o diary -g diary /opt/diary-app
runuser -u diary -- git clone https://github.com/axs192/diary-app /opt/diary-app

install -d -m 0750 -o root -g diary /etc/diary-app
install -m 0640 -o root -g diary /opt/diary-app/deploy/diary-app.env.example /etc/diary-app/diary-app.env
/opt/diary-app/deploy/creds.sh household_pin      # the PIN you'll type on each device
/opt/diary-app/deploy/creds.sh session_secret --generate   # signs the login cookie

cp /opt/diary-app/deploy/diary-app.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now diary-app
```

Each deploy:

```bash
sudo /opt/diary-app/deploy/deploy.sh
```

This fetches `origin/main`, hard-resets the checkout, runs `uv sync --frozen
--no-dev`, restarts the service and polls `/health`.

### Credentials

Secrets are [systemd credentials](docs/systemd-credentials.md): encrypted
files in `/etc/diary-app/creds/` (outside the git checkout, so deploys never
touch them), decrypted by systemd into a private directory only the service
can see. Create or rotate one with `sudo deploy/creds.sh <name> [--force]`,
then `systemctl restart diary-app`. The app fails to start if `household_pin`
or `session_secret` is missing, and `GET /config-check` reports whether it is set without ever
returning the value. Non-secret settings stay in
`/etc/diary-app/diary-app.env`. **Upgrading an existing install?** Follow
the step-by-step guide in [docs/systemd-credentials.md](docs/systemd-credentials.md).

Local development still uses a git-ignored `.env` file (dummy values only).
