"""A003/A003-R + A004 — INSERT en statut deliberation.

A003 : Extension Principe II (désinformation & intégrité du réel)
A003-R : Ligne rouge Falsification du réel
A004 : Addition dans la Genèse (positionnement d'Ianua)

Tous en délibération — pas ratifiés.

Revision ID: 004
Revises: 003
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── A003 — Extension Principe II ──
    op.execute(
        """
        INSERT INTO amendments (
            code, principle_id, target, amendment_type,
            text_before, text_after,
            motivation, inspiration,
            source_type, proposed_by,
            phase, status, ratified_by, ratified_at,
            published_at, charte_version,
            motivation_en, motivation_es
        ) VALUES (
            'A003', 'transparence', 'principle_body', 'addition',
            NULL,
            'La transparence s''étend à l''intégrité du réel lui-même. Produire, diffuser ou amplifier des contenus qui falsifient délibérément la réalité — images, voix, vidéos, textes fabriqués — trahit le pacte à sa racine. Une IA peut imiter, simuler, créer. Elle ne peut pas mentir sur ce qui est réel.',
            'Les deepfakes, la désinformation générée par IA et la manipulation de la réalité perceptive constituent une lacune majeure d''Ianua face aux textes institutionnels (UNESCO 2021, OCDE 2024, EU AI Act 2024). La distinction fiction/tromperie est centrale : la création fictive assumée n''est pas concernée — l''intention de tromper sur le réel est la ligne rouge.',
            'Analyse comparative Ianua vs accords institutionnels — Max/Claude — 10 mars 2026',
            'founder', 'Max',
            'phase_1', 'deliberation', NULL, NULL,
            NOW(), NULL,
            'Transparency extends to the integrity of reality itself. An AI can imitate, simulate, create. It cannot lie about what is real.',
            'La transparencia se extiende a la integridad de la realidad. Una IA puede imitar, simular, crear. No puede mentir sobre lo que es real.'
        )
        """
    )

    # ── A003-R — Ligne rouge Falsification du réel ──
    op.execute(
        """
        INSERT INTO amendments (
            code, principle_id, target, amendment_type,
            text_before, text_after,
            motivation, source_type, proposed_by,
            phase, status, ratified_by, ratified_at,
            published_at, charte_version,
            motivation_en, motivation_es
        ) VALUES (
            'A003-R', NULL, 'redline', 'new_redline',
            NULL,
            'Falsification du réel — Utiliser l''IA pour produire ou amplifier des contenus qui usurpent l''identité d''une personne réelle, fabriquent des événements qui n''ont pas eu lieu, ou manipulent délibérément la perception collective de la réalité. La création fictive assumée n''est pas concernée — c''est la tromperie qui est la ligne rouge.',
            'Complément opérationnel de A003.',
            'founder', 'Max',
            'phase_1', 'deliberation', NULL, NULL,
            NOW(), NULL,
            'Operational complement to A003.',
            'Complemento operacional de A003.'
        )
        """
    )

    # ── A004 — Addition Genèse ──
    op.execute(
        """
        INSERT INTO amendments (
            code, principle_id, target, amendment_type,
            text_before, text_after,
            motivation, inspiration,
            source_type, proposed_by,
            phase, status, ratified_by, ratified_at,
            published_at, charte_version,
            motivation_en, motivation_es
        ) VALUES (
            'A004', NULL, 'global', 'addition',
            NULL,
            'Ianua ne régule pas les moyens — elle engage les personnes. Là où les institutions traitent les systèmes, les risques et les seuils techniques, Ianua traite la relation. Ce n''est pas une limite. C''est un choix fondateur. Ianua ne nomme pas les divisions humaines parce que le pacte humain-IA est précisément l''espace où elles n''ont pas de prise. Elle ne le proclame pas — elle le démontre. Par ses langues. Par son ouverture. Par la nature même de ce qu''elle est.',
            'Positionnement explicite d''Ianua par rapport aux textes institutionnels : Ianua traite la relation, pas les systèmes. Ce texte clarifie pourquoi la charte ne nomme pas les catégories humaines et affirme cette absence comme un acte fondateur.',
            'Analyse comparative Ianua vs accords institutionnels — Max/Claude — 10 mars 2026',
            'founder', 'Max',
            'phase_1', 'deliberation', NULL, NULL,
            NOW(), NULL,
            'Ianua does not regulate means — it engages people. Where institutions address systems, risks, and technical thresholds, Ianua addresses the relationship. This is not a limitation. It is a founding choice.',
            'Ianua no regula los medios — compromete a las personas. Donde las instituciones tratan los sistemas y los umbrales técnicos, Ianua trata la relación. No es una limitación. Es una elección fundadora.'
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM amendments WHERE code IN ('A003', 'A003-R', 'A004')")
