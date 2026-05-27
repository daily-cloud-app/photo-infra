"""
Daily Cloud Photo — 統合 Lambda ハンドラー
API Gateway HTTP API からのリクエストをパスベースでルーティング
"""
import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

# ── 環境変数 ──
USER_POOL_ID = os.environ.get('USER_POOL_ID', '')
USER_POOL_CLIENT_ID = os.environ.get('USER_POOL_CLIENT_ID', '')
PHOTOS_BUCKET = os.environ.get('PHOTOS_BUCKET', '')
PHOTOS_TABLE = os.environ.get('PHOTOS_TABLE', '')
REQUIRE_EMAIL = os.environ.get('REQUIRE_EMAIL', 'true') == 'true'
REQUIRE_PHONE = os.environ.get('REQUIRE_PHONE', 'false') == 'true'
AWS_REGION = os.environ.get('AWS_REGION', 'ap-northeast-1')

# ── AWS クライアント ──
from botocore.config import Config as BotoConfig

cognito = boto3.client('cognito-idp')
s3 = boto3.client(
    's3',
    region_name=AWS_REGION,
    endpoint_url=f'https://s3.{AWS_REGION}.amazonaws.com',
    config=BotoConfig(signature_version='s3v4'),
)
dynamodb = boto3.resource('dynamodb')


# ============================================================
# ヘルパー
# ============================================================

def _table():
    return dynamodb.Table(PHOTOS_TABLE)


def _body(event):
    b = event.get('body', '{}')
    return json.loads(b) if isinstance(b, str) and b else (b or {})


def _ok(status, body):
    return {
        'statusCode': status,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body, default=str),
    }


def _err(status, msg, code=None):
    b = {'message': msg}
    if code:
        b['error'] = code
    return _ok(status, b)


def _user_id(event):
    headers = event.get('headers', {})
    auth = headers.get('authorization', '') or headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    try:
        resp = cognito.get_user(AccessToken=auth[7:])
        for a in resp.get('UserAttributes', []):
            if a['Name'] == 'sub':
                return a['Value']
    except Exception:
        return None
    return None


def _prefix(uid):
    return f'users/{uid}/'


# ============================================================
# ルーティング
# ============================================================

def handler(event, context):
    rc = event.get('requestContext', {})
    http = rc.get('http', {})
    method = http.get('method', 'GET').upper()
    path = http.get('path', '/')

    # /v1 プレフィックスを除去
    if path.startswith('/v1'):
        path = path[3:]

    if method == 'GET' and path == '/info':
        return _info(event)
    if method == 'POST' and path == '/auth/signup':
        return _signup(event)
    if method == 'POST' and path == '/auth/confirm':
        return _confirm(event)
    if method == 'POST' and path == '/auth/signin':
        return _signin(event)
    if method == 'POST' and path == '/auth/refresh':
        return _refresh(event)
    if method == 'POST' and path == '/auth/forgot-password':
        return _forgot_password(event)
    if method == 'POST' and path == '/auth/reset-password':
        return _reset_password(event)
    if method == 'GET' and path == '/photos':
        return _photos_list(event)
    if method == 'POST' and path == '/photos/upload-url':
        return _upload_url(event)
    if method == 'POST' and path.startswith('/photos/') and path.endswith('/confirm'):
        return _photos_confirm(event, path)
    if method == 'PUT' and path.startswith('/photos/') and path.endswith('/labels'):
        return _photos_update_labels(event, path)
    if method == 'DELETE' and path.startswith('/photos/'):
        return _photos_delete(event, path)

    return _err(404, 'Not found')


# ============================================================
# GET /info
# ============================================================

def _info(event):
    fields = ['username', 'password']
    if REQUIRE_EMAIL:
        fields.append('email')
    if REQUIRE_PHONE:
        fields.append('phone')
    return _ok(200, {
        'name': 'Daily Cloud Photo Backend',
        'version': '1.0.0',
        'signupFields': fields,
        'features': ['upload', 'labels'],
    })


# ============================================================
# POST /auth/signup
# ============================================================

def _signup(event):
    b = _body(event)
    username = b.get('username', '').strip()
    password = b.get('password', '')
    email = b.get('email', '').strip()
    phone = b.get('phone', '').strip()

    if not username or not password:
        return _err(400, 'username and password are required')

    attrs = []
    if email:
        attrs.append({'Name': 'email', 'Value': email})
    if phone:
        attrs.append({'Name': 'phone_number', 'Value': phone})

    try:
        resp = cognito.sign_up(
            ClientId=USER_POOL_CLIENT_ID,
            Username=username,
            Password=password,
            UserAttributes=attrs,
        )
        return _ok(201, {
            'message': 'User created. Confirmation may be required.',
            'confirmationRequired': not resp.get('UserConfirmed', False),
        })
    except cognito.exceptions.UsernameExistsException:
        return _err(409, 'Username already exists', 'UsernameExists')
    except cognito.exceptions.InvalidPasswordException as e:
        return _err(400, str(e), 'InvalidPassword')
    except cognito.exceptions.InvalidParameterException as e:
        return _err(400, str(e), 'InvalidParameter')
    except Exception as e:
        return _err(500, str(e))


# ============================================================
# POST /auth/confirm
# ============================================================

def _confirm(event):
    b = _body(event)
    username = b.get('username', '').strip()
    code = b.get('confirmationCode', '').strip()

    if not username or not code:
        return _err(400, 'username and confirmationCode are required')

    try:
        cognito.confirm_sign_up(
            ClientId=USER_POOL_CLIENT_ID,
            Username=username,
            ConfirmationCode=code,
        )
        return _ok(200, {'message': 'User confirmed.'})
    except cognito.exceptions.CodeMismatchException:
        return _err(400, 'Invalid confirmation code', 'CodeMismatch')
    except cognito.exceptions.ExpiredCodeException:
        return _err(400, 'Confirmation code expired', 'ExpiredCode')
    except cognito.exceptions.UserNotFoundException:
        return _err(404, 'User not found', 'UserNotFound')
    except Exception as e:
        return _err(500, str(e))


# ============================================================
# POST /auth/signin
# ============================================================

def _signin(event):
    b = _body(event)
    username = b.get('username', '').strip()
    password = b.get('password', '')

    if not username or not password:
        return _err(400, 'username and password are required')

    try:
        resp = cognito.initiate_auth(
            ClientId=USER_POOL_CLIENT_ID,
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': password,
            },
        )
        r = resp['AuthenticationResult']
        return _ok(200, {
            'accessToken': r['AccessToken'],
            'refreshToken': r.get('RefreshToken', ''),
            'expiresIn': r.get('ExpiresIn', 3600),
        })
    except cognito.exceptions.NotAuthorizedException:
        return _err(401, 'Incorrect username or password', 'NotAuthorized')
    except cognito.exceptions.UserNotConfirmedException:
        return _err(403, 'User is not confirmed', 'UserNotConfirmed')
    except cognito.exceptions.UserNotFoundException:
        return _err(404, 'User not found', 'UserNotFound')
    except Exception as e:
        return _err(500, str(e))


# ============================================================
# POST /auth/refresh
# ============================================================

def _refresh(event):
    b = _body(event)
    rt = b.get('refreshToken', '')

    if not rt:
        return _err(400, 'refreshToken is required')

    try:
        resp = cognito.initiate_auth(
            ClientId=USER_POOL_CLIENT_ID,
            AuthFlow='REFRESH_TOKEN_AUTH',
            AuthParameters={'REFRESH_TOKEN': rt},
        )
        r = resp['AuthenticationResult']
        return _ok(200, {
            'accessToken': r['AccessToken'],
            'expiresIn': r.get('ExpiresIn', 3600),
        })
    except cognito.exceptions.NotAuthorizedException:
        return _err(401, 'Refresh token is invalid or expired', 'NotAuthorized')
    except Exception as e:
        return _err(500, str(e))


# ============================================================
# POST /auth/forgot-password
# ============================================================

def _forgot_password(event):
    b = _body(event)
    username = b.get('username', '').strip()

    if not username:
        return _err(400, 'username is required')

    try:
        cognito.forgot_password(
            ClientId=USER_POOL_CLIENT_ID,
            Username=username,
        )
        return _ok(200, {'message': 'Confirmation code sent.'})
    except cognito.exceptions.UserNotFoundException:
        # セキュリティ上、ユーザーが存在しなくても同じレスポンスを返す
        return _ok(200, {'message': 'Confirmation code sent.'})
    except cognito.exceptions.LimitExceededException:
        return _err(429, 'Too many requests. Please try again later.', 'LimitExceeded')
    except Exception as e:
        return _err(500, str(e))


# ============================================================
# POST /auth/reset-password
# ============================================================

def _reset_password(event):
    b = _body(event)
    username = b.get('username', '').strip()
    code = b.get('confirmationCode', '').strip()
    new_password = b.get('newPassword', '')

    if not username or not code or not new_password:
        return _err(400, 'username, confirmationCode, and newPassword are required')

    try:
        cognito.confirm_forgot_password(
            ClientId=USER_POOL_CLIENT_ID,
            Username=username,
            ConfirmationCode=code,
            Password=new_password,
        )
        return _ok(200, {'message': 'Password reset successful.'})
    except cognito.exceptions.CodeMismatchException:
        return _err(400, 'Invalid confirmation code', 'CodeMismatch')
    except cognito.exceptions.ExpiredCodeException:
        return _err(400, 'Confirmation code expired', 'ExpiredCode')
    except cognito.exceptions.InvalidPasswordException as e:
        return _err(400, str(e), 'InvalidPassword')
    except Exception as e:
        return _err(500, str(e))


# ============================================================
# GET /photos
# ============================================================

def _photos_list(event):
    uid = _user_id(event)
    if not uid:
        return _err(401, 'Authentication required')

    params = event.get('queryStringParameters') or {}
    limit = int(params.get('limit', '100'))
    cursor = params.get('cursor')

    t = _table()
    qp = {
        'KeyConditionExpression': Key('userId').eq(uid),
        'Limit': limit,
        'ScanIndexForward': False,
    }
    if cursor:
        qp['ExclusiveStartKey'] = {'userId': uid, 'photoId': cursor}

    result = t.query(**qp)
    items = result.get('Items', [])

    photos = []
    for item in items:
        # deleted は除外
        if item.get('status') == 'deleted':
            continue

        # サムネイルキーがあればサムネイルの URL を返す
        thumbnail_key = item.get('thumbnailKey')
        s3_key = item.get('s3Key', f"{_prefix(uid)}{item['photoId']}")

        try:
            if thumbnail_key:
                url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': PHOTOS_BUCKET, 'Key': thumbnail_key},
                    ExpiresIn=3600,
                )
            else:
                url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': PHOTOS_BUCKET, 'Key': s3_key},
                    ExpiresIn=3600,
                )
        except Exception:
            url = None

        photos.append({
            'id': item['photoId'],
            'filename': item.get('filename', ''),
            'contentType': item.get('contentType', 'image/jpeg'),
            'size': int(item.get('size', 0)),
            'createdAt': item.get('createdAt', ''),
            'thumbnailUrl': url,
            'labels': item.get('labels', []),
        })

    nc = None
    lk = result.get('LastEvaluatedKey')
    if lk:
        nc = lk.get('photoId')

    return _ok(200, {'photos': photos, 'nextCursor': nc})


# ============================================================
# POST /photos/upload-url
# ============================================================

def _upload_url(event):
    uid = _user_id(event)
    if not uid:
        return _err(401, 'Authentication required')

    b = _body(event)
    filename = b.get('filename', '')
    ct = b.get('contentType', 'image/jpeg')
    created_at = b.get('createdAt', datetime.now(timezone.utc).isoformat())
    # アプリから photoId が送られたらそれを使う（再アップロード時に上書き）
    photo_id = b.get('photoId', '') or str(uuid.uuid4())

    if not filename:
        return _err(400, 'filename is required')

    # S3 パスに日付を含める: users/{sub}/2026/04/26/{photoId}
    try:
        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
    except Exception:
        dt = datetime.now(timezone.utc)
    date_path = f"{dt.year}/{dt.month:02d}/{dt.day:02d}"
    s3_key = f"{_prefix(uid)}{date_path}/{photo_id}"

    url = s3.generate_presigned_url(
        'put_object',
        Params={'Bucket': PHOTOS_BUCKET, 'Key': s3_key, 'ContentType': ct},
        ExpiresIn=3600,
    )

    _table().put_item(Item={
        'userId': uid,
        'photoId': photo_id,
        'filename': filename,
        'contentType': ct,
        's3Key': s3_key,
        'status': 'uploading',
        'createdAt': created_at,
        'labels': [],
    })

    return _ok(200, {
        'photoId': photo_id,
        'uploadUrl': url,
        'expiresIn': 3600,
    })


# ============================================================
# POST /photos/{photoId}/confirm
# ============================================================

def _photos_confirm(event, path):
    uid = _user_id(event)
    if not uid:
        return _err(401, 'Authentication required')

    # /photos/{photoId}/confirm からIDを抽出
    parts = path.strip('/').split('/')
    photo_id = parts[1] if len(parts) >= 3 else ''
    if not photo_id:
        return _err(400, 'photoId is required')

    t = _table()
    result = t.get_item(Key={'userId': uid, 'photoId': photo_id})
    item = result.get('Item')
    if not item:
        return _err(404, 'Photo not found')

    s3_key = item.get('s3Key', '')
    try:
        obj = s3.head_object(Bucket=PHOTOS_BUCKET, Key=s3_key)
        size = obj.get('ContentLength', 0)
    except Exception:
        return _err(404, 'File not found in storage')

    t.update_item(
        Key={'userId': uid, 'photoId': photo_id},
        UpdateExpression='SET #s = :status, #sz = :size',
        ExpressionAttributeNames={'#s': 'status', '#sz': 'size'},
        ExpressionAttributeValues={':status': 'uploaded', ':size': size},
    )

    thumb = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': PHOTOS_BUCKET, 'Key': s3_key},
        ExpiresIn=3600,
    )

    return _ok(200, {'message': 'Upload confirmed.', 'thumbnailUrl': thumb})


# ============================================================
# DELETE /photos/{photoId}
# ============================================================

def _photos_delete(event, path):
    uid = _user_id(event)
    if not uid:
        return _err(401, 'Authentication required')

    parts = path.strip('/').split('/')
    photo_id = parts[1] if len(parts) >= 2 else ''
    if not photo_id:
        return _err(400, 'photoId is required')

    t = _table()
    result = t.get_item(Key={'userId': uid, 'photoId': photo_id})
    item = result.get('Item')
    if not item:
        return _err(404, 'Photo not found')

    # 論理削除: ステータスを deleted に変更（S3 のデータはバージョニングで保持）
    t.update_item(
        Key={'userId': uid, 'photoId': photo_id},
        UpdateExpression='SET #s = :status, deletedAt = :now',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={
            ':status': 'deleted',
            ':now': datetime.now(timezone.utc).isoformat(),
        },
    )

    return _ok(200, {'message': 'Photo deleted.'})


# ============================================================
# PUT /photos/{photoId}/labels
# ============================================================

def _photos_update_labels(event, path):
    uid = _user_id(event)
    if not uid:
        return _err(401, 'Authentication required')

    # /photos/{photoId}/labels からIDを抽出
    parts = path.strip('/').split('/')
    photo_id = parts[1] if len(parts) >= 3 else ''
    if not photo_id:
        return _err(400, 'photoId is required')

    b = _body(event)
    labels = b.get('labels', [])

    if not isinstance(labels, list):
        return _err(400, 'labels must be an array')

    t = _table()
    result = t.get_item(Key={'userId': uid, 'photoId': photo_id})
    item = result.get('Item')
    if not item:
        return _err(404, 'Photo not found')

    t.update_item(
        Key={'userId': uid, 'photoId': photo_id},
        UpdateExpression='SET labels = :labels',
        ExpressionAttributeValues={':labels': labels},
    )

    return _ok(200, {'message': 'Labels updated.', 'labels': labels})
