# Cloudflare Tunnel — публичный доступ к веб-интерфейсу

Ваш ПК находится за NAT, прямого доступа извне нет. Чтобы веб-интерфейс
и API были видны пилотным пользователям, используем **Cloudflare Tunnel** —
бесплатный HTTPS-туннель без проброса портов и белого IP.

## Вариант 1: Быстрый (без своего домена, временный URL)

`cloudflared` умеет поднимать туннель вообще без аккаунта, выдавая
рандомный URL вида `https://tendr-test.trycloudflare.com`. Этого хватит
для демо и тестов пилота.

```bash
# Установка
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install -y cloudflared

# Пробросить локальный :5173 (Vite dev) наружу
cloudflared tunnel --url http://localhost:5173
```

В консоли появится URL `https://<random>.trycloudflare.com` — это и есть
публичный адрес. **Нестабильно** (URL меняется при перезапуске), но для
пилота на 50 человек и 4 месяца — более чем достаточно.

## Вариант 2: Доменный (для продакшна)

Когда купите домен `tendr.kz` (или поддомен `app.tendr.kz`):

1. Зарегистрируйтесь на https://dash.cloudflare.com/
2. Добавьте домен (бесплатный план достаточно)
3. Создайте туннель:

```bash
cloudflared tunnel login
cloudflared tunnel create tendr
cloudflared tunnel route dns tendr app.tendr.kz
```

4. Скопируйте `~/.cloudflared/<tunnel-id>.json` в эту папку как `tunnel-credentials.json`
5. Заполните `config.yml` (см. ниже) и запустите:

```bash
cloudflared tunnel --config infra/cloudflared/config.yml run tendr
```

## Запуск под Docker (рекомендуется для VPS)

Когда переедете на VPS — добавьте в `docker-compose.yml`:

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
    restart: unless-stopped
    depends_on:
      - backend
```

`TUNNEL_TOKEN` берёте из дашборда Cloudflare (создаёте туннель через UI,
копируете токен).
