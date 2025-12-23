import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from ops.models import OpsSupportAuditLog
from users.models import Tenant, CustomUser

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds Ops Audit Logs for testing"

    def handle(self, *args, **options):
        self.stdout.write("Seeding Ops Audit Logs...")

        # Ensure we have an Ops Admin
        ops_admin = User.objects.filter(ops_role=CustomUser.OpsRoles.OPS_ADMIN).first()
        if not ops_admin:
            self.stdout.write(self.style.WARNING("No Ops Admin found. Creating one..."))
            ops_admin = User.objects.create_user(
                email="opsadmin@example.com",
                password="password123",
                ops_role=CustomUser.OpsRoles.OPS_ADMIN,
                first_name="Ops",
                last_name="Admin",
            )

        # Get some targets
        tenants = list(Tenant.objects.all())
        users = list(User.objects.exclude(id=ops_admin.id))

        actions = [
            OpsSupportAuditLog.Actions.RESEND_NOTIFICATION,
            OpsSupportAuditLog.Actions.CLEAR_LOCKOUT,
            OpsSupportAuditLog.Actions.RESOLVE_ALERT,
        ]

        # Generate 50 logs
        created_count = 0
        now = timezone.now()

        for i in range(50):
            action = random.choice(actions)
            target_tenant = random.choice(tenants) if tenants else None
            target_user = random.choice(users) if users else None

            # Generate random time in last 30 days
            days_ago = random.randint(0, 30)
            log_time = now - timedelta(days=days_ago, minutes=random.randint(0, 1440))

            payload = {}
            if action == OpsSupportAuditLog.Actions.RESEND_NOTIFICATION:
                payload = {
                    "notification_id": random.randint(1000, 9999),
                    "channel": random.choice(["sms", "email"]),
                }
            elif action == OpsSupportAuditLog.Actions.CLEAR_LOCKOUT:
                payload = {"resolved_count": random.randint(1, 5)}
            elif action == OpsSupportAuditLog.Actions.RESOLVE_ALERT:
                payload = {
                    "alert_id": random.randint(100, 500),
                    "message": "High CPU usage",
                }

            log = OpsSupportAuditLog.objects.create(
                actor=ops_admin,
                action=action,
                target_tenant=target_tenant,
                target_user=target_user,
                payload=payload,
                result={"status": "success"},
            )
            # Hack to update created_at since auto_now_add sets it on creation
            OpsSupportAuditLog.objects.filter(id=log.id).update(created_at=log_time)
            created_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Successfully created {created_count} audit logs.")
        )
