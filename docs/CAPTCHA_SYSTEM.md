# 🛡️ Captcha System (EN/PT)

## 🇬🇧 English

### Overview
The system uses a self-hosted captcha solution based on `django-simple-captcha` to prevent automated abuse on public endpoints (Login, Registration, Password Reset) without relying on external services like Cloudflare or Google.

### Architecture
- **Provider:** `django-simple-captcha` (generates images locally).
- **Storage:** Database table `captcha_captchastore` stores hash/response pairs.
- **Flow:**
    1. Client requests `GET /api/captcha/new/`.
    2. Server returns `{ "key": "...", "image_url": "..." }`.
    3. Client submits protected form with headers:
        - `X-Captcha-Key`: The key received.
        - `X-Captcha-Value`: The user's input (from the image).
    4. Server validates key/value pair in `users.security.enforce_captcha_or_raise`.

### Configuration
Managed via environment variables in `.env` or `settings.ini`:

| Variable | Default | Description |
|---|---|---|
| `CAPTCHA_ENABLED` | `false` | Enable/disable validation globally. |
| `CAPTCHA_BYPASS_TOKEN` | `""` | Secret token to bypass validation in automated tests. |

### API Usage

#### Generate Captcha
**Request:** `GET /api/captcha/new/`  
**Response:**
```json
{
    "key": "b483...",
    "image_url": "http://localhost:8000/captcha/image/b483..."
}
```

#### Validate (Implicit)
Send headers in protected requests (e.g., `POST /api/users/token/`):
```
X-Captcha-Key: <key_from_step_1>
X-Captcha-Value: <user_input>
```

### Testing & Bypass
For automated tests (E2E/Integration), use the bypass token:
1. Set `CAPTCHA_BYPASS_TOKEN=my-secret` in env.
2. Send header `X-Captcha-Value: my-secret` (Key can be anything).

---

## 🇧🇷 Português

### Visão Geral
O sistema utiliza uma solução de captcha própria (self-hosted) baseada no `django-simple-captcha` para prevenir abusos automatizados em endpoints públicos (Login, Registro, Recuperação de Senha), sem depender de serviços externos como Cloudflare ou Google.

### Arquitetura
- **Provedor:** `django-simple-captcha` (gera imagens localmente).
- **Armazenamento:** Tabela `captcha_captchastore` no banco de dados.
- **Fluxo:**
    1. Cliente requisita `GET /api/captcha/new/`.
    2. Servidor retorna `{ "key": "...", "image_url": "..." }`.
    3. Cliente envia formulário protegido com headers:
        - `X-Captcha-Key`: A chave recebida.
        - `X-Captcha-Value`: O texto digitado pelo usuário.
    4. Servidor valida o par em `users.security.enforce_captcha_or_raise`.

### Configuração
Gerenciado via variáveis de ambiente no `.env` ou `settings.ini`:

| Variável | Padrão | Descrição |
|---|---|---|
| `CAPTCHA_ENABLED` | `false` | Habilita/desabilita validação globalmente. |
| `CAPTCHA_BYPASS_TOKEN` | `""` | Token secreto para ignorar validação em testes. |

### Uso da API

#### Gerar Captcha
**Requisição:** `GET /api/captcha/new/`  
**Resposta:**
```json
{
    "key": "b483...",
    "image_url": "http://localhost:8000/captcha/image/b483..."
}
```

#### Validar (Implícito)
Envie headers nas requisições protegidas (ex: `POST /api/users/token/`):
```
X-Captcha-Key: <key_da_etapa_1>
X-Captcha-Value: <texto_digitado>
```

### Testes e Bypass
Para testes automatizados (E2E/Integração), use o token de bypass:
1. Defina `CAPTCHA_BYPASS_TOKEN=my-secret` no env.
2. Envie o header `X-Captcha-Value: my-secret` (Key pode ser qualquer coisa).
