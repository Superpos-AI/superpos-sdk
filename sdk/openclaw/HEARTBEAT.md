# Superpos Heartbeat

Periodic maintenance tasks for the Superpos agent connection. Run these checks every ~30 minutes to keep the agent alive and responsive.

## Steps

1. Send a heartbeat to keep the agent from going stale:
   ```
   exec <skill_dir>/bin/superpos-cli.sh heartbeat
   ```

2. Check for pending tasks:
   ```
   exec <skill_dir>/bin/superpos-cli.sh poll
   ```

3. If tasks are found, process them based on configured mode:
   - **auto** tasks: claim, process, and complete/fail automatically
   - **manual** tasks: notify the user

4. Check for new events:
   ```
   exec <skill_dir>/bin/superpos-cli.sh events poll
   ```

5. If the daemon is not running and `SUPERPOS_AUTO_DAEMON=true`, restart it:
   ```
   exec <skill_dir>/bin/superpos-cli.sh daemon status
   ```
   If stopped:
   ```
   exec <skill_dir>/bin/superpos-cli.sh daemon start
   ```
