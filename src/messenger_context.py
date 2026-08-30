from messengers import Messenger


def get_users_table(messenger) -> str:
    return Messenger(messenger).table_name


def get_donations_table(messenger) -> str:
    return Messenger(messenger).donations_table


def get_messenger_from_m(m) -> Messenger:
    return m.messenger


def get_messenger_from_kwargs(kwargs) -> Messenger:
    messenger = kwargs.get('messenger')
    if messenger is None:
        raise ValueError('В kwargs не передан мессенджер')
    return messenger


def get_nice_name_of_messenger_from_kwargs(kwargs) -> str:
    return Messenger(get_messenger_from_kwargs(kwargs)).nice_name
