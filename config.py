import os

class Config:
    SECRET_KEY = "supersecretkey"

    # Render PostgreSQL connection
    SQLALCHEMY_DATABASE_URI = os.environ.get("postgresql://flowra_db_user:RN3hp87JDSRd0Oz2rnOf19mEovuTXjpk@dpg-d6qlt395pdvs73bd2gv0-a/flowra_db")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Twilio Credentials
    TWILIO_ACCOUNT_SID = "AC4c3d9e6938de4f399a3657eab881bc1"
    TWILIO_AUTH_TOKEN = "47ba1bf93fc039d575736ef477ca25b9"
    TWILIO_WHATSAPP_NUMBER = "+14155238886"