from json import dumps, loads

import telebot

from main import bot, logger, process_max_callback, process_command_message, process_text_message, set_connect, \
    telegram_client
from messengers import (
    MaxMessengerClient,
    Messenger,
    MessengerChat,
    MessengerUser,
    UnifiedCallbackMessage,
    UnifiedCallbackQuery,
    UnifiedMessage,
    UnifiedPhoto,
    max_keyboard_to_markup,
)


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

        photos = [
            UnifiedPhoto(attachment['payload']['token'], attachment['payload'].get('url'))
            for attachment in body.get('attachments', [])
            if attachment.get('type') == 'image' and attachment.get('payload', {}).get('token')
        ]
        if user_id is None or chat_id is None or (text is None and not photos):
            return None

        user = MessengerUser(
            id=int(user_id),
            first_name=sender.get('first_name', sender.get('name', 'Пользователь')),
            last_name=sender.get('last_name'),
            username=sender.get('username'),
        )
        return UnifiedMessage(
            messenger=Messenger.MAX,
            user=user,
            chat=MessengerChat(id=int(chat_id)),
            text=None if photos else text,
            caption=text if photos else None,
            photos=photos or None,
            context=context,
        )

    if update_type == 'message_callback':
        callback = payload.get('callback', {}) or {}
        callback_id = callback.get('callback_id')
        callback_payload = callback.get('payload')
        message = payload.get('message', {}) or {}
        callback_user = callback.get('user', {}) or {}
        recipient = message.get('recipient', {}) or {}
        body = message.get('body', {}) or {}

        user_id = callback_user.get('user_id')
        chat_id = recipient.get('chat_id') or recipient.get('user_id')
        if callback_id is None or callback_payload is None or user_id is None or chat_id is None:
            return None

        user = MessengerUser(
            id=int(user_id),
            first_name=callback_user.get('first_name', callback_user.get('name', 'Пользователь')),
            last_name=callback_user.get('last_name'),
            username=callback_user.get('username'),
        )
        callback_message = UnifiedCallbackMessage(
            messenger=Messenger.MAX,
            user=user,
            chat=MessengerChat(id=int(chat_id)),
            text=body.get('text') or '',
            message_id=body.get('mid'),
            reply_markup=max_keyboard_to_markup(body.get('attachments')),
            photos=[
                UnifiedPhoto(attachment['payload']['token'], attachment['payload'].get('url'))
                for attachment in body.get('attachments', [])
                if attachment.get('type') == 'image' and attachment.get('payload', {}).get('token')
            ] or None,
        )
        return UnifiedCallbackQuery(
            messenger=Messenger.MAX,
            id=str(callback_id),
            user=user,
            data=str(callback_payload),
            message=callback_message,
            context=context,
        )

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
        return UnifiedMessage(messenger=Messenger.MAX, user=user, chat=MessengerChat(id=int(chat_id)), text=text, context=context)

    return None


def handler(event, context):
    if 'httpMethod' in event:
        if event['path'] == '/telegram':
            message = telebot.types.Update.de_json(event['body'])
            logger.info('Получено событие Telegram',
                        extra={"update": loads(dumps(message, default=vars, ensure_ascii=False))})

            if message.message:
                message.message.context = context
                message.message.messenger = Messenger.TELEGRAM
            if message.callback_query:
                message.callback_query.context = context
                message.callback_query.messenger = Messenger.TELEGRAM
                message.callback_query.message.messenger = Messenger.TELEGRAM

            bot.process_new_updates([message])

        elif event['path'] == '/max':
            payload = loads(event['body'])
            logger.info('Получено событие MAX', extra={'update': payload})

            max_message = _parse_max_update(payload, context)
            if max_message is not None:
                max_client = MaxMessengerClient()
                if hasattr(max_message, 'data'):
                    process_max_callback(max_message, max_client)
                elif _is_command(max_message.text):
                    process_command_message(max_message, max_client)
                else:
                    process_text_message(max_message, max_client)

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
                mailing_changes_tt(
                    {
                        Messenger.TELEGRAM: telegram_client,
                        Messenger.MAX: MaxMessengerClient(),
                    },
                    session,
                    logger,
                )
                session.closing()

    return {'statusCode': 200, 'body': '!'}
