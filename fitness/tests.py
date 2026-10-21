import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth.models import Group, Permission as DjangoPermission
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.template import RequestContext
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
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
	WeightGoal,
	WeightLog,
	WaterLog,
	WorkoutExerciseLog,
	WorkoutLog,
	WorkoutPlan,
	WorkoutSplit,
	WorkoutSplitDay,
)
from .views import _format_workout_response
from .video_utils import youtube_embed_url


class PwaSupportTests(SimpleTestCase):
	def test_manifest_has_requested_install_metadata(self):
		manifest_path = finders.find("manifest.json")

		self.assertIsNotNone(manifest_path)
		with open(manifest_path, encoding="utf-8") as manifest_file:
			manifest = json.load(manifest_file)

		self.assertEqual(manifest["name"], "Caliber Labs Gym")
		self.assertEqual(manifest["short_name"], "Caliber")
		self.assertEqual(manifest["start_url"], "/")
		self.assertEqual(manifest["display"], "standalone")
		self.assertEqual(manifest["theme_color"], "#000000")

	def test_service_worker_is_served_with_root_scope(self):
		response = self.client.get(reverse("service_worker"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response["Content-Type"], "application/javascript")
		self.assertEqual(response["Service-Worker-Allowed"], "/")
		self.assertEqual(response["Cache-Control"], "no-cache")
		self.assertContains(response, "addEventListener('fetch'")
		self.assertContains(response, "OFFLINE_URL")

	def test_login_page_links_manifest_and_registers_service_worker(self):
		response = self.client.get(reverse("login"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '<link rel="manifest" href="/static/manifest.json">')
		self.assertContains(response, "navigator.serviceWorker.register('/sw.js')")


class AppNavigationTemplateTests(SimpleTestCase):
	def test_shared_navigation_partials_render_for_each_role(self):
		template = get_template("fitness/partials/app_navigation.html").template

		for role in ("Member", "Admin", "Trainer"):
			with self.subTest(role=role):
				request = RequestFactory().get(reverse("dashboard"))
				request.user = SimpleNamespace(
					role=SimpleNamespace(name=role),
					is_staff=False,
					is_superuser=False,
					username="navigation-test",
					get_full_name=lambda: "Navigation Test",
				)

				rendered = template.render(
					RequestContext(request, {"desktop_sidebar": True})
				)

				self.assertIn('aria-label="Sidebar"', rendered)
				self.assertIn('aria-label="Main"', rendered)
				self.assertIn("Workout schedule", rendered)
				self.assertIn("Exercise directory", rendered)
				self.assertIn("Profile", rendered)
				if role == "Member":
					self.assertIn(reverse("ai_workouts"), rendered)
				else:
					self.assertNotIn(reverse("ai_workouts"), rendered)


class WorkoutResponseFormattingTests(SimpleTestCase):
	def test_youtube_embed_url_accepts_standard_video_url_forms(self):
		video_id = "AbCdEf123_-"

		for video_url in (
			f"https://www.youtube.com/watch?v={video_id}&feature=share",
			f"https://youtu.be/{video_id}?si=token",
			f"https://m.youtube.com/shorts/{video_id}",
			f"https://www.youtube-nocookie.com/embed/{video_id}",
		):
			with self.subTest(video_url=video_url):
				self.assertEqual(
					youtube_embed_url(video_url),
					f"https://www.youtube.com/embed/{video_id}",
				)

	def test_youtube_embed_url_rejects_search_pages_and_untrusted_or_invalid_urls(self):
		for video_url in (
			"https://www.youtube.com/results?search_query=bench+press",
			"https://youtube.com.evil.example/watch?v=AbCdEf123_-",
			"javascript:alert(1)",
			"https://www.youtube.com/watch?v=too-short",
		):
			with self.subTest(video_url=video_url):
				self.assertIsNone(youtube_embed_url(video_url))

	def test_markdown_sections_and_bullets_render_as_cards(self):
		formatted = _format_workout_response(
			"Chest workout plan\n\n"
			"## Option A: Strength\n"
			"- **Barbell Bench Press**: 4 sets x 8 reps\n"
			"- Incline Dumbbell Press: 3 sets x 10 reps\n\n"
			"## Option B: Volume\n"
			"* Dumbbell Fly: 3 sets x 12 reps"
		)

		self.assertIn('class="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch"', formatted)
		self.assertIn('class="lg:col-span-2 min-w-0 rounded-xl border border-[#E7E3D6] bg-white p-4 sm:p-5"', formatted)
		self.assertIn("Option A: Strength", formatted)
		self.assertIn("Option B: Volume", formatted)
		self.assertIn("<strong>Barbell Bench Press</strong>", formatted)
		self.assertEqual(formatted.count("<article "), 2)
		self.assertEqual(formatted.count('<iframe class="w-full aspect-video rounded-xl shadow-md"'), 3)
		self.assertNotIn("<a ", formatted)

	def test_workout_response_embeds_only_a_valid_direct_video_reference(self):
		with patch("fitness.views.ALL_EXERCISE_GUIDES", ({
			"name": "Barbell Bench Press",
			"embed_url": "https://www.youtube.com/embed/AbCdEf123_-",
		},)):
			formatted = _format_workout_response(
				"## Option A: Strength\n- Barbell Bench Press: 4 sets x 8 reps"
			)

		self.assertIn(
			'<iframe class="w-full aspect-video rounded-xl shadow-md" '
			'src="https://www.youtube.com/embed/AbCdEf123_-"',
			formatted,
		)
		self.assertIn("allowfullscreen", formatted)
		self.assertNotIn("<a ", formatted)

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

	def test_admin_sees_all_attendance_and_trainer_sees_only_assigned_attendance(self):
		first_record = Attendance.objects.create(member=self.member_one, status="Present")
		second_record = Attendance.objects.create(member=self.member_two, status="Absent")
		unassigned_record = Attendance.objects.create(member=self.unassigned_member, status="Present")

		for user in (self.admin, self.trainer):
			with self.subTest(role=user.role.name):
				self.client.force_login(user)
				response = self.client.get(reverse("dashboard"))

				self.assertEqual(response.status_code, 200)
				expected_attendances = (
					[first_record, second_record, unassigned_record]
					if user == self.admin
					else [first_record, second_record]
				)
				self.assertCountEqual(response.context["attendances"], expected_attendances)

	def test_trainer_dashboard_metrics_count_only_assigned_members_and_plans(self):
		self.member_one.is_active = False
		self.member_one.save(update_fields=["is_active"])
		WorkoutPlan.objects.create(
			title="Assigned strength",
			description="Assigned workout",
			member=self.member_one,
		)
		WorkoutPlan.objects.create(
			title="Assigned conditioning",
			description="Assigned workout",
			member=self.member_two,
		)
		WorkoutPlan.objects.create(
			title="Unassigned strength",
			description="Unassigned workout",
			member=self.unassigned_member,
		)
		DietPlan.objects.create(
			title="Assigned nutrition",
			meal_details="Assigned diet",
			member=self.member_one,
		)
		DietPlan.objects.create(
			title="Unassigned nutrition",
			meal_details="Unassigned diet",
			member=self.unassigned_member,
		)
		Attendance.objects.create(member=self.member_one, status="Present")
		Attendance.objects.create(member=self.member_two, status="Absent")
		Attendance.objects.create(member=self.unassigned_member, status="Present")
		self.client.force_login(self.trainer)

		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["assigned_member_count"], 2)
		self.assertEqual(response.context["active_assigned_member_count"], 1)
		self.assertEqual(response.context["workout_count"], 2)
		self.assertEqual(response.context["diet_count"], 1)
		self.assertEqual(response.context["attendance_count"], 2)
		self.assertContains(response, "Active assigned members")
		self.assertContains(response, "Assigned workout plans")
		self.assertContains(response, "Assigned diet plans")
		self.assertContains(response, "Assigned attendance logs")
		self.assertNotContains(response, "Unassigned strength")
		self.assertNotContains(response, "Unassigned nutrition")

	def test_dashboard_navigation_keeps_shared_modules_and_role_access(self):
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
				self.assertContains(response, "Exercise Directory")
				self.assertContains(response, "AI Generator")
				module_nav = response.content.split(
					b'<nav class="space-y-1 p-3" aria-label="Application modules">', 1
				)[1].split(b"</nav>", 1)[0]
				self.assertEqual(module_nav.count(b"<a "), 8)
				for label in (
					b"Home",
					b"Daily Log",
					b"Workout Schedule",
					b"Nutrition",
					b"Weight &amp; Stats",
					b"Exercise Directory",
					b"AI Generator",
					b"Profile",
				):
					self.assertIn(label, module_nav)
				if ai_available:
					self.assertContains(response, reverse("ai_workouts"))
				else:
					self.assertNotContains(
						response, 'href="' + reverse("ai_workouts") + '"'
					)


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
	def test_signup_redirects_to_dashboard_without_sending_email(self):
		response = self.client.post(reverse("signup"), {
			"username": "new_member",
			"email": "new_member@example.com",
			"password1": "CaliberPass2026!",
			"password2": "CaliberPass2026!",
		})

		self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
		self.assertIn("_auth_user_id", self.client.session)
		self.assertEqual(mail.outbox, [])

	def test_login_redirects_members_to_daily_logging(self):
		user = CustomUser.objects.create_user(
			username="login_member",
			password="CaliberPass2026!",
			is_profile_complete=True,
		)

		response = self.client.post(reverse("login"), {
			"username": user.username,
			"password": "CaliberPass2026!",
		})

		self.assertRedirects(response, reverse("member_logging"), fetch_redirect_response=False)

	def test_login_keeps_admins_and_trainers_on_dashboard(self):
		for user in (self.admin, self.trainer):
			with self.subTest(role=user.role.name):
				user.set_password("CaliberPass2026!")
				user.save(update_fields=["password"])
				response = self.client.post(reverse("login"), {
					"username": user.username,
					"password": "CaliberPass2026!",
				})

				self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
				self.client.logout()

	def test_logout_redirects_to_login(self):
		self.client.force_login(self.member_one)

		response = self.client.post(reverse("logout"))

		self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
		self.assertNotIn("_auth_user_id", self.client.session)


class ExerciseDirectoryTests(TestCase):
	def setUp(self):
		self.member = CustomUser.objects.create_user(
			username="reference_member",
			is_profile_complete=True,
		)
		self.client.force_login(self.member)
		self.url = reverse("exercise_directory")

	def test_directory_lists_categories_without_non_embeddable_search_links(self):
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["guide_count"], 32)
		self.assertEqual(
			[category["name"] for category in response.context["exercise_groups"]],
			["Chest", "Back", "Shoulders", "Biceps", "Triceps", "Legs", "Core", "Cardio"],
		)
		self.assertEqual(response.content.decode().count('<iframe class="w-full aspect-video rounded-xl"'), 32)
		self.assertContains(response, 'src="https://www.youtube.com/embed/rT7DgCr-3pg"')
		self.assertNotContains(response, "youtube.com/results")
		self.assertContains(response, 'aria-label="Primary navigation"')

	def test_directory_includes_biceps_and_triceps_guides_with_working_embeds(self):
		response = self.client.get(self.url)
		guides = {
			guide["name"]: guide
			for group in response.context["exercise_groups"]
			for guide in group["exercises"]
		}
		expected_guides = {
			"Dumbbell Bicep Curl": ("Biceps", "sAq_ocpRh_I"),
			"Barbell Curl": ("Biceps", "kwG2ipFRgfo"),
			"Dumbbell Hammer Curl": ("Biceps", "zC3nLlEvin4"),
			"Preacher Curl": ("Biceps", "fIWP-FRFNU0"),
			"Triceps Cable Pushdown": ("Triceps", "-zLyUAo1gMw"),
			"Skull Crushers": ("Triceps", "d_KZxkY_0cM"),
			"Dumbbell Overhead Triceps Extension": ("Triceps", "YbX7Wd8jQ-Q"),
		}

		self.assertContains(response, 'class="ex-card surface flex h-full min-h-48 min-w-0 flex-col justify-between gap-4 p-4 sm:p-5"')
		self.assertContains(response, 'class="w-full aspect-video rounded-xl"')
		for name, (muscle_group, video_id) in expected_guides.items():
			with self.subTest(exercise=name):
				self.assertEqual(guides[name]["muscle_group"], muscle_group)
				self.assertTrue(guides[name]["description"])
				self.assertEqual(
					guides[name]["embed_url"],
					f"https://www.youtube.com/embed/{video_id}",
				)
				self.assertContains(response, f'title="{name} video demonstration"')

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


class WorkoutSplitBuilderTests(TestCase):
	def setUp(self):
		self.member = CustomUser.objects.create_user(
			username="split_member",
			is_profile_complete=True,
		)
		self.client.force_login(self.member)
		self.url = reverse("workout_split")

	def test_builder_shows_day_target_controls_and_exercise_library(self):
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["workout_split_schedule"], [])
		self.assertContains(response, 'aria-label="Primary navigation"')
		self.assertEqual(response.content.count(b'aria-label="Workout schedule"'), 2)
		self.assertContains(response, 'aria-label="Home"')
		self.assertLess(
			response.content.index(b'aria-label="Primary navigation"'),
			response.content.index(b"<main"),
		)
		self.assertContains(response, "Plan your weekly training")
		self.assertContains(response, "Quick pairing suggestions")
		self.assertContains(response, "Chest + Triceps")
		self.assertContains(response, "Back + Biceps")
		self.assertContains(response, "Upper body")
		self.assertContains(response, "Lower body")
		self.assertContains(response, 'id="split-weekday"')
		self.assertContains(response, 'aria-label="Quick navigation"')
		self.assertContains(response, "Build your schedule")
		self.assertContains(response, 'value="Chest"')
		self.assertContains(response, 'https://www.youtube.com/embed/rT7DgCr-3pg')

	def test_workout_split_offers_common_pairing_presets(self):
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 200)
		for preset in (
			"Chest + Triceps",
			"Back + Biceps",
			"Upper body",
			"Lower body",
			"Push",
			"Pull",
			"Full body",
		):
			with self.subTest(preset=preset):
				self.assertContains(response, preset)
		self.assertContains(response, 'data-muscle-preset="chest-triceps"')
		self.assertContains(response, 'data-muscle-preset="back-biceps"')

	def test_shared_sidebar_is_stable_across_member_pages(self):
		for page_url in (
			reverse("dashboard"),
			self.url,
			reverse("exercise_directory"),
			reverse("ai_workouts"),
		):
			with self.subTest(page=page_url):
				response = self.client.get(page_url)
				self.assertEqual(response.status_code, 200)
				self.assertContains(response, 'aria-label="Primary navigation"')
				self.assertContains(response, 'class="fixed inset-y-0 left-0')
				self.assertContains(response, reverse("member_logging"))
				self.assertContains(response, reverse("workout_split"))
				content_position = response.content.find(b"<main")
				if content_position == -1:
					content_position = response.content.find(b'class="page')
				self.assertGreater(content_position, 0)
				self.assertLess(
					response.content.index(b'aria-label="Primary navigation"'),
					content_position,
				)

	def test_dashboard_sidebar_keeps_split_link_outside_tab_content(self):
		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'aria-label="Workout schedule"')
		self.assertContains(response, reverse("workout_split"))
		self.assertLess(
			response.content.index(b'aria-label="Workout schedule"'),
			response.content.index(b"<main"),
		)

	def test_member_saves_and_updates_daywise_split_and_dashboard_schedule(self):
		response = self.client.post(self.url, {
			"title": "Push pull routine",
			"split_data": '{"0":["Chest","Triceps"],"2":["Back","Biceps"]}',
		})

		self.assertRedirects(response, reverse("dashboard"))
		split = WorkoutSplit.objects.get(member=self.member)
		self.assertEqual(split.title, "Push pull routine")
		self.assertEqual(
			list(split.days.values_list("weekday", "muscle_groups")),
			[(0, ["Chest", "Triceps"]), (2, ["Back", "Biceps"])],
		)
		dashboard = self.client.get(reverse("dashboard"))
		self.assertEqual(
			[(day["day_name"], day["muscle_groups"]) for day in dashboard.context["workout_split_schedule"]],
			[("Monday", ["Chest", "Triceps"]), ("Wednesday", ["Back", "Biceps"])],
		)
		self.assertContains(dashboard, "Your weekly workout split")
		self.assertContains(dashboard, "Push pull routine")
		self.assertContains(dashboard, "Chest, Triceps")

		builder = self.client.get(self.url)
		self.assertEqual(builder.context["split_data"], {
			"0": ["Chest", "Triceps"],
			"2": ["Back", "Biceps"],
		})
		self.assertContains(builder, "Barbell Bench Press")
		self.assertContains(builder, "Lat Pulldown")

		response = self.client.post(self.url, {
			"title": "Leg day focus",
			"split_data": '{"4":["Legs"]}',
		})
		self.assertRedirects(response, reverse("dashboard"))
		split.refresh_from_db()
		self.assertEqual(split.title, "Leg day focus")
		self.assertEqual(
			list(split.days.values_list("weekday", "muscle_groups")),
			[(4, ["Legs"])],
		)

	def test_invalid_split_does_not_create_or_overwrite_saved_schedule(self):
		response = self.client.post(self.url, {
			"title": "Invalid plan",
			"split_data": '{"1":["Not a muscle"]}',
		})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Each scheduled day needs valid")
		self.assertFalse(WorkoutSplit.objects.exists())

		split = WorkoutSplit.objects.create(member=self.member, title="Existing plan")
		WorkoutSplitDay.objects.create(split=split, weekday=0, muscle_groups=["Chest"])
		response = self.client.post(self.url, {
			"title": "Changed plan",
			"split_data": '{"2":[]}',
		})
		self.assertEqual(response.status_code, 200)
		split.refresh_from_db()
		self.assertEqual(split.title, "Existing plan")
		self.assertEqual(list(split.days.values_list("weekday", flat=True)), [0])

	def test_split_schedule_is_private_and_builder_is_member_only(self):
		WorkoutSplit.objects.create(member=self.member, title="Private plan")
		other_member = CustomUser.objects.create_user(
			username="other_split_member",
			is_profile_complete=True,
		)
		self.client.force_login(other_member)

		response = self.client.get(self.url)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["workout_split_schedule"], [])
		dashboard = self.client.get(reverse("dashboard"))
		self.assertEqual(dashboard.context["workout_split_schedule"], [])
		self.assertNotContains(dashboard, "Private plan")

		trainer_role = Role.objects.create(name="Trainer")
		trainer = CustomUser.objects.create_user(username="split_trainer", role=trainer_role)
		self.client.force_login(trainer)
		self.assertRedirects(self.client.get(self.url), reverse("dashboard"))

		incomplete_member = CustomUser.objects.create_user(
			username="incomplete_split_member",
			is_profile_complete=False,
		)
		self.client.force_login(incomplete_member)
		self.assertRedirects(self.client.get(self.url), reverse("complete_profile"))


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
		self.assertContains(response, 'https://www.youtube.com/embed/rT7DgCr-3pg')
		self.assertContains(response, 'aria-label="Primary navigation"')
		self.assertContains(response, "Featured tools")
		self.assertContains(response, 'href="#member-meal-section"')
		self.assertContains(response, 'href="#member-workout-section"')
		self.assertContains(response, 'href="#member-weight-section"')
		self.assertContains(response, "AI workout generator")
		self.assertContains(response, "Exercise directory")
		self.assertContains(response, 'name="activity"')
		self.assertNotContains(response, 'name="exercise_details"')
		self.assertContains(response, 'data-voice-target="meal-description"')
		self.assertContains(response, 'data-voice-target="workout-notes"')
		self.assertContains(response, 'data-voice-target="water-notes"')
		self.assertContains(response, 'data-voice-target="cardio-notes"')
		self.assertContains(response, 'data-voice-target="weight-notes"')
		self.assertContains(response, 'name="notes" maxlength="2000"')
		self.assertContains(response, "speech recognition")

	def test_voice_dictation_controls_are_available_for_meal_and_workout_notes(self):
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'data-voice-target="meal-description"')
		self.assertContains(response, 'data-voice-status="meal-voice-status"')
		self.assertContains(response, 'data-voice-target="workout-notes"')
		self.assertContains(response, 'data-voice-status="workout-voice-status"')
		self.assertContains(response, 'data-voice-target="water-notes"')
		self.assertContains(response, 'data-voice-status="water-voice-status"')
		self.assertContains(response, 'data-voice-target="cardio-notes"')
		self.assertContains(response, 'data-voice-status="cardio-voice-status"')
		self.assertContains(response, 'data-voice-target="weight-notes"')
		self.assertContains(response, 'data-voice-status="weight-voice-status"')
		self.assertContains(response, "Microphone permission was denied")
		self.assertContains(response, "Dictation is not supported by this browser")

	def test_selected_exercise_and_training_presets_are_saved(self):
		response = self.client.post(self.url, {
			"log_type": "workout",
			"did_workout": "yes",
			"log_date": "2026-09-18",
			"muscle_split": "Chest",
			"notes": "Felt strong on the final set.",
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
		self.assertEqual(workout_log.notes, "Felt strong on the final set.")
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

	def test_workout_notes_are_length_limited(self):
		response = self.client.post(self.url, {
			"log_type": "workout",
			"did_workout": "no",
			"log_date": "2026-09-18",
			"notes": "x" * 2001,
		})
		self.assertRedirects(response, self.url)
		self.assertFalse(WorkoutLog.objects.exists())

	def test_cardio_notes_support_voice_note_length_and_reject_overlong_text(self):
		response = self.client.post(self.url, {
			"log_type": "cardio",
			"log_date": "2026-09-18",
			"activity": "Cycling",
			"duration_minutes": "35",
			"intensity": "Moderate",
			"notes": "x" * 2001,
		})
		self.assertRedirects(response, self.url)
		self.assertFalse(CardioLog.objects.exists())

		response = self.client.post(self.url, {
			"log_type": "cardio",
			"log_date": "2026-09-18",
			"activity": "Cycling",
			"duration_minutes": "35",
			"intensity": "Moderate",
			"notes": "A longer dictated note. " * 20,
		})
		self.assertRedirects(response, self.url)
		self.assertEqual(len(CardioLog.objects.get().notes), 479)

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

	def test_meal_logging_saves_macros_and_rejects_negative_values(self):
		response = self.client.post(self.url, {
			"log_type": "meal",
			"log_date": "2026-09-17",
			"meal_type": "Lunch",
			"description": "Rice and grilled chicken",
			"calories": "625.5",
			"protein": "42.25",
			"carbs": "70",
			"fats": "15.75",
		})

		self.assertRedirects(response, self.url)
		meal_log = self.member.meal_logs.get()
		self.assertEqual(
			(meal_log.calories, meal_log.protein, meal_log.carbs, meal_log.fats),
			(Decimal("625.50"), Decimal("42.25"), Decimal("70.00"), Decimal("15.75")),
		)
		self.client.post(self.url, {
			"log_type": "meal",
			"log_date": "2026-09-17",
			"meal_type": "Lunch",
			"description": "Invalid meal",
			"calories": "-1",
			"protein": "0",
			"carbs": "0",
			"fats": "0",
		})
		self.assertEqual(self.member.meal_logs.count(), 1)

	def test_dashboard_shows_only_today_aggregate_and_target_gap(self):
		today = timezone.localdate()
		MealLog.objects.create(
			member=self.member,
			date=today,
			meal_type="Breakfast",
			description="Breakfast",
			calories=Decimal("650"),
			protein=Decimal("25"),
			carbs=Decimal("80"),
			fats=Decimal("18"),
		)
		MealLog.objects.create(
			member=self.member,
			date=today,
			meal_type="Lunch",
			description="Lunch",
			calories=Decimal("500"),
			protein=Decimal("30"),
			carbs=Decimal("60"),
			fats=Decimal("20"),
		)
		MealLog.objects.create(
			member=self.member,
			date=today - timedelta(days=1),
			meal_type="Dinner",
			description="Yesterday",
			calories=Decimal("900"),
		)
		other_member = CustomUser.objects.create_user(username="private_nutrition_member")
		MealLog.objects.create(
			member=other_member,
			date=today,
			meal_type="Dinner",
			description="Other member",
			calories=Decimal("2000"),
		)

		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		summary = response.context["nutrition_summary"]
		self.assertEqual(summary["nutrients"][0]["total"], Decimal("1150"))
		self.assertEqual(summary["nutrients"][0]["achievement"], 58)
		self.assertEqual(summary["calorie_gap"], Decimal("850"))
		self.assertEqual(summary["calorie_gap_type"], "deficit")
		self.assertContains(response, "Today’s nutrition")
		self.assertContains(response, "850 kcal below")

	def test_weight_checkin_is_member_private_and_updates_one_daily_entry(self):
		weight_date = date(2026, 9, 17)
		response = self.client.post(self.url, {
			"log_type": "weight",
			"log_date": weight_date.isoformat(),
			"weight_kg": "72.40",
			"notes": "Before breakfast",
		})
		self.assertRedirects(response, self.url)
		self.client.post(self.url, {
			"log_type": "weight",
			"log_date": weight_date.isoformat(),
			"weight_kg": "72.10",
			"notes": "After workout",
		})
		self.assertEqual(self.member.weight_logs.count(), 1)
		self.assertEqual(self.member.weight_logs.get().weight_kg, Decimal("72.10"))
		self.assertEqual(self.member.weight_logs.get().notes, "After workout")

		other_member = CustomUser.objects.create_user(username="weight_private_member", is_profile_complete=True)
		other_weight = WeightLog.objects.create(member=other_member, date=weight_date, weight_kg=Decimal("80"))
		response = self.client.get(self.url)
		self.assertEqual(list(response.context["weight_logs"]), [self.member.weight_logs.get()])
		self.assertNotContains(response, f"{other_weight.weight_kg} kg")

	def test_water_intake_is_private_validated_and_updatable_per_day(self):
		water_date = date(2026, 9, 17)
		response = self.client.post(self.url, {
			"log_type": "water",
			"log_date": water_date.isoformat(),
			"liters": "1.75",
			"notes": "Tracked throughout the day",
		})
		self.assertRedirects(response, self.url)
		self.client.post(self.url, {
			"log_type": "water",
			"log_date": water_date.isoformat(),
			"liters": "2.10",
			"notes": "Including training",
		})
		self.assertEqual(self.member.water_logs.count(), 1)
		self.assertEqual(self.member.water_logs.get().liters, Decimal("2.10"))
		self.assertEqual(self.member.water_logs.get().notes, "Including training")

		self.client.post(self.url, {
			"log_type": "water",
			"log_date": water_date.isoformat(),
			"liters": "100",
		})
		self.assertEqual(self.member.water_logs.get().liters, Decimal("2.10"))

		today = timezone.localdate()
		WaterLog.objects.create(member=self.member, date=today, liters=Decimal("1.40"))
		MealLog.objects.create(
			member=self.member,
			date=today,
			meal_type="Lunch",
			description="Today's meal",
			calories=Decimal("625"),
		)
		other_member = CustomUser.objects.create_user(
			username="private_water_member",
			is_profile_complete=True,
		)
		WaterLog.objects.create(member=other_member, date=today, liters=Decimal("8.50"))

		response = self.client.get(self.url)
		self.assertEqual(response.context["daily_water_liters"], Decimal("1.40"))
		self.assertEqual(response.context["daily_calorie_total"], Decimal("625"))
		self.assertEqual(list(response.context["water_logs"]), list(self.member.water_logs.order_by("-date", "-created_at")))
		self.assertContains(response, "Water logged today")
		self.assertNotContains(response, "8.5 L")

	def test_daily_log_notes_are_limited_and_chart_uses_chartjs(self):
		log_date = date(2026, 9, 17)
		for log_type, values in (
			("weight", {"weight_kg": "72.40"}),
			("water", {"liters": "1.80"}),
		):
			self.client.post(self.url, {
				"log_type": log_type,
				"log_date": log_date.isoformat(),
				"notes": "x" * 2001,
				**values,
			})
		self.assertFalse(self.member.weight_logs.exists())
		self.assertFalse(self.member.water_logs.exists())

		today = timezone.localdate()
		WeightLog.objects.create(member=self.member, date=today, weight_kg=Decimal("72.40"))
		WeightGoal.objects.create(
			member=self.member,
			starting_weight_kg=Decimal("72.40"),
			target_weight_kg=Decimal("67.00"),
			start_date=today,
			target_date=today + timedelta(days=84),
		)
		response = self.client.get(reverse("dashboard"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Chart.js")
		self.assertContains(response, "new window.Chart(")
		self.assertContains(response, "weight-goal-data-member-weight-progress")
		self.assertContains(response, "weekly milestones")

	def test_dashboard_weight_modal_saves_validated_daily_weight(self):
		response = self.client.get(reverse("dashboard"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'id="weight-log-modal"')
		self.assertContains(response, 'aria-labelledby="weight-modal-title"')
		self.assertContains(response, 'id="dashboard-section-switcher"')
		self.assertContains(response, "Nutrition")
		self.assertContains(response, "Weight &amp; Stats")
		self.assertContains(response, 'data-weight-range="7"')
		self.assertContains(response, 'data-weight-range="30"')

		response = self.client.post(reverse("weight_log"), {
			"log_date": timezone.localdate().isoformat(),
			"weight_kg": "71.85",
		})
		self.assertRedirects(response, reverse("dashboard"))
		self.assertEqual(self.member.weight_logs.get().weight_kg, Decimal("71.85"))

	def test_member_dashboard_has_searchable_module_cards(self):
		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'id="dashboard-feature-search"')
		self.assertContains(response, 'role="search"')
		self.assertContains(response, 'id="dashboard-feature-sections"')
		self.assertContains(response, 'data-feature-card')
		self.assertContains(response, 'data-search-terms="water hydration intake drink liters daily"')
		self.assertContains(response, "Your fitness workspace")
		self.assertContains(response, "Daily logging")
		self.assertContains(response, "Workout planning")
		self.assertContains(response, "Nutrition &amp; meals")
		self.assertContains(response, "Water intake")
		self.assertContains(response, "Weight &amp; stats")
		self.assertContains(response, "Attendance")
		self.assertContains(response, "Exercise directory")
		self.assertContains(response, "AI workout generator")
		self.assertContains(response, reverse("member_logging") + "#member-daily-log-section")
		self.assertContains(response, reverse("workout_split"))
		self.assertContains(response, reverse("exercise_directory"))
		self.assertContains(response, reverse("ai_workouts"))
		self.assertContains(response, "updateFeatureCards")

	def test_weight_goal_uses_latest_weighin_and_shows_goal_progress(self):
		today = timezone.localdate()
		start_date = today - timedelta(days=30)
		WeightLog.objects.create(
			member=self.member,
			date=start_date,
			weight_kg=Decimal("75.00"),
		)
		response = self.client.post(reverse("weight_goal"), {
			"target_weight_kg": "70.00",
			"target_date": (today + timedelta(days=90)).isoformat(),
			"return_to": "member_logging",
		})
		self.assertRedirects(response, self.url)

		goal = WeightGoal.objects.get(member=self.member)
		self.assertEqual(goal.starting_weight_kg, Decimal("75.00"))
		self.assertEqual(goal.start_date, start_date)
		self.assertEqual(goal.target_weight_kg, Decimal("70.00"))

		WeightLog.objects.create(member=self.member, date=today, weight_kg=Decimal("72.50"))
		dashboard = self.client.get(reverse("dashboard"))
		self.assertEqual(dashboard.context["weight_goal_progress"]["progress_percent"], 50)
		self.assertEqual(dashboard.context["weight_goal_progress"]["expected_weight_kg"], Decimal("73.75"))
		self.assertEqual(dashboard.context["weight_goal_progress"]["weekly_pace_kg"], Decimal("0.29"))
		self.assertEqual(dashboard.context["weight_goal_progress"]["next_milestone_weight_kg"], Decimal("73.54"))
		self.assertEqual(dashboard.context["weight_goal_progress"]["pace_status"], "ahead of")
		self.assertContains(dashboard, "Planned goal trajectory")
		self.assertContains(dashboard, "1.25 kg ahead")

		logging_page = self.client.get(self.url)
		self.assertContains(logging_page, "weight-goal-target-member_logging")
		self.assertContains(logging_page, 'data-weight-range="goal"')
		self.assertEqual(logging_page.context["weight_goal_chart_data"]["target_weight_kg"], 70.0)

	def test_weight_goal_requires_a_valid_future_target_and_starting_weight(self):
		today = timezone.localdate()
		response = self.client.post(reverse("weight_goal"), {
			"target_weight_kg": "70.00",
			"target_date": (today + timedelta(days=90)).isoformat(),
		})
		self.assertRedirects(response, reverse("dashboard"))
		self.assertFalse(WeightGoal.objects.exists())
		self.assertContains(self.client.get(reverse("dashboard")), "Set a weight goal")

		WeightLog.objects.create(member=self.member, date=today, weight_kg=Decimal("70.00"))
		response = self.client.post(reverse("weight_goal"), {
			"target_weight_kg": "70.00",
			"target_date": (today + timedelta(days=90)).isoformat(),
		})
		self.assertRedirects(response, reverse("dashboard"))
		self.assertFalse(WeightGoal.objects.exists())

		response = self.client.post(reverse("weight_goal"), {
			"target_weight_kg": "72.00",
			"target_date": today.isoformat(),
		})
		self.assertRedirects(response, reverse("dashboard"))
		self.assertFalse(WeightGoal.objects.exists())

	def test_weight_goal_is_private_and_can_be_removed(self):
		today = timezone.localdate()
		admin = CustomUser.objects.create_user(username="weight_goal_admin", is_staff=True)
		self.client.force_login(admin)
		response = self.client.post(reverse("weight_goal"), {
			"target_weight_kg": "70.00",
			"target_date": (today + timedelta(days=90)).isoformat(),
		})
		self.assertRedirects(response, reverse("dashboard"))
		self.assertFalse(WeightGoal.objects.exists())

		self.client.force_login(self.member)
		WeightLog.objects.create(member=self.member, date=today, weight_kg=Decimal("75.00"))
		self.client.post(reverse("weight_goal"), {
			"target_weight_kg": "70.00",
			"target_date": (today + timedelta(days=90)).isoformat(),
		})
		other_member = CustomUser.objects.create_user(
			username="private_goal_member",
			is_profile_complete=True,
		)
		self.client.force_login(other_member)
		other_dashboard = self.client.get(reverse("dashboard"))
		self.assertIsNone(other_dashboard.context["weight_goal"])
		self.assertNotContains(other_dashboard, "70.00 kg")

		self.client.force_login(self.member)
		response = self.client.post(reverse("weight_goal"), {
			"action": "clear",
			"return_to": "dashboard",
		})
		self.assertRedirects(response, reverse("dashboard"))
		self.assertFalse(WeightGoal.objects.filter(member=self.member).exists())

	def test_admin_and_trainer_member_detail_include_scoped_weight_history(self):
		member = CustomUser.objects.create_user(username="weight_chart_member")
		admin = CustomUser.objects.create_user(username="weight_chart_admin", is_staff=True)
		trainer_role = Role.objects.create(name="Trainer")
		trainer = CustomUser.objects.create_user(username="weight_chart_trainer", role=trainer_role)
		TrainerMemberAssignment.objects.create(trainer=trainer, member=member)
		today = timezone.localdate()
		WeightLog.objects.create(
			member=member,
			date=today,
			weight_kg=Decimal("75.20"),
		)
		WeightLog.objects.create(
			member=member,
			date=today - timedelta(days=31),
			weight_kg=Decimal("76.00"),
		)
		other_member = CustomUser.objects.create_user(username="other_weight_member")
		WeightLog.objects.create(member=other_member, date=today, weight_kg=Decimal("99"))
		detail_url = reverse("admin_member_detail", args=[member.pk])

		for staff_user in (admin, trainer):
			with self.subTest(role="admin" if staff_user.is_staff else "trainer"):
				self.client.force_login(staff_user)
				response = self.client.get(detail_url)
				self.assertEqual(response.status_code, 200)
				self.assertEqual(response.context["weight_chart_data"], [
					{"date": today.isoformat(), "weight_kg": 75.2},
				])
				self.assertContains(response, "Weight progress")
				self.assertContains(response, "75.2 kg")
				self.assertNotContains(response, "99.00 kg")
				self.assertNotContains(response, (today - timedelta(days=31)).isoformat())

		self.client.force_login(trainer)
		self.assertEqual(
			self.client.get(reverse("admin_member_detail", args=[other_member.pk])).status_code,
			404,
		)

	def test_coaching_uses_seven_day_member_macro_and_weight_trends(self):
		today = timezone.localdate()
		for days_ago, carbs, calories in ((0, 320, 2200), (1, 290, 2100), (2, 100, 1800)):
			MealLog.objects.create(
				member=self.member,
				date=today - timedelta(days=days_ago),
				meal_type="Dinner",
				description="Logged meal",
				calories=calories,
				protein=25,
				carbs=carbs,
				fats=20,
			)
		WeightLog.objects.create(
			member=self.member,
			date=today - timedelta(days=6),
			weight_kg=Decimal("72.00"),
		)
		WeightLog.objects.create(
			member=self.member,
			date=today,
			weight_kg=Decimal("72.50"),
		)
		yesterday_outside_window = today - timedelta(days=7)
		MealLog.objects.create(
			member=self.member,
			date=yesterday_outside_window,
			meal_type="Dinner",
			description="Outside rolling week",
			calories=5000,
			carbs=600,
		)
		other_member = CustomUser.objects.create_user(username="other_coaching_member")
		MealLog.objects.create(
			member=other_member,
			date=today,
			meal_type="Dinner",
			description="Private meal",
			calories=5000,
			carbs=600,
		)

		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		analysis = response.context["coaching_analysis"]
		self.assertEqual(analysis["days_logged"], 3)
		self.assertEqual(analysis["high_carb_days"], 2)
		self.assertEqual(analysis["average_macros"]["calories"], Decimal("6100") / 3)
		self.assertEqual(analysis["weight_change"], Decimal("0.50"))
		self.assertEqual(len(response.context["coaching_recommendations"]), 4)
		self.assertContains(response, "Your 7-day coaching check-in")
		self.assertContains(response, "For dinner, try a protein-forward plate")
		self.assertContains(response, "compare consistent morning readings")

	def test_coaching_without_logs_suggests_starting_tracking(self):
		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["coaching_analysis"]["days_logged"], 0)
		self.assertContains(response, "Log meals with their macros")
		self.assertContains(response, "Record weigh-ins on a few different days")

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
		self.assertEqual(response.content.decode().count('<iframe class="w-full aspect-video rounded-xl shadow-md"'), 28)
		self.assertNotContains(response, "Mechanical Tension")
		self.assertNotContains(response, "Metabolic Stress")
		self.assertContains(response, "Exercise form references")
		self.assertNotContains(response, "youtube.com/results")
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
		self.assertContains(response, '<iframe class="w-full aspect-video rounded-xl shadow-md"')
		self.assertContains(response, 'src="https://www.youtube.com/embed/rT7DgCr-3pg"')
		self.assertNotContains(response, "youtube.com/results")
