from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from fitness.views import RoleBasedLoginView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', RoleBasedLoginView.as_view(), name='login'),
    path('', include('fitness.urls')),
    path('accounts/', include('django.contrib.auth.urls')),  # Login/Logout
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)