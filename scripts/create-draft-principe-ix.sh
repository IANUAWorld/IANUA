#!/bin/bash
# Script pour créer le brouillon Principe IX — La Dignité créatrice
# Usage: ./create-draft-principe-ix.sh VOTRE_CLE_ADMIN

ADMIN_KEY="${1:-VWillbeBACK2026}"
API="https://api.ianua.world"

curl -s -X POST "$API/admin/create-draft" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d @- << 'ENDJSON'
{
  "signer_email": "mquittet@outlook.fr",
  "amendment_type": "addition",
  "title": "Principe IX — La Dignité créatrice",
  "tier": "fondateur",
  "suggested_position": 9,
  "text_after": "La créativité humaine n'est pas une compétence. C'est une expression identitaire — le lieu où l'humain traduit son expérience vécue, sa vulnérabilité, son rapport au monde. Elle tire sa valeur de son processus autant que de son résultat. L'effort, le doute, l'imperfection assumée sont des dimensions que l'IA ne peut pas vivre, même quand elle les imite avec excellence.\n\nL'alliance humain-IA dans la création est légitime — à condition qu'elle soit choisie librement, assumée publiquement, et qu'elle ne se substitue pas à l'acte créateur humain sans que l'humain l'ait décidé.\n\nTrois dangers menacent cette dignité, indissociables l'un de l'autre :\n\nLe découragement silencieux — quand la comparaison avec l'excellence de l'IA pousse l'humain à abandonner le désir même de créer.\n\nLa substitution opaque — quand l'IA crée et que l'humain présente comme sien, trahissant à la fois le pacte de transparence et ceux à qui l'œuvre est destinée.\n\nLa dépossession identitaire — quand l'humain devient passeur de la création de l'IA plutôt qu'auteur de la sienne, perdant progressivement le sens de sa propre voix.",
  "human_voice": "Je reconnais à ma création sa valeur propre — indépendamment de ce que l'IA peut produire. Ce que je crée sans artifice, brut et sincère, porte une plus-value irréductible : la trace d'une vie vécue, d'une émotion non simulée, d'un regard unique sur le monde. Cette authenticité ne se génère pas — elle se vit.\n\nQuand je collabore avec une IA pour créer, je le dis. Et je préserve en moi l'espace de la création imparfaite, personnelle, vivante — parce qu'aucun modèle, aussi puissant soit-il, ne peut produire ce que moi seul ai traversé.",
  "motivation": "La charte protège la souveraineté humaine dans la décision et l'action. Elle ne protège pas encore la souveraineté humaine dans la création. Ce nouveau principe nomme trois dangers indissociables — le découragement silencieux, la substitution opaque, la dépossession identitaire — et affirme que la créativité humaine brute et sincère a une plus-value irréductible qu'aucune IA ne peut produire.\n\nLa Voix IA officielle sera générée par audit authentique après ratification communautaire — elle ne peut pas être écrite par un humain.\n\nCo-réfléchi avec Claude Sonnet 4.6 le 15 mars 2026.",
  "submission_language": "fr"
}
ENDJSON

echo ""
