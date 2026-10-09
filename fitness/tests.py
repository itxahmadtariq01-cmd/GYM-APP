from datetime import date
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth.models import Group, Permission as DjangoPermission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from .models import (
	Attendance,
	CardioLog,
	CustomUser,
	DietPlan,
		MealLog,
	Permission,
	Role,
	TrainerMemberAssignment,
	TrainerProfile,
	WorkoutExerciseLog,
	WorkoutLog,
	WorkoutPlan,
)
from .views import _format_workout_response


class WorkoutResponseFormattingTests(SimpleTestCase):
	def test_markdown_sections_and_bullets_render_as_cards(self):
		formatted = _format_workout_response(
			"Chest workout plan\n\n"
			"## Option A: Strength\n"
			"- **Bench press**: 4 sets x 8 reps\n"
			"- Incline press: 3 sets x 10 reps\n\n"
			"## Option B: Volume\n"
			"* Cable fly: 3 sets x 12 reps"
		)

		self.assertIn('class="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch"', formatted)
		self.assertIn('class="lg:col-span-2 min-w-0 rounded-xl border border-[#E7E3D6] bg-white p-4 sm:p-5"', formatted)
		self.assertIn("Option A: Strength", formatted)
		self.assertIn("Option B: Volume", formatted)
		self.assertIn("<strong>Bench press</strong>", formatted)
		self.assertEqual(formatted.count("<article "), 2)
		self.assertEqual(formatted.count("Watch video tutorial</a>"), 3)

	def test_plain_text_is_rendered_and_html_is_escaped(self):
		formatted = _format_workout_response("Press <script>alert('x')</script> for 3 sets")

		self.assertIn("Workout Plan", formatted)
		self.assertIn("&lt;script&gt;", formatted)
		self.assertNotIn("<script>", formatted)

	def test_numbered_markdown_option_heading_starts_a_card(self):
		formatted = _format_workout_response(
			"1. **Option A: Strength**\n- Bench press: 4 sets x 8 reps"
		)

		self.assertIn("Option A: Strength", formatted)
		self.assertEqual(formatted.count("<article "), 1)

	def test_workout_summary_spans_above_two_option_cards(self):
		formatted = _format_workout_response(
			"Workout for: Chest\nGoal: General fitness\n"
			"## Heavy Strength Builder\n- Barbell Bench Press: 4 sets of 8 reps\n"
			"## Pump & Volume Focus\n- Push-up: 3 sets of 12 reps"
		)

		self.assertIn('class="lg:col-span-2 min-w-0 rounded-xl border border-[#E7E3D6] bg-white p-4 sm:p-5"', formatted)
		self.assertEqual(formatted.count('<article class="flex h-full min-w-0 flex-col overflow-hidden'), 2)
		self.assertIn('class="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch"', formatted)


class BulkAttendanceTests(TestCase):
	def setUp(self):
		self.trainer_role = Role.objects.create(name="Trainer")
		self.admin_role = Role.objects.create(name="Admin")
		self.member_role = Role.objects.create(name="Member")
		self.trainer = CustomUser.objects.create_user(username="coach", role=self.trainer_role)
		self.admin = CustomUser.objects.create_user(username="manager", role=self.admin_role, is_staff=True)
		self.member_one = CustomUser.objects.create_user(username="member_one", role=self.member_role)
		self.member_two = CustomUser.objects.create_user(username="member_two")
		self.unassigned_member = CustomUser.objects.create_user(username="unassigned_member")
		TrainerMemberAssignment.objects.create(trainer=self.trainer, member=self.member_one)
		TrainerMemberAssignment.objects.create(trainer=self.trainer, member=self.member_two)
		self.url = reverse("manage_attendance")

	def test_admin_and_trainer_can_view_member_roster(self):
		for user in (self.admin, self.trainer):
			with self.subTest(role=user.role.name):
				self.client.force_login(user)
				response = self.client.get(self.url, {"date": "2026-09-27"})

				self.assertEqual(response.status_code, 200)
				self.assertEqual(
					{member.username for member in response.context["members"]},
					{"member_one", "member_two", "unassigned_member"}
					if user == self.admin
					else {"member_one", "member_two"},
				)
				self.client.logout()

	def test_trainers_only_see_assigned_members_and_cannot_open_unassigned_records(self):
		self.client.force_login(self.trainer)

		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			{member.username for member in response.context["members"]},
			{"member_one", "member_two"},
		)
		self.assertNotContains(response, "unassigned_member")
		self.assertEqual(
			self.client.get(reverse("admin_member_detail", args=[self.unassigned_member.pk])).status_code,
			404,
		)
		self.assertEqual(
			self.client.get(reverse("member_daily_report", args=[self.unassigned_member.pk])).status_code,
			404,
		)

	def test_trainer_can_activate_assigned_member_without_losing_session(self):
		self.member_one.is_active = False
		self.member_one.save(update_fields=["is_active"])
		return_url = f"{reverse('dashboard')}?q=member_one&status=inactive&page=2#tab-users"
		self.client.force_login(self.trainer)
		session_user_id = self.client.session["_auth_user_id"]

		response = self.client.post(
			reverse("toggle_member_status", args=[self.member_one.pk]),
			{"next": return_url},
		)

		self.assertEqual(response.status_code, 302)
		self.assertEqual(response["Location"], return_url)
		self.member_one.refresh_from_db()
		self.trainer.refresh_from_db()
		self.assertTrue(self.member_one.is_active)
		self.assertTrue(self.trainer.is_active)
		self.assertEqual(self.client.session["_auth_user_id"], session_user_id)
		self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

	def test_trainer_cannot_toggle_unassigned_member_and_get_does_not_toggle(self):
		self.client.force_login(self.trainer)
		self.unassigned_member.is_active = False
		self.unassigned_member.save(update_fields=["is_active"])

		response = self.client.post(reverse("toggle_member_status", args=[self.unassigned_member.pk]))
		self.assertEqual(response.status_code, 404)
		self.unassigned_member.refresh_from_db()
		self.assertFalse(self.unassigned_member.is_active)

		get_response = self.client.get(reverse("toggle_member_status", args=[self.member_one.pk]))
		self.assertEqual(get_response.status_code, 302)
		self.member_one.refresh_from_db()
		self.assertTrue(self.member_one.is_active)

	def test_trainer_profile_and_assignment_are_managed_from_trainer_admin(self):
		profile = TrainerProfile.objects.create(
			user=self.trainer,
			years_experience=8,
			fitness_background="Strength coaching",
			expertise="Powerlifting",
		)
		custom_user_admin = admin.site._registry[CustomUser]
		inline_models = {
			inline.model
			for inline in custom_user_admin.get_inline_instances(
				RequestFactory().get("/admin/"),
				self.trainer,
			)
		}

		self.assertEqual(profile.user, self.trainer)
		self.assertIn(TrainerMemberAssignment, inline_models)
		self.assertIn(TrainerProfile, inline_models)

	def test_trainer_management_portal_is_admin_only_and_shows_current_assignments(self):
		url = reverse("manage_trainers")
		self.client.force_login(self.admin)

		response = self.client.get(url)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["selected_trainer"], self.trainer)
		self.assertIn(self.member_one.pk, response.context["selected_member_ids"])
		self.assertContains(response, "Trainer Management")
		self.assertContains(response, f'name="members" value="{self.member_one.pk}" checked')
		self.assertContains(response, reverse("manage_trainers"))

		self.client.force_login(self.trainer)
		self.assertEqual(self.client.get(url).status_code, 302)

	def test_admin_can_create_trainer_credentials_and_professional_profile(self):
		self.client.force_login(self.admin)
		response = self.client.post(reverse("manage_trainers"), {
			"action": "create_trainer",
			"username": "new_coach",
			"first_name": "Taylor",
			"last_name": "Coach",
			"email": "taylor.coach@example.com",
			"password1": "StrongCoachingPass2026!",
			"password2": "StrongCoachingPass2026!",
			"years_experience": "7",
			"fitness_background": "Strength and conditioning coaching",
			"expertise": "General fitness, beginner strength",
			"certifications": "Certified personal trainer",
		})

		trainer = CustomUser.objects.get(username="new_coach")
		self.assertRedirects(response, f"{reverse('manage_trainers')}?trainer_id={trainer.pk}")
		self.assertEqual(trainer.role.name, "Trainer")
		self.assertFalse(trainer.is_staff)
		self.assertTrue(trainer.check_password("StrongCoachingPass2026!"))
		self.assertEqual(trainer.trainer_profile.years_experience, 7)
		self.assertEqual(trainer.trainer_profile.expertise, "General fitness, beginner strength")

	def test_admin_reassigns_members_to_one_trainer_and_keeps_checkbox_state(self):
		other_trainer = CustomUser.objects.create_user(
			username="coach_two",
			role=self.trainer_role,
		)
		url = reverse("manage_trainers")
		self.client.force_login(self.admin)

		response = self.client.post(url, {
			"action": "save_assignments",
			"trainer": str(other_trainer.pk),
			"members": [str(self.member_one.pk), str(self.unassigned_member.pk)],
		})

		self.assertRedirects(response, f"{url}?trainer_id={other_trainer.pk}")
		self.assertCountEqual(
			other_trainer.member_assignments.values_list("member_id", flat=True),
			[self.member_one.pk, self.unassigned_member.pk],
		)
		self.assertFalse(
			self.trainer.member_assignments.filter(member=self.member_one).exists(),
		)
		self.assertTrue(self.trainer.member_assignments.filter(member=self.member_two).exists())
		self.client.force_login(other_trainer)
		trainer_dashboard = self.client.get(reverse("dashboard"))
		self.assertEqual(
			{member.username for member in trainer_dashboard.context["members"]},
			{"member_one", "unassigned_member"},
		)

	def test_invalid_member_selection_keeps_valid_checkboxes_checked(self):
		self.client.force_login(self.admin)
		response = self.client.post(reverse("manage_trainers"), {
			"action": "save_assignments",
			"trainer": str(self.trainer.pk),
			"members": [str(self.member_one.pk), "999999"],
		})

		self.assertEqual(response.status_code, 200)
		self.assertIn(self.member_one.pk, response.context["selected_member_ids"])
		self.assertContains(response, f'name="members" value="{self.member_one.pk}" checked')
		self.assertTrue(self.trainer.member_assignments.filter(member=self.member_one).exists())

	def test_assignment_model_rejects_non_trainer_accounts(self):
		assignment = TrainerMemberAssignment(trainer=self.member_one, member=self.unassigned_member)

		with self.assertRaises(ValidationError):
			assignment.full_clean()

	def test_bulk_submission_persists_selected_date_and_updates_existing_rows(self):
		self.client.force_login(self.trainer)
		selected_date = date(2026, 9, 20)
		existing = Attendance.objects.create(
			member=self.member_one,
			date=selected_date,
			status="Absent",
		)

		response = self.client.post(self.url, {
			"date": selected_date.isoformat(),
			f"attendance_{self.member_one.pk}": "Present",
			f"attendance_{self.member_two.pk}": "Absent",
		})

		self.assertRedirects(response, f"{self.url}?date={selected_date.isoformat()}")
		self.assertEqual(Attendance.objects.filter(date=selected_date).count(), 2)
		existing.refresh_from_db()
		self.assertEqual(existing.status, "Present")
		self.assertEqual(
			Attendance.objects.get(member=self.member_two, date=selected_date).status,
			"Absent",
		)

	def test_invalid_status_prevents_partial_submission(self):
		self.client.force_login(self.trainer)
		response = self.client.post(self.url, {
			"date": "2026-09-20",
			f"attendance_{self.member_one.pk}": "Present",
			f"attendance_{self.member_two.pk}": "On leave",
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Choose Present or Absent for every member")
		self.assertFalse(Attendance.objects.exists())

	def test_attendance_directory_opens_member_history_grouped_by_month(self):
		august_present = Attendance.objects.create(
			member=self.member_one,
			date=date(2026, 8, 10),
			status="Present",
		)
		august_absent = Attendance.objects.create(
			member=self.member_one,
			date=date(2026, 8, 22),
			status="Absent",
		)
		september_present = Attendance.objects.create(
			member=self.member_one,
			date=date(2026, 9, 3),
			status="Present",
		)
		Attendance.objects.create(
			member=self.member_two,
			date=date(2026, 9, 4),
			status="Absent",
		)
		self.client.force_login(self.trainer)

		directory_response = self.client.get(self.url)
		self.assertEqual(directory_response.status_code, 200)
		self.assertIsNone(directory_response.context["selected_member"])
		self.assertContains(directory_response, f"?member_id={self.member_one.pk}")

		history_response = self.client.get(self.url, {"member_id": self.member_one.pk})
		self.assertEqual(history_response.status_code, 200)
		self.assertEqual(history_response.context["selected_member"], self.member_one)
		monthly_records = history_response.context["monthly_records"]
		self.assertEqual([month["month"] for month in monthly_records], [date(2026, 9, 1), date(2026, 8, 1)])
		self.assertEqual(monthly_records[0]["records"], [september_present])
		self.assertCountEqual(monthly_records[1]["records"], [august_present, august_absent])

	def test_workout_and_diet_forms_select_and_assign_gym_members(self):
		self.client.force_login(self.trainer)
		workout_url = reverse("manage_workouts")
		diet_url = reverse("manage_diets")

		workout_page = self.client.get(workout_url)
		diet_page = self.client.get(diet_url)
		for response in (workout_page, diet_page):
			self.assertContains(response, f'<option value="{self.member_one.pk}">member_one')
			self.assertNotContains(response, f'<option value="{self.trainer.pk}">')

		workout_response = self.client.post(workout_url, {
			"title": "Strength",
			"description": "Three sessions per week",
			"member_id": str(self.member_one.pk),
		})
		diet_response = self.client.post(diet_url, {
			"title": "Balanced plan",
			"description": "Protein with each meal",
			"member_id": str(self.member_one.pk),
		})

		self.assertRedirects(workout_response, workout_url)
		self.assertRedirects(diet_response, diet_url)
		self.assertEqual(WorkoutPlan.objects.get().member, self.member_one)
		self.assertEqual(DietPlan.objects.get().member, self.member_one)

	def test_workout_assignment_rejects_non_member_ids(self):
		self.client.force_login(self.trainer)
		response = self.client.post(reverse("manage_workouts"), {
			"title": "Invalid assignment",
			"description": "Should not be assigned to a trainer",
			"member_id": str(self.trainer.pk),
		})

		self.assertEqual(response.status_code, 200)
		self.assertFalse(WorkoutPlan.objects.exists())

	def test_trainer_cannot_assign_workouts_to_unassigned_members(self):
		self.client.force_login(self.trainer)
		response = self.client.post(reverse("manage_workouts"), {
			"title": "Out of scope",
			"description": "Should be rejected",
			"member_id": str(self.unassigned_member.pk),
		})

		self.assertEqual(response.status_code, 200)
		self.assertFalse(WorkoutPlan.objects.exists())

	def test_member_with_dashboard_permission_only_sees_own_attendance(self):
		view_dashboard = Permission.objects.create(name="View dashboard", codename="view_dashboard")
		self.member_role.permissions.add(view_dashboard)
		self.member_one.is_profile_complete = True
		self.member_one.save(update_fields=["is_profile_complete"])
		own_record = Attendance.objects.create(member=self.member_one, status="Present")
		Attendance.objects.create(member=self.member_two, status="Absent")
		own_workout = WorkoutPlan.objects.create(title="Mine", description="Private workout", member=self.member_one)
		WorkoutPlan.objects.create(title="Other", description="Private workout", member=self.member_two)
		own_diet = DietPlan.objects.create(title="Mine", meal_details="Private diet", member=self.member_one)
		DietPlan.objects.create(title="Other", meal_details="Private diet", member=self.member_two)
		self.client.force_login(self.member_one)

		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(list(response.context["attendances"]), [own_record])
		self.assertEqual(list(response.context["workouts"]), [own_workout])
		self.assertEqual(list(response.context["diets"]), [own_diet])

	def test_permission_check_inherits_group_and_custom_role_permissions(self):
		group = Group.objects.create(name="Workout Operators")
		permission = DjangoPermission.objects.get(
			content_type=ContentType.objects.get_for_model(WorkoutPlan),
			codename="add_workoutplan",
		)
		group.permissions.add(permission)
		self.member_one.groups.add(group)

		custom_permission = Permission.objects.create(
			name="Manage workouts",
			codename="can_manage_workouts",
		)
		self.member_role.permissions.add(custom_permission)

		self.assertTrue(self.member_one.has_permission("add_workoutplan"))
		self.assertTrue(self.member_one.has_permission("fitness.add_workoutplan"))
		self.assertTrue(self.member_one.has_permission("can_manage_workouts"))
		self.assertFalse(self.member_two.has_permission("add_workoutplan"))

	def test_admin_and_trainer_dashboards_include_all_attendance(self):
		first_record = Attendance.objects.create(member=self.member_one, status="Present")
		second_record = Attendance.objects.create(member=self.member_two, status="Absent")

		for user in (self.admin, self.trainer):
			with self.subTest(role=user.role.name):
				self.client.force_login(user)
				response = self.client.get(reverse("dashboard"))

				self.assertEqual(response.status_code, 200)
				self.assertCountEqual(response.context["attendances"], [first_record, second_record])

	def test_featured_dashboard_tools_are_role_aware_and_use_compact_kpis(self):
		self.member_one.is_profile_complete = True
		self.member_one.save(update_fields=["is_profile_complete"])

		for user, ai_available in (
			(self.admin, False),
			(self.trainer, False),
			(self.member_one, True),
		):
			with self.subTest(role=user.role.name if user.role_id else "Member"):
				self.client.force_login(user)
				response = self.client.get(reverse("dashboard"))

				self.assertEqual(response.status_code, 200)
				self.assertContains(response, 'aria-label="Featured tools"')
				self.assertContains(response, "Exercise Directory")
				self.assertNotContains(response, "text-4xl")
				if ai_available:
					self.assertContains(response, "AI Workout Generator")
				else:
					self.assertNotContains(response, "AI Workout Generator")


	def test_admin_role_without_staff_flag_uses_admin_dashboard(self):
		role_admin = CustomUser.objects.create_user(username="role_admin", role=self.admin_role)
		self.client.force_login(role_admin)

		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["role"], "Admin")

	def test_staff_member_detail_includes_dated_daily_logs(self):
		log_date = date(2026, 9, 15)
		meal = MealLog.objects.create(
			member=self.member_one,
			date=log_date,
			meal_type="Lunch",
			description="Chicken and rice",
		)
		workout = WorkoutLog.objects.create(
			member=self.member_one,
			date=log_date,
			muscle_split="Chest",
		)
		exercise = WorkoutExerciseLog.objects.create(
			workout=workout,
			exercise_name="Barbell Bench Press",
			sets=4,
			rep_range="8-10",
		)
		cardio = CardioLog.objects.create(
			member=self.member_one,
			date=log_date,
			activity="Cycling",
			duration_minutes=30,
			intensity="Moderate",
		)
		detail_url = reverse("admin_member_detail", args=[self.member_one.pk])

		for staff_user in (self.admin, self.trainer):
			with self.subTest(role=staff_user.role.name):
				self.client.force_login(staff_user)
				response = self.client.get(detail_url)

				self.assertEqual(response.status_code, 200)
				self.assertEqual(list(response.context["meal_logs"]), [meal])
				self.assertEqual(list(response.context["workout_logs"]), [workout])
				self.assertEqual(list(response.context["workout_logs"][0].exercises.all()), [exercise])
				self.assertEqual(list(response.context["cardio_logs"]), [cardio])
				self.assertEqual(len(response.context["daily_activity"]), 1)
				self.assertEqual(response.context["daily_activity"][0]["date"], log_date)
				self.assertContains(response, "Daily activity reports")
				self.assertContains(response, "Chicken and rice")
				self.assertContains(response, "Barbell Bench Press")
				self.assertContains(response, "Cycling")

	def test_dedicated_report_is_chronological_and_staff_only(self):
		older_date = date(2026, 8, 1)
		newer_date = date(2026, 9, 12)
		MealLog.objects.create(
			member=self.member_one,
			date=newer_date,
			meal_type="Dinner",
			description="Later meal",
		)
		CardioLog.objects.create(
			member=self.member_one,
			date=older_date,
			activity="Rowing",
			duration_minutes=25,
			intensity="High",
		)
		report_url = reverse("member_daily_report", args=[self.member_one.pk])

		for staff_user in (self.admin, self.trainer):
			with self.subTest(role=staff_user.role.name):
				self.client.force_login(staff_user)
				response = self.client.get(report_url)

				self.assertEqual(response.status_code, 200)
				self.assertEqual(
					[day["date"] for day in response.context["daily_activity"]],
					[older_date, newer_date],
				)
				self.assertEqual(response.context["summary"]["cardio_minutes"], 25)
				self.assertContains(response, "Daily activity timeline")

		regular_member = CustomUser.objects.create_user(username="report_viewer")
		self.client.force_login(regular_member)
		self.assertEqual(self.client.get(report_url).status_code, 302)

	@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
	def test_signup_redirects_to_dashboard_after_login(self):
		response = self.client.post(reverse("signup"), {
			"username": "new_member",
			"email": "new_member@example.com",
			"password1": "CaliberPass2026!",
			"password2": "CaliberPass2026!",
		})

		self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
		self.assertIn("_auth_user_id", self.client.session)


class ExerciseDirectoryTests(TestCase):
	def setUp(self):
		self.member = CustomUser.objects.create_user(
			username="reference_member",
			is_profile_complete=True,
		)
		self.client.force_login(self.member)
		self.url = reverse("exercise_directory")

	def test_directory_lists_all_categories_and_tutorial_links(self):
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["guide_count"], 27)
		self.assertEqual(
			[category["name"] for category in response.context["exercise_groups"]],
			["Chest", "Back", "Shoulders", "Biceps", "Triceps", "Legs", "Core", "Cardio"],
		)
		self.assertEqual(response.content.decode().count("Watch video tutorial"), 27)
		self.assertContains(response, "youtube.com/results?search_query=Barbell+Bench+Press")
		self.assertContains(response, 'aria-label="Primary navigation"')

	def test_directory_preserves_group_and_search_filters(self):
		response = self.client.get(self.url, {"group": "Cardio", "q": "cycle"})

		self.assertEqual(response.context["selected_group"], "Cardio")
		self.assertEqual(response.context["search_query"], "cycle")
		self.assertContains(response, '<option value="cardio" selected>Cardio</option>')
		self.assertContains(response, 'value="cycle"')

	def test_directory_requires_login(self):
		self.client.logout()

		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 302)


class MemberWorkoutLoggingTests(TestCase):
	def setUp(self):
		self.member = CustomUser.objects.create_user(
			username="daily_member",
			is_profile_complete=True,
		)
		self.client.force_login(self.member)
		self.url = reverse("member_logging")

	def test_workout_form_uses_preset_selects(self):
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'name="muscle_split"')
		self.assertContains(response, 'name="exercise_name"')
		self.assertContains(response, 'name="sets"')
		self.assertContains(response, 'name="rep_range"')
		self.assertContains(response, "Barbell Bench Press")
		self.assertContains(response, "12-15")
		self.assertContains(response, "Lower the bar under control")
		self.assertContains(response, "Watch form reference")
		self.assertContains(response, 'aria-label="Primary navigation"')
		self.assertContains(response, "Featured tools")
		self.assertContains(response, "AI workout generator")
		self.assertContains(response, "Exercise directory")
		self.assertContains(response, 'name="activity"')
		self.assertNotContains(response, 'name="exercise_details"')

	def test_selected_exercise_and_training_presets_are_saved(self):
		response = self.client.post(self.url, {
			"log_type": "workout",
			"did_workout": "yes",
			"log_date": "2026-09-18",
			"muscle_split": "Chest",
			"exercise_name": [
				"Barbell Bench Press",
				"Incline Dumbbell Press",
				"Dumbbell Fly",
				"Push-up",
				"Lat Pulldown",
			],
			"sets": ["3", "4", "3", "3", "4"],
			"rep_range": ["8-10", "10-12", "12-15", "15-20", "8-10"],
		})

		self.assertRedirects(response, self.url)
		workout_log = WorkoutLog.objects.get(member=self.member)
		self.assertEqual(workout_log.date, date(2026, 9, 18))
		self.assertEqual(workout_log.muscle_split, "Chest")
		self.assertEqual(workout_log.exercises.count(), 5)
		self.assertEqual(workout_log.exercises.first().exercise_name, "Barbell Bench Press")
		self.assertEqual(workout_log.exercises.last().exercise_name, "Lat Pulldown")

	def test_rest_day_saves_without_exercise_details(self):
		response = self.client.post(self.url, {
			"log_type": "workout",
			"did_workout": "no",
			"log_date": "2026-09-18",
		})

		self.assertRedirects(response, self.url)
		workout_log = WorkoutLog.objects.get(member=self.member)
		self.assertFalse(workout_log.did_workout)
		self.assertIsNone(workout_log.muscle_split)
		self.assertEqual(workout_log.exercise_details, "")
		self.assertEqual(workout_log.date, date(2026, 9, 18))

	def test_meal_and_cardio_logs_keep_selected_date_and_member(self):
		meal_date = date(2026, 9, 17)
		meal_response = self.client.post(self.url, {
			"log_type": "meal",
			"log_date": meal_date.isoformat(),
			"meal_type": "Lunch",
			"description": "Rice and grilled chicken",
		})
		cardio_date = date(2026, 9, 16)
		cardio_response = self.client.post(self.url, {
			"log_type": "cardio",
			"log_date": cardio_date.isoformat(),
			"activity": "Cycling",
			"duration_minutes": "35",
			"intensity": "Moderate",
			"notes": "Steady pace",
		})

		self.assertRedirects(meal_response, self.url)
		self.assertRedirects(cardio_response, self.url)
		meal_log = self.member.meal_logs.get()
		cardio_log = self.member.cardio_logs.get()
		self.assertEqual((meal_log.date, meal_log.description), (meal_date, "Rice and grilled chicken"))
		self.assertEqual((cardio_log.date, cardio_log.activity, cardio_log.duration_minutes), (cardio_date, "Cycling", 35))

	def test_member_logging_page_only_shows_current_members_private_logs(self):
		other_member = CustomUser.objects.create_user(username="another_member", is_profile_complete=True)
		own_meal = MealLog.objects.create(member=self.member, meal_type="Breakfast", description="Own meal")
		MealLog.objects.create(member=other_member, meal_type="Dinner", description="Private meal")
		own_workout = WorkoutLog.objects.create(member=self.member, muscle_split="Back")
		WorkoutLog.objects.create(member=other_member, muscle_split="Legs")
		own_cardio = CardioLog.objects.create(
			member=self.member,
			activity="Treadmill",
			duration_minutes=20,
			intensity="Moderate",
		)
		CardioLog.objects.create(
			member=other_member,
			activity="Cycling",
			duration_minutes=45,
			intensity="High",
		)

		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(list(response.context["meal_logs"]), [own_meal])
		self.assertEqual(list(response.context["workout_logs"]), [own_workout])
		self.assertEqual(list(response.context["cardio_logs"]), [own_cardio])
		self.assertNotContains(response, "Private meal")

	@override_settings(GEMINI_API_KEY="")
	def test_ai_workout_fallback_handles_missing_key_and_escapes_profile_text(self):
		self.member.actual_goal = '<img src=x onerror="alert(1)">'
		self.member.save(update_fields=["actual_goal"])

		response = self.client.post(reverse("ai_workouts"), {
			"muscle_group": "Chest (Upper, Middle, Lower)",
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Workout for:")
		self.assertContains(response, "Heavy Strength Builder")
		self.assertContains(response, "Pump &amp; Volume Focus")
		self.assertContains(response, "Barbell Bench Press")
		self.assertContains(response, "Incline Dumbbell Press")
		self.assertEqual(response.content.decode().count("Watch video tutorial</a>"), 8)
		self.assertNotContains(response, "Mechanical Tension")
		self.assertNotContains(response, "Metabolic Stress")
		self.assertContains(response, "Exercise form references")
		self.assertContains(response, "Watch video tutorial")
		self.assertContains(response, "&lt;img")
		self.assertNotContains(response, '<img src=x onerror="alert(1)">')

	@override_settings(GEMINI_API_KEY="test-key")
	def test_ai_prompt_requests_plain_gym_language(self):
		client = Mock()
		client.models.generate_content.return_value.text = (
			"## Heavy Strength Builder\n- Barbell Bench Press: 3 sets of 8 reps"
		)

		with patch("fitness.views.genai.Client", return_value=client):
			response = self.client.post(reverse("ai_workouts"), {
				"muscle_group": "Chest (Upper, Middle, Lower)",
			})

		self.assertEqual(response.status_code, 200)
		prompt = client.models.generate_content.call_args.kwargs["contents"]
		self.assertIn("friendly, experienced personal trainer", prompt)
		self.assertIn("everyday gym member", prompt)
		self.assertIn("Main Compound Lifts", prompt)
		self.assertIn("one short, direct form tip", prompt)
		self.assertIn("sharp pain", prompt)
		self.assertContains(response, "Watch video tutorial")
		self.assertContains(response, "Barbell+Bench+Press+proper+form+tutorial")
