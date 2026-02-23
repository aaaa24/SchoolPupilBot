import os
import time
import uuid

import ydb
from yookassa import Configuration, Payment

from constants import Phrase
from utils import send_text, create_inline_kb


def successful_payment(bot, payment, session, logger):
    start_time = time.time()
    logger.debug('Запущена функция successful_payment')
    log_info = {
        'payment': payment,
        'user_id': None,
        'message_id': None
    }

    text_request = f'UPSERT INTO donations (id, is_successful) VALUES ("{payment["id"]}", True); ' \
                   f'SELECT user_id, message_id, amount FROM donations WHERE id = "{payment["id"]}"'
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
    bot.edit_message_text(text_user, user_id, message_id, reply_markup=inline_kb_user)

    user_info = bot.get_chat(user_id)
    text_admin = Phrase.SUCCESSFUL_PAYMENT_ADMIN.format(
        text=f'Сумма: {amount} ₽' + \
             f'\nСумма с учётом комиссии: {payment["income_amount"]["value"].replace(".", ",")} ₽' + \
             '\nID: ' + (
                 f'<code>{user_id}</code>' if user_info.has_private_forwards else f'<a href="tg://user?id={user_id}">{user_id}</a>') + \
             f'\nИмя: {user_info.first_name}' + \
             (f'\nФамилия: {user_info.last_name}' if user_info.last_name else '') + \
             (f'\nНик: @{user_info.username}' if user_info.username else '')
    )

    bot.send_message(int(os.getenv('TECHNO_INFO')), text_admin, parse_mode='HTML', disable_notification=True)

    log_info['user_id'] = user_id
    log_info['message_id'] = message_id
    logger.debug('Завершена функция successful_payment', extra={'duration': time.time() - start_time, 'info': log_info})


def create_order(m, user, bot, session, *args, **kwargs):
    Configuration.account_id = int(os.getenv('YOOKASSA_ACCOUNT_ID'))
    Configuration.secret_key = os.getenv('YOOKASSA_SECRET_KEY')

    amount = m.data.split('$')[0].split('_')[1]

    payment = Payment.create({
        'amount': {
            'value': f'{amount}.00',
            'currency': 'RUB'
        },
        'confirmation': {
            'type': 'redirect',
            'return_url': 'https://t.me/SchoolPupilBot'
        },
        'capture': True,
        'save_payment_method': False,
        'description': 'Пожертвование для бота «Школьный помощник»',
        'metadata': {'user_id': user['id']}
    }, uuid.uuid4())

    text = Phrase.PAYMENT.format(amount=amount)

    list_inline_btn = [
        ('💳 Пожертвовать', payment.confirmation.confirmation_url, 'url'),
        [('← Назад', 'pay$new'), ('🏠 В меню', 'menu$new')]
    ]
    inline_kb = create_inline_kb(list_inline_btn)
    message = send_text(bot, m, text, inline_kb)

    text_request = 'UPSERT INTO donations (id, user_id, message_id, amount, is_successful) ' \
                   f'VALUES ("{payment.id}", {user["id"]}, {message.id}, {amount}, False);'
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
