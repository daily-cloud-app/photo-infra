# Daily Cloud Photo — Backend API Specification

バックエンドが満たすべき REST API 仕様。
クラウドプロバイダーに依存しない統一インターフェース。

## Base URL

管理者がデプロイ後に発行するエンドポイント URL。
例: `https://api.example.com/v1`

## 認証

トークンベース認証。signin で取得した `accessToken` を以降のリクエストの
`Authorization: Bearer <accessToken>` ヘッダーに付与する。

---

## エンドポイント一覧

### 認証

#### POST /auth/signup

ユーザー登録。

**Request Body:**
```json
{
  "username": "string",
  "password": "string",
  "email": "string (optional)",
  "phone": "string (optional)"
}
```

必須フィールドは管理者がバックエンド側で設定可能（例: 電話番号必須）。

**Response 201:**
```json
{
  "message": "User created. Confirmation may be required.",
  "confirmationRequired": true
}
```

#### POST /auth/confirm

サインアップ後の確認コード検証。

**Request Body:**
```json
{
  "username": "string",
  "confirmationCode": "string"
}
```

**Response 200:**
```json
{
  "message": "User confirmed."
}
```

#### POST /auth/signin

ログイン。

**Request Body:**
```json
{
  "username": "string",
  "password": "string"
}
```

**Response 200:**
```json
{
  "accessToken": "string",
  "refreshToken": "string",
  "expiresIn": 3600
}
```

#### POST /auth/refresh

トークンの更新。

**Request Body:**
```json
{
  "refreshToken": "string"
}
```

**Response 200:**
```json
{
  "accessToken": "string",
  "expiresIn": 3600
}
```

---

### 写真

#### GET /photos

自分の写真一覧（メタデータ）を取得。

**Query Parameters:**
- `limit` (int, optional, default: 100)
- `cursor` (string, optional) — ページネーション用

**Response 200:**
```json
{
  "photos": [
    {
      "id": "string",
      "filename": "string",
      "contentType": "image/jpeg",
      "size": 1234567,
      "createdAt": "2025-01-01T00:00:00Z",
      "thumbnailUrl": "string (presigned URL)",
      "labels": ["family", "trip"]
    }
  ],
  "nextCursor": "string | null"
}
```

#### POST /photos/upload-url

アップロード用の presigned URL を取得。
アプリはこの URL に直接 PUT でファイルを送信する。

**Request Body:**
```json
{
  "filename": "IMG_20250101_120000.jpg",
  "contentType": "image/jpeg"
}
```

**Response 200:**
```json
{
  "photoId": "string",
  "uploadUrl": "string (presigned PUT URL)",
  "expiresIn": 3600
}
```

#### PUT {uploadUrl}

presigned URL に対して画像バイナリを直接 PUT。
（このリクエストはバックエンド API ではなくストレージに直接送信）

**Headers:**
- `Content-Type: image/jpeg`

**Body:** 画像バイナリ

#### POST /photos/{id}/confirm

アップロード完了をバックエンドに通知。
メタデータの確定やサムネイル生成のトリガーに使用。

**Response 200:**
```json
{
  "message": "Upload confirmed.",
  "thumbnailUrl": "string (presigned URL)"
}
```

#### DELETE /photos/{id}

写真を削除。

**Response 200:**
```json
{
  "message": "Photo deleted."
}
```

---

### サーバー情報

#### GET /info

サーバーの基本情報。接続テストにも使用。

**Response 200:**
```json
{
  "name": "Daily Cloud Photo Backend",
  "version": "1.0.0",
  "signupFields": ["username", "password", "email"],
  "features": ["upload", "labels"]
}
```

`signupFields` でアプリ側がサインアップフォームを動的に構築できる。

---

## エラーレスポンス

全エンドポイント共通。

```json
{
  "error": "string (error code)",
  "message": "string (human readable)"
}
```

**HTTP ステータスコード:**
- 400 — バリデーションエラー
- 401 — 認証エラー（トークン無効・期限切れ）
- 403 — 権限なし
- 404 — リソースが見つからない
- 409 — 競合（ユーザー名重複等）
- 429 — レート制限
- 500 — サーバーエラー
