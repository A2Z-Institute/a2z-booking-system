# Instructor login credentials

Instructor accounts use this standard:

- Username = exact instructor full name, including spaces.
- Password = first name in lowercase + `@123`.
- Example: `Abhinand Biju` → username `Abhinand Biju`, password `abhinand@123`.

## Existing production accounts

After deploying this version, run:

```bash
python set_instructor_credentials.py
```

The script makes a verified backup first, checks for username conflicts, updates only instructor accounts, and verifies SQLite integrity afterward.

## Future instructor accounts

New instructor accounts automatically receive the same username/password pattern. The administrator reset-password action also restores this instructor-specific credential pattern.
