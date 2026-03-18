from flask import make_response, request, redirect, url_for, render_template, current_app, session
from app.utils.whatsapp import send_whatsapp_message
from py_compile import main
from flask import Blueprint, app, render_template, request, redirect, send_from_directory, url_for, flash
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from app import db
from zoneinfo import ZoneInfo
from app.models import User, Task, Reminder, Department, TaskAttachment, SubTask, Announcement, RecurringTask
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
from flask import current_app, jsonify
import os
import re
from app.models import RecurringTask
from io import BytesIO
import pandas as pd
from flask import send_file
from app.models import TaskAttachment, SubTask

bp = Blueprint("main", __name__)

def to_ist(dt):
    if not dt:
        return None
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Kolkata"))

@bp.before_app_request
def keep_session_alive():
    if current_user.is_authenticated:
        session["last_activity"] = datetime.utcnow().isoformat()

@bp.route("/")
def home():
    return render_template("home.html")

# ---------------- LOGIN ----------------
@bp.route("/login", methods=["GET", "POST"])
def login():

    existing_admin = User.query.filter_by(role="admin").first()

    if not existing_admin:
        default_admin = User(
            username="admin",
            email="admin@example.com",
            role="admin"
        )
        default_admin.set_password("admin123")

        db.session.add(default_admin)
        db.session.commit()

        print("Default admin created: admin / admin123")

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):

            login_user(user)

            # ✅ session activity start
            session["last_activity"] = datetime.utcnow().isoformat()

            if user.role == "admin":
                return redirect(url_for("main.admin_panel"))

            elif user.role == "manager":
                return redirect(url_for("main.manager_panel"))

            else:
                return redirect(url_for("main.employee_panel"))

        else:
            flash("Invalid username or password", "danger")

    return render_template("login.html")




# ---------------- DASHBOARD ----------------
@bp.route("/dashboard")
@login_required
def dashboard():

    if current_user.role == "admin":

        tasks = Task.query.filter_by(is_deleted=False).all()
        managers = User.query.filter_by(role="manager").all()
        employees = User.query.filter_by(role="employee").all()
        departments = Department.query.all()

        department_tasks = {}

        for dept in departments:

            users = User.query.filter_by(department_id=dept.id).all()
            ids = [u.id for u in users]

            if ids:
                dept_tasks = Task.query.filter(
                    Task.assigned_to.in_(ids),
                    Task.is_deleted == False
                ).all()
            else:
                dept_tasks = []

            department_tasks[dept.name] = dept_tasks

        return render_template(
            "admin_panel.html",
            tasks=tasks,
            managers=managers,
            employees=employees,
            department_tasks=department_tasks
        )

    elif current_user.role == "manager":

        employees = User.query.filter_by(supervisor_id=current_user.id).all()
        employee_ids = [emp.id for emp in employees]

        tasks = Task.query.filter(
            Task.assigned_to.in_(employee_ids),
            Task.is_deleted == False
        ).all()

        return render_template("manager_panel.html", tasks=tasks, employees=employees)

    else:

        tasks = Task.query.filter_by(
            assigned_to=current_user.id,
            is_deleted=False
        ).all()

        employee = User.query.get(current_user.id)

        return render_template("employee_panel.html", tasks=tasks, employee=employee)


@bp.route("/reminders_page")
@login_required
def reminders_page():
    return render_template("reminders.html")


@bp.route("/my-reminders")
@login_required
def my_reminders():
    reminders = Reminder.query.filter_by(
        user_id=current_user.id
    ).order_by(Reminder.remind_at.desc()).all()

    return render_template("my_reminders.html", reminders=reminders)


@bp.route("/stop-reminder-page/<int:id>", methods=["POST"])
@login_required
def stop_reminder_page(id):
    reminder = Reminder.query.get_or_404(id)

    if reminder.user_id != current_user.id:
        flash("Unauthorized", "danger")
        return redirect(url_for("main.my_reminders"))

    reminder.active = False
    db.session.commit()

    flash("Reminder stopped successfully!", "success")
    return redirect(url_for("main.my_reminders"))


# ---------------- CREATE TASK ----------------


@bp.route("/create_task", methods=["GET", "POST"])
@login_required
def create_task():

    if current_user.role not in ["admin", "manager"]:
        flash("Unauthorized access", "danger")
        return redirect(url_for("main.admin_panel"))

    if request.method == "POST":

        title = request.form.get("title")
        description = request.form.get("description")
        priority = request.form.get("priority")
        assigned_to_id = request.form.get("assigned_to")
        due_date_str = request.form.get("due_date")
        reward_points = int(request.form.get("reward_points", 5))
        estimated_time = request.form.get("estimated_time")

        print("Reward points from form:", reward_points)

        if not title:
            flash("Title is required", "danger")
            return redirect(request.url)

        due_date = None
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                flash("Invalid date format", "danger")
                return redirect(request.url)

        assigned_to = int(assigned_to_id) if assigned_to_id else None

        if not description:
            description = "General task created"

        task = Task(
            title=title,
            description=description,
            priority=priority,
            due_date=due_date,
            assigned_to=assigned_to,
            created_by=current_user.id,
            reward_points=reward_points,
            estimated_time=estimated_time
        )

        # Single attachment
        attachment = request.files.get("attachment")
        if attachment and attachment.filename != "":
            filename = secure_filename(attachment.filename)
            upload_path = current_app.config["UPLOAD_FOLDER"]
            os.makedirs(upload_path, exist_ok=True)
            attachment.save(os.path.join(upload_path, filename))
            task.attachment = filename

        db.session.add(task)
        db.session.commit()

        # Multiple attachments
        files = request.files.getlist("attachments")
        upload_path = current_app.config["UPLOAD_FOLDER"]

        for file in files:
            if file and file.filename != "":
                filename = secure_filename(file.filename)
                file_path = os.path.join(upload_path, filename)
                file.save(file_path)

                new_attachment = TaskAttachment(
                    task_id=task.id,
                    filename=filename
                )
                db.session.add(new_attachment)

        db.session.commit()

        print("Task saved. Task ID:", task.id)
        print("Task reward points saved:", task.reward_points)

        # Auto reminder
        if due_date and assigned_to:
            reminder_time = due_date - timedelta(hours=1)

            reminder = Reminder(
                reason=f"New Task Assigned: {title}",
                remind_at=reminder_time,
                end_at=due_date,
                user_id=assigned_to,
                active=True
            )

            db.session.add(reminder)
            db.session.commit()

        # WhatsApp notification
        if assigned_to:
            employee = User.query.get(assigned_to)

            print("Assigned To ID:", assigned_to)
            print("Employee object:", employee)

            if employee:
                print("Employee username:", employee.username)
                print("Employee phone:", employee.phone)

            if employee and employee.phone:
                message = f"""
Hello {employee.username},

You have been assigned a new task.

📌 Task: {task.title}
⏰ Due Date: {task.due_date}
🏆 Reward Points: {task.reward_points}

Please check your dashboard.
"""
                print("About to send WhatsApp message...")
                print("Message body:", message)

                try:
                    send_whatsapp_message(employee.phone, message)
                    print("send_whatsapp_message function called successfully")
                except Exception as e:
                    print("WhatsApp Error:", e)
            else:
                print("Employee phone missing or employee not found")
        else:
            print("No assigned_to value received")

        flash("Task created successfully!", "success")

        if current_user.role == "manager":
            return redirect(url_for("main.manager_panel"))
        else:
            return redirect(url_for("main.admin_panel"))

    # Manager employee filter
    if current_user.role == "manager":
        employees = User.query.filter_by(
            role="employee",
            supervisor_id=current_user.id
        ).all()
    else:
        employees = User.query.filter_by(role="employee").all()

    return render_template(
        "create_task.html",
        users=employees
    )



@bp.route("/task/<int:task_id>/subtask", methods=["POST"])
@login_required
def create_subtask(task_id):

    task = Task.query.get_or_404(task_id)

    # ---------------- PERMISSION LOGIC ----------------

    # Admin -> allowed for all
    if current_user.role == "admin":
        pass

    # Manager -> only his employees tasks
    elif current_user.role == "manager":

        employee = User.query.get(task.assigned_to)

        if not employee or employee.supervisor_id != current_user.id:
            flash("You cannot add subtask to this task", "danger")
            return redirect(request.referrer)

    # Employee -> only own task
    elif current_user.role == "employee":

        if task.assigned_to != current_user.id:
            flash("You can only add subtask to your own task", "danger")
            return redirect(request.referrer)

    # --------------------------------------------------

    title = request.form.get("title")

    if not title:
        flash("Sub task title required", "danger")
        return redirect(request.referrer)

    subtask = SubTask(
        task_id=task_id,
        title=title,
        created_by=current_user.id
    )

    db.session.add(subtask)
    db.session.commit()

    flash("Sub Task Added", "success")

    return redirect(request.referrer)


@bp.route("/task/toggle/<int:task_id>")
@login_required
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Example toggle logic
    if task.status == "Completed":
        task.status = "Pending"
    else:
        task.status = "Completed"

    db.session.commit()
    return redirect(url_for("main.create_task"))





@bp.route("/edit-user/<int:id>", methods=["GET", "POST"])
@login_required
def edit_user(id):

    if current_user.role != "admin":
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    user = User.query.get_or_404(id)
    managers = User.query.filter_by(role="manager").all()
    departments = Department.query.all()

    if request.method == "POST":

        user.username = request.form.get("username").capitalize()
        user.email = request.form.get("email")
        phone = request.form.get("phone")
        user.role = request.form.get("role")
        user.department_id = request.form.get("department_id")

        supervisor_id = request.form.get("supervisor_id")

        if not re.match(r'^\+\d{10,15}$', phone):
            flash("Invalid phone number format. Use +919876543210", "danger")
            return redirect(url_for("main.edit_user", id=id))

        user.phone = phone

        if user.role == "employee" and supervisor_id:
            user.supervisor_id = int(supervisor_id)
        else:
            user.supervisor_id = None

        try:
            db.session.commit()
            flash("User updated successfully!", "success")
            return redirect(url_for("main.admin_panel"))

        except IntegrityError:
            db.session.rollback()
            flash("Username or Phone already exists!", "danger")

    return render_template(
        "edit_user.html",
        user=user,
        managers=managers,
        departments=departments
    )

@bp.route("/create-recurring-task", methods=["GET", "POST"])
@login_required
def create_recurring_task():

    if current_user.role not in ["admin", "manager"]:
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    if current_user.role == "manager":
        employees = User.query.filter_by(
            role="employee",
            supervisor_id=current_user.id
        ).all()
    else:
        employees = User.query.filter_by(role="employee").all()

    if request.method == "POST":
        title = request.form.get("title")
        assigned_to = request.form.get("assigned_to")
        start_date = datetime.strptime(request.form.get("start_date"), "%Y-%m-%d").date()
        end_date = datetime.strptime(request.form.get("end_date"), "%Y-%m-%d").date()
        frequency = request.form.get("frequency")

        recurring = RecurringTask(
            title=title,
            assigned_to=int(assigned_to),
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            last_generated=None
        )

        db.session.add(recurring)
        db.session.commit()

        flash("Recurring task created!", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("create_recurring_task.html", employees=employees)








#-------------------AI suggestioin-------------------
@bp.route("/task/<int:task_id>/ai-suggestion")
@login_required
def ai_suggestion(task_id):
    task = Task.query.get_or_404(task_id)

    # Permission
    if current_user.role == "employee" and task.assigned_to != current_user.id:
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    if current_user.role == "manager":
        employee = User.query.get(task.assigned_to)
        if not employee or employee.supervisor_id != current_user.id:
            return jsonify({"success": False, "message": "Unauthorized"}), 403

    title = (task.title or "").lower()
    description = (task.description or "").lower()
    priority = task.priority or "Low"
    status = task.status or "Pending"

    suggestions = []

    # General suggestions
    suggestions.append("Start by reading the task title and description carefully.")
    suggestions.append("Break the work into 2-3 small subtasks before starting.")
    suggestions.append("Keep proof of work ready before final submission.")

    # Priority based
    if priority == "High":
        suggestions.append("This is a high priority task. Complete the most critical part first.")
        suggestions.append("Avoid multitasking while working on this task.")
    elif priority == "Medium":
        suggestions.append("Plan the task in short steps and finish it before due time.")
    else:
        suggestions.append("You can complete this in a steady flow, but do not delay unnecessarily.")

    # Status based
    if status == "Pending":
        suggestions.append("Suggested next action: click Start and begin the first workable step.")
    elif status == "Rejected":
        suggestions.append("Read the rejection remarks carefully and correct the exact issue before resubmitting.")
    elif status == "Submitted":
        suggestions.append("Your proof is submitted. Wait for approval or feedback from manager/admin.")

    # Keyword based
    text = title + " " + description

    if "report" in text:
        suggestions.append("Prepare the report in clean sections: summary, details, and final conclusion.")
    if "design" in text or "ui" in text:
        suggestions.append("Create a rough draft first, then refine colors, alignment, and spacing.")
    if "data" in text or "excel" in text:
        suggestions.append("Validate your data before submission and double-check totals or formulas.")
    if "client" in text or "meeting" in text:
        suggestions.append("Keep communication points short, professional, and clearly documented.")
    if "upload" in text or "document" in text or "file" in text:
        suggestions.append("Make sure the final file name is clear and the correct version is uploaded.")

    # Due date based
    if task.due_date:
        suggestions.append(f"Target completion before due date: {task.due_date.strftime('%d %b %Y %I:%M %p') if hasattr(task.due_date, 'strftime') else task.due_date}")

    return jsonify({
        "success": True,
        "task_id": task.id,
        "title": task.title,
        "suggestions": suggestions
    })


#----------------------------------------

@bp.route("/delete_user/<int:id>", methods=["POST"])
@login_required
def delete_user(id):

    if current_user.role != "admin":
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    user = User.query.get_or_404(id)

    db.session.delete(user)
    db.session.commit()

    flash("User Deleted", "danger")

    return redirect(url_for("main.manage_users"))


@bp.route("/delete_reminder/<int:id>", methods=["POST"])
@login_required
def delete_reminder(id):

    reminder = Reminder.query.get_or_404(id)

    if reminder.user_id == current_user.id:
        db.session.delete(reminder)
        db.session.commit()

    return "",204

# ---------------- DELETE TASK ----------------
# DELETE TASK
@bp.route("/task/delete/<int:task_id>", methods=["POST"])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)

    if current_user.role != "admin" and task.created_by != current_user.id:
        return jsonify({"success": False, "message": "You are not authorized!"})

    task.is_deleted = True
    task.deleted_at = datetime.now()
    db.session.commit()

    return jsonify({"success": True, "message": "Task deleted successfully!"})
# ---------------- SUBMIT TASK WITH FILE ----------------
@bp.route("/task/submit/<int:id>", methods=["POST"])
@login_required
def submit_task(id):
    task = Task.query.get_or_404(id)

    if current_user.role != "employee":
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    file = request.files.get("proof_file")
    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)
        task.proof_file = filename

    task.status = "Submitted"
    db.session.commit()
    flash("Task submitted successfully with proof!", "success")
    return redirect(url_for("main.employee_panel"))

# ---------------- DOWNLOAD PROOF ----------------
@bp.route("/uploads/<filename>")
@login_required
def download_proof(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


@bp.route('/set-reminder', methods=['POST'])
@login_required
def set_reminder():
    reason = request.form.get('reason')
    remind_at = request.form.get('remind_at')
    end_at = request.form.get('end_at')
    is_daily = True if request.form.get('is_daily') else False

    try:
        reminder = Reminder(
            reason=reason,
            remind_at=datetime.fromisoformat(remind_at),
            end_at=datetime.fromisoformat(end_at) if end_at else None,
            user_id=current_user.id,
            is_daily=is_daily,
            active=True
        )

        db.session.add(reminder)
        db.session.commit()
        flash("Reminder set successfully!", "success")

    except Exception as e:
        db.session.rollback()
        print("Reminder Error:", e)
        flash(f"Reminder failed: {e}", "danger")

    if current_user.role == "manager":
        return redirect(url_for("main.manager_panel"))
    elif current_user.role == "admin":
        return redirect(url_for("main.admin_panel"))
    else:
        return redirect(url_for("main.employee_panel"))

# CREATE REMINDER
@bp.route("/create_reminder", methods=["POST"])
@login_required
def create_reminder():

    reason = request.form.get("reason")
    remind_at = request.form.get("remind_at")
    end_at = request.form.get("end_at")
    is_daily = True if request.form.get("is_daily") else False

    reminder = Reminder(
        reason=reason,
        remind_at=datetime.fromisoformat(remind_at),
        end_at=datetime.fromisoformat(end_at) if end_at else None,
        user_id=current_user.id,
        is_daily=is_daily,
        active=True
    )

    db.session.add(reminder)
    db.session.commit()

    flash("Reminder created successfully!", "success")

    if current_user.role == "manager":
        return redirect(url_for("main.manager_panel"))
    elif current_user.role == "admin":
        return redirect(url_for("main.admin_panel"))
    else:
        return redirect(url_for("main.employee_panel"))





#------------------Announcement------------------
@bp.route("/create-announcement", methods=["POST"])
@login_required
def create_announcement():
    message = request.form.get("message")

    if not message or not message.strip():
        flash("Announcement message is required", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))

    announcement = Announcement(
        message=message.strip(),
        created_by=current_user.id,
        active=True
    )

    db.session.add(announcement)
    db.session.commit()

    flash("Announcement posted successfully!", "success")
    return redirect(request.referrer or url_for("main.dashboard"))  

#-------------Latest announcements for dashboard----------------
@bp.route("/get-latest-announcement")
@login_required
def get_latest_announcement():
    announcement = Announcement.query.filter_by(active=True).order_by(Announcement.created_at.desc()).first()

    if not announcement:
        return jsonify({"show": False})

    return jsonify({
        "show": True,
        "id": announcement.id,
        "message": announcement.message,
        "created_by": announcement.creator.username if announcement.creator else "Unknown",
        "created_at": announcement.created_at.strftime("%d %b %Y %I:%M %p")
    })

# GET ACTIVE REMINDERS
@bp.route("/get_reminders")
@login_required
def get_reminders():

    now = datetime.now()

    reminders = Reminder.query.filter(
        Reminder.user_id == current_user.id,
        Reminder.active == True,
        Reminder.remind_at <= now
    ).all()

    data = []

    for r in reminders:

        # If daily, shift next remind time by 1 day
        if r.is_daily:
            r.remind_at = r.remind_at + timedelta(days=1)
            db.session.commit()
        else:
            r.active = False
            db.session.commit()

        data.append({
            "id": r.id,
            "reason": r.reason
        })

    return jsonify(data)


# STOP REMINDER
@bp.route("/stop_reminder/<int:id>", methods=["POST"])
@login_required
def stop_reminder(id):

    reminder = Reminder.query.get_or_404(id)

    if reminder.user_id != current_user.id:
        return jsonify({"success": False})

    reminder.active = False
    db.session.commit()

    return jsonify({"success": True})

# ---------------- APPROVE TASK ----------------
@bp.route("/task/approve/<int:id>")
@login_required
def approve_task(id):

    # ✅ Allow Admin + Manager
    if current_user.role not in ["admin", "manager"]:
        return "Unauthorized"

    task = Task.query.get_or_404(id)

    print("Approving task:", task.id)
    print("Task reward points:", task.reward_points)
    print("Task assigned_to:", task.assigned_to)

    task.status = "Approved"
    task.work_status = "Completed"
    task.completed_at = datetime.utcnow()

    if task.assigned_to:
        employee = User.query.get(task.assigned_to)

        if employee:
            print("Employee:", employee.username)
            print("Old points:", employee.points)

            employee.points = (employee.points or 0) + (task.reward_points or 0)

            print("New points:", employee.points)

    db.session.commit()
    print("Approve committed successfully")

    # ✅ Redirect according to role
    if current_user.role == "admin":
        return redirect(url_for("main.admin_panel"))
    else:
        return redirect(url_for("main.manager_panel"))


# ---------------- CREATE USER ----------------
@bp.route("/create-user", methods=["GET", "POST"])
@login_required
def create_user():

    if current_user.role != "admin":
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    managers = User.query.filter_by(role="manager").all()

    # 🔹 Departments fetch
    departments = Department.query.all()

    if request.method == "POST":

        username = request.form.get("username")
        username = username.capitalize()
        email = request.form.get("email")

        # 🔹 Department ID form se
        department_id = request.form.get("department_id")

        phone = request.form.get("phone")
        password = request.form.get("password")
        role = request.form.get("role")
        supervisor_id = request.form.get("supervisor_id")

        if not re.match(r'^\+\d{10,15}$', phone):
            flash("Invalid phone number format. Use +919876543210", "danger")
            return redirect(url_for("main.create_user"))

        try:
            # Employee ko supervisor chahiye
            if role == "employee" and supervisor_id:
                supervisor_id = int(supervisor_id)
            else:
                supervisor_id = None

            new_user = User(
                username=username,
                email=email,
                department_id=department_id,  # 🔹 yaha change
                phone=phone,
                role=role,
                supervisor_id=supervisor_id
            )

            new_user.set_password(password)

            db.session.add(new_user)
            db.session.commit()

            flash("User created successfully!", "success")
            return redirect(url_for("main.admin_panel"))

        except IntegrityError:
            db.session.rollback()
            flash("Username or Phone already exists!", "danger")

    return render_template(
        "create_user.html",
        managers=managers,
        departments=departments   # 🔹 template ko bhejna
    )



@bp.route("/manage-users")
@login_required
def manage_users():

    if current_user.role != "admin":
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    users = User.query.all()

    return render_template(
        "manage_users.html",
        users=users
    )
@bp.route("/department-dashboard")
@login_required
def department_dashboard():

    if current_user.role != "admin":
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    departments = Department.query.all()
    department_data = []

    for dept in departments:
        employees = User.query.filter_by(
            role="employee",
            department_id=dept.id
        ).all()

        employee_cards = []

        for emp in employees:
            tasks = Task.query.filter_by(
                assigned_to=emp.id,
                is_deleted=False
            ).all()

            employee_cards.append({
                "employee": emp,
                "tasks": tasks
            })

        department_data.append({
            "department": dept,
            "count": len(employees),
            "employee_cards": employee_cards
        })

    return render_template(
        "department_dashboard.html",
        department_data=department_data
    )
# ---------------- ADMIN PANEL ----------------
@bp.route("/admin")
@login_required
def admin_panel():

    if current_user.role != "admin":
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    managers = User.query.filter_by(role="manager").all()
    employees = User.query.filter_by(role="employee").all()

    # Department logic
    departments = Department.query.all()

    department_tasks = {}

    for dept in departments:

        users = User.query.filter_by(department_id=dept.id).all()

        ids = [u.id for u in users]

        tasks = Task.query.filter(Task.assigned_to.in_(ids),Task.is_deleted == False).all()

        department_tasks[dept.name] = tasks

    return render_template(
        "admin_panel.html",
        managers=managers,
        employees=employees,
        department_tasks=department_tasks
    )

@bp.route("/create-department", methods=["GET","POST"])
@login_required
def create_department():

    if current_user.role != "admin":
        flash("Only admin can create departments", "danger")
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":

        name = request.form.get("name")

        dept = Department(name=name)

        db.session.add(dept)
        db.session.commit()

        flash("Department created successfully!", "success")

        return redirect(url_for("main.admin_panel"))

    departments = Department.query.all()

    return render_template("create_department.html", departments=departments)


@bp.route("/delete-department/<int:id>")
@login_required
def delete_department(id):

    if current_user.role != "admin":
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    dept = Department.query.get_or_404(id)

    db.session.delete(dept)
    db.session.commit()

    flash("Department deleted!", "warning")

    return redirect(url_for("main.create_department"))



# ---------------- MANAGER PANEL ----------------
@bp.route("/manager")
@login_required
def manager_panel():

    if current_user.role != "manager":
        flash("Unauthorized", "danger")
        return redirect(url_for("main.admin_panel"))

    # ONLY employees under this manager
    employees = User.query.filter_by(
        role="employee",
        supervisor_id=current_user.id
    ).all()

    print("Manager ID:", current_user.id)
    print("Employees found:", employees)

    employee_ids = [emp.id for emp in employees]

    if employee_ids:
        tasks = Task.query.filter(
            Task.assigned_to.in_(employee_ids),
            Task.is_deleted == False
        ).all()
    else:
        tasks = []

    return render_template(
        "manager_panel.html",
        tasks=tasks,
        employees=employees
    )
# ---------------- EMPLOYEE PANEL ----------------
@bp.route("/employee")
@login_required
def employee_panel():

    if current_user.role != "employee":
        flash("Unauthorized access", "danger")
        return redirect(url_for("main.admin_panel"))

    # GET FILTER
    filter_type = request.args.get("filter", "mytasks")

    # BASE QUERY (your existing query)
    query = Task.query.filter_by(
        assigned_to=current_user.id,
        is_deleted=False
    )

    today = date.today()

    # FILTER LOGIC
    if filter_type == "today":
        tasks = query.filter(db.func.date(Task.due_date) == today).all()

    elif filter_type == "upcoming":
        # tomorrow and future tasks
        tasks = query.filter(db.func.date(Task.due_date) > today).all()

    elif filter_type == "completed":
        tasks = query.filter(Task.status == "Approved").all()

    else:  # mytasks
        tasks = query.all()

    employee = User.query.get(current_user.id)

    return render_template(
        "employee_panel.html",
        tasks=tasks,
        employee=employee,
        active_filter=filter_type
    )


# ---------------- ANALYTICS ----------------
@bp.route("/analytics")
@login_required
def analytics():

    if current_user.role not in ["admin", "manager"]:
        flash("Unauthorized", "danger")
        return redirect(url_for("main.dashboard"))

    # Role-based employees
    if current_user.role == "admin":
        employees = User.query.filter_by(role="employee").all()
    else:
        employees = User.query.filter_by(
            role="employee",
            supervisor_id=current_user.id
        ).all()

    employee_ids = [emp.id for emp in employees]

    if employee_ids:
        tasks = Task.query.filter(Task.assigned_to.in_(employee_ids)).all()
    else:
        tasks = []

    # Summary
    total = len(tasks)
    approved = len([t for t in tasks if t.status == "Approved"])
    pending = len([t for t in tasks if t.status not in ["Approved"]])

    overdue_tasks = [
    t for t in tasks
    if t.due_date and t.status != "Approved" and t.due_date() < date.today()
]
    overdue = len(overdue_tasks)

    # 1) Task completed per employee
    employee_names = []
    employee_completed = []
    employee_points = []
    employee_report = []

    for emp in employees:
        emp_tasks = [t for t in tasks if t.assigned_to == emp.id]
        completed = len([t for t in emp_tasks if t.status == "Approved"])
        pending_count = len([t for t in emp_tasks if t.status != "Approved"])
        in_progress = len([t for t in emp_tasks if t.work_status == "Started"])

        employee_names.append(emp.username)
        employee_completed.append(completed)
        employee_points.append(emp.points or 0)

        employee_report.append({
            "name": emp.username,
            "completed": completed,
            "pending": pending_count,
            "in_progress": in_progress,
            "points": emp.points or 0
        })

    # 2) Project progress
    project_completed = approved
    project_remaining = total - approved if total >= approved else 0
    progress_percent = round((approved / total) * 100, 2) if total > 0 else 0

    # 3) Overdue task table data
    overdue_task_data = []
    for task in overdue_tasks:
        overdue_task_data.append({
            "title": task.title,
            "employee": task.assignee.username if task.assignee else "-",
            "due_date": task.due_date,
            "status": task.status
        })

    # 4) Productivity trends (monthly completed tasks)
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    productivity_trend = [0] * 12

    for task in tasks:
        if task.status == "Approved" and task.completed_at:
            productivity_trend[task.completed_at.month - 1] += 1

    # Top performer
    top_performer = None
    if employees:
        top_emp = max(employees, key=lambda e: e.points or 0)
        top_performer = top_emp.username

    return render_template(
        "analytics.html",
        total=total,
        approved=approved,
        pending=pending,
        overdue=overdue,
        employee_names=employee_names,
        employee_completed=employee_completed,
        employee_points=employee_points,
        employee_report=employee_report,
        project_completed=project_completed,
        project_remaining=project_remaining,
        progress_percent=progress_percent,
        overdue_tasks=overdue_task_data,
        month_labels=month_labels,
        productivity_trend=productivity_trend,
        top_performer=top_performer
    )
    

from xhtml2pdf import pisa
import io



@bp.route("/task-history")
@login_required
def task_history():
    selected_employee_id = request.args.get("employee_id", type=int)

    if current_user.role == "admin":
        query = Task.query
        if selected_employee_id:
            query = query.filter(Task.assigned_to == selected_employee_id)
        tasks = query.order_by(Task.created_at.desc()).all()

    elif current_user.role == "manager":
        employees = User.query.filter_by(role="employee", supervisor_id=current_user.id).all()
        employee_ids = [emp.id for emp in employees]

        query = Task.query.filter(Task.assigned_to.in_(employee_ids))
        if selected_employee_id:
            if selected_employee_id not in employee_ids:
                flash("Unauthorized employee selection", "danger")
                return redirect(url_for("main.task_history"))
            query = query.filter(Task.assigned_to == selected_employee_id)

        tasks = query.order_by(Task.created_at.desc()).all()

    else:
        tasks = Task.query.filter_by(
            assigned_to=current_user.id
        ).order_by(Task.created_at.desc()).all()

    for task in tasks:
        task.created_at_ist = to_ist(task.created_at)
        task.completed_at_ist = to_ist(task.completed_at)

    return render_template("task_history.html", tasks=tasks)



@bp.route("/export-report")
@login_required
def export_report_pdf():

    employees = User.query.filter_by(role="employee").all()

    employee_report=[]

    for e in employees:

        completed = Task.query.filter_by(assigned_to=e.id, status="Approved").count()
        pending = Task.query.filter(Task.assigned_to == e.id, Task.status != "Approved").count()

        employee_report.append({
            "name":e.username,
            "completed":completed,
            "pending":pending,
            "points":e.points
        })

    html=render_template(
        "report_pdf.html",
        employee_report=employee_report
    )

    pdf=io.BytesIO()

    pisa.CreatePDF(io.StringIO(html),pdf)

    response=make_response(pdf.getvalue())

    response.headers["Content-Type"]="application/pdf"
    response.headers["Content-Disposition"]="attachment; filename=flowra_report.pdf"

    return response



@bp.route("/task-history/export")
@login_required
def export_task_history():
    selected_employee_id = request.args.get("employee_id", type=int)

    # Admin users
    if current_user.role == "admin":
        query = Task.query
        if selected_employee_id:
            query = query.filter(Task.assigned_to == selected_employee_id)
        tasks = query.order_by(Task.created_at.desc()).all()

    # Manager users
    elif current_user.role == "manager":
        employees = User.query.filter_by(role="employee", supervisor_id=current_user.id).all()
        employee_ids = [emp.id for emp in employees]

        query = Task.query.filter(Task.assigned_to.in_(employee_ids))
        if selected_employee_id:
            if selected_employee_id not in employee_ids:
                flash("Unauthorized employee selection", "danger")
                return redirect(url_for("main.export_task_history"))
            query = query.filter(Task.assigned_to == selected_employee_id)

        tasks = query.order_by(Task.created_at.desc()).all()

    # Other roles
    else:
        flash("Unauthorized", "danger")
        return redirect(url_for("main.export_task_history"))

    # Build Excel data
    data = []
    for task in tasks:
        data.append({
            "Task ID": task.id,
            "Title": task.title,
            "Description": task.description,
            "Priority": task.priority,
            "Status": task.status,
            "Deleted": "Yes" if task.is_deleted else "No",
            "Assigned To": task.assignee.username if task.assignee else "-",
            "Assigned By": task.creator.username if task.creator else "-",
            "Department": task.assignee.department.name if task.assignee and task.assignee.department else "-",
            "Reward Points": task.reward_points or 0,
            "Work Status": task.work_status or "-",
            "Start Time": task.start_time.strftime("%Y-%m-%d %H:%M:%S") if task.start_time else "-",
            "End Time": task.end_time.strftime("%Y-%m-%d %H:%M:%S") if task.end_time else "-",
            "Total Time Spent (sec)": task.total_time_spent or 0,
            "Created At": task.created_at.strftime("%Y-%m-%d %H:%M:%S") if task.created_at else "-",
            "Completed At": task.completed_at.strftime("%Y-%m-%d %H:%M:%S") if task.completed_at else "-",
            "Due Date": task.due_date.strftime("%Y-%m-%d %H:%M:%S") if task.due_date else "-",
            "Remarks": task.remarks or "-",
            "Proof File": task.proof_file or "-"
        })

    df = pd.DataFrame(data)

    # Write to Excel in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Task History")
    output.seek(0)

    # Send Excel file
    return send_file(
        output,
        as_attachment=True,
        download_name="task_history.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
@bp.route("/task/reject/<int:id>", methods=["POST"])
@login_required
def reject_task(id):
    if current_user.role not in ["admin", "manager"]:
        return "Unauthorized"

    task = Task.query.get_or_404(id)
    remarks = request.form.get("remarks")
    task.status = "Rejected"
    task.remarks = remarks
    db.session.commit()
    flash("Task rejected with remarks", "warning")
    return redirect(url_for("main.manager_panel"))


@bp.route("/productivity")
@login_required
def productivity():
    if current_user.role != "admin":
        return "Unauthorized"

    employees = User.query.filter(User.role != "admin").all()
    stats = []
    for emp in employees:
        total = Task.query.filter_by(assigned_to=emp.id).count()
        completed = Task.query.filter_by(assigned_to=emp.id, status="Approved").count()
        stats.append({"employee": emp.username, "total": total, "completed": completed})

    return render_template("productivity.html", stats=stats)





@bp.route("/resubmit-task/<int:id>", methods=["POST"])
@login_required
def resubmit_task(id):

    if current_user.role != "employee":
        return "Unauthorized"

    task = Task.query.get_or_404(id)

    if task.status != "Rejected":
        return redirect(url_for("main.employee_panel"))

    file = request.files.get("proof_file")

    if file and file.filename != "":

        upload_folder = current_app.config["UPLOAD_FOLDER"]

        # 🔥 DELETE OLD PROOF FILE
        if task.proof_file:
            old_path = os.path.join(upload_folder, task.proof_file)
            if os.path.exists(old_path):
                os.remove(old_path)

        # 🔥 SAVE NEW FILE
        filename = secure_filename(file.filename)
        new_path = os.path.join(upload_folder, filename)
        file.save(new_path)

        task.proof_file = filename

    # Update task status
    task.status = "Submitted"
    task.remarks = None

    db.session.commit()

    flash("Task resubmitted successfully!", "success")

    return redirect(url_for("main.employee_panel"))



@bp.route("/download_attachment/<filename>")
@login_required
def download_attachment(filename):
    return send_from_directory(
        current_app.config['UPLOAD_FOLDER'],
        filename,
        as_attachment=True
    )




# START WORK
@bp.route("/task/start/<int:id>")
@login_required
def start_task(id):
    task = Task.query.get_or_404(id)

    if current_user.role != "employee" or task.assigned_to != current_user.id:
        flash("Unauthorized", "danger")
        return redirect(url_for("main.employee_panel"))

    # Stop only if task is not already running
    if task.work_status != "Started":
        task.work_status = "Started"
        task.start_time = datetime.now()
        task.end_time = None
        task.is_timer_running = True
        db.session.commit()
        flash("Work Started!", "success")

    return redirect(url_for("main.employee_panel"))


# STOP WORK
@bp.route("/task/stop/<int:id>")
@login_required
def stop_task(id):
    task = Task.query.get_or_404(id)

    if current_user.role != "employee" or task.assigned_to != current_user.id:
        flash("Unauthorized", "danger")
        return redirect(url_for("main.employee_panel"))

    if task.work_status == "Started" and task.start_time:
        now = datetime.now()
        # calculate seconds worked
        elapsed = int((now - task.start_time).total_seconds())
        task.total_time_spent = (task.total_time_spent or 0) + elapsed

        # stop timer
        task.work_status = "Stopped"
        task.end_time = now
        task.start_time = None
        task.is_timer_running = False
        db.session.commit()

        flash(f"Work Stopped! Total seconds worked: {task.total_time_spent}", "warning")

    return redirect(url_for("main.employee_panel"))

# ---------------- LOGOUT ----------------
@bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("main.home"))