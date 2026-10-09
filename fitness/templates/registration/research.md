# Research & Technical Implementation: Role-Based Access Control (RBAC) in Django

## 1. Django Groups & Permissions
- **What we learned:** Django provides a built-in authentication and authorization framework that links permissions directly to models (`add`, `change`, `delete`, `view`). We utilized Django `Group` and `Permission` models to assign specific roles to users.
- **Where we learned it:** [Using the Django authentication system | Django documentation](https://docs.djangoproject.com/en/6.1/topics/auth/)

## 2. Restricting Views via `@permission_required` / Decorators
- **What we learned:** To secure sensitive backend endpoints from unauthorized access, we applied Django's `@permission_required` decorator and custom role-checking logic. If an unauthorized user attempts access, it safely blocks them instead of crashing.
- **Where we learned it:** [Using the Django authentication system | Django documentation](https://docs.djangoproject.com/en/6.1/topics/auth/default/#the-permission-required-decorator)

## 3. Template-Level Restrictions & UI Hiding
- **What we learned:** Using Django's template engine, we evaluated the user's group/role dynamically (`{% if role == 'Admin' %}`) to hide administrative buttons, links, and panels (such as "Manage Workouts") from regular members.
- **Where we learned it:** [Built-in template tags and filters | Django documentation](https://docs.djangoproject.com/en/6.1/ref/templates/builtins/)

## 4. Object-Level Data Isolation
- **What we learned:** To ensure data privacy, queries were filtered dynamically based on `request.user`. A regular Member's view queries only their own records (`member=request.user`), preventing data leakage across user profiles.
- **Where we learned it:** [Making queries | Django documentation](https://docs.djangoproject.com/en/6.1/topics/db/queries/)