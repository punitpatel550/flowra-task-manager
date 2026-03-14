from flask import Flask, session, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user, logout_user
from config import Config
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import os

db = SQLAlchemy()
login_manager = LoginManager()

# 🔔 Create Scheduler
scheduler = BackgroundScheduler()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ✅ Session timeout
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=1)

    upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    app.config["UPLOAD_FOLDER"] = upload_folder
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max

    if not os.path.exists(app.config["UPLOAD_FOLDER"]):
        os.makedirs(app.config["UPLOAD_FOLDER"])

    db.init_app(app)
    login_manager.init_app(app)

    # ✅ Login required page redirect
    login_manager.login_view = "main.login"
    login_manager.login_message = "Please login to continue."
    login_manager.login_message_category = "warning"

    from app.models import User, Task
    from app.routes import bp
    app.register_blueprint(bp)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ✅ If session expired / unauthorized
    @login_manager.unauthorized_handler
    def unauthorized():
        flash("Session expired. Please login again.", "warning")
        return redirect(url_for("main.home"))

    # ✅ Session activity checker
    @app.before_request
    def handle_session_timeout():
        session.permanent = True

        # इन routes पर timeout check skip
        allowed_endpoints = {
            "main.home",
            "main.login",
            "static"
        }

        if request.endpoint in allowed_endpoints:
            return

        if current_user.is_authenticated:
            now = datetime.utcnow()

            last_activity = session.get("last_activity")

            if last_activity:
                try:
                    last_activity = datetime.fromisoformat(last_activity)

                    if now - last_activity > timedelta(minutes=15):
                        logout_user()
                        session.clear()
                        flash("Session timed out due to inactivity. Please login again.", "warning")
                        return redirect(url_for("main.home"))
                except Exception:
                    session.clear()
                    return redirect(url_for("main.home"))

            session["last_activity"] = now.isoformat()

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
    if not scheduler.get_jobs():
        scheduler.add_job(func=check_reminders, trigger="interval", minutes=1)

    if not scheduler.running:
        scheduler.start()

    with app.app_context():
        db.create_all()

    return app