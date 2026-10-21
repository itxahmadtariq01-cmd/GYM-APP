import json
import re
from datetime import timedelta
from decimal import Decimal
from html import escape as escape_html
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from .decorators import permission_required
from .models import (
    Attendance,
    CardioLog,
    CustomUser,
    DietPlan,
    MealLog,
    Payment,
    Role,
    TrainerMemberAssignment,
    TrainerProfile,
    WeightGoal,
    WeightLog,
    WaterLog,
    WorkoutExerciseLog,
    WorkoutLog,
    WorkoutPlan,
    WorkoutSplit,
    WorkoutSplitDay,
)
from .forms import (
    CustomUserCreationForm,
    TrainerAssignmentForm,
    TrainerOnboardingForm,
    TrainerProfileForm,
)
from google import genai
from .video_utils import youtube_embed_url

# Check if user is Admin or Staff
def is_admin(user):
    return user.is_authenticated and (
        user.is_staff
        or user.is_superuser
        or (getattr(user, 'role', None) and user.role.name.lower() == 'admin')
    )

# Check if user is Trainer
def is_trainer(user):
    return user.is_authenticated and hasattr(user, 'role') and user.role and user.role.name.lower() == 'trainer'

# Combined check for Admin or Trainer
def is_admin_or_trainer(user):
    return is_admin(user) or is_trainer(user)


class RoleBasedLoginView(LoginView):
    def get_default_redirect_url(self):
        if is_admin_or_trainer(self.request.user):
            return reverse('dashboard')
        return reverse('member_logging')


WORKOUT_MUSCLE_SPLITS = tuple(value for value, _ in WorkoutLog.MUSCLE_SPLIT_CHOICES)
WORKOUT_EXERCISES = tuple(value for value, _ in WorkoutExerciseLog.EXERCISE_CHOICES)
EXERCISE_GROUP_BY_NAME = {
    'Barbell Bench Press': 'Chest',
    'Incline Dumbbell Press': 'Chest',
    'Dumbbell Fly': 'Chest',
    'Push-up': 'Chest',
    'Lat Pulldown': 'Back',
    'Barbell Row': 'Back',
    'Seated Cable Row': 'Back',
    'Assisted Pull-up': 'Back',
    'Overhead Press': 'Shoulders',
    'Dumbbell Lateral Raise': 'Shoulders',
    'Face Pull': 'Shoulders',
    'Dumbbell Bicep Curl': 'Biceps',
    'Barbell Curl': 'Biceps',
    'Dumbbell Hammer Curl': 'Biceps',
    'Preacher Curl': 'Biceps',
    'Triceps Cable Pushdown': 'Triceps',
    'Skull Crushers': 'Triceps',
    'Dumbbell Overhead Triceps Extension': 'Triceps',
    'Barbell Squat': 'Legs',
    'Leg Press': 'Legs',
    'Romanian Deadlift': 'Legs',
    'Leg Curl': 'Legs',
    'Walking Lunge': 'Legs',
    'Plank': 'Core',
    'Cable Crunch': 'Core',
}
WORKOUT_EXERCISE_DESCRIPTIONS = {
    'Barbell Bench Press': 'Lower the bar under control to mid-chest, keep wrists stacked, and press without bouncing.',
    'Incline Dumbbell Press': 'Keep shoulder blades supported and lower dumbbells beside the upper chest before pressing.',
    'Dumbbell Fly': 'Use a soft elbow bend and a comfortable stretch; bring the weights together without turning it into a press.',
    'Push-up': 'Keep a straight line from head to heels and lower the chest between the hands.',
    'Lat Pulldown': 'Pull the bar toward the upper chest with elbows down; avoid leaning back to create momentum.',
    'Barbell Row': 'Hinge at the hips, brace the trunk, and row toward the lower ribs while keeping the back steady.',
    'Seated Cable Row': 'Sit tall, pull the handle to the torso, and let the shoulder blades reach forward under control.',
    'Assisted Pull-up': 'Start with arms extended, pull the chest toward the bar, and lower smoothly.',
    'Overhead Press': 'Brace the midsection and press overhead with the bar traveling close to the face.',
    'Dumbbell Lateral Raise': 'Raise the weights out to the sides with relaxed shoulders and a slight bend in the elbows.',
    'Face Pull': 'Pull the rope toward eye level and separate the hands while keeping elbows high.',
    'Barbell Curl': 'Stand tall with elbows close to your sides and curl the bar without swinging your torso.',
    'Dumbbell Hammer Curl': 'Keep palms facing each other, elbows close to your sides, and lower the dumbbells under control.',
    'Preacher Curl': 'Keep your upper arms supported on the pad and curl smoothly without lifting your elbows.',
    'Barbell Squat': 'Brace before descending, keep the whole foot grounded, and track knees in line with toes.',
    'Leg Press': 'Keep hips against the pad and lower only as far as you can without the lower back rounding.',
    'Romanian Deadlift': 'Push hips back with a soft knee bend and keep the weights close to the legs.',
    'Leg Curl': 'Keep hips settled on the pad and curl smoothly without lifting the pelvis.',
    'Walking Lunge': 'Take a stable step, lower both knees under control, and push through the front foot to stand.',
    'Dumbbell Bicep Curl': 'Keep elbows near the sides and curl without swinging the torso.',
    'Triceps Cable Pushdown': 'Pin elbows by the ribs and extend the arms fully without leaning over the cable.',
    'Skull Crushers': 'Keep upper arms steady and lower the weight toward the forehead before extending your elbows.',
    'Dumbbell Overhead Triceps Extension': 'Keep elbows pointing forward and lower the dumbbell behind your head with a controlled stretch.',
    'Plank': 'Stack shoulders over elbows and keep ribs, hips, and heels in one straight line.',
    'Cable Crunch': 'Curl the ribs toward the pelvis while keeping hips mostly still.',
}
WORKOUT_EXERCISE_VIDEO_URLS = {
    'Barbell Bench Press': 'https://www.youtube.com/watch?v=rT7DgCr-3pg',
    'Incline Dumbbell Press': 'https://www.youtube.com/watch?v=IP4oeKh1Sd4',
    'Dumbbell Fly': 'https://www.youtube.com/watch?v=eozdVDA78K0',
    'Push-up': 'https://www.youtube.com/watch?v=WDIpL0pjun0',
    'Lat Pulldown': 'https://www.youtube.com/watch?v=SALxEARiMkw',
    'Barbell Row': 'https://www.youtube.com/watch?v=RQU8wZPbioA',
    'Seated Cable Row': 'https://www.youtube.com/watch?v=xQNrFHEMhI4',
    'Assisted Pull-up': 'https://www.youtube.com/watch?v=wFj808u2HWU',
    'Overhead Press': 'https://www.youtube.com/watch?v=KP1sYz2VICk',
    'Dumbbell Lateral Raise': 'https://www.youtube.com/watch?v=XPPfnSEATJA',
    'Face Pull': 'https://www.youtube.com/watch?v=0Po47vvj9g4',
    'Dumbbell Bicep Curl': 'https://www.youtube.com/watch?v=sAq_ocpRh_I',
    'Barbell Curl': 'https://www.youtube.com/watch?v=kwG2ipFRgfo',
    'Dumbbell Hammer Curl': 'https://www.youtube.com/watch?v=zC3nLlEvin4',
    'Preacher Curl': 'https://www.youtube.com/watch?v=fIWP-FRFNU0',
    'Triceps Cable Pushdown': 'https://www.youtube.com/watch?v=-zLyUAo1gMw',
    'Skull Crushers': 'https://www.youtube.com/watch?v=d_KZxkY_0cM',
    'Dumbbell Overhead Triceps Extension': 'https://www.youtube.com/watch?v=YbX7Wd8jQ-Q',
    'Barbell Squat': 'https://www.youtube.com/watch?v=-bJIpOq-LWk',
    'Leg Press': 'https://www.youtube.com/watch?v=nDh_BlnLCGc',
    'Romanian Deadlift': 'https://www.youtube.com/watch?v=3VXmecChYYM',
    'Leg Curl': 'https://www.youtube.com/watch?v=t9sTSr-JYSs',
    'Walking Lunge': 'https://www.youtube.com/watch?v=tQNktxPkSeE',
    'Plank': 'https://www.youtube.com/watch?v=pvIjsG5Svck',
    'Cable Crunch': 'https://www.youtube.com/watch?v=3qjoXDTuyOE',
}
WORKOUT_EXERCISE_GUIDES = tuple(
    {
        'name': exercise,
        'description': WORKOUT_EXERCISE_DESCRIPTIONS[exercise],
        'muscle_group': EXERCISE_GROUP_BY_NAME[exercise],
        'embed_url': youtube_embed_url(WORKOUT_EXERCISE_VIDEO_URLS[exercise]),
    }
    for exercise in WORKOUT_EXERCISES
)
WORKOUT_SET_OPTIONS = tuple(str(value) for value in range(1, 11))
WORKOUT_REP_RANGES = tuple(value for value, _ in WorkoutExerciseLog.REP_RANGE_CHOICES)
CARDIO_ACTIVITIES = tuple(value for value, _ in CardioLog.ACTIVITY_CHOICES)
CARDIO_INTENSITIES = tuple(value for value, _ in CardioLog.INTENSITY_CHOICES)
CARDIO_EXERCISE_DESCRIPTIONS = {
    'Treadmill': 'Walk or jog at a pace you can maintain. Use the handrails only for balance, not to support your body weight.',
    'Cycling': 'Adjust the seat so your knee stays slightly bent at the bottom of each pedal stroke, then ride at a steady pace.',
    'Elliptical': 'Stand tall, keep a light grip, and move your arms and legs through a smooth, comfortable range.',
    'Rowing': 'Push with your legs first, lean back slightly, then bring the handle to your lower ribs. Reverse the order to return.',
    'Stair Climber': 'Stand tall and step at a steady pace. Avoid leaning heavily on the rails.',
    'Jump Rope': 'Keep jumps low, elbows close to your sides, and turn the rope with your wrists.',
    'Outdoor Run': 'Start at an easy pace, land lightly, and choose a route that matches your current fitness level.',
}
CARDIO_EXERCISE_VIDEO_URLS = {
    'Treadmill': 'https://www.youtube.com/watch?v=HxsFneJFM2c',
    'Cycling': 'https://www.youtube.com/watch?v=fQqndzvURAU',
    'Elliptical': 'https://www.youtube.com/watch?v=YWfswVvOaiI',
    'Rowing': 'https://www.youtube.com/watch?v=6_eLpWiNijE',
    'Stair Climber': 'https://www.youtube.com/watch?v=Zn1O9LcKW9E',
    'Jump Rope': 'https://www.youtube.com/watch?v=53Da1uyST48',
    'Outdoor Run': 'https://www.youtube.com/watch?v=_kGESn8ArrU',
}
CARDIO_EXERCISE_GUIDES = tuple(
    {
        'name': activity,
        'description': CARDIO_EXERCISE_DESCRIPTIONS[activity],
        'muscle_group': 'Cardio',
        'embed_url': youtube_embed_url(CARDIO_EXERCISE_VIDEO_URLS[activity]),
    }
    for activity in CARDIO_ACTIVITIES
)
ALL_EXERCISE_GUIDES = WORKOUT_EXERCISE_GUIDES + CARDIO_EXERCISE_GUIDES
DAILY_NUTRITION_TARGETS = {
    'calories': Decimal('2000'),
    'protein': Decimal('50'),
    'carbs': Decimal('275'),
    'fats': Decimal('78'),
}
DAILY_NUTRITION_LABELS = {
    'calories': ('Calories', 'kcal'),
    'protein': ('Protein', 'g'),
    'carbs': ('Carbohydrates', 'g'),
    'fats': ('Fat', 'g'),
}
EXERCISE_DIRECTORY_GROUPS = tuple(
    {
        'name': muscle_group,
        'slug': muscle_group.lower(),
        'exercises': tuple(
            guide for guide in ALL_EXERCISE_GUIDES
            if guide['muscle_group'] == muscle_group
        ),
    }
    for muscle_group in ('Chest', 'Back', 'Shoulders', 'Biceps', 'Triceps', 'Legs', 'Core', 'Cardio')
)
AI_WORKOUT_MUSCLE_GROUPS = (
    'Chest (Upper, Middle, Lower)',
    'Chest & Triceps',
    'Back & Biceps',
    'Shoulders & Abs',
    'Legs (Quads, Hamstrings, Calves)',
    'Arms (Biceps & Triceps Super-set)',
)


def _gym_members(user=None):
    members = CustomUser.objects.filter(
        is_staff=False,
        is_superuser=False,
    ).exclude(
        role__name__iexact='admin',
    ).exclude(
        role__name__iexact='trainer',
    )
    if user and is_trainer(user):
        members = members.filter(trainer_assignments__trainer=user)
    return members.order_by('username').distinct()


def _calculate_daily_nutrition(user, day=None):
    day = day or timezone.localdate()
    aggregates = MealLog.objects.filter(member=user, date=day).aggregate(
        **{f'{field}_total': Sum(field) for field in DAILY_NUTRITION_TARGETS}
    )
    totals = {
        field: aggregates[f'{field}_total'] or Decimal('0')
        for field in DAILY_NUTRITION_TARGETS
    }
    nutrients = []
    for field, target in DAILY_NUTRITION_TARGETS.items():
        label, unit = DAILY_NUTRITION_LABELS[field]
        achievement = round((totals[field] / target) * 100) if target else 0
        nutrients.append({
            'label': label,
            'total': totals[field],
            'target': target,
            'unit': unit,
            'achievement': achievement,
            'progress': min(achievement, 100),
        })

    calorie_gap = DAILY_NUTRITION_TARGETS['calories'] - totals['calories']
    return {
        'date': day,
        'nutrients': nutrients,
        'calorie_gap': abs(calorie_gap),
        'calorie_gap_type': 'deficit' if calorie_gap > 0 else 'surplus' if calorie_gap < 0 else 'on_target',
    }


def analyze_weekly_coaching(user, day=None):
    """Summarize the member's seven-day logged nutrition and weigh-in history."""
    today = day or timezone.localdate()
    start_date = today - timedelta(days=6)
    daily_intakes = list(
        MealLog.objects.filter(member=user, date__range=(start_date, today))
        .values('date')
        .annotate(
            calories=Sum('calories'),
            protein=Sum('protein'),
            carbs=Sum('carbs'),
            fats=Sum('fats'),
        )
        .order_by('date')
    )
    days_logged = len(daily_intakes)
    averages = {
        field: (
            sum((entry[field] or Decimal('0') for entry in daily_intakes), Decimal('0'))
            / days_logged
            if days_logged
            else Decimal('0')
        )
        for field in DAILY_NUTRITION_TARGETS
    }
    high_carb_days = sum(
        1 for entry in daily_intakes
        if (entry['carbs'] or Decimal('0')) > DAILY_NUTRITION_TARGETS['carbs']
    )
    weigh_ins = list(
        WeightLog.objects.filter(member=user, date__range=(start_date, today))
        .order_by('date', 'created_at')
        .values('date', 'weight_kg')
    )
    weight_change = (
        weigh_ins[-1]['weight_kg'] - weigh_ins[0]['weight_kg']
        if len(weigh_ins) >= 2
        else None
    )
    return {
        'start_date': start_date,
        'end_date': today,
        'days_logged': days_logged,
        'average_macros': averages,
        'high_carb_days': high_carb_days,
        'weigh_ins': weigh_ins,
        'weight_change': weight_change,
    }


def generate_coaching_recommendations(analysis):
    """Generate practical, privacy-preserving suggestions from weekly trends."""
    recommendations = []
    averages = analysis['average_macros']
    days_logged = analysis['days_logged']

    if not days_logged:
        recommendations.append(
            'Log meals with their macros this week to get nutrition suggestions based on your own patterns.'
        )
    else:
        if analysis['high_carb_days']:
            recommendations.append(
                f"Carbs were above the daily reference on {analysis['high_carb_days']} "
                f"of {days_logged} logged day(s). For dinner, try a protein-forward plate "
                "such as chicken, fish, tofu, or beans with vegetables, and keep starch portions comfortable."
            )
        if averages['protein'] < DAILY_NUTRITION_TARGETS['protein']:
            recommendations.append(
                'Your logged protein average is below the reference. Add a protein source '
                'to one meal, such as eggs, yogurt, lentils, tofu, fish, or chicken.'
            )
        if averages['calories'] > DAILY_NUTRITION_TARGETS['calories']:
            recommendations.append(
                'Logged calories averaged above the general reference. Review portions and '
                'calorie-dense drinks or snacks; avoid drastic cuts and use a personalized target if available.'
            )
        elif averages['calories'] < DAILY_NUTRITION_TARGETS['calories'] * Decimal('0.75'):
            recommendations.append(
                'Logged calories averaged well below the general reference. Check that meal '
                'entries are complete and that you are eating enough to support your activity.'
            )
        if not recommendations:
            recommendations.append(
                'Your logged intake is broadly within the general references. Keep recording meals '
                'and aim for a varied mix of protein, produce, and energy-giving foods.'
            )

    weight_change = analysis['weight_change']
    if weight_change is None:
        recommendations.append(
            'Record weigh-ins on a few different days to see a trend; a single reading cannot show a direction.'
        )
    elif abs(weight_change) >= Decimal('0.30'):
        direction = 'up' if weight_change > 0 else 'down'
        recommendations.append(
            f"Your recorded weight is {abs(weight_change):.2f} kg {direction} across this week. "
            'Daily weight can fluctuate; compare consistent morning readings over several weeks before adjusting your plan.'
        )

    return recommendations


# --- Public / Authentication Views ---
def signup_view(request):
    """Register a user, log them in, and send them through dashboard role routing."""
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            
            # Debugging check: Print email in console
            print(f"Registered User Email: {user.email}")
            
            # --- Welcome Email Dispatch Logic ---
            if user.email:
                try:
                    subject = 'Welcome to Caliber Labs — Operations Portal'
                    message = f'Hi {user.username},\n\nYour Caliber Labs account has been created. Open your dashboard to continue; member accounts will be guided through profile onboarding.\n\nBest regards,\nCaliber Labs Team'
                    sender = settings.DEFAULT_FROM_EMAIL
                    recipient = [user.email]
                    
                    send_mail(subject, message, sender, recipient, fail_silently=False)
                    print("Welcome email sent successfully!")
                except Exception as e:
                    print(f"Email sending failed: {e}")
            else:
                print("Error: User email is empty!")
            
            login(
                request,
                user,
                backend='django.contrib.auth.backends.ModelBackend',
            )
            return redirect('dashboard')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'fitness/signup.html', {'form': form})


@login_required
def dashboard_view(request):
    user = request.user
    
    # 1. If user is admin/staff, render the admin analytics dashboard
    if is_admin(user):
        return admin_dashboard_view(request)
    
    # 2. If user is a trainer, bypass onboarding completely and render trainer dashboard
    if is_trainer(user):
        assigned_members = _gym_members(user)
        workouts = WorkoutPlan.objects.filter(member__in=assigned_members)
        diets = DietPlan.objects.filter(member__in=assigned_members)
        attendances = Attendance.objects.filter(member__in=assigned_members)
        assigned_member_count = assigned_members.count()
        active_assigned_member_count = assigned_members.filter(is_active=True).count()

        members_list = assigned_members.order_by('-date_joined')
        search_query = request.GET.get('q', '')
        if search_query:
            members_list = members_list.filter(username__icontains=search_query) | members_list.filter(email__icontains=search_query)

        status_filter = request.GET.get('status', '')
        if status_filter == 'active':
            members_list = members_list.filter(is_active=True)
        elif status_filter == 'inactive':
            members_list = members_list.filter(is_active=False)

        paginator = Paginator(members_list, 5)
        members = paginator.get_page(request.GET.get('page'))

        context = {
            'role': 'Trainer',
            'workouts': workouts,
            'diets': diets,
            'attendances': attendances,
            'payments': Payment.objects.none(),
            'members': members,
            'assigned_member_count': assigned_member_count,
            'active_assigned_member_count': active_assigned_member_count,
            'workout_count': workouts.count(),
            'diet_count': diets.count(),
            'attendance_count': attendances.count(),
            'search_query': search_query,
            'status_filter': status_filter,
        }
        return render(request, 'fitness/dashboard.html', context)
    
    # 3. --- BOSS REQUIREMENT: Mandatory Onboarding Enforcement for Regular Members ---
    if not user.is_profile_complete:
        return redirect('complete_profile')
    
    # Any account not handled by the explicit Admin/Trainer branches is private to itself.
    workouts = WorkoutPlan.objects.filter(member=user)
    diets = DietPlan.objects.filter(member=user)
    attendances = Attendance.objects.filter(member=user)
    role = user.role.name if (user.role and hasattr(user.role, 'name')) else 'Member'

    # Fetch member payment history for profile tab
    payments = Payment.objects.filter(member=user).order_by('-created_at')
    workout_split = WorkoutSplit.objects.filter(member=user).prefetch_related('days').first()

    context = {
        'role': role,
        'workouts': workouts,
        'workout_split_title': workout_split.title if workout_split else None,
        'workout_split_schedule': _workout_split_schedule(workout_split),
        'diets': diets,
        'attendances': attendances,
        'payments': payments,
        'nutrition_summary': _calculate_daily_nutrition(user),
        'coaching_analysis': analyze_weekly_coaching(user),
        **_weight_tracking_context(user),
        'weight_goal_return_to': 'dashboard',
        'today': timezone.localdate().isoformat(),
    }
    context['coaching_recommendations'] = generate_coaching_recommendations(
        context['coaching_analysis']
    )
    return render(request, 'fitness/dashboard.html', context)


def _workout_split_schedule(split):
    if not split:
        return []

    schedule = []
    for day in split.days.all():
        exercises = [
            guide for guide in WORKOUT_EXERCISE_GUIDES
            if guide['muscle_group'] in day.muscle_groups
        ]
        schedule.append({
            'weekday': day.weekday,
            'day_name': day.get_weekday_display(),
            'muscle_groups': day.muscle_groups,
            'exercises': exercises,
        })
    return schedule


# --- BOSS REQUIREMENT: Mandatory Profile Completion View ---
@login_required
def complete_profile_view(request):
    user = request.user
    
    # Admin and Trainers do not need profile onboarding AT ALL (prevents redirect loops)
    if is_admin_or_trainer(user):
        return redirect('dashboard')
        
    # If regular member has already completed profile, stop loop and go to dashboard
    if user.is_profile_complete:
        return redirect('dashboard')
        
    if request.method == 'POST':
        user.height = request.POST.get('height')
        user.weight = request.POST.get('weight')
        user.daily_activity_level = request.POST.get('daily_activity_level')
        user.exercise_experience = request.POST.get('exercise_experience')
        user.training_frequency = request.POST.get('training_frequency')
        user.preferred_muscle_split = request.POST.get('preferred_muscle_split')
        user.cardio_routine = request.POST.get('cardio_routine')
        user.core_focus = request.POST.get('core_focus')
        user.current_body_type = request.POST.get('current_body_type')
        user.actual_goal = request.POST.get('actual_goal')
        user.target_duration_months = request.POST.get('target_duration_months')
        user.normal_diet_routine = request.POST.get('normal_diet_routine')
        user.daily_general_activity = request.POST.get('daily_general_activity')
        
        # Check completion percentage and update flag
        percentage = user.calculate_profile_completion()
        if percentage >= 80:  # Mark complete if profile completion is 80% or above
            user.is_profile_complete = True
            
        user.save()
        return redirect('dashboard')
        
    return render(request, 'fitness/complete_profile.html')


# Boss Requirement: Admin Dashboard & Analytics (Stats, Search, Filters, Pagination)
@user_passes_test(is_admin)
def admin_dashboard_view(request):
    # 1. Stats Calculations
    total_members = CustomUser.objects.filter(is_superuser=False).count()
    active_members = CustomUser.objects.filter(is_superuser=False, is_active=True).count()
    expired_memberships = CustomUser.objects.filter(is_superuser=False, is_active=False).count()
    
    # Total Revenue (Approved payments sum)
    total_revenue = Payment.objects.filter(status='Approved').aggregate(Sum('amount'))['amount__sum'] or 0.00
    
    # Unpaid Amount (Pending payments sum)
    unpaid_amount = Payment.objects.filter(status='Pending').aggregate(Sum('amount'))['amount__sum'] or 0.00

    # 2. Search & Filtering for Members List
    members_list = CustomUser.objects.filter(is_superuser=False).order_by('-date_joined')
    
    search_query = request.GET.get('q', '')
    if search_query:
        members_list = members_list.filter(username__icontains=search_query) | members_list.filter(email__icontains=search_query)

    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        members_list = members_list.filter(is_active=True)
    elif status_filter == 'inactive':
        members_list = members_list.filter(is_active=False)

    # 3. Pagination (5 members per page)
    paginator = Paginator(members_list, 5)
    page_number = request.GET.get('page')
    members = paginator.get_page(page_number)

    context = {
        'total_members': total_members,
        'active_members': active_members,
        'expired_memberships': expired_memberships,
        'total_revenue': total_revenue,
        'unpaid_amount': unpaid_amount,
        'attendances': Attendance.objects.all(),
        'members': members,
        'search_query': search_query,
        'status_filter': status_filter,
        'role': 'Admin',
    }

    return render(request, 'fitness/dashboard.html', context)


@login_required
@user_passes_test(is_admin)
def manage_trainers_view(request):
    trainer_role = Role.objects.filter(name__iexact='trainer').first()
    trainers = CustomUser.objects.none()
    if trainer_role:
        trainers = CustomUser.objects.filter(role=trainer_role).select_related(
            'trainer_profile',
        ).annotate(
            assigned_member_count=Count('member_assignments'),
        ).order_by('first_name', 'last_name', 'username')

    members = _gym_members().select_related('plan').order_by('username')
    trainer_form = TrainerOnboardingForm()
    profile_form = TrainerProfileForm()
    assignment_form = TrainerAssignmentForm(trainers=trainers, members=members)
    trainer_id = request.GET.get('trainer_id', '')
    selected_trainer = trainers.filter(pk=trainer_id).first() if trainer_id.isdecimal() else None
    selected_member_ids = set()

    if request.method == 'POST' and request.POST.get('action') == 'create_trainer':
        trainer_form = TrainerOnboardingForm(request.POST)
        profile_form = TrainerProfileForm(request.POST)
        if trainer_form.is_valid() and profile_form.is_valid():
            with transaction.atomic():
                if trainer_role is None:
                    trainer_role = Role.objects.create(name='Trainer')
                trainer = trainer_form.save(commit=False)
                trainer.role = trainer_role
                trainer.is_staff = False
                trainer.is_superuser = False
                trainer.save()
                trainer_profile = profile_form.save(commit=False)
                trainer_profile.user = trainer
                trainer_profile.save()
            messages.success(request, f'Trainer account created for {trainer.get_full_name() or trainer.username}.')
            return redirect(f"{reverse('manage_trainers')}?trainer_id={trainer.pk}")
        messages.error(request, 'Review the trainer details and correct the highlighted fields.')

    elif request.method == 'POST' and request.POST.get('action') == 'save_assignments':
        assignment_form = TrainerAssignmentForm(
            request.POST,
            trainers=trainers,
            members=members,
        )
        if assignment_form.is_valid():
            selected_trainer = assignment_form.cleaned_data['trainer']
            selected_member_ids = {
                member.pk for member in assignment_form.cleaned_data['members']
            }
            current_assignments = TrainerMemberAssignment.objects.filter(
                trainer=selected_trainer,
            )
            existing_member_ids = set(
                current_assignments.values_list('member_id', flat=True)
            )
            with transaction.atomic():
                current_assignments.exclude(member_id__in=selected_member_ids).delete()
                TrainerMemberAssignment.objects.filter(
                    member_id__in=selected_member_ids,
                ).exclude(trainer=selected_trainer).delete()
                TrainerMemberAssignment.objects.bulk_create([
                    TrainerMemberAssignment(trainer=selected_trainer, member_id=member_id)
                    for member_id in selected_member_ids - existing_member_ids
                ])
            messages.success(
                request,
                f'Assignments saved for {selected_trainer.get_full_name() or selected_trainer.username}.',
            )
            return redirect(f"{reverse('manage_trainers')}?trainer_id={selected_trainer.pk}")
        try:
            selected_trainer = trainers.get(pk=request.POST.get('trainer'))
        except (CustomUser.DoesNotExist, TypeError, ValueError):
            selected_trainer = None
        messages.error(request, 'Choose a valid trainer and review the selected members.')

    if selected_trainer is None and request.method == 'GET':
        selected_trainer = trainers.first()
    if selected_trainer and not assignment_form.is_bound:
        selected_member_ids = set(
            selected_trainer.member_assignments.values_list('member_id', flat=True)
        )
        assignment_form = TrainerAssignmentForm(
            trainers=trainers,
            members=members,
            initial={
                'trainer': selected_trainer.pk,
                'members': selected_trainer.member_assignments.values_list('member_id', flat=True),
            },
        )
    elif assignment_form.is_bound:
        valid_member_ids = set(members.values_list('pk', flat=True))
        selected_member_ids = {
            int(member_id)
            for member_id in request.POST.getlist('members')
            if member_id.isdecimal() and int(member_id) in valid_member_ids
        }

    context = {
        'role': 'Admin',
        'trainers': trainers,
        'members': members,
        'selected_trainer': selected_trainer,
        'selected_member_ids': selected_member_ids,
        'trainer_form': trainer_form,
        'profile_form': profile_form,
        'assignment_form': assignment_form,
    }
    return render(request, 'fitness/manage_trainers.html', context)


# Admin Member Detail View (Fixes the previous AttributeError)
# Pehle yahan sirf admin tha:
# @user_passes_test(is_admin)

# Ab isay yeh kar dein:
def _member_daily_report_data(member, newest_first=True):
    meal_logs = MealLog.objects.filter(member=member).order_by('-date', '-created_at')
    workout_logs = WorkoutLog.objects.filter(member=member).prefetch_related('exercises').order_by('-date', '-created_at')
    cardio_logs = CardioLog.objects.filter(member=member).order_by('-date', '-created_at')
    activity_by_date = {}
    for key, logs in (
        ('meals', meal_logs),
        ('workouts', workout_logs),
        ('cardio', cardio_logs),
    ):
        for log in logs:
            activity_by_date.setdefault(log.date, {'meals': [], 'workouts': [], 'cardio': []})[key].append(log)
    daily_activity = [
        {'date': log_date, **activity}
        for log_date, activity in sorted(activity_by_date.items(), reverse=newest_first)
    ]

    return {
        'meal_logs': meal_logs,
        'workout_logs': workout_logs,
        'cardio_logs': cardio_logs,
        'daily_activity': daily_activity,
        'summary': {
            'meal_count': meal_logs.count(),
            'workout_count': workout_logs.count(),
            'cardio_count': cardio_logs.count(),
            'cardio_minutes': sum(session.duration_minutes for session in cardio_logs),
        },
    }


def _weight_chart_data(member, goal=None):
    today = timezone.localdate()
    start_date = today - timedelta(days=29)
    if goal:
        start_date = min(start_date, goal.start_date)
    return [
        {
            'date': entry.date.isoformat(),
            'weight_kg': float(entry.weight_kg),
        }
        for entry in WeightLog.objects.filter(
            member=member,
            date__range=(start_date, today),
        ).order_by('date', 'created_at')
    ]


def _weight_tracking_context(member):
    today = timezone.localdate()
    goal = WeightGoal.objects.filter(member=member).first()
    latest_weight = (
        WeightLog.objects.filter(member=member, date__lte=today)
        .order_by('-date', '-created_at')
        .first()
    )
    goal_chart_data = None
    goal_progress = None

    if goal:
        goal_chart_data = {
            'start_date': goal.start_date.isoformat(),
            'starting_weight_kg': float(goal.starting_weight_kg),
            'target_date': goal.target_date.isoformat(),
            'target_weight_kg': float(goal.target_weight_kg),
        }

        if latest_weight:
            total_days = (goal.target_date - goal.start_date).days
            elapsed_days = min(max((today - goal.start_date).days, 0), total_days)
            weight_delta = goal.target_weight_kg - goal.starting_weight_kg
            next_milestone_days = min(
                (elapsed_days // 7 + 1) * 7,
                total_days,
            )
            next_milestone_date = goal.start_date + timedelta(days=next_milestone_days)
            next_milestone_weight = goal.starting_weight_kg + (
                weight_delta * Decimal(next_milestone_days) / Decimal(total_days)
            )
            expected_weight = goal.starting_weight_kg + (
                weight_delta * Decimal(elapsed_days) / Decimal(total_days)
            )
            progress = (
                (latest_weight.weight_kg - goal.starting_weight_kg)
                / weight_delta
                * Decimal('100')
            )
            ahead_delta = (
                expected_weight - latest_weight.weight_kg
                if weight_delta < 0
                else latest_weight.weight_kg - expected_weight
            )
            if ahead_delta > Decimal('0.05'):
                pace_status = 'ahead of'
            elif ahead_delta < Decimal('-0.05'):
                pace_status = 'behind'
            else:
                pace_status = 'on'

            goal_progress = {
                'current_weight_kg': latest_weight.weight_kg,
                'expected_weight_kg': expected_weight.quantize(Decimal('0.01')),
                'remaining_kg': abs(goal.target_weight_kg - latest_weight.weight_kg).quantize(Decimal('0.01')),
                'progress_percent': min(max(round(progress), 0), 100),
                'weekly_pace_kg': (
                    abs(weight_delta) * Decimal('7') / Decimal(total_days)
                ).quantize(Decimal('0.01')),
                'weight_direction': 'loss' if weight_delta < 0 else 'gain',
                'next_milestone_date': next_milestone_date,
                'next_milestone_weight_kg': next_milestone_weight.quantize(Decimal('0.01')),
                'pace_status': pace_status,
                'pace_difference_kg': abs(ahead_delta).quantize(Decimal('0.01')),
            }

    return {
        'weight_goal': goal,
        'weight_goal_chart_data': goal_chart_data,
        'weight_goal_progress': goal_progress,
        'weight_goal_latest_weight': latest_weight,
        'weight_chart_data': _weight_chart_data(member, goal),
        **_daily_intake_summary(member),
        'default_weight_goal_date': (today + timedelta(days=90)).isoformat(),
        'tomorrow': (today + timedelta(days=1)).isoformat(),
    }


def _daily_intake_summary(member):
    today = timezone.localdate()
    calories = MealLog.objects.filter(member=member, date=today).aggregate(
        total=Sum('calories'),
    )['total'] or Decimal('0')
    water = WaterLog.objects.filter(member=member, date=today).values_list(
        'liters',
        flat=True,
    ).first() or Decimal('0')
    calorie_target = DAILY_NUTRITION_TARGETS['calories']
    return {
        'daily_calorie_total': calories,
        'daily_calorie_target': calorie_target,
        'daily_calorie_progress': min(round(calories / calorie_target * 100), 100),
        'daily_water_liters': water,
    }


@user_passes_test(is_admin_or_trainer)
def admin_member_detail_view(request, user_id):
    member = get_object_or_404(_gym_members(request.user), id=user_id)
    payments = Payment.objects.filter(member=member).order_by('-created_at')
    workouts = WorkoutPlan.objects.filter(member=member)
    diets = DietPlan.objects.filter(member=member)
    daily_report = _member_daily_report_data(member)
    
    context = {
        'member': member,
        'payments': payments,
        'workouts': workouts,
        'diets': diets,
        'role': 'Trainer' if is_trainer(request.user) else 'Admin',
        'weight_chart_data': _weight_chart_data(member),
        'today': timezone.localdate().isoformat(),
        **_daily_intake_summary(member),
    }
    context.update(daily_report)
    return render(request, 'fitness/admin_member_detail.html', context)


@login_required
def weight_goal_view(request):
    if request.method != 'POST':
        return redirect('dashboard')
    if is_admin_or_trainer(request.user):
        messages.error(request, 'Weight goals are available from member accounts.')
        return redirect('dashboard')
    if not request.user.is_profile_complete:
        return redirect('complete_profile')

    redirect_to = (
        'member_logging'
        if request.POST.get('return_to') == 'member_logging'
        else 'dashboard'
    )
    if request.POST.get('action') == 'clear':
        WeightGoal.objects.filter(member=request.user).delete()
        messages.success(request, 'Your weight goal has been removed.')
        return redirect(redirect_to)

    today = timezone.localdate()
    starting_log = (
        WeightLog.objects.filter(member=request.user, date__lte=today)
        .order_by('-date', '-created_at')
        .first()
    )
    if not starting_log:
        messages.error(request, 'Log a weigh-in before setting a weight goal.')
        return redirect(redirect_to)

    try:
        target_weight = WeightGoal._meta.get_field('target_weight_kg').clean(
            request.POST.get('target_weight_kg', ''),
            None,
        )
    except ValidationError:
        messages.error(request, 'Enter a valid target weight greater than zero.')
        return redirect(redirect_to)

    target_date = _parse_log_date(request.POST.get('target_date'))
    if not target_date or target_date <= today:
        messages.error(request, 'Choose a target date in the future.')
        return redirect(redirect_to)

    goal = WeightGoal.objects.filter(member=request.user).first()
    if goal is None:
        goal = WeightGoal(member=request.user)
    goal.starting_weight_kg = starting_log.weight_kg
    goal.target_weight_kg = target_weight
    goal.start_date = starting_log.date
    goal.target_date = target_date
    try:
        goal.full_clean()
    except ValidationError as error:
        for field_errors in error.message_dict.values():
            for message in field_errors:
                messages.error(request, message)
        return redirect(redirect_to)
    goal.save()
    messages.success(request, 'Your weight goal and weekly milestones have been updated.')
    return redirect(redirect_to)


@login_required
def weight_log_view(request):
    if request.method != 'POST':
        return redirect('dashboard')
    if is_admin_or_trainer(request.user):
        messages.error(request, 'Weight check-ins are available from member accounts.')
        return redirect('dashboard')

    log_date = _parse_log_date(request.POST.get('log_date'))
    if not log_date:
        messages.error(request, 'Choose a valid date for your weigh-in.')
        return redirect('dashboard')
    try:
        weight_kg = WeightLog._meta.get_field('weight_kg').clean(
            request.POST.get('weight_kg', ''),
            None,
        )
    except ValidationError:
        messages.error(request, 'Enter a valid weight greater than zero.')
        return redirect('dashboard')

    WeightLog.objects.update_or_create(
        member=request.user,
        date=log_date,
        defaults={'weight_kg': weight_kg},
    )
    messages.success(request, 'Your weigh-in has been saved.')
    return redirect('dashboard')

@login_required
@user_passes_test(is_admin_or_trainer)
def member_daily_report_view(request, user_id):
    member = get_object_or_404(_gym_members(request.user), id=user_id)
    context = {
        'member': member,
        'role': 'Trainer' if is_trainer(request.user) else 'Admin',
        **_member_daily_report_data(member, newest_first=False),
    }
    return render(request, 'fitness/member_daily_report.html', context)


# Step 3: Member Portal & Payment Proof Submission View
@login_required
def member_profile_view(request):
    user = request.user
    
    if is_admin_or_trainer(user):
        return redirect('dashboard')
        
    if request.method == 'POST':
        amount = request.POST.get('amount')
        bank_name = request.POST.get('bank_name')
        transaction_id = request.POST.get('transaction_id')
        receipt_image = request.FILES.get('receipt_image')
        
        Payment.objects.create(
            member=user,
            amount=amount,
            bank_name=bank_name,
            transaction_id=transaction_id,
            receipt_image=receipt_image,
            status='Pending'
        )
        return redirect('dashboard')

    return redirect('dashboard')


# Step 3 (Cont.): Admin Payment Review & Approval Panel View
@user_passes_test(is_admin)
def admin_payments_view(request):
    payments = Payment.objects.all().order_by('-created_at')
    
    if request.method == 'POST':
        payment_id = request.POST.get('payment_id')
        action = request.POST.get('action') # 'Approve' or 'Reject'
        
        payment_obj = get_object_or_404(Payment, id=payment_id)
        if action == 'Approve':
            payment_obj.status = 'Approved'
            payment_obj.save()
        elif action == 'Reject':
            payment_obj.status = 'Rejected'
            payment_obj.save()
            
        return redirect('admin_payments')

    context = {
        'payments': payments,
        'role': 'Admin',
    }
    return render(request, 'fitness/admin_payments.html', context)


# Toggle a gym member's active status without modifying the authenticated operator.
@login_required
@user_passes_test(is_admin_or_trainer)
def toggle_member_status(request, user_id):
    if request.method != 'POST':
        return redirect('dashboard')

    member_obj = get_object_or_404(_gym_members(request.user), pk=user_id)
    member_obj.is_active = not member_obj.is_active
    member_obj.save(update_fields=['is_active'])

    return_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(
        return_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return_url = f"{reverse('dashboard')}#tab-users"
    return redirect(return_url)


@login_required
@user_passes_test(is_admin_or_trainer)
def manage_workouts_view(request):
    members = _gym_members(request.user)
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        try:
            member_obj = members.get(pk=request.POST.get('member_id'))
            WorkoutPlan.objects.create(title=title, description=description, member=member_obj)
            return redirect('manage_workouts')
        except (CustomUser.DoesNotExist, TypeError, ValueError):
            pass
            
    workouts = WorkoutPlan.objects.filter(member__in=members)
    return render(request, 'fitness/manage_workouts.html', {'workouts': workouts, 'members': members})


@login_required
@user_passes_test(is_admin_or_trainer)
def manage_diets_view(request):
    members = _gym_members(request.user)
    if request.method == 'POST':
        title = request.POST.get('title')
        meal_details = request.POST.get('description')
        try:
            member_obj = members.get(pk=request.POST.get('member_id'))
            DietPlan.objects.create(title=title, meal_details=meal_details, member=member_obj)
            return redirect('manage_diets')
        except (CustomUser.DoesNotExist, TypeError, ValueError):
            pass
            
    diets = DietPlan.objects.filter(member__in=members)
    return render(request, 'fitness/manage_diets.html', {'diets': diets, 'members': members})


@login_required
@user_passes_test(is_admin_or_trainer)
def manage_attendance_view(request):
    members = _gym_members(request.user)
    search_query = request.GET.get('q', '').strip()
    if search_query:
        members = members.filter(
            Q(username__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(email__icontains=search_query)
        )
    members = members.annotate(
        attendance_count=Count('attendances'),
        present_count=Count('attendances', filter=Q(attendances__status='Present')),
    )

    selected_member = None
    monthly_records = []
    member_id = request.GET.get('member_id')
    if member_id:
        selected_member = get_object_or_404(_gym_members(request.user), pk=member_id)
        records_by_month = {}
        for record in Attendance.objects.filter(member=selected_member).order_by('-date', '-pk'):
            month = record.date.replace(day=1)
            records_by_month.setdefault(month, []).append(record)
        monthly_records = [
            {
                'month': month,
                'records': records,
                'present_count': sum(record.status == 'Present' for record in records),
                'absent_count': sum(record.status == 'Absent' for record in records),
            }
            for month, records in sorted(records_by_month.items(), reverse=True)
        ]

    date_value = request.POST.get('date') if request.method == 'POST' else request.GET.get('date')
    try:
        parsed_date = parse_date(date_value or '')
    except ValueError:
        parsed_date = None
    selected_date = parsed_date or timezone.localdate()
    error = None

    if request.method == 'POST':
        if not parsed_date:
            error = 'Choose a valid attendance date.'
        else:
            attendance_updates = []
            for member in members:
                status = request.POST.get(f'attendance_{member.pk}')
                if status not in {'Present', 'Absent'}:
                    error = 'Choose Present or Absent for every member before submitting.'
                    break
                attendance_updates.append((member, status))

            if not error and not attendance_updates:
                error = 'There are no gym members to update.'

            if not error:
                with transaction.atomic():
                    for member, status in attendance_updates:
                        existing_records = Attendance.objects.filter(member=member, date=selected_date)
                        if not existing_records.update(status=status):
                            Attendance.objects.create(
                                member=member,
                                date=selected_date,
                                status=status,
                            )

                messages.success(
                    request,
                    f'Attendance saved for {len(attendance_updates)} members on {selected_date:%B %d, %Y}.',
                )
                return redirect(f"{reverse('manage_attendance')}?date={selected_date.isoformat()}")

    attendance_statuses = {
        attendance.member_id: attendance.status
        for attendance in Attendance.objects.filter(
            member__in=members,
            date=selected_date,
        ).order_by('pk')
    }
    for member in members:
        member.attendance_status = attendance_statuses.get(member.pk, 'Present')

    context = {
        'members': members,
        'search_query': search_query,
        'selected_member': selected_member,
        'monthly_records': monthly_records,
        'selected_date': selected_date.isoformat(),
        'error': error,
        'role': 'Trainer' if is_trainer(request.user) else 'Admin',
    }
    return render(request, 'fitness/manage_attendance.html', context)


# --- BOSS REQUIREMENT: Member Daily Tracking & Logging Suite ---
def _parse_log_date(value):
    try:
        return parse_date(value or '')
    except ValueError:
        return None


@login_required
def workout_split_builder_view(request):
    user = request.user
    if is_admin_or_trainer(user):
        return redirect('dashboard')
    if not user.is_profile_complete:
        return redirect('complete_profile')

    split = WorkoutSplit.objects.filter(member=user).prefetch_related('days').first()
    error = None
    title = split.title if split else 'My weekly split'

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        raw_split = request.POST.get('split_data', '')
        try:
            submitted_days = json.loads(raw_split)
        except (TypeError, ValueError):
            submitted_days = None

        valid_groups = {value for value, _ in WorkoutSplitDay.MUSCLE_GROUP_CHOICES}
        validated_days = {}
        if not title or len(title) > 100:
            error = 'Enter a split name of 1 to 100 characters.'
        elif not isinstance(submitted_days, dict):
            error = 'Choose at least one training day and muscle target.'
        else:
            for raw_weekday, groups in submitted_days.items():
                try:
                    weekday = int(raw_weekday)
                except (TypeError, ValueError):
                    error = 'One or more selected days is invalid.'
                    break
                if (
                    weekday not in dict(WorkoutSplitDay.WEEKDAY_CHOICES)
                    or str(weekday) != raw_weekday
                    or weekday in validated_days
                    or not isinstance(groups, list)
                    or not groups
                    or any(not isinstance(group, str) for group in groups)
                    or len(groups) != len(set(groups))
                    or not set(groups).issubset(valid_groups)
                ):
                    error = 'Each scheduled day needs valid, non-duplicate muscle targets.'
                    break
                validated_days[weekday] = groups
            if not error and not validated_days:
                error = 'Choose at least one training day and muscle target.'

        if not error:
            with transaction.atomic():
                split, _ = WorkoutSplit.objects.get_or_create(
                    member=user,
                    defaults={'title': title},
                )
                if split.title != title:
                    split.title = title
                    split.save(update_fields=['title', 'updated_at'])
                split.days.exclude(weekday__in=validated_days).delete()
                for weekday, groups in validated_days.items():
                    day, _ = WorkoutSplitDay.objects.update_or_create(
                        split=split,
                        weekday=weekday,
                        defaults={'muscle_groups': groups},
                    )
                    day.full_clean()
                    day.save(update_fields=['muscle_groups'])
            messages.success(request, 'Your weekly workout split has been saved.')
            return redirect('dashboard')

    split = WorkoutSplit.objects.filter(member=user).prefetch_related('days').first()
    split_data = {
        str(day.weekday): day.muscle_groups
        for day in split.days.all()
    } if split else {}
    return render(request, 'fitness/workout_split.html', {
        'role': 'Member',
        'split_title': title,
        'split_data': split_data,
        'workout_split_schedule': _workout_split_schedule(split),
        'muscle_groups': WorkoutSplitDay.MUSCLE_GROUP_CHOICES,
        'weekday_choices': WorkoutSplitDay.WEEKDAY_CHOICES,
        'exercise_guides': WORKOUT_EXERCISE_GUIDES,
        'split_error': error,
    })


@login_required
def member_logging_view(request):
    user = request.user
    
    if is_admin_or_trainer(user):
        return redirect('dashboard')
        
    if not user.is_profile_complete:
        return redirect('complete_profile')
        
    if request.method == 'POST':
        log_type = request.POST.get('log_type')
        log_date = _parse_log_date(request.POST.get('log_date'))
        if not log_date:
            messages.error(request, 'Choose a valid date for this daily log.')
            return redirect('member_logging')

        if log_type == 'meal':
            meal_type = request.POST.get('meal_type')
            description = request.POST.get('description', '').strip()
            receipt_image = request.FILES.get('receipt_image')
            if meal_type not in dict(MealLog.MEAL_TYPE_CHOICES) or not description:
                messages.error(request, 'Choose a meal type and enter a meal description.')
                return redirect('member_logging')

            try:
                nutrients = {
                    field: MealLog._meta.get_field(field).clean(request.POST.get(field) or '0', None)
                    for field in DAILY_NUTRITION_TARGETS
                }
            except ValidationError:
                messages.error(request, 'Enter valid non-negative values for calories and macros.')
                return redirect('member_logging')

            MealLog.objects.create(
                member=user,
                date=log_date,
                meal_type=meal_type,
                description=description,
                **nutrients,
                receipt_image=receipt_image,
            )
            return redirect('member_logging')

        if log_type == 'weight':
            notes = request.POST.get('notes', '').strip()
            if len(notes) > 2000:
                messages.error(request, 'Keep weigh-in notes under 2,000 characters.')
                return redirect('member_logging')
            try:
                weight_kg = WeightLog._meta.get_field('weight_kg').clean(
                    request.POST.get('weight_kg', ''),
                    None,
                )
            except ValidationError:
                messages.error(request, 'Enter a valid weight greater than zero.')
                return redirect('member_logging')

            WeightLog.objects.update_or_create(
                member=user,
                date=log_date,
                defaults={'weight_kg': weight_kg, 'notes': notes},
            )
            return redirect('member_logging')

        if log_type == 'water':
            notes = request.POST.get('notes', '').strip()
            if len(notes) > 2000:
                messages.error(request, 'Keep water intake notes under 2,000 characters.')
                return redirect('member_logging')
            try:
                liters = WaterLog._meta.get_field('liters').clean(
                    request.POST.get('liters', ''),
                    None,
                )
            except ValidationError:
                messages.error(request, 'Enter a valid daily water intake between 0.01 and 99.99 liters.')
                return redirect('member_logging')

            WaterLog.objects.update_or_create(
                member=user,
                date=log_date,
                defaults={'liters': liters, 'notes': notes},
            )
            return redirect('member_logging')

        if log_type == 'workout':
            did_workout_val = request.POST.get('did_workout')
            if did_workout_val not in {'yes', 'no'}:
                messages.error(request, 'Choose whether you completed a workout or took a rest day.')
                return redirect('member_logging')

            did_workout = did_workout_val == 'yes'
            notes = request.POST.get('notes', '').strip()
            if len(notes) > 2000:
                messages.error(request, 'Keep workout notes under 2,000 characters.')
                return redirect('member_logging')
            muscle_split = request.POST.get('muscle_split') or None
            exercise_entries = []
            if did_workout:
                if muscle_split not in WORKOUT_MUSCLE_SPLITS:
                    messages.error(request, 'Choose a valid muscle split for your workout.')
                    return redirect('member_logging')

                exercises = request.POST.getlist('exercise_name')
                set_counts = request.POST.getlist('sets')
                rep_ranges = request.POST.getlist('rep_range')
                if len(exercises) > 20 or not (len(exercises) == len(set_counts) == len(rep_ranges)):
                    messages.error(request, 'Submit up to 20 complete exercise rows.')
                    return redirect('member_logging')

                for exercise, set_count, rep_range in zip(exercises, set_counts, rep_ranges):
                    if not exercise and not set_count and not rep_range:
                        continue
                    if (
                        exercise not in WORKOUT_EXERCISES
                        or set_count not in WORKOUT_SET_OPTIONS
                        or rep_range not in WORKOUT_REP_RANGES
                    ):
                        messages.error(request, 'Complete each selected exercise with a valid set count and rep range.')
                        return redirect('member_logging')
                    exercise_entries.append({
                        'exercise_name': exercise,
                        'sets': int(set_count),
                        'rep_range': rep_range,
                        'position': len(exercise_entries),
                    })

                if not exercise_entries:
                    messages.error(request, 'Select at least one exercise for a completed workout.')
                    return redirect('member_logging')

            exercise_details = '\n'.join(
                f"{entry['exercise_name']} - {entry['sets']} sets x {entry['rep_range']} reps"
                for entry in exercise_entries
            )
            with transaction.atomic():
                workout_log = WorkoutLog.objects.create(
                    member=user,
                    date=log_date,
                    did_workout=did_workout,
                    muscle_split=muscle_split,
                    exercise_details=exercise_details,
                    notes=notes,
                )
                WorkoutExerciseLog.objects.bulk_create([
                    WorkoutExerciseLog(workout=workout_log, **entry)
                    for entry in exercise_entries
                ])
            return redirect('member_logging')

        if log_type == 'cardio':
            activity = request.POST.get('activity')
            intensity = request.POST.get('intensity')
            notes = request.POST.get('notes', '').strip()
            try:
                duration_minutes = int(request.POST.get('duration_minutes', ''))
            except (TypeError, ValueError):
                duration_minutes = 0

            if activity not in CARDIO_ACTIVITIES or intensity not in CARDIO_INTENSITIES:
                messages.error(request, 'Choose a cardio activity and intensity.')
                return redirect('member_logging')
            if not 1 <= duration_minutes <= 300:
                messages.error(request, 'Enter a cardio duration between 1 and 300 minutes.')
                return redirect('member_logging')
            if len(notes) > 2000:
                messages.error(request, 'Keep cardio notes under 2,000 characters.')
                return redirect('member_logging')

            CardioLog.objects.create(
                member=user,
                date=log_date,
                activity=activity,
                duration_minutes=duration_minutes,
                intensity=intensity,
                notes=notes,
            )
            return redirect('member_logging')

    meal_logs = MealLog.objects.filter(member=user).order_by('-date', '-created_at')
    workout_logs = WorkoutLog.objects.filter(member=user).prefetch_related('exercises').order_by('-date', '-created_at')
    cardio_logs = CardioLog.objects.filter(member=user).order_by('-date', '-created_at')
    weight_logs = WeightLog.objects.filter(member=user)[:7]
    water_logs = WaterLog.objects.filter(member=user)[:7]

    context = {
        'meal_logs': meal_logs,
        'workout_logs': workout_logs,
        'cardio_logs': cardio_logs,
        'weight_logs': weight_logs,
        'water_logs': water_logs,
        **_weight_tracking_context(user),
        'weight_goal_return_to': 'member_logging',
        'role': 'Member',
        'today': timezone.localdate().isoformat(),
        'meal_types': MealLog.MEAL_TYPE_CHOICES,
        'muscle_splits': WORKOUT_MUSCLE_SPLITS,
        'workout_exercises': WORKOUT_EXERCISES,
        'exercise_guides': WORKOUT_EXERCISE_GUIDES,
        'set_options': WORKOUT_SET_OPTIONS,
        'rep_ranges': WORKOUT_REP_RANGES,
        'cardio_activities': CARDIO_ACTIVITIES,
        'cardio_intensities': CARDIO_INTENSITIES,
    }
    return render(request, 'fitness/member_logging.html', context)


def _format_workout_response(response_text):
    def clean_markdown(text):
        return re.sub(r"^(?:\*\*|__)(.*?)(?:\*\*|__)$", r"\1", text.strip())

    def is_option_heading(text):
        if re.match(r"^workout\s+for\b", text, re.IGNORECASE):
            return False
        return re.match(
            r"^(?:option(?:\s+[a-z0-9]+)?|workout\s+(?:option\s+)?[a-z0-9]+|day\s+[a-z0-9]+|routine\s+[a-z0-9]+|plan\s+[a-z0-9]+)(?:\s*[:.-]\s*|\s*$)",
            text,
            re.IGNORECASE,
        ) is not None

    def format_inline(text):
        escaped_text = escape_html(text)
        escaped_text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", r"<strong>\1\2</strong>", escaped_text)
        return re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped_text)

    def exercise_video_url(item):
        normalized_item = clean_markdown(item).casefold()
        matching_guides = [
            guide for guide in ALL_EXERCISE_GUIDES
            if guide['name'].casefold() in normalized_item
        ]
        if matching_guides:
            return max(matching_guides, key=lambda guide: len(guide['name']))['embed_url']

        return None

    lines = []
    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith("```"):
            lines.append(line)

    intro = []
    sections = []
    current_section = None
    for line in lines:
        markdown_heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
        heading_text = clean_markdown(markdown_heading.group(2)) if markdown_heading else ""
        option_text = clean_markdown(re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line))

        if markdown_heading and (len(markdown_heading.group(1)) <= 2 or is_option_heading(heading_text)):
            if len(markdown_heading.group(1)) == 1 and not is_option_heading(heading_text):
                intro.append(f"**{heading_text}**")
            else:
                current_section = {"title": heading_text, "lines": []}
                sections.append(current_section)
        elif not markdown_heading and is_option_heading(option_text):
            current_section = {"title": option_text, "lines": []}
            sections.append(current_section)
        elif current_section:
            current_section["lines"].append(f"**{heading_text}**" if markdown_heading else line)
        else:
            intro.append(f"**{heading_text}**" if markdown_heading else line)

    if not sections:
        sections = [{"title": "Workout Plan", "lines": intro}]
        intro = []

    def render_body(body_lines):
        output = []
        paragraph = []
        list_items = []

        def flush_paragraph():
            if paragraph:
                output.append(f'<p class="text-sm leading-relaxed text-[#5D685F]">{" ".join(format_inline(item) for item in paragraph)}</p>')
                paragraph.clear()

        def flush_list():
            if list_items:
                rendered_items = []
                for item in list_items:
                    embed_url = exercise_video_url(item)
                    video_html = (
                        f'<iframe class="w-full aspect-video rounded-xl shadow-md" '
                        f'src="{embed_url}" title="{escape_html(clean_markdown(item))} video demonstration" '
                        f'loading="lazy" referrerpolicy="strict-origin-when-cross-origin" '
                        f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
                        f'allowfullscreen></iframe>'
                        if embed_url
                        else '<p class="text-[11px] text-[#6B7568]">No embeddable video reference is available for this exercise yet.</p>'
                    )
                    rendered_items.append(
                        f'<li class="min-w-0 space-y-3 rounded-lg border border-[#E7E3D6] bg-[#FCFBF8] p-3">'
                        f'<span class="block min-w-0 break-words text-sm leading-relaxed text-[#4B5750]">{format_inline(item)}</span>'
                        f'{video_html}</li>'
                    )
                items = ''.join(rendered_items)
                output.append(f'<ul class="min-w-0 space-y-2">{items}</ul>')
                list_items.clear()

        for line in body_lines:
            bullet = re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)(.+)$", line)
            if not line:
                flush_paragraph()
                flush_list()
            elif bullet:
                flush_paragraph()
                list_items.append(bullet.group(1))
            else:
                flush_list()
                paragraph.append(line)

        flush_paragraph()
        flush_list()
        return "".join(output)

    intro_html = render_body(intro)
    cards = []
    for section in sections:
        body_html = render_body(section["lines"])
        if not body_html:
            continue
        title_html = format_inline(section["title"])
        cards.append(
            '<article class="flex h-full min-w-0 flex-col overflow-hidden rounded-xl border border-[#E7E3D6] bg-white p-4 shadow-sm sm:p-5">'
            f'<h4 class="mb-4 border-b border-[#E7E3D6] pb-3 text-sm font-semibold text-[#1F4D3A]">{title_html}</h4>'
            f'<div class="min-w-0 flex-1">{body_html}</div></article>'
        )

    if not cards:
        return intro_html

    intro_section = (
        '<section class="lg:col-span-2 min-w-0 rounded-xl border border-[#E7E3D6] bg-white p-4 sm:p-5">'
        '<div class="mb-2 inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold text-[#1F4D3A]">'
        'Your Workout Plan</div>'
        f'<div class="min-w-0 text-sm leading-relaxed text-[#5D685F]">{intro_html}</div></section>'
        if intro_html
        else ""
    )
    return (
        f'<div class="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">'
        f'{intro_section}{"".join(cards)}</div>'
    )


@login_required
def exercise_directory_view(request):
    selected_group = request.GET.get('group', '').strip()
    search_query = request.GET.get('q', '').strip()
    valid_groups = {group['name'] for group in EXERCISE_DIRECTORY_GROUPS}
    if selected_group not in valid_groups:
        selected_group = ''

    return render(request, 'fitness/exercise_reference.html', {
        'exercise_groups': EXERCISE_DIRECTORY_GROUPS,
        'guide_count': len(ALL_EXERCISE_GUIDES),
        'selected_group': selected_group,
        'search_query': search_query,
        'role': 'Admin' if is_admin(request.user) else 'Trainer' if is_trainer(request.user) else 'Member',
    })


def _fallback_workout_response(selected_muscle, user):
    target_groups = {
        'Chest (Upper, Middle, Lower)': ('Chest',),
        'Chest & Triceps': ('Chest', 'Triceps'),
        'Back & Biceps': ('Back', 'Biceps'),
        'Shoulders & Abs': ('Shoulders', 'Core'),
        'Legs (Quads, Hamstrings, Calves)': ('Legs',),
        'Arms (Biceps & Triceps Super-set)': ('Biceps', 'Triceps', 'Shoulders', 'Core'),
    }
    available_exercises = [
        guide for guide in WORKOUT_EXERCISE_GUIDES
        if guide['muscle_group'] in target_groups[selected_muscle]
    ]
    plan_lines = [
        f'Workout for: {selected_muscle}',
        f'Goal: {user.actual_goal or "General fitness"}. Experience: {user.exercise_experience or "Not specified"}.',
    ]

    for option_title, offset, sets_and_reps, rest in (
        ('Heavy Strength Builder', 0, '4 sets of 6-8 reps', 'Rest 2-3 minutes.'),
        ('Pump & Volume Focus', 1, '3 sets of 10-12 reps', 'Rest 60-90 seconds.'),
    ):
        plan_lines.extend(('', f'## {option_title}'))
        for index in range(min(4, len(available_exercises))):
            guide = available_exercises[(index + offset) % len(available_exercises)]
            plan_lines.append(
                f'- {guide["name"]} — {sets_and_reps}. {rest} {guide["description"]}'
            )

    plan_lines.append('Take a drink of water between sets. Stop if you feel sharp pain.')
    return _format_workout_response('\n'.join(plan_lines))


# --- BOSS REQUIREMENT: Gemini API Smart Workout Generator ---
# --- BOSS REQUIREMENT: Elite Professional AI Workout Generator View ---
@login_required
def ai_workout_generator_view(request):
    user = request.user
    
    if is_admin_or_trainer(user):
        return redirect('dashboard')
        
    if not user.is_profile_complete:
        return redirect('complete_profile')
        
    ai_recommendations = None
    selected_muscle = None
    
    if request.method == 'POST':
        selected_muscle = request.POST.get('muscle_group')

        if selected_muscle and selected_muscle not in AI_WORKOUT_MUSCLE_GROUPS:
            ai_recommendations = 'Select a valid muscle group to generate a workout.'
            selected_muscle = None
        
        if selected_muscle:
            client = None
            if settings.GEMINI_API_KEY:
                try:
                    client = genai.Client(api_key=settings.GEMINI_API_KEY)
                except Exception:
                    client = None
            
            prompt = f"""
            Act as a friendly, experienced personal trainer. Create 2-3 practical workout options for: {selected_muscle}.
            Write for an everyday gym member. Use short sentences, familiar exercise names, and plain gym language.
            Use the option titles "Heavy Strength Builder" and "Pump & Volume Focus" when they fit.
            Label groups of exercises "Main Compound Lifts", "Accessory Exercises", and "Finishing Exercises".
            Avoid academic training terms and unexplained abbreviations. Do not overstate what a workout can achieve.
            Use only these exercise names: {', '.join(WORKOUT_EXERCISES)}.
            Put exactly one exercise on each bullet, followed by its sets, reps, rest time, and one short form tip.
            
            Member Details:
            - Height: {user.height} cm
            - Weight: {user.weight} kg
            - Exercise Experience: {user.exercise_experience}
            - Training Frequency: {user.training_frequency}
            - Primary Goal: {user.actual_goal}
            
            Requirements:
            1. Cover the selected muscle group with practical exercise choices.
            2. Provide 2 or 3 distinct workout options.
            3. Give each exercise a clear number of sets and reps.
            4. Add one short, direct form tip for each exercise.
            5. Keep instructions simple and actionable; tell the member to stop if they feel sharp pain.
            """
            
            models_to_try = ['gemini-1.5-flash', 'gemini-2.5-flash', 'gemini-pro']
            success = False
            
            if client:
                for model_name in models_to_try:
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                        )
                        if response.text:
                            formatted_response = _format_workout_response(response.text)
                            if formatted_response:
                                ai_recommendations = formatted_response
                                success = True
                                break
                    except Exception:
                        continue
            
            # Use the same exercise catalog and tutorial buttons if AI generation is unavailable.
            if not success:
                ai_recommendations = _fallback_workout_response(selected_muscle, user)

    context = {
        'ai_recommendations': ai_recommendations,
        'selected_muscle': selected_muscle,
        'role': 'Member',
        'exercise_guides': WORKOUT_EXERCISE_GUIDES,
    }
    return render(request, 'fitness/ai_workout.html', context)