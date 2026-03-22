import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask_dance.contrib.google import make_google_blueprint, google
from oauthlib.oauth2.rfc6749.errors import TokenExpiredError

# Force HTTPS on Render to satisfy Google's security requirements
if os.getenv("RENDER"):
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '0'
else:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "neu-library-secret-2024")

# 🔗 MongoDB Connection
MONGO_URI = "mongodb+srv://user1:Echaluse@cluster0.e9xpwkj.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["neu_library"]
users_col = db["users"]
logs_col = db["visitor_logs"]

# 🔐 Google OAuth Setup
# Fetching these directly ensures Render Environment Variables are used
client_id = os.getenv("GOOGLE_CLIENT_ID")
client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

google_bp = make_google_blueprint(
    client_id=client_id,
    client_secret=client_secret,
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email"
    ],
    redirect_to="index"
)
app.register_blueprint(google_bp, url_prefix="/login")


# 🏠 HOME PAGE
@app.route('/')
def index():
    if not google.authorized:
        return redirect(url_for("google.login"))

    try:
        resp = google.get("/oauth2/v2/userinfo")
        if not resp.ok:
            return "Could not fetch user info. Check your Google Console Credentials.", 400
        info = resp.json()
    except Exception:
        return redirect(url_for("google.login"))

    email = info["email"]
    name = info["name"]
    session["email"] = email
    session["name"] = name

    # Professor's specific account
    PROF_EMAIL = "jcesperanza@neu.edu.ph"

    # Check/Create User in DB
    user = users_col.find_one({"email": email})
    if not user:
        # Initial Role Assignment
        role = "admin" if email == PROF_EMAIL else "user"
        users_col.insert_one({
            "email": email,
            "name": name,
            "role": role,
            "college": "CICS",
            "is_employee": False
        })
        session["role"] = role
    else:
        session["role"] = user.get("role", "user")

    return render_template("templates.html", user_name=name, role=session["role"])


# 📊 ADMIN DASHBOARD
@app.route('/admin')
def admin():
    if "email" not in session:
        return redirect(url_for("google.login"))

    # Secure Authorization Check
    user = users_col.find_one({"email": session["email"]})
    if not user or user.get("role") != "admin":
        return "Access Denied. Admins only.", 403

    # Filters
    reason = request.args.get("reason")
    college = request.args.get("college")
    is_employee = request.args.get("is_employee")

    query = {}
    if reason: query["reason"] = reason
    if college: query["college"] = {"$regex": college, "$options": "i"}
    if is_employee: query["is_employee"] = (is_employee == "true")

    logs = list(logs_col.find(query).sort("visit_date", -1))

    # Statistics logic for the cards
    now = datetime.now()
    today_start = datetime(now.year, now.month, now.day)
    week_start = today_start - timedelta(days=now.weekday())

    daily_count = logs_col.count_documents({"visit_date": {"$gte": today_start}})
    weekly_count = logs_col.count_documents({"visit_date": {"$gte": week_start}})

    return render_template(
        "admin.html",
        logs=logs,
        daily_count=daily_count,
        weekly_count=weekly_count
    )


# 🔄 SECURE ROLE SWITCHING (Professor Requirement)
@app.route('/switch_role/<role>')
def switch_role(role):
    if "email" not in session: return redirect(url_for("google.login"))

    # Hardcoded security check for the professor's email
    if session["email"] != "jcesperanza@neu.edu.ph":
        return "Unauthorized to switch roles.", 403

    if role in ["admin", "user"]:
        users_col.update_one({"email": session["email"]}, {"$set": {"role": role}})
        session["role"] = role

    return redirect(url_for('admin' if role == "admin" else 'index'))


@app.route('/log_visit', methods=['POST'])
def log_visit():
    if "email" not in session: return jsonify({"status": "error"})

    user = users_col.find_one({"email": session["email"]})
    reason = request.form.get('reason', 'Reading')

    log_entry = {
        "email": session["email"],
        "name": session["name"],
        "college": user.get("college", "CICS"),
        "reason": reason,
        "is_employee": user.get("is_employee", False),
        "visit_date": datetime.now()
    }
    logs_col.insert_one(log_entry)
    return jsonify({"status": "success", "name": session["name"]})


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))