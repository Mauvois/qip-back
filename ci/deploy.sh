#!/bin/sh
set -eu
umask 077

: "${CI_COMMIT_SHA:?Missing commit SHA}"
test -r /run/qip.env
export QIP_API_IMAGE="qip_api_prod_api:$CI_COMMIT_SHA"
compose() {
    docker compose --env-file /run/qip.env -f docker/prod/docker-compose.yml \
        -p qip_api_prod "$@"
}

docker network inspect qip_backend_net >/dev/null
docker volume inspect qip-bdd_pgdata_qip >/dev/null
docker inspect postgres_qip --format '{{.State.Health.Status}}' | grep -qx healthy
compose config --quiet

# Fail before deployment if the existing database cannot be backed up.
mkdir -p /ci-state/backups
backup="/ci-state/backups/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)-$CI_COMMIT_SHA.dump"
docker exec postgres_qip sh -c 'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$backup"
test -s "$backup"

# The database is already running: do not recreate it or change its credentials.
compose up -d --no-build --no-deps --wait --wait-timeout 180 api
# Nginx must resolve the recreated API container, without changing the tunnel.
docker exec qip_front_prod nginx -t
docker exec qip_front_prod nginx -s reload
curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors \
    --max-time 15 https://qip.taan.ovh/api/terms/ -o /dev/null
actual=$(docker inspect qip_api_prod --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
test "$actual" = "$CI_COMMIT_SHA"
printf 'Verified API commit: %s\n' "$actual"
