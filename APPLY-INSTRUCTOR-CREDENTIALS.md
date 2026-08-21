# Apply the instructor credentials

This release includes the approved instructor usernames and temporary passwords
from `booking credintial.xlsx`.

## Important

Deploying the release does **not** automatically reset anyone's password. This
prevents a later redeploy from unexpectedly locking staff out.

After Coolify shows the deployment as healthy, open the application container
terminal and run the following commands once:

```sh
python apply_instructor_credentials.py
python apply_instructor_credentials.py --apply
```

The first command is a preview. The second command will:

1. Create a login for instructors without one, including ANSAN and ALIN SHIBY.
2. Update the registered username and temporary password for every matching
   instructor profile.
3. Enable those instructor logins.
4. Create a database backup before modifying any account.
5. Require each instructor to change the temporary password at first sign-in.

If the preview reports a duplicate instructor or username conflict, do not run
`--apply`. Resolve that conflict first, then run the preview again.
