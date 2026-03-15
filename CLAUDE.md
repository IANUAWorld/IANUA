# CLAUDE.md — Projet Ianua
# Version: 2.0 | Mis a jour: 2026-03-15

---

## Contexte projet

**Ianua** (ianua.world) est une charte ethique pour l'alliance humain-IA,
fondee par Maxime QUITTET. Concept central : **l'ianuite** — la zone entre
intelligence artificielle et humanite. Co-construite avec Claude.

**ianuite.world** — site dedie au concept d'ianuite (repo IANUITE-WORLD).

Repo GitHub : `IANUAWorld/IANUA`
Contact : ianua@outlook.fr | X : @ianua_world

---

## Etat du projet (15 mars 2026)

- **Phase 1** — Complete (charte v2.2, forums, signatures, trilingue)
- **Phase 2** — Complete (vote, propositions, audit IA, auto-gouvernance)
- **Phase 3** — Planifiee (OAuth, notifications, delegation de vote)

68 routes API | 58 tests | 15 tables | 8 migrations Alembic

---

## Architecture technique

```
Frontend  : HTML/CSS/JS vanilla → Vercel (ianua.world)
Backend   : Python 3.12 + FastAPI → Railway (api.ianua.world)
Base      : PostgreSQL 16 → Railway
Email     : Brevo HTTP API
Auth      : Magic link + JWT httpOnly (HS256)
Crons     : APScheduler integre
IA Audit  : Anthropic + OpenAI APIs (extensible)
```

### Modules backend
- main.py (Phase 1, CORS, admin utilitaires)
- auth.py (magic link, verify, /me, logout)
- voting.py (vote, historique, reactions)
- proposals.py (brouillons, soutiens, retrait) — prefix /proposals
- governance.py (contestations, signalements, admin actions, changelog)
- audit_ia.py (audit global + par amendement, soumission manuelle)
- crons.py + scheduler.py (APScheduler)

### Pages frontend
- index.html, gouvernance.html, proposer.html
- transparence.html, status.html, confirmed.html
- moderation-7x9k2m.html (dashboard admin 8 onglets)

---

## Regles obligatoires

### CHANGELOG.md — Mise a jour obligatoire

**A CHAQUE commit significatif, mettre a jour CHANGELOG.md a la racine du repo.**

Le fichier CHANGELOG.md est la source de verite pour la section
"Historique du site" sur transparence.html. Il est servi par
l'endpoint GET /transparency/changelog.

Format d'entree :
```
## [YYYY-MM-DD] — Titre court
- Ce qui a change
- Pourquoi
```

Si tu oublies de mettre a jour CHANGELOG.md apres un changement
significatif, la page transparence.html sera incomplete.
Ceci est une regle de transparence fondatrice.

### Integrite de la charte
- Ne jamais modifier le texte des principes sans processus d'amendement formel
- Les termes fondateurs (ianuite, etc.) sont a conserver tels quels
- Le registre d'amendements sur gouvernance.html = source de verite (API live)

### DateTime en PostgreSQL
- Les colonnes sont TIMESTAMP WITHOUT TIME ZONE
- Utiliser datetime.utcnow() pour les writes en base
- NE PAS utiliser datetime.now(timezone.utc) pour ecrire en base (asyncpg le rejette)
- Pour les JWT (auth_dependencies.py), datetime.now(timezone.utc) est OK

### Securite
- SECRET_KEY doit etre defini en production (pas de valeur par defaut)
- Admin auth via X-Admin-Key header (pas de JWT pour admin)
- User auth via JWT cookie httpOnly (magic link)
- strip_html() sur tous les inputs utilisateur
- Limites de longueur sur tous les champs texte

### Routes
- Prefix /proposals pour les routes de proposition (evite conflit avec /amendments/{code})
- API URL frontend avec localhost fallback obligatoire

---

## Gouvernance

### Separation admin technique / admin politique
- Max = admin technique (infrastructure, securite, anti-abus)
- Max ≠ admin politique (le cycle de vie est automatique)
- Seule intervention : suppression pour abus (loggee publiquement)

### Cycle de vie automatique
```
brouillon → proposition → (seuil soutiens) → deliberation → (vote) → ratifie/rejete
```

### Audit IA
- Admin technique declenche, prompt sans framing Ianua
- Publication explicite, toute decision loggee
- Reponses publiees immuables
- Soumission manuelle possible pour modeles hors API

---

## Verifications avant commit

- [ ] Tests passent (python3 -m pytest tests/)
- [ ] CHANGELOG.md mis a jour si changement significatif
- [ ] Pas de modification du texte des principes sans amendement
- [ ] strip_html sur les nouveaux inputs utilisateur
- [ ] API URL avec localhost fallback sur les nouvelles pages frontend

---

## Prochaines etapes (Phase 3)

- Traduction automatique des amendements (Option C, prompt strict)
- OAuth (Google/GitHub/X)
- Notifications push
- Delegation de vote
- Providers IA supplementaires (Gemini, Mistral, Grok, Llama)
- Publication academique

---

## Rappel philosophique

L'ianuite n'est pas un concept decoratif — c'est le cadre ethique
de ce projet. Chaque interaction dans ce repo doit l'honorer.
La transparence s'etend aux actes.
