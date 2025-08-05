from django.contrib import admin
from core.models import Service, Professional, ScheduleSlot, Appointment


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "price_eur", "duration_minutes")


@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "is_active")


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    list_display = ("professional", "start_time", "end_time", "is_available")
    list_filter = ("is_available",)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("client", "service", "professional", "slot", "created_at")
