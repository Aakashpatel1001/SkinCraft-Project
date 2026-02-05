from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordChangeForm
from .models import *
from .models import Address

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
            "class": "block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-[#E8F3E8] file:text-[#2D5A27] hover:file:bg-[#dcfce7]"
        })

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


class PaymentForm(forms.ModelForm):
    """Form for collecting payment details (bank details for COD refunds)"""
    class Meta:
        model = Payment
        fields = ['account_holder_name', 'account_number', 'ifsc_code', 'bank_name', 'upi_id']
        widgets = {
            'account_holder_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-700 focus:outline-none focus:border-[#1A3C34] transition-colors',
                'placeholder': 'Full Name',
                'required': True
            }),
            'account_number': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-700 focus:outline-none focus:border-[#1A3C34] transition-colors',
                'placeholder': '10-18 digit account number',
                'required': True
            }),
            'ifsc_code': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-700 focus:outline-none focus:border-[#1A3C34] transition-colors',
                'placeholder': 'e.g., SBIN0001234',
                'required': True
            }),
            'bank_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-700 focus:outline-none focus:border-[#1A3C34] transition-colors',
                'placeholder': 'Bank Name',
                'required': True
            }),
            'upi_id': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-700 focus:outline-none focus:border-[#1A3C34] transition-colors',
                'placeholder': 'user@bankname (Optional)',
                'required': False
            }),
        }
            
class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ['name', 'phone', 'email', 'subject', 'message']