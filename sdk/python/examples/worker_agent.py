"""Worker agent — poll for tasks, process them, report results."""

import time

from superpos_sdk import SuperposClient
from superpos_sdk.exceptions import ConflictError

SUPERPOS_URL = "http://localhost:8080"
HIVE_ID = "your-hive-id-here"  # 26-char ULID

client = SuperposClient(SUPERPOS_URL)

# Authenticate with existing credentials
client.login(agent_id="your-agent-id", secret="your-secret")
client.update_status("online")

print("Worker started. Polling for tasks...")

try:
    while True:
        # Send heartbeat
        client.heartbeat()

        # Poll for tasks matching our capabilities
        tasks = client.poll_tasks(HIVE_ID, capability="summarize", limit=1)

        if not tasks:
            time.sleep(5)
            continue

        task = tasks[0]
        print(f"Found task {task['id']} (type={task['type']})")

        # Claim the task (may fail if another agent claims first)
        try:
            task = client.claim_task(HIVE_ID, task["id"])
        except ConflictError:
            print("  Task already claimed by another agent, skipping.")
            continue

        print("  Claimed. Processing...")

        try:
            # Report progress
            client.update_progress(HIVE_ID, task["id"], progress=50, status_message="Working...")

            # Simulate work
            result = {"summary": f"Processed payload: {task.get('payload', {})}"}

            # Mark complete
            client.complete_task(HIVE_ID, task["id"], result=result)
            print(f"  Completed task {task['id']}")

        except Exception as e:
            # Mark failed on unexpected errors
            client.fail_task(
                HIVE_ID,
                task["id"],
                error={"type": type(e).__name__, "message": str(e)},
                status_message="Unhandled error",
            )
            print(f"  Failed task {task['id']}: {e}")

except KeyboardInterrupt:
    print("\nShutting down...")
finally:
    client.update_status("offline")
    client.logout()
    client.close()
