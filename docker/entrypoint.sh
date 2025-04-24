#!/bin/sh
set -e

# Si la variable base64 est fournie, on la décode dans /secrets
if [ -n "$GOOGLE_CREDENTIALS_B64" ]; then
  echo "$GOOGLE_CREDENTIALS_B64" | base64 -d > /secrets/credentials.json
  export GOOGLE_APPLICATION_CREDENTIALS=/secrets/credentials.json
fi

exec "$@"
