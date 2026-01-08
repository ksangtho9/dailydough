# Security Fixes Implementation Plan

## Phase 0: Verification (COMPLETED)

See `SECURITY_VERIFICATION.md` for confirmed findings:
- ✅ SQLite WAL mode enabled at runtime (`app/database/database.py:40`)
- ✅ Unprotected endpoints identified (see table below)
- ✅ Admin mode default = True (`app/core/config.py:15`)
- ✅ Next.js version 16.0.10 (`frontend/package.json:20`)

### Unprotected Endpoints Categorization

| Endpoint | Method | Expected? | Notes |
|----------|--------|-----------|-------|
| `/api/debug/db-stats` | GET | ❌ No | **Security issue** - exposes DB stats |
| `/api/auth/signup` | POST | ✅ Yes | Public registration endpoint |
| `/api/auth/token` | POST | ✅ Yes | Public login endpoint |
| `/api/bakeries/` | GET | ⚠️ Maybe | List all bakeries - may be intentional for public API |
| `/api/bakeries/` | POST | ⚠️ Maybe | Create bakery - may be intentional for demo |
| `/api/products/` | GET | ⚠️ Maybe | List products - may be intentional for public API |
| `/api/products/` | POST | ⚠️ Maybe | Create product - may be intentional for demo |
| `/api/products/{id}/metrics` | GET | ⚠️ Maybe | Get metrics - may be intentional for public API |
| `/api/sales/` | GET | ⚠️ Maybe | List sales - may be intentional for public API |
| `/api/sales/` | POST | ⚠️ Maybe | Create sales - may be intentional for demo |
| `/api/sales/upload-csv` | POST | ⚠️ Maybe | Upload CSV - may be intentional for demo |
| `/` (root) | GET | ✅ Yes | Health check endpoint |

**Action**: Only `/api/debug/db-stats` is clearly a security issue. Others may be intentional for demo/public API use.

---

## Phase 1: Critical Fixes

### A) JWT Secret Key Hardcoded + Admin Mode Default + Settings Primitives

**Status**: ⚠️ **PARTIALLY IMPLEMENTED** - Already moved to settings, needs fail-fast validation

**Files to Change**:
1. `app/core/config.py` - Add Pydantic validators for JWT secret, change admin mode default, add CORS and upload size settings

**Changes**:
```python
# app/core/config.py
import os
import json
from typing import Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_JWT = "CHANGE_ME_TO_A_LONG_RANDOM_STRING_DEV_ONLY"

class Settings(BaseSettings):
    # Note: .env file is optional for local development. Production must use environment variables.
    # .env is gitignored and should not be committed.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    app_name: str = "BAKEZY API"
    database_url: str = "sqlite:///./bakezy.db"
    
    # Environment detection
    environment: str = Field(default="development", alias="ENVIRONMENT")
    
    # Admin mode: default to False for security (must explicitly enable)
    admin_mode_enabled: bool = Field(default=False, alias="ADMIN_MODE_ENABLED")
    
    # JWT secret key
    jwt_secret_key: str = Field(default=DEFAULT_DEV_JWT, alias="JWT_SECRET_KEY")
    
    # CORS origins (comma-separated string or JSON array in env)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
        alias="CORS_ORIGINS",
    )
    
    # File upload size limit
    max_upload_size_mb: int = Field(default=10, alias="MAX_UPLOAD_SIZE_MB")
    max_upload_size_bytes: Optional[int] = Field(default=None, alias="MAX_UPLOAD_SIZE_BYTES")
    
    # ... (keep all other existing fields) ...
    
    @field_validator("environment")
    @classmethod
    def _normalize_env(cls, v: str) -> str:
        """Normalize environment to lowercase."""
        return (v or "development").lower().strip()
    
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v):
        """Parse CORS_ORIGINS from env (comma-separated string or JSON array)."""
        if v is None:
            return v
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                # Try JSON array first, fall back to comma-splitting if it fails
                try:
                    return json.loads(s)
                except (json.JSONDecodeError, ValueError):
                    # If JSON parsing fails, treat as comma-separated string
                    return [o.strip() for o in s.split(",") if o.strip()]
            return [o.strip() for o in s.split(",") if o.strip()]
        return v
    
    @model_validator(mode="after")
    def _fail_fast_prod_jwt(self):
        """Fail fast if production uses default JWT secret."""
        if self.environment in ("production", "prod", "staging") and self.jwt_secret_key == DEFAULT_DEV_JWT:
            raise ValueError("JWT_SECRET_KEY must be set in production.")
        return self
    
    @model_validator(mode="after")
    def _compute_upload_size_bytes(self):
        """Compute bytes from MB setting if not explicitly set."""
        if self.max_upload_size_bytes is None:
            self.max_upload_size_bytes = self.max_upload_size_mb * 1024 * 1024
        return self

settings = Settings()
```

**Verification**:
```bash
# Test 1: Dev mode works with default
python -c "from app.core.config import settings; print('OK')"
# Expected: No error, admin_mode_enabled=False

# Test 2: Admin mode defaults to False
python -c "from app.core.config import settings; print(settings.admin_mode_enabled)"
# Expected: False

# Test 3: Admin mode can be enabled in dev
ADMIN_MODE_ENABLED=true python -c "from app.core.config import settings; assert settings.admin_mode_enabled == True; print('OK')"
# Expected: No error, admin_mode_enabled=True

# Test 4: Production fails without secret
ENVIRONMENT=production python -c "from app.core.config import settings"
# Expected: ValueError about JWT_SECRET_KEY

# Test 5: Production works with secret
ENVIRONMENT=production JWT_SECRET_KEY=test_secret_123 python -c "from app.core.config import settings; print('OK')"
# Expected: No error

# Test 6: Login still works
curl -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=testpass"
# Expected: 200 OK with token or 401 if invalid credentials
```

---

### B) Empty .gitignore

**Status**: ❌ **NOT IMPLEMENTED** - File is empty

**Files to Change**:
1. `.gitignore` - Add comprehensive entries

**Changes**:
```gitignore
# Environment variables
.env
.env.local
.env.*.local
*.env

# Database files
*.db
*.db-shm
*.db-wal
*.sqlite
*.sqlite3

# Logs
logs/
*.log

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
.venv

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Build artifacts
dist/
build/
*.egg-info/
```

**Verification**:
```bash
# Test 1: Check .gitignore exists and has content
cat .gitignore | wc -l
# Expected: > 20 lines

# Test 2: Verify .env is ignored
echo "TEST=value" > .env
git status
# Expected: .env should NOT appear in git status

# Test 3: Verify db files are ignored
touch test.db
git status
# Expected: test.db should NOT appear

# Note: If files are already tracked, they won't be removed automatically
# Check with: git ls-files | grep -E '\.(db|env|log)$'
```

---

### C) Verbose Internal Error Leakage

**Status**: ❌ **NOT IMPLEMENTED** - 9 instances found

**Files to Change**:
1. `app/api/bakery.py:159,164` - Upload endpoint error handling
2. `app/api/sales.py:112,117` - Upload endpoint error handling
3. `app/api/demo.py:47,97,102` - Demo endpoints error handling
4. `app/api/forecast_training.py:48,66` - Training endpoints error handling

**Changes** (example for `app/api/bakery.py`):
```python
# Add import at top
import logging
logger = logging.getLogger("bakezy.api.bakery")

# Replace lines 156-165
except ValueError:
    logger.exception("ValueError in bakery sales upload")
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid data in upload. Please check your CSV format and try again.",
    )
except Exception:
    logger.exception("Unexpected error in bakery sales upload")
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An error occurred processing the upload. Please try again later.",
    )
```

**Note**: `logger.exception()` automatically includes `exc_info=True` when called inside an `except` block. Do NOT pass `exc_info=exc` parameter. Also, do NOT capture the exception in the except clause variable if you're not using it (just use `except ValueError:` not `except ValueError as exc:`).

**Apply same pattern to**:
- `app/api/sales.py` (lines 109-118) - logger name: `"bakezy.api.sales"`
- `app/api/demo.py` (lines 44-48, 94-103) - logger name: `"bakezy.api.demo"`
- `app/api/forecast_training.py` (lines 45-49, 63-67) - logger name: `"bakezy.api.forecast_training"`

**Verification**:
```bash
# Test 1: Trigger ValueError (invalid CSV)
curl -X POST http://localhost:8000/api/bakeries/1/sales/upload \
  -F "file=@invalid.csv" \
  -F "upload_mode=append"
# Expected: 400 with generic message, NOT internal exception details
# Check logs/forecast.log for full exception

# Test 2: Trigger Exception (simulate server error)
# (May require code injection or DB lock to trigger)
# Expected: 500 with generic message, full error in logs only

# Test 3: Verify logs contain exception details
tail -n 50 logs/forecast.log | grep -A 5 "Exception"
# Expected: Full stack traces in logs
```

---

### D) Protect Debug Endpoint

**Status**: ❌ **NOT IMPLEMENTED** - Endpoint is unprotected

**Files to Change**:
1. `app/api/debug.py:12` - Add authentication dependency

**Changes**:
```python
# Add import
from app.api.auth import get_current_user

# Modify endpoint
@router.get("/db-stats")
def debug_db_stats(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),  # Add this line
):
    return {
        "bakeries": db.query(Bakery).count(),
        "products": db.query(Product).count(),
        "sales": db.query(SalesRecord).count(),
    }
```

**Verification**:
```bash
# Test 1: Unauthenticated request fails
curl http://localhost:8000/api/debug/db-stats
# Expected: 401 Unauthorized

# Test 2: Authenticated request succeeds
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=testpass" | jq -r '.access_token')
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/debug/db-stats
# Expected: 200 OK with JSON stats
```

---

## Phase 2: High Priority Hardening

### E) File Upload Limits

**Status**: ❌ **NOT IMPLEMENTED** - No size checks found

**Files to Change**:
1. `app/core/config.py` - max_upload_size setting already added in Fix A
2. `app/api/bakery.py:128` - Add size check after `content_bytes = await file.read()`
3. `app/api/sales.py:89` - Add size check after `content_bytes = await file.read()`
4. `app/api/demo.py:74` - Add size check after `content_bytes = await file.read()`

**Note**: Upload size settings are already added in Fix A. This commit only adds the runtime checks.

**In `app/api/bakery.py` after line 128**:
```python
from app.core.config import settings
import logging
logger = logging.getLogger("bakezy.api.bakery")

# After: content_bytes = await file.read()
if len(content_bytes) > settings.max_upload_size_bytes:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"File size ({len(content_bytes) / (1024*1024):.1f}MB) exceeds maximum of {settings.max_upload_size_mb}MB",
    )

# Best-effort content-type check (don't rely solely on it)
if file.content_type and file.content_type not in ["text/csv", "application/csv", "text/plain"]:
    logger.warning(f"Unexpected content-type {file.content_type} for file {file.filename}")
```

**Note**: This prevents processing oversized uploads but does not prevent ingress/memory use. Add proxy/body-size limits at deployment later (nginx/ingress/uvicorn).

**Apply same pattern to**:
- `app/api/sales.py` (after line 89)
- `app/api/demo.py` (after line 74)

**Verification**:
```bash
# Test 1: Normal file upload works
dd if=/dev/zero of=test.csv bs=1M count=5
curl -X POST http://localhost:8000/api/bakeries/1/sales/upload \
  -F "file=@test.csv" \
  -F "upload_mode=append"
# Expected: Processes normally (if valid CSV) or appropriate error

# Test 2: Large file is rejected
dd if=/dev/zero of=large.csv bs=1M count=15
curl -X POST http://localhost:8000/api/bakeries/1/sales/upload \
  -F "file=@large.csv" \
  -F "upload_mode=append"
# Expected: 400 with "exceeds maximum" message

# Test 3: Verify configurable limit (MB)
MAX_UPLOAD_SIZE_MB=5 python -c "from app.core.config import settings; print(settings.max_upload_size_bytes)"
# Expected: 5242880 (5MB)

# Test 4: Verify bytes override
MAX_UPLOAD_SIZE_BYTES=3145728 python -c "from app.core.config import settings; print(settings.max_upload_size_bytes)"
# Expected: 3145728 (3MB in bytes, overrides MB setting)
```

---

### F) Production-Ready CORS

**Status**: ❌ **NOT IMPLEMENTED** - Hardcoded localhost only

**Files to Change**:
1. `app/core/config.py` - CORS origins setting already added in Fix A
2. `app/main.py:64-73` - Use settings instead of hardcoded list

**Changes**:
```python
# app/main.py - Replace lines 66-69
allow_origins=settings.cors_origins,
```

**Note**: CORS origins parsing is already implemented in Fix A with the `_parse_cors_origins` field validator that handles both comma-separated strings and JSON arrays.

**Verification**:
```bash
# Test 1: Default localhost origins work
curl -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST" \
  -X OPTIONS http://localhost:8000/api/auth/token \
  -v
# Expected: 200 OK with Access-Control-Allow-Origin: http://localhost:3000

# Test 2: Custom origin from env (comma-separated)
CORS_ORIGINS="https://app.example.com,https://www.example.com" \
  python -c "from app.core.config import settings; print(settings.cors_origins)"
# Expected: ['https://app.example.com', 'https://www.example.com']

# Test 3: Custom origin from env (JSON array)
CORS_ORIGINS='["https://app.example.com","https://www.example.com"]' \
  python -c "from app.core.config import settings; print(settings.cors_origins)"
# Expected: ['https://app.example.com', 'https://www.example.com']

# Test 4: Unlisted origin is rejected
curl -H "Origin: https://evil.com" \
  -H "Access-Control-Request-Method: POST" \
  -X OPTIONS http://localhost:8000/api/auth/token \
  -v
# Expected: No Access-Control-Allow-Origin header (or CORS error)

# Test 5: Verify credentials still work
curl -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization" \
  -X OPTIONS http://localhost:8000/api/auth/token \
  -v | grep -i "access-control-allow-credentials"
# Expected: access-control-allow-credentials: true
```

---

### G) Security Headers

**Status**: ❌ **NOT IMPLEMENTED** - No security headers middleware

**Files to Change**:
1. `app/core/config.py` - Environment setting (already added in Fix A)
2. `app/main.py` - Add security headers middleware (function-based, not BaseHTTPMiddleware)

**Changes**:
```python
# app/main.py - Add after CORS middleware (around line 73)
from fastapi import Request

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # HSTS only in production/staging
    if settings.environment in ("production", "prod", "staging"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
```

**Note**: Using function-based middleware (`@app.middleware("http")`) instead of `BaseHTTPMiddleware` to avoid edge cases with streaming responses.

**Note**: X-XSS-Protection is deprecated and not included. Modern browsers handle XSS via CSP (not implemented here but can be added later).

**Verification**:
```bash
# Test 1: Check headers in dev
curl -I http://localhost:8000/
# Expected headers:
# X-Content-Type-Options: nosniff
# X-Frame-Options: DENY
# Referrer-Policy: strict-origin-when-cross-origin
# (No HSTS in dev)

# Test 2: Check HSTS in production mode
ENVIRONMENT=production python -m uvicorn app.main:app --port 8000 &
sleep 2
curl -I http://localhost:8000/
# Expected: Includes Strict-Transport-Security header
pkill -f uvicorn

# Test 3: Verify headers on API endpoints
curl -I http://localhost:8000/api/auth/token
# Expected: Same security headers present
```

---

## Phase 3: Optional / Larger Changes

### H) Rate Limiting

**Status**: ❌ **NOT IMPLEMENTED** - Plan only

**Proposed Implementation**:
- Use `slowapi` library (FastAPI-compatible rate limiter)
- Add to `requirements.txt`: `slowapi`
- Apply limits to:
  - `/api/auth/token` - 5 requests/minute per IP
  - `/api/forecast/*` - 30 requests/minute per user
  - `/api/admin/training/retrain` - 1 request/5 minutes per user

**Files to Change**:
1. `requirements.txt` - Add slowapi
2. `app/main.py` - Initialize limiter
3. `app/api/auth.py` - Add rate limit decorator
4. `app/api/forecast.py` - Add rate limit decorator
5. `app/api/admin/training.py` - Add rate limit decorator

**Note**: slowapi works with both sync and async FastAPI endpoints.

**Verification Steps** (if implemented):
```bash
# Test 1: Normal requests work
for i in {1..4}; do
  curl -X POST http://localhost:8000/api/auth/token \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=test@example.com&password=wrong"
done
# Expected: 4x 401 responses

# Test 2: Rate limit triggers
curl -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=wrong"
# Expected: 429 Too Many Requests with Retry-After header
```

---

### I) Token Storage (localStorage -> httpOnly Cookie)

**Status**: ❌ **NOT IMPLEMENTED** - Plan only, do not implement

**Migration Plan**:

**Backend Changes** (`app/api/auth.py`):
- Modify `/api/auth/token` to set httpOnly cookie instead of returning JSON
- Add CSRF token in response body (for state-changing requests)
- Add `/api/auth/logout` endpoint to clear cookie

**Frontend Changes**:
- Remove all `localStorage.getItem/setItem("access_token")` calls
- Remove manual `Authorization` header setting (cookies sent automatically)
- Add CSRF token to state-changing requests (POST/PUT/DELETE)
- Update `frontend/lib/api.ts` to handle cookie-based auth

**CSRF Considerations**:
- Use Double Submit Cookie pattern (CSRF token in cookie + header)
- Or use SameSite=Strict cookies (simpler, but less flexible for cross-origin)

**Files Affected**:
- `app/api/auth.py` - Cookie setting, CSRF token generation
- `frontend/lib/api.ts` - Remove localStorage, add CSRF header
- `frontend/app/login/page.tsx` - Remove token storage
- All frontend components using `localStorage.getItem("access_token")`

**Note**: This is a larger change affecting authentication flow. Only implement if explicitly requested.

---

## Implementation Summary

### Commit Structure

**Commit 1: Phase 0 Verification**
- Add `SECURITY_VERIFICATION.md` (already done)

**Commit 2: Fix A - Settings Primitives (JWT Secret, Admin Mode, CORS, Upload Size)**
- `app/core/config.py` - Add Pydantic validators for JWT secret fail-fast, change admin_mode_enabled default to False, add CORS origins parsing, add upload size settings

**Commit 3: Fix B - .gitignore**
- `.gitignore` - Add comprehensive entries

**Commit 4: Fix C - Error Message Sanitization**
- `app/api/bakery.py` - Sanitize error messages
- `app/api/sales.py` - Sanitize error messages
- `app/api/demo.py` - Sanitize error messages
- `app/api/forecast_training.py` - Sanitize error messages

**Commit 5: Fix D - Protect Debug Endpoint**
- `app/api/debug.py` - Add authentication

**Commit 6: Fix E - File Upload Limits**
- `app/api/bakery.py` - Add size and content-type checks (uses settings from Fix A)
- `app/api/sales.py` - Add size and content-type checks
- `app/api/demo.py` - Add size and content-type checks

**Commit 7: Fix F - Production CORS Wiring**
- `app/main.py` - Use settings.cors_origins for CORS (settings already added in Fix A)

**Commit 8: Fix G - Security Headers**
- `app/main.py` - Add function-based security headers middleware

---

## Remaining Gaps (Not Addressed)

1. **Rate Limiting** - Phase 3, plan only
2. **Token Storage** - Phase 3, plan only (localStorage XSS risk remains)
3. **CSRF Protection** - Not needed with Bearer tokens, but needed if moving to cookies
4. **Content Security Policy (CSP)** - Not implemented (would require frontend changes)
5. **Dependency Vulnerability Scanning** - Not in codebase (should add to CI/CD)
6. **PII Logging Review** - Logs may contain user/product data (compliance risk)
7. **Many Unprotected Endpoints** - Public endpoints for bakeries, products, sales (may be intentional for demo/public API - see table above)

---

## Verification Checklist

After each commit, verify:
- [ ] Application starts without errors
- [ ] Existing functionality still works
- [ ] Security improvement is active (check headers/behavior)
- [ ] Logs contain detailed errors (for fix C)
- [ ] No secrets in code (for fix A)
- [ ] .gitignore prevents committing sensitive files (for fix B)
