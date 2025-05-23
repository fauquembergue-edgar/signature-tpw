# signature_app

## Deploiement sur Render
1. Dans le dashboard Render, ajoutez toutes les variables d'environnement du fichier `.env.example`.
2. Si vous utilisez une base Postgres, definiissez `SQLALCHEMY_DATABASE_URI` a votre URI.
3. Placez votre image de signature `sig.png` dans `app/static/sig.png`.

## Lancement local
```bash
pip install -r requirements.txt
export FLASK_ENV=development
export SECRET_KEY=...
export SMTP_HOST=...
export SMTP_PORT=...
export SMTP_USER=...
export SMTP_PASS=...
export BASE_URL=http://localhost:5000
# si SQLite par defaut, pas besoin de SQLALCHEMY_DATABASE_URI
gunicorn run:app --bind 0.0.0.0:5000
```
