import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from .models import WhatsAppSettings


logger = logging.getLogger(__name__)


class WhatsAppConfigurationError(Exception):
    pass


class WhatsAppDeliveryError(Exception):
    pass


def send_leave_notification(leave):
    config = WhatsAppSettings.get_settings()
    access_token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")
    api_version = getattr(settings, "WHATSAPP_API_VERSION", "v23.0")
    if not access_token:
        raise WhatsAppConfigurationError("WHATSAPP_ACCESS_TOKEN belum diatur pada environment server.")
    if (
        not config.sender_phone_number_id
        or not config.sender_phone_number
        or not config.kamad_phone_number
    ):
        raise WhatsAppConfigurationError("Phone Number ID, nomor pengirim, dan nomor WhatsApp Kamad harus diatur di Dashboard Admin.")
    if not config.sender_phone_number_id.isdigit():
        raise WhatsAppConfigurationError("Phone Number ID harus berupa angka dari WhatsApp Manager.")
    if not re.fullmatch(r"\+[1-9]\d{7,14}", config.sender_phone_number):
        raise WhatsAppConfigurationError("Nomor WhatsApp pengirim harus menggunakan format internasional.")
    if not re.fullmatch(r"\+[1-9]\d{7,14}", config.kamad_phone_number):
        raise WhatsAppConfigurationError("Nomor WhatsApp Kamad harus menggunakan format internasional.")
    if not re.fullmatch(r"[a-z0-9_]{1,100}", config.template_name):
        raise WhatsAppConfigurationError("Nama template WhatsApp tidak valid.")
    if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", config.template_language):
        raise WhatsAppConfigurationError("Kode bahasa template WhatsApp tidak valid.")
    if not re.fullmatch(r"v\d+\.\d+", api_version):
        raise WhatsAppConfigurationError("WHATSAPP_API_VERSION tidak valid.")

    template = {
        "name": config.template_name,
        "language": {"code": config.template_language},
        "components": [{
            "type": "body",
            "parameters": [
                {"type": "text", "text": leave.guru.nama_lengkap[:256]},
                {"type": "text", "text": leave.get_jenis_izin_display()[:256]},
                {"type": "text", "text": leave.tgl_mulai.strftime("%d-%m-%Y")},
                {"type": "text", "text": leave.tgl_selesai.strftime("%d-%m-%Y")},
            ],
        }],
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": config.kamad_phone_number.removeprefix("+"),
        "type": "template",
        "template": template,
    }
    request = Request(
        f"https://graph.facebook.com/{api_version}/{config.sender_phone_number_id}/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            error_data = json.loads(exc.read().decode("utf-8"))
            error_message = error_data.get("error", {}).get("message", "Meta menolak pengiriman pesan.")
        except (json.JSONDecodeError, AttributeError):
            error_message = "Meta menolak pengiriman pesan."
        raise WhatsAppDeliveryError(error_message) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WhatsAppDeliveryError("Tidak dapat terhubung ke WhatsApp Cloud API.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WhatsAppDeliveryError("Respons WhatsApp Cloud API tidak valid.") from exc

    if not isinstance(response_data, dict) or not response_data.get("messages"):
        raise WhatsAppDeliveryError("WhatsApp Cloud API tidak mengonfirmasi pengiriman pesan.")
    logger.info("WhatsApp leave notification accepted for leave request %s", leave.pk)
