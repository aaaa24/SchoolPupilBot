def get_users_table(messenger='telegram'):
    return 'users_max' if messenger == 'max' else 'users_telegram'


def get_messenger_from_kwargs(kwargs):
    messenger = kwargs.get('messenger') if isinstance(kwargs, dict) else None
    return messenger or 'telegram'
