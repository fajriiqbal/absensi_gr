import hashlib
import mimetypes
from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files.base import ContentFile, File
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class EncryptedPrivateFileSystemStorage(FileSystemStorage):
    def _cipher(self):
        key = getattr(settings, "MEDIA_ENCRYPTION_KEY", "")
        if not key and settings.DEBUG:
            digest = hashlib.sha256((settings.SECRET_KEY + ":media").encode()).digest()
            key = urlsafe_b64encode(digest).decode()
        if not key:
            raise ImproperlyConfigured("MEDIA_ENCRYPTION_KEY wajib diatur untuk media terenkripsi.")
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except (TypeError, ValueError):
            raise ImproperlyConfigured("MEDIA_ENCRYPTION_KEY bukan kunci Fernet yang valid.") from None

    def _save(self, name, content):
        plaintext = b"".join(content.chunks())
        encrypted = self._cipher().encrypt(plaintext)
        return super()._save(name, ContentFile(encrypted))

    def _open(self, name, mode="rb"):
        if mode != "rb":
            raise ValueError("Media terenkripsi hanya dapat dibaca.")
        with super()._open(name, mode) as encrypted_file:
            encrypted = encrypted_file.read()
        try:
            plaintext = self._cipher().decrypt(encrypted)
        except InvalidToken:
            raise SuspiciousFileOperation("Media terenkripsi rusak atau kunci tidak cocok.") from None
        return File(ContentFile(plaintext), name=name)

    def size(self, name):
        with self.open(name, "rb") as media_file:
            media_file.seek(0, 2)
            return media_file.tell()

    def url(self, name):
        raise ValueError("Media privat tidak memiliki URL publik; gunakan endpoint media terautentikasi.")

    def content_type(self, name):
        return mimetypes.guess_type(name)[0] or "application/octet-stream"


encrypted_private_storage = EncryptedPrivateFileSystemStorage()