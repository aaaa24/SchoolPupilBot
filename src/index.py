from json import dumps, loads

import telebot

from main import bot, logger, process_command_message, process_text_message, set_connect
from messengers import MaxMessengerClient, MessengerChat, MessengerUser, UnifiedMessage


def _is_command(text):
    return isinstance(text, str) and text.startswith('/')


def _parse_max_update(payload, context):
    update_type = payload.get('update_type')

    if update_type == 'message_created':
        message = payload.get('message', {})
        body = message.get('body', {}) or {}
        sender = message.get('sender', {}) or {}
        recipient = message.get('recipient', {}) or {}

        text = body.get('text')
        user_id = sender.get('user_id')
        chat_id = recipient.get('chat_id') or recipient.get('user_id')

        if user_id is None or chat_id is None or text is None:
            return None

        user = MessengerUser(
            id=int(user_id),
            first_name=sender.get('first_name', sender.get('name', 'Пользователь')),
            last_name=sender.get('last_name'),
            username=sender.get('username'),
        )
        return UnifiedMessage(user=user, chat=MessengerChat(id=int(chat_id)), text=text, context=context)

    if update_type == 'bot_started':
        user_data = payload.get('user', {})
        user_id = user_data.get('user_id')
        chat_id = payload.get('chat_id')
        if user_id is None or chat_id is None:
            return None

        payload_text = payload.get('payload')
        text = '/start' if payload_text is None else f'/start {payload_text}'
        user = MessengerUser(
            id=int(user_id),
            first_name=user_data.get('first_name', user_data.get('name', 'Пользователь')),
            last_name=user_data.get('last_name'),
            username=user_data.get('username'),
        )
        return UnifiedMessage(user=user, chat=MessengerChat(id=int(chat_id)), text=text, context=context)

    return None


def handler(event, context):
    if 'httpMethod' in event:
        if event['path'] == '/telegram':
            message = telebot.types.Update.de_json(event['body'])
            logger.info('Получено событие Telegram',
                        extra={"update": loads(dumps(message, default=vars, ensure_ascii=False))})

            if message.message:
                message.message.context = context
            if message.callback_query:
                message.callback_query.context = context

            bot.process_new_updates([message])

        elif event['path'] == '/max':
            payload = loads(event['body'])
            logger.info('Получено событие MAX', extra={'update': payload})

            max_message = _parse_max_update(payload, context)
            if max_message is not None:
                max_client = MaxMessengerClient()
                if _is_command(max_message.text):
                    process_command_message(max_message, max_client, messenger='max')
                else:
                    process_text_message(max_message, max_client, messenger='max')

        elif event['path'] == '/yookassa':
            session, _ = set_connect(50)
            if not session is None:
                from pay import successful_payment
                payment = loads(event['body'])['object']
                successful_payment(bot, payment, session, logger)
                session.closing()

    elif 'details' in event and 'payload' in event['details']:
        if event['details']['payload'] == 'daily_statistics':
            from statistics import daily_statistics
            daily_statistics(bot, context, logger)
        elif event['details']['payload'] == 'mailing_changes_tt':
            session, _ = set_connect(50)
            if not session is None:
                from changes_tt import mailing_changes_tt
                mailing_changes_tt(bot, session, logger)
                session.closing()

    return {'statusCode': 200, 'body': '!'}
