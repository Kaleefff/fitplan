-- TEMPORARY development seed: foods, until DB-04.
--
-- Lets the diet plan generator (B-12) run end to end before the food seed of DB-04
-- exists. Delete this file and the rows it inserted when DB-04 is merged. Values per
-- 100 g are USDA-like; the catalogue is the one tests/domain/test_diet.py proves every
-- goal x diet type x meals per day on. Allergens and categories come from the DB-02
-- seed (load it first) and are found by name. Idempotent: rows are keyed by name.
--
-- Load: cd backend && uv run python -m app.db.seed, then
--   docker exec -i fitplan-postgres psql -U fitplan -d fitplan < database/dev/temporary_food_seed.sql

BEGIN;

INSERT INTO food_item (name, cals_per_100g, protein_per_100g, fat_per_100g, carbs_per_100g, diet_role,
                       suitable_meal_types, is_vegetarian, is_vegan, default_portion_g, min_portion_g,
                       max_portion_g, portion_step_g) VALUES
  ('Chicken breast, cooked', 165, 31, 3.6, 0, 'protein', '{dinner,lunch}', false, false, 180, 50, 300, 10),
  ('Salmon, baked', 208, 20, 13, 0, 'protein', '{dinner,lunch}', false, false, 150, 50, 250, 10),
  ('Eggs, boiled', 143, 12.6, 9.5, 0.7, 'protein', '{breakfast,dinner,lunch}', true, false, 120, 50, 200, 10),
  ('Tofu, firm', 144, 17.3, 8.7, 2.8, 'protein', '{breakfast,dinner,lunch}', true, true, 180, 50, 300, 10),
  ('Turkey breast, cooked', 135, 30, 1, 0, 'protein', '{dinner,lunch}', false, false, 180, 50, 300, 10),
  ('Tempeh', 192, 20, 11, 7.6, 'protein', '{dinner,lunch}', true, true, 150, 50, 250, 10),
  ('Seitan', 370, 75, 1.9, 14, 'protein', '{breakfast,dinner,lunch}', true, true, 90, 30, 150, 10),
  ('Lentils, cooked', 116, 9, 0.4, 20, 'protein', '{dinner,lunch}', true, true, 180, 50, 300, 10),
  ('Greek yogurt 0%', 59, 10, 0.4, 3.6, 'dairy', '{breakfast,snack}', true, false, 250, 100, 400, 50),
  ('Skyr', 63, 11, 0.2, 4, 'dairy', '{breakfast,snack}', true, false, 250, 100, 400, 50),
  ('Cottage cheese', 98, 11, 4.3, 3.4, 'dairy', '{breakfast,snack}', true, false, 200, 100, 300, 50),
  ('Soy protein pudding', 90, 9, 2.5, 7, 'dairy', '{breakfast,snack}', true, true, 250, 100, 400, 50),
  ('Soy milk', 33, 3.3, 1.8, 0.6, 'dairy', '{breakfast,snack}', true, true, 300, 100, 500, 50),
  ('Oats', 389, 16.9, 6.9, 66, 'carb', '{breakfast}', true, true, 90, 30, 150, 10),
  ('Rice, cooked', 130, 2.7, 0.3, 28, 'carb', '{dinner,lunch}', true, true, 280, 50, 500, 10),
  ('Potatoes, boiled', 87, 1.9, 0.1, 20, 'carb', '{dinner,lunch}', true, true, 300, 100, 500, 50),
  ('Wholemeal bread', 247, 13, 3.4, 41, 'carb', '{breakfast,dinner,lunch}', true, true, 90, 30, 150, 10),
  ('Pasta, cooked', 158, 5.8, 0.9, 31, 'carb', '{dinner,lunch}', true, true, 280, 50, 500, 10),
  ('Buckwheat, cooked', 92, 3.4, 0.6, 20, 'carb', '{dinner,lunch}', true, true, 220, 50, 400, 10),
  ('Broccoli', 34, 2.8, 0.4, 7, 'vegetable', '{dinner,lunch}', true, true, 200, 50, 300, 50),
  ('Mixed salad', 15, 1.2, 0.2, 2.9, 'vegetable', '{dinner,lunch}', true, true, 200, 50, 300, 50),
  ('Carrots', 41, 0.9, 0.2, 10, 'vegetable', '{dinner,lunch}', true, true, 200, 50, 300, 50),
  ('Spinach', 23, 2.9, 0.4, 3.6, 'vegetable', '{dinner,lunch}', true, true, 200, 50, 300, 50),
  ('Banana', 89, 1.1, 0.3, 23, 'fruit', '{breakfast,snack}', true, true, 150, 50, 250, 10),
  ('Apple', 52, 0.3, 0.2, 14, 'fruit', '{breakfast,snack}', true, true, 180, 50, 300, 10),
  ('Berries', 57, 0.7, 0.3, 14, 'fruit', '{breakfast,snack}', true, true, 150, 50, 250, 10),
  ('Olive oil', 884, 0, 100, 0, 'fat', '{dinner,lunch}', true, true, 20, 5, 30, 5),
  ('Peanut butter', 588, 25, 50, 20, 'fat', '{breakfast,snack}', true, true, 25, 10, 40, 5),
  ('Almonds', 579, 21, 50, 22, 'fat', '{breakfast,snack}', true, true, 30, 10, 50, 5),
  ('Avocado', 160, 2, 15, 9, 'fat', '{breakfast,dinner,lunch}', true, true, 90, 30, 150, 10),
  ('Soy protein isolate', 335, 80, 3, 7, 'protein', '{breakfast,dinner,lunch}', true, true, 40, 20, 60, 10),
  ('Soy protein yogurt', 60, 10, 1.5, 3, 'dairy', '{breakfast,snack}', true, true, 250, 100, 400, 50),
  ('Bagel', 257, 10, 1.6, 50, 'carb', '{breakfast,dinner,lunch}', true, true, 120, 50, 200, 10),
  ('Dates', 277, 1.8, 0.2, 75, 'fruit', '{breakfast,snack}', true, true, 60, 20, 100, 10),
  ('Chicken curry with rice', 150, 10, 5, 16, 'dish', '{dinner,lunch}', false, false, 350, 200, 500, 50),
  ('Vegan chili', 110, 6, 3, 15, 'dish', '{dinner,lunch}', true, true, 350, 200, 500, 50)
ON CONFLICT (name) DO NOTHING;

INSERT INTO food_item_allergen (food_item_id, allergen_id)
SELECT f.id, a.id FROM (VALUES
  ('Salmon, baked', 'Fish'),
  ('Eggs, boiled', 'Eggs'),
  ('Tofu, firm', 'Soybeans'),
  ('Tempeh', 'Soybeans'),
  ('Seitan', 'Gluten'),
  ('Greek yogurt 0%', 'Milk'),
  ('Greek yogurt 0%', 'Lactose'),
  ('Skyr', 'Milk'),
  ('Skyr', 'Lactose'),
  ('Cottage cheese', 'Milk'),
  ('Cottage cheese', 'Lactose'),
  ('Soy protein pudding', 'Soybeans'),
  ('Soy milk', 'Soybeans'),
  ('Oats', 'Gluten'),
  ('Wholemeal bread', 'Gluten'),
  ('Pasta, cooked', 'Gluten'),
  ('Peanut butter', 'Peanuts'),
  ('Almonds', 'Tree nuts'),
  ('Soy protein isolate', 'Soybeans'),
  ('Soy protein yogurt', 'Soybeans'),
  ('Bagel', 'Gluten')
) AS v(food, allergen)
JOIN food_item f ON f.name = v.food
JOIN allergen a ON a.name = v.allergen
ON CONFLICT DO NOTHING;

INSERT INTO food_item_category (food_item_id, food_category_id)
SELECT f.id, c.id FROM (VALUES
  ('Chicken breast, cooked', 'Poultry'),
  ('Salmon, baked', 'Fish and seafood'),
  ('Eggs, boiled', 'Eggs'),
  ('Tofu, firm', 'Plant proteins'),
  ('Turkey breast, cooked', 'Poultry'),
  ('Tempeh', 'Plant proteins'),
  ('Seitan', 'Plant proteins'),
  ('Lentils, cooked', 'Plant proteins'),
  ('Greek yogurt 0%', 'Dairy'),
  ('Skyr', 'Dairy'),
  ('Cottage cheese', 'Dairy'),
  ('Soy protein pudding', 'Plant-based alternatives'),
  ('Soy milk', 'Plant-based alternatives'),
  ('Oats', 'Grains and cereals'),
  ('Rice, cooked', 'Grains and cereals'),
  ('Potatoes, boiled', 'Grains and cereals'),
  ('Wholemeal bread', 'Grains and cereals'),
  ('Pasta, cooked', 'Grains and cereals'),
  ('Buckwheat, cooked', 'Grains and cereals'),
  ('Broccoli', 'Vegetables'),
  ('Mixed salad', 'Vegetables'),
  ('Carrots', 'Vegetables'),
  ('Spinach', 'Vegetables'),
  ('Banana', 'Fruits'),
  ('Apple', 'Fruits'),
  ('Berries', 'Fruits'),
  ('Olive oil', 'Fats and oils'),
  ('Peanut butter', 'Nuts and seeds'),
  ('Almonds', 'Nuts and seeds'),
  ('Avocado', 'Fats and oils'),
  ('Soy protein isolate', 'Plant proteins'),
  ('Soy protein yogurt', 'Plant-based alternatives'),
  ('Bagel', 'Grains and cereals'),
  ('Dates', 'Fruits'),
  ('Chicken curry with rice', 'Prepared dishes'),
  ('Vegan chili', 'Prepared dishes')
) AS v(food, category)
JOIN food_item f ON f.name = v.food
JOIN food_category c ON c.category_name = v.category
ON CONFLICT DO NOTHING;

COMMIT;
