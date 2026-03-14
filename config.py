import os

class Config:
    SECRET_KEY = "supersecretkey"
    SQLALCHEMY_DATABASE_URI = "mysql+pymysql://root:%40punit1280@localhost/task_manager"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Twilio Credentials
    TWILIO_ACCOUNT_SID = "AC4c3d9e6938de4f399a3657eab881bc1c"
    TWILIO_AUTH_TOKEN = "47ba1bf93fc039d575736ef477ca25b9"
    TWILIO_WHATSAPP_NUMBER = "+14155238886"  