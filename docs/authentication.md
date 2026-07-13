# 认证模型

RamanAgent 现在使用 Access Token + Refresh Token Rotation。

- Access Token：默认 30 分钟，数据库只保存 `token_hash`。
- Refresh Token：默认 30 天，推荐通过 HttpOnly Cookie 保存。
- 每次 `/api/auth/refresh` 都会撤销旧 refresh token，并签发新的 access/refresh token。
- 旧 refresh token 再次使用会被识别为 replay，并撤销同一 `token_family_id` 下的会话。

## 接口

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `POST /api/auth/logout-all`
- `GET /api/auth/sessions`
- `DELETE /api/auth/sessions/{session_id}`
- `GET /api/auth/me`

生产环境必须设置 `AUTH_SECRET`，禁止默认管理员密码，禁止 `ALLOW_ANONYMOUS_DEV=true`。
