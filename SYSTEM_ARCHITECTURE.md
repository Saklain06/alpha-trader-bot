# Alpha Trader - Secure System Architecture

This document outlines the security architecture implemented for the Alpha Trader Bot.

## 1. High-Level Overview
The system is designed with a **Defense-in-Depth** approach, ensuring multiple layers of security.

-   **Public Layer:** Nginx (Reverse Proxy) & UFW (Firewall).
-   **Application Layer:** Next.js Middleware (Route Protection).
-   **API Layer:** JWT Authentication & Dependency Injection.
-   **Data Layer:** Bcrypt Password Hashing.

---

## 2. Authentication Flow

### A. Login Process
1.  **User** accesses `/login`.
2.  **Frontend** sends `username/password` to Backend (`POST /api/token`).
3.  **Backend** (`main.py` -> `auth.py`):
    -   Verifies credentials against SQLite Database (`users` table).
    -   If valid, generates a **signed JWT** (JSON Web Token).
4.  **Backend** returns the token.
5.  **Frontend** (`app/login/page.tsx`):
    -   Stores the token in a **HTTP Cookie** (`auth_token`).
    -   Redirects user to `/dashboard` using a hard redirect (to ensure cookie propagation).

### B. Accessing the Dashboard (Route Protection)
1.  **User** navigates to `/dashboard`.
2.  **Next.js Middleware** (`middleware.ts`) intercepts the request **on the server**.
3.  **Middleware** checks for the existence of the `auth_token` cookie.
    -   **If Missing:** Redirects immediately to `/login`.
    -   **If Present:** Allows value to pass through to the page.

### C. API Data Fetching (Backend Protection)
1.  **Dashboard** (`app/dashboard/page.tsx`) loads and fetches data (e.g., `GET /api/stats`).
2.  **Browser** automatically sends the `auth_token` cookie with the request.
3.  **Backend** (`main.py`):
    -   Route is protected by `Depends(get_current_user)`.
    -   `get_current_user` (in `auth.py`) checks for the token in the **Authorization Header**.
    -   If missing (browser default), it checks the **Cookie**.
    -   It validates the JWT signature using the `SECRET_KEY`.
4.  **Result:**
    -   **Valid:** Returns JSON data.
    -   **Invalid/Expired:** Returns `401 Unauthorized`. Frontend detects this and redirects to Login.

---

## 3. Key Files Created & Modified

### 📂 Frontend (`crypto-dashboard/`)

| File | Purpose |
| :--- | :--- |
| `app/page.tsx` | **[NEW]** Public Landing Page. Replaces the old dashboard at root. Safe for public view. |
| `app/login/page.tsx` | **[NEW]** Login Form. Handles credential submission and Cookie setting. |
| `app/dashboard/page.tsx` | **[MOVED]** The original trading interface. Now lives here and requires auth. |
| `middleware.ts` | **[NEW]** The "Gatekeeper". Runs on every request to `/dashboard` to enforce login. |
| `tailwind.config.ts` | **[NEW]** Styling configuration. Ensures the UI looks correct. |

### 📂 Backend (`/`)

| File | Purpose |
| :--- | :--- |
| `auth.py` | **[NEW]** The Security Core. Contains `verify_password`, `create_access_token`, and the critical `get_current_user` dependency. |
| `seed_user.py` | **[NEW]** Admin creation script. Hashes password `admin123` and inserts it into the DB. |
| `main.py` | **[MODIFIED]** Added `/token` endpoint and applied `Depends(get_current_user)` to all sensitive routes. |
| `database.py` | **[MODIFIED]** Added `users` table schema to store credentials securely. |

### 📂 Infrastructure

| File | Purpose |
| :--- | :--- |
| `deploy_vps.py` | **[MODIFIED]** Automation script. Now handles uploading new files, migrating DB, and managing the entire deployment lifecycle. |
| `UFW (Firewall)` | **[VPS]** Configured globally to BLOCK ports `8000` and `3000`. Only Nginx (Port 80) is allowed to speak to the outside world. |

---

## 4. Why this is Secure request?
1.  **No Direct API Access:** Hackers cannot bypass the frontend and hit your API (Port 8000) directly because the Firewall blocks it. They MUST go through Nginx.
2.  **No Unauthenticated Use:** Even if they go through Nginx, the API rejects them without a valid JWT.
3.  **No Database Leaks:** Passwords are hashed with **Bcrypt**. Even if the DB is stolen, passwords are unreadable.
4.  **No Ghost Access:** The Frontend (Dashboard) code isn't even sent to the browser unless the Middleware sees a cookie (mostly true, though strict static assets might be public, the *data* is 100% hidden).
