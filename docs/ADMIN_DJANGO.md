# 🏢 Django Admin — Salonix (EN/PT)

## 🇬🇧 English

### Overview
Salonix ships a customised Django Admin for multi‑tenant operations: dashboards, top tenants, recent activity, alerts, tenant management with feature flags, bulk actions and granular permissions.

### Quick Start
- Configure: `python manage.py setup_admin --create-superuser`.
- Login: `/admin/` (change default credentials immediately in dev).
- Key sections: Tenants (`/admin/users/tenant/`), Users (`/admin/users/customuser/`).

### Security & Observability
- Tenant isolation enforced; only Ops accounts can be superusers.
- Structured logging, CSP/XSS headers, audit trails.

---

## Visão Geral

O Django Admin do Salonix foi completamente personalizado para fornecer uma interface administrativa poderosa e intuitiva para gerenciar o sistema multi-tenant.

## ✨ Funcionalidades Principais

### 🎯 Dashboard Personalizado
- **Estatísticas em Tempo Real**: Tenants ativos, usuários, agendamentos
- **Top Tenants**: Rankings por atividade semanal
- **Atividade Recente**: Log de ações importantes
- **Alertas do Sistema**: Notificações de problemas

### 👥 Gestão de Tenants
- **Visualização Completa**: Todos os campos do tenant
- **Feature Flags**: Configuração visual de funcionalidades
- **Ações em Lote**: Ativar/desativar múltiplos tenants
- **Upgrade Automático**: Promoção para planos superiores
- **Resumo de Features**: Visualização rápida das funcionalidades ativas

### 🔐 Sistema de Permissões
- **Grupos Predefinidos**:
  - `Salonix Admins`: Acesso total
  - `Tenant Managers`: Gestão limitada ao próprio tenant
  - `Support`: Apenas visualização
- **Isolamento por Tenant**: Staff só vê dados do próprio tenant
- **Superusuários Ops**: Apenas contas Ops (sem tenant associado) recebem `is_superuser`; owners/tenants comuns permanecem staff
- **Permissões Customizadas**: Controle granular de acesso

### 📊 Administração Multi-Model
- **Usuários**: Filtros por tenant, links cruzados
- **Agendamentos**: Visualização com contexto completo
- **Serviços**: Gestão por tenant
- **Profissionais**: Controle de atividade
- **Pagamentos**: Status de assinaturas
- **Notificações**: Logs e métricas

## 🚀 Como Usar

### 1. Configuração Inicial
```bash
# Configurar permissões e grupos
python manage.py setup_admin --create-superuser

# Acessar admin
http://localhost:8000/admin/
```

### 2. Credenciais Padrão
- **Usuário**: admin
- **Email**: admin@salonix.pt
- **Senha**: admin123 (altere imediatamente!)

### 3. URLs Importantes
- **Login**: `/admin/`
- **Dashboard**: `/admin/` (página inicial)
- **Tenants**: `/admin/users/tenant/`
- **Usuários**: `/admin/users/customuser/`

## 🎨 Interface Personalizada

### Dashboard
```
🏢 Dashboard Salonix

📊 Estatísticas:
[Tenants Ativos] [Total Usuários] [Agendamentos Hoje]
[Agendamentos Semana] [Assinaturas Ativas] [Notificações]

⚠️ Alertas do Sistema:
- Tenants sem assinatura
- Notificações falhadas

🏆 Top Tenants (Última Semana)
📈 Atividade Recente
🚀 Ações Rápidas
```

### Tenant Admin
- **Lista**: Nome, plano, status, features ativas
- **Filtros**: Por plano, status, features
- **Busca**: Nome, slug
- **Ações**: Ativar, desativar, upgrade
- **Detalhes**: Fieldsets organizados por categoria

## 🔧 Configuração Técnica

### Estrutura de Arquivos
```
salonix_backend/
├── admin.py              # Admin site personalizado
├── admin_permissions.py  # Sistema de permissões
├── middleware.py         # Logging e segurança
├── logging_utils.py      # Utilitários de log
├── templates/admin/      # Templates customizados
└── management/commands/
    └── setup_admin.py    # Comando de configuração
```

### Modelos Registrados
- ✅ `Tenant` - Gestão completa de salões
- ✅ `CustomUser` - Usuários com filtro por tenant
- ✅ `Service` - Serviços por tenant
- ✅ `Professional` - Profissionais
- ✅ `Appointment` - Agendamentos
- ✅ `Notification` - Sistema de notificações
- ✅ `PaymentCustomer` - Clientes de pagamento
- ✅ `Subscription` - Assinaturas

### Segurança
- **Middleware de Logging**: Todas as ações são logadas
- **Headers de Segurança**: CSP, XSS Protection, etc.
- **Isolamento de Dados**: Staff só vê próprio tenant
- **Auditoria**: Logs estruturados com contexto

## 📈 Métricas e Monitoramento

### Estatísticas Disponíveis
- Total de tenants ativos
- Usuários cadastrados
- Agendamentos (hoje/semana)
- Assinaturas ativas
- Notificações enviadas

### Alertas Automáticos
- Tenants sem assinatura ativa
- Notificações falhadas (24h)
- Erros de sistema

## 🎯 Próximos Passos

### Melhorias Planejadas
- [ ] Gráficos interativos no dashboard
- [ ] Exportação de relatórios
- [ ] Notificações push para admins
- [ ] API de métricas
- [ ] Integração com Slack/Discord

### Personalizações Possíveis
- Temas personalizados por tenant
- Widgets customizados
- Relatórios específicos
- Integrações externas

## 🆘 Suporte

### Problemas Comuns

**1. Erro de permissão**
```bash
# Reconfigurar permissões
python manage.py setup_admin
```

**2. Dashboard não carrega**
- Verificar se todos os modelos estão registrados
- Checar logs de erro no console

**3. Filtros não funcionam**
- Verificar se campos existem nos modelos

---

## 🇬🇧 Django Admin – English Summary

**Overview**
- Customised admin tailored for Salonix: dashboard with real-time stats, top tenants, recent activity and alerts.

**Key features**
- Tenant management with feature flags, bulk actions, upgrade shortcuts, detailed fieldsets.
- Permission system with predefined groups (`Salonix Admins`, `Tenant Managers`, `Support`) and tenant isolation.
- Cross-linked admin for users, appointments, services, professionals, payments, notifications.

**Getting started**
```bash
python manage.py setup_admin --create-superuser
```
- Default login: `admin` / `admin123` (change immediately).
- Key URLs: `/admin/`, `/admin/users/tenant/`, `/admin/users/customuser/`.

**Structure & security**
- Custom admin definitions (`salonix_backend/admin.py`, templates under `templates/admin/`).
- Logging middleware captures actions; CSP/XSS headers configured; data isolation enforced per tenant.

**Metrics & monitoring**
- Dashboard shows active tenants, users, appointments (today/week), subscriptions, notifications, and alerts (inactive subscriptions, failed notifications, system errors).

**Roadmap**
- Interactive charts, report export, admin push notifications, metrics API, Slack/Discord integrations, tenant-specific themes and widgets.
- Confirmar relacionamentos ForeignKey

### Logs Úteis
```bash
# Ver logs do admin
tail -f logs/app.log | grep "admin"

# Logs de permissão
tail -f logs/app.log | grep "permission"
```

---

## 🏆 Resultado

O Django Admin do Salonix oferece:
- ✅ **Interface Intuitiva**: Dashboard moderno e responsivo
- ✅ **Gestão Completa**: Todos os modelos em um lugar
- ✅ **Segurança Robusta**: Permissões e isolamento
- ✅ **Monitoramento**: Métricas em tempo real
- ✅ **Escalabilidade**: Suporta crescimento da plataforma

**🎉 Administração profissional para uma plataforma de salões moderna!**
