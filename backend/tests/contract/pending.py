"""Contract operations not implemented yet (B-28).

The drift test requires this list to equal the contract operations the app does not
serve. Remove an operation here in the PR that implements it.
"""

PENDING_OPERATIONS = (
    "signInWithGoogle",  # POST /auth/google
    "signInWithApple",  # POST /auth/apple
    "listFoods",  # GET /foods
    "getFood",  # GET /foods/{food_id}
    "listFoodCategories",  # GET /food-categories
    "registerPushToken",  # POST /devices/push-token
    "unregisterPushToken",  # DELETE /devices/push-token
    "createRecognition",  # POST /meals/recognitions
    "getRecognition",  # GET /meals/recognitions/{recognition_id}
    "discardRecognition",  # DELETE /meals/recognitions/{recognition_id}
    "addRecognitionItem",  # POST /meals/recognitions/{recognition_id}/items
    "updateRecognitionItem",  # PATCH /meals/recognitions/{recognition_id}/items/{item_index}
    "deleteRecognitionItem",  # DELETE /meals/recognitions/{recognition_id}/items/{item_index}
    "confirmRecognition",  # POST /meals/recognitions/{recognition_id}/confirm
    "listNutritionLogs",  # GET /nutrition-logs
    "createNutritionLog",  # POST /nutrition-logs
    "updateNutritionLog",  # PATCH /nutrition-logs/{nutrition_log_id}
    "deleteNutritionLog",  # DELETE /nutrition-logs/{nutrition_log_id}
    "getDailySummary",  # GET /nutrition/daily-summary
    "getMealSuggestions",  # GET /nutrition/suggestions
    "listReports",  # GET /reports
    "generateReport",  # POST /reports
    "getReport",  # GET /reports/{report_id}
    "exportReport",  # GET /reports/{report_id}/export
    "syncPush",  # POST /sync/push
    "syncPull",  # GET /sync/pull
)
