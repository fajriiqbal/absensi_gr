from dataclasses import dataclass
from datetime import date, time

from django.db import transaction
from django.utils import timezone

from core.models import JadwalWaktuPresensiKhusus, PengaturanWaktuPresensi

from .models import AbsensiLog


class AttendanceScheduleError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class DailyAttendanceSchedule:
    jam_mulai_masuk: time
    batas_terlambat: time
    jam_mulai_pulang: time
    jam_pulang: time


def get_daily_attendance_schedule(day: date) -> DailyAttendanceSchedule:
    settings_obj = PengaturanWaktuPresensi.get_settings()
    override = JadwalWaktuPresensiKhusus.objects.filter(tanggal=day).first()
    if override is None:
        checkout_start = settings_obj.jam_mulai_pulang
        departure = settings_obj.jam_pulang_normal
    else:
        checkout_start = override.jam_mulai_pulang
        departure = override.jam_pulang
    return DailyAttendanceSchedule(
        jam_mulai_masuk=settings_obj.jam_mulai_masuk,
        batas_terlambat=settings_obj.batas_terlambat,
        jam_mulai_pulang=checkout_start,
        jam_pulang=departure,
    )


def record_attendance_event(
    guru,
    *,
    method,
    now=None,
    latitude=None,
    longitude=None,
    photo=None,
):
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    today = timezone.localdate(now)
    local_time = local_now.time().replace(tzinfo=None)
    schedule = get_daily_attendance_schedule(today)

    with transaction.atomic():
        log = AbsensiLog.objects.select_for_update().filter(guru=guru, tanggal=today).first()
        if log is None:
            if local_time < schedule.jam_mulai_masuk:
                raise AttendanceScheduleError(
                    f"Presensi masuk dibuka pukul {schedule.jam_mulai_masuk:%H:%M}."
                )
            if local_time >= schedule.jam_mulai_pulang:
                raise AttendanceScheduleError(
                    f"Waktu presensi masuk hari ini sudah berakhir pukul {schedule.jam_mulai_pulang:%H:%M}."
                )
            log = AbsensiLog.objects.create(
                guru=guru,
                tanggal=today,
                waktu_masuk=now,
                lat_masuk=latitude,
                long_masuk=longitude,
                foto_masuk=photo,
                metode_scan=method,
                status="terlambat" if local_time > schedule.batas_terlambat else "hadir",
            )
            return log, "masuk"

        if log.waktu_pulang is not None:
            raise AttendanceScheduleError(
                "Presensi masuk dan pulang hari ini sudah tercatat.",
                status=409,
            )
        if local_time < schedule.jam_mulai_pulang:
            raise AttendanceScheduleError(
                f"Presensi pulang baru dibuka pukul {schedule.jam_mulai_pulang:%H:%M}."
            )
        log.waktu_pulang = now
        log.status_pulang = "pulang_cepat" if local_time < schedule.jam_pulang else "tepat_waktu"
        log.save(update_fields=("waktu_pulang", "status_pulang"))
        return log, "pulang"
