# IANUA — Roadmap technique

Derniere mise a jour : 14 mars 2026

---

## Phase 1 — Ancrage (Complete)

Fondation du site et de la charte. Gouvernance fondateur-led.

### Livre

- Site statique ianua.world (Vercel)
- Backend FastAPI api.ianua.world (Railway)
- PostgreSQL 16 (Railway)
- Charte 8 principes, 3 paliers visuels (fondations / mecanismes / agents)
- Voix humaine + voix IA pour chaque principe
- 8 lignes rouges non negociables (Pacte)
- Forum commentaires par principe + reactions (pertinent/enrichissant/hors_sujet)
- Newsletter double opt-in (Brevo HTTP API)
- Signatures de soutien global (double opt-in)
- SEO complet (Open Graph, Twitter Cards, sitemap.xml, robots.txt)
- Trilingue FR/EN/ES (data attributes + detection navigateur)
- Gouvernance : registre des amendements avec filtres
- Forum de deliberation par amendement
- Amendements A001, A001-R, A002 ratifies (v2.1 → v2.2)
- Amendements A003, A003-R, A004 en deliberation
- Dashboard admin : moderation commentaires, liste inscrits
- Page confirmation email (inscription + signature)
- SSL, CORS, rate limiting (slowapi), security headers
- Alembic migrations (001-005)

---

## Phase 2 — Deliberation communautaire (Complete — 14 mars 2026)

Auto-gouvernance. Le cycle de vie des amendements est 100% automatique et communautaire. L'admin technique ne peut que supprimer pour abus (logge publiquement).

### Livre en une session

**Authentification**
- Magic link email (token usage unique, 15 min, Brevo)
- JWT session (httpOnly, secure, SameSite=Lax, HS256, 24h)
- Rate limiting : 3 magic links par email par heure
- Anti-enumeration (reponse generique pour email inconnu)
- Endpoint /auth/me pour etat de connexion frontend

**Vote communautaire**
- Boutons Pour / Contre / Abstention par amendement
- Modification de vote avec historique public (table vote_history)
- Rate limit : 10 modifications par amendement par utilisateur par heure
- Resultats en temps reel (polling 30s)
- Motivations signees publiques
- Reactions sur motivations (pertinent/enrichissant/hors_sujet)
- Compteurs denormalises sur amendments (votes_for/against/abstain)

**Flux de proposition**
- Brouillons (max 5 par auteur, modifiables librement)
- Partage brouillon par lien token (UUID, lecture sans auth)
- Commentaires prives sur brouillons partages
- Soumission : gel du texte, statut proposed
- 3 types : Modification, Ajout, Suppression
- Forçage automatique palier Fondateur pour Ajout/Suppression
- Soutiens communautaires (filtre positif, seuil adaptatif par palier)
- Transition automatique proposed → deliberation quand seuil atteint
- Retrait par l'auteur (statut withdrawn)
- L'auteur ne peut pas soutenir sa propre proposition

**Seuils de recevabilite**

| Palier | Seuil | Plancher | Delai expiration | Duree deliberation |
|--------|-------|----------|------------------|--------------------|
| Mineur | 5% | 3 | 60 jours | 14 jours |
| Substantiel | 10% | 10 | 90 jours | 21 jours |
| Fondateur | 20% | 25 | 120 jours | 30 jours |

**Seuils de ratification**

| Palier | Majorite | Quorum |
|--------|----------|--------|
| Mineur | >50% FOR/(FOR+AGAINST) | Non |
| Substantiel | >=2/3 | Non |
| Fondateur | >=2/3 | 30% signataires confirmes |

**Gouvernance**
- Contestation de palier (3 contestations → auto-requalification si convergence)
- Signalement communautaire (spam/hors_charte/contenu_inapproprie)
- Suppression pour abus (admin, loggee publiquement)
- Requalification de palier (admin si divergence, loggee)

**Audit IA**
- Declenchement admin sur amendements proposed/deliberation
- Provider registry extensible (Claude, GPT-4o configures)
- Prompt identique sans framing Ianua
- Publication explicite par l'admin (non publie par defaut)
- Toute decision (publier/rejeter) loggee dans admin_actions
- Reponses publiees immuables
- Affichage en cyan sur gouvernance.html (section repliable)

**Transparence**
- Page transparence.html : log public de toutes les actions admin
- Chaque suppression, rejet de signalement, requalification, audit tracee

**Crons automatiques (APScheduler)**
- Expiration des propositions : toutes les heures
- Cloture des votes : toutes les heures (evaluation majorite + quorum)
- Nettoyage magic tokens : quotidien

**Frontend**
- Vote integre dans gouvernance.html (plus de page separee)
- proposer.html : formulaire de proposition, gestion brouillons, diff preview
- transparence.html : log public actions admin
- status.html : etat du projet pour la communaute
- vote.html : redirect vers gouvernance#deliberation
- Navigation unifiee : Principes → Gouvernance → Proposer
- Etat de connexion global (toutes les pages)

**Dashboard admin (8 onglets)**
- En attente / Approuves / Rejetes (commentaires)
- Inscrits newsletter
- Amendements (suppression, requalification, signalements)
- Audit IA (lancer, publier, rejeter)
- Signataires
- Transparence

**Securite**
- Audit complet : SQL injection, XSS, CSRF, auth bypass, IDOR, rate limiting
- JWT secret sans valeur par defaut (warning au startup)
- Sanitization strip_html sur tous les inputs utilisateur
- Limites de longueur sur tous les champs texte
- Cookie domain, httpOnly, secure, SameSite=Lax
- Blocage sondes (wp-admin, phpmyadmin, xmlrpc) dans vercel.json
- 58 tests automatises

**Infrastructure**
- 61 routes API
- 15 tables PostgreSQL
- Alembic migrations 006-007
- 6 modules backend (auth, voting, proposals, governance, audit_ia, crons)

**Documentation**
- Spec vote communautaire
- Spec flux de proposition + audit IA + navigation
- Plan 1 (auth + vote) et Plan 2 (proposition + audit + nav)
- Definition fondatrice d'ianuite (texte trilateral immuable)

---

## Phase 3 — Ratification formelle (Planifiee)

### A construire

- OAuth (Google/GitHub/X) en complement du magic link
- Notifications push (nouveaux amendements, resultats de vote, seuil atteint)
- Traduction communautaire des propositions (mecanisme collaboratif)
- Systeme de delegation de vote
- Publication academique de la charte
- Integration providers IA supplementaires (Gemini, Mistral Large, Grok, Llama)
- Ratification formelle des amendements Phase 2 par la communaute
- Internationalisation complete du frontend (i18n switching)

---

## Actif en production (14 mars 2026)

| Composant | URL | Hebergement |
|-----------|-----|-------------|
| Frontend | https://ianua.world | Vercel |
| API | https://api.ianua.world | Railway |
| PostgreSQL | interne Railway | Railway |
| Email | Brevo HTTP API | SaaS |

---

## Variables d'environnement Railway requises

```
# Base de donnees
DATABASE_URL=postgresql+asyncpg://user:pass@host:port/dbname

# Email (Brevo)
BREVO_API_KEY=xkeysib-...
FROM_EMAIL=ianua@outlook.fr
FROM_NAME=Ianua

# Securite
ADMIN_KEY=<cle-admin-forte>
SECRET_KEY=<generer-avec-openssl-rand-hex-32>

# URLs
BASE_URL=https://ianua.world
API_URL=https://api.ianua.world
ALLOWED_ORIGINS=https://ianua.world,https://www.ianua.world

# Audit IA (optionnel, activer quand configure)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```
