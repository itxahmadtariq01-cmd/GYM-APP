from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('manage-workouts/', views.manage_workouts_view, name='manage_workouts'),
    path('manage-diets/', views.manage_diets_view, name='manage_diets'),
    path('manage-attendance/', views.manage_attendance_view, name='manage_attendance'), # <-- Yeh line lazmi add karni hai
    path('member/profile/', views.member_profile_view, name='member_profile'),
    path('management/payments/', views.admin_payments_view, name='admin_payments'),
    path('management/toggle-status/<int:user_id>/', views.toggle_member_status, name='toggle_member_status'),
    path('complete-profile/', views.complete_profile_view, name='complete_profile'),
    path('member/logging/', views.member_logging_view, name='member_logging'),
    path('signup/', views.signup_view, name='signup'),
    path('management/member/<int:user_id>/daily-report/', views.member_daily_report_view, name='member_daily_report'),
    path('management/member/<int:user_id>/', views.admin_member_detail_view, name='admin_member_detail'),
    path('ai-workouts/', views.ai_workout_generator_view, name='ai_workouts'),
    path('exercises/', views.exercise_directory_view, name='exercise_directory'),
    path('management/trainers/', views.manage_trainers_view, name='manage_trainers'),
]