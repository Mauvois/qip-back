# Déploiement — qip.taan.ovh

## CI/CD

Un push sur `staging` lance le pipeline `.woodpecker.yml` : construction d'une
image `qip_api_prod_api:<SHA>`, tests sur PostgreSQL éphémère, sauvegarde de la
base existante puis remplacement de l'API. Le tunnel et le domaine ne sont pas
modifiés. L'étape de déploiement utilise le `.env.prod` existant du Mac en lecture
seule, et le verrou partagé `/Users/serveur/docker/qip/ci-state/deploy.lock`.
Les sauvegardes sensibles restent dans le sous-dossier `backups/` de ce dossier.
Nginx est rechargé après remplacement de l'API ; le pipeline contrôle ensuite
`https://qip.taan.ovh/api/terms/` et le label de révision du conteneur.

Les instructions ci-dessous concernent une installation ou intervention manuelle.
Après une livraison CI, exporter `QIP_API_IMAGE=qip_api_prod_api:<SHA>` pour
réutiliser cette image, avec `--no-build` au lieu de `--build`. Sinon une commande
manuelle peut remplacer la version CI par une autre image.

Les deux dépôts sont déployés séparément : l'API Django dans `qip-back`, le
frontend Nginx dans `qip-front`. Le Compose de l'API gère aussi PostgreSQL 15.
Le frontend est l'unique point d'entrée de
l'application et transmet `/api/` ainsi que les anciennes routes d'authentification
à Django sur le réseau Docker `qip_backend_net`. PostgreSQL reste privé ; le
stockage des fichiers de production utilise GCP.

## Prérequis sur le serveur

- Docker avec le plugin Compose, le réseau `qip_backend_net`, le volume
  `qip-bdd_pgdata_qip` et les paramètres du bucket GCP existant ;
- DNS `qip.taan.ovh` relié au serveur (ou au tunnel), avec TLS à l'entrée : le
  proxy HTTPS du serveur ou le tunnel transmet au frontend sur
  `http://127.0.0.1:8012` ; **ne pas exposer le port 8012 sur Internet** ;
- accès GitHub aux deux dépôts privés si nécessaire. Aucun troisième dépôt
  n'est nécessaire sur le serveur.

## Première installation

Cloner les deux dépôts côte à côte (adapter la branche si les changements ont
été intégrés ailleurs) :

```sh
git clone -b staging git@github.com:Mauvois/qip-back.git
git clone -b staging git@github.com:Mauvois/qip-front.git
docker network create qip_backend_net
docker volume create qip-bdd_pgdata_qip
cp qip-back/.env.prod.example qip-back/.env.prod
```

Renseigner **toutes** les valeurs obligatoires dans `qip-back/.env.prod`. Les
secrets ne sont jamais commités. Utiliser `DB_HOST=postgres_qip` et `DB_PORT=5432` :
PostgreSQL reste sur le réseau Docker, sans port publié. Le volume existant est
réutilisé ; avant de migrer une base existante, la sauvegarder. Pour un volume
déjà initialisé, `DB_USER` et `DB_PASSWORD` doivent correspondre à un rôle réel :
les variables `POSTGRES_*` ne modifient pas les identifiants existants.
`GOOGLE_CREDENTIALS_FILE` désigne le chemin absolu du JSON du compte de service
GCP sur l'hôte, en dehors des dépôts Git et des contextes de build. Restreindre
le dossier à son propriétaire (`700`) et le fichier à `600`. Le Compose monte
ce fichier en lecture seule dans `/secrets/credentials.json` ; la clé n'est pas
transmise comme variable d'environnement. Garder `DJANGO_SECRET_KEY` et
`SIGNING_SECRET` stables après le premier démarrage. Pour activer Zotero OAuth,
renseigner les trois variables `ZOTERO_*` et déclarer l'URL de callback
`https://qip.taan.ovh/api/v2/zotero/oauth/callback/` auprès de Zotero.
Pour les transferts directs vers GCP, configurer le CORS du bucket avec
`cors.json` (qui autorise `https://qip.taan.ovh`).

Depuis le dossier `qip-back` :

```sh
docker compose --env-file .env.prod -f docker/prod/docker-compose.yml -p qip_api_prod up -d --build api
```

Attendre que l'API ait exécuté ses migrations et `collectstatic`, puis depuis
le dossier `qip-front` :

```sh
docker compose -f docker/prod/docker-compose.prod.yml -p qip_front_prod up -d --build frontend
```

Le volume Docker partagé `qip_static` contient les fichiers de l'admin Django.
Le frontend publie uniquement `127.0.0.1:8012` sur le serveur ; l'API ne publie
aucun port hôte. Configurer le proxy HTTPS ou le tunnel existant pour
`qip.taan.ovh` vers ce port, sans réécrire les chemins. Si le tunnel Cloudflare
tourne lui-même dans un conteneur, `127.0.0.1` désigne **ce conteneur**, pas
l'hôte : le raccorder à `qip_backend_net` et cibler `http://qip_front_prod:80`,
ou passer par un proxy hôte. Vérifier ensuite
`https://qip.taan.ovh/`, `https://qip.taan.ovh/api/terms/`, la connexion et
l'admin. Pour diagnostiquer le démarrage :

```sh
docker compose --env-file .env.prod -f docker/prod/docker-compose.yml -p qip_api_prod logs api
docker compose -f docker/prod/docker-compose.prod.yml -p qip_front_prod logs frontend
```

## Mises à jour

Dans chaque dépôt, faire `git pull` sur la branche déployée, relancer d'abord
l'API avec la commande ci-dessus (migrations comprises), puis le frontend.
Si le frontend n'est pas recréé après une recréation de l'API, recharger Nginx
avec `docker exec qip_front_prod nginx -s reload` pour actualiser sa résolution DNS.
Les pipelines Woodpecker déploient automatiquement sur push de `staging` ; ils
peuvent aussi être lancés manuellement. Ne pas intervenir simultanément avec un
pipeline : utiliser le même verrou de déploiement. Un rollback après migration
nécessite une analyse de compatibilité et, si nécessaire, une restauration de la
sauvegarde ; il n'est pas automatique.
