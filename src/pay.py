import os
import time
import uuid

import ydb
from telebot.apihelper import ApiTelegramException
from yookassa import Configuration, Payment

from constants import Phrase
from messenger_context import get_donations_table, get_messenger_from_kwargs
from messengers import Messenger, get_client
from utils import send_text, create_inline_kb


def _payment_metadata(m, user, messenger):
    metadata = {'user_id': user['id'], 'messenger': messenger.value}
    for key in ('first_name', 'last_name', 'username'):
        value = getattr(m.from_user, key, None)
        if value:
            metadata[key] = value
    return metadata


def _screen_message_id(m, message):
    message_id = getattr(message, 'id', None)
    if message_id is None and hasattr(m, 'message'):
        message_id = m.message.id
    return message_id


def _user_info_for_admin(bot, messenger, user_id, metadata):
    if messenger is Messenger.TELEGRAM:
        user_info = bot.get_chat(user_id)
        id_text = f'<code>{user_id}</code>' if user_info.has_private_forwards \
            else f'<a href="tg://user?id={user_id}">{user_id}</a>'
        return id_text, user_info.first_name, user_info.last_name, user_info.username

    return f'<code>{user_id}</code>', metadata.get('first_name'), metadata.get('last_name'), metadata.get('username')


def _edit_screen(bot, text, user_id, message_id, reply_markup, logger):
    # При ошибке обработки YooKassa повторяет уведомление, поэтому экран уже может быть отрисован
    try:
        bot.edit_message_text(text, user_id, message_id, reply_markup=reply_markup)
    except ApiTelegramException as error:
        if 'message is not modified' not in str(error):
            raise
        logger.debug('Экран об успешной оплате уже отрисован')


def successful_payment(clients, payment, session, logger):
    start_time = time.time()
    logger.debug('Запущена функция successful_payment')
    log_info = {
        'payment': payment,
        'user_id': None,
        'message_id': None
    }

    metadata = payment.get('metadata') or {}
    messenger = Messenger(metadata.get('messenger', Messenger.TELEGRAM.value))
    bot = clients[messenger]
    donations_table = get_donations_table(messenger)

    text_request = f'UPSERT INTO {donations_table} (id, is_successful) VALUES ("{payment["id"]}", True); ' \
                   f'SELECT user_id, message_id, amount FROM {donations_table} WHERE id = "{payment["id"]}"'
    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )
    user_id, message_id, amount = [request[0].rows[0][x] for x in ('user_id', 'message_id', 'amount')]

    text_user = Phrase.SUCCESSFUL_PAYMENT_USER.format(amount=amount)
    url = f'https://yoomoney.ru/checkout/payments/v2/success?orderId={payment["id"]}'

    inline_kb_user = create_inline_kb(
        [('💳 Детали платежа', url, 'url'), ('🏠 В меню', 'menu$new')]
    )
    _edit_screen(bot, text_user, user_id, message_id, inline_kb_user, logger)

    id_text, first_name, last_name, username = _user_info_for_admin(bot, messenger, user_id, metadata)
    text_admin = Phrase.SUCCESSFUL_PAYMENT_ADMIN.format(
        text=f'Сумма: {amount} ₽' + \
             f'\nСумма с учётом комиссии: {payment["income_amount"]["value"].replace(".", ",")} ₽' + \
             f'\nID: {id_text}' + \
             (f'\nИмя: {first_name}' if first_name else '') + \
             (f'\nФамилия: {last_name}' if last_name else '') + \
             (f'\nНик: @{username}' if username else '')
    )

    bot.send_message(messenger.techno_chat_id, text_admin, parse_mode='HTML', disable_notification=True)

    log_info['user_id'] = user_id
    log_info['message_id'] = message_id
    logger.debug('Завершена функция successful_payment', extra={'duration': time.time() - start_time, 'info': log_info})


def create_order(m, user, bot, session, *args, **kwargs):
    Configuration.account_id = int(os.getenv('YOOKASSA_ACCOUNT_ID'))
    Configuration.secret_key = os.getenv('YOOKASSA_SECRET_KEY')

    messenger = get_messenger_from_kwargs(kwargs)
    amount = m.data.split('$')[0].split('_')[1]

    payment = Payment.create({
        'amount': {
            'value': f'{amount}.00',
            'currency': 'RUB'
        },
        'confirmation': {
            'type': 'redirect',
            'return_url': get_client(bot).get_bot_url()
        },
        'capture': True,
        'save_payment_method': False,
        'description': 'Пожертвование для бота «Школьный помощник»',
        'metadata': _payment_metadata(m, user, messenger)
    }, uuid.uuid4())

    text = Phrase.PAYMENT.format(amount=amount)

    list_inline_btn = [
        ('💳 Пожертвовать', payment.confirmation.confirmation_url, 'url'),
        [('← Назад', 'pay$new'), ('🏠 В меню', 'menu$new')]
    ]
    inline_kb = create_inline_kb(list_inline_btn)
    message = send_text(bot, m, text, inline_kb)

    message_id = _screen_message_id(m, message)
    text_request = f'UPSERT INTO {get_donations_table(messenger)} (id, user_id, message_id, amount, is_successful) ' \
                   f'VALUES ("{payment.id}", {user["id"]}, "{message_id}", {amount}, False);'
    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )


def call(m, user, bot, session, *args, **kwargs):
    text = Phrase.CHOOSE_AMOUNT
    amounts = [10, 25, 50, 100, 150, 200, 250, 500]

    list_inline_btn = [(f'{amount} ₽', f'pay_{amount}') for amount in amounts]
    inline_kb = create_inline_kb([
        list_inline_btn[:4],
        list_inline_btn[4:],
        ('🏠 В меню', 'menu')
    ])

    send_text(bot, m, text, inline_kb)
