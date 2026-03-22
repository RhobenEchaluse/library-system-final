import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask_dance.contrib.google import make_google_blueprint, google
from oauthlib.oauth2.rfc6749.errors import TokenExpiredError

# Set this to '1' only for local development. Render provides HTTPS automatically.
if os.getenv("RENDER"):
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '0'
else:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key-123")

# 🔗 MongoDB Connection
# Note: Ensure your IP Whitelist in MongoDB Atlas includes 0.0.0.0/0 for Render
MONGO_URI = "mongodb+srv://user1:Echaluse@cluster0.e9xpwkj.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["neu_library"]
users_col = db["users"]
logs_col = db["visitor_logs"]

# 🔐 Google OAuth Setup
# IMPORTANT: Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Render Environment Variables
google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email"
    ],
    redirect_to="index"
)
app.register_blueprint(google_bp, url_prefix="/login")


# 🏠 HOME / KIOSK PAGE
@app.route('/')
def index():
    if not google.authorized:
        return redirect(url_for("google.login"))

    try:
        resp = google.get("/oauth2/v2/userinfo")
        if not resp.ok:
            return "Failed to fetch user info from Google.", 400
        info = resp.json()
    except TokenExpiredError:
        return redirect(url_for("google.login"))

    email = info["email"]
    name = info["name"]
    session["email"] = email
    session["name"] = name

    # Check if user exists in DB
    user = users_col.find_one({"email": email})

    if not user:
        # Default role assignment
        role = "admin" if email == "jcesperanza@neu.edu.ph" else "user"
        users_col.insert_one({
            "email": email,
            "name": name,
            "program": "Unknown",
            "college": "Unknown",
            "role": role,
            "is_employee": False,
            "is_blocked": False
        })
        session["role"] = role
    else:
        # Ensure the professor is always recognized as admin if they haven't switched roles
        session["role"] = user.get("role", "user")

    return render_template("templates.html", user_name=name, role=session.get("role"))


# 📊 ADMIN DASHBOARD
@app.route('/admin')
def admin():
    if "email" not in session:
        return redirect(url_for("google.login"))

    user = users_col.find_one({"email": session["email"]})

    # Secure Authorization
    if not user or user.get("role") != "admin":
        return "Access Denied: Admin privileges required. ❌", 403

    # FILTERS from request arguments
    reason = request.args.get("reason")
    college = request.args.get("college")
    is_employee = request.args.get("is_employee")
    start = request.args.get("start")
    end = request.args.get("end")

    query = {}
    if reason: query["reason"] = reason
    if college: query["college"] = {"$regex": college, "$options": "i"}  # Case-insensitive search
    if is_employee: query["is_employee"] = (is_employee == "true")

    # Date Range Filter
    if start and end:
        query["visit_date"] = {
            "$gte": datetime.strptime(start, "%Y-%m-%d"),
            "$lte": datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
        }

    logs = list(logs_col.find(query).sort("visit_date", -1))

    # 📊 STATISTICS FOR CARDS
    today = datetime.now()
    start_of_today = datetime(today.year, today.month, today.day)
    start_of_week = start_of_today - timedelta(days=today.weekday())

    stats = {
        "daily": logs_col.count_documents({"visit_date": {"$gte": start_of_today}}),
        "weekly": logs_col.count_documents({"visit_date": {"$gte": start_of_week}}),
        "filtered": len(logs)  # Count for the "chosen date range"
    }

    return render_template(
        "admin.html",
        logs=logs,
        daily_count=stats["daily"],
        weekly_count=stats["weekly"],
        range_count=stats["filtered"]
    )


# 🔄 SECURE ROLE SWITCHING
@app.route('/switch_role/<role>')
def switch_role(role):
    if "email" not in session:
        return redirect(url_for("google.login"))

    # Only allow the professor's email to switch roles
    professor_email = "jcesperanza@neu.edu.ph"
    if session["email"] != professor_email:
        return "Unauthorized: You do not have permission to change roles. ❌", 403

    if role not in ["admin", "user"]:
        return "Invalid role", 400

    # Update database and session
    users_col.update_one({"email": session["email"]}, {"$set": {"role": role}})
    session["role"] = role

    return redirect(url_for('admin' if role == "admin" else 'index'))


# 🚪 LOG VISIT
@app.route('/log_visit', methods=['POST'])
def log_visit():
    if "email" not in session:
        return jsonify({"status": "error", "message": "Please login first"})

    email = session["email"]
    reason = request.form.get('reason', 'General Visit')

    user = users_col.find_one({"email": email})
    if not user:
        return jsonify({"status": "error", "message": "User not found"})

    if user.get("is_blocked"):
        return jsonify({"status": "error", "message": "Your access is blocked."})

    # Record the log
    log_entry = {
        "email": email,
        "name": user["name"],
        "college": user.get("college", "CICS"),
        "reason": reason,
        "is_employee": user.get("is_employee", False),
        "visit_date": datetime.now()
    }
    logs_col.insert_one(log_entry)

    return jsonify({
        "status": "success",
        "name": user["name"],
        "program": user.get("program", "Student")
    })


# 🚪 LOGOUT
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)