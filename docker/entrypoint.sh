#!/bin/sh
set -e

# Crée le dossier s’il n’existe pas
mkdir -p /secrets

# Si la variable est présente, décode et écrit le fichier
if [ -n "$GOOGLE_CREDENTIALS_B64" ] ; then
  echo "$GOOGLE_CREDENTIALS_B64" | base64 -d > /secrets/credentials.json
  export GOOGLE_APPLICATION_CREDENTIALS=/secrets/credentials.json
fi

exec "$@"
