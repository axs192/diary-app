# diary-app

Family diary: weekly meal plans, a recipe library (with import from a few
allowed sites) and, later, shopping lists and per-person calendars. It is a
server-rendered FastAPI app behind a household PIN, built for a kitchen iPad
and also usable from phones. See [Installing on the iPad](#installing-on-the-ipad).

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

### Testing an unmerged branch on the LXC

`deploy.sh` always resets to `origin/main`. To try a branch on the iPad, run
git as the service user (the checkout belongs to `diary`; running git as
root fails with "dubious ownership"), then restart:

```bash
runuser -u diary -- git -C /opt/diary-app fetch origin <branch>
runuser -u diary -- git -C /opt/diary-app reset --hard origin/<branch>
systemctl restart diary-app
```

Run `sudo /opt/diary-app/deploy/deploy.sh` afterwards to return to `main`.
Force-close the Home Screen app on the iPad so it does not show a cached page.

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

## Installing on the iPad

The main display is a 1st-generation iPad mini (iOS 9.3.5, Mobile Safari 9)
left on in the kitchen.

1. Open the app's address in **Safari** and log in with the household PIN.
2. Tap Share, then **Add to Home Screen**, and open it from the new icon. It
   runs full screen with no address bar. Log in again inside this Home Screen
   app: iOS 9 can keep a separate cookie jar from Safari.
3. Settings > Display & Brightness > **Auto-Lock: Never**, and keep the iPad
   on a charger.
4. Settings > General > Accessibility > **Guided Access**: turn it on, set a
   passcode, then triple-click the Home button inside the app to start it.

**Why the app ships one script.** In an iOS 9 Home Screen app, tapping a plain
link opens Safari, and Guided Access blocks leaving the app, so taps appeared
dead. `src/diary_app/web/static/app.js` (loaded on every page) intercepts
clicks on same-origin links and navigates in place; external links are left
alone. Forms are plain `POST` then `303` redirects, which stay inside the app.

## Self-healing (24/7 display)

`app.js` keeps the kitchen display usable without anyone touching it:

- **Reconnecting.** Every 30 seconds it asks `/health` (using
  `XMLHttpRequest`). If that fails or times out, a full-screen
  "Reconnecting…" screen covers the page and it keeps asking every 30 seconds,
  then reloads the page once the server answers. Safari's own error page is
  never left on screen.
- **Scheduled reload.** The page reloads 6 hours after it loaded, or at 3 am
  local time if that comes first, to shed any memory built up. A reload waits
  while someone has been typing in the last 5 minutes, and until the server is
  reachable.
- **Error banner.** A script error shows a small dismissible banner (message,
  file and line), because the iPad has no Web Inspector. Set
  `ERROR_BANNER=false` in `/etc/diary-app/diary-app.env` (then restart the
  service) to hide it.

- **Meals tabs.** Ideas / Favourites / My meals at the bottom of the Meals
  page are real links, so they work with no script. With `app.js` they fetch
  just the list from `GET /meals/library` (same query as the page, shared in
  `meals._library_context`) and swap it in place, so a tab tap is not a page
  load. If the fetch fails, the tab falls back to a normal page load. Note the
  list is most of the page's weight, so this removes the navigation (and the
  black backdrop it flashed on the iPad), not the cost of drawing the list.
  If a large library still feels slow, paginate the list.

Not yet done: saving UI state in `localStorage`. There is no client-side state
worth saving yet (every view is its own URL); add it when a feature needs it.

## Front-end rules (iOS 9 / Safari 9)

There is no build step or bundler, so what is written is what the iPad runs.
Everything the iPad loads must work in Mobile Safari 9 and still work in
current phone browsers.

- **JavaScript:** the only script is hand-written ES5 in `static/app.js`; no
  inline scripts, no other files. Use `var` and `function`. No arrow
  functions, classes, template literals, `let`/`const`, `async`/`await`,
  default parameters, spread, destructuring or `for...of`.
- **APIs:** no `fetch` (use `XMLHttpRequest`), `Element.closest`,
  `Array.includes`, `String.includes`/`startsWith`, `NodeList.forEach`,
  `Object.entries`/`values` or `Promise.prototype.finally`. Prefer plain
  callbacks over `Promise`. Add a small targeted polyfill only if unavoidable.
- **CSS:** no grid, no flex `gap`, no custom properties (`var(--x)`), no
  unprefixed `position: sticky`. Flexbox with margins is fine. Fonts are TTF
  (no WOFF2).
- **Page changes:** every tap is a full page load, so the page colour is set
  inline in `base.html` (ahead of the stylesheet) to avoid flashing the
  browser's backdrop, and `app.css` asks modern browsers to cross-fade
  (`@view-transition`; iOS 9 ignores it). Keep that colour in one place.
- **Pages:** server-rendered; every action is a plain form `POST` that answers
  with a `303` redirect. Prefer native elements (`<details>`) to JavaScript.
- **Guard rails:** `tests/test_app_js.py` fails if `app.js` uses modern syntax
  or APIs, and the `Ios9SafetyTest` classes fail on extra scripts, grid or
  flex gap. `tests/test_app_js_behaviour.py` runs the real `app.js` under Node
  in a small fake browser (`tests/js/`) to check links, the overlay, the
  reloads and the banner; it needs `node` (CI has it; locally it skips
  without it). Nothing here counts as working until it is tried on the iPad.
