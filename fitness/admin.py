from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Attendance,
    CustomUser,
    DietPlan,
    Permission,
    Plan,
    Role,
    TrainerMemberAssignment,
    TrainerProfile,
    WorkoutPlan,
)

# 1. Membership Plan model ko admin mein register karein
@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'duration_type', 'price')
    search_fields = ('name',)

# 2. CustomUser Admin mein naye gym fields aur role add karein
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'role', 'plan', 'phone_number', 'is_active']
    
    # User edit page mein fields ki grouping (admission_date yahan se hata di hai)
    fieldsets = UserAdmin.fieldsets + (
        ('Gym Membership & Profile Info', {
            'fields': ('role', 'plan', 'phone_number', 'description', 'weight', 'bmi')
        }),
    )
    
    # Naya user add karte waqt ki fields
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Gym Membership & Profile Info', {
            'fields': ('role', 'plan', 'phone_number', 'description', 'weight', 'bmi')
        }),
    )

    def get_inline_instances(self, request, obj=None):
        inline_instances = super().get_inline_instances(request, obj)
        if obj and obj.role and obj.role.name.lower() == 'trainer':
            return inline_instances + [
                TrainerMemberAssignmentInline(self.model, self.admin_site),
                TrainerProfileInline(self.model, self.admin_site),
            ]
        return inline_instances


class TrainerMemberAssignmentInline(admin.TabularInline):
    model = TrainerMemberAssignment
    fk_name = 'trainer'
    extra = 1
    autocomplete_fields = ('member',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'member':
            kwargs['queryset'] = CustomUser.objects.filter(
                is_staff=False,
                is_superuser=False,
            ).exclude(role__name__iexact='admin').exclude(role__name__iexact='trainer')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class TrainerProfileInline(admin.StackedInline):
    model = TrainerProfile
    extra = 0

# 3. Baaki sab models ko register kar do
admin.site.register(Permission)
admin.site.register(Role)
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(WorkoutPlan)
admin.site.register(DietPlan)
admin.site.register(Attendance)
admin.site.register(TrainerProfile)
