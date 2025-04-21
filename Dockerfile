# Image de base officielle Python
FROM python:3.11-slim

# Variables d’environnement
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Dossier de travail dans le conteneur
WORKDIR /app

# Installer les dépendances système (libpq pour psycopg2)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copier les dépendances Python
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copier le code du projet
COPY . .

# Exposer le port sur lequel Django écoute
EXPOSE 80

# Lancer le serveur Django
CMD ["python", "manage.py", "runserver", "0.0.0.0:80"]
