# 📚 Documentação do Salonix Backend

## 📋 **Índice da Documentação**

Esta pasta contém toda a documentação técnica e operacional do backend Salonix.

### **🎯 Documentos Estratégicos**
- [`ESTRATEGIA_DESENVOLVIMENTO.md`](./ESTRATEGIA_DESENVOLVIMENTO.md) - Estratégia de desenvolvimento em fases
- [`MVP_STATUS_ATUAL.md`](./MVP_STATUS_ATUAL.md) - Status atual do MVP
- [`BE_BUSINESS_BRIEF.md`](./BE_BUSINESS_BRIEF.md) - Alinhamento de negócio e implicações BE

### **🏗️ Documentos Técnicos**
- [`ARQUITETURA_SISTEMA.md`](./ARQUITETURA_SISTEMA.md) - Arquitetura técnica completa
- [`IMPLEMENTACOES_BACKEND.md`](./IMPLEMENTACOES_BACKEND.md) - Funcionalidades implementadas

### **📖 Tutoriais e Guias**
- [`TUTORIAL_DJANGO_ADMIN.md`](./TUTORIAL_DJANGO_ADMIN.md) - Guia completo do Django Admin
- [`OPS_RUNBOOK.md`](./OPS_RUNBOOK.md) - Runbook para operações e suporte (console Ops)

## 🎯 **Para Desenvolvedores Novos**

### **📚 Leitura Recomendada (Ordem)**
1. **MVP_STATUS_ATUAL.md** - Entenda onde estamos
2. **ARQUITETURA_SISTEMA.md** - Compreenda a arquitetura
3. **IMPLEMENTACOES_BACKEND.md** - Veja o que foi feito
4. **ESTRATEGIA_DESENVOLVIMENTO.md** - Entenda o roadmap

### **🛠️ Para Usar o Sistema**
1. **TUTORIAL_DJANGO_ADMIN.md** - Como gerenciar tenants e usuários

## 🔍 **Encontre Rapidamente**

### **🏢 Multi-tenancy**
- Implementação: [`IMPLEMENTACOES_BACKEND.md#multi-tenancy`](./IMPLEMENTACOES_BACKEND.md#1-infraestrutura-base)
- Arquitetura: [`ARQUITETURA_SISTEMA.md#multi-tenancy-first`](./ARQUITETURA_SISTEMA.md#multi-tenancy-first)

### **👥 Staff / Equipe**
- Visão técnica: [`IMPLEMENTACOES_BACKEND.md#gestão-de-staff-por-tenant-be-282`](./IMPLEMENTACOES_BACKEND.md#gestão-de-staff-por-tenant-be-282)
- Alinhamento de negócio (PT/EN): [`BE_BUSINESS_BRIEF.md`](./BE_BUSINESS_BRIEF.md#1-resumo-do-modelo-de-negócio)
- Operação/Admin: [`TUTORIAL_DJANGO_ADMIN.md#gestão-de-staff-convites-e-profissionais`](./TUTORIAL_DJANGO_ADMIN.md#gestão-de-staff-convites-e-profissionais)

### **🎨 White-label**
- Tutorial: [`TUTORIAL_DJANGO_ADMIN.md#white-label`](./TUTORIAL_DJANGO_ADMIN.md#configurando-white-label)
- Implementação: [`IMPLEMENTACOES_BACKEND.md#white-label`](./IMPLEMENTACOES_BACKEND.md#2-white-label-e-branding)

### **📊 Relatórios**
- Funcionalidades: [`IMPLEMENTACOES_BACKEND.md#relatórios`](./IMPLEMENTACOES_BACKEND.md#4-sistema-de-relatórios)
- Arquitetura: [`ARQUITETURA_SISTEMA.md#cache`](./ARQUITETURA_SISTEMA.md#sistema-de-cache)

### **🔔 Notificações**
- Sistema: [`IMPLEMENTACOES_BACKEND.md#notificações`](./IMPLEMENTACOES_BACKEND.md#5-sistema-de-notificações)
- Drivers: [`ARQUITETURA_SISTEMA.md#observability`](./ARQUITETURA_SISTEMA.md#monitoramento-e-observabilidade)

### **🧪 Testes**
- Cobertura: [`IMPLEMENTACOES_BACKEND.md#testes`](./IMPLEMENTACOES_BACKEND.md#sistema-de-testes)
- Estratégia: [`ARQUITETURA_SISTEMA.md#testes`](./ARQUITETURA_SISTEMA.md#estratégia-de-testes)

## 📊 **Status do Projeto (MVP)**

### **✅ Entregues (MVP)**
- Autenticação/registro self‑service com slug do tenant, bootstrap `/users/me/tenant/`.
- Relatórios com cache e throttling de exportação.
- Hardening: throttling por escopo, captcha switch (bypass dev), logs estruturados.
- Recuperação de senha (reset/confirm) com métricas e rate limit.

### **🚀 Próximos passos (go‑live)**
- BE‑212A: validação real de Captcha (Turnstile/hCaptcha) ou 212B self‑hosted.
- BE‑240B: e‑mails transacionais (template HTML, FROM amigável, URL do FE).
- Stripe live (chaves + webhook) e infra prod‑like (Postgres/Redis/HTTPS/CORS/Secrets/Observability).
- OpenAPI atualizado e smokes e2e.

## 🔗 **Links Úteis**

### **🌐 URLs do Sistema**
- **Admin**: http://0.0.0.0:8000/admin/
- **API**: http://0.0.0.0:8000/api/
- **Docs**: http://0.0.0.0:8000/api/schema/swagger-ui/

### **📂 Arquivos Importantes**
- **Configuração**: `salonix_backend/settings.py`
- **URLs**: `salonix_backend/urls.py`
- **Modelos**: `users/models.py`, `core/models.py`
- **Admin**: `salonix_backend/admin.py`

## 🛠️ **Comandos Rápidos**

### **🚀 Iniciar Desenvolvimento**
```bash
python manage.py runserver 0.0.0.0:8000
```

### **🧪 Executar Testes**
```bash
python -m pytest
```

### **🏛️ Setup Admin**
```bash
python manage.py setup_admin
```

### **📊 Verificar Status**
```bash
python manage.py check
```

## 📞 **Suporte**

### **🐛 Issues e Bugs**
- GitHub Issues: https://github.com/CriativoDevs/salonix-backend/issues

### **📧 Contato**
- Desenvolvedor: Pablo III (NemoIII)
- Email: criativodevs@gmail.com

## 📝 **Contribuição**

### **📋 Antes de Contribuir**
1. Leia [`ARQUITETURA_SISTEMA.md`](./ARQUITETURA_SISTEMA.md)
2. Execute todos os testes
3. Siga os padrões de código estabelecidos
4. Atualize a documentação relevante

### **🔄 Processo de PR**
1. Fork do repositório
2. Branch para feature/bugfix
3. Testes passando
4. Documentação atualizada
5. PR com descrição detalhada

---

*Documentação mantida pela equipe Salonix*  
*Última atualização: 11 Setembro 2025*

---

## 🇬🇧 Documentation Overview (English Summary)

- **Strategy & Status**: `ESTRATEGIA_DESENVOLVIMENTO.md`, `MVP_STATUS_ATUAL.md`, `BE_BUSINESS_BRIEF.md`.
- **Architecture & Implementation**: `ARQUITETURA_SISTEMA.md`, `IMPLEMENTACOES_BACKEND.md` (includes English highlights).
- **Operations & Admin**: `ADMIN_DJANGO.md`, `TUTORIAL_DJANGO_ADMIN.md`, `OPS_RUNBOOK.md` (each contains bilingual guidance).
- **Rules & Validation**: `BE_RULES.md`, `VALIDATION_SYSTEM.md`, `PYRIGHT_TYPING_CLEANUP.md`.
- **How to start**: run `python manage.py runserver 0.0.0.0:8000`, execute `python -m pytest`, manage admin with `python manage.py setup_admin`.
