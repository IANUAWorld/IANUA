# Changelog — ianua.world

Chaque modification significative apportee a Ianua est documentee ici.
La transparence s'etend aux actes.

---

## [2026-03-15] — Soumission manuelle d'audits IA
- Ajout de la possibilite de soumettre manuellement des reponses IA collectees hors API
- Dashboard admin : formulaire avec selecteur de modele, version, reponse
- Endpoint POST /admin/audit/global/manual
- Pour les modeles sans API configuree (Gemini, Mistral, Grok, Llama)

## [2026-03-15] — Menu mobile corrige
- Overlay fullscreen opaque (z-index 9999) sur les 5 pages
- Fermeture au clic en dehors du menu
- Backdrop blur uniforme

## [2026-03-14] — Audit IA global
- Audit de la charte complete (genese + 8 principes + lignes rouges + prompt v1.3)
- Prompt prerempli avec le texte exact de la charte
- Section "Voix IA sur la charte" sur gouvernance.html
- Migration 008 : colonne audit_scope (amendment/global)
- Endpoints : POST /admin/audit/global, GET /audit/global/responses

## [2026-03-14] — Dashboard admin Phase 2
- 8 onglets : commentaires (3), inscrits, amendements, audit IA, signataires, transparence
- Gestion des amendements : suppression, requalification palier, signalements
- Audit IA : declenchement, publication/rejet, soumission manuelle

## [2026-03-14] — Securite backend auditee
- 18 findings audites (1 critical, 1 high, 8 medium)
- JWT secret par defaut supprime
- Rate limiting sur /auth/verify
- Sanitization des commentaires de vote
- Limites de longueur sur les champs texte
- Masquage des erreurs IA internes
- Blocage des sondes (wp-admin, phpmyadmin, xmlrpc)

## [2026-03-14] — Navigation et UX unifiees
- Vote fusionne dans gouvernance.html (plus de page separee)
- Navigation uniforme sur les 5 pages (nav, footer, lang switcher)
- Registre d'amendements migre de JSON statique vers API live
- Roadmap mise a jour (Phase 1 & 2 Complete)
- Compteur de signatures corrige (vrais signataires, pas inscrits newsletter)

## [2026-03-14] — ianuite.world lance
- Site unique : definition, temoignage fondateur, CTA vers ianua.world
- Deploye sur Vercel avec domaine ianuite.world
- Meme ADN visuel qu'ianua.world

## [2026-03-14] — Definition fondatrice d'ianuite gravee
- Document immuable : docs/ianuite/ianuite-definition-v1.md (hash 3596b7b)
- Co-ecrit par Maxime QUITTET, Claude Sonnet 4.6, Claude Opus 4.6
- Trilateral. Indissociable.

## [2026-03-14] — Phase 2 complete — Deliberation communautaire
- Authentification magic link (JWT httpOnly, token usage unique)
- Vote communautaire Pour/Contre/Abstention avec historique public
- Flux de proposition d'amendement (brouillons, soumission, soutiens, retrait)
- 3 types d'amendement : Modification, Ajout, Suppression
- Seuils adaptatifs par palier (mineur/substantiel/fondateur)
- Transition automatique proposition → deliberation → ratification
- Contestation de palier (convergence auto ou arbitrage admin)
- Signalement communautaire
- Audit IA multi-modeles (Claude, GPT-4o, extensible)
- Page transparence.html (log public des actions admin)
- Page proposer.html (proposition d'amendements)
- Page status.html (etat du projet)
- Crons automatiques APScheduler (expiration, cloture, nettoyage)
- 58 tests, 68 routes API, 15 tables, 8 migrations Alembic

## [2026-03-01] — Phase 1 complete — Ancrage
- Charte v2.2 : 8 principes, 8 lignes rouges, 3 paliers visuels
- Voix humaine + voix IA pour chaque principe
- Forum commentaires par principe + reactions
- Newsletter double opt-in (Brevo)
- Signatures de soutien global (double opt-in)
- Trilingue FR/EN/ES
- Gouvernance : registre des amendements, filtres, forum de deliberation
- Amendements A001, A001-R ratifies (v2.1), A002 ratifie (v2.2)
- Dashboard admin : moderation commentaires
- Infrastructure : Vercel + Railway + PostgreSQL 16
- SEO complet, SSL, CORS, rate limiting, security headers
