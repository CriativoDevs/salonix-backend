from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.models import Professional, Service, ScheduleSlot, Appointment, SalonCustomer
from users.models import UserFeatureFlags, Tenant, TenantStaffMember


User = get_user_model()


class Command(BaseCommand):
    help = "Cria dados de demonstração (idempotente)."

    def handle(self, *args, **options):
        created_counts = {}
        smoke_password = settings.SMOKE_USER_PASSWORD

        from typing import Any, cast
        with cast(Any, transaction.atomic()):
            # --- Tenant padrão ---
            default_tenant, tenant_created = Tenant.objects.get_or_create(
                slug="default",
                defaults={
                    "name": "Default Salon",
                    "primary_color": "#3B82F6",
                    "secondary_color": "#1F2937",
                    # Configurar plano Standard para demo
                    "plan_tier": "standard",
                    # Habilitar features para demo
                    "reports_enabled": True,
                    "pwa_admin_enabled": True,
                    "pwa_client_enabled": True,
                    "push_web_enabled": True,
                    "push_mobile_enabled": True,
                },
            )

            # Se tenant já existia, atualizar feature flags para demo
            if not tenant_created:
                default_tenant.plan_tier = "standard"
                default_tenant.reports_enabled = True
                default_tenant.pwa_admin_enabled = True
                default_tenant.pwa_client_enabled = True
                default_tenant.push_web_enabled = True
                default_tenant.push_mobile_enabled = True
                default_tenant.save()

            # --- Usuários ---
            admin, admin_created = User.objects.get_or_create(
                username="admin",
                defaults={
                    "email": "admin@demo.local",
                    "is_staff": True,
                    "tenant": default_tenant,
                },
            )
            if admin_created:
                admin.set_password("admin")
                admin.save()
            created_counts["user_admin_created"] = int(admin_created)

            pro, pro_created = User.objects.get_or_create(
                username="pro_smoke",
                defaults={
                    "email": "pro_smoke@demo.local",
                    "tenant": default_tenant,
                },
            )
            if pro_created or not pro.check_password(smoke_password):
                pro.set_password(smoke_password)
                if pro_created:
                    pro.save()
                else:
                    pro.save(update_fields=["password"])
            created_counts["user_pro_created"] = int(pro_created)

            client, client_created = User.objects.get_or_create(
                username="client_smoke",
                defaults={
                    "email": "client_smoke@demo.local",
                    "tenant": default_tenant,
                },
            )
            if client_created or not client.check_password(smoke_password):
                client.set_password(smoke_password)
                if client_created:
                    client.save()
                else:
                    client.save(update_fields=["password"])
            created_counts["user_client_created"] = int(client_created)

            owner_staff, owner_staff_created = TenantStaffMember.objects.get_or_create(
                tenant=default_tenant,
                user=admin,
                defaults={
                    "role": TenantStaffMember.Role.OWNER,
                    "status": TenantStaffMember.Status.ACTIVE,
                    "activated_at": timezone.now(),
                },
            )
            if not owner_staff_created and owner_staff.role != TenantStaffMember.Role.OWNER:
                owner_staff.role = TenantStaffMember.Role.OWNER
                owner_staff.status = TenantStaffMember.Status.ACTIVE
                owner_staff.activated_at = owner_staff.activated_at or timezone.now()
                owner_staff.save(
                    update_fields=["role", "status", "activated_at", "updated_at"]
                )
            created_counts["staff_owner_created"] = int(owner_staff_created)

            pro_staff, pro_staff_created = TenantStaffMember.objects.get_or_create(
                tenant=default_tenant,
                user=pro,
                defaults={
                    "role": TenantStaffMember.Role.MANAGER,
                    "status": TenantStaffMember.Status.ACTIVE,
                    "invited_by": admin,
                    "invited_at": timezone.now(),
                    "activated_at": timezone.now(),
                },
            )
            if not pro_staff_created and pro_staff.role != TenantStaffMember.Role.MANAGER:
                pro_staff.role = TenantStaffMember.Role.MANAGER
                pro_staff.status = TenantStaffMember.Status.ACTIVE
                pro_staff.activated_at = pro_staff.activated_at or timezone.now()
                pro_staff.save(
                    update_fields=["role", "status", "activated_at", "updated_at"]
                )
            created_counts["staff_manager_created"] = int(pro_staff_created)

            # Garantir que pro_smoke (manager) tenha Professional associado se for colaborador
            # Isso é necessário para o novo fluxo unificado
            if pro_staff.role == TenantStaffMember.Role.COLLABORATOR:
                pro_professional = pro_staff.ensure_professional()
                if pro_professional:
                    # Atualizar dados do professional para ser consistente
                    pro_professional.name = "Pablo"
                    pro_professional.bio = "Barbeiro"
                    pro_professional.save(update_fields=["name", "bio"])

            customer_defaults = {
                "name": "Cliente Demo",
                "phone_number": "+351912345678",
                "marketing_opt_in": True,
                "is_active": True,
                "notes": "Criado automaticamente pelo seed_demo.",
            }
            demo_customer, customer_created = SalonCustomer.objects.get_or_create(
                tenant=default_tenant,
                email=client.email,
                defaults=customer_defaults,
            )
            if not customer_created and demo_customer.name != customer_defaults["name"]:
                demo_customer.name = customer_defaults["name"]
                demo_customer.save(update_fields=["name"])
            created_counts["customers_created"] = int(customer_created)

            # --- Feature flags (PRO e relatórios habilitados para o pro_smoke) ---
            ff, _ = UserFeatureFlags.objects.get_or_create(
                user=pro, defaults={"is_pro": True, "reports_enabled": True}
            )
            # se já existe, garante coerência
            if not ff.is_pro or not ff.reports_enabled:
                ff.is_pro = True
                ff.reports_enabled = True
                ff.save(update_fields=["is_pro", "reports_enabled"])

            def ensure_collaborator_staff(
                username: str,
                email: str,
                first_name: str,
                last_name: str,
                role: str = TenantStaffMember.Role.COLLABORATOR,
            ) -> tuple[TenantStaffMember, bool]:
                user_defaults = {
                    "email": email,
                    "tenant": default_tenant,
                    "first_name": first_name,
                    "last_name": last_name,
                }
                user_obj, user_created = User.objects.get_or_create(
                    username=username, defaults=user_defaults
                )
                if user_created:
                    user_obj.set_unusable_password()
                    user_obj.save()
                else:
                    needs_update = False
                    for field, value in user_defaults.items():
                        if getattr(user_obj, field) != value and value:
                            setattr(user_obj, field, value)
                            needs_update = True
                    if needs_update:
                        user_obj.save(
                            update_fields=["email", "first_name", "last_name", "tenant"]
                        )

                staff_defaults = {
                    "role": role,
                    "status": TenantStaffMember.Status.ACTIVE,
                    "invited_by": admin,
                    "invited_at": timezone.now(),
                    "activated_at": timezone.now(),
                }
                staff_obj, staff_created = TenantStaffMember.objects.get_or_create(
                    tenant=default_tenant,
                    user=user_obj,
                    defaults=staff_defaults,
                )
                if not staff_created:
                    updated_fields = []
                    if staff_obj.role != role:
                        staff_obj.role = role
                        updated_fields.append("role")
                    if staff_obj.status != TenantStaffMember.Status.ACTIVE:
                        staff_obj.status = TenantStaffMember.Status.ACTIVE
                        updated_fields.append("status")
                    if staff_obj.activated_at is None:
                        staff_obj.activated_at = timezone.now()
                        updated_fields.append("activated_at")
                    if updated_fields:
                        staff_obj.save(update_fields=updated_fields + ["updated_at"])
                return staff_obj, staff_created

            alice_staff, alice_staff_created = ensure_collaborator_staff(
                "staff_alice",
                "alice@demo.local",
                first_name="Alice",
                last_name="Demo",
            )
            bruno_staff, bruno_staff_created = ensure_collaborator_staff(
                "staff_bruno",
                "bruno@demo.local",
                first_name="Bruno",
                last_name="Demo",
            )
            created_counts["staff_collaborators_created"] = int(
                alice_staff_created
            ) + int(bruno_staff_created)

            # Garantir que todos os staff colaboradores tenham Professional usando ensure_professional
            alice_professional = alice_staff.ensure_professional()
            if alice_professional:
                # Atualizar dados se necessário
                if alice_professional.name != "Alice" or alice_professional.bio != "Especialista em cortes e coloração.":
                    alice_professional.name = "Alice"
                    alice_professional.bio = "Especialista em cortes e coloração."
                    alice_professional.save(update_fields=["name", "bio"])

            bruno_professional = bruno_staff.ensure_professional()
            if bruno_professional:
                # Atualizar dados se necessário
                if bruno_professional.name != "Bruno" or bruno_professional.bio != "Barbeiro especialista em fade.":
                    bruno_professional.name = "Bruno"
                    bruno_professional.bio = "Barbeiro especialista em fade."
                    bruno_professional.save(update_fields=["name", "bio"])

            # Contar professionals criados/atualizados
            prof1_exists = Professional.objects.filter(staff_member=alice_staff).exists()
            prof2_exists = Professional.objects.filter(staff_member=bruno_staff).exists()
            created_counts["professionals_created"] = int(not prof1_exists) + int(not prof2_exists)

            # --- Serviços do salão do pro_smoke ---
            svc1, s1_new = Service.objects.get_or_create(
                user=pro,
                name="Corte Feminino",
                defaults={
                    "price_eur": Decimal("25.00"),
                    "duration_minutes": 45,
                    "tenant": default_tenant,
                },
            )
            svc2, s2_new = Service.objects.get_or_create(
                user=pro,
                name="Corte Masculino",
                defaults={
                    "price_eur": Decimal("18.00"),
                    "duration_minutes": 30,
                    "tenant": default_tenant,
                },
            )
            svc3, s3_new = Service.objects.get_or_create(
                user=pro,
                name="Coloração",
                defaults={
                    "price_eur": Decimal("55.00"),
                    "duration_minutes": 60,
                    "tenant": default_tenant,
                },
            )
            created_counts["services_created"] = int(s1_new) + int(s2_new) + int(s3_new)

            # Buscar professionals para criar slots
            alice_professional = Professional.objects.filter(staff_member=alice_staff).first()
            bruno_professional = Professional.objects.filter(staff_member=bruno_staff).first()
            professionals = [p for p in [alice_professional, bruno_professional] if p is not None]

            # --- Slots próximos 3 dias (9h–17h, de hora em hora) ---
            tz_now = timezone.now()
            base_day = tz_now.replace(minute=0, second=0, microsecond=0)
            working_hours = list(range(9, 17))  # 9..16

            slots_created = 0
            for d in range(0, 3):
                day = (base_day + timedelta(days=d)).date()
                for hour in working_hours:
                    for prof in professionals:
                        start = timezone.make_aware(
                            timezone.datetime(
                                year=day.year, month=day.month, day=day.day, hour=hour
                            )
                        )
                        end = start + timedelta(minutes=60)
                        _, created = ScheduleSlot.objects.get_or_create(
                            professional=prof,
                            start_time=start,
                            end_time=end,
                            defaults={
                                "is_available": True,
                                "status": "available",
                                "tenant": default_tenant,
                            },
                        )
                        slots_created += int(created)
            created_counts["slots_created"] = slots_created

            # --- Alguns agendamentos (scheduled, cancelled, completed) ---
            # Buscar professionals pelos staff members
            alice_professional = Professional.objects.filter(staff_member=alice_staff).first()
            bruno_professional = Professional.objects.filter(staff_member=bruno_staff).first()
            
            professionals = [p for p in [alice_professional, bruno_professional] if p]
            
            # Seleciona 3 slots disponíveis e reserva para o cliente
            free_slots = (
                ScheduleSlot.objects.filter(
                    professional__in=professionals, is_available=True
                )
                .order_by("start_time")
                .distinct()[:6]
            )
            appts_created = 0

            def _book(slot: ScheduleSlot, service: Service, status: str = "scheduled"):
                # idempotente: existe appointment para este slot+client?
                appt, created = Appointment.objects.get_or_create(
                    slot=slot,
                    client=client,
                    defaults={
                        "professional": slot.professional,
                        "service": service,
                        "status": status,
                        "notes": "",
                        "tenant": default_tenant,
                        "customer": demo_customer,
                    },
                )
                if created:
                    # marcar slot conforme status
                    if status in ("scheduled", "completed", "paid"):
                        # reservado
                        slot.mark_booked()
                    elif status == "cancelled":
                        slot.mark_available()
                else:
                    updated_fields = []
                    if appt.customer_id is None:
                        appt.customer = demo_customer
                        updated_fields.append("customer")
                    # se já existe, garantimos consistência básica do status/slot
                    if status in ("scheduled", "completed", "paid"):
                        slot.mark_booked()
                        if appt.status != status:
                            appt.status = status
                            updated_fields.append("status")
                    elif status == "cancelled":
                        slot.mark_available()
                        if appt.status != "cancelled":
                            appt.status = "cancelled"
                            updated_fields.append("status")
                    if updated_fields:
                        appt.save(update_fields=updated_fields)
                return int(created)

            if free_slots:
                appts_created += _book(free_slots[0], svc1, status="scheduled")
            if free_slots.count() > 1:
                appts_created += _book(free_slots[1], svc2, status="cancelled")
            if free_slots.count() > 2:
                appts_created += _book(free_slots[2], svc3, status="completed")
            if free_slots.count() > 3:
                appts_created += _book(free_slots[3], svc1, status="scheduled")
            if free_slots.count() > 4:
                appts_created += _book(free_slots[4], svc2, status="completed")
            if free_slots.count() > 5:
                appts_created += _book(free_slots[5], svc3, status="scheduled")

            created_counts["appointments_created"] = appts_created

        self.stdout.write(self.style.SUCCESS("Seed concluído."))
        for k, v in created_counts.items():
            self.stdout.write(f"- {k}: {v}")
        self.stdout.write(
            "\nCredenciais úteis:\n"
            "  • admin@demo.local / admin (superuser)\n"
            f"  • pro_smoke@demo.local / {smoke_password} (PRO, relatórios habilitados)\n"
            f"  • client_smoke@demo.local / {smoke_password}\n"
            "\nDica: defina SMOKE_USER_PASSWORD=... antes de rodar o seed para mudar a senha padrão.\n"
        )
