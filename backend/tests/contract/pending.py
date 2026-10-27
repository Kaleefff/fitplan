"""Contract operations not implemented yet (B-28).

The drift test requires this list to equal the contract operations the app does not
serve. Remove an operation here in the PR that implements it.
"""

PENDING_OPERATIONS = (
    "forgotPassword",  # POST /auth/password/forgot
    "resetPassword",  # POST /auth/password/reset
    "signInWithGoogle",  # POST /auth/google
    "signInWithApple",  # POST /auth/apple
    "getMe",  # GET /users/me
    "updateMe",  # PATCH /users/me
    "changeEmail",  # POST /users/me/email
    "changePassword",  # POST /users/me/password
    "deleteAccount",  # POST /users/me/delete
    "getProfile",  # GET /users/me/profile
    "putProfile",  # PUT /users/me/profile
    "listInjuries",  # GET /users/me/injuries
    "createInjury",  # POST /users/me/injuries
    "updateInjury",  # PATCH /users/me/injuries/{injury_id}
    "deleteInjury",  # DELETE /users/me/injuries/{injury_id}
    "getAllergies",  # GET /users/me/allergies
    "putAllergies",  # PUT /users/me/allergies
    "getExcludedFoods",  # GET /users/me/excluded-foods
    "putExcludedFoods",  # PUT /users/me/excluded-foods
    "listInjuryTypes",  # GET /injury-types
    "listAllergens",  # GET /allergens
    "listMuscleGroups",  # GET /muscle-groups
    "listExercises",  # GET /exercises
    "getExercise",  # GET /exercises/{exercise_id}
    "listExerciseAlternatives",  # GET /exercises/{exercise_id}/alternatives
    "listFoods",  # GET /foods
    "getFood",  # GET /foods/{food_id}
    "listFoodCategories",  # GET /food-categories
    "updateTrainingSession",  # PATCH /training-sessions/{training_session_id}
    "updateSessionExercise",  # PATCH /session-exercises/{session_exercise_id}
    "swapSessionExercise",  # PUT /session-exercises/{session_exercise_id}/swap
    "generateDietPlan",  # POST /diet-plans/generate
    "getActiveDietPlan",  # GET /diet-plans/active
    "getDietPlan",  # GET /diet-plans/{plan_id}
    "acceptDietPlan",  # POST /diet-plans/{plan_id}/accept
    "listReminders",  # GET /reminders
    "putReminders",  # PUT /reminders
    "registerPushToken",  # POST /devices/push-token
    "unregisterPushToken",  # DELETE /devices/push-token
    "listNotifications",  # GET /notifications
    "getNextSession",  # GET /sessions/next
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
    "listBodyMetrics",  # GET /body-metrics
    "saveBodyMetrics",  # POST /body-metrics
    "deleteBodyMetrics",  # DELETE /body-metrics/{body_metrics_id}
    "getAnalyticsSummary",  # GET /analytics/summary
    "getAnalyticsChart",  # GET /analytics/charts/{metric}
    "getGoalPrediction",  # GET /analytics/goal-prediction
    "listReports",  # GET /reports
    "generateReport",  # POST /reports
    "getReport",  # GET /reports/{report_id}
    "exportReport",  # GET /reports/{report_id}/export
    "syncPush",  # POST /sync/push
    "syncPull",  # GET /sync/pull
)
