from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordChangeForm
from django.core.exceptions import ValidationError
import os
from .models import *
from .models import Address

MAX_PROFILE_IMAGE_SIZE_BYTES = 5 * 1024 * 1024
MAX_PROFILE_IMAGE_SIZE_MB = 5
ALLOWED_PROFILE_IMAGE_CONTENT_TYPES = {
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/webp',
    'image/gif',
}
ALLOWED_PROFILE_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        # Removed "role" from this list
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "gender",
        ]
    def __init__(self, *args, **kwargs):
        super(UserRegistrationForm, self).__init__(*args, **kwargs)

        # Apply styling to all fields dynamically
        for field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "class": "custom-input w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-700 focus:outline-none text-sm",
                    "placeholder": self.fields[field].label,
                }
            )

            # ✅ FIX: Add padding for icons (Check for 'password' in the name to catch password1 and password2)
            if field in ["email", "phone"] or "password" in field:
                existing_class = self.fields[field].widget.attrs.get("class", "")
                self.fields[field].widget.attrs["class"] = existing_class + " pl-10"

class UserLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super(UserLoginForm, self).__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "class": "custom-input w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-700 focus:outline-none text-sm",
                    "placeholder": self.fields[field].label,
                }
            )
            # ✅ FIX: Apply icon padding to the login password field too
            if "password" in field:
                self.fields[field].widget.attrs["class"] += " pl-10"


class BankDetailsForm(forms.ModelForm):
    class Meta:
        model = BankDetails
        fields = ['account_holder_name', 'account_number', 'ifsc_code', 'bank_name', 'upi_id']

    def __init__(self, *args, **kwargs):
        super(BankDetailsForm, self).__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "class": "custom-input w-full px-4 py-2.5 border border-gray-200 rounded-lg text-gray-700 focus:outline-none text-sm",
                    "placeholder": self.fields[field].label,
                }
            )
            if field in ["account_holder_name", "account_number", "ifsc_code", "bank_name", "upi_id"]:
                existing_class = self.fields[field].widget.attrs.get("class", "")
                self.fields[field].widget.attrs["class"] = existing_class + " pl-10"
                
class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'gender', 'date_of_birth', 'profile_image']
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date', 'class': 'custom-input'}),
        }
    def __init__(self, *args, **kwargs):
        super(UserUpdateForm, self).__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({
                "class": "w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-700 focus:outline-none focus:border-[#D4AF37] transition-colors text-sm",
                "placeholder": self.fields[field].label
            })
        # Special style for image upload
        self.fields['profile_image'].widget.attrs.update({
            "class": "block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-[#E8F3E8] file:text-[#2D5A27] hover:file:bg-[#dcfce7]",
            "accept": "image/jpeg,image/png,image/webp,image/gif",
        })

    def clean_profile_image(self):
        profile_image = self.cleaned_data.get('profile_image')
        if not profile_image:
            return profile_image

        if profile_image.size > MAX_PROFILE_IMAGE_SIZE_BYTES:
            raise ValidationError(f'Profile image must be {MAX_PROFILE_IMAGE_SIZE_MB}MB or smaller.')

        content_type = (getattr(profile_image, 'content_type', '') or '').lower()
        extension = os.path.splitext(getattr(profile_image, 'name', '') or '')[1].lower()
        if content_type in ALLOWED_PROFILE_IMAGE_CONTENT_TYPES:
            return profile_image
        if extension in ALLOWED_PROFILE_IMAGE_EXTENSIONS:
            return profile_image

        raise ValidationError('Only JPG, JPEG, PNG, WEBP, and GIF images are allowed. PDF files are not allowed.')

class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        # Use 'address_type' to match your model definition
        fields = ['address_type', 'street_address', 'city', 'state', 'zip_code', 'phone_number', 'is_default']

    def __init__(self, *args, **kwargs):
        super(AddressForm, self).__init__(*args, **kwargs)
        
        # Apply premium styling to all fields
        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                "class": "w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-700 focus:outline-none focus:border-[#D4AF37] transition-colors text-sm",
                "placeholder": field.label
            })
        
        # Add the 'Select' placeholder to the dropdown
        if 'address_type' in self.fields:
            self.fields['address_type'].choices = [('', 'Select Address Type')] + list(self.fields['address_type'].choices)

    def clean_city(self):
        city = (self.cleaned_data.get('city') or '').strip()
        if city and city.lower() != 'surat':
            raise ValidationError('We currently deliver only in Surat.')
        return city

class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ['name', 'phone', 'email', 'subject', 'message']
