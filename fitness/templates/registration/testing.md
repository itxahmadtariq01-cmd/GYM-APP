# Role-Based Access Control (RBAC) - Testing Report

## 1. Test Accounts Configuration
- **Admin Account:** `admin_boss` (Password: `admin123`) — Full superuser and administrative privileges.
- **Trainer Account:** `trainer_john` (Password: `trainer123`) — Restricted to managing workout and diet plans.
- **Member Account:** `member_ahmad` (Password: `member123`) — Restricted to viewing personal dashboard data only.

## 2. Test Cases & Verification Results

| Test Case ID | Scenario Description | Expected Outcome | Actual Result | Status |
| :--- | :--- | :--- | :--- | :--- |
| **TC-01** | Log in as **Admin** (`admin_boss`) | Full access to dashboard, manage panel, and Django admin. | All controls and links visible and accessible. | **Passed ✅** |
| **TC-02** | Log in as **Trainer** (`trainer_john`) | Access workout/diet management, no delete member access. | Manage button visible; restricted admin links hidden. | **Passed ✅** |
| **TC-03** | Log in as **Member** (`member_ahmad`) | View only personal workouts, diet plans, and attendance. | Only personal entity data rendered; management buttons hidden. | **Passed ✅** |
| **TC-04** | Direct URL Access by Member (`/manage-workouts/`) | Block access gracefully with a 403 Forbidden response. | Successfully blocked with permission denied check. | **Passed ✅** |