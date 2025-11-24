# Daily Dough - local dev running. This is the second version with better ML implementation

## Database Management

### Clear All Application Data

To clear all data from the database while keeping the schema intact:

```bash
python -m app.scripts.clear_database
```

**Note:** You must run it as a module (using `-m`) for the imports to work correctly.

This will delete all rows from:
- `sales_records` (SalesRecord)
- `products` (Product)  
- `bakeries` (Bakery)

**Note:** This does NOT drop tables or modify migrations. Only data rows are removed.

The script:
- Uses the same database session as the FastAPI app (`app.database.database`)
- Shows counts before and after clearing
- Deletes in FK-safe order: Sales → Products → Bakeries
- Uses `synchronize_session=False` to avoid stale-state issues

### Verify Database State

After clearing, you can verify the database is empty:

1. **Restart the backend server** (if it's running):
   ```bash
   # Stop the server (Ctrl+C) and restart:
   uvicorn app.main:app --reload
   ```

2. **Check the debug endpoint**:
   Visit in browser or use curl:
   ```
   http://localhost:8000/api/debug/db-stats
   ```
   
   This should return:
   ```json
   {
     "bakeries": 0,
     "products": 0,
     "sales": 0
   }
   ```

3. **Clear browser cache** (if frontend still shows old data):
   - Hard refresh: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)
   - Or clear browser cache and reload the page