# diary-app

Family diary backend: weekly meal plans, shopping lists and per-person
calendars, shown on an iPad. This repo is currently a **spike**: a
hello-world FastAPI app used to prove the deployment pipeline.

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

One-time setup (as root in the LXC; `<...>` values are yours to fill in):

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
$EDITOR /etc/diary-app/diary-app.env              # set the real API_KEY

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

Secrets live in `/etc/diary-app/diary-app.env` (mode `0640`, `root:diary`),
loaded by systemd's `EnvironmentFile=`. The file is outside the git checkout,
so deploys never overwrite it. To rotate: edit the file, then
`systemctl restart diary-app`. The app fails to start if `API_KEY` is
missing, and `GET /config-check` reports whether it is set without ever
returning the value.
