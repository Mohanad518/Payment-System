import os
import csv
import io
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()
BASE = Path(__file__).resolve().parent
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'development-only-change-me'),
    SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///gas_demo.db'),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=int(os.environ.get('MAX_UPLOAD_MB', '8')) * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
db = SQLAlchemy(app)
ROLES = ['employee', 'manager', 'finance', 'final_manager', 'admin']
STAGES = {'pending_manager':'Division Manager Review', 'pending_finance':'Finance Validation', 'pending_final':'Final Manager Approval', 'approved':'Approved · Ready for Payment', 'paid':'Paid / Completed', 'rejected':'Rejected'}
NEXT = {'pending_manager':('manager', 'pending_finance'), 'pending_finance':('finance', 'pending_final'), 'pending_final':('final_manager','approved')}
ALLOWED = {'pdf','png','jpg','jpeg','webp'}

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    budget = db.Column(db.Numeric(14,2), default=0, nullable=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(24), default='employee', nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    department = db.relationship('Department')
    active = db.Column(db.Boolean, default=True)

class Vendor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    bank_details = db.Column(db.String(240), default='')

class PaymentRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ref = db.Column(db.String(30), unique=True, nullable=False)
    title = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(24), nullable=False)
    payment_method = db.Column(db.String(30), default='Bank Transfer')
    description = db.Column(db.Text, default='')
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    requester = db.relationship('User', foreign_keys=[requester_id])
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=False)
    department = db.relationship('Department')
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'))
    vendor = db.relationship('Vendor')
    status = db.Column(db.String(30), default='pending_manager', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    items = db.relationship('PaymentItem', backref='payment', cascade='all, delete-orphan')
    documents = db.relationship('Document', backref='payment', cascade='all, delete-orphan')
    actions = db.relationship('AuditLog', backref='payment', order_by='AuditLog.created_at', cascade='all, delete-orphan')
    @property
    def total(self):
        return sum((i.quantity * i.unit_price for i in self.items), Decimal('0'))

class PaymentItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment_request.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(14,2), nullable=False)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment_request.id'), nullable=False)
    filename = db.Column(db.String(220), nullable=False)
    stored_filename = db.Column(db.String(100), nullable=False)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment_request.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    actor = db.relationship('User')
    action = db.Column(db.String(80), nullable=False)
    comment = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@app.template_filter('money')
def money(value): return '{:,.2f}'.format(value or 0)
@app.context_processor
def global_values():
    return {'me': db.session.get(User, session.get('user_id')) if session.get('user_id') else None, 'stages':STAGES}
@app.after_request
def secure_headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return resp
@app.before_request
def csrf_guard():
    if 'csrf' not in session: session['csrf'] = uuid.uuid4().hex
    if request.method == 'POST' and request.form.get('csrf') != session['csrf']:
        abort(400, 'Form security token invalid. Refresh the page and retry.')
@app.context_processor
def csrf_context(): return {'csrf_token': lambda: session.get('csrf','')}

def auth(f):
    @wraps(f)
    def inner(*args,**kwargs):
        u = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
        if not u or not u.active: session.clear(); return redirect(url_for('login'))
        return f(*args,**kwargs)
    return inner

def roles(*accepted):
    def decorate(f):
        @wraps(f)
        @auth
        def inner(*args,**kwargs):
            if current().role not in accepted: abort(403)
            return f(*args,**kwargs)
        return inner
    return decorate

def current(): return db.session.get(User, session['user_id'])
def visible(query):
    u = current()
    if u.role == 'employee': return query.filter_by(requester_id=u.id)
    if u.role == 'manager': return query.filter_by(department_id=u.department_id)
    return query

def access(p):
    u = current()
    if u.role == 'employee' and p.requester_id != u.id: abort(403)
    if u.role == 'manager' and p.department_id != u.department_id: abort(403)

def permission(p):
    u=current()
    if u.role == 'admin': return p.status in NEXT or p.status == 'approved'
    if p.status in NEXT: return u.role == NEXT[p.status][0] and (u.role!='manager' or u.department_id==p.department_id)
    return p.status=='approved' and u.role=='finance'

def budget_remaining(department_id, excluding=None):
    dept=db.session.get(Department,department_id)
    used=Decimal('0')
    payments=PaymentRequest.query.filter(PaymentRequest.department_id==department_id,PaymentRequest.status.in_(['pending_final','approved','paid'])).all()
    for p in payments:
        if p.id != excluding: used += p.total
    return Decimal(dept.budget) - used

@app.route('/login',methods=['GET','POST'])
def login():
    if session.get('user_id'): return redirect(url_for('dashboard'))
    if request.method=='POST':
        email=request.form.get('email','').strip().lower()
        user=User.query.filter_by(email=email,active=True).first()
        if user and check_password_hash(user.password_hash, request.form.get('password','')):
            session.clear(); session['user_id']=user.id; session['csrf']=uuid.uuid4().hex
            return redirect(url_for('dashboard'))
        flash('Incorrect email or password.','danger')
    return render_template('login.html')

@app.route('/logout',methods=['POST'])
@auth
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@auth
def dashboard():
    payments=visible(PaymentRequest.query).order_by(PaymentRequest.created_at.desc()).all()
    counts=Counter(p.status for p in payments)
    dept_totals=defaultdict(lambda: Decimal('0'))
    for p in payments:
        if p.status in ('approved','paid'): dept_totals[p.department.name]+=p.total
    overview={'total':len(payments), 'approved':counts['approved']+counts['paid'], 'pending':sum(counts[k] for k in NEXT), 'rejected':counts['rejected'], 'paid':counts['paid'], 'value':sum((p.total for p in payments),Decimal('0'))}
    return render_template('dashboard.html',payments=payments[:7],counts=counts,overview=overview,dept_totals=dept_totals, chart_counts=[counts.get(k,0) for k in STAGES], chart_depts=list(dept_totals), chart_amounts=[float(x) for x in dept_totals.values()])

@app.route('/requests')
@auth
def requests_page():
    payments=visible(PaymentRequest.query).order_by(PaymentRequest.created_at.desc()).all()
    return render_template('requests.html',payments=payments)

@app.route('/requests/new',methods=['GET','POST'])
@auth
def new_request():
    departments=Department.query.order_by(Department.name).all()
    vendors=Vendor.query.order_by(Vendor.name).all()
    if request.method=='POST':
        title=request.form.get('title','').strip()[:160]
        kind=request.form.get('kind','')
        method=request.form.get('payment_method','')
        descs=request.form.getlist('item_description[]')
        quantities=request.form.getlist('item_quantity[]')
        prices=request.form.getlist('item_price[]')
        if not title or kind not in ('Advance','Reimbursement') or method not in ('Bank Transfer','Cash'):
            flash('Complete the required fields.','danger')
        else:
            try:
                entries=[]
                if not (len(descs)==len(quantities)==len(prices)): raise ValueError()
                for d,q,price in zip(descs,quantities,prices):
                    if not d.strip(): continue
                    n=int(q); amount=Decimal(price)
                    if n<1 or n>10000 or not amount.is_finite() or amount<=0 or amount>100000000: raise ValueError()
                    entries.append((d.strip()[:200],n,amount))
                if not entries or len(entries)>30: raise ValueError()
                department_id=current().department_id
                if current().role=='admin' and request.form.get('department_id'): department_id=int(request.form['department_id'])
                if not db.session.get(Department, department_id): raise ValueError()
                vendor_id=request.form.get('vendor_id',type=int) or None
                if vendor_id and not db.session.get(Vendor,vendor_id): raise ValueError()
                files=request.files.getlist('attachments')
                for f in files:
                    if f.filename and ('.' not in f.filename or f.filename.rsplit('.',1)[1].lower() not in ALLOWED): raise ValueError('Unsupported document format')
                p=PaymentRequest(ref='PPS-'+datetime.now(timezone.utc).strftime('%y%m%d')+'-'+uuid.uuid4().hex[:6].upper(),title=title,kind=kind,payment_method=method,description=request.form.get('description','')[:2000],requester_id=current().id,department_id=department_id,vendor_id=vendor_id)
                db.session.add(p); db.session.flush()
                for d,n,price in entries: db.session.add(PaymentItem(payment_id=p.id,description=d,quantity=n,unit_price=price))
                folder=BASE/'uploads'; folder.mkdir(exist_ok=True)
                for f in files:
                    if f.filename:
                        safe=secure_filename(f.filename)
                        name=uuid.uuid4().hex+'.'+safe.rsplit('.',1)[-1].lower()
                        f.save(folder/name)
                        db.session.add(Document(payment_id=p.id, filename=safe, stored_filename=name))
                db.session.add(AuditLog(payment_id=p.id,user_id=current().id,action='Submitted',comment='Payment request submitted for review'))
                db.session.commit()
                flash('Request created and sent to the division manager.','success')
                return redirect(url_for('request_detail',pid=p.id))
            except (ValueError,InvalidOperation) as exc:
                db.session.rollback(); flash('Please check item amounts, departments, and attachments. '+str(exc),'danger')
    return render_template('new_request.html',departments=departments,vendors=vendors)

@app.route('/requests/<int:pid>')
@auth
def request_detail(pid):
    p=db.get_or_404(PaymentRequest,pid); access(p)
    return render_template('detail.html',p=p,can_act=permission(p),remaining=budget_remaining(p.department_id,p.id))

@app.route('/requests/<int:pid>/action',methods=['POST'])
@auth
def act(pid):
    p=db.get_or_404(PaymentRequest,pid); access(p)
    if not permission(p): abort(403)
    action=request.form.get('action')
    old=p.status
    if old=='approved':
        if action!='paid': abort(400)
        p.status='paid'; p.completed_at=datetime.utcnow(); label='Payment Completed'
    elif old in NEXT:
        if action=='reject': p.status='rejected'; label='Rejected'
        elif action=='approve':
            if old=='pending_finance' and p.total>budget_remaining(p.department_id,p.id):
                flash('Insufficient department budget. Finance validation blocked.','danger')
                return redirect(url_for('request_detail',pid=pid))
            p.status=NEXT[old][1]; label='Approved: '+STAGES[old]
        else: abort(400)
    else: abort(400)
    db.session.add(AuditLog(payment_id=p.id,user_id=current().id,action=label,comment=request.form.get('comment','')[:1500]))
    db.session.commit(); flash('Request updated successfully.','success')
    return redirect(url_for('request_detail',pid=pid))

@app.route('/documents/<int:did>')
@auth
def document(did):
    doc=db.get_or_404(Document,did); access(db.get_or_404(PaymentRequest,doc.payment_id))
    path=BASE/'uploads'/doc.stored_filename
    if not path.is_file(): abort(404)
    return send_file(path,as_attachment=True,download_name=doc.filename)

@app.route('/requests/<int:pid>/advice')
@auth
def advice(pid):
    p=db.get_or_404(PaymentRequest,pid); access(p)
    if p.status not in ('approved','paid'): abort(403)
    return render_template('advice.html',p=p)

@app.route('/reports')
@auth
def reports():
    payments=visible(PaymentRequest.query).order_by(PaymentRequest.created_at.desc()).all()
    status=request.args.get('status','')
    dept=request.args.get('department','')
    if status in STAGES: payments=[p for p in payments if p.status==status]
    if dept.isdigit(): payments=[p for p in payments if p.department_id==int(dept)]
    if request.args.get('export')=='csv':
        output=io.StringIO(); w=csv.writer(output)
        w.writerow(['Reference','Date','Title','Department','Requester','Type','Amount SAR','Status'])
        for p in payments: w.writerow([p.ref,p.created_at.strftime('%Y-%m-%d'),p.title,p.department.name,p.requester.name,p.kind,str(p.total),STAGES[p.status]])
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=gas_payment_report.csv'})
    return render_template('reports.html',payments=payments,departments=Department.query.all(),status=status,dept=dept)

@app.route('/insights')
@auth
def insights():
    payments=visible(PaymentRequest.query).all()
    pending=[p for p in payments if p.status in NEXT]
    rejected=[p for p in payments if p.status=='rejected']
    complete=[p for p in payments if p.status=='paid']
    by_dept=defaultdict(lambda: Decimal(0))
    for p in payments: by_dept[p.department.name]+=p.total
    leader=max(by_dept.items(),key=lambda x:x[1]) if by_dept else None
    insights_list=[('Approval workload',f'{len(pending)} requests are awaiting action. Review oldest requests first.'),('Rejection pattern',f'{len(rejected)} of {len(payments)} requests have been rejected.'),('Payment throughput',f'{len(complete)} payments have been marked complete.'),('Department concentration',f'{leader[0]} represents the largest requested amount (SAR {leader[1]:,.2f}).' if leader else 'No request data to analyze yet.')]
    return render_template('insights.html',insights=insights_list)

@app.route('/master')
@roles('admin','finance')
def master(): return render_template('master.html',departments=Department.query.all(),vendors=Vendor.query.all(),users=User.query.all())

@app.route('/master/<kind>',methods=['POST'])
@roles('admin')
def master_add(kind):
    name=request.form.get('name','').strip()[:120]
    if not name: abort(400)
    if kind=='department':
        try:
            budget=Decimal(request.form.get('budget','0'))
            if not budget.is_finite() or budget<0: raise ValueError()
        except (InvalidOperation,ValueError): abort(400)
        db.session.add(Department(name=name,budget=budget))
    elif kind=='vendor': db.session.add(Vendor(name=name,bank_details=request.form.get('bank_details','')[:240]))
    else: abort(404)
    try: db.session.commit();flash('Master data added.','success')
    except Exception: db.session.rollback();flash('This name already exists.','danger')
    return redirect(url_for('master'))

@app.route('/users/new',methods=['POST'])
@roles('admin')
def add_user():
    name=request.form.get('name','').strip()[:120]; email=request.form.get('email','').strip().lower()
    password=request.form.get('password',''); role=request.form.get('role',''); department_id=request.form.get('department_id',type=int)
    if not name or '@' not in email or len(password)<10 or role not in ROLES or not db.session.get(Department, department_id): abort(400)
    db.session.add(User(name=name,email=email,password_hash=generate_password_hash(password),role=role,department_id=department_id))
    try:db.session.commit();flash('User created successfully.','success')
    except Exception:db.session.rollback();flash('Email already exists.','danger')
    return redirect(url_for('master'))

@app.errorhandler(403)
def forbidden(error):return render_template('error.html',code=403,message='You do not have access to this operation.'),403
@app.errorhandler(404)
def not_found(error):return render_template('error.html',code=404,message='The requested page could not be found.'),404
@app.errorhandler(413)
def too_large(error):return render_template('error.html',code=413,message='File too large. Reduce the attachment size.'),413

with app.app_context():
    db.create_all()

if __name__=='__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG')=='1',port=5000)
