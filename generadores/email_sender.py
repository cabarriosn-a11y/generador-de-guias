"""Envío de correos con adjunto vía SMTP (Gmail).

Requiere:
  - Cuenta Gmail con Verificación en 2 pasos ACTIVADA
  - Contraseña de aplicación generada (16 caracteres)
    Se obtiene en: https://myaccount.google.com/apppasswords

Uso:
  enviar_correo(
      remitente="tu@gmail.com",
      contrasena_app="xxxx xxxx xxxx xxxx",
      destinatario="aprendiz@correo.com",
      asunto="Plan de Trabajo",
      cuerpo_html="<p>Hola...</p>",
      adjuntos=["/ruta/plan.pdf"],
  )
"""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import List, Optional

# Configuración por defecto para Gmail
SMTP_HOST_GMAIL = "smtp.gmail.com"
SMTP_PORT_GMAIL = 587


def enviar_correo(
    remitente: str,
    contrasena_app: str,
    destinatario: str,
    asunto: str,
    cuerpo_html: str,
    adjuntos: Optional[List[str]] = None,
    nombre_remitente: Optional[str] = None,
    smtp_host: str = SMTP_HOST_GMAIL,
    smtp_port: int = SMTP_PORT_GMAIL,
) -> None:
    """Envía UN correo con adjuntos. Lanza excepción si falla."""
    msg = MIMEMultipart("mixed")
    msg["From"] = f"{nombre_remitente} <{remitente}>" if nombre_remitente else remitente
    msg["To"] = destinatario
    msg["Subject"] = asunto

    # Cuerpo HTML
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(cuerpo_html, "html", "utf-8"))
    msg.attach(alternative)

    # Adjuntos
    for adjunto in adjuntos or []:
        p = Path(adjunto)
        if not p.exists():
            continue
        part = MIMEBase("application", "octet-stream")
        with open(p, "rb") as f:
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{p.name}"')
        msg.attach(part)

    # Enviar
    contexto_ssl = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as servidor:
        servidor.starttls(context=contexto_ssl)
        servidor.login(remitente, contrasena_app.replace(" ", ""))
        servidor.send_message(msg)


def probar_conexion(remitente: str, contrasena_app: str,
                    smtp_host: str = SMTP_HOST_GMAIL,
                    smtp_port: int = SMTP_PORT_GMAIL) -> tuple[bool, str]:
    """Prueba que las credenciales SMTP funcionen. Retorna (ok, mensaje)."""
    try:
        contexto_ssl = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as servidor:
            servidor.starttls(context=contexto_ssl)
            servidor.login(remitente, contrasena_app.replace(" ", ""))
        return True, "Conexión y autenticación exitosas."
    except smtplib.SMTPAuthenticationError as e:
        return False, ("Autenticación fallida. Verifica que hayas usado una CONTRASEÑA DE "
                       "APLICACIÓN (16 caracteres) y no tu contraseña normal de Gmail. "
                       f"Detalle: {e}")
    except Exception as e:
        return False, f"Error de conexión: {e}"


def plantilla_correo_plan_trabajo(nombre_aprendiz: str, nombre_instructor: str,
                                   programa: str, competencia: str) -> str:
    """Devuelve el cuerpo HTML del correo con el plan de trabajo adjunto."""
    return f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #2C2C2C; line-height: 1.5;">
        <p>Apreciado(a) <b>{nombre_aprendiz}</b>,</p>

        <p>Espero se encuentre muy bien. Le adjunto en este correo su
        <b>Plan de Trabajo Individual</b> correspondiente al programa
        <i>{programa}</i>, competencia <i>{competencia}</i>.</p>

        <p>En el documento encontrará:</p>
        <ul>
          <li>El cronograma de las 4 actividades a desarrollar</li>
          <li>Las fechas de inicio y entrega de cada actividad</li>
          <li>Un espacio para registrar el estado de entrega</li>
        </ul>

        <p>Le solicito revisarlo con atención, firmarlo y devolverlo por este
        mismo medio para constancia. Cualquier duda me la puede consultar
        directamente.</p>

        <p>Éxitos en su proceso de formación.</p>

        <p>Cordialmente,<br>
        <b>{nombre_instructor}</b><br>
        Instructor SENA</p>

        <hr style="border: none; border-top: 1px solid #D0D0D0; margin: 20px 0;">
        <p style="font-size: 11px; color: #888;">
          Este correo fue enviado desde el sistema Generador de Guías SENA.
        </p>
      </body>
    </html>
    """
