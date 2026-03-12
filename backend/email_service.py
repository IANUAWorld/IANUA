import os
import httpx

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
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


async def send_signature_confirmation(email: str, pseudo: str, token: str, lang: str = "fr") -> bool:
    if lang not in SIGNATURE_TEMPLATES:
        lang = "en"

    confirm_url = f"{API_URL}/signatures/confirm/{token}"

    template = SIGNATURE_TEMPLATES[lang]
    body = template["body"].format(confirm_url=confirm_url, pseudo=pseudo)

    return await _send_via_brevo(email, template["subject"], body)
