db = db.getSiblingDB("fitplan");

db.createCollection("meal_recognitions");
db.meal_recognitions.createIndex({ expiresAt: 1 }, { expireAfterSeconds: 0 });
db.meal_recognitions.createIndex({ userId: 1, status: 1 });
