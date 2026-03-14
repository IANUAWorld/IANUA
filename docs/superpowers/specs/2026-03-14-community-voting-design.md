# Design — Vote communautaire sur les amendements

**Date** : 2026-03-14
**Projet** : IANUA (ianua.world)
**Périmètre** : Vote humain uniquement (l'audit IA multi-modèles fera l'objet d'un design séparé)

---

## 1. Contexte

IANUA est une charte éthique pour l'alliance humain-IA. Les amendements sont des propositions de modification de la charte. Les signataires vérifiés votent Pour/Contre/Abstention sur les amendements en statut "délibération".

La table `amendment_votes` existe déjà en base PostgreSQL. L'objectif est de construire l'interface de vote et les endpoints API nécessaires.

### Stack existant

- Frontend statique (HTML/CSS/JS vanilla) sur Vercel
- Backend FastAPI sur Railway
- PostgreSQL sur Railway
- Email via Brevo HTTP API
- Trilingue FR/EN/ES

---

## 2. Authentification — Magic link email

### Flux

1. Le signataire arrive sur `vote.html`, clique "Se connecter pour voter"
2. Il entre son email → le backend vérifie qu'il existe dans la table des signataires confirmés
3. Si oui → Brevo envoie un magic link contenant un token unique (UUID, expiration 15 min)
4. Le signataire clique le lien → le backend valide le token, le marque comme utilisé (`used = true`), crée une session JWT (cookie httpOnly, expiration 24h)
5. Redirection vers `vote.html` — il est connecté et peut voter

### Token à usage unique

Le magic link est invalidé en base dès sa première utilisation. Un lien intercepté ne peut pas être réutilisé.

### Table `magic_tokens` (nouvelle)

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer | PK, auto-increment |
| `email` | String | Email du signataire |
| `token` | String | Token unique (UUID) |
| `used` | Boolean | Default `false`, passé à `true` après usage |
| `expires_at` | DateTime | Expiration à 15 min |
| `created_at` | DateTime | Horodatage |

### Cas d'erreur

- Email inconnu → "Cette adresse n'est pas associée à une signature vérifiée"
- Token expiré → "Lien expiré, demandez-en un nouveau"
- Token déjà utilisé → "Ce lien a déjà été utilisé, demandez-en un nouveau"
- Signataire non confirmé → "Votre signature n'a pas encore été confirmée"

### Session

Le JWT contient les claims suivants : `{sub: signer_id, name: "display_name", iat: ..., exp: ...}`. Signé en HS256 avec un secret serveur stocké en variable d'environnement. Pas de table de sessions — le cookie suffit. Déconnexion = suppression du cookie.

### Indexes

- Index unique sur `magic_tokens.token`
- Index sur `magic_tokens.email` (vérification rate limit)
- Nettoyage : cron quotidien supprime les tokens où `used = true` OR `expires_at < now()`

---

## 3. Interface de vote (`vote.html`)

### Structure de la page

1. **Header** : titre "Vote communautaire", état de connexion (nom du signataire ou bouton "Se connecter"), lien retour vers `gouvernance.html`
2. **Liste des amendements en délibération** : seuls les amendements avec `status = 'deliberation'` et `vote_opened_at` non null apparaissent
3. **Carte d'amendement** (pour chaque amendement) :
   - Identifiant (ex: A003), titre, résumé du changement proposé
   - Palier de seuil affiché (mineur/substantiel/fondateur + seuil requis)
   - Dates d'ouverture et de clôture du vote (ex: "Vote ouvert jusqu'au 28 mars")
   - **Bloc de vote** : trois boutons Pour / Contre / Abstention + champ texte "Motivation (optionnelle)"
   - Si déjà voté : le choix actuel est mis en évidence + bouton "Modifier mon vote"
   - **Bloc résultats** : barres de progression (pour/contre/abstention) avec compteurs, rafraîchies par polling toutes les 30s
   - **Motivations publiques** : liste des motivations signées (nom + vote + texte), les plus récentes en premier. La motivation du signataire connecté apparaît en premier.
   - Réactions sur les motivations : Pertinent / Enrichissant / Hors sujet (même système que les réactions sur commentaires de principes, via la table `reactions` existante avec type `vote_motivation`)
   - Si le votant a modifié son vote : mention visible "(vote modifié)" à côté de son nom

### État non connecté

Les résultats, compteurs et motivations sont visibles en lecture seule (transparence totale). Les boutons de vote sont remplacés par "Connectez-vous pour voter".

### Ancrage

`vote.html#A003` scrolle directement vers l'amendement concerné (lien depuis `gouvernance.html`).

---

## 4. Modification de vote et historique

### Flux de modification

1. Le signataire a déjà voté → sa carte affiche son choix actuel en surbrillance
2. Il clique "Modifier mon vote" → les trois boutons redeviennent actifs, le champ motivation se rouvre (prérempli avec sa motivation précédente)
3. Il soumet son nouveau vote → le backend crée une entrée dans `vote_history`, met à jour la ligne dans `amendment_votes` et recalcule les compteurs dénormalisés

### Table `vote_history` (nouvelle)

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer | PK, auto-increment |
| `vote_id` | Integer | FK → `amendment_votes.id` |
| `previous_vote` | String(10) | `FOR` / `AGAINST` / `ABSTAIN` |
| `previous_comment` | Text | Motivation précédente |
| `changed_at` | DateTime | Horodatage du changement |

### Affichage public

Dans la liste des motivations, un votant ayant modifié son vote apparaît avec la mention "(vote modifié)" et un indicateur cliquable/dépliable qui montre l'historique : ancien vote → nouveau vote, avec dates.

### Indexes

- Index sur `vote_history.vote_id`

### Règles

- Les compteurs dénormalisés sont recalculés à chaque modification (décrémente l'ancien, incrémente le nouveau)
- La contrainte unique `(amendment_id, voter_identity)` reste inchangée — mise à jour de la ligne existante
- Les constantes de vote (`FOR`, `AGAINST`, `ABSTAIN`) sont en majuscules côté backend, traduites côté frontend selon la langue active (FR/EN/ES)
- Rate limit sur les modifications : max 10 modifications par amendement par utilisateur par heure

---

## 5. Intégration avec `gouvernance.html`

### Modifications au registre des amendements

Pour chaque amendement en statut "délibération" :
- Badge cliquable "Voter →" redirigeant vers `vote.html#A00X`
- Date de clôture du vote sous le badge (ex: "Vote ouvert jusqu'au 28 mars")
- Compteurs compacts (ex: "12 pour · 3 contre · 2 abstentions") alimentés par les champs dénormalisés

Pour les amendements dont le vote est clos :
- Badge remplacé par le résultat final ("Ratifié" / "Rejeté") avec compteurs définitifs

### Ce qui ne change pas

- Le forum de délibération par amendement reste en place
- Pas de boutons de vote sur cette page — le vote se fait exclusivement sur `vote.html`
- Pas d'auth requise pour consulter le registre

### Navigation

- `gouvernance.html` → lien "Voter →" → `vote.html#A00X`
- `vote.html` → lien retour "← Gouvernance" → `gouvernance.html`
- Le menu hamburger mobile inclut un lien vers "Vote" (nouveau)

---

## 6. Endpoints API (FastAPI)

### Authentification

| Méthode | Route | Auth | Description |
|---------|-------|------|-------------|
| `POST` | `/auth/magic-link` | Non | Envoie le magic link. Body: `{email}`. Vérifie signataire confirmé, crée token usage unique, envoie via Brevo. Rate limit: 3/email/heure |
| `GET` | `/auth/verify/{token}` | Non | Valide le token, le marque comme utilisé, set cookie JWT httpOnly (24h). Redirige vers `vote.html` |
| `POST` | `/auth/logout` | Oui | Supprime le cookie JWT |

### Vote

| Méthode | Route | Auth | Description |
|---------|-------|------|-------------|
| `GET` | `/amendments/voting` | Non | Liste des amendements en délibération avec compteurs, seuils, dates |
| `GET` | `/amendments/{id}/votes` | Non | Toutes les données de vote publiques : compteurs, motivations signées, historique de modifications. Accepte `?voter_id=` pour prioriser le vote du connecté |
| `POST` | `/amendments/{id}/vote` | Oui | Soumet ou modifie un vote. Body: `{vote, comment}`. Si modification → écrit dans `vote_history`, recalcule compteurs |
| `GET` | `/amendments/{id}/votes/{vote_id}/history` | Non | Historique des modifications d'un vote spécifique |
| `GET` | `/amendments/{id}/votes/{vote_id}/reactions` | Non | Liste des réactions sur une motivation |
| `POST` | `/amendments/{id}/votes/{vote_id}/reactions` | Oui | Ajoute une réaction (Pertinent/Enrichissant/Hors sujet). Utilise la table `reactions` existante avec type `vote_motivation` |

### Principes de visibilité

**Toutes les données de vote sont publiques** et accessibles sans authentification :
- Résultats (compteurs pour/contre/abstention)
- Motivations signées et historique de modification
- Seuils de ratification par amendement

L'authentification est requise **uniquement pour les actions d'écriture** (voter, réagir).

### Erreurs de l'endpoint de vote

| Code | Condition |
|------|-----------|
| 404 | Amendement non trouvé |
| 409 | Amendement pas en statut délibération |
| 403 | Période de vote close |
| 422 | Valeur de vote invalide (doit être `FOR`, `AGAINST` ou `ABSTAIN`) |
| 429 | Rate limit dépassé (modifications)

---

## 7. Seuils de ratification

Configurable par amendement via le champ `vote_threshold` existant. Trois paliers :

| Palier | Type d'amendement | Seuil | Quorum |
|--------|-------------------|-------|--------|
| Mineur | Clarification, reformulation, traduction | Majorité simple > 50% | Non |
| Substantiel | Modification d'un principe | Majorité qualifiée ⅔ | Non |
| Fondateur | Lignes rouges, structure de gouvernance | Majorité qualifiée ⅔ | 30% des signataires confirmés doivent avoir voté |

**Calcul de majorité** : les abstentions sont exclues du dénominateur. Le seuil s'applique à `FOR / (FOR + AGAINST)`. Les abstentions comptent pour le quorum (le signataire a participé) mais pas pour la majorité.

Le palier est attribué à chaque amendement lors de sa création et affiché sur la carte de vote.

### Cycle de vie du vote

Les champs `vote_opened_at` et `vote_closed_at` sont de type `TIMESTAMP WITH TIME ZONE`. L'affichage frontend formate en date locale (ex: "28 mars 2026").

1. Un amendement passe en statut `deliberation` avec `vote_opened_at = now()` et `vote_closed_at = now() + durée_délibération` définis automatiquement lors de l'atteinte du seuil de soutiens (voir spec "Flux de proposition d'amendement"). Durées par palier : Mineur 14j, Substantiel 21j, Fondateur 30j
2. Pendant la période ouverte, les signataires votent et modifient leurs votes
3. **Enforcement côté API** : `POST /amendments/{id}/vote` rejette tout vote si `now() >= vote_closed_at` (code 403 "Période de vote close"), indépendamment du cron
4. **Cron de clôture** : tourne toutes les heures, traite les amendements où `vote_closed_at <= now()` et `status = 'deliberation'` :
   - Vérifie le quorum (si applicable au palier)
   - Calcule la majorité selon la formule `FOR / (FOR + AGAINST)`
   - Si quorum atteint + majorité atteinte → statut `ratified`
   - Si quorum atteint + majorité non atteinte → statut `rejected`
   - Si quorum non atteint → statut `rejected` avec `rejection_reason = 'quorum_not_met'` (affiché distinctement : "Rejeté — quorum non atteint" vs "Rejeté")
5. Le résultat final est affiché sur `gouvernance.html` et `vote.html`

---

## 8. Sécurité

- **Magic link** : token UUID à usage unique, expiration 15 min, invalidé en base après utilisation
- **JWT** : cookie httpOnly, secure, SameSite=Lax, expiration 24h, signé HS256. SameSite=Lax protège contre les CSRF POST cross-origin tout en permettant la navigation depuis un lien email (magic link). Les endpoints d'écriture (POST) sont protégés car Lax bloque les requêtes POST cross-origin avec cookies.
- **Rate limiting** : 3 magic links par email par heure sur `/auth/magic-link` ; 10 modifications de vote par amendement par utilisateur par heure
- **Validation des motivations** : longueur max 500 caractères, échappement HTML à l'affichage (prévention XSS)
- **CORS** : configuration existante conservée
- **Nettoyage** : cron quotidien supprime les magic tokens où `used = true` OR `expires_at < now()`

---

## 9. Nouvelles tables

Deux tables à créer :

1. **`magic_tokens`** — tokens d'authentification à usage unique (voir section 2)
2. **`vote_history`** — historique des modifications de vote (voir section 4)

La table `amendments` nécessite l'ajout d'une colonne `rejection_reason` (String, nullable) pour distinguer les rejets par majorité des rejets par quorum non atteint. Les autres tables existantes restent inchangées.

---

## 10. Hors périmètre

- Audit IA multi-modèles — voir spec "Flux de proposition d'amendement, audit IA & navigation globale" (section 15)
- OAuth (Google/GitHub/X) — évolution future possible
- Notifications (nouveaux amendements, résultats) — Phase 2 ultérieure
