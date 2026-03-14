import os
import httpx

# Try BREVO_API_KEY first, fallback to BREVO_SMTP_PASS (Railway env var workaround)
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "") or os.getenv("BREVO_SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "ianua@outlook.fr")
FROM_NAME = os.getenv("FROM_NAME", "Ianua")
API_URL = os.getenv("API_URL", "https://api.ianua.world")

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"

TEMPLATES = {
    "fr": {
        "subject": "Ianua — Confirmez votre inscription",
        "body": """Merci de rejoindre Ianua.

Pour confirmer votre inscription, cliquez ici :
{confirm_url}

Ce lien est valable 72 heures.

— Ianua · ianua.world""",
    },
    "en": {
        "subject": "Ianua — Confirm your subscription",
        "body": """Thank you for joining Ianua.

To confirm your subscription, click here:
{confirm_url}

This link is valid for 72 hours.

— Ianua · ianua.world""",
    },
    "es": {
        "subject": "Ianua — Confirme tu suscripción",
        "body": """Gracias por unirte a Ianua.

Para confirmar tu suscripción, haz clic aquí:
{confirm_url}

Este enlace es válido durante 72 horas.

— Ianua · ianua.world""",
    },
}

UNSUBSCRIBE_FOOTER = {
    "fr": "\n\n---\nPour vous désinscrire : {unsubscribe_url}",
    "en": "\n\n---\nTo unsubscribe: {unsubscribe_url}",
    "es": "\n\n---\nPara darse de baja: {unsubscribe_url}",
}


async def _send_via_brevo(to_email: str, subject: str, text_content: str) -> bool:
    """Send email via Brevo HTTP API (port 443, never blocked)."""
    if not BREVO_API_KEY:
        print("[EMAIL ERROR] BREVO_API_KEY not set")
        return False

    payload = {
        "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text_content,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                BREVO_SEND_URL,
                json=payload,
                headers={
                    "api-key": BREVO_API_KEY,
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code in (200, 201):
                print(f"[EMAIL OK] Sent to {to_email}")
                return True
            else:
                print(f"[EMAIL ERROR] Brevo {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


async def send_confirmation_email(email: str, token: str, lang: str = "fr") -> bool:
    if lang not in TEMPLATES:
        lang = "en"

    confirm_url = f"{API_URL}/confirm/{token}"
    unsubscribe_url = f"{API_URL}/unsubscribe/{token}"

    template = TEMPLATES[lang]
    body = template["body"].format(confirm_url=confirm_url)
    body += UNSUBSCRIBE_FOOTER[lang].format(unsubscribe_url=unsubscribe_url)

    return await _send_via_brevo(email, template["subject"], body)


# ── Signature confirmation ────────────────────────

SIGNATURE_TEMPLATES = {
    "fr": {
        "subject": "Ianua — Confirmez votre soutien",
        "body": """Merci {pseudo} de soutenir la démarche Ianua.

Pour confirmer votre signature, cliquez ici :
{confirm_url}

Ce lien est valable 72 heures.

— Ianua · ianua.world""",
    },
    "en": {
        "subject": "Ianua — Confirm your support",
        "body": """Thank you {pseudo} for supporting the Ianua initiative.

To confirm your signature, click here:
{confirm_url}

This link is valid for 72 hours.

— Ianua · ianua.world""",
    },
    "es": {
        "subject": "Ianua — Confirme su apoyo",
        "body": """Gracias {pseudo} por apoyar la iniciativa Ianua.

Para confirmar su firma, haga clic aquí:
{confirm_url}

Este enlace es válido durante 72 horas.

— Ianua · ianua.world""",
    },
}


# ── Magic link authentication ────────────────────
MAGIC_LINK_TEMPLATES = {
    "fr": {
        "subject": "Ianua — Votre lien de connexion",
        "body": """Pour vous connecter et voter sur les amendements, cliquez ici :
{magic_url}

Ce lien est valable 15 minutes et utilisable une seule fois.

— Ianua · ianua.world""",
    },
    "en": {
        "subject": "Ianua — Your login link",
        "body": """To log in and vote on amendments, click here:
{magic_url}

This link is valid for 15 minutes and can only be used once.

— Ianua · ianua.world""",
    },
    "es": {
        "subject": "Ianua — Su enlace de conexion",
        "body": """Para conectarse y votar sobre las enmiendas, haga clic aqui:
{magic_url}

Este enlace es valido durante 15 minutos y solo se puede usar una vez.

— Ianua · ianua.world""",
    },
}


async def send_magic_link_email(email: str, token: str, lang: str = "fr") -> bool:
    if lang not in MAGIC_LINK_TEMPLATES:
        lang = "en"

    magic_url = f"{API_URL}/auth/verify/{token}"
    template = MAGIC_LINK_TEMPLATES[lang]
    body = template["body"].format(magic_url=magic_url)

    return await _send_via_brevo(email, template["subject"], body)


# ── Tier requalification notification ─────────────
TIER_REQUALIFIED_TEMPLATES = {
    "fr": {
        "subject": "Ianua — Palier de votre proposition requalifie",
        "body": """Votre proposition [{code}] "{title}" a ete requalifiee.

Ancien palier : {old_tier}
Nouveau palier : {new_tier}
Raison : {reason}

Consultez la gouvernance : {base_url}/gouvernance

— Ianua · ianua.world""",
    },
    "en": {
        "subject": "Ianua — Your proposal tier was requalified",
        "body": """Your proposal [{code}] "{title}" has been requalified.

Previous tier: {old_tier}
New tier: {new_tier}
Reason: {reason}

View governance: {base_url}/gouvernance

— Ianua · ianua.world""",
    },
    "es": {
        "subject": "Ianua — Nivel de su propuesta reclasificado",
        "body": """Su propuesta [{code}] "{title}" ha sido reclasificada.

Nivel anterior: {old_tier}
Nuevo nivel: {new_tier}
Razon: {reason}

Ver gobernanza: {base_url}/gouvernance

— Ianua · ianua.world""",
    },
}

# ── Abuse deletion notification ───────────────────
ABUSE_DELETION_TEMPLATES = {
    "fr": {
        "subject": "Ianua — Votre proposition a ete supprimee",
        "body": """Votre proposition [{code}] "{title}" a ete supprimee pour le motif suivant :

{reason}

Voie : {via}

Le log de cette action est consultable publiquement sur :
{base_url}/transparence

— Ianua · ianua.world""",
    },
    "en": {
        "subject": "Ianua — Your proposal has been removed",
        "body": """Your proposal [{code}] "{title}" has been removed for the following reason:

{reason}

Via: {via}

The log of this action is publicly available at:
{base_url}/transparence

— Ianua · ianua.world""",
    },
    "es": {
        "subject": "Ianua — Su propuesta ha sido eliminada",
        "body": """Su propuesta [{code}] "{title}" ha sido eliminada por el siguiente motivo:

{reason}

Via: {via}

El registro de esta accion esta disponible publicamente en:
{base_url}/transparence

— Ianua · ianua.world""",
    },
}

BASE_URL_FOR_TEMPLATES = os.getenv("BASE_URL", "https://ianua.world")


async def send_tier_requalified_email(email: str, code: str, title: str, old_tier: str, new_tier: str, reason: str, lang: str = "fr") -> bool:
    if lang not in TIER_REQUALIFIED_TEMPLATES:
        lang = "en"
    template = TIER_REQUALIFIED_TEMPLATES[lang]
    body = template["body"].format(code=code, title=title, old_tier=old_tier, new_tier=new_tier, reason=reason, base_url=BASE_URL_FOR_TEMPLATES)
    return await _send_via_brevo(email, template["subject"], body)


async def send_abuse_deletion_email(email: str, code: str, title: str, reason: str, via: str, lang: str = "fr") -> bool:
    if lang not in ABUSE_DELETION_TEMPLATES:
        lang = "en"
    template = ABUSE_DELETION_TEMPLATES[lang]
    body = template["body"].format(code=code, title=title, reason=reason, via=via, base_url=BASE_URL_FOR_TEMPLATES)
    return await _send_via_brevo(email, template["subject"], body)


async def send_signature_confirmation(email: str, pseudo: str, token: str, lang: str = "fr") -> bool:
    if lang not in SIGNATURE_TEMPLATES:
        lang = "en"

    confirm_url = f"{API_URL}/signatures/confirm/{token}"

    template = SIGNATURE_TEMPLATES[lang]
    body = template["body"].format(confirm_url=confirm_url, pseudo=pseudo)

    return await _send_via_brevo(email, template["subject"], body)
