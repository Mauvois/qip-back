#!/bin/sh
set -eu

: "${CI_COMMIT_SHA:?Missing commit SHA}"
export QIP_API_IMAGE="qip_api_prod_api:$CI_COMMIT_SHA"
project="qip_ci_${CI_PIPELINE_NUMBER:-local}_$(printf %.12s "$CI_COMMIT_SHA")"
compose() { docker compose -f ci/compose.test.yml -p "$project" "$@"; }
cleanup() { compose down --volumes --remove-orphans; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

compose up -d --wait --wait-timeout 120 db
compose run --rm tests
