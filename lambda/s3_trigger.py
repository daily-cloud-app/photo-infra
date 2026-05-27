"""
S3 イベントトリガー: ファイルが PUT されたら DynamoDB にメタデータを自動登録
（サムネイル生成はアプリ側で行う）
"""
import os
import urllib.parse
from datetime import datetime, timezone

import boto3

PHOTOS_TABLE = os.environ.get('PHOTOS_TABLE', '')

dynamodb = boto3.resource('dynamodb')


def handler(event, context):
    table = dynamodb.Table(PHOTOS_TABLE)

    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = urllib.parse.unquote_plus(record['s3']['object']['key'])
        size = record['s3']['object'].get('size', 0)

        # thumbnails/ プレフィックスのファイルは無視
        if key.startswith('thumbnails/'):
            continue

        # パスから userId を抽出
        parts = key.split('/')
        if len(parts) < 3 or parts[0] != 'users':
            continue

        user_id = parts[1]
        photo_id = parts[-1]

        # 拡張子からコンテンツタイプを推定
        ext = photo_id.rsplit('.', 1)[-1].lower() if '.' in photo_id else ''
        content_type_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'heic': 'image/heic',
            'heif': 'image/heic',
        }
        content_type = content_type_map.get(ext, 'application/octet-stream')

        # 既にレコードがあればスキップ
        existing = table.get_item(Key={'userId': user_id, 'photoId': photo_id})
        if 'Item' in existing:
            continue

        # DynamoDB にメタデータを登録
        table.put_item(Item={
            'userId': user_id,
            'photoId': photo_id,
            'filename': photo_id,
            'contentType': content_type,
            's3Key': key,
            'size': size,
            'status': 'uploaded',
            'createdAt': datetime.now(timezone.utc).isoformat(),
            'labels': [],
        })

        print(f'Registered: {key} for user {user_id}')
