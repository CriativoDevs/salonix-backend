# 🏗️ Arquitetura do Sistema - Salonix Backend

## 📋 **Visão Geral**

Este documento descreve a arquitetura técnica do backend Salonix, incluindo padrões, tecnologias e decisões de design.

## 🎯 **Princípios Arquiteturais**

### **🏢 Multi-tenancy First**
- **Isolamento obrigatório** de dados por tenant
- **Tenant ID** presente em todos os modelos principais
- **Middleware automático** de detecção de tenant
- **Queries sempre filtradas** por tenant

### **⚡ Performance & Scalability**
- **Cache Redis** para dados frequentes
- **Queries otimizadas** com select_related/prefetch_related
- **Paginação** em todos os endpoints de lista
- **Índices de banco** em campos críticos

### **🛡️ Security by Design**
- **Autenticação JWT** obrigatória
- **Validação rigorosa** de entrada
- **Sanitização** de dados sensíveis em logs
- **Permissões granulares** por tenant

### **📊 Observability**
- **Logs estruturados** com contexto
- **Métricas Prometheus** para monitoramento
- **Request ID** para correlação
- **Error tracking** centralizado

## 🏗️ **Stack Tecnológico**

### **🐍 Backend Core**
```
Django 4.2+          - Framework web
Django REST Framework - API REST
PostgreSQL           - Banco principal
Redis                - Cache e sessões
```

### **🔧 Bibliotecas Principais**
```
django-redis==5.4.0     - Cache Redis
djangorestframework-jwt - Autenticação JWT
Pillow==10.4.0         - Processamento de imagens
drf-spectacular        - Documentação OpenAPI
```

### **📊 Monitoramento**
```
Prometheus metrics     - Métricas de sistema
Structured logging     - Logs JSON
Request correlation    - X-Request-ID
```

## 📐 **Arquitetura de Camadas**

```
┌─────────────────────────────────────────┐
│                Frontend                 │
│        (Web + Mobile Apps)              │
└─────────────────┬───────────────────────┘
                  │ HTTP/HTTPS
┌─────────────────┴───────────────────────┐
│              API Gateway                │
│         (Django + DRF)                  │
├─────────────────────────────────────────┤
│           Business Logic                │
│     (Views + Serializers)               │
├─────────────────────────────────────────┤
│            Data Layer                   │
│    (Models + Managers + Signals)        │
├─────────────────────────────────────────┤
│              Cache Layer                │
│           (Redis Cache)                 │
├─────────────────────────────────────────┤
│            Database Layer               │
│          (PostgreSQL)                   │
└─────────────────────────────────────────┘
```

## 🗂️ **Estrutura de Diretórios**

```
salonix-backend/
├── salonix_backend/          # Configurações principais
│   ├── settings.py           # Configurações Django
│   ├── urls.py              # URLs principais
│   ├── admin.py             # Admin customizado
│   ├── middleware.py        # Middlewares customizados
│   ├── error_handling.py    # Sistema de erros
│   ├── logging_utils.py     # Utilitários de log
│   └── validators.py        # Validadores globais
├── users/                   # Gestão de usuários e tenants
│   ├── models.py           # User, Tenant, UserFeatureFlags
│   ├── views.py            # APIs de autenticação
│   ├── serializers.py      # Serializers de user/tenant
│   └── admin.py            # Admin de usuários
├── core/                    # Funcionalidades principais
│   ├── models.py           # Service, Professional, Appointment
│   ├── views.py            # APIs de agendamento
│   ├── serializers.py      # Serializers do core
│   └── admin.py            # Admin do core
├── reports/                 # Sistema de relatórios
│   ├── views.py            # APIs de relatórios
│   ├── serializers.py      # Serializers de relatórios
│   └── utils.py            # Utilitários de cálculo
├── notifications/           # Sistema de notificações
│   ├── models.py           # NotificationDevice, Log
│   ├── services.py         # Drivers de notificação
│   └── views.py            # APIs de notificação
├── payments/               # Integração com Stripe
├── tests/                  # Testes automatizados
└── docs/                   # Documentação
```

## 🗃️ **Modelo de Dados**

### **👥 Entidades Principais**

#### **Tenant (Multi-tenancy)**
```python
class Tenant(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    plan_tier = models.CharField(choices=PLAN_CHOICES)
    logo = models.ImageField(upload_to='tenant_logos/')
    primary_color = models.CharField(max_length=7)  # Hex
    secondary_color = models.CharField(max_length=7)
    # Feature flags
    reports_enabled = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)
    whatsapp_enabled = models.BooleanField(default=False)
```

#### **CustomUser**
```python
class CustomUser(AbstractUser):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=20)
    # Campos padrão do Django User
```

#### **Service (Serviços do Salão)**
```python
class Service(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration = models.DurationField()  # Ex: 01:30:00
```

#### **Professional**
```python
class Professional(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    bio = models.TextField()
    services = models.ManyToManyField(Service)
```

#### **ScheduleSlot (Horários Disponíveis)**
```python
class ScheduleSlot(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_available = models.BooleanField(default=True)
```

#### **Appointment (Agendamentos)**
```python
class Appointment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    slot = models.OneToOneField(ScheduleSlot, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    client_name = models.CharField(max_length=100)
    client_email = models.EmailField()
    client_phone = models.CharField(max_length=20)
    status = models.CharField(choices=STATUS_CHOICES)
    notes = models.TextField(blank=True)
```

### **🔗 Relacionamentos**

```
Tenant (1) ←→ (N) CustomUser
Tenant (1) ←→ (N) Service
Tenant (1) ←→ (N) Professional
Tenant (1) ←→ (N) ScheduleSlot
Tenant (1) ←→ (N) Appointment

Professional (N) ←→ (N) Service
Professional (1) ←→ (N) ScheduleSlot
ScheduleSlot (1) ←→ (1) Appointment
Service (1) ←→ (N) Appointment
```

## 🔌 **APIs e Endpoints**

### **🔐 Autenticação**
```
POST /api/users/token/          # Login (JWT)
POST /api/users/token/refresh/  # Refresh token
POST /api/users/register/       # Cadastro self-service (retorna owner + tenant)
POST /api/users/logout/         # Logout
```

> Tanto o registro quanto o login retornam um bloco `tenant` com `id`, `slug`, plano, feature flags e branding. Esse payload é usado pelo frontend/mobile para aplicar o tema assim que o owner entra no sistema.

### **🏢 Tenant Management**
```
GET  /api/users/me/tenant/      # Bootstrap do tenant autenticado (slug, plano, branding)
GET  /api/tenant/meta/          # Dados do tenant (branding)
PATCH /api/tenant/meta/         # Atualizar branding
```

### **📅 Agendamentos**
```
GET    /api/appointments/       # Listar agendamentos
POST   /api/appointments/       # Criar agendamento
GET    /api/appointments/{id}/  # Detalhes do agendamento
PATCH  /api/appointments/{id}/  # Atualizar agendamento
DELETE /api/appointments/{id}/  # Cancelar agendamento
GET    /api/appointments/{id}/ics/ # Download .ics
```

### **📊 Relatórios**
```
GET /api/reports/overview/      # Visão geral
GET /api/reports/top-services/  # Serviços populares
GET /api/reports/revenue/       # Análise de receita
# Todos suportam ?format=csv
```

### **🔔 Notificações**
```
POST /api/notifications/register_device/  # Registrar device
POST /api/notifications/test/             # Testar canal
```

### **⚙️ Admin**
```
GET /admin/                     # Django Admin customizado
```

## 🔧 **Middlewares Customizados**

### **TenantMiddleware**
```python
class TenantMiddleware:
    """Detecta e injeta tenant no request"""
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Detecta tenant via user ou header
        # Injeta tenant no request.tenant
        return self.get_response(request)
```

### **RequestLoggingMiddleware**
```python
class RequestLoggingMiddleware:
    """Logs estruturados de requests/responses"""
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Gera X-Request-ID
        # Log de início de request
        response = self.get_response(request)
        # Log de fim de request
        return response
```

### **SecurityHeadersMiddleware**
```python
class SecurityHeadersMiddleware:
    """Adiciona headers de segurança"""
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        # Adiciona headers de segurança
        return response
```

## 🗄️ **Sistema de Cache**

### **Configuração Redis**
```python
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://localhost:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True,
            },
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
        }
    }
}
```

### **Estratégia de Cache**
- **Chaves**: Incluem tenant_id para isolamento
- **TTL**: Configurável por tipo de dado
- **Invalidação**: Automática via signals
- **Fallback**: LocMemCache se Redis indisponível

### **Exemplos de Chaves**
```
reports:overview:tenant_123:today
reports:top_services:tenant_123:week
tenant_meta:tenant_123
```

## 📊 **Sistema de Logging**

### **Formatters**
```python
# Produção - JSON estruturado
{
    "timestamp": "2025-09-04T10:30:00Z",
    "level": "INFO",
    "message": "Request completed",
    "request_id": "req_abc123",
    "user_id": 456,
    "tenant_id": 123,
    "duration_ms": 250
}

# Desenvolvimento - Colorido
[10:30:00] INFO req_abc123 | user:456 | tenant:123 | Request completed (250ms)
```

### **Contexto Automático**
- **request_id**: UUID único por request
- **user_id**: ID do usuário autenticado
- **tenant_id**: ID do tenant atual
- **duration**: Tempo de processamento

## 🛡️ **Sistema de Segurança**

### **Autenticação**
- **JWT Tokens** com refresh automático
- **Expiração** configurável (15min access, 7d refresh)
- **Blacklist** de tokens inválidos

### **Autorização**
- **Isolamento por tenant** obrigatório
- **Permissões granulares** via Django
- **Feature flags** por plano

### **Validação**
- **Sanitização** de entrada
- **Validadores customizados** por tipo de dado
- **Rate limiting** por endpoint

### **Headers de Segurança**
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000
```

## 📈 **Monitoramento e Observabilidade**

### **Métricas Prometheus**
```python
# Exemplos de métricas coletadas
http_requests_total{method="GET", endpoint="/api/appointments/"}
http_request_duration_seconds{method="GET", endpoint="/api/appointments/"}
cache_hits_total{cache_key="reports:overview"}
notifications_sent_total{channel="sms", status="success"}
```

### **Logs Estruturados**
- **Correlação** via X-Request-ID
- **Contexto rico** (user, tenant, duration)
- **Sanitização** de dados sensíveis
- **Rotação** automática de arquivos

### **Health Checks**
```python
GET /health/          # Status geral
GET /health/db/       # Status do banco
GET /health/cache/    # Status do cache
GET /health/external/ # Integrações externas
```

## 🧪 **Estratégia de Testes**

### **Estrutura de Testes**
```
tests/
├── test_models.py           # Testes de modelos
├── test_views.py            # Testes de APIs
├── test_serializers.py      # Testes de serialização
├── test_cache.py            # Testes de cache
├── test_admin.py            # Testes do admin
├── test_middleware.py       # Testes de middlewares
└── fixtures/                # Dados de teste
```

### **Tipos de Teste**
- **Unitários**: Modelos, serializers, utils
- **Integração**: APIs, cache, banco
- **Funcionais**: Fluxos completos
- **Performance**: Cache, queries, endpoints

### **Mocks e Fixtures**
- **Integrações externas** mockadas
- **Dados de teste** isolados por tenant
- **Setup/teardown** automático

## 🚀 **Deploy e Infraestrutura**

### **Ambientes**
```
Development  → SQLite + LocMem cache
Staging      → PostgreSQL + Redis
Production   → PostgreSQL + Redis + Load Balancer
```

### **Configuração por Ambiente**
```python
# .env files
.env.development
.env.staging  
.env.production
```

### **Checklist de Deploy**
- [ ] Migrações de banco aplicadas
- [ ] Arquivos estáticos coletados
- [ ] Cache Redis funcionando
- [ ] Logs estruturados configurados
- [ ] Monitoramento ativo
- [ ] Backup configurado

## 📚 **Padrões e Convenções**

### **Nomenclatura**
- **Modelos**: PascalCase (Tenant, CustomUser)
- **Campos**: snake_case (tenant_id, created_at)
- **URLs**: kebab-case (/api/tenant-meta/)
- **Variáveis**: snake_case (user_id, request_data)

### **Estrutura de Código**
- **Fat models, thin views**: Lógica nos modelos
- **Serializers robustos**: Validação e transformação
- **Utils separados**: Funções reutilizáveis
- **Signals para eventos**: Invalidação de cache, logs

### **Documentação**
- **Docstrings** em todas as funções
- **Comentários** para lógica complexa
- **README** atualizado
- **OpenAPI** para APIs

## 🎯 **Próximas Evoluções**

### **Performance**
- [ ] Query optimization com índices
- [ ] Cache warming strategies
- [ ] Database sharding (futuro)
- [ ] CDN para assets

### **Funcionalidades**
- [ ] Agendamentos múltiplos (BE-153)
- [ ] Métricas de clientes (BE-154)
- [ ] Sistema de auditoria
- [ ] Integração com calendários externos

### **Infraestrutura**
- [ ] Kubernetes deployment
- [ ] Auto-scaling configurado
- [ ] Monitoring avançado
- [ ] Disaster recovery

---

*Documento criado: 4 Setembro 2025*  
*Última atualização: 4 Setembro 2025*  
*Versão: 1.0*
