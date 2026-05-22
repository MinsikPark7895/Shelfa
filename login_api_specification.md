# Shelfa 인증 API 명세서 (Auth API Specification)

본 명세서는 Shelfa 백엔드 시스템의 인증(가입/로그인) 관련 API 엔드포인트를 정의합니다. 
모든 응답은 JSON 형식을 따르며, 강력한 보안 기제(Rate Limiting, HttpOnly 쿠키, RTR)가 적용되어 있습니다.

---

## 1. 회원가입 (Sign Up)

새로운 사용자 계정을 생성합니다.

*   **URL**: `/auth/signup`
*   **Method**: `POST`
*   **Rate Limit**: `3회 / 1분` (동일 IP)

### 📌 Request (Body: `application/json`)
```json
{
  "name": "홍길동",
  "email": "user@shelfa.com",
  "password": "Password123!"
}
```
> [!WARNING]  
> **비밀번호 규칙**: 최소 8자 이상, 영문자, 숫자, 특수문자를 각각 1개 이상 포함해야 합니다. 규칙 위반 시 `422 Unprocessable Entity` 에러가 발생합니다.

### 🟢 Response (Success: `201 Created`)
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "name": "홍길동",
  "email": "user@shelfa.com",
  "role": "user",
  "created_at": "2026-05-21T10:00:00.000Z"
}
```

### 🔴 Response (Error: `400 Bad Request`)
*   이미 존재하는 이메일일 경우 발생합니다.
```json
{
  "detail": "이미 가입된 이메일입니다."
}
```

---

## 2. 로그인 (Login)

이메일과 비밀번호를 검증하고 Access Token(JSON)과 Refresh Token(Cookie)을 발급합니다.

*   **URL**: `/auth/login`
*   **Method**: `POST`
*   **Rate Limit**: `5회 / 1분` (동일 IP)

### 📌 Request (Body: `application/x-www-form-urlencoded`)
| Key | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `username` | string | O | 가입 시 사용한 이메일 주소 |
| `password` | string | O | 사용자 비밀번호 |

### 🟢 Response (Success: `200 OK`)
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```
> [!NOTE]  
> **[Cookie 발급]** 성공 시, 응답 헤더의 `Set-Cookie`를 통해 `refresh_token`이 브라우저에 저장됩니다. (속성: `HttpOnly=True`, `SameSite=Lax`, 만료: 14일)

### 🔴 Response (Error: `401 Unauthorized`)
*   아이디 또는 비밀번호 불일치 시 발생합니다.
```json
{
  "detail": "이메일 또는 비밀번호가 일치하지 않습니다."
}
```

---

## 3. 토큰 재발급 (Refresh Token)

만료된 Access Token을 새 토큰으로 갱신합니다. (RTR 방식 적용)

*   **URL**: `/auth/refresh`
*   **Method**: `POST`

### 📌 Request (Headers & Cookies)
*   **Cookie**: 브라우저에 저장된 `refresh_token`이 자동으로 포함되어야 합니다.

### 🟢 Response (Success: `200 OK`)
```json
{
  "access_token": "새로_발급된_ACCESS_TOKEN",
  "token_type": "bearer"
}
```
> [!NOTE]  
> **[RTR 보안]** 이 API를 호출하면 기존 쿠키의 `refresh_token`은 즉시 폐기(Redis 삭제)되며, 브라우저의 쿠키에는 **완전히 새로운 `refresh_token`이 덮어씌워집니다.**

### 🔴 Response (Error: `401 Unauthorized`)
*   쿠키가 없거나, 만료되었거나, 탈취(이미 사용)된 경우 강제 로그아웃 처리됩니다.
```json
{
  "detail": "폐기되거나 재발급된 Refresh Token입니다. 강제 로그아웃됩니다."
}
```

---

## 4. 로그아웃 (Logout)

Redis에 저장된 Refresh Token을 폐기하고, 클라이언트의 쿠키를 삭제합니다.

*   **URL**: `/auth/logout`
*   **Method**: `POST`

### 📌 Request (Headers & Cookies)
*   **Cookie**: `refresh_token`

### 🟢 Response (Success: `200 OK`)
```json
{
  "message": "로그아웃 되었습니다."
}
```
> [!NOTE]  
> 응답 헤더를 통해 브라우저의 `refresh_token` 쿠키를 삭제하라는 명령이 함께 전달됩니다.
