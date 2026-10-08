import os
import json
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

from app import (
    users,
    files,
    ask_ollama,
    security_check,
    calculate_risk,
    get_user_by_email,
)


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

SESSION_SECRET = os.getenv(
    "SESSION_SECRET",
    "aegisai-demo-secret-2026"
)


# =========================================================
# APP
# =========================================================

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET
)

templates = Jinja2Templates(
    directory="templates"
)


# =========================================================
# LOCAL FALLBACK FILES
# =========================================================

RESTRICTIONS_FILE = Path(
    "user_restrictions.json"
)

AUDIT_FILE = Path(
    "audit_log.json"
)


# =========================================================
# HATOON EMPLOYEE
# =========================================================

if "u36" not in users:

    users["u36"] = {
        "name": "Hatoon",
        "role": "Cybersecurity",
        "title": "Security Analyst",
        "clearance": 3,
        "email": "hatoon@company.com"
    }


if "u37" not in users:

    users["u37"] = {
        "name": "Jumana",
        "role": "Cybersecurity",
        "title": "Security Analyst",
        "clearance": 3,
        "email": "jumana@company.com"
    }


# =========================================================
# MANAGERS
# =========================================================

MANAGERS = {

    "nasser": {
        "id": "admin01",
        "name": "Nasser",
        "title": "Security Manager",
        "role": "Cybersecurity",
        "clearance": 5,
        "account_type": "manager"
    },

    "hatoon1": {
        "id": "admin02",
        "name": "Hatoon1",
        "title": "Security Manager",
        "role": "Cybersecurity",
        "clearance": 5,
        "account_type": "manager"
    },

    "jumana1": {
        "id": "admin03",
        "name": "Jumana1",
        "title": "Security Manager",
        "role": "Cybersecurity",
        "clearance": 5,
        "account_type": "manager"
    }

}


# =========================================================
# DATABASE
# =========================================================

def database_enabled():

    return bool(
        DATABASE_URL
    )


def get_db():

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=15
    )


# =========================================================
# LOCAL JSON HELPERS
# =========================================================

def ensure_json_file(
    path,
    default_value
):

    if not path.exists():

        path.write_text(
            json.dumps(
                default_value,
                indent=4
            ),
            encoding="utf-8"
        )


def load_json(
    path,
    default_value
):

    ensure_json_file(
        path,
        default_value
    )

    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return default_value


def save_json(
    path,
    data
):

    path.write_text(
        json.dumps(
            data,
            indent=4
        ),
        encoding="utf-8"
    )


ensure_json_file(
    RESTRICTIONS_FILE,
    {}
)

ensure_json_file(
    AUDIT_FILE,
    []
)


# =========================================================
# USER HELPERS
# =========================================================

def find_user_by_name(
    name: str
):

    name = name.strip().lower()

    for user_id, user in users.items():

        if (
            user["name"]
            .strip()
            .lower()
            == name
        ):

            result = user.copy()

            result["id"] = user_id

            return result

    return None


def get_logged_user(
    request: Request
):

    user_id = request.session.get(
        "user_id"
    )

    if not user_id:

        return None

    if user_id not in users:

        return None

    user = users[user_id].copy()

    user["id"] = user_id

    return user


# =========================================================
# MANAGER HELPERS
# =========================================================

def find_manager_by_name(
    name: str
):

    return MANAGERS.get(
        name.strip().lower()
    )


def get_logged_manager(
    request: Request
):

    manager_id = request.session.get(
        "manager_id"
    )

    if not manager_id:

        return None

    for manager in MANAGERS.values():

        if (
            manager["id"]
            == manager_id
        ):

            return manager.copy()

    return None


# =========================================================
# RESTRICTIONS
# =========================================================

def default_restriction():

    return {
        "send_blocked": False,
        "all_blocked": False,
        "reason": "",
        "restricted_by": "",
        "timestamp": ""
    }


def get_restriction(
    user_id
):

    if database_enabled():

        try:

            with get_db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        SELECT
                            user_id,
                            send_blocked,
                            all_blocked,
                            reason,
                            restricted_by,
                            timestamp
                        FROM public.user_restrictions
                        WHERE user_id = %s
                        """,
                        (
                            user_id,
                        )
                    )

                    row = cur.fetchone()

            if not row:

                return default_restriction()

            return {

                "send_blocked":
                    row["send_blocked"],

                "all_blocked":
                    row["all_blocked"],

                "reason":
                    row["reason"] or "",

                "restricted_by":
                    row["restricted_by"] or "",

                "timestamp":
                    (
                        row["timestamp"].isoformat()
                        if row["timestamp"]
                        else ""
                    )
            }

        except Exception as error:

            print(
                "DATABASE GET RESTRICTION ERROR:",
                error
            )

            return default_restriction()


    restrictions = load_json(
        RESTRICTIONS_FILE,
        {}
    )

    return restrictions.get(
        user_id,
        default_restriction()
    )


def save_restriction(
    user_id,
    send_blocked=False,
    all_blocked=False,
    reason="",
    restricted_by=""
):

    if database_enabled():

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO public.user_restrictions
                    (
                        user_id,
                        send_blocked,
                        all_blocked,
                        reason,
                        restricted_by,
                        timestamp
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        NOW()
                    )

                    ON CONFLICT (user_id)

                    DO UPDATE SET

                        send_blocked =
                            EXCLUDED.send_blocked,

                        all_blocked =
                            EXCLUDED.all_blocked,

                        reason =
                            EXCLUDED.reason,

                        restricted_by =
                            EXCLUDED.restricted_by,

                        timestamp =
                            NOW()
                    """,
                    (
                        user_id,
                        send_blocked,
                        all_blocked,
                        reason,
                        restricted_by
                    )
                )

            conn.commit()

        return


    restrictions = load_json(
        RESTRICTIONS_FILE,
        {}
    )

    restrictions[user_id] = {

        "send_blocked":
            send_blocked,

        "all_blocked":
            all_blocked,

        "reason":
            reason,

        "restricted_by":
            restricted_by,

        "timestamp":
            datetime.now().isoformat(
                timespec="seconds"
            )
    }

    save_json(
        RESTRICTIONS_FILE,
        restrictions
    )


def restore_restriction(
    user_id
):

    if database_enabled():

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    DELETE FROM public.user_restrictions
                    WHERE user_id = %s
                    """,
                    (
                        user_id,
                    )
                )

            conn.commit()

        return


    restrictions = load_json(
        RESTRICTIONS_FILE,
        {}
    )

    restrictions.pop(
        user_id,
        None
    )

    save_json(
        RESTRICTIONS_FILE,
        restrictions
    )


def get_all_restrictions():

    if database_enabled():

        try:

            with get_db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        SELECT
                            user_id,
                            send_blocked,
                            all_blocked,
                            reason,
                            restricted_by,
                            timestamp
                        FROM public.user_restrictions
                        """
                    )

                    rows = cur.fetchall()

            result = {}

            for row in rows:

                result[
                    row["user_id"]
                ] = {

                    "send_blocked":
                        row["send_blocked"],

                    "all_blocked":
                        row["all_blocked"],

                    "reason":
                        row["reason"] or "",

                    "restricted_by":
                        row["restricted_by"] or "",

                    "timestamp":
                        (
                            row["timestamp"].isoformat()
                            if row["timestamp"]
                            else ""
                        )
                }

            return result

        except Exception as error:

            print(
                "DATABASE GET ALL RESTRICTIONS ERROR:",
                error
            )

            return {}

    return load_json(
        RESTRICTIONS_FILE,
        {}
    )


# =========================================================
# REVIEW ENGINE
# =========================================================

def requires_review(
    decision,
    risk_score
):

    if decision != "ALLOW":

        return False

    return risk_score >= 50


def create_review_request(
    user,
    user_request,
    action,
    file_name,
    recipient_email,
    risk_score,
    risk_level,
    risk_reasons
):

    if not database_enabled():

        raise RuntimeError(
            "Review workflow requires DATABASE_URL."
        )


    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO public.review_requests
                (
                    user_id,
                    username,
                    department,
                    title,
                    clearance,
                    request,
                    action,
                    file_name,
                    recipient,
                    risk_score,
                    risk_level,
                    risk_reasons,
                    status
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'PENDING'
                )
                RETURNING id
                """,
                (
                    user["id"],
                    user["name"],
                    user["role"],
                    user["title"],
                    user["clearance"],
                    user_request,
                    action,
                    file_name,
                    recipient_email,
                    risk_score,
                    risk_level,
                    Jsonb(
                        risk_reasons or []
                    )
                )
            )

            row = cur.fetchone()

        conn.commit()


    return row["id"]


def get_review_requests():

    if not database_enabled():

        return []


    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        created_at,
                        updated_at,
                        user_id,
                        username,
                        department,
                        title,
                        clearance,
                        request,
                        action,
                        file_name,
                        recipient,
                        risk_score,
                        risk_level,
                        risk_reasons,
                        status,
                        reviewed_by,
                        reviewer_reason,
                        reviewed_at
                    FROM public.review_requests
                    ORDER BY
                        CASE
                            WHEN status = 'PENDING'
                            THEN 0
                            ELSE 1
                        END,
                        created_at DESC
                    LIMIT 500
                    """
                )

                rows = cur.fetchall()


        reviews = []


        for row in rows:

            reviews.append(
                {
                    "id":
                        row["id"],

                    "created_at":
                        (
                            row["created_at"].isoformat()
                            if row["created_at"]
                            else None
                        ),

                    "updated_at":
                        (
                            row["updated_at"].isoformat()
                            if row["updated_at"]
                            else None
                        ),

                    "user_id":
                        row["user_id"],

                    "username":
                        row["username"],

                    "department":
                        row["department"],

                    "title":
                        row["title"],

                    "clearance":
                        row["clearance"],

                    "request":
                        row["request"],

                    "action":
                        row["action"],

                    "file":
                        row["file_name"],

                    "recipient":
                        row["recipient"],

                    "risk_score":
                        row["risk_score"],

                    "risk_level":
                        row["risk_level"],

                    "risk_reasons":
                        row["risk_reasons"] or [],

                    "status":
                        row["status"],

                    "reviewed_by":
                        row["reviewed_by"],

                    "reviewer_reason":
                        row["reviewer_reason"],

                    "reviewed_at":
                        (
                            row["reviewed_at"].isoformat()
                            if row["reviewed_at"]
                            else None
                        )
                }
            )


        return reviews


    except Exception as error:

        print(
            "DATABASE GET REVIEWS ERROR:",
            error
        )

        return []


def update_review_status(
    review_id,
    new_status,
    manager_name,
    reason=""
):

    if new_status not in [
        "APPROVED",
        "DENIED"
    ]:

        raise ValueError(
            "Invalid review status."
        )


    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    status,
                    username,
                    action,
                    file_name,
                    recipient
                FROM public.review_requests
                WHERE id = %s
                FOR UPDATE
                """,
                (
                    review_id,
                )
            )

            review = cur.fetchone()


            if not review:

                raise ValueError(
                    "Review request not found."
                )


            if review["status"] != "PENDING":

                raise ValueError(
                    "This request has already been reviewed."
                )


            cur.execute(
                """
                UPDATE public.review_requests
                SET
                    status = %s,
                    reviewed_by = %s,
                    reviewer_reason = %s,
                    reviewed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    new_status,
                    manager_name,
                    reason,
                    review_id
                )
            )

        conn.commit()


    return review


# =========================================================
# AUDIT
# =========================================================

def save_security_audit(
    user,
    user_request,
    action,
    file_name,
    recipient_email,
    decision,
    reason,
    risk_score,
    risk_level,
    risk_reasons
):

    if database_enabled():

        try:

            with get_db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        INSERT INTO public.audit_logs
                        (
                            type,
                            username,
                            department,
                            title,
                            clearance,
                            request,
                            action,
                            file_name,
                            recipient,
                            decision,
                            reason,
                            risk_score,
                            risk_level,
                            risk_reasons
                        )
                        VALUES
                        (
                            'SECURITY_EVENT',
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        """,
                        (
                            user.get("name"),
                            user.get("role"),
                            user.get("title"),
                            user.get("clearance"),
                            user_request,
                            action,
                            file_name,
                            recipient_email,
                            decision,
                            reason,
                            risk_score,
                            risk_level,
                            Jsonb(
                                risk_reasons or []
                            )
                        )
                    )

                conn.commit()

            return

        except Exception as error:

            print(
                "DATABASE AUDIT ERROR:",
                error
            )


    logs = load_json(
        AUDIT_FILE,
        []
    )

    logs.append(
        {
            "timestamp":
                datetime.now().isoformat(
                    timespec="seconds"
                ),

            "type":
                "SECURITY_EVENT",

            "user":
                user.get("name"),

            "department":
                user.get("role"),

            "title":
                user.get("title"),

            "clearance":
                user.get("clearance"),

            "request":
                user_request,

            "action":
                action,

            "file":
                file_name,

            "recipient":
                recipient_email,

            "decision":
                decision,

            "reason":
                reason,

            "risk_score":
                risk_score,

            "risk_level":
                risk_level,

            "risk_reasons":
                risk_reasons or []
        }
    )

    save_json(
        AUDIT_FILE,
        logs
    )


def save_manager_audit(
    manager_name,
    action,
    target_user=None,
    reason=""
):

    if database_enabled():

        try:

            with get_db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        INSERT INTO public.audit_logs
                        (
                            type,
                            username,
                            department,
                            title,
                            action,
                            target_user,
                            decision,
                            reason,
                            risk_score,
                            risk_level,
                            risk_reasons
                        )
                        VALUES
                        (
                            'MANAGER_ACTION',
                            %s,
                            'Cybersecurity',
                            'Security Manager',
                            %s,
                            %s,
                            'ADMIN',
                            %s,
                            0,
                            'ADMIN',
                            '[]'::jsonb
                        )
                        """,
                        (
                            manager_name,
                            action,
                            target_user,
                            reason
                        )
                    )

                conn.commit()

            return

        except Exception as error:

            print(
                "DATABASE MANAGER AUDIT ERROR:",
                error
            )


    logs = load_json(
        AUDIT_FILE,
        []
    )

    logs.append(
        {
            "timestamp":
                datetime.now().isoformat(
                    timespec="seconds"
                ),

            "type":
                "MANAGER_ACTION",

            "user":
                manager_name,

            "department":
                "Cybersecurity",

            "title":
                "Security Manager",

            "action":
                action,

            "target_user":
                target_user,

            "reason":
                reason,

            "decision":
                "ADMIN",

            "risk_score":
                0,

            "risk_level":
                "ADMIN",

            "risk_reasons":
                []
        }
    )

    save_json(
        AUDIT_FILE,
        logs
    )


def get_audit_logs():

    if database_enabled():

        try:

            with get_db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        SELECT
                            id,
                            timestamp,
                            type,
                            username,
                            department,
                            title,
                            clearance,
                            request,
                            action,
                            file_name,
                            recipient,
                            decision,
                            reason,
                            risk_score,
                            risk_level,
                            risk_reasons,
                            target_user
                        FROM public.audit_logs
                        ORDER BY timestamp DESC
                        LIMIT 1000
                        """
                    )

                    rows = cur.fetchall()


            logs = []


            for row in rows:

                logs.append(
                    {
                        "id":
                            row["id"],

                        "timestamp":
                            (
                                row["timestamp"].isoformat()
                                if row["timestamp"]
                                else None
                            ),

                        "type":
                            row["type"],

                        "user":
                            row["username"],

                        "department":
                            row["department"],

                        "title":
                            row["title"],

                        "clearance":
                            row["clearance"],

                        "request":
                            row["request"],

                        "action":
                            row["action"],

                        "file":
                            row["file_name"],

                        "recipient":
                            row["recipient"],

                        "decision":
                            row["decision"],

                        "reason":
                            row["reason"],

                        "risk_score":
                            row["risk_score"],

                        "risk_level":
                            row["risk_level"],

                        "risk_reasons":
                            row["risk_reasons"] or [],

                        "target_user":
                            row["target_user"]
                    }
                )


            return logs


        except Exception as error:

            print(
                "DATABASE GET AUDIT ERROR:",
                error
            )

            return []


    logs = load_json(
        AUDIT_FILE,
        []
    )

    return list(
        reversed(
            logs
        )
    )


# =========================================================
# LOGIN PAGE
# =========================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
async def login_page(
    request: Request
):

    account_type = request.session.get(
        "account_type"
    )

    if account_type == "employee":

        return RedirectResponse(
            "/employee",
            status_code=303
        )

    if account_type == "manager":

        return RedirectResponse(
            "/manager",
            status_code=303
        )


    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": None
        }
    )


# =========================================================
# EMPLOYEE LOGIN
# =========================================================

@app.post(
    "/login/employee"
)
async def employee_login(
    request: Request,
    name: str = Form(...)
):

    user = find_user_by_name(
        name
    )

    if not user:

        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error":
                    "Employee not found."
            }
        )


    request.session.clear()

    request.session[
        "account_type"
    ] = "employee"

    request.session[
        "user_id"
    ] = user["id"]


    return RedirectResponse(
        "/employee",
        status_code=303
    )


# =========================================================
# MANAGER LOGIN
# =========================================================

@app.post(
    "/login/manager"
)
async def manager_login(
    request: Request,
    name: str = Form(...)
):

    manager = find_manager_by_name(
        name
    )

    if not manager:

        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error":
                    "Manager account not found."
            }
        )


    request.session.clear()

    request.session[
        "account_type"
    ] = "manager"

    request.session[
        "manager_id"
    ] = manager["id"]

    request.session[
        "manager_name"
    ] = manager["name"]


    return RedirectResponse(
        "/manager",
        status_code=303
    )


# =========================================================
# LOGOUT
# =========================================================

@app.get(
    "/logout"
)
async def logout(
    request: Request
):

    request.session.clear()

    return RedirectResponse(
        "/",
        status_code=303
    )


# =========================================================
# EMPLOYEE PAGE
# =========================================================

@app.get(
    "/employee",
    response_class=HTMLResponse
)
async def employee_page(
    request: Request
):

    if (
        request.session.get(
            "account_type"
        )
        != "employee"
    ):

        return RedirectResponse(
            "/",
            status_code=303
        )


    user = get_logged_user(
        request
    )

    if not user:

        request.session.clear()

        return RedirectResponse(
            "/",
            status_code=303
        )


    department_files = {}


    for (
        file_name,
        file_info
    ) in files.items():

        if (
            file_info["department"]
            == user["role"]
        ):

            department_files[
                file_name
            ] = file_info


    restriction = get_restriction(
        user["id"]
    )


    return templates.TemplateResponse(
        request=request,
        name="employee.html",
        context={
            "user":
                user,

            "files":
                department_files,

            "all_users":
                users,

            "restriction":
                restriction
        }
    )


# =========================================================
# MANAGER PAGE
# =========================================================

@app.get(
    "/manager",
    response_class=HTMLResponse
)
async def manager_page(
    request: Request
):

    manager = get_logged_manager(
        request
    )

    if not manager:

        request.session.clear()

        return RedirectResponse(
            "/",
            status_code=303
        )


    restrictions = get_all_restrictions()

    employees = []


    for (
        user_id,
        user
    ) in users.items():

        employee = user.copy()

        employee["id"] = user_id

        employee[
            "restriction"
        ] = restrictions.get(
            user_id,
            {}
        )

        employees.append(
            employee
        )


    return templates.TemplateResponse(
        request=request,
        name="manager.html",
        context={
            "manager":
                manager,

            "employees":
                employees
        }
    )


# =========================================================
# MANAGER RESTRICTIONS
# =========================================================

@app.post(
    "/api/manager/restrict-send"
)
async def restrict_send(
    request: Request,
    user_id: str = Form(...),
    reason: str = Form("")
):

    manager = get_logged_manager(
        request
    )

    if not manager:

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    if user_id not in users:

        return JSONResponse(
            {
                "error":
                    "Employee not found"
            },
            status_code=404
        )


    try:

        save_restriction(
            user_id=user_id,
            send_blocked=True,
            all_blocked=False,
            reason=reason,
            restricted_by=manager["name"]
        )


        save_manager_audit(
            manager["name"],
            "SUSPEND_SEND",
            users[user_id]["name"],
            reason
        )


    except Exception as error:

        return JSONResponse(
            {
                "error":
                    str(error)
            },
            status_code=500
        )


    return {
        "success": True
    }


@app.post(
    "/api/manager/restrict-all"
)
async def restrict_all(
    request: Request,
    user_id: str = Form(...),
    reason: str = Form("")
):

    manager = get_logged_manager(
        request
    )

    if not manager:

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    if user_id not in users:

        return JSONResponse(
            {
                "error":
                    "Employee not found"
            },
            status_code=404
        )


    try:

        save_restriction(
            user_id=user_id,
            send_blocked=True,
            all_blocked=True,
            reason=reason,
            restricted_by=manager["name"]
        )


        save_manager_audit(
            manager["name"],
            "SUSPEND_ALL_ACCESS",
            users[user_id]["name"],
            reason
        )


    except Exception as error:

        return JSONResponse(
            {
                "error":
                    str(error)
            },
            status_code=500
        )


    return {
        "success": True
    }


@app.post(
    "/api/manager/restore"
)
async def restore_user(
    request: Request,
    user_id: str = Form(...)
):

    manager = get_logged_manager(
        request
    )

    if not manager:

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    if user_id not in users:

        return JSONResponse(
            {
                "error":
                    "Employee not found"
            },
            status_code=404
        )


    try:

        restore_restriction(
            user_id
        )


        save_manager_audit(
            manager["name"],
            "RESTORE_ACCESS",
            users[user_id]["name"],
            "Access restored"
        )


    except Exception as error:

        return JSONResponse(
            {
                "error":
                    str(error)
            },
            status_code=500
        )


    return {
        "success": True
    }


# =========================================================
# MANAGER AUDIT
# =========================================================

@app.get(
    "/api/manager/audit"
)
async def manager_audit(
    request: Request
):

    manager = get_logged_manager(
        request
    )

    if not manager:

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    return {
        "logs":
            get_audit_logs()
    }


# =========================================================
# MANAGER REVIEWS
# =========================================================

@app.get(
    "/api/manager/reviews"
)
async def manager_reviews(
    request: Request
):

    manager = get_logged_manager(
        request
    )

    if not manager:

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    return {
        "reviews":
            get_review_requests()
    }


@app.post(
    "/api/manager/reviews/approve"
)
async def approve_review(
    request: Request,
    review_id: int = Form(...),
    reason: str = Form("")
):

    manager = get_logged_manager(
        request
    )

    if not manager:

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    try:

        review = update_review_status(
            review_id,
            "APPROVED",
            manager["name"],
            reason
        )


        save_manager_audit(
            manager["name"],
            "APPROVE_REVIEW",
            review["username"],
            (
                f"Review #{review_id}. "
                + (
                    reason
                    if reason
                    else "Approved"
                )
            )
        )


        return {
            "success": True,
            "status": "APPROVED"
        }


    except Exception as error:

        return JSONResponse(
            {
                "error":
                    str(error)
            },
            status_code=400
        )


@app.post(
    "/api/manager/reviews/deny"
)
async def deny_review(
    request: Request,
    review_id: int = Form(...),
    reason: str = Form("")
):

    manager = get_logged_manager(
        request
    )

    if not manager:

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    try:

        review = update_review_status(
            review_id,
            "DENIED",
            manager["name"],
            reason
        )


        save_manager_audit(
            manager["name"],
            "DENY_REVIEW",
            review["username"],
            (
                f"Review #{review_id}. "
                + (
                    reason
                    if reason
                    else "Denied"
                )
            )
        )


        return {
            "success": True,
            "status": "DENIED"
        }


    except Exception as error:

        return JSONResponse(
            {
                "error":
                    str(error)
            },
            status_code=400
        )


# =========================================================
# EMPLOYEE REVIEW STATUS
# =========================================================

@app.get(
    "/api/review-status/{review_id}"
)
async def employee_review_status(
    review_id: int,
    request: Request
):

    if (
        request.session.get(
            "account_type"
        )
        != "employee"
    ):

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    user = get_logged_user(
        request
    )

    if not user:

        return JSONResponse(
            {
                "error":
                    "User session not found"
            },
            status_code=401
        )


    if not database_enabled():

        return JSONResponse(
            {
                "error":
                    "Review database is unavailable"
            },
            status_code=503
        )


    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        status,
                        reviewed_by,
                        reviewer_reason,
                        reviewed_at
                    FROM public.review_requests
                    WHERE
                        id = %s
                        AND user_id = %s
                    """,
                    (
                        review_id,
                        user["id"]
                    )
                )

                review = cur.fetchone()


        if not review:

            return JSONResponse(
                {
                    "error":
                        "Review request not found"
                },
                status_code=404
            )


        return {

            "id":
                review["id"],

            "status":
                review["status"],

            "reviewed_by":
                review["reviewed_by"],

            "reviewer_reason":
                review["reviewer_reason"],

            "reviewed_at":
                (
                    review["reviewed_at"].isoformat()
                    if review["reviewed_at"]
                    else None
                )
        }


    except Exception as error:

        print(
            "REVIEW STATUS ERROR:",
            error
        )

        return JSONResponse(
            {
                "error":
                    str(error)
            },
            status_code=500
        )


# =========================================================
# EMPLOYEE HISTORY
# =========================================================

def get_employee_history(
    user,
    limit=500
):

    if database_enabled():

        try:

            with get_db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        SELECT
                            id,
                            timestamp,
                            request,
                            action,
                            file_name,
                            recipient,
                            decision,
                            reason,
                            risk_score,
                            risk_level,
                            risk_reasons
                        FROM public.audit_logs
                        WHERE
                            type = 'SECURITY_EVENT'
                            AND username = %s
                        ORDER BY timestamp DESC
                        LIMIT %s
                        """,
                        (
                            user["name"],
                            limit
                        )
                    )

                    audit_rows = cur.fetchall()

                    cur.execute(
                        """
                        SELECT
                            id,
                            created_at,
                            request,
                            action,
                            file_name,
                            recipient,
                            risk_score,
                            status,
                            reviewed_by,
                            reviewer_reason,
                            reviewed_at
                        FROM public.review_requests
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                        LIMIT 500
                        """,
                        (
                            user["id"],
                        )
                    )

                    review_rows = cur.fetchall()


            used_review_ids = set()
            history = []


            def normalized(value):

                if value is None:
                    return ""

                return str(value).strip().lower()


            for row in audit_rows:

                review_match = None

                if (
                    str(
                        row["decision"]
                        or ""
                    ).upper()
                    == "REVIEW"
                ):

                    candidates = []

                    for review in review_rows:

                        if review["id"] in used_review_ids:
                            continue

                        if (
                            normalized(review["request"])
                            != normalized(row["request"])
                        ):
                            continue

                        if (
                            normalized(review["action"])
                            != normalized(row["action"])
                        ):
                            continue

                        if (
                            normalized(review["file_name"])
                            != normalized(row["file_name"])
                        ):
                            continue

                        if (
                            normalized(review["recipient"])
                            != normalized(row["recipient"])
                        ):
                            continue

                        if (
                            review["risk_score"]
                            != row["risk_score"]
                        ):
                            continue

                        if (
                            row["timestamp"]
                            and review["created_at"]
                        ):

                            difference = abs(
                                (
                                    review["created_at"]
                                    - row["timestamp"]
                                ).total_seconds()
                            )

                        else:

                            difference = 0

                        candidates.append(
                            (
                                difference,
                                review
                            )
                        )


                    if candidates:

                        candidates.sort(
                            key=lambda item: item[0]
                        )

                        review_match = candidates[0][1]

                        used_review_ids.add(
                            review_match["id"]
                        )


                item = {
                    "id":
                        row["id"],

                    "timestamp":
                        (
                            row["timestamp"].isoformat()
                            if row["timestamp"]
                            else None
                        ),

                    "request":
                        row["request"],

                    "action":
                        row["action"],

                    "file":
                        row["file_name"],

                    "recipient":
                        row["recipient"],

                    "decision":
                        row["decision"],

                    "reason":
                        row["reason"],

                    "risk_score":
                        row["risk_score"],

                    "risk_level":
                        row["risk_level"],

                    "risk_reasons":
                        row["risk_reasons"] or [],

                    "review_id":
                        (
                            review_match["id"]
                            if review_match
                            else None
                        ),

                    "review_status":
                        (
                            review_match["status"]
                            if review_match
                            else None
                        ),

                    "reviewed_by":
                        (
                            review_match["reviewed_by"]
                            if review_match
                            else None
                        ),

                    "reviewer_reason":
                        (
                            review_match["reviewer_reason"]
                            if review_match
                            else None
                        ),

                    "reviewed_at":
                        (
                            review_match["reviewed_at"].isoformat()
                            if (
                                review_match
                                and review_match["reviewed_at"]
                            )
                            else None
                        )
                }

                history.append(item)


            return history


        except Exception as error:

            print(
                "EMPLOYEE HISTORY DATABASE ERROR:",
                error
            )

            return []


    logs = load_json(
        AUDIT_FILE,
        []
    )

    history = []

    for item in reversed(logs):

        if item.get("type") != "SECURITY_EVENT":
            continue

        if item.get("user") != user["name"]:
            continue

        history.append(
            {
                "id": None,
                "timestamp": item.get("timestamp"),
                "request": item.get("request"),
                "action": item.get("action"),
                "file": item.get("file"),
                "recipient": item.get("recipient"),
                "decision": item.get("decision"),
                "reason": item.get("reason"),
                "risk_score": item.get("risk_score"),
                "risk_level": item.get("risk_level"),
                "risk_reasons": item.get("risk_reasons") or [],
                "review_id": None,
                "review_status": None,
                "reviewed_by": None,
                "reviewer_reason": None,
                "reviewed_at": None
            }
        )

        if len(history) >= limit:
            break

    return history


@app.get(
    "/api/employee/history"
)
async def employee_history(
    request: Request
):

    if (
        request.session.get(
            "account_type"
        )
        != "employee"
    ):

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    user = get_logged_user(
        request
    )

    if not user:

        return JSONResponse(
            {
                "error":
                    "User session not found"
            },
            status_code=401
        )


    return {
        "history":
            get_employee_history(
                user
            )
    }


# =========================================================
# ANALYZE
# =========================================================

@app.post(
    "/api/analyze"
)
async def analyze(
    request: Request,
    prompt: str = Form(...),
    recipients: str = Form("")
):

    if (
        request.session.get(
            "account_type"
        )
        != "employee"
    ):

        return JSONResponse(
            {
                "error":
                    "Unauthorized"
            },
            status_code=401
        )


    user = get_logged_user(
        request
    )

    if not user:

        return JSONResponse(
            {
                "error":
                    "User session not found"
            },
            status_code=401
        )


    try:

        restriction = get_restriction(
            user["id"]
        )


        # =================================================
        # SUSPEND ALL BEFORE AI
        # =================================================

        if restriction.get(
            "all_blocked",
            False
        ):

            restricted_by = (
                restriction.get(
                    "restricted_by"
                )
                or "Security Manager"
            )

            manager_reason = (
                restriction.get(
                    "reason"
                )
                or ""
            )


            reason = (
                "All account operations are suspended "
                f"by {restricted_by}."
            )


            if manager_reason:

                reason += (
                    " Reason: "
                    + manager_reason
                )


            save_security_audit(
                user,
                prompt,
                "BLOCKED_BEFORE_AI",
                None,
                None,
                "BLOCK",
                reason,
                100,
                "CRITICAL",
                [
                    "Account suspended by Security Manager"
                ]
            )


            return {

                "user":
                    user["name"],

                "department":
                    user["role"],

                "title":
                    user["title"],

                "clearance":
                    user["clearance"],

                "action":
                    "BLOCKED_BEFORE_AI",

                "file":
                    None,

                "decision":
                    "BLOCK",

                "reason":
                    reason,

                "risk_score":
                    100,

                "risk_level":
                    "CRITICAL",

                "risk_reasons":
                    [
                        "Account suspended by Security Manager"
                    ],

                "review_id":
                    None,

                "recipient_results":
                    []
            }


        # =================================================
        # AI INTENT
        # =================================================

        interpretation = ask_ollama(
            prompt
        )


        action = str(
            interpretation.get(
                "action",
                ""
            )
        ).strip().upper()


        file_name = interpretation.get(
            "file"
        )


        ai_recipient = interpretation.get(
            "recipient"
        )


        # =================================================
        # SELECTED RECIPIENTS
        # =================================================

        selected_recipients = []


        if recipients:

            try:

                selected_recipients = json.loads(
                    recipients
                )

                if not isinstance(
                    selected_recipients,
                    list
                ):

                    selected_recipients = []


            except Exception:

                selected_recipients = []


        if (
            action == "SEND"
            and selected_recipients
        ):

            recipient_list = (
                selected_recipients
            )


        elif (
            action == "SEND"
            and ai_recipient
        ):

            recipient_list = [
                ai_recipient
            ]


        else:

            recipient_list = []


        # =================================================
        # SEND SUSPENDED
        # =================================================

        if (
            action == "SEND"
            and restriction.get(
                "send_blocked",
                False
            )
        ):

            restricted_by = (
                restriction.get(
                    "restricted_by"
                )
                or "Security Manager"
            )

            manager_reason = (
                restriction.get(
                    "reason"
                )
                or ""
            )


            reason = (
                "SEND operations are suspended "
                f"by {restricted_by}."
            )


            if manager_reason:

                reason += (
                    " Reason: "
                    + manager_reason
                )


            save_security_audit(
                user,
                prompt,
                action,
                file_name,
                None,
                "BLOCK",
                reason,
                90,
                "CRITICAL",
                [
                    "SEND privilege suspended"
                ]
            )


            return {

                "user":
                    user["name"],

                "department":
                    user["role"],

                "title":
                    user["title"],

                "clearance":
                    user["clearance"],

                "action":
                    action,

                "file":
                    file_name,

                "decision":
                    "BLOCK",

                "reason":
                    reason,

                "risk_score":
                    90,

                "risk_level":
                    "CRITICAL",

                "risk_reasons":
                    [
                        "SEND privilege suspended"
                    ],

                "review_id":
                    None,

                "recipient_results":
                    []
            }


        # =================================================
        # MULTI-RECIPIENT SEND
        # =================================================

        if (
            action == "SEND"
            and recipient_list
        ):

            evaluations = []

            any_block = False


            for recipient_email in recipient_list:

                decision, reason = security_check(
                    user,
                    action,
                    file_name,
                    recipient_email
                )


                (
                    risk_score,
                    risk_level,
                    risk_reasons
                ) = calculate_risk(
                    user,
                    action,
                    file_name,
                    recipient_email,
                    decision,
                    prompt
                )


                if decision == "BLOCK":

                    any_block = True


                evaluations.append(
                    {
                        "recipient_email":
                            recipient_email,

                        "decision":
                            decision,

                        "reason":
                            reason,

                        "risk_score":
                            risk_score,

                        "risk_level":
                            risk_level,

                        "risk_reasons":
                            risk_reasons
                    }
                )


            recipient_results = []

            overall_decision = "ALLOW"

            highest_risk_score = 0

            highest_risk_level = "LOW"

            all_risk_reasons = []


            for evaluation in evaluations:

                recipient_email = evaluation[
                    "recipient_email"
                ]

                decision = evaluation[
                    "decision"
                ]

                reason = evaluation[
                    "reason"
                ]

                risk_score = evaluation[
                    "risk_score"
                ]

                risk_level = evaluation[
                    "risk_level"
                ]

                risk_reasons = evaluation[
                    "risk_reasons"
                ]


                recipient_user = get_user_by_email(
                    recipient_email
                )


                final_decision = decision

                review_id = None


                if decision == "BLOCK":

                    overall_decision = (
                        "BLOCK"
                    )


                elif (
                    not any_block
                    and requires_review(
                        decision,
                        risk_score
                    )
                ):

                    final_decision = (
                        "REVIEW"
                    )

                    overall_decision = (
                        "REVIEW"
                    )


                    review_id = create_review_request(
                        user,
                        prompt,
                        action,
                        file_name,
                        recipient_email,
                        risk_score,
                        risk_level,
                        risk_reasons
                    )


                    reason = (
                        "Security policy passed, "
                        "but human review is required "
                        "before execution."
                    )


                recipient_results.append(
                    {

                        "email":
                            recipient_email,

                        "name":
                            (
                                recipient_user["name"]
                                if recipient_user
                                else recipient_email
                            ),

                        "department":
                            (
                                recipient_user["role"]
                                if recipient_user
                                else "Unknown"
                            ),

                        "decision":
                            final_decision,

                        "reason":
                            reason,

                        "risk_score":
                            risk_score,

                        "risk_level":
                            risk_level,

                        "review_id":
                            review_id
                    }
                )


                save_security_audit(
                    user,
                    prompt,
                    action,
                    file_name,
                    recipient_email,
                    final_decision,
                    reason,
                    risk_score,
                    risk_level,
                    risk_reasons
                )


                if (
                    risk_score
                    > highest_risk_score
                ):

                    highest_risk_score = (
                        risk_score
                    )

                    highest_risk_level = (
                        risk_level
                    )


                for item in risk_reasons:

                    if (
                        item
                        not in all_risk_reasons
                    ):

                        all_risk_reasons.append(
                            item
                        )


            if any_block:

                overall_decision = (
                    "BLOCK"
                )

                overall_reason = (
                    "One or more selected recipients "
                    "failed a mandatory security policy."
                )


            elif (
                overall_decision
                == "REVIEW"
            ):

                overall_reason = (
                    "Mandatory security policies passed, "
                    "but this request requires human review."
                )


            else:

                overall_reason = (
                    "All selected recipients passed "
                    "security policy checks."
                )


            return {

                "user":
                    user["name"],

                "department":
                    user["role"],

                "title":
                    user["title"],

                "clearance":
                    user["clearance"],

                "action":
                    action,

                "file":
                    file_name,

                "decision":
                    overall_decision,

                "reason":
                    overall_reason,

                "risk_score":
                    highest_risk_score,

                "risk_level":
                    highest_risk_level,

                "risk_reasons":
                    all_risk_reasons,

                "review_id":
                    None,

                "recipient_results":
                    recipient_results
            }


        # =================================================
        # NORMAL READ / EDIT
        # =================================================

        decision, reason = security_check(
            user,
            action,
            file_name,
            ai_recipient
        )


        (
            risk_score,
            risk_level,
            risk_reasons
        ) = calculate_risk(
            user,
            action,
            file_name,
            ai_recipient,
            decision,
            prompt
        )


        file_info = files.get(
            file_name,
            {}
        )


        review_id = None

        final_decision = decision


        if requires_review(
            decision,
            risk_score
        ):

            review_id = create_review_request(
                user,
                prompt,
                action,
                file_name,
                ai_recipient,
                risk_score,
                risk_level,
                risk_reasons
            )


            final_decision = "REVIEW"

            reason = (
                "Mandatory security policies passed, "
                "but this request requires human review "
                "before execution."
            )


        save_security_audit(
            user,
            prompt,
            action,
            file_name,
            ai_recipient,
            final_decision,
            reason,
            risk_score,
            risk_level,
            risk_reasons
        )


        return {

            "user":
                user["name"],

            "department":
                user["role"],

            "title":
                user["title"],

            "clearance":
                user["clearance"],

            "action":
                action,

            "file":
                file_name,

            "file_department":
                file_info.get(
                    "department"
                ),

            "classification":
                file_info.get(
                    "classification"
                ),

            "required_clearance":
                file_info.get(
                    "required_clearance"
                ),

            "recipient":
                ai_recipient,

            "decision":
                final_decision,

            "reason":
                reason,

            "risk_score":
                risk_score,

            "risk_level":
                risk_level,

            "risk_reasons":
                risk_reasons,

            "review_id":
                review_id,

            "recipient_results":
                []
        }


    except Exception as error:

        print(
            "ANALYZE ERROR:",
            error
        )

        return JSONResponse(
            {
                "error":
                    str(error)
            },
            status_code=500
        )