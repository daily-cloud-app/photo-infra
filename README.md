# Daily Cloud Photo — AWS Backend デプロイ手順

AWS コンソールのみで完結する手順です。CLI は不要です。

## 手順

### 1. Lambda コードを S3 にアップロード

1. `infra/aws/lambda/index.py` を **ZIP ファイル**にする
   - Windows: `index.py` を右クリック → 送る → 圧縮（zip 形式）フォルダー
   - ZIP 内のファイル名が `index.py` であること（フォルダを挟まない）
2. AWS コンソール → **S3** → 任意のバケットを選択（なければ作成）
3. ZIP ファイルをアップロード
4. **バケット名**と**キー（パス）**をメモ
   - 例: バケット `my-deploy-bucket`、キー `daily-cloud-photo/lambda.zip`

### 2. CloudFormation でスタックを作成

1. AWS コンソール → **CloudFormation** → **スタックの作成**
2. 「テンプレートファイルのアップロード」を選択
3. `infra/aws/template.yaml` をアップロード
4. パラメータを入力:

| パラメータ | 説明 | 例 |
|-----------|------|-----|
| AppName | リソース名のプレフィックス | `daily-cloud-photo` |
| RequireEmail | サインアップ時にメール必須 | `true` |
| RequirePhone | サインアップ時に電話番号必須 | `false` |
| PhotosBucketName | 写真用 S3 バケット名（空欄で自動生成） | （空欄） |
| LambdaCodeBucket | 手順1でアップロードした S3 バケット名 | `my-deploy-bucket` |
| LambdaCodeKey | 手順1でアップロードした ZIP のキー | `daily-cloud-photo/lambda.zip` |

5. 「AWS CloudFormation によって IAM リソースが作成される場合があることを承認します」にチェック
6. **スタックの作成** をクリック

### 3. エンドポイント URL を確認

1. スタック作成完了後、**出力** タブを開く
2. `ApiEndpoint` の値がアプリに入力する URL

```
例: https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/v1
```

### 4. アプリで接続

1. アプリの Drawer → **設定** を開く
2. エンドポイント URL を入力 → **保存**
3. **接続テスト** で確認
4. Drawer → **ログイン** からアカウント作成・ログイン

## 削除

1. **S3 バケット**（写真用）を空にする
   - S3 → バケット → 「空にする」
2. **CloudFormation** → スタック → **削除**

## アーキテクチャ

```
ユーザー → API Gateway (HTTP API) → Lambda (統合ハンドラー)
                                        ├── Cognito (認証)
                                        ├── S3 (写真保存)
                                        └── DynamoDB (メタデータ)
```

- 全 API を1つの Lambda で処理（パスベースルーティング）
- ユーザーの写真は `users/{cognito_sub}/` プレフィックスで分離
- presigned URL で S3 に直接アップロード（Lambda を経由しない）

## コスト目安

すべて従量課金のサービスを使用しています。
少人数・少量利用であれば AWS 無料枠内に収まる可能性が高いです。

| サービス | 無料枠 |
|----------|--------|
| Lambda | 月100万リクエスト |
| API Gateway | 月100万リクエスト |
| DynamoDB | 25GB + 月25WCU/25RCU |
| S3 | 5GB（12ヶ月間） |
| Cognito | 月50,000 MAU |
