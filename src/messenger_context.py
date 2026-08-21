def get_users_table(messenger='telegram'):
    return 'users_max' if messenger == 'max' else 'users_telegram'


def get_messenger_from_m(m):
    messenger = getattr(m, 'messenger', None)
    return messenger or 'telegram'


def get_messenger_from_kwargs(kwargs):
    messenger = kwargs.get('messenger') if isinstance(kwargs, dict) else None
    return messenger or 'telegram'


def get_nice_name_of_messenger_from_kwargs(kwargs):
    messenger = get_messenger_from_kwargs(kwargs)
    return 'Telegram' if messenger == 'telegram' else 'MAX' if messenger == 'max' else messenger
