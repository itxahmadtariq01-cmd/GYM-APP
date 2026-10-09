from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone


class Permission(models.Model):
    name = models.CharField(max_length=100, unique=True)
    codename = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)
    permissions = models.ManyToManyField(Permission, blank=True)

    def __str__(self):
        return self.name


class Plan(models.Model):
    name = models.CharField(max_length=100)
    duration_type = models.CharField(max_length=20, choices=[('Monthly', 'Monthly'), ('Yearly', 'Yearly')])
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.duration_type}) - {self.price}"


class CustomUser(AbstractUser):
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Contact & Basic Info
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    admission_date = models.DateField(auto_now_add=True, null=True, blank=True)
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name='members')

    # --- BOSS REQUIREMENT: Extended Onboarding Profile Fields ---
    height = models.FloatField(blank=True, null=True)  # in cm or feet representation
    weight = models.FloatField(blank=True, null=True)  # in kg
    bmi = models.FloatField(blank=True, null=True)
    
    daily_activity_level = models.CharField(max_length=100, blank=True, null=True) # e.g., Sedentary, Moderate, Active
    exercise_experience = models.CharField(max_length=50, blank=True, null=True)   # Beginner / Intermediate / Expert
    training_frequency = models.CharField(max_length=100, blank=True, null=True)   # e.g., 3 days/week, 5 days/week
    preferred_muscle_split = models.CharField(max_length=150, blank=True, null=True) # e.g., Push/Pull/Legs, Bro Split
    cardio_routine = models.CharField(max_length=150, blank=True, null=True)        # e.g., 20 mins HIIT post workout
    core_focus = models.CharField(max_length=50, blank=True, null=True)            # e.g., Yes/No (Abs focus)
    current_body_type = models.CharField(max_length=100, blank=True, null=True)    # e.g., Skinny, Bulky, Average
    actual_goal = models.CharField(max_length=150, blank=True, null=True)          # e.g., Fat Loss, Muscle Hypertrophy
    target_duration_months = models.IntegerField(blank=True, null=True)            # e.g., 3 months
    normal_diet_routine = models.TextField(blank=True, null=True)                  # e.g., Home-cooked, High protein
    daily_general_activity = models.CharField(max_length=100, blank=True, null=True) # Sitting job vs Walking a lot
    
    # Flag to check if profile onboarding is complete
    is_profile_complete = models.BooleanField(default=False)

    def calculate_profile_completion(self):
        """Calculates profile completion percentage out of 100% based on onboarding fields."""
        fields_to_check = [
            self.height, self.weight, self.daily_activity_level, 
            self.exercise_experience, self.training_frequency, 
            self.preferred_muscle_split, self.current_body_type, 
            self.actual_goal, self.target_duration_months, 
            self.normal_diet_routine, self.daily_general_activity
        ]
        filled_count = sum(1 for f in fields_to_check if f is not None and str(f).strip() != "")
        total_fields = len(fields_to_check)
        percentage = int((filled_count / total_fields) * 100)
        return percentage

    def has_permission(self, codename):
        if not self.is_authenticated or not self.is_active:
            return False
        if self.is_superuser:
            return True

        app_permission = codename if '.' in codename else f'fitness.{codename}'
        if super().has_perm(app_permission):
            return True

        role_codename = codename.rsplit('.', 1)[-1]
        return bool(
            self.role_id
            and self.role.permissions.filter(codename=role_codename).exists()
        )


class TrainerProfile(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='trainer_profile',
    )
    years_experience = models.PositiveSmallIntegerField(blank=True, null=True)
    fitness_background = models.TextField(blank=True)
    expertise = models.TextField(blank=True)
    certifications = models.TextField(blank=True)

    def __str__(self):
        return f'Trainer profile: {self.user.username}'


class TrainerMemberAssignment(models.Model):
    trainer = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='member_assignments',
    )
    member = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='trainer_assignments',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('trainer', 'member'),
                name='unique_trainer_member_assignment',
            ),
        ]

    def clean(self):
        errors = {}
        if self.trainer_id:
            trainer = self.trainer
            if not trainer.role_id or trainer.role.name.lower() != 'trainer':
                errors['trainer'] = 'Assignments must belong to a trainer account.'
        if self.member_id:
            member = self.member
            if (
                member.is_staff
                or member.is_superuser
                or (member.role_id and member.role.name.lower() in {'admin', 'trainer'})
            ):
                errors['member'] = 'Assignments must target a gym member account.'
        if self.trainer_id and self.trainer_id == self.member_id:
            errors['member'] = 'A trainer cannot be assigned to themselves.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.trainer.username} -> {self.member.username}'


# Gym Core Models
class WorkoutPlan(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField()
    member = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='workout_plans')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.title} - {self.member.username}'

class DietPlan(models.Model):
    title = models.CharField(max_length=100)
    meal_details = models.TextField()
    member = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='diet_plans')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Diet: {self.title} - {self.member.username}'

class Attendance(models.Model):
    member = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=[('Present', 'Present'), ('Absent', 'Absent')])

    def __str__(self):
        return f'{self.member.username} - {self.date} ({self.status})'


# --- BOSS REQUIREMENT: Daily Logging Suites (Meal Logs & Workout Logs) ---
class MealLog(models.Model):
    MEAL_TYPE_CHOICES = [
        ('Breakfast', 'Breakfast'),
        ('Lunch', 'Lunch'),
        ('Dinner', 'Dinner'),
        ('Snack', 'Snack'),
        ('Custom', 'Custom'),
    ]

    member = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='meal_logs')
    date = models.DateField(default=timezone.localdate, db_index=True)
    meal_type = models.CharField(max_length=50, choices=MEAL_TYPE_CHOICES)
    description = models.TextField()
    receipt_image = models.ImageField(upload_to='meal_logs/', blank=True, null=True) # Meal photo
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member.username} - {self.meal_type} ({self.date})"


class WorkoutLog(models.Model):
    MUSCLE_SPLIT_CHOICES = [
        ('Chest', 'Chest'),
        ('Back', 'Back'),
        ('Legs', 'Legs'),
        ('Shoulders', 'Shoulders'),
        ('Arms', 'Arms'),
        ('Core', 'Core'),
        ('Push', 'Push'),
        ('Pull', 'Pull'),
        ('Full Body', 'Full Body'),
    ]

    member = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='workout_logs')
    date = models.DateField(default=timezone.localdate, db_index=True)
    did_workout = models.BooleanField(default=True)
    muscle_split = models.CharField(max_length=100, choices=MUSCLE_SPLIT_CHOICES, blank=True, null=True)
    exercise_details = models.TextField(blank=True, null=True)             # Sets, reps, weights notes or JSON structure
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = "Done" if self.did_workout else "Skipped"
        return f"{self.member.username} - {self.muscle_split} [{status}] ({self.date})"


class WorkoutExerciseLog(models.Model):
    EXERCISE_CHOICES = [
        ('Barbell Bench Press', 'Barbell Bench Press'),
        ('Incline Dumbbell Press', 'Incline Dumbbell Press'),
        ('Dumbbell Fly', 'Dumbbell Fly'),
        ('Push-up', 'Push-up'),
        ('Lat Pulldown', 'Lat Pulldown'),
        ('Barbell Row', 'Barbell Row'),
        ('Seated Cable Row', 'Seated Cable Row'),
        ('Assisted Pull-up', 'Assisted Pull-up'),
        ('Overhead Press', 'Overhead Press'),
        ('Dumbbell Lateral Raise', 'Dumbbell Lateral Raise'),
        ('Face Pull', 'Face Pull'),
        ('Barbell Squat', 'Barbell Squat'),
        ('Leg Press', 'Leg Press'),
        ('Romanian Deadlift', 'Romanian Deadlift'),
        ('Leg Curl', 'Leg Curl'),
        ('Walking Lunge', 'Walking Lunge'),
        ('Dumbbell Bicep Curl', 'Dumbbell Bicep Curl'),
        ('Triceps Cable Pushdown', 'Triceps Cable Pushdown'),
        ('Plank', 'Plank'),
        ('Cable Crunch', 'Cable Crunch'),
    ]
    REP_RANGE_CHOICES = [
        ('3-5', '3-5 reps'),
        ('6-8', '6-8 reps'),
        ('8-10', '8-10 reps'),
        ('10-12', '10-12 reps'),
        ('12-15', '12-15 reps'),
        ('15-20', '15-20 reps'),
        ('20-30', '20-30 reps'),
    ]

    workout = models.ForeignKey(WorkoutLog, on_delete=models.CASCADE, related_name='exercises')
    exercise_name = models.CharField(max_length=100, choices=EXERCISE_CHOICES)
    sets = models.PositiveSmallIntegerField()
    rep_range = models.CharField(max_length=10, choices=REP_RANGE_CHOICES)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ('position', 'pk')

    def __str__(self):
        return f'{self.exercise_name} - {self.sets} sets x {self.rep_range} reps'


class CardioLog(models.Model):
    ACTIVITY_CHOICES = [
        ('Treadmill', 'Treadmill'),
        ('Cycling', 'Cycling'),
        ('Elliptical', 'Elliptical'),
        ('Rowing', 'Rowing'),
        ('Stair Climber', 'Stair Climber'),
        ('Jump Rope', 'Jump Rope'),
        ('Outdoor Run', 'Outdoor Run'),
    ]
    INTENSITY_CHOICES = [
        ('Low', 'Low'),
        ('Moderate', 'Moderate'),
        ('High', 'High'),
    ]

    member = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='cardio_logs')
    date = models.DateField(default=timezone.localdate, db_index=True)
    activity = models.CharField(max_length=50, choices=ACTIVITY_CHOICES)
    duration_minutes = models.PositiveSmallIntegerField()
    intensity = models.CharField(max_length=20, choices=INTENSITY_CHOICES)
    notes = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.member.username} - {self.activity} ({self.date}, {self.duration_minutes} min)'


# Automated Welcome Email Signal
@receiver(post_save, sender=CustomUser)
def send_welcome_email(sender, instance, created, **kwargs):
    if created and instance.email:
        subject = 'Welcome to Gym Management System!'
        message = f"""
Hello {instance.username},

An account has been successfully created for you in the Gym Management System by the administrator.

Your Login Details:
Username: {instance.username}

You can access your portal here: http://127.0.0.1:8000/accounts/login/

Note: If this is your first time logging in or you don't remember your password, please contact the gym admin or use the password reset option.

Best regards,
Gym Management Team
        """
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [instance.email],
                fail_silently=False,
            )
        except Exception as e:
            print(f"Error sending email: {e}")


# Payment & Fee Management Model
class Payment(models.Model):
    member = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status_choices = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected')
    ]
    status = models.CharField(max_length=20, choices=status_choices, default='Pending')
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    receipt_image = models.ImageField(upload_to='payment_receipts/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.member.username} - {self.amount} ({self.status})"