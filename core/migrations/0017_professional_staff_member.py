from django.db import migrations, models


def link_professionals_to_staff(apps, schema_editor):
  Professional = apps.get_model('core', 'Professional')
  TenantStaffMember = apps.get_model('users', 'TenantStaffMember')

  staff_by_user = {
    staff.user_id: staff.id
    for staff in TenantStaffMember.objects.all().only('id', 'user_id')
  }

  batch = []
  for professional in Professional.objects.all().only('id', 'user_id'):
    staff_id = staff_by_user.get(professional.user_id)
    if staff_id:
      batch.append((professional.id, staff_id))

  for professional_id, staff_id in batch:
    Professional.objects.filter(id=professional_id).update(staff_member_id=staff_id)


class Migration(migrations.Migration):

  dependencies = [
    ('users', '0013_tenantstaffmember'),
    ('core', '0016_populate_appointment_customer'),
  ]

  operations = [
    migrations.AddField(
      model_name='professional',
      name='staff_member',
      field=models.ForeignKey(blank=True, help_text='Staff associado a este profissional (quando aplicável).', null=True, on_delete=models.SET_NULL, related_name='professionals', to='users.tenantstaffmember'),
    ),
    migrations.AddIndex(
      model_name='professional',
      index=models.Index(fields=['tenant', 'staff_member'], name='core_prof_tenant_staff_idx'),
    ),
    migrations.RunPython(link_professionals_to_staff, migrations.RunPython.noop),
  ]
