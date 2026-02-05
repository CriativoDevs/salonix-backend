# Account Cancellation Operations Guide

**Version:** 1.0  
**Date:** February 2026  
**Feature:** BE-ACCOUNT-CANCEL #396

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Cancellation Flow](#cancellation-flow)
3. [Administrative Operations](#administrative-operations)
4. [Backup and Restore](#backup-and-restore)
5. [Troubleshooting](#troubleshooting)
6. [Monitoring](#monitoring)
7. [FAQ](#faq)

---

## Overview

### What is Account Cancellation?

A soft-delete system that allows tenants to cancel their accounts with:
- **Retention period**: 30 days for reactivation
- **Stripe cancellation**: Automatic for all subscriptions
- **Transactional emails**: Confirmation, reminders, reactivation
- **Scheduled hard delete**: After retention period

### Tenant States

```python
ACTIVE = 'active'           # Active and operational account
CANCELLED = 'cancelled'     # Cancelled, awaiting deletion
DELETED = 'deleted'         # Hard delete executed (not restorable)
```

### Cancellation Timeline

```
Day 0: Cancellation
├─ Status = 'cancelled'
├─ cancelled_at = now()
├─ scheduled_deletion_at = now() + 30 days
├─ reactivation_token generated
└─ Confirmation email sent

Day 23: Automatic reminder
└─ Email 7 days before deletion

Day 30: Hard Delete
├─ Backup exported
├─ Data deleted (GDPR compliant)
└─ Status = 'deleted'
```

---

## Cancellation Flow

### 1. Cancellation by Owner

**Endpoint:** `POST /api/tenants/cancel/`

**Validations:**
- ✅ User must be tenant OWNER
- ✅ Password required
- ✅ Confirmation text: "CANCEL MY ACCOUNT"

**Request:**
```json
{
  "password": "userPassword",
  "confirmation_text": "CANCEL MY ACCOUNT"
}
```

**Response (Success):**
```json
{
  "message": "Account cancelled successfully",
  "reactivation_deadline": "2026-03-07T14:30:00Z",
  "reactivation_token": "abc123...xyz"
}
```

**Automatic Actions:**
1. Stripe: Cancels all active subscriptions
2. Tenant: Changes status to `cancelled`
3. Email: Sends confirmation with reactivation link
4. Logs: Records operation in audit log

### 2. Reactivation by Owner

**Endpoint:** `POST /api/tenants/reactivate/`

**Validations:**
- ✅ Valid and non-expired token
- ✅ Within retention period (30 days)
- ✅ Tenant in `cancelled` status

**Request:**
```json
{
  "token": "abc123...xyz"
}
```

**Response (Success):**
```json
{
  "message": "Account reactivated successfully",
  "tenant": {
    "id": 123,
    "status": "active",
    "name": "Example Salon"
  }
}
```

**Automatic Actions:**
1. Tenant: Returns to `active` status
2. Clears: `cancelled_at`, `scheduled_deletion_at`, `reactivation_token`
3. Email: Sends reactivation welcome message

---

## Administrative Operations

### Revert Cancellation (Django Admin)

**When to use:**
- Customer requested reactivation via support
- Reactivation token expired/lost
- Error in cancellation process

**Step by step:**

1. **Via Django Admin** (Recommended):
```bash
# Access /admin/core/tenant/
# Search for tenant
# Edit fields:
- status: 'active'
- cancelled_at: null
- scheduled_deletion_at: null
- reactivation_token: ''
```

2. **Via Django Shell**:
```python
from core.models import Tenant

tenant = Tenant.objects.get(id=123)
tenant.status = 'active'
tenant.cancelled_at = None
tenant.scheduled_deletion_at = None
tenant.reactivation_token = ''
tenant.save()

print(f"✅ Tenant {tenant.name} reactivated successfully")
```

3. **Notify Customer**:
```python
from core.email_utils import send_account_reactivation_email

send_account_reactivation_email(
    tenant=tenant,
    owner_email='owner@example.com',
    owner_name='John Doe'
)
```

### Postpone Hard Delete

**Scenario:** Customer needs more time to decide

```python
from datetime import timedelta
from django.utils import timezone

tenant = Tenant.objects.get(id=123)

# Add 15 days to current deadline
tenant.scheduled_deletion_at += timedelta(days=15)
tenant.save()

print(f"🕐 New deletion date: {tenant.scheduled_deletion_at}")
```

### Force Immediate Hard Delete

**⚠️ WARNING: Irreversible operation!**

```python
from core.tasks import hard_delete_tenant_data

tenant = Tenant.objects.get(id=123)

# Create manual backup first!
print(f"📦 Backing up tenant {tenant.id}...")
# ... export data ...

# Execute hard delete
hard_delete_tenant_data(tenant_id=tenant.id)

print("🗑️ Tenant permanently deleted")
```

### Cancel Without Retention (Internal Use)

**Scenario:** Fraud, ToS violation, GDPR request

```python
from core.models import Tenant
from payments.services import SubscriptionService

tenant = Tenant.objects.get(id=123)

# 1. Cancel Stripe subscriptions
result = SubscriptionService.cancel_tenant_subscriptions(tenant)
print(f"💳 Stripe: {result['cancelled_count']} subscriptions cancelled")

# 2. Immediate hard delete
tenant.status = 'deleted'
tenant.save()

# 3. Execute cleanup
from core.tasks import hard_delete_tenant_data
hard_delete_tenant_data(tenant_id=tenant.id)
```

---

## Backup and Restore

### Automatic Backup

**When it happens:**
- Before each hard delete
- Executed by `hard_delete_tenant_data` task

**Location:**
```
/backups/tenants/{tenant_id}_{timestamp}/
├── tenant_metadata.json
├── appointments.json
├── clients.json
├── professionals.json
├── services.json
└── README.txt
```

**Backup Structure:**
```json
{
  "backup_date": "2026-02-05T14:30:00Z",
  "tenant_id": 123,
  "tenant_name": "Example Salon",
  "tenant_slug": "example-salon",
  "owner_email": "owner@example.com",
  "cancelled_at": "2026-01-05T14:30:00Z",
  "records": {
    "appointments": 1250,
    "clients": 450,
    "professionals": 8,
    "services": 25
  }
}
```

### Manual Backup

```python
from core.tasks import export_tenant_data

tenant = Tenant.objects.get(id=123)
backup_path = export_tenant_data(tenant)

print(f"✅ Backup saved at: {backup_path}")
```

### Restore (Manual Procedure)

**⚠️ No automatic restore. Manual procedure:**

1. **Locate Backup:**
```bash
ls -la backups/tenants/123_*
```

2. **Create New Tenant:**
```python
from core.models import Tenant

# Create new tenant with same slug (or new one)
new_tenant = Tenant.objects.create(
    name="Example Salon (Restored)",
    slug="example-salon-restored",
    status='active'
)
```

3. **Import Data:**
```python
import json

# Load backup
with open('backups/tenants/123_2026-02-05/clients.json') as f:
    clients_data = json.load(f)

# Recreate records
from core.models import Client
for client_data in clients_data:
    Client.objects.create(
        tenant=new_tenant,
        name=client_data['name'],
        phone=client_data['phone'],
        # ... other fields
    )
```

4. **Notify Customer:**
- Email informing about restoration
- New access link
- Password reset instructions (if needed)

---

## Troubleshooting

### Problem: Cancellation email not sent

**Symptoms:**
- Cancellation completed but owner didn't receive email

**Diagnosis:**
```python
# Check Celery logs
tail -f /var/log/celery/celery.log | grep "send_account_cancellation_email"

# Check tenant status
tenant = Tenant.objects.get(id=123)
print(f"Status: {tenant.status}")
print(f"Cancelled at: {tenant.cancelled_at}")
print(f"Token: {tenant.reactivation_token[:20]}...")
```

**Solution:**
```python
# Resend email manually
from core.email_utils import send_account_cancellation_email

send_account_cancellation_email(
    tenant=tenant,
    owner_email='owner@example.com',
    owner_name='John Doe'
)
```

### Problem: Stripe didn't cancel subscriptions

**Symptoms:**
- Tenant cancelled but subscriptions still active in Stripe

**Diagnosis:**
```python
from payments.models import Subscription

# Check subscriptions
subs = Subscription.objects.filter(
    user__tenant=tenant,
    status='active'
)
print(f"📊 Active subscriptions: {subs.count()}")
```

**Solution:**
```python
from payments.services import SubscriptionService

result = SubscriptionService.cancel_tenant_subscriptions(tenant)
print(f"✅ Cancelled: {result['cancelled_count']}")
print(f"❌ Errors: {result['errors']}")
```

### Problem: Hard delete didn't execute

**Symptoms:**
- Deletion date passed but tenant still exists

**Diagnosis:**
```python
from django.utils import timezone

tenant = Tenant.objects.get(id=123)
print(f"Status: {tenant.status}")
print(f"Scheduled deletion: {tenant.scheduled_deletion_at}")
print(f"Now: {timezone.now()}")
print(f"Overdue: {timezone.now() > tenant.scheduled_deletion_at}")

# Check Celery Beat
# Confirm task is scheduled
```

**Solution:**
```python
# Execute manually
from core.tasks import check_expired_tenants, hard_delete_tenant_data

# Find expired tenants
check_expired_tenants()

# Or force specific hard delete
hard_delete_tenant_data(tenant_id=123)
```

### Problem: Invalid reactivation token

**Symptoms:**
- Customer tries to reactivate but token doesn't work

**Diagnosis:**
```python
tenant = Tenant.objects.get(id=123)

# Check saved token
print(f"Saved token: {tenant.reactivation_token[:20]}...")

# Check deadline
from django.utils import timezone
print(f"Scheduled deletion: {tenant.scheduled_deletion_at}")
print(f"Expired: {timezone.now() > tenant.scheduled_deletion_at}")
```

**Solution:**
```python
# Generate new token and extend deadline
from datetime import timedelta
from django.utils import timezone

tenant.reactivation_token = tenant.generate_reactivation_token()
tenant.scheduled_deletion_at = timezone.now() + timedelta(days=7)
tenant.save()

# Send new email with updated token
from core.email_utils import send_account_cancellation_email
send_account_cancellation_email(
    tenant=tenant,
    owner_email='owner@example.com',
    owner_name='John Doe'
)
```

### Problem: Deletion reminder not sent

**Symptoms:**
- Tenant 7 days before deletion but didn't receive reminder

**Diagnosis:**
```bash
# Check Celery Beat logs
tail -f /var/log/celery/celery-beat.log

# Check task scheduling
python manage.py shell
>>> from django_celery_beat.models import PeriodicTask
>>> task = PeriodicTask.objects.get(name='send-deletion-reminders')
>>> print(f"Enabled: {task.enabled}")
>>> print(f"Last run: {task.last_run_at}")
```

**Solution:**
```python
# Execute task manually
from core.tasks import send_deletion_reminders

send_deletion_reminders()

# Or send specific email
from core.email_utils import send_deletion_reminder_email

tenant = Tenant.objects.get(id=123)
send_deletion_reminder_email(
    tenant=tenant,
    owner_email='owner@example.com',
    owner_name='John Doe',
    days_remaining=7
)
```

---

## Monitoring

### Recommended Metrics

**1. Cancellation Rate:**
```python
from django.utils import timezone
from datetime import timedelta

# Cancellations in last 30 days
last_month = timezone.now() - timedelta(days=30)
cancellations = Tenant.objects.filter(
    status='cancelled',
    cancelled_at__gte=last_month
).count()

total_active = Tenant.objects.filter(status='active').count()
churn_rate = (cancellations / total_active) * 100

print(f"📉 Cancellation rate: {churn_rate:.2f}%")
```

**2. Reactivation Rate:**
```python
# Tenants that reactivated after cancelling
reactivations = Tenant.objects.filter(
    status='active',
    cancelled_at__isnull=False  # Previously cancelled
).count()

reactivation_rate = (reactivations / cancellations) * 100
print(f"📈 Reactivation rate: {reactivation_rate:.2f}%")
```

**3. Pending Deletion Tenants:**
```python
from django.utils import timezone

pending = Tenant.objects.filter(
    status='cancelled',
    scheduled_deletion_at__gt=timezone.now()
).count()

print(f"⏳ Pending deletion: {pending}")
```

**4. Executed Hard Deletes:**
```python
deleted = Tenant.objects.filter(status='deleted').count()
print(f"🗑️ Hard deletes executed: {deleted}")
```

### Logs to Monitor

**1. Celery Worker:**
```bash
tail -f /var/log/celery/celery.log | grep -E "(hard_delete|check_expired|deletion_reminder)"
```

**2. Celery Beat:**
```bash
tail -f /var/log/celery/celery-beat.log
```

**3. Django Application:**
```bash
tail -f /var/log/django/app.log | grep -E "(TenantCancel|TenantReactivate)"
```

### Recommended Alerts

1. **Cancellation spike**: > 10% in 24h
2. **Hard delete failed**: Tenant with scheduled_deletion_at in past and status != deleted
3. **Emails not sent**: Failures in Celery email task
4. **Stripe sync issues**: Errors cancelling subscriptions

---

## FAQ

### Q: Can I revert a hard delete?

**A:** Not directly. Hard delete is permanent. However:
- ✅ Automatic backup exists before deletion
- ✅ Manual restore is possible (see [Backup and Restore](#backup-and-restore))
- ⚠️ Requires creating new tenant and manual data import

### Q: What happens to Stripe subscriptions?

**A:** 
- All active subscriptions are cancelled immediately
- Stripe is notified via API
- No future charges occur
- Already-paid period remains available until end

### Q: Do salon customers receive notification?

**A:**
- ❌ Customers do NOT receive automatic email
- ✅ Recommended: Owner notifies customers before cancelling
- ✅ Frontend can show banner/modal before cancellation

### Q: Can I cancel a tenant without being owner?

**A:**
- ❌ Only OWNER can cancel via API
- ✅ Django Admin can cancel (superuser/staff)
- ✅ System operations can force cancellation

### Q: Does hard delete really delete everything?

**A:**
Yes, deleted items include:
- ✅ Appointments
- ✅ Clients
- ✅ Professionals
- ✅ Services
- ✅ TenantStaffMembers
- ✅ CustomUser (if no other tenants)
- ✅ Tenant metadata

Preserved:
- ✅ Backup in `/backups/tenants/`
- ✅ Audit logs (if configured)

### Q: How long is the backup stored?

**A:**
- Indefinitely (or according to retention policy)
- Recommended: Move to cold storage after 90 days
- GDPR: Customer can request backup deletion

### Q: Can I test cancellation in staging?

**A:**
Yes! Use test data:
1. Create test tenant
2. Use Stripe test keys
3. Execute cancellation
4. Wait for Celery tasks
5. Check emails (MailHog/Mailtrap)

### Q: How to debug Celery issues?

**A:**
```bash
# Worker status
celery -A salonix_backend inspect active

# Scheduled tasks
celery -A salonix_backend inspect scheduled

# View logs in real-time
tail -f /var/log/celery/celery.log

# Execute task manually
python manage.py shell
>>> from core.tasks import send_deletion_reminders
>>> send_deletion_reminders.delay()
```

---

## Compliance and GDPR

### Right to be Forgotten

The cancellation system complies with GDPR:
- ✅ Permanent deletion of personal data after 30 days
- ✅ Backup can be deleted on request
- ✅ Process is documented and auditable

### GDPR Request Procedure

1. Customer requests immediate deletion:
```python
# No retention period
tenant.status = 'deleted'
tenant.save()

# Immediate hard delete
from core.tasks import hard_delete_tenant_data
hard_delete_tenant_data(tenant_id=tenant.id)

# Delete backup
import shutil
shutil.rmtree(f'/backups/tenants/{tenant.id}_*')
```

2. Document compliance:
- Record request in audit log
- Confirm deletion via email
- Keep operation record (without PII)

---

## Support Contacts

**Operations Team:**
- Email: ops@timelyone.com
- Slack: #ops-support

**Emergencies:**
- On-call: +55 11 99999-9999
- Escalation: tech-lead@timelyone.com

**Additional Documentation:**
- [Celery Production Guide](../celery_prod_run.md)
- [System Architecture](ARQUITETURA_SISTEMA.md)
- [OpenAPI Documentation](API_OPENAPI.md)

---

**Last update:** February 2026  
**Revision:** v1.0  
**Next review:** May 2026
