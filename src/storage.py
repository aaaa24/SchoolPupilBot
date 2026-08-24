import mimetypes
import os
from uuid import uuid4

import boto3


class ObjectStorage:
    def __init__(self):
        self.bucket_name = os.getenv('BUCKET_NAME')
        if not self.bucket_name:
            raise RuntimeError('Отсутствует переменная окружения BUCKET_NAME')
        self.client = boto3.client(
            's3',
            endpoint_url=os.getenv('S3_ENDPOINT_URL'),
            region_name=os.getenv('AWS_REGION'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        )

    def upload_photo(self, data: bytes, content_type: str | None = None, filename: str | None = None) -> str:
        extension = mimetypes.guess_extension(content_type or '') or '.jpg'
        if filename is None:
            filename = str(uuid4())
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=f'{filename}{extension}',
            Body=data,
            ContentType=content_type or 'image/jpeg',
        )
        return f'{filename}{extension}'

    def download_photo(self, filename: str) -> tuple[bytes, str | None]:
        response = self.client.get_object(Bucket=self.bucket_name, Key=filename)
        return response['Body'].read(), response.get('ContentType')

    def delete_photo(self, filename: str):
        self.client.delete_object(Bucket=self.bucket_name, Key=filename)
