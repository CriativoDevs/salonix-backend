# 🛡️ Django Admin Tutorial — Salonix (EN/PT)

## 🇬🇧 English

### Overview
This tutorial explains how to use Salonix’s customized Django Admin to manage tenants, users, staff, and system settings.

### Accessing Django Admin
- Start server: `python manage.py runserver 0.0.0.0:8000`.
- Admin URL: `http://0.0.0.0:8000/admin/`.
- Use the admin credentials provided by your team (default values in dev may be `admin` / `admin123`, only for local use).

### Create a New Tenant
1. In Admin, go to `Tenants` → `Add Tenant`.
2. Fill basic info: Name, Slug (auto), Description.
3. Choose a Plan and enable relevant Features (Reports, SMS, WhatsApp, PWA, Push).
4. Optional branding: upload Logo (PNG/JPG, ≤2MB, 300×300), set Primary/Secondary colors.
5. Save — the tenant becomes Active.

### Create/Invite Staff Members
1. Go to `Users` → `Tenant staff members` → `Add`.
2. Select Tenant and User (or create via green “+”).
3. Set Role: `manager` or `collaborator`. Set Status: `Invited` (generates token) or `Active` (for seeds).
4. Save and copy the Invite token (resend action available once email is integrated).
5. When the collaborator accepts the invite (`POST /api/users/staff/accept/`), Status switches to Active and a linked `Professional` is created automatically (see `Core → Professionals`).
6. To revoke, set Status to `Disabled` — linked professionals become inactive but history remains.

Tip: when migrating legacy data, ensure all `Professional` records are linked to a staff member (via admin or migration).

### Configure White‑label
- Edit the tenant → Branding.
- Upload logo (transparent PNG preferred) and set color scheme.
- Validate via `/api/tenant/meta/` to see logo URL, colors, plan tier, and features.

### Feature Flags
- Plans toggle feature availability (Basic/Standard/Pro/Enterprise).
- Manually enable/disable features in the tenant’s Feature Flags section and Save.

### Monitoring & Metrics (Admin Dashboard)
- Active users today, active tenants, today’s appointments, estimated revenue.
- Top tenants by users, monthly appointments, plan value, activity score.
- Recent activity: new tenants, new users, recent appointments, config changes.
- Alerts: inactive tenants, users without tenant, sync failures, configuration issues.

### Bulk Actions
- Tenants: Activate/Deactivate, Upgrade plan.
- Users: Activate/Deactivate, Send welcome email.

### Search & Filters
- Tenants: by name, owner email, slug. Filters: plan, status, created date, features.
- Users: by username, email, tenant name, phone.

### Troubleshooting
- Can’t log in: check user Active, tenant association, tenant Active.
- Features not working: check Feature Flags and Plan.

---

## 🇧🇷 Português

## 📋 **Visão Geral**

Este tutorial mostra como usar o Django Admin customizado do Salonix para gerenciar tenants, usuários e configurações do sistema.

## 🚀 **Acessando o Django Admin**

### **1. Iniciar o Servidor**
```bash
cd salonix-backend
python manage.py runserver 0.0.0.0:8000
```

### **2. Acessar o Admin**
- **URL**: http://0.0.0.0:8000/admin/
- **Usuário padrão**: admin
- **Senha padrão**: admin123

### **3. Dashboard Principal**
O admin customizado exibe:
- 📊 **Estatísticas gerais** (usuários, tenants, agendamentos)
- 🏆 **Top tenants** por atividade
- 📅 **Atividade recente**
- ⚠️ **Alertas do sistema**

## 🏢 **Gestão de Tenants**

### **📝 Criando um Novo Tenant**

#### **Passo 1: Navegar para Tenants**
1. No admin, clique em **"Tenants"**
2. Clique em **"Add Tenant"**

#### **Passo 2: Preencher Informações Básicas**
```
Nome: Salão Beleza & Estilo
Slug: salao-beleza-estilo (gerado automaticamente)
Descrição: Salão de beleza especializado em cortes e tratamentos
```

#### **Passo 3: Configurar Plano e Features**
```
Plano: Pro (€99/mês)
Features Habilitadas:
☑️ Relatórios habilitados
☑️ PWA Admin habilitado  
☑️ PWA Cliente habilitado
☑️ SMS habilitado
☑️ WhatsApp habilitado
☑️ Push Web habilitado
☑️ Push Mobile habilitado
```

#### **Passo 4: White-label (Opcional)**
```
Logo: [Upload de imagem - máx 2MB, 300x300px]
Cor Primária: #ff6b6b
Cor Secundária: #4ecdc4
```

#### **Passo 5: Salvar**
- Clique em **"Save"**
- O tenant será criado com ID único
- Status automaticamente definido como "Ativo"

### **📊 Visualizando Tenant Criado**

#### **Na Lista de Tenants**
Você verá:
- ✅ **Nome**: Salão Beleza & Estilo
- 📊 **Usuários**: 0 usuários
- 🎯 **Plano**: Pro
- 📅 **Criado**: 04/09/2025
- ⭐ **Features**: Relatórios, SMS, WhatsApp, PWA

#### **Detalhes do Tenant**
Clicando no tenant, você vê:
- 📈 **Resumo de features** ativas
- 👥 **Contagem de usuários**
- 🎨 **Preview do branding** (se configurado)
- ⚙️ **Configurações avançadas**

## 👥 **Criando Usuário para o Tenant**

### **Passo 1: Criar Usuário**
1. Vá para **"Users"** → **"Add User"**
2. Preencha:
```
Username: admin_salao_beleza
Email: admin@salaobeleza.com
Password: senha_segura_123
Confirm Password: senha_segura_123
```

### **Passo 2: Associar ao Tenant**
```
Tenant: Salão Beleza & Estilo
Nome Completo: João Silva
Telefone: +351912345678
É Staff: ☑️ (para acesso admin)
É Ativo: ☑️
```

### **Passo 3: Configurar Permissões**
```
Grupos: Tenant Managers
Permissões Específicas:
☑️ Can view appointments
☑️ Can add appointments  
☑️ Can change appointments
☑️ Can delete appointments
☑️ Can view reports
```

### **Passo 4: Salvar**
- O usuário agora pode fazer login
- Terá acesso apenas aos dados do seu tenant
- Pode gerenciar agendamentos e relatórios

## 👥 **Gestão de Staff (Convites e Profissionais)**

### 🇧🇷 **Fluxo via Admin**
1. Acesse **Users → Tenant staff members**.
2. Clique em **"Add tenant staff member"**.
3. Preencha:
   ```
   Tenant: Salão Beleza & Estilo
   User: (escolha um CustomUser existente ou crie pelo botão verde “+”)
   Role: manager | collaborator
   Status: Invited (gera token) ou Active (para fixtures/seeds)
   ```
4. Após salvar, copie o campo **Invite token** (ou use o botão de reenviar convite quando integrado ao serviço de email).
5. Quando o colaborador aceitar o convite (endpoint `/api/users/staff/accept/`), o status muda para **Active** e um `Professional` é criado/vinculado automaticamente ao staff (visível na aba **Core → Professionals**). Profissionais criados manualmente no admin também devem ser associados a um staff ativo.
6. Para revogar acesso, defina **Status = Disabled** — o profissional ligado fica inativo mas permanece no histórico.

### 🇬🇧 **Admin Flow (English)**
1. Go to **Users → Tenant staff members**.
2. Click **“Add tenant staff member”**.
3. Fill out:
   ```
   Tenant: choose the salon
   User: pick an existing CustomUser or create a new one via the green “+” button
   Role: manager | collaborator
   Status: Invited (issues a token) or Active (for seeds/internal bootstrap)
   ```
4. After saving, copy the **Invite token** (or use the “resend invite” action once email integration is configured).
5. When the collaborator follows the invite (POST `/api/users/staff/accept/`), the status flips to **Active** and a matching `Professional` record is created/linked automatically (check **Core → Professionals**). When creating professionals manually, always select an active staff member.
6. To revoke access, set **Status = Disabled** — linked professionals become inactive while keeping appointment history intact.

> 💡 **Dica/Tip**: caso esteja migrando dados antigos, execute a migração `core/0019_attach_professionals_to_staff` (ou associe via admin) para garantir que todos os profissionais tenham `staff_member` definido.

## 🎨 **Configurando White-label**

### **Upload de Logo**
1. Edite o tenant
2. Na seção **"Branding"**:
   - **Logo**: Selecione arquivo (PNG/JPG, máx 2MB)
   - **Dimensões recomendadas**: 300x300px
   - **Formato**: Transparente (PNG) preferível

### **Branding (sem cores)**
Os campos de cor foram removidos. Branding agora utiliza:
- `logo_url` (ou upload de `logo`)
- `favicon_url`
- `app_name`

### **Testando o Branding**
1. Acesse `/api/users/tenant/meta/` logado como usuário do tenant
2. Verifique se retorna:
```json
{
  "name": "Salão Beleza & Estilo",
  "logo_url": "https://domain.com/media/tenant_logos/logo_abc123.png",
  "favicon_url": "https://domain.com/media/tenant_favicons/fav_abc123.png",
  "app_name": "Salão App",
  "plan_tier": "pro",
  "feature_flags": {
    "reports_enabled": true,
    "sms_enabled": true,
    "whatsapp_enabled": true
  }
}
```

## 📊 **Gestão de Feature Flags**

### **Configuração por Plano**
```
Basic (€29/mês):
☐ Relatórios
☐ SMS  
☐ WhatsApp
☑️ PWA Cliente básico

Standard (€59/mês):
☑️ Relatórios básicos
☐ SMS
☐ WhatsApp  
☑️ PWA Cliente + Admin

Pro (€99/mês):
☑️ Relatórios avançados
☑️ SMS (500/mês)
☑️ WhatsApp ilimitado
☑️ PWA completo
☑️ Push notifications

Enterprise (€199/mês):
☑️ Todas as features
☑️ SMS ilimitado
☑️ Suporte prioritário
☑️ White-label completo
```

### **Ativação Manual de Features**
1. Edite o tenant
2. Na seção **"Feature Flags"**
3. Marque/desmarque conforme necessário
4. **Salvar** - as mudanças são imediatas

## 📈 **Monitoramento e Métricas**

### **Dashboard do Admin**
O dashboard mostra:
- 📊 **Usuários ativos**: Total de usuários logados hoje
- 🏢 **Tenants ativos**: Tenants com atividade recente
- 📅 **Agendamentos hoje**: Total de agendamentos do dia
- 💰 **Receita estimada**: Baseada nos planos dos tenants

### **Top Tenants**
Lista os tenants mais ativos por:
- 👥 **Número de usuários**
- 📅 **Agendamentos no mês**
- 💰 **Valor do plano**
- ⭐ **Score de atividade**

### **Atividade Recente**
Mostra últimas ações:
- ➕ Novos tenants criados
- 👤 Novos usuários registrados
- 📅 Agendamentos recentes
- ⚙️ Mudanças de configuração

### **Alertas do Sistema**
Monitora:
- ⚠️ **Tenants inativos** há mais de 30 dias
- 🚨 **Usuários sem tenant** (erro de configuração)
- 📊 **Falhas de sincronização**
- 🔧 **Problemas de configuração**

## 🔧 **Ações em Massa**

### **Para Tenants**
Selecione múltiplos tenants e execute:
- ✅ **Ativar tenants** selecionados
- ❌ **Desativar tenants** selecionados
- ⬆️ **Upgrade para Pro** (ação especial)

### **Para Usuários**
Selecione múltiplos usuários e execute:
- ✅ **Ativar usuários**
- ❌ **Desativar usuários**
- 📧 **Enviar email de boas-vindas**

## 🔍 **Busca e Filtros**

### **Busca de Tenants**
Busque por:
- 🏢 **Nome do tenant**
- 📧 **Email do proprietário**
- 🏷️ **Slug do tenant**

### **Filtros Disponíveis**
- 📊 **Por plano**: Basic, Standard, Pro, Enterprise
- ⭐ **Por status**: Ativo, Inativo, Suspenso
- 📅 **Por data de criação**: Hoje, Esta semana, Este mês
- 🎯 **Por features**: Com relatórios, Com SMS, etc.

### **Busca de Usuários**
Busque por:
- 👤 **Username**
- 📧 **Email**
- 🏢 **Nome do tenant**
- 📱 **Telefone**

## ⚠️ **Troubleshooting Comum**

### **Problema: Usuário não consegue fazer login**
**Solução**:
1. Verifique se o usuário está **ativo**
2. Confirme se tem **tenant associado**
3. Verifique se o tenant está **ativo**

### **Problema: Features não funcionam**
**Solução**:
1. Confirme as **feature flags** do tenant
2. Verifique o **plano** do tenant
3. Teste o endpoint `/api/tenant/meta/`

### **Problema: Logo não aparece**
**Solução**:
1. Verifique se o arquivo foi **uploaded**
2. Confirme as **permissões** do diretório media
3. Teste o **link direto** da imagem

### **Problema: Cores não aplicam**
**Solução**:
1. Verifique o **formato hex** das cores (#ff6b6b)
2. Confirme se o frontend está **consumindo** `/api/tenant/meta/`
3. Limpe o **cache** do browser

## 📚 **Comandos Úteis**

### **Criar Superusuário**
```bash
python manage.py createsuperuser
```

> **Importante:** Superusuários são contas Ops/desenvolvimento sem tenant associado. Owners criados via plataforma não devem ter `is_superuser` habilitado para manter o isolamento multi-tenant.

### **Setup Inicial do Admin**
```bash
python manage.py setup_admin
```

### **Limpar Cache**
```bash
python manage.py shell
>>> from django.core.cache import cache
>>> cache.clear()
```

### **Verificar Configurações**
```bash
python manage.py check
python manage.py check --settings=salonix_backend.settings
```

## 🎯 **Boas Práticas**

### **✅ Segurança**
- Use **senhas fortes** para administradores
- Ative **2FA** quando disponível
- **Revise permissões** regularmente
- **Monitore atividade** suspeita

### **✅ Gestão de Tenants**
- **Padronize nomes** de tenant (sem caracteres especiais)
- **Configure features** de acordo com o plano
- **Monitore uso** de recursos
- **Documente mudanças** importantes

### **✅ Monitoramento**
- **Verifique dashboard** diariamente
- **Acompanhe alertas** do sistema
- **Analise métricas** semanalmente
- **Mantenha backups** atualizados

## 📞 **Suporte**

### **Logs do Sistema**
```bash
# Ver logs em tempo real
tail -f logs/django.log

# Buscar erros específicos
grep ERROR logs/django.log
```

### **Informações de Debug**
- **Versão Django**: 4.2+
- **Admin customizado**: SalonixAdminSite
- **Autenticação**: JWT + Session
- **Permissões**: Baseadas em tenant

---

*Tutorial criado: 4 Setembro 2025*  
*Última atualização: 4 Setembro 2025*  
*Versão: 1.0*
