# Admin User Setup

## Setting Admin Status for a User

After running the migration that adds the `is_admin` column, you need to set `is_admin=True` for your user account.

### Option 1: SQL Update (Recommended)

Connect to your database and run:

```sql
UPDATE users SET is_admin = TRUE WHERE email = 'your@email.com';
```

### Option 2: Python Script

Create a script to set admin status:

```python
from app.database.database import SessionLocal
from app.models import User

db = SessionLocal()
user = db.query(User).filter(User.email == "your@email.com").first()
if user:
    user.is_admin = True
    db.commit()
    print(f"Set is_admin=True for {user.email}")
else:
    print("User not found")
db.close()
```

### Option 3: Environment Variable Bootstrap (One-time)

You can add a one-time bootstrap in `app/api/auth.py` login endpoint that checks an env var:

```python
# In login_for_access_token function, after authentication:
ADMIN_EMAILS = os.getenv("ADMIN_EMAILS", "").split(",")
if user.email in ADMIN_EMAILS:
    user.is_admin = True
    db.commit()
```

Then set `ADMIN_EMAILS="you@x.com"` in your environment. Remove this after initial setup.

## Verification

After setting admin status, verify it works:

1. Log in with your admin account
2. Call `/api/auth/me` - should return `{"is_admin": true, ...}`
3. Try accessing `/api/admin/training/status` - should succeed (200)
4. Log in with a non-admin account
5. Try accessing `/api/admin/training/status` - should fail (403)
