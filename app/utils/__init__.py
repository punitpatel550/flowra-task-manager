from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import os

db = SQLAlchemy()
login_manager = LoginManager()

# 🔔 Create Scheduler
scheduler = BackgroundScheduler()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    app.config["UPLOAD_FOLDER"] = upload_folder
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max

    if not os.path.exists(app.config["UPLOAD_FOLDER"]):
        os.makedirs(app.config["UPLOAD_FOLDER"])

    db.init_app(app)
    login_manager.init_app(app)

    login_manager.login_view = "main.login"

    from app.models import User, Task
    from app.routes import bp
    app.register_blueprint(bp)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # 🔥 Reminder Checker Function
    def check_reminders():
        with app.app_context():
            now = datetime.now()

            tasks = Task.query.filter(
                Task.reminder_active == True,
                Task.reminder_end_time != None,
                Task.reminder_end_time > now
            ).all()

            for task in tasks:
                print(f"🔔 Reminder: {task.title}")  
                # Future: WhatsApp API yaha integrate hoga

    # 🔥 Run reminder every 1 minute
    scheduler.add_job(func=check_reminders, trigger="interval", minutes=1)

    if not scheduler.running:
        scheduler.start()

    with app.app_context():
        db.create_all()

    return app