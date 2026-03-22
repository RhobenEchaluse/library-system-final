import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from datetime import datetime, timedelta

from flask_dance.contrib.google import make_google_blueprint, google

from oauthlib.oauth2.rfc6749.errors import TokenExpiredError

app = Flask(__name__)
app.secret_key = "supersecretkey"


# 🔗 MongoDB Connection
client = MongoClient("mongodb+srv://user1:Echaluse@cluster0.e9xpwkj.mongodb.net/?appName=Cluster0")
db = client["neu_library"]

users_col = db["users"]
logs_col = db["visitor_logs"]


# 🔐 Google OAuth Setup
import os

google_bp = make_google_blueprint(
    client_id = os.getenv("GOOGLE_CLIENT_ID"),
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET"),
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email"
    ],
     redirect_to="index"
)


app.register_blueprint(google_bp, url_prefix="/login")


# 🏠 HOME (Kiosk/User Page)
@app.route('/')
def index():
    if not google.authorized:
        return redirect(url_for("google.login"))

    # 🔥 GET USER INFO HERE (IMPORTANT)
    resp = google.get("/oauth2/v2/userinfo")
    info = resp.json()

    email = info["email"]
    name = info["name"]

    session["email"] = email
    session["name"] = name

    # 🔥 AUTO ASSIGN ROLE
    role = "admin" if email == "jcesperanza@neu.edu.ph" else "user"

    user = users_col.find_one({"email": email})

    if not user:
        admin_emails = [
            "rhoben.echaluse@neu.edu.ph",
            "rhobenechaluse2045@gmail.com"
        ]

        role = "admin" if email in admin_emails else "user"

        users_col.insert_one({
            "email": email,
            "name": name,
            "program": "Unknown",
            "college": "Unknown",
            "role": role,
            "is_employee": False,
            "is_blocked": False
        })
    else:
        users_col.update_one(
            {"email": email},
            {"$set": {"role": role}}
        )

    return render_template("templates.html")




# 🔐 LOGIN HANDLER
@app.route('/login_success')
def login_success():
    if not google.authorized:
        return redirect(url_for("google.login"))

    resp = google.get("/oauth2/v2/userinfo")
    info = resp.json()

    email = info["email"]
    name = info["name"]

    session["email"] = email
    session["name"] = name

    # 🔥 AUTO ASSIGN ROLE
    role = "admin" if email == "jcesperanza@neu.edu.ph" else "user"

    user = users_col.find_one({"email": email})

    if not user:
        users_col.insert_one({
            "email": email,
            "name": name,
            "program": "Unknown",
            "college": "Unknown",
            "role": role,
            "is_employee": False,
            "is_blocked": False
        })
    else:
        users_col.update_one(
            {"email": email},
            {"$set": {"role": role}}
        )

    return redirect('/')


# 🚪 LOG VISIT
@app.route('/log_visit', methods=['POST'])
def log_visit():
    if "email" not in session:
        return jsonify({"status": "error", "message": "Not logged in"})

    email = session["email"]
    reason = request.form['reason']

    user = users_col.find_one({"email": email})

    if user.get("is_blocked"):
        return jsonify({"status": "error", "message": "Access denied"})

    log = {
        "email": email,
        "name": user["name"],
        "program": user["program"],
        "college": user.get("college", "Unknown"),
        "reason": reason,
        "is_employee": user.get("is_employee", False),
        "visit_date": datetime.now()
    }

    logs_col.insert_one(log)

    return jsonify({
        "status": "success",
        "name": user["name"],
        "program": user["program"]
    })


# 📊 ADMIN DASHBOARD
from datetime import datetime, timedelta

@app.route('/admin')
def admin():
    if "email" not in session:
        return redirect(url_for("google.login"))

    user = users_col.find_one({"email": session["email"]})

    if user["role"] != "admin":
        return "Access Denied ❌"

    # FILTERS
    reason = request.args.get("reason")
    college = request.args.get("college")
    is_employee = request.args.get("is_employee")
    start = request.args.get("start")
    end = request.args.get("end")

    query = {}

    if reason:
        query["reason"] = reason

    if college:
        query["college"] = college

    if is_employee:
        query["is_employee"] = True if is_employee == "true" else False

    if start and end:
        query["visit_date"] = {
            "$gte": datetime.strptime(start, "%Y-%m-%d"),
            "$lte": datetime.strptime(end, "%Y-%m-%d")
        }

    logs = list(logs_col.find(query).sort("visit_date", -1))

    # 📊 STATS
    today = datetime.now()
    start_day = datetime(today.year, today.month, today.day)

    daily_count = logs_col.count_documents({
        "visit_date": {"$gte": start_day}
    })

    weekly_count = logs_col.count_documents({
        "visit_date": {"$gte": today - timedelta(days=7)}
    })

    monthly_count = logs_col.count_documents({
        "visit_date": {"$gte": today - timedelta(days=30)}
    })

    return render_template(
        "admin.html",
        logs=logs,
        daily_count=daily_count,
        weekly_count=weekly_count,
        monthly_count=monthly_count
    )


# 🔄 SWITCH ROLE (OPTIONAL BONUS)
@app.route('/switch_role/<role>')
def switch_role(role):
    if "email" not in session:
        return redirect(url_for("google.login"))

    users_col.update_one(
        {"email": session["email"]},
        {"$set": {"role": role}}
    )

    return redirect('/')


# 🚪 LOGOUT
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)