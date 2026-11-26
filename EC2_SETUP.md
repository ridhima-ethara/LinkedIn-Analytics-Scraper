# EC2 deployment (Amazon Linux 2023 / Ubuntu 22.04+)

Headless Playwright **Firefox** on a small instance. `t3.small` (2 vCPU / 2 GB)
is the practical minimum; `t3.medium` is comfortable. ~2 GB disk for the browser.

## 1. Provision

* AMI: Ubuntu 22.04/24.04 LTS or Amazon Linux 2023
* Security group: **no inbound rules needed** (outbound 443 only). Use SSM
  Session Manager or SSH from your own IP.
* IAM role (optional): `AmazonSSMManagedInstanceCore` for Session Manager, plus
  S3 write if you want to ship reports to a bucket.

## 2. Install

```bash
sudo mkdir -p /opt/linkedin-analytics && sudo chown "$USER" /opt/linkedin-analytics
cd /opt/linkedin-analytics
# copy this project here (git clone / scp -r)
bash setup_ec2.sh
```

`setup_ec2.sh` installs Python 3 + venv, the project dependencies, Firefox and
its system libraries (`playwright install --with-deps firefox`), plus `xvfb`
for the one-time interactive login, then runs the offline tests.

## 3. Get an authenticated session onto the instance (MFA-friendly)

The tool needs a logged-in session. Pick **one** of these. All three keep the
human in control of the password and the MFA code — nothing is automated.

### Option A — log in locally, copy the encrypted session (recommended)

On your laptop:

```bash
export LI_SESSION_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
python login.py                       # visible Firefox: sign in + MFA by hand
```

Then move both halves to the instance and keep the key out of the file system:

```bash
scp secrets/linkedin_state.json.enc ec2-user@<host>:/opt/linkedin-analytics/secrets/
# on the instance, put the key in the environment (or SSM Parameter Store):
echo "LI_SESSION_KEY=<the key you generated>" >> /opt/linkedin-analytics/.env
chmod 600 /opt/linkedin-analytics/.env
```

Better: store the key in **SSM Parameter Store (SecureString)** and export it at
run time, so the key never sits on disk:

```bash
aws ssm put-parameter --name /linkedin-analytics/session-key --type SecureString --value "<key>"
# in the cron wrapper:
export LI_SESSION_KEY="$(aws ssm get-parameter --name /linkedin-analytics/session-key \
  --with-decryption --query Parameter.Value --output text)"
```

### Option B — interactive login on the instance over Xvfb + VNC

```bash
Xvfb :99 -screen 0 1600x1200x24 &
export DISPLAY=:99
x11vnc -display :99 -localhost -nopw -forever &     # then: ssh -L 5900:localhost:5900 ...
.venv/bin/python login.py                            # log in through your VNC viewer
pkill x11vnc
```

### Option C — import your own `li_at` cookie (no display at all)

Sign in to LinkedIn in your own browser, copy the value of your own `li_at`
cookie (DevTools → Application → Cookies), then:

```bash
export LI_AT='<your li_at value>'
.venv/bin/python login.py --from-cookie-env
unset LI_AT
```

Validate whichever option you used:

```bash
.venv/bin/python login.py --check
```

LinkedIn sessions are long-lived but not permanent, and LinkedIn may challenge a
session seen from a new network/datacentre IP. When `run_analytics.py` exits
`2`, redo this step. The tool refreshes the stored session after every
successful run to extend its life.

## 4. Run

```bash
cd /opt/linkedin-analytics
.venv/bin/python run_analytics.py --url "https://www.linkedin.com/company/<id>/admin/analytics/updates/"

# explicit windows
.venv/bin/python run_analytics.py --year 2026
.venv/bin/python run_analytics.py --start 2026-01-01 --end 2026-11-25
```

After each run, check `date_range_verified` in `run_meta.json`: `false` means
LinkedIn did not confirm the requested window and the numbers belong to the
range named in `date_range_applied`.

Headless is the default (`browser.headless: true`). Nothing needs `DISPLAY`.

## 5. Schedule

```bash
crontab -e
```

```cron
# daily at 03:15 UTC
15 3 * * * /opt/linkedin-analytics/run.sh >> /opt/linkedin-analytics/logs/cron.log 2>&1
```

`run.sh` loads `.env`/SSM, activates the venv, runs the extractor, and (if
`S3_BUCKET` is set) syncs the report folder to S3.

## 6. Operations

* **Logs**: `logs/<run_id>.log` (DEBUG) and `logs/cron.log`.
* **Failure evidence**: `output/<run_id>/screenshots/*_failure_*.png`.
* **Exit codes**: `0` completed · `2` session expired → redo step 3 ·
  `3` fatal error. Alert on non-zero.
* **Retries**: per-section, `extraction.retries` (default 3) with linear backoff;
  a screenshot is captured on each failed attempt.
* **Memory**: if Firefox is OOM-killed on `t3.small`, add swap:
  `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`
* **Timeouts**: slow instances may need `browser.nav_timeout_ms: 90000` and
  `extraction.settle_ms: 4000`.
* **Secrets hygiene**: `secrets/` is `chmod 600` and git-ignored; prefer
  `LI_SESSION_KEY` from SSM over the on-disk key file; never commit `.env`.
* **Cleanup**: `find output -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +`
