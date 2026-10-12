-- MySQL Workbench Forward Engineering

SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

-- -----------------------------------------------------
-- Schema ERD_FitApp
-- -----------------------------------------------------
CREATE SCHEMA IF NOT EXISTS `ERD_FitApp` DEFAULT CHARACTER SET utf8 ;
USE `ERD_FitApp` ;

-- -----------------------------------------------------
-- Table `ERD_FitApp`.`User`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`User` (
  `idUser` INT NOT NULL,
  `email` VARCHAR(100) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `surname` VARCHAR(100) NOT NULL,
  `registration_date` DATE NOT NULL,
  `is_active` TINYINT NOT NULL,
  PRIMARY KEY (`idUser`),
  UNIQUE INDEX `idUser_UNIQUE` (`idUser` ASC),
  UNIQUE INDEX `email_UNIQUE` (`email` ASC),
  UNIQUE INDEX `password_UNIQUE` (`password_hash` ASC) )
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`UserProfile`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`UserProfile` (
  `User_idUser` INT NOT NULL,
  `age` INT NOT NULL,
  `sex` ENUM('Male', 'Female', 'Other') NOT NULL,
  `current_weight` DECIMAL(5,2) NOT NULL,
  `height` INT NOT NULL,
  `activity_level_pal` DECIMAL(3,2) NOT NULL,
  `goal` ENUM('weight_loss', 'muscle_gain', 'strength', 'maintenance', 'general_fitness', 'edurance') NOT NULL,
  `target_type` DECIMAL(5,2) NOT NULL,
  `tdee` INT NOT NULL,
  `profile_update` DATETIME NULL,
  PRIMARY KEY (`User_idUser`),
  INDEX `fk_UserProfile_User1_idx` (`User_idUser` ASC),
  UNIQUE INDEX `User_idUser_UNIQUE` (`User_idUser` ASC),
  CONSTRAINT `fk_UserProfile_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`Notification`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`Notification` (
  `idNotification` INT NOT NULL,
  `message_type` ENUM('meal_reminder', 'training_reminder', 'progress_update', 'achievement', 'motivational') NOT NULL,
  `time` DATETIME NOT NULL,
  `message` MEDIUMTEXT NOT NULL,
  `is_sent` TINYINT NOT NULL,
  `is_dismissed` TINYINT NOT NULL,
  `User_idUser` INT NOT NULL,
  UNIQUE INDEX `idNotification_UNIQUE` (`idNotification` ASC),
  PRIMARY KEY (`idNotification`),
  INDEX `fk_Notification_User1_idx` (`User_idUser` ASC),
  CONSTRAINT `fk_Notification_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`InjuryType`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`InjuryType` (
  `idInjuryType` INT NOT NULL,
  `type_name` VARCHAR(45) NOT NULL,
  `description` VARCHAR(250) NOT NULL,
  `avg_healing_time_days` INT NOT NULL,
  PRIMARY KEY (`idInjuryType`),
  UNIQUE INDEX `idInjuryType_UNIQUE` (`idInjuryType` ASC),
  UNIQUE INDEX `type_name_UNIQUE` (`type_name` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`Injury`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`Injury` (
  `idInjury` INT NOT NULL,
  `injury_type` VARCHAR(100) NOT NULL,
  `affected_muscle_group` VARCHAR(100) NOT NULL,
  `severity` ENUM('mild', 'moderate', 'severe') NOT NULL,
  `start_date` DATE NOT NULL,
  `is_active` TINYINT NOT NULL,
  `User_idUser` INT NOT NULL,
  `InjuryType_idInjuryType` INT NOT NULL,
  UNIQUE INDEX `idInjury_UNIQUE` (`idInjury` ASC),
  PRIMARY KEY (`idInjury`),
  INDEX `fk_Injury_User1_idx` (`User_idUser` ASC),
  INDEX `fk_Injury_InjuryType1_idx` (`InjuryType_idInjuryType` ASC),
  CONSTRAINT `fk_Injury_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_Injury_InjuryType1`
    FOREIGN KEY (`InjuryType_idInjuryType`)
    REFERENCES `ERD_FitApp`.`InjuryType` (`idInjuryType`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`BodyMetrics`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`BodyMetrics` (
  `User_idUser` INT NOT NULL,
  `update_date` DATE NOT NULL,
  `weight` INT NOT NULL,
  `chest` DECIMAL(5,2) NULL,
  `waist` DECIMAL(5,2) NULL,
  `thigh` DECIMAL(5,2) NULL,
  `bicep` DECIMAL(5,2) NULL,
  `hip` DECIMAL(5,2) NULL,
  `calf` DECIMAL(5,2) NULL,
  `fat_percentage` DECIMAL(4,2) NULL,
  `recorded_at` DATETIME NOT NULL,
  PRIMARY KEY (`User_idUser`),
  INDEX `fk_BodyMetrics_User_idx` (`User_idUser` ASC),
  UNIQUE INDEX `User_idUser_UNIQUE` (`User_idUser` ASC),
  CONSTRAINT `fk_BodyMetrics_User`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`ProgressReport`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`ProgressReport` (
  `idProgressReport` INT NOT NULL,
  `report_period_start` DATE NOT NULL,
  `report_period_end` DATE NOT NULL,
  `raport_type` ENUM('weekly', 'monthly', 'custom') NOT NULL,
  `weight_difference` DECIMAL(5,2) NOT NULL,
  `training_volume` DECIMAL(6,2) NOT NULL,
  `training_sessions_completed` INT NOT NULL,
  `training_sessions_planned` INT NOT NULL,
  `avg_cals_daily` INT NOT NULL,
  `estimated_goal_completion_date` DATE NOT NULL,
  `generated` DATETIME NOT NULL,
  `User_idUser` INT NOT NULL,
  PRIMARY KEY (`idProgressReport`),
  UNIQUE INDEX `idProgressRaport_UNIQUE` (`idProgressReport` ASC),
  INDEX `fk_ProgressRaport_User1_idx` (`User_idUser` ASC),
  CONSTRAINT `fk_ProgressRaport_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`TrainingPlan`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`TrainingPlan` (
  `idTrainingPlan` INT NOT NULL,
  `plan_name` VARCHAR(45) NOT NULL,
  `goal` ENUM('weight_loss', 'muscle_gain', 'strength', 'maintenance', 'general_fitness', 'edurance') NOT NULL,
  `num_training_days` INT NOT NULL,
  `generated_at` DATETIME NOT NULL,
  `start_date` DATE NOT NULL,
  `end_date` DATE NOT NULL,
  `is_active` TINYINT NOT NULL,
  `User_idUser` INT NOT NULL,
  PRIMARY KEY (`idTrainingPlan`),
  UNIQUE INDEX `idTrainingPlan_UNIQUE` (`idTrainingPlan` ASC),
  INDEX `fk_TrainingPlan_User1_idx` (`User_idUser` ASC),
  CONSTRAINT `fk_TrainingPlan_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`TrainingSession`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`TrainingSession` (
  `idTrainingSession` INT NOT NULL,
  `session_order` INT NOT NULL,
  `day_of_week` ENUM('Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat') NOT NULL,
  `estimated_duration` INT NOT NULL,
  `TrainingPlan_idTrainingPlan` INT NOT NULL,
  PRIMARY KEY (`idTrainingSession`),
  UNIQUE INDEX `idTrainingSession_UNIQUE` (`idTrainingSession` ASC),
  INDEX `fk_TrainingSession_TrainingPlan1_idx` (`TrainingPlan_idTrainingPlan` ASC),
  CONSTRAINT `fk_TrainingSession_TrainingPlan1`
    FOREIGN KEY (`TrainingPlan_idTrainingPlan`)
    REFERENCES `ERD_FitApp`.`TrainingPlan` (`idTrainingPlan`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`Exercise`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`Exercise` (
  `idExercise` INT NOT NULL,
  `name` VARCHAR(45) NOT NULL,
  `main_muscle_group` VARCHAR(100) NOT NULL,
  `secondary_muscle_group` VARCHAR(150) NOT NULL,
  `difficulty_level` ENUM('beginner', 'intermediate', 'advanced') NOT NULL,
  `required_equipment` VARCHAR(250) NOT NULL,
  `description` MEDIUMTEXT NOT NULL,
  `instruction` MEDIUMTEXT NOT NULL,
  PRIMARY KEY (`idExercise`),
  UNIQUE INDEX `idExercise_UNIQUE` (`idExercise` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`SessionExercise`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`SessionExercise` (
  `idSessionExercise` INT NOT NULL,
  `planned_sets` INT NOT NULL,
  `planned_reps` INT NOT NULL,
  `weight` DECIMAL(5,2) NOT NULL,
  `rest_time` INT NOT NULL,
  `order` INT NOT NULL,
  `Exercise_idExercise` INT NOT NULL,
  `TrainingSession_idTrainingSession` INT NOT NULL,
  PRIMARY KEY (`idSessionExercise`),
  UNIQUE INDEX `idSessionExercise_UNIQUE` (`idSessionExercise` ASC),
  INDEX `fk_SessionExercise_Exercise1_idx` (`Exercise_idExercise` ASC),
  INDEX `fk_SessionExercise_TrainingSession1_idx` (`TrainingSession_idTrainingSession` ASC),
  CONSTRAINT `fk_SessionExercise_Exercise1`
    FOREIGN KEY (`Exercise_idExercise`)
    REFERENCES `ERD_FitApp`.`Exercise` (`idExercise`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_SessionExercise_TrainingSession1`
    FOREIGN KEY (`TrainingSession_idTrainingSession`)
    REFERENCES `ERD_FitApp`.`TrainingSession` (`idTrainingSession`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`PersonalRecord`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`PersonalRecord` (
  `idPersonalRecord` INT NOT NULL,
  `max_weight` DECIMAL(5,2) NOT NULL,
  `max_reps` INT NOT NULL,
  `achieved_date` DATE NOT NULL,
  `is_current` TINYINT NOT NULL,
  `Exercise_idExercise` INT NOT NULL,
  `User_idUser` INT NOT NULL,
  PRIMARY KEY (`idPersonalRecord`),
  UNIQUE INDEX `idPersonalRecords_UNIQUE` (`idPersonalRecord` ASC),
  INDEX `fk_PersonalRecord_Exercise1_idx` (`Exercise_idExercise` ASC),
  INDEX `fk_PersonalRecord_User1_idx` (`User_idUser` ASC),
  CONSTRAINT `fk_PersonalRecord_Exercise1`
    FOREIGN KEY (`Exercise_idExercise`)
    REFERENCES `ERD_FitApp`.`Exercise` (`idExercise`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_PersonalRecord_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`WorkoutLog`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`WorkoutLog` (
  `idWorkoutLog` INT NOT NULL,
  `log_date` DATE NOT NULL,
  `actual_sets` INT NOT NULL,
  `actual_reps` INT NOT NULL,
  `actual_weight` DECIMAL(5,2) NOT NULL,
  `rpe_rating` INT NOT NULL,
  `logged_at` DATETIME NOT NULL,
  `User_idUser` INT NOT NULL,
  `TrainingSession_idTrainingSession` INT NOT NULL,
  PRIMARY KEY (`idWorkoutLog`),
  INDEX `fk_WorkoutLog_User1_idx` (`User_idUser` ASC),
  INDEX `fk_WorkoutLog_TrainingSession1_idx` (`TrainingSession_idTrainingSession` ASC),
  CONSTRAINT `fk_WorkoutLog_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION ON UPDATE NO ACTION,
  CONSTRAINT `fk_WorkoutLog_TrainingSession1`
    FOREIGN KEY (`TrainingSession_idTrainingSession`)
    REFERENCES `ERD_FitApp`.`TrainingSession` (`idTrainingSession`)
    ON DELETE NO ACTION ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`RecognitionAI`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`RecognitionAI` (
  `idRecognitionAI` INT NOT NULL,
  `url_image` VARCHAR(250) NOT NULL,
  `upload_time` DATETIME NOT NULL,
  `recognised_items` JSON NOT NULL,
  `estimated_cals` INT NOT NULL,
  `estimated_protein` DECIMAL(6,2) NOT NULL,
  `estimated_fat` DECIMAL(6,2) NOT NULL,
  `estimated_carbs` DECIMAL(6,2) NOT NULL,
  `confidence_score` DECIMAL(3,2) NOT NULL,
  `was_edited` TINYINT NOT NULL,
  `user_approved` TINYINT NOT NULL,
  `logged_at` DATETIME NOT NULL,
  `User_idUser` INT NOT NULL,
  PRIMARY KEY (`idRecognitionAI`),
  UNIQUE INDEX `idRecognitionAI_UNIQUE` (`idRecognitionAI` ASC),
  INDEX `fk_RecognitionAI_User1_idx` (`User_idUser` ASC),
  CONSTRAINT `fk_RecognitionAI_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`DietPlan`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`DietPlan` (
  `idDietPlan` INT NOT NULL,
  `name` VARCHAR(45) NOT NULL,
  `goal` ENUM('weight_loss', 'muscle_gain', 'strength', 'maintenance', 'general_fitness', 'edurance') NOT NULL,
  `generated_at` DATETIME NOT NULL,
  `start_date` DATE NOT NULL,
  `end_date` DATE NOT NULL,
  `daily_cal_goal` INT NOT NULL,
  `protein_goal` DECIMAL(6,2) NOT NULL,
  `fat_goal` DECIMAL(6,2) NOT NULL,
  `carbs_goal` DECIMAL(6,2) NOT NULL,
  `is_active` TINYINT NOT NULL,
  `dietary_restrictions` VARCHAR(500) NOT NULL,
  `User_idUser` INT NOT NULL,
  PRIMARY KEY (`idDietPlan`),
  UNIQUE INDEX `idDietPlan_UNIQUE` (`idDietPlan` ASC),
  INDEX `fk_DietPlan_User1_idx` (`User_idUser` ASC),
  CONSTRAINT `fk_DietPlan_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`Meal`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`Meal` (
  `idMeal` INT NOT NULL,
  `meal_type` ENUM('breakfast', 'lunch', 'dinner', 'snack') NOT NULL,
  `meal_order` INT NOT NULL,
  `time` DATE NOT NULL,
  `planned_cals` INT NOT NULL,
  `planned_protein` DECIMAL(6,2) NOT NULL,
  `planned_fat` DECIMAL(6,2) NOT NULL,
  `planned_carbs` DECIMAL(6,2) NOT NULL,
  PRIMARY KEY (`idMeal`),
  UNIQUE INDEX `idMeal_UNIQUE` (`idMeal` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`FoodItem`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`FoodItem` (
  `idFoodItem` INT NOT NULL,
  `name` VARCHAR(45) NOT NULL,
  `cals_per_100g` DECIMAL(5,2) NOT NULL,
  `protein_per_100g` DECIMAL(5,2) NOT NULL,
  `fat_per_100g` DECIMAL(5,2) NOT NULL,
  `carbs_per_100g` DECIMAL(5,2) NOT NULL,
  `category` VARCHAR(45) NOT NULL,
  `Meal_idMeal` INT NOT NULL,
  `Meal_DietPlan_idDietPlan` INT NOT NULL,
  PRIMARY KEY (`idFoodItem`),
  UNIQUE INDEX `idFoodItem_UNIQUE` (`idFoodItem` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`NutritionLog`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`NutritionLog` (
  `idNutritionLog` INT NOT NULL,
  `log_date` DATE NOT NULL,
  `meal_type` ENUM('breakfast', 'lunch', 'dinner', 'snack') NOT NULL,
  `meal_photo_url` VARCHAR(250) NULL,
  `actual_cals` DECIMAL(6,2) NOT NULL,
  `actual_protein` DECIMAL(6,2) NOT NULL,
  `actual_fat` DECIMAL(6,2) NOT NULL,
  `actual_carbs` DECIMAL(6,2) NOT NULL,
  `hunger_level_before` INT NOT NULL,
  `hunger_level_after` INT NOT NULL,
  `logged_at` DATETIME NOT NULL,
  `User_idUser` INT NOT NULL,
  `RecognitionAI_idRecognitionAI` INT NOT NULL,
  PRIMARY KEY (`idNutritionLog`),
  UNIQUE INDEX `idNutritionLog_UNIQUE` (`idNutritionLog` ASC),
  INDEX `fk_NutritionLog_User1_idx` (`User_idUser` ASC),
  INDEX `fk_NutritionLog_RecognitionAI1_idx` (`RecognitionAI_idRecognitionAI` ASC),
  CONSTRAINT `fk_NutritionLog_User1`
    FOREIGN KEY (`User_idUser`)
    REFERENCES `ERD_FitApp`.`User` (`idUser`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_NutritionLog_RecognitionAI1`
    FOREIGN KEY (`RecognitionAI_idRecognitionAI`)
    REFERENCES `ERD_FitApp`.`RecognitionAI` (`idRecognitionAI`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`FoodCategory`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`FoodCategory` (
  `idFoodCategory` INT NOT NULL,
  `category_name` VARCHAR(45) NOT NULL,
  `description` VARCHAR(250) NOT NULL,
  PRIMARY KEY (`idFoodCategory`),
  UNIQUE INDEX `idFoodCategory_UNIQUE` (`idFoodCategory` ASC),
  UNIQUE INDEX `category_name_UNIQUE` (`category_name` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`MuscleGroup`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`MuscleGroup` (
  `idMuscleGroup` INT NOT NULL,
  `group_name` VARCHAR(45) NOT NULL,
  `description` VARCHAR(250) NOT NULL,
  `image_url` VARCHAR(100) NULL,
  PRIMARY KEY (`idMuscleGroup`),
  UNIQUE INDEX `idMuscleGroup_UNIQUE` (`idMuscleGroup` ASC),
  UNIQUE INDEX `group_name_UNIQUE` (`group_name` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`Exercise_has_MuscleGroup`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`Exercise_has_MuscleGroup` (
  `Exercise_idExercise` INT NOT NULL,
  `MuscleGroup_idMuscleGroup` INT NOT NULL,
  INDEX `fk_Exercise_has_MuscleGroup_MuscleGroup1_idx` (`MuscleGroup_idMuscleGroup` ASC),
  INDEX `fk_Exercise_has_MuscleGroup_Exercise1_idx` (`Exercise_idExercise` ASC),
  PRIMARY KEY (`Exercise_idExercise`, `MuscleGroup_idMuscleGroup`),
  CONSTRAINT `fk_Exercise_has_MuscleGroup_Exercise1`
    FOREIGN KEY (`Exercise_idExercise`)
    REFERENCES `ERD_FitApp`.`Exercise` (`idExercise`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_Exercise_has_MuscleGroup_MuscleGroup1`
    FOREIGN KEY (`MuscleGroup_idMuscleGroup`)
    REFERENCES `ERD_FitApp`.`MuscleGroup` (`idMuscleGroup`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`Meal_has_FoodItem`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`Meal_has_FoodItem` (
  `Meal_idMeal` INT NOT NULL,
  `FoodItem_idFoodItem` INT NOT NULL,
  INDEX `fk_Meal_has_FoodItem_FoodItem1_idx` (`FoodItem_idFoodItem` ASC),
  INDEX `fk_Meal_has_FoodItem_Meal1_idx` (`Meal_idMeal` ASC),
  PRIMARY KEY (`Meal_idMeal`, `FoodItem_idFoodItem`),
  CONSTRAINT `fk_Meal_has_FoodItem_Meal1`
    FOREIGN KEY (`Meal_idMeal`)
    REFERENCES `ERD_FitApp`.`Meal` (`idMeal`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_Meal_has_FoodItem_FoodItem1`
    FOREIGN KEY (`FoodItem_idFoodItem`)
    REFERENCES `ERD_FitApp`.`FoodItem` (`idFoodItem`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`NutritionLog_has_FoodItem`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`NutritionLog_has_FoodItem` (
  `NutritionLog_idNutritionLog` INT NOT NULL,
  `FoodItem_idFoodItem` INT NOT NULL,
  INDEX `fk_NutritionLog_has_FoodItem_FoodItem1_idx` (`FoodItem_idFoodItem` ASC),
  INDEX `fk_NutritionLog_has_FoodItem_NutritionLog1_idx` (`NutritionLog_idNutritionLog` ASC),
  PRIMARY KEY (`NutritionLog_idNutritionLog`, `FoodItem_idFoodItem`),
  CONSTRAINT `fk_NutritionLog_has_FoodItem_NutritionLog1`
    FOREIGN KEY (`NutritionLog_idNutritionLog`)
    REFERENCES `ERD_FitApp`.`NutritionLog` (`idNutritionLog`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_NutritionLog_has_FoodItem_FoodItem1`
    FOREIGN KEY (`FoodItem_idFoodItem`)
    REFERENCES `ERD_FitApp`.`FoodItem` (`idFoodItem`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`FoodCategory_has_FoodItem`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`FoodCategory_has_FoodItem` (
  `FoodCategory_idFoodCategory` INT NOT NULL,
  `FoodItem_idFoodItem` INT NOT NULL,
  INDEX `fk_FoodCategory_has_FoodItem_FoodItem1_idx` (`FoodItem_idFoodItem` ASC),
  INDEX `fk_FoodCategory_has_FoodItem_FoodCategory1_idx` (`FoodCategory_idFoodCategory` ASC),
  PRIMARY KEY (`FoodItem_idFoodItem`, `FoodCategory_idFoodCategory`),
  CONSTRAINT `fk_FoodCategory_has_FoodItem_FoodCategory1`
    FOREIGN KEY (`FoodCategory_idFoodCategory`)
    REFERENCES `ERD_FitApp`.`FoodCategory` (`idFoodCategory`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_FoodCategory_has_FoodItem_FoodItem1`
    FOREIGN KEY (`FoodItem_idFoodItem`)
    REFERENCES `ERD_FitApp`.`FoodItem` (`idFoodItem`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`WorkoutLog_has_Exercise`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`WorkoutLog_has_Exercise` (
  `WorkoutLog_idWorkoutLog` INT NOT NULL,
  `Exercise_idExercise` INT NOT NULL,
  INDEX `fk_WorkoutLog_has_Exercise_Exercise1_idx` (`Exercise_idExercise` ASC),
  INDEX `fk_WorkoutLog_has_Exercise_WorkoutLog1_idx` (`WorkoutLog_idWorkoutLog` ASC),
  PRIMARY KEY (`WorkoutLog_idWorkoutLog`, `Exercise_idExercise`),
  CONSTRAINT `fk_WorkoutLog_has_Exercise_WorkoutLog1`
    FOREIGN KEY (`WorkoutLog_idWorkoutLog`)
    REFERENCES `ERD_FitApp`.`WorkoutLog` (`idWorkoutLog`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_WorkoutLog_has_Exercise_Exercise1`
    FOREIGN KEY (`Exercise_idExercise`)
    REFERENCES `ERD_FitApp`.`Exercise` (`idExercise`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `ERD_FitApp`.`DietPlan_has_Meal`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `ERD_FitApp`.`DietPlan_has_Meal` (
  `DietPlan_idDietPlan` INT NOT NULL,
  `Meal_idMeal` INT NOT NULL,
  PRIMARY KEY (`DietPlan_idDietPlan`, `Meal_idMeal`),
  INDEX `fk_DietPlan_has_Meal_Meal1_idx` (`Meal_idMeal` ASC),
  INDEX `fk_DietPlan_has_Meal_DietPlan1_idx` (`DietPlan_idDietPlan` ASC),
  CONSTRAINT `fk_DietPlan_has_Meal_DietPlan1`
    FOREIGN KEY (`DietPlan_idDietPlan`)
    REFERENCES `ERD_FitApp`.`DietPlan` (`idDietPlan`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_DietPlan_has_Meal_Meal1`
    FOREIGN KEY (`Meal_idMeal`)
    REFERENCES `ERD_FitApp`.`Meal` (`idMeal`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


SET SQL_MODE=@OLD_SQL_MODE;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;