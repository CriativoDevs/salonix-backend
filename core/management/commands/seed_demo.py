from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.models import Professional, Service, ScheduleSlot, Appointment, SalonCustomer
from users.models import UserFeatureFlags, Tenant, TenantStaffMember, CommLedger


User = get_user_model()


class Command(BaseCommand):
    help = "Cria dados de demonstração (idempotente)."

    def handle(self, *args, **options):
        created_counts = {}
        smoke_password = settings.SMOKE_USER_PASSWORD

        from typing import Any, cast

        with cast(Any, transaction.atomic()):
            # --- Tenant padrão: TimelyOne (Founder, billing promocional) ---
            # Renomeado de "Default Salon" -- este é o tenant "vitrine",
            # usado para gerar imagens/vídeos de demonstração da plataforma
            # e para testar a app localmente com dados ricos. Plano Pro
            # removido daqui (BE-PLANS-01: bloqueado para venda/atribuição,
            # não faz sentido como demo) -- Founder é Basic + is_founder=True.
            default_tenant, tenant_created = Tenant.objects.get_or_create(
                slug="default",
                defaults={
                    "name": "TimelyOne",
                    "app_name": "TimelyOne",
                    "plan_tier": Tenant.PLAN_BASIC,
                    "is_founder": True,
                    "billing_mode": Tenant.BILLING_MODE_PROMOTIONAL,
                    # Habilitar features para demo
                    "reports_enabled": True,
                    "pwa_admin_enabled": True,
                    "pwa_client_enabled": True,
                    "push_web_enabled": True,
                    "push_mobile_enabled": True,
                    # Novos campos de comunicação
                    "comm_credit_eur": Decimal("10.00"),  # 10 EUR de crédito inicial
                    "comm_extra_allowed": True,  # Permite compra de créditos extras
                    "comm_auto_renew": True,
                    # Domínio personalizado desabilitado por padrão
                    "custom_domain_enabled": False,
                    "custom_domain": "",
                },
            )

            # Se tenant já existia, atualizar feature flags para demo
            if not tenant_created:
                default_tenant.name = "TimelyOne"
                default_tenant.app_name = "TimelyOne"
                default_tenant.plan_tier = Tenant.PLAN_BASIC
                default_tenant.is_founder = True
                default_tenant.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
                default_tenant.reports_enabled = True
                default_tenant.pwa_admin_enabled = True
                default_tenant.pwa_client_enabled = True
                default_tenant.push_web_enabled = True
                default_tenant.push_mobile_enabled = True
                # Atualizar novos campos
                default_tenant.comm_credit_eur = Decimal("10.00")
                default_tenant.comm_extra_allowed = True
                default_tenant.comm_auto_renew = True
                default_tenant.custom_domain_enabled = False
                default_tenant.custom_domain = ""
                default_tenant.save()

            # --- Tenants adicionais para demonstrar diferentes planos ---
            # Todos em billing_mode=promotional -- são tenants de teste/demo,
            # nunca passaram por checkout real, então não faz sentido exibir
            # o gate de cobrança do Stripe para eles (mesmo padrão usado em
            # produção para tenants não-pagantes, ver Tenant.billing_mode).

            # Tenant Basic - sem créditos auto-renew
            basic_tenant, basic_created = Tenant.objects.get_or_create(
                slug="basic-demo",
                defaults={
                    "name": "Basic Salon Demo",
                    "app_name": "Basic Salon",
                    "plan_tier": Tenant.PLAN_BASIC,
                    "billing_mode": Tenant.BILLING_MODE_PROMOTIONAL,
                    "reports_enabled": True,  # Basic agora tem relatórios
                    "pwa_admin_enabled": True,
                    "pwa_client_enabled": False,
                    "push_web_enabled": False,
                    "push_mobile_enabled": False,
                    "comm_credit_eur": Decimal("5.00"),  # Menos créditos iniciais
                    "comm_extra_allowed": True,  # Pode comprar créditos extras
                    "comm_auto_renew": False,  # Sem auto-renovação
                    "custom_domain_enabled": False,
                    "custom_domain": "",
                },
            )
            created_counts["basic_tenant_created"] = int(basic_created)

            # Tenant sem créditos (para testar cenário de esgotamento)
            empty_tenant, empty_created = Tenant.objects.get_or_create(
                slug="empty-credits",
                defaults={
                    "name": "Empty Credits Demo",
                    "app_name": "Empty Credits",
                    "plan_tier": Tenant.PLAN_BASIC,
                    "billing_mode": Tenant.BILLING_MODE_PROMOTIONAL,
                    "reports_enabled": True,
                    "pwa_admin_enabled": True,
                    "pwa_client_enabled": True,
                    "push_web_enabled": True,
                    "push_mobile_enabled": True,
                    "comm_credit_eur": Decimal("0.00"),  # Sem créditos
                    "comm_extra_allowed": True,
                    "comm_auto_renew": False,
                    "custom_domain_enabled": False,
                    "custom_domain": "",
                },
            )
            created_counts["empty_tenant_created"] = int(empty_created)

            # --- Usuários ---
            # "admin" é o OWNER do tenant de teste (TimelyOne) -- usado para
            # exercitar o app como um tenant normal (login web/mobile, agenda,
            # billing, etc.). NUNCA deve ser superuser do Django Admin: é a
            # conta que usamos pra testar a plataforma como cliente, não pra
            # administrar o sistema. Ver "superadmin" abaixo para acesso ao DAP.
            admin, admin_created = User.objects.get_or_create(
                username="admin",
                defaults={
                    "email": "admin@demo.local",
                    "is_staff": True,
                    "tenant": default_tenant,
                },
            )
            if admin_created:
                # >= 6 caracteres -- MOB valida tamanho mínimo de senha no
                # login; "admin" (5 chars) passava no BE mas falhava no MOB.
                admin.set_password("admin123")
                admin.save()
            created_counts["user_admin_created"] = int(admin_created)

            # Superuser dedicado para o Django Admin (DAP) -- sem tenant,
            # separado do "admin" acima de propósito (ver comentário acima).
            superadmin = User.objects.filter(username="superadmin").first()
            superadmin_created = superadmin is None
            if superadmin_created:
                superadmin = User(
                    username="superadmin",
                    email="superadmin@demo.local",
                    is_staff=True,
                    is_superuser=True,
                )
                superadmin._tenant_explicitly_none = True
                superadmin.tenant = None
                superadmin.set_password("superadmin123")
                superadmin.save()
                # Força tenant=None via UPDATE direto, ignorando qualquer
                # save() sobrescrito (ex.: monkey patch de tenant automático
                # em conftest.py:setup_default_tenant, usado só em testes).
                User.objects.filter(pk=superadmin.pk).update(tenant=None)
                superadmin.refresh_from_db()
            created_counts["user_superadmin_created"] = int(superadmin_created)

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
            if (
                not owner_staff_created
                and owner_staff.role != TenantStaffMember.Role.OWNER
            ):
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
            if (
                not pro_staff_created
                and pro_staff.role != TenantStaffMember.Role.MANAGER
            ):
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
                if (
                    alice_professional.name != "Alice"
                    or alice_professional.bio != "Especialista em cortes e coloração."
                ):
                    alice_professional.name = "Alice"
                    alice_professional.bio = "Especialista em cortes e coloração."
                    alice_professional.save(update_fields=["name", "bio"])

            bruno_professional = bruno_staff.ensure_professional()
            if bruno_professional:
                # Atualizar dados se necessário
                if (
                    bruno_professional.name != "Bruno"
                    or bruno_professional.bio != "Barbeiro especialista em fade."
                ):
                    bruno_professional.name = "Bruno"
                    bruno_professional.bio = "Barbeiro especialista em fade."
                    bruno_professional.save(update_fields=["name", "bio"])

            # Contar professionals criados/atualizados
            prof1_exists = Professional.objects.filter(
                staff_member=alice_staff
            ).exists()
            prof2_exists = Professional.objects.filter(
                staff_member=bruno_staff
            ).exists()
            created_counts["professionals_created"] = int(not prof1_exists) + int(
                not prof2_exists
            )

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
            alice_professional = Professional.objects.filter(
                staff_member=alice_staff
            ).first()
            bruno_professional = Professional.objects.filter(
                staff_member=bruno_staff
            ).first()
            professionals = [
                p for p in [alice_professional, bruno_professional] if p is not None
            ]

            # --- Clientes extra para diversidade nos relatórios (Top Serviços,
            # Novos vs Recorrentes, Receita por semana etc.) -- além do
            # "Cliente Demo" original, criado acima. ---
            extra_customers_data = [
                ("Ana Ferreira", "ana.ferreira@demo.local", "+351911111111"),
                ("Bruno Costa", "bruno.costa@demo.local", "+351911111112"),
                ("Carla Nunes", "carla.nunes@demo.local", "+351911111113"),
                ("Diogo Pinto", "diogo.pinto@demo.local", "+351911111114"),
                ("Elsa Ramos", "elsa.ramos@demo.local", "+351911111115"),
                ("Filipe Sousa", "filipe.sousa@demo.local", "+351911111116"),
            ]
            demo_customers = [demo_customer]
            for name, email, phone in extra_customers_data:
                cust, cust_created = SalonCustomer.objects.get_or_create(
                    tenant=default_tenant,
                    email=email,
                    defaults={
                        "name": name,
                        "phone_number": phone,
                        "marketing_opt_in": True,
                        "is_active": True,
                        "notes": "Criado automaticamente pelo seed_demo (histórico de 2 meses).",
                    },
                )
                demo_customers.append(cust)
                created_counts["customers_created"] += int(cust_created)

            # --- Slots e agendamentos: ~2 meses completos (30 dias antes +
            # 30 dias a partir de hoje), para preencher relatórios/insights
            # com dados realistas (usado também para gerar imagens/vídeos de
            # demonstração da plataforma). Passado: mix completed/paid/
            # cancelled. Hoje em diante: scheduled. ---
            tz_now = timezone.now()
            base_day = tz_now.replace(minute=0, second=0, microsecond=0)
            appointment_hours = [9, 11, 14, 16]
            services_cycle = [svc1, svc2, svc3]

            alice_professional = Professional.objects.filter(
                staff_member=alice_staff
            ).first()
            bruno_professional = Professional.objects.filter(
                staff_member=bruno_staff
            ).first()
            professionals = [
                p for p in [alice_professional, bruno_professional] if p
            ]

            def _upsert_appointment(
                slot: ScheduleSlot, service: Service, customer: SalonCustomer, status: str
            ):
                appt, created = Appointment.objects.get_or_create(
                    slot=slot,
                    client=client,
                    defaults={
                        "professional": slot.professional,
                        "service": service,
                        "status": status,
                        "notes": "",
                        "tenant": default_tenant,
                        "customer": customer,
                    },
                )
                if not created:
                    updated_fields = []
                    if appt.customer_id != customer.id:
                        appt.customer = customer
                        updated_fields.append("customer")
                    if appt.status != status:
                        appt.status = status
                        updated_fields.append("status")
                    if updated_fields:
                        appt.save(update_fields=updated_fields)
                if status in ("scheduled", "completed", "paid"):
                    slot.mark_booked()
                elif status == "cancelled":
                    slot.mark_available()
                return int(created)

            slots_created = 0
            appts_created = 0
            i = 0
            for d in range(-30, 30):
                day = (base_day + timedelta(days=d)).date()
                is_past = d < 0
                for idx, hour in enumerate(appointment_hours):
                    prof = professionals[idx % len(professionals)]
                    service = services_cycle[idx % len(services_cycle)]
                    customer = demo_customers[i % len(demo_customers)]
                    start = timezone.make_aware(
                        timezone.datetime(
                            year=day.year, month=day.month, day=day.day, hour=hour
                        )
                    )
                    end = start + timedelta(minutes=60)
                    slot, slot_created = ScheduleSlot.objects.get_or_create(
                        professional=prof,
                        start_time=start,
                        end_time=end,
                        defaults={
                            "is_available": True,
                            "status": "available",
                            "tenant": default_tenant,
                        },
                    )
                    slots_created += int(slot_created)

                    if is_past:
                        # distribuição determinística: 60% completed,
                        # 20% paid, 20% cancelled
                        bucket = i % 5
                        if bucket < 3:
                            status = "completed"
                        elif bucket == 3:
                            status = "paid"
                        else:
                            status = "cancelled"
                    else:
                        status = "scheduled"

                    appts_created += _upsert_appointment(
                        slot, service, customer, status
                    )
                    i += 1

            created_counts["slots_created"] = slots_created
            created_counts["appointments_created"] = appts_created

        # --- Histórico de transações de créditos (CommLedger) ---
        comm_ledger_created = 0

        # Transações para o tenant padrão
        if default_tenant:
            # Crédito inicial
            initial_credit, created = CommLedger.objects.get_or_create(
                tenant=default_tenant,
                transaction_type="purchase",
                amount_eur=Decimal("10.00"),
                description="Créditos iniciais do plano",
                defaults={
                    "balance_before": Decimal("0.00"),
                    "balance_after": Decimal("10.00"),
                    "status": "completed",
                    "created_at": timezone.now() - timedelta(days=30),
                },
            )
            if created:
                comm_ledger_created += 1

            # Compra de créditos extras
            purchase_credit, created = CommLedger.objects.get_or_create(
                tenant=default_tenant,
                transaction_type="purchase",
                amount_eur=Decimal("5.00"),
                description="Compra de créditos extras",
                defaults={
                    "balance_before": Decimal("10.00"),
                    "balance_after": Decimal("15.00"),
                    "status": "completed",
                    "created_at": timezone.now() - timedelta(days=20),
                },
            )
            if created:
                comm_ledger_created += 1

            # Consumo por SMS
            sms_debit, created = CommLedger.objects.get_or_create(
                tenant=default_tenant,
                transaction_type="consumption",
                amount_eur=Decimal("0.50"),
                description="Envio de SMS para cliente",
                defaults={
                    "balance_before": Decimal("15.00"),
                    "balance_after": Decimal("14.50"),
                    "status": "completed",
                    "created_at": timezone.now() - timedelta(days=15),
                },
            )
            if created:
                comm_ledger_created += 1

            # Consumo por WhatsApp
            whatsapp_debit, created = CommLedger.objects.get_or_create(
                tenant=default_tenant,
                transaction_type="consumption",
                amount_eur=Decimal("0.30"),
                description="Envio de mensagem WhatsApp",
                defaults={
                    "balance_before": Decimal("14.50"),
                    "balance_after": Decimal("14.20"),
                    "status": "completed",
                    "created_at": timezone.now() - timedelta(days=10),
                },
            )
            if created:
                comm_ledger_created += 1

        # Transações para o tenant Basic
        if basic_tenant:
            # Crédito inicial menor
            basic_initial, created = CommLedger.objects.get_or_create(
                tenant=basic_tenant,
                transaction_type="purchase",
                amount_eur=Decimal("5.00"),
                description="Créditos iniciais do plano Basic",
                defaults={
                    "balance_before": Decimal("0.00"),
                    "balance_after": Decimal("5.00"),
                    "status": "completed",
                    "created_at": timezone.now() - timedelta(days=15),
                },
            )
            if created:
                comm_ledger_created += 1

            # Alguns consumos básicos
            basic_sms, created = CommLedger.objects.get_or_create(
                tenant=basic_tenant,
                transaction_type="consumption",
                amount_eur=Decimal("0.50"),
                description="SMS de confirmação",
                defaults={
                    "balance_before": Decimal("5.00"),
                    "balance_after": Decimal("4.50"),
                    "status": "completed",
                    "created_at": timezone.now() - timedelta(days=10),
                },
            )
            if created:
                comm_ledger_created += 1

        # Para o tenant sem créditos, criar histórico que mostra esgotamento
        if empty_tenant:
            # Crédito inicial que foi totalmente consumido
            empty_initial, created = CommLedger.objects.get_or_create(
                tenant=empty_tenant,
                transaction_type="purchase",
                amount_eur=Decimal("3.00"),
                description="Créditos iniciais",
                defaults={
                    "balance_before": Decimal("0.00"),
                    "balance_after": Decimal("3.00"),
                    "status": "completed",
                    "created_at": timezone.now() - timedelta(days=10),
                },
            )
            if created:
                comm_ledger_created += 1

            # Consumo que esgotou os créditos
            empty_consumed, created = CommLedger.objects.get_or_create(
                tenant=empty_tenant,
                transaction_type="consumption",
                amount_eur=Decimal("3.00"),
                description="Consumo total dos créditos disponíveis",
                defaults={
                    "balance_before": Decimal("3.00"),
                    "balance_after": Decimal("0.00"),
                    "status": "completed",
                    "created_at": timezone.now() - timedelta(days=5),
                },
            )
            if created:
                comm_ledger_created += 1

        created_counts["comm_ledger_created"] = comm_ledger_created

        self.stdout.write(self.style.SUCCESS("Seed concluído."))
        for k, v in created_counts.items():
            self.stdout.write(f"- {k}: {v}")
        self.stdout.write(
            "\nCredenciais úteis:\n"
            "  • admin@demo.local / admin123 (owner do tenant de teste TimelyOne)\n"
            f"  • pro_smoke@demo.local / {smoke_password} (PRO, relatórios habilitados)\n"
            f"  • client_smoke@demo.local / {smoke_password}\n"
            "  • superadmin@demo.local / superadmin123 (Django Admin/DAP -- sem tenant)\n"
            "\nDica: defina SMOKE_USER_PASSWORD=... antes de rodar o seed para mudar a senha padrão.\n"
        )
