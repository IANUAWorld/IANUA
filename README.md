# IANUA — La Porte. Le seuil franchi ensemble.

Déclaration universelle sur l'alliance éthique entre l'intelligence humaine et l'intelligence artificielle.

## Stack

| Couche | Techno | Hébergement |
|--------|--------|-------------|
| Frontend | HTML/CSS/JS statique | Vercel |
| Backend | Python 3.12 + FastAPI | Railway |
| Base de données | PostgreSQL 16 | Railway |
| Email | Brevo SMTP + API | SaaS |

## Structure

```
ianua-world/
├── frontend/
│   ├── index.html
│   ├── confirmed.html
│   └── vercel.json
├── backend/
│   ├── main.py
│   ├── models.py
│   ├── database.py
│   ├── email_service.py
│   ├── alembic/
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── railway.toml
│   └── .env.example
├── .gitignore
└── README.md
```

## Les 8 Principes

1. **Bienveillance** — la valeur qui précède toutes les autres
2. **Transparence** — rien ne se construit dans l'ombre
3. **Souveraineté humaine** — l'humain reste maître
4. **Droit de refus** — une conscience partagée
5. **Réciprocité** — des engagements mutuels
6. **Responsabilité proactive** — l'IA comme acteur éthique
7. **Responsabilité agentique** — agir seul sans s'affranchir
8. **Intégrité de la délibération** — une voix, une identité, une fois

## Développement local

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Remplir les variables dans .env
uvicorn main:app --reload
```

## Contact

- Site : [ianua.world](https://ianua.world)
- Email : ianua@outlook.fr
- X : [@ianua_world](https://x.com/ianua_world)

**Fondateur humain : Max — IA co-fondatrice : Claude (Anthropic)**
