# Déploiement manuel — qip.taan.ovh

Les deux dépôts sont déployés séparément : l'API Django dans `qip-back`, le
frontend Nginx dans `qip-front`. Le frontend est l'unique point d'entrée de
l'application et transmet `/api/` ainsi que les anciennes routes d'authentification
à Django sur le réseau Docker `qip_backend_net`. PostgreSQL reste privé ; le
stockage des fichiers de production utilise GCP.

## Prérequis sur le serveur

- Docker avec le plugin Compose, une base PostgreSQL accessible depuis le réseau
  `qip_backend_net` et les paramètres du bucket GCP existant ;
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
cp qip-back/.env.prod.example qip-back/.env.prod
```

Renseigner **toutes** les valeurs obligatoires dans `qip-back/.env.prod`. Les
secrets ne sont jamais commités. Le PostgreSQL existant doit être joignable sous
  `DB_HOST` depuis `qip_backend_net` ; rattacher son conteneur à ce réseau si
nécessaire. `GOOGLE_CREDENTIALS_B64` contient le JSON du compte de service GCP
encodé en base64 sur **une seule ligne**. Garder `DJANGO_SECRET_KEY` et
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
`qip.taan.ovh` vers ce port, sans réécrire les chemins. Vérifier ensuite
`https://qip.taan.ovh/`, `https://qip.taan.ovh/api/terms/`, la connexion et
l'admin. Pour diagnostiquer le démarrage :

```sh
docker compose --env-file .env.prod -f docker/prod/docker-compose.yml -p qip_api_prod logs api
docker compose -f docker/prod/docker-compose.prod.yml -p qip_front_prod logs frontend
```

## Mises à jour

Dans chaque dépôt, faire `git pull` sur la branche déployée, relancer d'abord
l'API avec la commande ci-dessus (migrations comprises), puis le frontend.
Les anciens pipelines Woodpecker peuvent toujours être lancés **manuellement** ;
un push ne lance plus leur étape de déploiement. L'intégration CI sur le serveur
sera revue lorsque son accès sera disponible.
