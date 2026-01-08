# Phase 0: Security Claims Verification

## 1. SQLite WAL Mode Runtime Execution

**Status**: ✅ **CONFIRMED**

**Evidence**: 
- File: `app/database/database.py:32-42`
- SQLAlchemy event listener registered: `@event.listens_for(engine, "connect")`
- PRAGMA executed on every connection: `cursor.execute("PRAGMA journal_mode=WAL;")` (line 40)
- This runs automatically when SQLAlchemy creates a new database connection

**Verification**: WAL mode is enabled at runtime via event listener.

---

## 2. Unprotected Endpoints Enumeration

**Status**: ✅ **CONFIRMED** - Multiple unprotected endpoints found

**Unprotected Endpoints** (missing `Depends(get_current_user)`):

1. **`GET /api/debug/db-stats`**
   - File: `app/api/debug.py:12-18`
   - No authentication dependency
   - Returns database statistics (bakeries, products, sales counts)

2. **`POST /api/auth/signup`**
   - File: `app/api/auth.py:92-114`
   - Intentionally unprotected (public registration endpoint)

3. **`POST /api/auth/token`**
   - File: `app/api/auth.py:117-135`
   - Intentionally unprotected (login endpoint)

4. **`GET /api/bakeries/`** (list all bakeries)
   - File: `app/api/bakery.py:47-49`
   - No authentication

5. **`POST /api/bakeries/`** (create bakery)
   - File: `app/api/bakery.py:22-43`
   - No authentication

6. **`POST /api/products/`** (create product)
   - File: `app/api/product.py:15-45`
   - No authentication

7. **`GET /api/products/`** (list products)
   - File: `app/api/product.py:48-56`
   - No authentication

8. **`GET /api/products/{product_id}/metrics`**
   - File: `app/api/product.py:59-86`
   - No authentication

9. **`POST /api/sales/`** (create sales record)
   - File: `app/api/sales.py:26-55`
   - No authentication

10. **`GET /api/sales/`** (list sales)
    - File: `app/api/sales.py:58-69`
    - No authentication

11. **`POST /api/sales/upload-csv`** (upload CSV)
    - File: `app/api/sales.py:72-78`
    - No authentication (but has `Depends(get_current_user)` at line 143 in different endpoint)

**Note**: Many endpoints are intentionally public (auth endpoints, some read endpoints), but `/api/debug/db-stats` should be protected.

---

## 3. Admin Mode Default Value

**Status**: ✅ **CONFIRMED**

**Evidence**:
- File: `app/core/config.py:15`
- Default value: `admin_mode_enabled: bool = True`
- Comment says: "Default: True in dev/local, False in prod unless explicitly enabled"
- **Issue**: Default is `True`, which contradicts the comment. Must set `ADMIN_MODE_ENABLED=false` in production env to disable.

**Override mechanism**: Can be set via environment variable `ADMIN_MODE_ENABLED` (pydantic-settings will read from `.env` file).

**Usage**: 
- `app/api/admin/training.py:38` - checks `settings.admin_mode_enabled`
- `app/api/admin/diagnostics.py:32` - checks `settings.admin_mode_enabled`

---

## 4. Next.js Version

**Status**: ✅ **CONFIRMED**

**Evidence**:
- File: `frontend/package.json:20`
- Version: `"next": "^16.0.10"`
- This is Next.js 16 (App Router version)

---

## Summary

| Claim | Status | Evidence Location |
|-------|--------|-------------------|
| SQLite WAL mode enabled | ✅ Confirmed | `app/database/database.py:40` |
| Unprotected endpoints exist | ✅ Confirmed | Multiple files, `/api/debug/db-stats` is security issue |
| Admin mode default = True | ✅ Confirmed | `app/core/config.py:15` (contradicts comment) |
| Next.js version 16.0.10 | ✅ Confirmed | `frontend/package.json:20` |
