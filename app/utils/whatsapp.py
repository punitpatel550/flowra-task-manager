from twilio.rest import Client
from flask import current_app


def send_whatsapp_message(to_number, message):
    try:
        account_sid = current_app.config["TWILIO_ACCOUNT_SID"]
        auth_token = current_app.config["TWILIO_AUTH_TOKEN"]
        twilio_number = current_app.config["TWILIO_WHATSAPP_NUMBER"]

        client = Client(account_sid, auth_token)

        print("SID:", account_sid)
        print("TOKEN:", auth_token)
        print("FROM:", twilio_number)

        msg = client.messages.create(
            body=message,
            from_=f"whatsapp:{twilio_number}",
            to=f"whatsapp:{to_number}"
        )

        print("Message Sent SID:", msg.sid)

    except Exception as e:
        print("Error sending WhatsApp message:", e)