"""Contract operations not implemented yet (B-28).

The drift test requires this list to equal the contract operations the app does not
serve. Remove an operation here in the PR that implements it.
"""

PENDING_OPERATIONS = (
    "signInWithGoogle",  # POST /auth/google
    "signInWithApple",  # POST /auth/apple
    "registerPushToken",  # POST /devices/push-token
    "unregisterPushToken",  # DELETE /devices/push-token
    "syncPush",  # POST /sync/push
    "syncPull",  # GET /sync/pull
)
