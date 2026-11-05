# GAS Arabian Services — Payment Processing System (PPS)

An independently built **training prototype** using the supplied GAS artwork. This is not an official GAS website or a production-approved payment platform.

## Technologies
- **Backend:** Python 3.11+ / Flask / Flask-SQLAlchemy
- **Database:** MySQL 8+ using PyMySQL; optional SQLite for local demonstration
- **Frontend:** HTML, CSS, Bootstrap 5, JavaScript, Chart.js
- **Reporting:** Interactive dashboard, filterable tables, CSV exports, printable payment advice, **rule-based** data insights

## Windows PowerShell setup

1. Install Python and MySQL Server; make sure MySQL is running.
2. Extract ZIP and open PowerShell **in the folder containing `app.py`**.
3. Create virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env`:

   ```powershell
   Copy-Item .env.example .env
   ```

5. Create MySQL database with MySQL Workbench:

   ```sql
   CREATE DATABASE gas_pps CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

6. Edit `.env` and set `DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/gas_pps?charset=utf8mb4` replacing YOUR_PASSWORD with your MySQL password (URL-encode special characters). Set `SECRET_KEY` to a secure randomly generated value.
7. Seed **demo data only for an empty test database**:

   ```powershell
   python seed_demo.py
   ```

8. Run:

   ```powershell
   python app.py
   ```

9. Open http://127.0.0.1:5000 in your browser.

**Quick test without configuring MySQL:** change `DATABASE_URL` in `.env` to `sqlite:///gas_demo.db`, then run steps 7–9. MySQL remains the intended production database to satisfy the project specification.

## Demo login (local testing ONLY)

| Role | Email | Password |
|------|-------|----------|
| Administrator | admin@gas.local | Demo@123456 |
| Employee | employee@gas.local | Demo@123456 |
| Division Manager | manager@gas.local | Demo@123456 |
| Finance | finance@gas.local | Demo@123456 |
| Final Manager | director@gas.local | Demo@123456 |

Remove demo users and change all passwords before sharing a deployment. The demo users are created **only** when `python seed_demo.py` is executed; not on app startup.

## Working flow

1. Employee creates an Advance/Reimbursement request, multiple items, optional supplier and documents.
2. Employee's **division manager** reviews and approves/rejects.
3. **Finance** validates documentation and ensures department budget can cover the request.
4. **Final manager** approves/rejects; approved request becomes ready for payment.
5. **Finance** marks the request paid, and approved payment advice can be printed / saved to PDF.
6. Request details display the full audit trail; departments, users and vendors are manageable by administrator.

Roles limit access: employee sees own requests; division manager sees their department; finance, final manager and admin have global visibility. Actions require the appropriate role. Finance budget validation is applied on the finance approval step.

## Current limitations (planned work to make production-ready)

- Rule-based analytics, not a trained/prompted AI model. An AI service integration is needed to meet advanced AI-analysis requirements.
- CSV export and printable browser PDF, not native Excel generation or server-side PDF report export.
- No email/SMS notification system, no currency conversion, no payment gateway/bank integration, no request editing/resubmission or budget-period accounting.
- Deployment needs HTTPS, appropriate backups, fine-grained roles, authentication hardening (MFA, rate limiting), malware scanning for uploads, robust error logging, migrations, password reset, and security review.
- CDN-based frontend scripts and Google fonts need internet access. For a fully offline or restricted network, self-host these assets.

## Files

`app.py` = Flask routes/models and workflow. `templates/` = Jinja2 HTML pages. `static/css/style.css` = professional branding. `static/js/app.js` = dynamic forms and filtering. `static/img/GAS.webp` = supplied logo. `schema.sql` = MySQL database initialization. `seed_demo.py` = optional demo records. `uploads/` = private attachment storage.
