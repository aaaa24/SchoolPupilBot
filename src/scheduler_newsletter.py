from newsletter import send_newsletter


def handler(event, context):
    return send_newsletter()
