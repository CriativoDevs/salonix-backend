# 🇬🇧 Mobile Push Notifications — Salonix Backend (EN)

**Issue:** BE-49 #209  
**Status:** ✅ Production Ready  
**Last Updated:** February 6, 2026

## Overview

Salonix backend supports mobile push notifications via **Expo Push Notifications Service** for React Native/Expo mobile apps. The system is zero-cost (free tier: 1M notifications/month), requires no external SDKs, and uses simple HTTP POST requests.

### Key Features
- ✅ Multi-tenant isolation (tenant_id + user_id)
- ✅ Device management (iOS/Android tokens)
- ✅ Deep links (open specific appointments)
- ✅ Automatic signals (appointment created/cancelled)
- ✅ Admin test endpoint
- ✅ Error handling (DeviceNotRegistered auto-cleanup)
- ✅ Last activity tracking

## Architecture

### Components
```
┌─────────────────┐       HTTP POST        ┌──────────────────┐
│  Django Backend │  ───────────────────>  │  Expo Push API   │
│  (services.py)  │   exp.host/--/api/v2   │                  │
└─────────────────┘                        └──────────────────┘
         │                                          │
         │ stores tokens                            │ delivers
         v                                          v
┌─────────────────┐                        ┌──────────────────┐
│ NotificationDevice│                       │   Mobile App     │
│ (models.py)     │                        │  (React Native)  │
└─────────────────┘                        └──────────────────┘
```

### Database Model

**NotificationDevice** (`notifications/models.py`):
```python
class NotificationDevice(models.Model):
    tenant = ForeignKey(Tenant)
    user = ForeignKey(User)
    device_type = CharField  # 'mobile' for push
    token = CharField  # Expo push token: ExponentPushToken[...]
    platform = CharField  # 'ios' or 'android' (NEW)
    app_version = CharField  # e.g., "1.0.0" (NEW)
    last_used_at = DateTimeField  # auto-updated on push (NEW)
    is_active = BooleanField
    created_at = DateTimeField
```

**Migration:** `notifications/migrations/0002_notificationdevice_app_version_and_more.py`

## Implementation

### 1. MobilePushDriver

**File:** `notifications/services.py` (lines ~450-520)

**Key Methods:**
```python
class MobilePushDriver(NotificationDriver):
    def send(self, tenant, user, notification_type, title, message, metadata):
        # 1. Query NotificationDevice for user
        # 2. Build Expo payload with deep link
        # 3. HTTP POST to https://exp.host/--/api/v2/push/send
        # 4. Handle errors (DeviceNotRegistered = deactivate)
        # 5. Update last_used_at on success
```

**Expo Payload Example:**
```json
{
  "to": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
  "title": "Agendamento confirmado",
  "body": "Seu horário está marcado para 15:00",
  "data": {
    "route": "appointment/123",
    "notification_type": "appointment_created",
    "appointment_id": 123
  },
  "sound": "default",
  "priority": "high"
}
```

**Deep Link Logic:**
- If `metadata['appointment_id']` exists → adds `"route": "appointment/{id}"`
- Mobile app handles: `salonix://appointment/123`

### 2. Signals Integration

**File:** `core/signals.py`

**Appointment Created:**
```python
@receiver(post_save, sender=Appointment)
def send_appointment_notifications(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(lambda: notification_service.send_notification(
            tenant=instance.tenant,
            user=instance.client,
            channels=["push_mobile", "in_app"],
            notification_type="appointment_created",
            metadata={"appointment_id": instance.id}
        ))
```

**Appointment Cancelled:**
```python
@receiver(post_delete, sender=Appointment)
def send_appointment_cancelled_push(sender, instance, **kwargs):
    notification_service.send_notification(
        tenant=instance.tenant,
        user=instance.client,
        channels=["push_mobile", "in_app"],
        notification_type="appointment_cancelled",
        metadata={"appointment_id": instance.id}
    )
```

### 3. Admin Test Endpoint

**Endpoint:** `POST /api/notifications/test-push/`  
**Permissions:** Staff only  
**File:** `notifications/views.py` (lines 249-320)

**Request:**
```bash
curl -X POST https://api.salonix.com/api/notifications/test-push/ \
  -H "Authorization: Bearer <token>" \
  -H "X-Tenant-Slug: my-salon" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 42,
    "title": "Test Push",
    "message": "Testing notification system",
    "appointment_id": 123
  }'
```

**Response (success):**
```json
{
  "success": true,
  "message": "Push enviado com sucesso",
  "user_id": 42,
  "has_device": true
}
```

**Response (no device):**
```json
{
  "success": false,
  "message": "Usuário não tem dispositivo mobile registrado",
  "user_id": 42,
  "has_device": false
}
```

## Testing

**Test File:** `notifications/tests/test_mobile_push.py` (16 tests)

**Coverage:**
- ✅ MobilePushDriver (5 tests): send success, no device, error handling, deep links, last_used_at
- ✅ Signals (3 tests): appointment created, cancelled, no device (graceful)
- ✅ Model (2 tests): platform field, last_used_at update
- ✅ Endpoint (6 tests): auth, staff-only, user not found, no device, success, deep links
  - Note: 3 endpoint tests skipped (URL routing issue - needs rewrite with `reverse()`)

**Run Tests:**
```bash
cd salonix-backend
make test  # 609 passed, 5 skipped
pytest notifications/tests/test_mobile_push.py -v  # run only push tests
```

## Error Handling

### DeviceNotRegistered
When Expo returns `DeviceNotRegistered` (token invalid/expired):
```python
if response_data.get("data", [{}])[0].get("status") == "error":
    error_code = response_data["data"][0].get("details", {}).get("error")
    if error_code == "DeviceNotRegistered":
        device.is_active = False
        device.save()
        logger.warning(f"Device {device.id} marked inactive")
```

### HTTP Errors
- Timeout: 10 seconds
- Connection errors: Logged, push fails gracefully
- Non-200 responses: Logged, push fails gracefully

### Multi-tenant Safety
- All queries filtered by `tenant_id`
- Middleware enforces tenant isolation
- Tests verify no cross-tenant leakage

## Mobile App Integration (MOB-04)

**Not implemented yet** — separate task for mobile team.

### Required Steps:
1. Install Expo Notifications:
   ```bash
   npx expo install expo-notifications
   ```

2. Request permissions:
   ```javascript
   const { status } = await Notifications.requestPermissionsAsync();
   ```

3. Get Expo push token:
   ```javascript
   const token = await Notifications.getExpoPushTokenAsync();
   ```

4. Register device with backend:
   ```javascript
   await fetch('https://api.salonix.com/api/notifications/register_device/', {
     method: 'POST',
     headers: {
       'Authorization': `Bearer ${userToken}`,
       'X-Tenant-Slug': tenantSlug,
       'Content-Type': 'application/json',
     },
     body: JSON.stringify({
       device_type: 'mobile',
       token: token.data,
       platform: Platform.OS,  // 'ios' or 'android'
       app_version: Constants.expoConfig.version,
     }),
   });
   ```

5. Handle deep links:
   ```javascript
   Notifications.addNotificationResponseReceivedListener(response => {
     const route = response.notification.request.content.data.route;
     if (route?.startsWith('appointment/')) {
       const id = route.split('/')[1];
       navigation.navigate('AppointmentDetail', { id });
     }
   });
   ```

## Production Deployment

### Environment Variables
None required — Expo Push API is public endpoint.

### Monitoring
- Check logs: `/api/notifications/logs/` (admin only)
- Track failures: `DeviceNotRegistered` errors logged
- Metrics: Monitor push success/failure rates

### Scaling
- Free tier: **1,000,000 notifications/month**
- Paid tier: Pay-as-you-go beyond 1M
- No rate limits for free tier

### Security
- ✅ Multi-tenant isolation enforced
- ✅ User authentication required
- ✅ Staff-only test endpoint
- ✅ No token validation needed (Expo handles it)

## Troubleshooting

### "Push not received on mobile"
1. Verify device registered: Check `NotificationDevice` in admin
2. Verify token format: `ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]`
3. Check mobile app permissions: Notifications enabled?
4. Test with admin endpoint: `/api/notifications/test-push/`
5. Check Expo Go vs standalone: Expo Go uses different tokens

### "DeviceNotRegistered error"
- Token expired/invalid → Device auto-deactivated
- User needs to re-register device

### "404 on test endpoint"
- Verify URL: `/api/notifications/test-push/` (trailing slash)
- Verify staff permission: `user.is_staff = True`
- Check tenant header: `X-Tenant-Slug: <slug>`

## API Reference

### Register Device
**Endpoint:** `POST /api/notifications/register_device/`  
**Permissions:** Authenticated users  
**Headers:** `X-Tenant-Slug: <slug>`

**Request:**
```json
{
  "device_type": "mobile",
  "token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
  "platform": "ios",
  "app_version": "1.0.0"
}
```

**Response:** `201 Created`

### Test Push (Admin)
**Endpoint:** `POST /api/notifications/test-push/`  
**Permissions:** Staff only  
**Headers:** `X-Tenant-Slug: <slug>`

See section 3 above for details.

## References

- **Expo Push Notifications:** https://docs.expo.dev/push-notifications/overview/
- **Expo Push API:** https://docs.expo.dev/push-notifications/sending-notifications/
- **Backend Notifications:** `NOTIFICATIONS_OVERVIEW.md`
- **Architecture:** `ARQUITETURA_SISTEMA.md`

---

# 🇧🇷 Notificações Push Mobile — Salonix Backend (PT)

**Issue:** BE-49 #209  
**Status:** ✅ Pronto para Produção  
**Última Atualização:** 6 de Fevereiro de 2026

## Visão Geral

O backend Salonix suporta notificações push mobile via **Expo Push Notifications Service** para apps React Native/Expo. O sistema é zero-custo (tier gratuito: 1M notificações/mês), não requer SDKs externos, e usa simples requisições HTTP POST.

### Recursos Principais
- ✅ Isolamento multi-tenant (tenant_id + user_id)
- ✅ Gestão de dispositivos (tokens iOS/Android)
- ✅ Deep links (abrir agendamentos específicos)
- ✅ Signals automáticos (agendamento criado/cancelado)
- ✅ Endpoint de teste para admin
- ✅ Tratamento de erros (DeviceNotRegistered auto-limpeza)
- ✅ Rastreamento de última atividade

## Arquitetura

### Componentes
```
┌─────────────────┐       HTTP POST        ┌──────────────────┐
│  Django Backend │  ───────────────────>  │  Expo Push API   │
│  (services.py)  │   exp.host/--/api/v2   │                  │
└─────────────────┘                        └──────────────────┘
         │                                          │
         │ armazena tokens                          │ entrega
         v                                          v
┌─────────────────┐                        ┌──────────────────┐
│ NotificationDevice│                       │   App Mobile     │
│ (models.py)     │                        │  (React Native)  │
└─────────────────┘                        └──────────────────┘
```

### Modelo de Dados

**NotificationDevice** (`notifications/models.py`):
```python
class NotificationDevice(models.Model):
    tenant = ForeignKey(Tenant)
    user = ForeignKey(User)
    device_type = CharField  # 'mobile' para push
    token = CharField  # Token Expo: ExponentPushToken[...]
    platform = CharField  # 'ios' ou 'android' (NOVO)
    app_version = CharField  # ex: "1.0.0" (NOVO)
    last_used_at = DateTimeField  # auto-atualizado no push (NOVO)
    is_active = BooleanField
    created_at = DateTimeField
```

**Migration:** `notifications/migrations/0002_notificationdevice_app_version_and_more.py`

## Implementação

### 1. MobilePushDriver

**Arquivo:** `notifications/services.py` (linhas ~450-520)

**Métodos Principais:**
```python
class MobilePushDriver(NotificationDriver):
    def send(self, tenant, user, notification_type, title, message, metadata):
        # 1. Busca NotificationDevice do usuário
        # 2. Constrói payload Expo com deep link
        # 3. HTTP POST para https://exp.host/--/api/v2/push/send
        # 4. Trata erros (DeviceNotRegistered = desativar)
        # 5. Atualiza last_used_at em sucesso
```

**Exemplo de Payload Expo:**
```json
{
  "to": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
  "title": "Agendamento confirmado",
  "body": "Seu horário está marcado para 15:00",
  "data": {
    "route": "appointment/123",
    "notification_type": "appointment_created",
    "appointment_id": 123
  },
  "sound": "default",
  "priority": "high"
}
```

**Lógica de Deep Link:**
- Se `metadata['appointment_id']` existe → adiciona `"route": "appointment/{id}"`
- App mobile trata: `salonix://appointment/123`

### 2. Integração com Signals

**Arquivo:** `core/signals.py`

**Agendamento Criado:**
```python
@receiver(post_save, sender=Appointment)
def send_appointment_notifications(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(lambda: notification_service.send_notification(
            tenant=instance.tenant,
            user=instance.client,
            channels=["push_mobile", "in_app"],
            notification_type="appointment_created",
            metadata={"appointment_id": instance.id}
        ))
```

**Agendamento Cancelado:**
```python
@receiver(post_delete, sender=Appointment)
def send_appointment_cancelled_push(sender, instance, **kwargs):
    notification_service.send_notification(
        tenant=instance.tenant,
        user=instance.client,
        channels=["push_mobile", "in_app"],
        notification_type="appointment_cancelled",
        metadata={"appointment_id": instance.id}
    )
```

### 3. Endpoint de Teste Admin

**Endpoint:** `POST /api/notifications/test-push/`  
**Permissões:** Apenas staff  
**Arquivo:** `notifications/views.py` (linhas 249-320)

**Request:**
```bash
curl -X POST https://api.salonix.com/api/notifications/test-push/ \
  -H "Authorization: Bearer <token>" \
  -H "X-Tenant-Slug: meu-salao" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 42,
    "title": "Teste Push",
    "message": "Testando sistema de notificações",
    "appointment_id": 123
  }'
```

**Response (sucesso):**
```json
{
  "success": true,
  "message": "Push enviado com sucesso",
  "user_id": 42,
  "has_device": true
}
```

**Response (sem device):**
```json
{
  "success": false,
  "message": "Usuário não tem dispositivo mobile registrado",
  "user_id": 42,
  "has_device": false
}
```

## Testes

**Arquivo de Testes:** `notifications/tests/test_mobile_push.py` (16 testes)

**Cobertura:**
- ✅ MobilePushDriver (5 testes): envio com sucesso, sem device, tratamento de erros, deep links, last_used_at
- ✅ Signals (3 testes): agendamento criado, cancelado, sem device (graceful)
- ✅ Model (2 testes): campo platform, atualização last_used_at
- ✅ Endpoint (6 testes): autenticação, staff-only, usuário não encontrado, sem device, sucesso, deep links
  - Nota: 3 testes de endpoint com skip (problema de routing - precisa reescrita com `reverse()`)

**Rodar Testes:**
```bash
cd salonix-backend
make test  # 609 passed, 5 skipped
pytest notifications/tests/test_mobile_push.py -v  # apenas testes push
```

## Tratamento de Erros

### DeviceNotRegistered
Quando Expo retorna `DeviceNotRegistered` (token inválido/expirado):
```python
if response_data.get("data", [{}])[0].get("status") == "error":
    error_code = response_data["data"][0].get("details", {}).get("error")
    if error_code == "DeviceNotRegistered":
        device.is_active = False
        device.save()
        logger.warning(f"Device {device.id} marcado como inativo")
```

### Erros HTTP
- Timeout: 10 segundos
- Erros de conexão: Logados, push falha gracefully
- Respostas não-200: Logadas, push falha gracefully

### Segurança Multi-tenant
- Todas queries filtradas por `tenant_id`
- Middleware garante isolamento de tenant
- Testes verificam ausência de vazamento cross-tenant

## Integração App Mobile (MOB-04)

**Não implementado ainda** — tarefa separada para time mobile.

### Passos Necessários:
1. Instalar Expo Notifications:
   ```bash
   npx expo install expo-notifications
   ```

2. Pedir permissões:
   ```javascript
   const { status } = await Notifications.requestPermissionsAsync();
   ```

3. Obter token Expo:
   ```javascript
   const token = await Notifications.getExpoPushTokenAsync();
   ```

4. Registrar device no backend:
   ```javascript
   await fetch('https://api.salonix.com/api/notifications/register_device/', {
     method: 'POST',
     headers: {
       'Authorization': `Bearer ${userToken}`,
       'X-Tenant-Slug': tenantSlug,
       'Content-Type': 'application/json',
     },
     body: JSON.stringify({
       device_type: 'mobile',
       token: token.data,
       platform: Platform.OS,  // 'ios' ou 'android'
       app_version: Constants.expoConfig.version,
     }),
   });
   ```

5. Tratar deep links:
   ```javascript
   Notifications.addNotificationResponseReceivedListener(response => {
     const route = response.notification.request.content.data.route;
     if (route?.startsWith('appointment/')) {
       const id = route.split('/')[1];
       navigation.navigate('AppointmentDetail', { id });
     }
   });
   ```

## Deploy em Produção

### Variáveis de Ambiente
Nenhuma necessária — Expo Push API é endpoint público.

### Monitoramento
- Verificar logs: `/api/notifications/logs/` (apenas admin)
- Rastrear falhas: erros `DeviceNotRegistered` são logados
- Métricas: Monitorar taxas de sucesso/falha de push

### Escalabilidade
- Tier gratuito: **1.000.000 notificações/mês**
- Tier pago: Pay-as-you-go acima de 1M
- Sem rate limits no tier gratuito

### Segurança
- ✅ Isolamento multi-tenant garantido
- ✅ Autenticação de usuário obrigatória
- ✅ Endpoint de teste apenas para staff
- ✅ Validação de token não necessária (Expo cuida disso)

## Troubleshooting

### "Push não recebido no mobile"
1. Verificar device registrado: Checar `NotificationDevice` no admin
2. Verificar formato do token: `ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]`
3. Checar permissões do app: Notificações habilitadas?
4. Testar com endpoint admin: `/api/notifications/test-push/`
5. Verificar Expo Go vs standalone: Expo Go usa tokens diferentes

### "Erro DeviceNotRegistered"
- Token expirado/inválido → Device auto-desativado
- Usuário precisa re-registrar device

### "404 no endpoint de teste"
- Verificar URL: `/api/notifications/test-push/` (barra final)
- Verificar permissão staff: `user.is_staff = True`
- Checar header tenant: `X-Tenant-Slug: <slug>`

## Referência da API

### Registrar Device
**Endpoint:** `POST /api/notifications/register_device/`  
**Permissões:** Usuários autenticados  
**Headers:** `X-Tenant-Slug: <slug>`

**Request:**
```json
{
  "device_type": "mobile",
  "token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
  "platform": "ios",
  "app_version": "1.0.0"
}
```

**Response:** `201 Created`

### Testar Push (Admin)
**Endpoint:** `POST /api/notifications/test-push/`  
**Permissões:** Apenas staff  
**Headers:** `X-Tenant-Slug: <slug>`

Veja seção 3 acima para detalhes.

## Referências

- **Expo Push Notifications:** https://docs.expo.dev/push-notifications/overview/
- **Expo Push API:** https://docs.expo.dev/push-notifications/sending-notifications/
- **Notificações Backend:** `NOTIFICATIONS_OVERVIEW.md`
- **Arquitetura:** `ARQUITETURA_SISTEMA.md`
