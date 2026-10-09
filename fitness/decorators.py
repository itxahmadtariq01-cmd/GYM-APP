from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

def permission_required(permission_codename):
    """
    Decorator jo check karega ke user ke role ke paas 
    wo specific permission hai ya nahi.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            # Yahan role ka naam nahi check ho raha, balkay permission check ho rahi hai!
            if request.user.has_permission(permission_codename):
                return view_func(request, *args, **kwargs)
                
            return HttpResponseForbidden("Access Denied: Aapke role ke paas yeh permission nahi hai.")
        return _wrapped_view
    return decorator