import os

import ydb


def create_driver():
    mode = os.getenv('YDB_MODE', 'cloud')
    endpoint = os.getenv('YDB_ENDPOINT')
    database = os.getenv('YDB_DATABASE')
    service_account_file = os.getenv('YC_SERVICE_ACCOUNT_KEY_FILE')
    if mode == 'cloud':
        return ydb.Driver(
            endpoint=endpoint,
            database=database,
            credentials=ydb.iam.MetadataUrlCredentials()
        )
    elif mode == 'cloud-local':
        return ydb.Driver(
            endpoint=endpoint,
            database=database,
            credentials=ydb.iam.ServiceAccountCredentials.from_file(service_account_file)
        )
    elif mode == 'local':
        return ydb.Driver(
            endpoint=endpoint,
            database=database,
            credentials=ydb.credentials.AnonymousCredentials()
        )
    else:
        raise ValueError('Unknown YDB_MODE')
