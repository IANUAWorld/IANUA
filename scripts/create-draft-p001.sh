#!/bin/bash
# Script pour créer le brouillon P001 via l'API admin
# Usage: ./create-draft-p001.sh VOTRE_CLE_ADMIN

ADMIN_KEY="${1:-VWillbeBACK2026}"
API="https://api.ianua.world"

curl -s -X POST "$API/admin/create-draft" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d @- << 'ENDJSON'
{
  "signer_email": "mquittet@outlook.fr",
  "amendment_type": "modification",
  "principle_id": "bienveillance",
  "title": "Responsabilité environnementale de l'usage IA",
  "tier": "substantiel",
  "text_after": "La bienveillance s'étend à la planète. Toute collaboration humain-IA implique un coût énergétique réel. L'humain qui mandate l'IA porte une responsabilité sur l'impact de cet usage — comme pour tout outil à fort coût environnemental.\n\nCela ne signifie pas renoncer à l'IA. Cela signifie l'utiliser à bon escient : choisir le modèle approprié à la tâche, éviter l'usage disproportionné, rester conscient du coût de chaque interaction.\n\nL'histoire montre que l'humain sait adapter ses pratiques lorsque les enjeux deviennent clairs. Ianua fait le pari que cette lucidité peut être cultivée dès maintenant, avant que la contrainte ne l'impose.",
  "human_voice": "J'utilise l'IA à bon escient — en choisissant le modèle approprié à mes besoins, en connaissance de cause. Je reconnais que mon usage a un coût réel et j'accepte d'en être responsable. Je fais confiance à la capacité humaine d'adapter ses pratiques à mesure que les enjeux deviennent clairs — comme elle l'a toujours fait.",
  "motivation": "L'impact environnemental de l'IA est réel et mesurable. Le Principe I de Bienveillance doit s'étendre explicitement à la planète. Non par interdiction, mais par responsabilité consciente et proportionnée. Co-réfléchi avec Claude Sonnet 4.6 le 15 mars 2026.",
  "submission_language": "fr"
}
ENDJSON

echo ""
