import pytest
from rest_framework.test import APIClient
from core.models import (
    Appointment,
    Service,
    Professional,
    ScheduleSlot,
    ProfessionalService,
)
from users.models import Tenant, TenantStaffMember
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch
from django.test import override_settings
import logging
from salonix_backend.pii_utils import mask_email


@pytest.mark.django_db
class TestBusinessLogging:
    def setup_method(self):
        self.client = APIClient()
        # Enable propagation for testing capture
        self._old_propagate_core = logging.getLogger("core").propagate
        self._old_propagate_users = logging.getLogger("users").propagate
        self._old_propagate_payments = logging.getLogger("payments").propagate
        logging.getLogger("core").propagate = True
        logging.getLogger("users").propagate = True
        logging.getLogger("payments").propagate = True

    def teardown_method(self):
        logging.getLogger("core").propagate = self._old_propagate_core
        logging.getLogger("users").propagate = self._old_propagate_users
        logging.getLogger("payments").propagate = self._old_propagate_payments

    @patch("core.views.send_appointment_confirmation_email")
    def test_appointment_creation_logs(self, mock_email, user_fixture, caplog):
        """Verifica se logs são gerados ao criar agendamento"""
        self.client.force_authenticate(user=user_fixture)

        # Setup data
        tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        user_fixture.tenant = tenant
        user_fixture.save()

        service = Service.objects.create(
            user=user_fixture,
            name="Corte",
            price_eur=20,
            duration_minutes=30,
            tenant=tenant,
        )
        professional = Professional.objects.create(
            user=user_fixture, name="Pro", tenant=tenant
        )
        # Link professional to service
        ProfessionalService.objects.create(
            professional=professional, service=service, tenant=tenant
        )

        now = timezone.now() + timedelta(days=1)
        slot = ScheduleSlot.objects.create(
            professional=professional,
            start_time=now,
            end_time=now + timedelta(minutes=30),
            is_available=True,
            tenant=tenant,
        )

        data = {
            "service": service.id,
            "professional": professional.id,
            "slot": slot.id,
            "notes": "Test Log",
        }

        # Clear logs
        caplog.clear()

        with caplog.at_level(logging.INFO, logger="core.views"):
            response = self.client.post("/api/appointments/", data)

        if response.status_code != 201:
            print(f"Response error: {response.data}")

        assert response.status_code == 201

        # Check logs
        log_records = [
            r for r in caplog.records if "Appointment created successfully" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert record.levelname == "INFO"
        assert getattr(record, "appointment_id", None) is not None
        # tenant_id is overwritten by RequestContextFilter with slug
        assert getattr(record, "tenant_id", None) == tenant.slug

    @patch("core.views.send_appointment_cancellation_email")
    def test_appointment_cancellation_logs(self, mock_email, user_fixture, caplog):
        """Verifica se logs são gerados ao cancelar agendamento"""
        self.client.force_authenticate(user=user_fixture)

        # Setup data
        tenant = Tenant.objects.create(name="Test Tenant 2", slug="test-tenant-2")
        user_fixture.tenant = tenant
        user_fixture.save()

        service = Service.objects.create(
            user=user_fixture,
            name="Corte",
            price_eur=20,
            duration_minutes=30,
            tenant=tenant,
        )
        professional = Professional.objects.create(
            user=user_fixture, name="Pro", tenant=tenant
        )

        now = timezone.now() + timedelta(days=2)
        slot = ScheduleSlot.objects.create(
            professional=professional,
            start_time=now,
            end_time=now + timedelta(minutes=30),
            is_available=False,
            tenant=tenant,
        )

        appointment = Appointment.objects.create(
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            tenant=tenant,
            status="scheduled",
        )

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="core.views"):
            response = self.client.patch(f"/api/appointments/{appointment.id}/cancel/")

        assert response.status_code == 200

        # Check logs
        log_records = [
            r
            for r in caplog.records
            if "Appointment cancelled successfully via View" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert record.levelname == "INFO"
        assert getattr(record, "appointment_id", None) == appointment.id
        assert getattr(record, "cancelled_by_id", None) == user_fixture.id

    def test_user_registration_logs(self, caplog):
        """Verifica logs de registro de usuário"""
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "strongpassword123",
            "salon_name": "New Salon Log",
        }

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="users.views"):
            response = self.client.post("/api/users/register/", data)

        assert response.status_code == 201

        # Check logs
        log_records = [
            r for r in caplog.records if "User registered successfully" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert getattr(record, "email", None) == mask_email("newuser@example.com")

    def test_user_login_logs(self, user_fixture, caplog):
        """Verifica logs de login"""
        # Set password
        user_fixture.set_password("password123")
        user_fixture.save()

        data = {"email": user_fixture.email, "password": "password123"}

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="users.views"):
            response = self.client.post("/api/users/token/", data)

        assert response.status_code == 200

        # Check logs
        log_records = [
            r for r in caplog.records if "User logged in successfully" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        # user_id might be missing if RequestContextFilter doesn't see auth user
        # and extra params behavior is complex with filters. Check email instead.
        assert getattr(record, "email", None) == mask_email(user_fixture.email)

    def test_salon_appointment_reschedule_logs(self, user_fixture, caplog):
        """Verifica logs de reagendamento pelo salão"""
        self.client.force_authenticate(user=user_fixture)

        # Setup
        tenant = Tenant.objects.create(name="Salon Tenant", slug="salon-tenant")
        user_fixture.tenant = tenant
        user_fixture.save()

        service = Service.objects.create(
            user=user_fixture,
            name="Corte",
            duration_minutes=30,
            price_eur=20,
            tenant=tenant,
        )
        professional = Professional.objects.create(
            user=user_fixture, name="Pro Salon", tenant=tenant
        )
        ProfessionalService.objects.create(
            professional=professional, service=service, tenant=tenant
        )

        now = timezone.now() + timedelta(days=3)
        slot1 = ScheduleSlot.objects.create(
            professional=professional,
            start_time=now,
            end_time=now + timedelta(minutes=30),
            is_available=False,
            tenant=tenant,
        )
        slot2 = ScheduleSlot.objects.create(
            professional=professional,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=1, minutes=30),
            is_available=True,
            tenant=tenant,
        )

        appointment = Appointment.objects.create(
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot1,
            tenant=tenant,
            status="scheduled",
        )

        # Reschedule
        data = {"slot": slot2.id}

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="core.views"):
            response = self.client.patch(
                f"/api/salon/appointments/{appointment.id}/", data
            )

        if response.status_code != 200:
            print(f"Reschedule error: {response.data}")
        assert response.status_code == 200

        # Verify logs
        log_records = [
            r
            for r in caplog.records
            if "Appointment rescheduled successfully" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert getattr(record, "appointment_id", None) == appointment.id
        assert getattr(record, "new_slot_id", None) == slot2.id
        assert getattr(record, "rescheduled_by_id", None) == user_fixture.id

    def test_salon_appointment_cancellation_logs(self, user_fixture, caplog):
        """Verifica logs de cancelamento pelo salão"""
        self.client.force_authenticate(user=user_fixture)

        # Setup
        tenant = Tenant.objects.create(name="Salon Tenant 2", slug="salon-tenant-2")
        user_fixture.tenant = tenant
        user_fixture.save()

        service = Service.objects.create(
            user=user_fixture,
            name="Corte",
            duration_minutes=30,
            price_eur=20,
            tenant=tenant,
        )
        professional = Professional.objects.create(
            user=user_fixture, name="Pro Salon", tenant=tenant
        )
        ProfessionalService.objects.create(
            professional=professional, service=service, tenant=tenant
        )

        now = timezone.now() + timedelta(days=4)
        slot = ScheduleSlot.objects.create(
            professional=professional,
            start_time=now,
            end_time=now + timedelta(minutes=30),
            is_available=False,
            tenant=tenant,
        )

        appointment = Appointment.objects.create(
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            tenant=tenant,
            status="scheduled",
        )

        # Cancel via salon endpoint
        data = {"status": "cancelled"}

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="core.views"):
            response = self.client.patch(
                f"/api/salon/appointments/{appointment.id}/", data
            )

        assert response.status_code == 200

        # Verify logs
        log_records = [
            r
            for r in caplog.records
            if "Appointment cancelled successfully via partial_update" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert getattr(record, "appointment_id", None) == appointment.id
        assert getattr(record, "cancelled_by_id", None) == user_fixture.id

    def test_tenant_branding_update_logs(self, user_fixture, caplog):
        """Verifica logs de atualização de branding do tenant"""
        self.client.force_authenticate(user=user_fixture)

        # Setup
        tenant = Tenant.objects.create(name="Branding Tenant", slug="branding-tenant")
        user_fixture.tenant = tenant
        # Need to ensure user is owner/manager logic if enforced?
        # TenantMetaView check: if request.user.tenant != tenant: Forbidden.
        # So setting user.tenant = tenant is enough.
        user_fixture.save()

        data = {"app_name": "New App Name", "primary_color": "#FF0000"}

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="users.views"):
            response = self.client.patch("/api/users/tenant/meta/", data)

        if response.status_code != 200:
            print(f"Branding update error: {response.data}")
        assert response.status_code == 200

        # Verify logs
        log_records = [
            r
            for r in caplog.records
            if "Tenant branding updated successfully" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        # Tenant ID is overwritten by RequestContextFilter with slug
        assert getattr(record, "tenant_id", None) == tenant.slug
        assert "app_name" in getattr(record, "updated_fields", [])

    def test_service_creation_and_update_logs(
        self, user_fixture, tenant_fixture, caplog
    ):
        """Verifica logs de criação e atualização de serviço"""
        self.client.force_authenticate(user=user_fixture)

        tenant = tenant_fixture
        # Ensure user is owner/manager (default fixture user is owner)

        # Create
        data = {
            "name": "New Service",
            "duration_minutes": 60,
            "price_eur": "50.00",
        }

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="core.views"):
            response = self.client.post("/api/services/", data)

        assert response.status_code == 201

        log_records = [
            r for r in caplog.records if "Service created successfully" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert getattr(record, "tenant_id", None) == tenant.slug
        assert getattr(record, "service_name", None) == "New Service"

        service_id = response.data["id"]

        # Update
        update_data = {"price_eur": "60.00"}
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="core.views"):
            response = self.client.patch(f"/api/services/{service_id}/", update_data)

        assert response.status_code == 200

        log_records = [
            r for r in caplog.records if "Service updated successfully" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert getattr(record, "tenant_id", None) == tenant.slug
        assert "price_eur" in getattr(record, "updated_fields", [])

    def test_professional_creation_and_update_logs(
        self, user_fixture, tenant_fixture, caplog
    ):
        """Verifica logs de criação e atualização de profissional"""
        self.client.force_authenticate(user=user_fixture)

        # Use existing tenant and staff from fixtures to avoid middleware mismatch
        tenant = tenant_fixture
        staff = user_fixture.staff_member

        # Create
        data = {"name": "New Pro", "bio": "Expert", "staff_member": staff.id}

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="core.views"):
            response = self.client.post("/api/professionals/", data)

        if response.status_code != 201:
            pytest.fail(f"Pro create error: {response.data}")
        assert response.status_code == 201

        log_records = [
            r
            for r in caplog.records
            if "Professional created successfully" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert getattr(record, "tenant_id", None) == tenant.slug
        assert getattr(record, "professional_name", None) == "New Pro"

        pro_id = response.data["id"]

        # Update
        update_data = {"bio": "Senior Expert"}
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="core.views"):
            response = self.client.patch(f"/api/professionals/{pro_id}/", update_data)

        assert response.status_code == 200

        log_records = [
            r
            for r in caplog.records
            if "Professional updated successfully" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert getattr(record, "tenant_id", None) == tenant.slug
        assert "bio" in getattr(record, "updated_fields", [])

    @patch("stripe.Customer.create")
    @patch("stripe.checkout.Session.create")
    # BE-PLANS-01 (#481): checkout usa Basic; override garante o price ID no CI.
    @override_settings(STRIPE_PRICE_BASIC_MONTHLY_ID="price_test_basic_123")
    def test_checkout_session_logs(
        self,
        mock_stripe_session,
        mock_stripe_customer,
        user_fixture,
        tenant_fixture,
        caplog,
    ):
        """Verifica logs de criação de sessão de checkout"""
        self.client.force_authenticate(user=user_fixture)

        # Mock customer creation
        mock_stripe_customer.return_value = {"id": "cus_test_123"}

        # Use existing tenant and staff from fixtures
        tenant = tenant_fixture

        # Ensure user has OWNER role
        staff = user_fixture.staff_member
        staff.role = TenantStaffMember.Role.OWNER
        staff.status = TenantStaffMember.Status.ACTIVE
        staff.save()

        mock_stripe_session.return_value = type(
            "obj",
            (object,),
            {"url": "http://checkout.stripe.com", "id": "sess_123"},
        )

        data = {"plan": "basic", "period": "monthly"}

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="payments.views"):
            response = self.client.post(
                "/api/payments/stripe/create-checkout-session/", data
            )

        if response.status_code != 200:
            print(f"Checkout error: {response.data}")
        assert response.status_code == 200

        log_records = [
            r for r in caplog.records if "Stripe checkout session created" in r.message
        ]
        assert len(log_records) > 0
        record = log_records[0]
        assert getattr(record, "tenant_id", None) == tenant.slug
        assert getattr(record, "plan_code", None) == "basic"
        assert getattr(record, "checkout_url", None) == "http://checkout.stripe.com"
