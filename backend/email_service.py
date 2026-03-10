import os
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.getenv("BREVO_SMTP_HOST", "smtp-relay.brevo.com")
SMTP_PORT = int(os.getenv("BREVO_SMTP_PORT", "587"))
SMTP_USER = os.getenv("BREVO_SMTP_USER", "")
SMTP_PASS = os.getenv("BREVO_SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "ianua@outlook.fr")
FROM_NAME = os.getenv("FROM_NAME", "Ianua")
API_URL = os.getenv("API_URL", "https://api.ianua.world")

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


async def send_confirmation_email(email: str, token: str, lang: str = "fr") -> bool:
    if lang not in TEMPLATES:
        lang = "en"

    confirm_url = f"{API_URL}/confirm/{token}"
    unsubscribe_url = f"{API_URL}/unsubscribe/{token}"

    template = TEMPLATES[lang]
    body = template["body"].format(confirm_url=confirm_url)
    body += UNSUBSCRIBE_FOOTER[lang].format(unsubscribe_url=unsubscribe_url)

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = email
    msg["Subject"] = template["subject"]
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASS,
            start_tls=True,
        )
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


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

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = email
    msg["Subject"] = template["subject"]
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASS,
            start_tls=True,
        )
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False
