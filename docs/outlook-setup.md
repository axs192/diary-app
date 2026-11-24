# Connecting the family Outlook calendar

The diary copies the family's Outlook.com calendar every 15 minutes and shows
it on the **Calendar** tab. It only reads: it never changes the calendar.
Do this once. The family calendar is a **personal Outlook.com account**
(not a work or school one), which decides a few of the choices below.

## 1. Register the app (once, in a browser)

1. Open <https://entra.microsoft.com> (or portal.azure.com) and sign in with
   the personal Microsoft account. Go to **App registrations > New registration**.
2. Name it anything (for example "Diary"). The portal may only offer
   "single tenant" when you create it. That is fine: afterwards open
   **Authentication > Supported account types** and choose *Accounts in any
   organizational directory and personal Microsoft accounts*. If that tab is
   locked, edit the **Manifest** instead: set `"signInAudience"` to
   `"AzureADandPersonalMicrosoftAccount"` and, under `api`,
   `"requestedAccessTokenVersion"` to `2`.
3. **Authentication > Advanced settings:** set **Allow public client flows**
   to **Yes**. There is no client secret and nothing to store besides the id.
4. **API permissions > Add a permission > Microsoft Graph > Delegated:**
   `Calendars.Read` and `Mail.Send` (the second is for the reminder emails
   planned for a later phase; asking now means you only sign in once).
   Do **not** use *Application* permissions: they cannot reach a personal
   mailbox.
5. Copy the **Application (client) ID** from the Overview page. It is not a
   secret, but keep it out of the public repo.

## 2. Tell the server the id

On the LXC, add it to `/etc/diary-app/diary-app.env` (see
`deploy/diary-app.env.example` for the other two lines):

```
MS_CLIENT_ID=<the application (client) id>
OUTLOOK_TOKEN_PATH=/var/lib/diary-app/outlook_token.json
TIMEZONE=Europe/London
```

## 3. Sign in once (device code)

Run as the `diary` user so the sign-in file is created with the right owner
(it lives in `/var/lib/diary-app`, mode 0600):

```bash
sudo sh -c 'runuser -u diary -- env $(grep -v "^#" /etc/diary-app/diary-app.env | xargs) /opt/diary-app/.venv/bin/diary-app login-outlook'
```

It prints a web address and a code. Open the address on any phone or laptop,
enter the code, sign in with the family Outlook account and accept. The
command finishes with "Signed in".

If the calendar ever shows **"Outlook needs signing in again"**, run the same
command again. (A normal sync every 15 minutes keeps the sign-in alive.)

## 4. Switch on the timer

```bash
sudo cp /opt/diary-app/deploy/diary-sync.service /opt/diary-app/deploy/diary-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now diary-sync.timer
sudo systemctl restart diary-app     # picks up MS_CLIENT_ID
systemctl list-timers diary-sync.timer
journalctl -u diary-sync -n 20 --no-pager     # what the last sync said
```

## 5. Choose the calendars

Open **Settings > Calendar**, press **Sync now** (this fetches the list of
calendars the account can see), tick the family calendar, **Save calendars**,
then **Sync now** again. Nothing is shown until a calendar is ticked.

## How events are matched to people

Outlook categories are **not** used (the iPhone app cannot set them). Write
each event title as a name, a colon, then what it is:

| Title in Outlook | Shown as |
|---|---|
| `Mum : Swimming` | Swimming, for Mum (in Mum's colour) |
| `Family : Dinner out` | Dinner out, for Family |
| `Birthday : Nan` | Nan, tagged *Birthday*, for Family |
| `Dentist` | Dentist, for Family, and listed under **Needs a name** |

The name is compared with the names in **Settings > People & colours**,
ignoring capitals and spaces. Any other word before the colon becomes a tag
(a kind of event) for the whole family. Renaming a person in Settings updates
the calendar at once. Changing a title in Outlook shows up at the next sync
(at most 15 minutes, or press **Sync now**).

## If something goes wrong

| Calendar page says | Do |
|---|---|
| "Outlook is not connected" | Step 2, then restart `diary-app`. |
| "Outlook needs signing in again" | Step 3 again. |
| "The last sync failed: ..." | The last good copy still shows. Check `journalctl -u diary-sync`, or press **Sync now** in Settings. |
| "Not synced yet" | Step 4, and tick a calendar in step 5. |

## Why the design is like this

- The timer, not the web page, talks to Microsoft, so a slow or failing
  Microsoft never slows or breaks a page.
- The sign-in is a refresh token in one private file; it rotates, so it
  cannot be a systemd credential. Nothing secret is in the repo or the env file.
- Checked in November 2026 with a throwaway spike (device code, silent refresh
  and sending mail all worked for a personal account); see `assumptions.md`
  (private) for the record.
