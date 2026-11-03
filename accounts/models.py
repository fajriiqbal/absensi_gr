from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class UserGuruManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "admin")
        return super().create_superuser(username, email, password, **extra_fields)


class UserGuru(AbstractUser):
    ROLE_CHOICES = (
        ("guru", "Guru / Staf"),
        ("kamad", "Kepala Madrasah"),
        ("admin", "Administrator System"),
    )

    nip = models.CharField(max_length=20, unique=True, db_index=True)
    nama_lengkap = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="guru")
    foto_profil = models.ImageField(upload_to="profiles/", null=True, blank=True)

    USERNAME_FIELD = "nip"
    REQUIRED_FIELDS = ["username", "nama_lengkap", "email"]
    objects = UserGuruManager()

    def __str__(self):
        return f"{self.nama_lengkap} ({self.nip})"