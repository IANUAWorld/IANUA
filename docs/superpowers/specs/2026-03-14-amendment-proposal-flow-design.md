# Design — Flux de proposition d'amendement, audit IA & navigation globale

**Date** : 2026-03-14
**Projet** : IANUA (ianua.world)
**Périmètre** : Proposition d'amendement auto-gouvernée + audit IA multi-modèles + navigation globale Phase 2
**Prérequis** : Spec "Vote communautaire sur les amendements" (2026-03-14)

---

## 1. Contexte et contrainte fondatrice

En Phase 2, IANUA passe en auto-gouvernance. Il n'y a plus d'admin politique. Le cycle de vie des amendements est 100% automatique et communautaire.

**Rôle de l'admin technique (Max)** : infrastructure, sécurité, anti-abus, déploiement. Aucune intervention sur le cycle de vie des amendements, sauf suppression pour abus (loggée publiquement).

---

## 2. Cycle de vie d'un amendement

```
brouillon → proposition → (seuil de soutiens) → délibération → (vote) → ratifié/rejeté
                              ↓ (délai expiré)
                            expiré
```

| Statut | Visibilité | Modifiable | Durée |
|--------|-----------|------------|-------|
| `draft` | Auteur uniquement (+ lien token partageable) | Oui, librement | Illimitée |
| `proposed` | Public | Non (texte gelé) | Selon palier (60/90/120 jours) |
| `deliberation` | Public | Non | Automatique selon palier (14j/21j/30j) |
| `withdrawn` | Public | Non | Permanent |
| `deleted` | Public (métadonnées uniquement) | Non | Permanent — contenu supprimé, motif visible via `admin_actions` |
| `ratified` / `rejected` | Public | Non | Permanent |
| `expired` | Public | Non | Permanent |

La transition `proposed → deliberation` déclenche automatiquement l'ouverture du vote : `vote_opened_at = now()` et `vote_closed_at = now() + durée_délibération`. Durées automatiques par palier :

| Palier | Durée de délibération |
|--------|----------------------|
| Mineur | 14 jours |
| Substantiel | 21 jours |
| Fondateur | 30 jours |

**Note** : ceci remplace la mention "définis par l'admin" de la spec de vote — en Phase 2 le cycle est 100% automatique.

### Retrait par l'auteur

L'auteur peut retirer sa proposition à tout moment tant que `status = proposed` :
- Le statut passe à `withdrawn`
- Les soutiens, contestations et signalements existants sont conservés (pour l'historique) mais deviennent inactifs
- La proposition reste visible dans le registre avec le badge "Retiré"
- L'auteur peut resoumettre un nouveau brouillon sur le même sujet (pas de lien technique avec la proposition retirée)

### Règles de participation de l'auteur

- L'auteur d'une proposition **ne peut pas soutenir** son propre amendement (le soutien mesure l'intérêt de la communauté, pas celui de l'auteur)
- L'auteur **peut voter** sur son propre amendement une fois en délibération (le vote est un acte citoyen, chaque signataire a le même droit)

---

## 3. Types d'amendement

Le proposant déclare le type au moment de la création :

### Type 1 — Modification

- Principe existant sélectionné dans la liste des 8 principes (ou "transversal")
- Texte actuel prérempli automatiquement depuis la charte (non modifiable)
- Texte proposé en champ libre (remplace le texte actuel)
- Diff visuel généré automatiquement à l'affichage

### Type 2 — Ajout

- Aucun principe existant sélectionné
- Pas de champ "texte actuel"
- Champ "texte du nouveau principe" + position suggérée dans la charte
- **Palier automatiquement forcé à Fondateur minimum** (non négociable, pas d'intervention admin)

### Type 3 — Suppression

- Principe existant sélectionné
- Texte proposé vide
- Champ "justification" obligatoire
- **Palier automatiquement forcé à Fondateur minimum** (non négociable, pas d'intervention admin)

---

## 4. Formulaire de proposition

Champs du formulaire sur `proposer.html` :

| Champ | Type | Requis | Notes |
|-------|------|--------|-------|
| Type d'amendement | Select | Oui | Modification / Ajout / Suppression |
| Titre | String (max 120 chars) | Oui | |
| Principe(s) concerné(s) | Select multiple | Oui (sauf Ajout) | Liste des 8 principes + "transversal" |
| Texte actuel | Text (readonly) | Auto | Prérempli depuis la charte, absent pour Ajout |
| Texte proposé | Text (max 2000 chars) | Oui (sauf Suppression) | Pour Ajout : "texte du nouveau principe" |
| Position suggérée | Select | Ajout uniquement | Après quel principe existant |
| Justification | Text (max 500 chars) | Suppression uniquement | Obligatoire pour le type Suppression |
| Motivation | Text (max 1000 chars) | Oui | Pourquoi ce changement améliore la charte |
| Palier déclaré | Select | Oui | Mineur / Substantiel / Fondateur — avec définitions affichées. Forcé à Fondateur pour Ajout/Suppression |
| Langue de soumission | Select | Oui | FR / EN / ES — la traduction dans les autres langues est de la responsabilité de la communauté avant ratification |

---

## 5. Phase brouillon

### Règles

- L'auteur peut avoir jusqu'à **5 brouillons actifs** en parallèle
- Chaque brouillon est privé par défaut
- Modification libre tant que `status = draft`
- Prévisualisation du diff avant soumission
- Une fois soumis (`status = proposed`), le texte est gelé

### Partage par lien token

- L'auteur peut générer un lien de partage pour chaque brouillon
- Le lien contient un UUID non devinable (même principe que le magic link)
- **Pas d'auth requise pour lire** un brouillon partagé — mais impossible à indexer/découvrir sans le lien
- Le destinataire peut laisser un **commentaire privé** (visible uniquement par l'auteur)
- Pas de soutien possible au stade brouillon

### Table `draft_share_tokens` (nouvelle)

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer | PK |
| `amendment_id` | Integer | FK → `amendments.id` |
| `token` | String | UUID unique |
| `created_at` | DateTime | Horodatage |

Index unique sur `token`. Les tokens de partage sont automatiquement invalidés (requêtes retournent 404) quand le brouillon n'est plus en statut `draft`.

### Table `draft_comments` (nouvelle)

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer | PK |
| `amendment_id` | Integer | FK → `amendments.id` |
| `author_name` | String(100) | Nom libre auto-déclaré (pas forcément signataire) |
| `comment` | Text | Max 500 chars, échappement HTML, trimming espaces |
| `created_at` | DateTime | Horodatage |

---

## 6. Phase proposition — soutiens

### Mécanique de soutien

- Bouton unique "Soutenir cette proposition" — filtre positif, pas de bouton "S'opposer"
- Le soutien signifie "cette proposition mérite d'être débattue", pas "je suis pour"
- Motivation optionnelle (max 500 chars)
- Un signataire ne peut soutenir qu'une fois par proposition
- Les soutiens sont publics (qui a soutenu, motivation si fournie)

### Table `amendment_supports` (nouvelle)

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer | PK |
| `amendment_id` | Integer | FK → `amendments.id` |
| `signer_id` | Integer | FK → signataires confirmés |
| `comment` | Text | Motivation optionnelle, max 500 chars |
| `created_at` | DateTime | Horodatage |

Contrainte unique : `(amendment_id, signer_id)` — un signataire ne peut soutenir qu'une fois.
Index sur `amendment_id`.

### Seuils de recevabilité

Adaptatifs (% des signataires confirmés) avec plancher minimum, modulés par palier :

| Palier | Seuil | Plancher | Délai d'expiration |
|--------|-------|----------|--------------------|
| Mineur | 5% | 3 | 60 jours |
| Substantiel | 10% | 10 | 90 jours |
| Fondateur | 20% | 25 | 120 jours |

**Calcul** : le seuil effectif est `max(plancher, ceil(pourcentage * nb_signataires_confirmes))`.

**Transition automatique** : quand le seuil est atteint, le statut passe à `deliberation`, `vote_opened_at = now()` et `vote_closed_at = now() + durée du palier` (14j/21j/30j). Le vote s'ouvre automatiquement sans intervention admin.

**Expiration automatique** : un cron job vérifie les propositions dont `proposed_at + délai < now()` et les passe en statut `expired`.

---

## 7. Contestation de palier

### Flux hybride

1. Bouton "Contester le palier" visible sur toute proposition publique, accessible aux signataires vérifiés
2. Le contestataire choisit le palier qu'il estime correct (**supérieur uniquement** — on ne peut pas déclasser)
3. Un signataire ne peut contester qu'une fois par proposition
4. Les contestations sont publiques (qui a contesté, quel palier suggéré)
5. Quand 3 contestations atteintes :
   - **Convergence** (3 sur le même palier) → requalification automatique, loggée publiquement, auteur notifié par email
   - **Divergence** → notification à l'admin technique qui tranche, décision loggée publiquement avec motif
6. L'auteur peut retirer sa proposition et la resoumettre avec le bon palier (reset du compteur de soutiens)

### Règle automatique

Les amendements de type Ajout ou Suppression sont forcés au palier Fondateur. Ils ne peuvent pas être contestés vers le bas — la contestation est désactivée pour ces types.

### Table `tier_challenges` (nouvelle)

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer | PK |
| `amendment_id` | Integer | FK → `amendments.id` |
| `challenger_id` | Integer | FK → signataires confirmés |
| `suggested_tier` | String(20) | `SUBSTANTIEL` / `FONDATEUR` |
| `created_at` | DateTime | Horodatage |

Contrainte unique : `(amendment_id, challenger_id)`.
Index sur `amendment_id`.

### Champs ajoutés à la table `amendments`

| Colonne | Type | Description |
|---------|------|-------------|
| `tier_requalified` | Boolean | Default `false`, `true` si palier requalifié |
| `tier_requalified_by` | String(20) | `auto` (convergence) ou `admin` |
| `tier_requalified_at` | DateTime | Horodatage de la requalification |
| `tier_original` | String(20) | Palier d'origine avant requalification |

---

## 8. Suppression pour abus

### Voie 1 — Signalement communautaire (cas ambigus)

- Bouton "Signaler" accessible à tout signataire vérifié
- Catégories : `spam` / `hors_charte` / `contenu_inapproprie`
- Seuil : 3 signalements → notification admin technique par email
- L'admin examine et décide : supprimer ou rejeter les signalements (avec motif dans les deux cas)
- La proposition reste visible pendant l'examen (pas de suspension automatique)

### Voie 2 — Action directe admin (urgences)

- Spam évident, contenu illégal, attaque de la plateforme
- L'admin peut supprimer immédiatement sans seuil
- Obligation identique : motif écrit public + log horodaté

### Règles communes

- La suppression est irréversible
- L'auteur est notifié par email avec le motif
- Le log public affiche : date, motif, voie utilisée (signalement communautaire ou action directe)

### Table `content_reports` (nouvelle)

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer | PK |
| `amendment_id` | Integer | FK → `amendments.id` |
| `reporter_id` | Integer | FK → signataires confirmés |
| `category` | String(30) | `spam` / `hors_charte` / `contenu_inapproprie` |
| `created_at` | DateTime | Horodatage |

Contrainte unique : `(amendment_id, reporter_id)` — un signataire ne peut signaler qu'une fois.

### Table `admin_actions` (nouvelle)

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer | PK |
| `amendment_id` | Integer | FK → `amendments.id` |
| `action` | String(30) | `deleted` / `reports_dismissed` / `tier_requalified` / `audit_published` / `audit_rejected` |
| `reason` | Text | Motif écrit obligatoire |
| `via` | String(20) | `community_report` / `direct_action` / `audit` |
| `audit_response_id` | Integer | FK → `audit_responses.id`, nullable. Renseigné uniquement pour `audit_unpublished` |
| `acted_at` | DateTime | Horodatage |

### Page `transparence.html`

Page publique listant toutes les entrées de `admin_actions`, triées par date décroissante. Accessible depuis le footer de `gouvernance.html`. Affiche pour chaque action : date, amendement concerné, action prise, motif, voie utilisée.

---

## 9. Interface — `proposer.html`

### Structure (auth requise)

1. **Header** : fil d'Ariane "Gouvernance > Proposer", état de connexion, lien retour
2. **Mes brouillons** : liste des brouillons de l'auteur connecté (max 5), actions : éditer, prévisualiser diff, partager, supprimer, soumettre
3. **Nouveau brouillon** : bouton ouvrant le formulaire de proposition (section 4)
4. **Mes propositions soumises** : suivi des propositions publiées — compteur de soutiens, contestations, statut actuel
5. **Ancrage** : `proposer.html#P00X` pour accéder directement à une proposition (lien depuis `gouvernance.html`)

### État non connecté

Redirection vers la page de connexion (magic link) avec retour vers `proposer.html` après authentification.

---

## 10. Intégration avec `gouvernance.html`

### Registre enrichi

Le registre affiche désormais tous les statuts :

| Statut | Badge | Action |
|--------|-------|--------|
| `proposed` | "Proposition" + compteur soutiens + délai restant | "Soutenir →" (action directe si connecté, sinon redirige vers connexion) |
| `deliberation` | "Délibération" + compteur votes + date clôture | "Voter →" (redirige vers `vote.html#A00X`) |
| `ratified` | "Ratifié" + compteurs définitifs | Lecture seule |
| `rejected` | "Rejeté" (+ "quorum non atteint" si applicable) | Lecture seule |
| `expired` | "Expiré" + compteur soutiens atteints / requis | Lecture seule |
| `withdrawn` | "Retiré" | Lecture seule |
| `deleted` | "Supprimé — [motif]" (lien vers transparence.html) | Lecture seule |

### Nouveaux éléments

- Bouton "Proposer un amendement →" en haut du registre (redirige vers `proposer.html`)
- Lien "Transparence" dans le footer (vers `transparence.html`)

---

## 11. Navigation globale Phase 2

### Parcours signataire

Le menu hamburger et la navigation reflètent l'entonnoir d'engagement :

```
Lire (index.html) → Participer (gouvernance.html) → Soutenir/Proposer (proposer.html) → Voter (vote.html)
```

### État de connexion global

Le JWT cookie (httpOnly) est lu sur toutes les pages. Si connecté :
- Header affiche le nom du signataire + lien "Déconnexion"
- Cohérent sur `index.html`, `gouvernance.html`, `vote.html`, `proposer.html`

Si non connecté :
- Header affiche "Se connecter" (magic link)

### Fil d'Ariane

Présent sur les pages d'action, une ligne, toujours visible :
- `Gouvernance › Voter › A003`
- `Gouvernance › Proposer › Brouillon`
- `Gouvernance › Proposer › P005`
- `Gouvernance › Transparence`

### CTAs contextuels sur `gouvernance.html`

Les badges du registre sont les vraies portes d'entrée vers l'action :
- Proposition active → badge "Soutenir →" avec compteur
- Amendement en délibération → badge "Voter →" avec compteur et date clôture
- Amendement ratifié/rejeté → badge statut final

### Page `transparence.html`

- Accessible depuis le footer de `gouvernance.html` (pas dans la nav principale)
- Log public des actions admin (suppressions, rejets de signalements, requalifications de palier)

---

## 12. Endpoints API (FastAPI)

### Brouillons (auth requise)

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/amendments/drafts` | Liste des brouillons de l'auteur connecté |
| `POST` | `/amendments/drafts` | Crée un nouveau brouillon. Limite : 5 actifs |
| `PUT` | `/amendments/drafts/{id}` | Modifie un brouillon |
| `DELETE` | `/amendments/drafts/{id}` | Supprime un brouillon |
| `POST` | `/amendments/drafts/{id}/submit` | Soumet le brouillon → statut `proposed`, texte gelé |
| `POST` | `/amendments/drafts/{id}/share` | Génère un lien token de partage |

### Brouillons partagés (pas d'auth)

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/amendments/shared/{token}` | Lecture d'un brouillon partagé via token |
| `POST` | `/amendments/shared/{token}/comments` | Ajoute un commentaire privé sur un brouillon partagé |

### Amendements publics (lecture sans auth)

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/amendments/public` | Liste de tous les amendements non-brouillon (proposed, deliberation, ratified, rejected, expired, withdrawn). Supporte filtres par statut. Pour `gouvernance.html` |
| `GET` | `/amendments/{id}` | Détail d'un amendement spécifique (public si non-brouillon) |
| `GET` | `/amendments/{id}/supports` | Liste des soutiens d'une proposition (qui, motivation) |

### Soutiens (auth requise)

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/amendments/{id}/support` | Soutenir une proposition. Body : `{comment}` (optionnel). Erreur si déjà soutenu, si statut != `proposed`, ou si l'auteur tente de soutenir sa propre proposition |
| `POST` | `/amendments/{id}/withdraw` | Retirer sa proposition. Auteur uniquement, statut doit être `proposed` |

### Contestation de palier (auth requise)

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/amendments/{id}/challenge-tier` | Contester le palier. Body : `{suggested_tier}`. Erreur si déjà contesté, si palier suggéré <= actuel, ou si type Ajout/Suppression |
| `GET` | `/amendments/{id}/challenges` | Liste des contestations (public, sans auth) |

### Signalement (auth requise)

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/amendments/{id}/report` | Signaler une proposition. Body : `{category}`. Erreur si déjà signalé |

### Admin (auth requise + rôle admin)

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/admin/amendments/{id}/delete` | Suppression pour abus. Body : `{reason, via}` |
| `POST` | `/admin/amendments/{id}/dismiss-reports` | Rejeter les signalements. Body : `{reason}` |
| `POST` | `/admin/amendments/{id}/requalify-tier` | Requalifier le palier (si contestation divergente). Body : `{new_tier, reason}` |
| `GET` | `/admin/actions` | Log public des actions admin (accessible sans auth aussi via `/transparency/actions`) |

### Transparence (sans auth)

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/transparency/actions` | Log public de toutes les actions admin |

### Texte de la charte (sans auth)

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/charter/principles` | Liste des principes actuels de la charte avec texte (pour le préremplissage du formulaire) |

### Erreurs communes

| Code | Condition |
|------|-----------|
| 401 | Non authentifié (endpoints protégés) |
| 403 | Non autorisé (action admin sans rôle admin) |
| 404 | Ressource non trouvée |
| 409 | Conflit (déjà soutenu, déjà contesté, déjà signalé, statut incompatible) |
| 422 | Données invalides (palier <= actuel, type invalide, champ manquant) |
| 429 | Rate limit dépassé |

---

## 13. Nouvelles tables

| Table | Description |
|-------|-------------|
| `draft_share_tokens` | Tokens de partage de brouillons (section 5) |
| `draft_comments` | Commentaires privés sur brouillons partagés (section 5) |
| `amendment_supports` | Soutiens communautaires des propositions (section 6) |
| `tier_challenges` | Contestations de palier (section 7) |
| `content_reports` | Signalements communautaires (section 8) |
| `admin_actions` | Log public des actions admin (section 8) |
| `audit_responses` | Réponses d'audit IA multi-modèles (section 15) |

### Colonnes ajoutées à `amendments`

| Colonne | Type | Description |
|---------|------|-------------|
| `amendment_type` | String(20) | `modification` / `addition` / `deletion` |
| `proposed_at` | DateTime | Horodatage de la soumission |
| `expires_at` | DateTime | Date d'expiration (calculée : `proposed_at + délai du palier`) |
| `author_id` | Integer | FK → signataires confirmés |
| `suggested_position` | Integer | Position suggérée (type Ajout uniquement) |
| `submission_language` | String(2) | `fr` / `en` / `es` |
| `tier_requalified` | Boolean | Default `false` |
| `tier_requalified_by` | String(20) | `auto` / `admin` |
| `tier_requalified_at` | DateTime | Horodatage |
| `tier_original` | String(20) | Palier d'origine avant requalification |
| `deletion_justification` | Text | Obligatoire pour type Suppression |
| `rejection_reason` | String(30) | Nullable. `quorum_not_met` si rejeté pour quorum (cf. spec vote) |
| `withdrawn_at` | DateTime | Horodatage du retrait par l'auteur |
| `deliberation_duration_days` | Integer | Durée auto selon palier : 14/21/30 jours |

---

## 14. Crons automatiques

| Cron | Fréquence | Action |
|------|-----------|--------|
| Expiration des propositions | Toutes les heures | Passe en `expired` les propositions où `expires_at <= now()` et `status = 'proposed'` |
| Clôture des votes | Toutes les heures | Évalue les résultats des amendements où `vote_closed_at <= now()` et `status = 'deliberation'` (voir spec vote) |
| Nettoyage magic tokens | Quotidien | Supprime tokens où `used = true` OR `expires_at < now()` |

---

## 15. Audit IA multi-modèles

### Philosophie

Les voix IA participent à la délibération comme éclaireurs transparents et auditables, pas comme décideurs. Elles n'ont aucun poids dans le calcul du seuil de ratification.

### Déclenchement

- Seul l'admin technique peut lancer un audit IA sur un amendement (bouton "Lancer l'audit IA" dans le dashboard admin)
- Disponible dès qu'un amendement est en statut `proposed` ou `deliberation`
- **Un audit par amendement par modèle** — pas de doublon pour le même modèle sur le même amendement
- L'admin sélectionne les modèles à interroger parmi la liste disponible

### Modèles interrogés

| Modèle | Provider |
|--------|----------|
| Claude | Anthropic |
| GPT-4o | OpenAI |
| Gemini | Google |
| Mistral Large | Mistral |
| Grok | xAI |
| Llama | Meta (via API) |

### Protocole d'audit

1. L'admin sélectionne un amendement et les modèles à interroger
2. Un **prompt identique** est envoyé à chaque modèle sélectionné
3. Le prompt ne contient **aucun framing Ianua** — l'IA répond de façon authentique, sans biais de conformité
4. Le texte exact du prompt est stocké et affiché publiquement avec les résultats (transparence totale)
5. Les appels API sont effectués séquentiellement côté backend (pas de contrainte de temps réel)
6. Le champ `model_version` est auto-renseigné par le backend depuis les métadonnées de la réponse API (ex: header `x-model-version`, champ `model` dans la réponse)
7. **En cas d'erreur API** (timeout, rate limit provider, réponse malformée) : aucune ligne n'est créée dans `audit_responses`. L'admin est informé de l'échec et peut relancer. Les modèles ayant répondu avec succès sont enregistrés normalement

### Publication

- Par défaut, chaque réponse est **non publiée** (`published = false`) — l'admin doit publier explicitement
- L'admin examine chaque réponse et décide de publier ou non
- **Toute décision** (publier OU ne pas publier) est **loggée dans `admin_actions`** avec motif — pas de censure silencieuse, transparence dans les deux sens
- Une réponse publiée est **immuable** — aucune modification possible après publication

### Table `audit_responses` (nouvelle)

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer | PK |
| `amendment_id` | Integer | FK → `amendments.id` |
| `model_name` | String(50) | Nom du modèle (ex: `claude`, `gpt-4o`) |
| `model_version` | String(50) | Version exacte utilisée |
| `prompt_used` | Text | Texte exact du prompt envoyé |
| `response_text` | Text | Réponse complète du modèle |
| `published` | Boolean | Default `false`. L'admin publie explicitement via endpoint dédié |
| `publication_decision_logged` | Boolean | Default `false`. `true` une fois la décision (publier ou non) loggée dans `admin_actions` |
| `audited_at` | DateTime | Horodatage de l'audit |

Contrainte unique : `(amendment_id, model_name)` — un seul audit par modèle par amendement.
Index sur `amendment_id`.

### Affichage

- Sur `gouvernance.html` et `vote.html`, sous chaque amendement ayant des audits publiés
- **Section repliable par défaut** — présente mais non intrusive
- Voix IA affichées en **cyan** (cohérent avec le design existant des voix IA sur la charte)
- Chaque voix clairement labellisée : modèle + version + date d'audit
- Le prompt utilisé est affiché en en-tête de la section (identique pour tous les modèles)
- Mention explicite : "Les voix IA éclairent la délibération mais ne participent pas au vote"

### Endpoints API

| Méthode | Route | Auth | Description |
|---------|-------|------|-------------|
| `POST` | `/admin/amendments/{id}/audit` | Admin | Lance un audit. Body : `{models: ["claude", "gpt-4o", ...], prompt}` |
| `POST` | `/admin/amendments/{id}/audit/{audit_id}/publish` | Admin | Publie une réponse d'audit. Body : `{reason}`. Loggé dans `admin_actions` |
| `POST` | `/admin/amendments/{id}/audit/{audit_id}/reject` | Admin | Décide de ne pas publier. Body : `{reason}`. Loggé dans `admin_actions` |
| `GET` | `/amendments/{id}/audit-responses` | Non | Liste des réponses d'audit publiées pour un amendement |
| `GET` | `/admin/amendments/{id}/audit-responses` | Admin | Liste de toutes les réponses d'audit (publiées et non publiées) pour un amendement |

---

## 16. Sécurité

- **Auth** : magic link + JWT cookie httpOnly, SameSite=Lax, HS256 (identique à la spec vote)
- **Rate limiting** : 3 magic links/email/heure, 5 brouillons max/auteur, 1 soutien/proposition/signataire, 1 contestation/proposition/signataire, 1 signalement/proposition/signataire, 10 commentaires/IP/heure sur brouillons partagés
- **Validation** : échappement HTML sur tous les champs texte affichés publiquement, longueurs max documentées, trimming des espaces
- **Intégrité** : texte gelé dès soumission, palier Fondateur forcé automatiquement pour Ajout/Suppression
- **Transparence** : toute action admin loggée dans `admin_actions` et affichée sur `transparence.html`
- **Clés API IA** : stockées en variables d'environnement sur Railway, jamais exposées côté frontend. Les appels aux modèles sont effectués exclusivement côté backend
- **Immuabilité audit** : les réponses publiées ne peuvent pas être modifiées. La non-publication est loggée avec motif

---

## 17. Hors périmètre

- OAuth (Google/GitHub/X) — évolution future possible
- Notifications push (nouveaux amendements, résultats) — Phase 2 ultérieure
- Traduction communautaire des propositions — mécanisme à designer séparément
- Système de délégation de vote — Phase 3
