from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


SECRET_KEY = 'django-insecure-7l#dza29j*nm-4d7y^0=6kcortomzp(5$5uil2us_57puh#&a5'

DEBUG = True

ALLOWED_HOSTS = []

# Application definition
INSTALLED_APPS = [
    'jazzmin',
    'SkinCraft_Main',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'SkinCraft.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / "Templates",

            ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'SkinCraft_Main.context_processors.cart_count',
                'SkinCraft_Main.context_processors.categories',
            ],
        },
    },
]

WSGI_APPLICATION = 'SkinCraft.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'  # Indian Standard Time

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    BASE_DIR / "Static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"

AUTH_USER_MODEL = 'SkinCraft_Main.User'

# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'aakashsavaliya16@gmail.com'  # Replace with your email
EMAIL_HOST_PASSWORD = 'gufs cpwi acur hfdq'  # Replace with your app password
DEFAULT_FROM_EMAIL = 'SkinCraft <aakashsavaliya16@gmail.com>'

# Razorpay Configuration
RAZORPAY_KEY_ID='rzp_test_RksTz1xSamkg4r'
RAZORPAY_KEY_SECRET='049Ey19sBZd9AIIdnWqWJMIx'
# Custom admin dashboard path: change this to your secret admin URL segment (no leading/trailing slashes)
ADMIN_DASHBOARD_PATH = 'secret-admin'
# Ensure @login_required redirects to our custom admin entry instead of default '/accounts/login/'
LOGIN_URL = '/' + ADMIN_DASHBOARD_PATH + '/'
# After login, redirect to admin dashboard by default
LOGIN_REDIRECT_URL = '/admin_dashboard/'