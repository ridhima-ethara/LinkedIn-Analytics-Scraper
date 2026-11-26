#!/usr/bin/env bash
# Cron-friendly wrapper: loads config/secrets, runs the extractor, optionally
# ships the reports to S3. Usage: ./run.sh [extra run_analytics.py args...]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

[ -f .env ] && set -a && . ./.env && set +a

# Prefer the session key from SSM Parameter Store when configured.
if [ -n "${LI_SESSION_KEY_SSM_PARAM:-}" ] && command -v aws >/dev/null 2>&1; then
  LI_SESSION_KEY="$(aws ssm get-parameter --name "$LI_SESSION_KEY_SSM_PARAM" \
      --with-decryption --query Parameter.Value --output text)"
  export LI_SESSION_KEY
fi

mkdir -p logs output
set +e
.venv/bin/python run_analytics.py "$@"
code=$?
set -e

case "$code" in
  0) echo "run completed" ;;
  2) echo "SESSION EXPIRED — re-authenticate (see EC2_SETUP.md section 3)" >&2 ;;
  *) echo "run failed with exit code $code" >&2 ;;
esac

if [ -n "${S3_BUCKET:-}" ] && command -v aws >/dev/null 2>&1; then
  latest="$(ls -1dt output/*/ 2>/dev/null | head -1 || true)"
  if [ -n "$latest" ]; then
    aws s3 sync "$latest" "s3://${S3_BUCKET}/linkedin-analytics/$(basename "${latest%/}")/" \
      --only-show-errors && echo "synced $latest to s3://${S3_BUCKET}"
  fi
fi

exit "$code"
