from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
  help = 'Creates default roles (Admin, Trainer, Member) and assigns permissions.'

  def handle(self, *args, **kwargs):
    self.stdout.write('Creating groups and permissions...')

    # 1. Groups create karna
    admin_group, _ = Group.objects.get_or_create(name='Admin')
    trainer_group, _ = Group.objects.get_or_create(name='Trainer')
    member_group, _ = Group.objects.get_or_create(name='Member')

    # 2. Trainer Permissions (Workout aur Diet plans ko add, change, view kar sakta hai)
    trainer_perms = Permission.objects.filter(
        codename__in=[
            'add_workoutplan',
            'change_workoutplan',
            'view_workoutplan',
            'add_dietplan',
            'change_dietplan',
            'view_dietplan',
        ]
    )
    trainer_group.permissions.set(trainer_perms)

    # 3. Member Permissions (Sirf view kar sakta hai)
    member_perms = Permission.objects.filter(
        codename__in=[
            'view_workoutplan',
            'view_dietplan',
            'view_attendance',
        ]
    )
    member_group.permissions.set(member_perms)

    # 4. Admin ko fitness app ki saari permissions dena
    admin_perms = Permission.objects.filter(content_type__app_label='fitness')
    admin_group.permissions.set(admin_perms)

    self.stdout.write(
        self.style.SUCCESS(
            'Successfully created Admin, Trainer, and Member groups with'
            ' permissions!'
        )
    )