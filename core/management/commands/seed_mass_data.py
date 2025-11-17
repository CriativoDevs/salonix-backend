from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from faker import Faker

from core.models import Service, ScheduleSlot, Appointment, SalonCustomer
from users.models import Tenant, TenantStaffMember, CustomUser

User = get_user_model()
fake = Faker("pt_BR")


class Command(BaseCommand):
    help = "Gera dados de teste em massa para performance testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--appointments",
            type=int,
            default=10000,
            help="Número de agendamentos a criar (padrão: 10000)",
        )
        parser.add_argument(
            "--customers",
            type=int,
            default=2000,
            help="Número de clientes a criar (padrão: 2000)",
        )
        parser.add_argument(
            "--professionals",
            type=int,
            default=20,
            help="Número de profissionais a criar (padrão: 20)",
        )
        parser.add_argument(
            "--services",
            type=int,
            default=50,
            help="Número de serviços a criar (padrão: 50)",
        )
        parser.add_argument(
            "--days-back",
            type=int,
            default=365,
            help="Quantos dias no passado gerar dados (padrão: 365)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Tamanho do batch para inserção (padrão: 1000)",
        )

    def handle(self, *args, **options):
        appointments_count = options["appointments"]
        customers_count = options["customers"]
        professionals_count = options["professionals"]
        services_count = options["services"]
        days_back = options["days_back"]
        batch_size = options["batch_size"]

        self.stdout.write(
            self.style.WARNING(
                f"Gerando dados de teste em massa:\n"
                f"- {appointments_count} agendamentos\n"
                f"- {customers_count} clientes\n"
                f"- {professionals_count} profissionais\n"
                f"- {services_count} serviços\n"
                f"- {days_back} dias no passado\n"
                f"- Batch size: {batch_size}"
            )
        )

        # Verificar se tenant padrão existe
        try:
            tenant = Tenant.objects.get(slug="default")
        except Tenant.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    "Tenant 'default' não encontrado. Execute 'python manage.py seed_demo' primeiro."
                )
            )
            return

        # Verificar se usuário admin existe
        try:
            admin_user = User.objects.get(username="admin")
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    "Usuário 'admin' não encontrado. Execute 'python manage.py seed_demo' primeiro."
                )
            )
            return

        self.stdout.write("Iniciando geração de dados...")

        with transaction.atomic():
            # 1. Criar serviços
            services = self._create_services(tenant, admin_user, services_count)
            self.stdout.write(f"✓ {len(services)} serviços criados")

            # 2. Criar profissionais
            professionals = self._create_professionals(
                tenant, admin_user, professionals_count
            )
            self.stdout.write(f"✓ {len(professionals)} profissionais criados")

            # 3. Criar clientes
            customers = self._create_customers(tenant, customers_count, batch_size)
            self.stdout.write(f"✓ {len(customers)} clientes criados")

            # 4. Criar slots de horário
            slots = self._create_schedule_slots(
                tenant, professionals, days_back, batch_size
            )
            self.stdout.write(f"✓ {len(slots)} slots criados")

            # 5. Criar agendamentos
            appointments = self._create_appointments(
                tenant, customers, services, slots, appointments_count, batch_size
            )
            self.stdout.write(f"✓ {len(appointments)} agendamentos criados")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDados de teste gerados com sucesso!\n"
                f"Total de registros criados: {len(services) + len(professionals) + len(customers) + len(slots) + len(appointments)}"
            )
        )

    def _create_services(self, tenant, admin_user, count):
        """Cria serviços variados"""
        service_types = [
            ("Corte Masculino", 30, 25),
            ("Corte Feminino", 45, 35),
            ("Coloração", 120, 80),
            ("Mechas", 180, 120),
            ("Escova", 60, 30),
            ("Hidratação", 45, 40),
            ("Progressiva", 240, 200),
            ("Barba", 20, 15),
            ("Sobrancelha", 15, 20),
            ("Manicure", 30, 25),
            ("Pedicure", 45, 30),
            ("Depilação Perna", 60, 50),
            ("Depilação Axila", 15, 20),
            ("Massagem Relaxante", 60, 70),
            ("Limpeza de Pele", 90, 80),
        ]

        services = []
        existing_services = set(
            Service.objects.filter(tenant=tenant).values_list("name", flat=True)
        )

        for i in range(count):
            base_service = random.choice(service_types)
            name = (
                f"{base_service[0]} {i + 1}"
                if i >= len(service_types)
                else base_service[0]
            )

            # Evitar duplicatas
            counter = 1
            original_name = name
            while name in existing_services:
                name = f"{original_name} {counter}"
                counter += 1

            existing_services.add(name)

            # Variação nos preços e duração
            duration = base_service[1] + random.randint(-10, 20)
            price = base_service[2] + random.randint(-5, 15)

            service = Service.objects.create(
                tenant=tenant,
                user=admin_user,  # Precisa de um user também
                name=name,
                duration_minutes=max(15, duration),
                price_eur=Decimal(str(max(10, price))),
            )
            services.append(service)

        return services

    def _create_professionals(self, tenant, admin_user, count):
        """Cria profissionais com usuários associados"""
        professionals = []

        for i in range(count):
            # Criar usuário
            username = f"prof_{i + 1:04d}"
            email = f"prof{i + 1}@demo.local"

            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "first_name": fake.first_name(),
                    "last_name": fake.last_name(),
                    "tenant": tenant,
                },
            )

            if created:
                user.set_unusable_password()
                user.save()

            # Criar staff member
            staff, staff_created = TenantStaffMember.objects.get_or_create(
                tenant=tenant,
                user=user,
                defaults={
                    "role": TenantStaffMember.Role.COLLABORATOR,
                    "status": TenantStaffMember.Status.ACTIVE,
                    "invited_by": admin_user,
                    "invited_at": timezone.now(),
                    "activated_at": timezone.now(),
                },
            )

            # Criar professional
            professional = staff.ensure_professional()
            if professional:
                professional.name = f"{user.first_name} {user.last_name}"
                professional.bio = fake.text(max_nb_chars=200)
                professional.save()
                professionals.append(professional)

        return professionals

    def _create_customers(self, tenant, count, batch_size):
        """Cria clientes em batches"""
        customers = []
        batch = []

        existing_emails = set(
            SalonCustomer.objects.filter(tenant=tenant).values_list("email", flat=True)
        )

        for i in range(count):
            email = fake.email()
            # Evitar emails duplicados
            while email in existing_emails:
                email = fake.email()
            existing_emails.add(email)

            phone_number = fake.phone_number()[:20]  # Limitar tamanho

            customer = SalonCustomer(
                tenant=tenant,
                name=fake.name(),
                email=email,
                phone_number=phone_number,
                notes=fake.text(max_nb_chars=100) if random.random() > 0.7 else "",
            )
            batch.append(customer)

            if len(batch) >= batch_size:
                created_customers = SalonCustomer.objects.bulk_create(
                    batch, ignore_conflicts=True
                )
                customers.extend(created_customers)
                batch = []

        # Criar último batch
        if batch:
            created_customers = SalonCustomer.objects.bulk_create(
                batch, ignore_conflicts=True
            )
            customers.extend(created_customers)

        return SalonCustomer.objects.filter(tenant=tenant).order_by("-id")[:count]

    def _create_schedule_slots(self, tenant, professionals, days_back, batch_size):
        """Cria slots de horário para os profissionais"""
        slots = []
        batch = []

        start_date = timezone.now().date() - timedelta(days=days_back)
        end_date = timezone.now().date() + timedelta(days=30)  # 30 dias no futuro

        working_hours = list(range(8, 18))  # 8h às 17h

        current_date = start_date
        while current_date <= end_date:
            # Pular domingos
            if current_date.weekday() != 6:
                for professional in professionals:
                    # Nem todos profissionais trabalham todos os dias
                    if random.random() > 0.2:  # 80% chance de trabalhar
                        for hour in working_hours:
                            # Nem todos horários disponíveis
                            if random.random() > 0.3:  # 70% chance de ter slot
                                start_time = timezone.make_aware(
                                    datetime.combine(
                                        current_date,
                                        datetime.min.time().replace(hour=hour),
                                    )
                                )
                                end_time = start_time + timedelta(hours=1)

                                slot = ScheduleSlot(
                                    tenant=tenant,
                                    professional=professional,
                                    start_time=start_time,
                                    end_time=end_time,
                                    is_available=True,
                                    status="available",
                                )
                                batch.append(slot)

                                if len(batch) >= batch_size:
                                    created_slots = ScheduleSlot.objects.bulk_create(
                                        batch, ignore_conflicts=True
                                    )
                                    slots.extend(created_slots)
                                    batch = []

            current_date += timedelta(days=1)

        # Criar último batch
        if batch:
            created_slots = ScheduleSlot.objects.bulk_create(
                batch, ignore_conflicts=True
            )
            slots.extend(created_slots)

        return slots

    def _create_appointments(
        self, tenant, customers, services, slots, count, batch_size
    ):
        """Cria agendamentos distribuídos no tempo"""
        appointments = []
        batch = []

        # Pegar slots disponíveis
        available_slots = list(
            ScheduleSlot.objects.filter(
                tenant=tenant, is_available=True
            ).select_related("professional")
        )

        if not available_slots:
            self.stdout.write(self.style.WARNING("Nenhum slot disponível encontrado"))
            return []

        # Criar alguns usuários para usar como client
        client_users = []
        for i in range(
            min(50, count // 10 + 1)
        ):  # Criar alguns usuários para reutilizar
            username = f"client_{fake.user_name()}_{i}"
            email = f"client_{i}@{fake.domain_name()}"

            client_user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password="password123",
                first_name=fake.first_name(),
                last_name=fake.last_name(),
            )
            # Associar ao tenant se necessário
            if hasattr(client_user, "tenant"):
                client_user.tenant = tenant
                client_user.save()
            client_users.append(client_user)

        status_choices = ["scheduled", "paid", "completed", "cancelled"]
        status_weights = [0.25, 0.35, 0.3, 0.1]  # Mais agendamentos pagos e completados

        for i in range(min(count, len(available_slots))):
            slot = available_slots[i]
            customer = random.choice(customers)
            service = random.choice(services)
            client_user = random.choice(client_users)
            status = random.choices(status_choices, weights=status_weights)[0]

            appointment = Appointment(
                tenant=tenant,
                client=client_user,
                customer=customer,
                service=service,
                professional=slot.professional,
                slot=slot,
                status=status,
                notes=fake.text(max_nb_chars=100) if random.random() > 0.8 else "",
            )
            batch.append(appointment)

            if len(batch) >= batch_size:
                # Salvar objetos relacionados primeiro
                for appointment in batch:
                    appointment.save()
                appointments.extend(batch)
                batch = []

                # Marcar slots como ocupados
                slot_ids = [
                    app.slot_id
                    for app in batch
                    if app.status in ["scheduled", "confirmed", "completed"]
                ]
                ScheduleSlot.objects.filter(id__in=slot_ids).update(is_available=False)

        # Criar último batch
        if batch:
            for appointment in batch:
                appointment.save()
            appointments.extend(batch)

            # Marcar slots como ocupados
            slot_ids = [
                app.slot_id
                for app in batch
                if app.status in ["scheduled", "confirmed", "completed"]
            ]
            ScheduleSlot.objects.filter(id__in=slot_ids).update(is_available=False)

        return appointments
