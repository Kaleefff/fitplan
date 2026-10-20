"""Contract operations not implemented yet (B-28).

The drift test requires this list to equal the contract operations the app does not
serve. Remove an operation here in the PR that implements it.
"""

PENDING_OPERATIONS = (
    "register",  # POST /auth/register
    "login",  # POST /auth/login
    "refreshTokens",  # POST /auth/refresh
    "logout",  # POST /auth/logout
    "forgotPassword",  # POST /auth/password/forgot
    "resetPassword",  # POST /auth/password/reset
    "signInWithGoogle",  # POST /auth/google
    "signInWithApple",  # POST /auth/apple
    "getMe",  # GET /users/me
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
    "listInjuryTypes",  # GET /injury-types
    "listAllergens",  # GET /allergens
    "listMuscleGroups",  # GET /muscle-groups
    "listExercises",  # GET /exercises
    "getExercise",  # GET /exercises/{exercise_id}
    "listExerciseAlternatives",  # GET /exercises/{exercise_id}/alternatives
    "listFoods",  # GET /foods
    "getFood",  # GET /foods/{food_id}
    "listFoodCategories",  # GET /food-categories
    "generateTrainingPlan",  # POST /training-plans/generate
    "getActiveTrainingPlan",  # GET /training-plans/active
    "getTrainingPlan",  # GET /training-plans/{plan_id}
    "acceptTrainingPlan",  # POST /training-plans/{plan_id}/accept
    "swapSessionExercise",  # PUT /session-exercises/{session_exercise_id}/swap
    "getNutritionTargets",  # GET /nutrition/targets
    "generateDietPlan",  # POST /diet-plans/generate
    "getActiveDietPlan",  # GET /diet-plans/active
    "getDietPlan",  # GET /diet-plans/{plan_id}
    "acceptDietPlan",  # POST /diet-plans/{plan_id}/accept
    "listReminders",  # GET /reminders
    "putReminders",  # PUT /reminders
    "registerPushToken",  # POST /devices/push-token
    "getNextSession",  # GET /sessions/next
    "listWorkouts",  # GET /workouts
    "createWorkout",  # POST /workouts
    "createRecognition",  # POST /meals/recognitions
    "getRecognition",  # GET /meals/recognitions/{recognition_id}
    "discardRecognition",  # DELETE /meals/recognitions/{recognition_id}
    "addRecognitionItem",  # POST /meals/recognitions/{recognition_id}/items
    "updateRecognitionItem",  # PATCH /meals/recognitions/{recognition_id}/items/{item_index}
    "deleteRecognitionItem",  # DELETE /meals/recognitions/{recognition_id}/items/{item_index}
    "confirmRecognition",  # POST /meals/recognitions/{recognition_id}/confirm
    "listNutritionLogs",  # GET /nutrition-logs
    "createNutritionLog",  # POST /nutrition-logs
    "getDailySummary",  # GET /nutrition/daily-summary
    "getMealSuggestions",  # GET /nutrition/suggestions
    "listBodyMetrics",  # GET /body-metrics
    "saveBodyMetrics",  # POST /body-metrics
    "getAnalyticsSummary",  # GET /analytics/summary
    "getAnalyticsChart",  # GET /analytics/charts/{metric}
    "getGoalPrediction",  # GET /analytics/goal-prediction
    "listReports",  # GET /reports
    "getReport",  # GET /reports/{report_id}
    "exportReport",  # GET /reports/{report_id}/export
    "syncPush",  # POST /sync/push
    "syncPull",  # GET /sync/pull
)
