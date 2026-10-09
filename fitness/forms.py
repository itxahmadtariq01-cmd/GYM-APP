from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, TrainerProfile

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('username', 'email')


class TrainerOnboardingForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('username', 'first_name', 'last_name', 'email')


class TrainerProfileForm(forms.ModelForm):
    class Meta:
        model = TrainerProfile
        fields = ('years_experience', 'fitness_background', 'expertise', 'certifications')
        widgets = {
            'years_experience': forms.NumberInput(attrs={
                'min': 0,
                'max': 60,
                'class': 'w-full rounded-lg border border-[#DCD8CB] bg-[#FCFBF8] px-3 py-2.5 text-sm outline-none focus:border-[#1F4D3A]',
            }),
            'fitness_background': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full rounded-lg border border-[#DCD8CB] bg-[#FCFBF8] px-3 py-2.5 text-sm outline-none focus:border-[#1F4D3A]',
            }),
            'expertise': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full rounded-lg border border-[#DCD8CB] bg-[#FCFBF8] px-3 py-2.5 text-sm outline-none focus:border-[#1F4D3A]',
            }),
            'certifications': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full rounded-lg border border-[#DCD8CB] bg-[#FCFBF8] px-3 py-2.5 text-sm outline-none focus:border-[#1F4D3A]',
            }),
        }


class TrainerAssignmentForm(forms.Form):
    trainer = forms.ModelChoiceField(queryset=CustomUser.objects.none())
    members = forms.ModelMultipleChoiceField(
        queryset=CustomUser.objects.none(),
        required=False,
    )

    def __init__(self, *args, trainers=None, members=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['trainer'].queryset = trainers if trainers is not None else CustomUser.objects.none()
        self.fields['members'].queryset = members if members is not None else CustomUser.objects.none()