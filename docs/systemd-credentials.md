# Managing secrets with systemd credentials

A walkthrough for the LXC. Do it once; rotating later is two commands.

## Why this instead of a `.env` file

| | `EnvironmentFile` (before) | systemd credentials (now) |
|---|---|---|
| Stored on disk as | plain text | encrypted `.cred` file |
| Reaches the app as | environment variable | a file in a private in-memory directory |
| Visible in `systemctl show`, `/proc/<pid>/environ` | yes | no |
| Readable by other services | if file permissions slip | no: only this unit gets it |

Plain, non-secret settings (like `LOG_LEVEL`) stay in `/etc/diary-app/diary-app.env`.

## How it fits together

1. `deploy/creds.sh <name>` asks for a value and pipes it into
   `systemd-creds encrypt`, producing `/etc/diary-app/creds/<name>.cred`. The file is
   encrypted with a key that only exists on this machine
   (`/var/lib/systemd/credential.secret`, root-only).
2. `diary-app.service` has `LoadCredentialEncrypted=<name>:/etc/diary-app/creds/<name>.cred`.
   At start, systemd decrypts it into a private directory and sets `$CREDENTIALS_DIRECTORY`.
3. `diary_app.config.Settings` reads that directory: a file called `household_pin` fills the
   `household_pin` setting, and likewise `session_secret`. If a credential is missing, the
   app refuses to start.

The credential name, the unit line and the setting name must all match.

## Step 0: check the container (once)

```bash
systemctl --version | head -1     # need systemd 250 or newer (Debian 12 has 252)
sudo systemd-creds has-tpm2       # "no" is expected in an LXC; the host key is used instead
```

## Step 1: create the credentials

Two secrets: the PIN you type to open the diary, and a random key that signs the login cookie.

```bash
sudo /opt/diary-app/deploy/creds.sh household_pin
sudo /opt/diary-app/deploy/creds.sh session_secret --generate
```

The first prompts twice without echoing. `--generate` makes a random value you never need to see. It refuses to overwrite an existing file unless you add `--force`.

## Step 2: tidy up the old placeholder and set the database path

The earlier spike used an `api_key` secret. Delete its plain-text line (if still there) and the
old credential file, and point the app at its state directory:

```bash
sudo $EDITOR /etc/diary-app/diary-app.env     # delete any API_KEY line; add
                                              # DATABASE_PATH=/var/lib/diary-app/diary.db
sudo rm -f /etc/diary-app/creds/api_key.cred
```

The environment wins over credentials, so a leftover `HOUSEHOLD_PIN=` line there would silently
be used instead of the encrypted one.

## Step 3: install the updated unit and restart

```bash
sudo cp /opt/diary-app/deploy/diary-app.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart diary-app
```

(`deploy.sh` restarts the service but does not copy the unit file: that is deliberate, so
unit changes are a conscious step.)

## Step 4: verify

```bash
sudo systemctl status diary-app --no-pager         # active (running)
curl -s http://127.0.0.1:8000/config-check         # both values true
sudo systemctl show diary-app -p Environment       # no PIN or secret in the output
sudo ls -l /etc/diary-app/creds                    # *.cred, mode 0600, root
sudo systemd-analyze security diary-app --no-pager | tail -3   # exposure score
```

If the service fails to start, `journalctl -u diary-app -n 30` shows why. The usual
causes are a credential name that doesn't match, a `.cred` file created on a different
machine, or a credential that was never created.

## Rotating

```bash
sudo /opt/diary-app/deploy/creds.sh household_pin --force
sudo systemctl restart diary-app
```

## Things worth knowing

- `.cred` files only decrypt on the machine whose `credential.secret` encrypted them.
  A Proxmox backup of the whole container keeps both, so restores work. Copying `.cred`
  files to a different container does not: just re-create them with `creds.sh`.
- Back up nothing by hand; re-creating a credential takes seconds.
- The Outlook refresh token (added with the calendar feature) is the one secret that
  cannot be a credential, because it changes each time it is used. It lives in
  `/var/lib/diary-app/` (`StateDirectory`, mode `0700`, owned by the service user).
