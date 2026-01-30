from json import dumps, loads

import telebot

from main import bot, logger, set_connect


def handler(event, context):
    if 'httpMethod' in event:
        if event['path'] == '/':
            message = telebot.types.Update.de_json(event['body'])
            logger.info('Получено событие', extra={"update": loads(dumps(message, default=vars, ensure_ascii=False))})

            if message.message:
                message.message.context = context
            if message.callback_query:
                message.callback_query.context = context

            bot.process_new_updates([message])
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
