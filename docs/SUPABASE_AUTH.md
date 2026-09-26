# Supabase Auth для Tendr

## 1. Настройте проект Supabase

1. Создайте проект в Supabase.
2. В **Authentication → Providers → Email** включите вход по email/password.
3. В **Authentication → URL Configuration** укажите:
   - Site URL для разработки: `http://localhost:5173`
   - Redirect URL: `http://localhost:5173/auth/callback`
4. Для production добавьте точные HTTPS-адреса сайта и callback.

## 2. Настройте frontend

Скопируйте `web/.env.example` в `web/.env` и заполните:

```env
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=your_publishable_key
```

## 3. Настройте backend

Добавьте те же публичные настройки в `backend/.env`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your_publishable_key
```

После изменения `.env` перезапустите frontend и backend.

## Безопасность

- Используйте только **Publishable key** (или старый `anon` key).
- Никогда не добавляйте `service_role` или secret key в `web/.env`.
- Файлы `.env` не коммитятся в Git.
- Backend не доверяет данным браузера: bearer token проверяется через Supabase Auth.
- Перед production настройте собственный SMTP, точные redirect URL и защиту от перебора в Supabase.
