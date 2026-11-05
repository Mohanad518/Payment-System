"""Create SAMPLE demo users and data. Run only on a local test database."""
from decimal import Decimal
from werkzeug.security import generate_password_hash
from app import app, db, Department, User, Vendor, PaymentRequest, PaymentItem, AuditLog

with app.app_context():
    if User.query.first():
        print('Users already exist. Demo seed was skipped to protect existing records.')
    else:
        ops=Department(name='Operations',budget=Decimal('600000'))
        it=Department(name='IT Services',budget=Decimal('300000'))
        fin=Department(name='Finance',budget=Decimal('500000'))
        db.session.add_all([ops,it,fin]);db.session.flush()
        accounts=[('System Administrator','admin@gas.local','admin',fin),('Maya Al-Salem','employee@gas.local','employee',ops),('Department Manager','manager@gas.local','manager',ops),('Finance Officer','finance@gas.local','finance',fin),('General Manager','director@gas.local','final_manager',fin)]
        people={}
        for name,email,role,dept in accounts:
            person=User(name=name,email=email,role=role,department_id=dept.id,password_hash=generate_password_hash('Demo@123456'))
            db.session.add(person);db.session.flush();people[role]=person
        vendor=Vendor(name='GAS Approved Supplier (Demo)',bank_details='Demo bank account — no real transfer')
        db.session.add(vendor);db.session.flush()
        examples=[('IT Equipment Reimbursement','Reimbursement','paid',2750),('Site Travel Advance','Advance','pending_finance',1600),('Office Supply Request','Reimbursement','pending_manager',880),('Training Materials','Advance','pending_final',3400),('Facility Repairs','Reimbursement','rejected',920)]
        for idx,(title,kind,status,amount) in enumerate(examples,1):
            p=PaymentRequest(ref='PPS-DEMO-'+str(idx).zfill(3),title=title,kind=kind,requester_id=people['employee'].id,department_id=ops.id,vendor_id=vendor.id,status=status,description='Example data for user interface demonstration.')
            db.session.add(p);db.session.flush()
            db.session.add(PaymentItem(payment_id=p.id,description=title,quantity=1,unit_price=Decimal(amount)))
            db.session.add(AuditLog(payment_id=p.id,user_id=people['employee'].id,action='Submitted',comment='Demo record'))
        db.session.commit()
        print('Demo database seeded successfully. Login: admin@gas.local / Demo@123456')
        print('Other demo roles: employee, manager, finance, director @gas.local (same password).')
