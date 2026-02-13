from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from .forms import *
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from .models import *
from django.db.models import Min, Max, Q, Count, Sum, F, DecimalField, ExpressionWrapper, Avg, Value
from django.db.models.functions import TruncMonth, TruncWeek, TruncDay, TruncHour, Coalesce
from django.core.paginator import Paginator
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.http import HttpResponse, JsonResponse
from .models import Wishlist
import uuid
from django.db import transaction
from django.conf import settings
import random
import razorpay
import hashlib
import hmac
import json
import os
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from django.urls import reverse
from urllib.parse import quote

MAX_PRODUCT_IMAGE_SIZE_BYTES = 5 * 1024 * 1024
MAX_PRODUCT_IMAGE_SIZE_MB = 5
ALLOWED_PRODUCT_IMAGE_CONTENT_TYPES = {
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/webp',
    'image/gif',
}
ALLOWED_PRODUCT_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}


def _validate_inventory_image(file_obj, field_label):
    if not file_obj:
        return

    if file_obj.size > MAX_PRODUCT_IMAGE_SIZE_BYTES:
        raise ValueError(f'{field_label} must be {MAX_PRODUCT_IMAGE_SIZE_MB}MB or smaller.')

    content_type = (getattr(file_obj, 'content_type', '') or '').lower()
    extension = os.path.splitext(getattr(file_obj, 'name', '') or '')[1].lower()
    if content_type in ALLOWED_PRODUCT_IMAGE_CONTENT_TYPES:
        return
    if extension in ALLOWED_PRODUCT_IMAGE_EXTENSIONS:
        return

    raise ValueError(
        f'{field_label} must be a valid image (JPG, JPEG, PNG, WEBP, GIF). PDF files are not allowed.'
    )


def _parse_positive_variant_price(price):
    try:
        parsed_price = Decimal(str(price))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Variant price must be a valid number.')

    if parsed_price <= 0:
        raise ValueError('Variant price must be greater than 0.')

    return parsed_price


# --- REGISTRATION VIEW ---
REGISTRATION_OTP_SESSION_KEY = 'registration_otp_payload'
REGISTRATION_OTP_EXPIRY_SECONDS = 120


def _registration_form_data(post_data):
    return {
        'username': post_data.get('username', '').strip(),
        'first_name': post_data.get('first_name', '').strip(),
        'last_name': post_data.get('last_name', '').strip(),
        'email': post_data.get('email', '').strip(),
        'phone': post_data.get('phone', '').strip(),
        'gender': post_data.get('gender', '').strip(),
        'password1': post_data.get('password1', ''),
        'password2': post_data.get('password2', ''),
    }


def _send_registration_otp_email(email, otp):
    subject = 'Verify your email - SkinCraft'
    body = (
        f'Your registration OTP is {otp}. '
        f'It will expire in {REGISTRATION_OTP_EXPIRY_SECONDS // 60} minutes.'
    )
    EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    ).send(fail_silently=False)


def register_view(request):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST' and request.POST.get('otp_step') == '1':
        payload = request.session.get(REGISTRATION_OTP_SESSION_KEY)

        if not payload:
            messages.error(request, 'OTP session expired. Please register again.')
            form = UserRegistrationForm()
            return render(request, 'register.html', {'form': form})

        form_data = payload.get('form_data', {})
        if request.POST.get('resend_otp') == '1':
            current_expires_at = int(payload.get('expires_at', 0))
            current_now_ts = int(timezone.now().timestamp())
            if current_now_ts < current_expires_at:
                form = UserRegistrationForm(form_data)
                messages.error(request, 'You can resend OTP only after 2 minutes.')
                return render(
                    request,
                    'register.html',
                    {
                        'form': form,
                        'form_data': form_data,
                        'otp_required': True,
                        'otp_expires_at': current_expires_at,
                    },
                )

            otp = f'{random.randint(100000, 999999)}'
            expires_at = timezone.now() + timedelta(seconds=REGISTRATION_OTP_EXPIRY_SECONDS)
            request.session[REGISTRATION_OTP_SESSION_KEY] = {
                'form_data': form_data,
                'otp': otp,
                'expires_at': int(expires_at.timestamp()),
            }

            try:
                _send_registration_otp_email(form_data.get('email', ''), otp)
                messages.success(request, 'A new OTP has been sent. Please verify within 2 minutes.')
            except Exception:
                messages.error(request, 'Unable to resend OTP right now. Please try again.')

            form = UserRegistrationForm(form_data)
            return render(
                request,
                'register.html',
                {
                    'form': form,
                    'form_data': form_data,
                    'otp_required': True,
                    'otp_expires_at': int(expires_at.timestamp()),
                },
            )

        entered_otp = request.POST.get('otp_code', '').strip()
        expires_at = int(payload.get('expires_at', 0))
        now_ts = int(timezone.now().timestamp())

        if now_ts > expires_at:
            request.session.pop(REGISTRATION_OTP_SESSION_KEY, None)
            messages.error(request, 'OTP expired. Please request a new OTP by registering again.')
            form = UserRegistrationForm(form_data)
            return render(
                request,
                'register.html',
                {
                    'form': form,
                    'form_data': form_data,
                },
            )

        if entered_otp != payload.get('otp'):
            messages.error(request, 'Invalid OTP. Please try again.')
            form = UserRegistrationForm(form_data)
            return render(
                request,
                'register.html',
                {
                    'form': form,
                    'form_data': form_data,
                    'otp_required': True,
                    'otp_expires_at': expires_at,
                },
            )

        form = UserRegistrationForm(form_data)
        if form.is_valid():
            form.save()
            request.session.pop(REGISTRATION_OTP_SESSION_KEY, None)
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! Please log in.')
            return redirect('login')

        request.session.pop(REGISTRATION_OTP_SESSION_KEY, None)
        messages.error(request, 'Registration details are no longer valid. Please submit again.')
        return render(request, 'register.html', {'form': form, 'form_data': form_data})

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            form_data = _registration_form_data(request.POST)
            otp = f'{random.randint(100000, 999999)}'
            expires_at = timezone.now() + timedelta(seconds=REGISTRATION_OTP_EXPIRY_SECONDS)

            request.session[REGISTRATION_OTP_SESSION_KEY] = {
                'form_data': form_data,
                'otp': otp,
                'expires_at': int(expires_at.timestamp()),
            }

            try:
                _send_registration_otp_email(form_data['email'], otp)
            except Exception:
                request.session.pop(REGISTRATION_OTP_SESSION_KEY, None)
                if is_ajax:
                    return JsonResponse(
                        {'success': False, 'message': 'Unable to send OTP email right now. Please try again.'},
                        status=500,
                    )
                messages.error(request, 'Unable to send OTP email right now. Please try again.')
                return render(request, 'register.html', {'form': form, 'form_data': form_data})

            if is_ajax:
                return JsonResponse(
                    {
                        'success': True,
                        'message': 'OTP sent to your email. Please verify within 2 minutes.',
                        'expires_at': int(expires_at.timestamp()),
                    }
                )

            messages.success(request, 'OTP sent to your email. Please verify within 2 minutes.')
            return render(
                request,
                'register.html',
                {
                    'form': form,
                    'form_data': form_data,
                    'otp_required': True,
                    'otp_expires_at': int(expires_at.timestamp()),
                },
            )
        if is_ajax:
            error_message = 'Please check your input and try again.'
            if form.errors:
                first_error_list = next(iter(form.errors.values()))
                if first_error_list:
                    error_message = str(first_error_list[0])
            errors = {field: [str(err) for err in error_list] for field, error_list in form.errors.items()}
            return JsonResponse({'success': False, 'message': error_message, 'errors': errors}, status=400)
        return render(
            request,
            'register.html',
            {
                'form': form,
                'form_data': _registration_form_data(request.POST),
            },
        )
    else:
        payload = request.session.get(REGISTRATION_OTP_SESSION_KEY)
        if payload:
            if request.GET.get('otp') == '1':
                expires_at = int(payload.get('expires_at', 0))
                now_ts = int(timezone.now().timestamp())
                if now_ts <= expires_at:
                    form_data = payload.get('form_data', {})
                    form = UserRegistrationForm(form_data)
                    return render(
                        request,
                        'register.html',
                        {
                            'form': form,
                            'form_data': form_data,
                            'otp_required': True,
                            'otp_expires_at': expires_at,
                        },
                    )
            request.session.pop(REGISTRATION_OTP_SESSION_KEY, None)
        form = UserRegistrationForm()
    
    return render(request, 'register.html', {'form': form})

# --- LOGIN VIEW ---
def _get_session_wishlist_items(request):
    return request.session.get('wishlist_items', [])

def _set_session_wishlist_items(request, items):
    request.session['wishlist_items'] = items
    request.session.modified = True

def _merge_session_wishlist_into_user(request, user):
    items = _get_session_wishlist_items(request)
    if not items:
        return
    for entry in items:
        product_id = entry.get('product_id')
        variant_id = entry.get('variant_id')
        if not product_id:
            continue
        product = Product.objects.filter(id=product_id).first()
        if not product:
            continue
        variant = ProductVariant.objects.filter(id=variant_id).first() if variant_id else None
        Wishlist.objects.get_or_create(user=user, product=product, variant=variant)
    _set_session_wishlist_items(request, [])

def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            
            if user is not None:
                login(request, user)
                _merge_session_wishlist_into_user(request, user)
                messages.info(request, f"You are now logged in as {username}.")
                if getattr(user, 'role', None) == User.DELIVERY:
                    return redirect('delivery_dashboard')
                return redirect('homepage') 
            else:
                messages.error(request, "Invalid username or password.")
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = UserLoginForm()

    return render(request, 'login.html', {'form': form})


# --- CUSTOM ADMIN ENTRY VIA URL ---
def custom_admin_entry(request):
    """Allow admin to access a secret URL which shows a small login form
    accepting username or email and password. Successful staff users are
    redirected to the `admin_dashboard` view."""
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        password = request.POST.get('password', '')

        user_obj = None
        if identifier:
            # Try by email first (case-insensitive), then by username
            try:
                user_obj = User.objects.get(email__iexact=identifier)
            except User.DoesNotExist:
                try:
                    user_obj = User.objects.get(username__iexact=identifier)
                except User.DoesNotExist:
                    user_obj = None

        if user_obj is None:
            messages.error(request, 'User not found.')
            return render(request, 'admin_url_login.html')

        user_auth = authenticate(username=user_obj.username, password=password)
        if user_auth is not None and user_auth.is_staff:
            login(request, user_auth)
            # Do not add a success message for admin login — only show messages on errors
            return redirect('admin_dashboard')
        else:
            messages.error(request, 'Invalid credentials or you are not an admin.')

    return render(request, 'admin_url_login.html')

# --- LOGOUT VIEW ---
def logout_view(request):
    logout(request)
    # messages.info(request, "You have successfully logged out.")
    return redirect('homepage')


def _send_order_cancellation_email(order):
    """Send cancellation email to customer if an email address is available."""
    recipient = (order.email or (order.user.email if order.user else '')).strip()
    if not recipient:
        return False

    customer_name = (
        order.full_name
        or (order.user.get_full_name() if order.user else '')
        or 'Customer'
    )
    subject = f"Order Cancelled - #{order.order_number}"
    body = (
        f"Hello {customer_name},\n\n"
        f"Your order #{order.order_number} has been cancelled successfully.\n"
        f"Order Total: Rs. {order.total_amount}\n\n"
        "If this was not expected, please contact our support team.\n\n"
        "Thanks,\n"
        "SkinCraft"
    )
    EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    ).send(fail_silently=True)
    return True


# --- ADMIN DASHBOARD VIEW ---
def admin_dashboard(request):
    """Admin dashboard showing business statistics"""
    if not request.user.is_authenticated:
        return redirect(f"/{settings.ADMIN_DASHBOARD_PATH}/")
    if not request.user.is_staff:
        messages.error(request, 'Access denied. You need admin privileges.')
        return redirect('homepage')
    
    delivered_orders_qs = Order.objects.filter(status='Delivered')

    revenue_range = request.GET.get('revenue_range', 'week')
    revenue_from = request.GET.get('from', '')
    revenue_to = request.GET.get('to', '')

    def _parse_date(value):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return None

    def _make_aware(dt):
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    def _build_revenue_series(range_key, from_value, to_value):
        now = timezone.now()
        range_key = (range_key or 'week').lower()
        labels = []
        values = []

        if range_key == 'day':
            start = (now - timezone.timedelta(hours=23)).replace(minute=0, second=0, microsecond=0)
            end = now
            trunc_fn = TruncHour('created_at')
            label_fmt = '%H:00'
            step = timezone.timedelta(hours=1)
        elif range_key == 'month':
            start = (now - timezone.timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
            trunc_fn = TruncDay('created_at')
            label_fmt = '%b %d'
            step = timezone.timedelta(days=1)
        elif range_key == 'custom':
            from_date = _parse_date(from_value)
            to_date = _parse_date(to_value)
            if not from_date and not to_date:
                from_date = (now - timezone.timedelta(days=6)).date()
                to_date = now.date()
            if not from_date:
                from_date = to_date
            if not to_date:
                to_date = from_date
            start = _make_aware(datetime.combine(from_date, time.min))
            end = _make_aware(datetime.combine(to_date, time.max))
            trunc_fn = TruncDay('created_at')
            label_fmt = '%b %d'
            step = timezone.timedelta(days=1)
        else:
            start = (now - timezone.timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
            trunc_fn = TruncDay('created_at')
            label_fmt = '%b %d'
            step = timezone.timedelta(days=1)

        qs = delivered_orders_qs.filter(created_at__gte=start, created_at__lte=end)
        buckets = (
            qs.annotate(period=trunc_fn)
            .values('period')
            .annotate(total=Sum('total_amount'))
            .order_by('period')
        )
        bucket_map = {
            item['period'].strftime(label_fmt): float(item['total'] or 0)
            for item in buckets
            if item['period']
        }

        cursor = start
        while cursor <= end:
            label = cursor.strftime(label_fmt)
            labels.append(label)
            values.append(bucket_map.get(label, 0))
            cursor = cursor + step

        return labels, values

    if request.GET.get('ajax') == '1':
        labels, values = _build_revenue_series(revenue_range, revenue_from, revenue_to)
        return JsonResponse({'labels': labels, 'values': values})

    # Get statistics
    delivered_total_revenue = delivered_orders_qs.aggregate(total=Sum('total_amount'))['total'] or 0
    net_total_revenue = delivered_total_revenue

    stats = {
        'total_orders': Order.objects.count(),
        'total_payments': Payment.objects.count(),
        'total_returns': Return.objects.count(),
        'total_users': User.objects.count(),
        'total_products': Product.objects.count(),
        'active_users': User.objects.filter(is_active=True).count(),
        'pending_orders': Order.objects.filter(status='Pending').count(),
        'active_delivery_partners': DeliveryProfile.objects.filter(is_active=True).count(),
        'delivered_orders': Order.objects.filter(status='Delivered').count(),
        'total_revenue': net_total_revenue,
    }
    
    # Recent data
    recent_orders_qs = Order.objects.select_related('user', 'assigned_to').prefetch_related('items__product').order_by('-created_at')
    recent_orders = recent_orders_qs[:10]
    all_orders = recent_orders_qs
    recent_payments = Payment.objects.select_related('order').order_by('-created_at')[:10]
    recent_returns = Return.objects.select_related('order', 'user', 'assigned_to').order_by('-created_at')[:10]
    returns = Return.objects.select_related('order', 'user', 'assigned_to').prefetch_related('order__items__product').order_by('-created_at')
    returns_ready_for_refund = returns.filter(status='Completed').filter(Q(refund_record__isnull=True) | ~Q(refund_record__status='Processed'))
    active_pickups = returns.filter(status='Approved', assigned_to__isnull=False)
    refunds = Refund.objects.select_related('order', 'order__user', 'return_request', 'processed_by').order_by('-created_at')
    cancelled_refund_orders = Order.objects.select_related('user').prefetch_related('refunds').filter(
        status='Cancelled',
        payment_status='Paid',
    ).order_by('-created_at')
    cancelled_refund_rows = []
    for cancelled_order in cancelled_refund_orders:
        cancelled_refund = (
            cancelled_order.refunds.filter(return_request__isnull=True)
            .order_by('-created_at')
            .first()
        )
        if cancelled_refund:
            if cancelled_refund.status == 'Processed':
                display_status = 'Paid'
            elif cancelled_refund.status == 'Pending':
                display_status = 'Pending'
            else:
                display_status = 'Failed'
            refund_amount = cancelled_refund.amount
            updated_at = cancelled_refund.processed_at or cancelled_refund.created_at
        else:
            if cancelled_order.payment_status == 'Paid':
                display_status = 'Paid'
            elif cancelled_order.payment_status == 'Pending':
                display_status = 'Pending'
            else:
                display_status = cancelled_order.payment_status
            refund_amount = cancelled_order.total_amount
            updated_at = cancelled_order.created_at

        cancelled_refund_rows.append({
            'order': cancelled_order,
            'refund': cancelled_refund,
            'display_status': display_status,
            'refund_amount': refund_amount,
            'updated_at': updated_at,
        })
    inventory_items = ProductVariant.objects.select_related('product', 'product__category').order_by('-stock')[:10]
    inventory_products_qs = Product.objects.select_related('category', 'subcategory').prefetch_related(
        'variants', 'images', 'tags'
    ).order_by('-created_at')
    inventory_data = []
    for product in inventory_products_qs:
        variants = []
        total_stock = 0
        for variant in product.variants.all():
            total_stock += variant.stock
            variants.append({
                'id': variant.id,
                'unit_value': variant.unit_value,
                'unit_type': variant.unit_type,
                'unit_label': f"{variant.unit_value}{variant.unit_type}",
                'price': float(variant.price),
                'stock': variant.stock,
                'batch_number': variant.batch_number,
                'manufacturing_date': variant.manufacturing_date.isoformat() if variant.manufacturing_date else '',
                'expiry_date': variant.expiry_date.isoformat() if variant.expiry_date else '',
            })

        inventory_data.append({
            'id': product.id,
            'name': product.name,
            'category': product.category.name if product.category else 'Uncategorized',
            'subcategory': product.subcategory.name if product.subcategory else '',
            'category_id': product.category.id if product.category else None,
            'subcategory_id': product.subcategory.id if product.subcategory else None,
            'tags': [tag.name for tag in product.tags.all()],
            'description': product.description or '',
            'is_active': product.is_active,
            'thumbnail': product.thumbnail.url if product.thumbnail else '',
            'gallery': [img.image.url for img in product.images.all()],
            'variants': variants,
            'variant_count': len(variants),
            'total_stock': total_stock,
        })

    inventory_categories = []
    for category in Category.objects.prefetch_related('subcategories').all():
        inventory_categories.append({
            'id': category.id,
            'name': category.name,
            'subcategories': [
                {'id': sub.id, 'name': sub.name}
                for sub in category.subcategories.all()
            ],
        })
    inventory_tags = list(ProductTag.objects.values_list('name', flat=True).order_by('name'))
    # Get ALL active delivery partners for dropdown
    all_delivery_partners = DeliveryProfile.objects.select_related('user', 'user__bank_details').filter(is_active=True).order_by('user__first_name')
    delivery_partners = DeliveryProfile.objects.select_related('user').annotate(
        active_deliveries=Count('user__assigned_orders', filter=Q(user__assigned_orders__status__in=['Pending', 'Shipped', 'On Way'])),
        completed_deliveries=Count('user__assigned_orders', filter=Q(user__assigned_orders__status='Delivered')),
        avg_rating=Coalesce(Avg('reviews__rating'), Value(0.0)),
        review_count=Count('reviews', distinct=True),
    ).order_by('-joined_at')[:10]
    recent_customers = User.objects.filter(role=User.CUSTOMER).annotate(
        total_orders=Count('orders', distinct=True),
        total_spent=Sum('orders__total_amount'),
    ).order_by('-date_joined')[:10]
    delivery_candidate_users = User.objects.filter(role=User.CUSTOMER).exclude(
        delivery_profile__isnull=False
    ).order_by('first_name', 'username')

    stats['total_orders'] = recent_orders_qs.count()
    stats['inventory_count'] = Product.objects.count()
    order_counts = {
        'total': recent_orders_qs.count(),
        'assigned': recent_orders_qs.filter(assigned_to__isnull=False).count(),
        'unassigned': recent_orders_qs.filter(assigned_to__isnull=True).count(),
    }

    now = timezone.now()
    start_week = (now - timezone.timedelta(weeks=5))
    start_week = (start_week - timezone.timedelta(days=start_week.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = (now.replace(day=1) - timezone.timedelta(days=5 * 31)).replace(day=1)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    delivered_orders_qs = delivered_orders_qs
    month_delivered_total = delivered_orders_qs.filter(created_at__gte=month_start).aggregate(total=Sum('total_amount'))['total'] or 0
    year_delivered_total = delivered_orders_qs.filter(created_at__gte=year_start).aggregate(total=Sum('total_amount'))['total'] or 0
    weekly_labels, weekly_values = _build_revenue_series(revenue_range, revenue_from, revenue_to)
    total_transactions = delivered_orders_qs.count()
    avg_order_value = (delivered_total_revenue / total_transactions) if total_transactions else 0

    stats['monthly_revenue'] = month_delivered_total
    stats['yearly_revenue'] = year_delivered_total
    stats['avg_order_value'] = avg_order_value
    stats['total_transactions'] = total_transactions
    delivered_by_month_qs = (
        delivered_orders_qs.filter(created_at__gte=start_month)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('total_amount'))
        .order_by('month')
    )

    orders_by_month = {item['month'].strftime('%B'): float(item['total'] or 0) for item in delivered_by_month_qs}
    monthly_labels = []
    monthly_values = []
    current = start_month
    for _ in range(6):
        label = current.strftime('%B')
        monthly_labels.append(label)
        monthly_values.append(orders_by_month.get(label, 0))
        current = (current + timezone.timedelta(days=32)).replace(day=1)

    line_total = ExpressionWrapper(F('quantity') * F('price_at_purchase'), output_field=DecimalField(max_digits=12, decimal_places=2))
    category_sales = (
        OrderItem.objects.filter(order__status='Delivered', product__category__isnull=False)
        .values('product__category__name')
        .annotate(total=Sum(line_total))
        .order_by('-total')[:4]
    )
    category_labels = [item['product__category__name'] for item in category_sales]
    category_values = [float(item['total'] or 0) for item in category_sales]

    top_products = (
        OrderItem.objects.filter(order__status='Delivered', product__isnull=False)
        .values('product__name')
        .annotate(total_qty=Sum('quantity'))
        .order_by('-total_qty')[:5]
    )
    top_product_labels = [item['product__name'] for item in top_products]
    top_product_values = [int(item['total_qty'] or 0) for item in top_products]

    status_order = [
        'Pending',
        'Delivered',
        'Cancelled'
    ]
    status_counts = Order.objects.values('status').annotate(total=Count('id'))
    status_map = {item['status']: item['total'] for item in status_counts}
    order_status_labels = ['Pending', 'Return', 'Delivered', 'Cancelled']
    order_status_values = [
        status_map.get('Pending', 0),
        Return.objects.count(),
        status_map.get('Delivered', 0),
        status_map.get('Cancelled', 0)
    ]
    
    returns_pending_count = Return.objects.filter(status='Initiated').count()
    salary_payments = SalaryPayment.objects.select_related('delivery_partner').order_by('-year', '-month', '-created_at')[:20]
    salary_pending_count = SalaryPayment.objects.filter(status='Pending').count()

    context = {
        'stats': stats,
        'recent_orders': recent_orders,
        'all_orders': all_orders,
        'recent_payments': recent_payments,
        'recent_returns': recent_returns,
        'returns': returns,
        'returns_ready_for_refund': returns_ready_for_refund,
        'active_pickups': active_pickups,
        'refunds': refunds,
        'cancelled_refund_orders': cancelled_refund_orders,
        'cancelled_refund_rows': cancelled_refund_rows,
        'inventory_items': inventory_items,
        'inventory_data_json': json.dumps(inventory_data),
        'inventory_categories_json': json.dumps(inventory_categories),
        'inventory_tags_json': json.dumps(inventory_tags),
        'recent_customers': recent_customers,
        'delivery_partners': delivery_partners,
        'all_delivery_partners': all_delivery_partners,
        'delivery_candidate_users': delivery_candidate_users,
        'order_counts': order_counts,
        'weekly_revenue_labels': json.dumps(weekly_labels),
        'weekly_revenue_values': json.dumps(weekly_values),
        'revenue_range': revenue_range,
        'revenue_from': revenue_from,
        'revenue_to': revenue_to,
        'monthly_revenue_labels': json.dumps(monthly_labels),
        'monthly_revenue_values': json.dumps(monthly_values),
        'order_status_labels': json.dumps(order_status_labels),
        'order_status_values': json.dumps(order_status_values),
        'category_labels': json.dumps(category_labels),
        'category_values': json.dumps(category_values),
        'top_product_labels': json.dumps(top_product_labels),
        'top_product_values': json.dumps(top_product_values),
        'returns_pending_count': returns_pending_count,
        'salary_payments': salary_payments,
        'salary_pending_count': salary_pending_count,
    }
    
    return render(request, 'admin_dashboard.html', context)


# --- ADMIN: SALARY PAYMENT ACTION ---
@login_required
@require_http_methods(["POST"])
def process_salary_payment(request):
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    def _error_response(message, redirect_to='/admin_dashboard/#salary', status=400):
        if is_ajax:
            return JsonResponse({'success': False, 'message': message}, status=status)
        messages.error(request, message)
        return redirect(redirect_to)

    if not request.user.is_staff:
        return _error_response('Access denied. You need admin privileges.', redirect_to='homepage', status=403)

    partner_id = request.POST.get('delivery_partner_id')
    month_raw = request.POST.get('month', '').strip()
    year_raw = request.POST.get('year', '').strip()
    payment_mode = (request.POST.get('payment_mode') or '').strip()
    remarks = (request.POST.get('remarks') or '').strip()
    allowed_payment_modes = {'Bank Transfer', 'UPI'}

    if not partner_id or not month_raw or not year_raw or not payment_mode:
        return _error_response('Delivery partner, month, year, and payment mode are required.')
    if payment_mode not in allowed_payment_modes:
        return _error_response('Invalid payment mode. Use Bank Transfer or UPI.')

    try:
        month = int(month_raw)
        year = int(year_raw)
        if month < 1 or month > 12:
            raise ValueError
    except ValueError:
        return _error_response('Invalid salary period selected.')

    partner = User.objects.filter(id=partner_id, role=User.DELIVERY).select_related('delivery_profile', 'bank_details').first()
    if not partner or not hasattr(partner, 'delivery_profile'):
        return _error_response('Selected delivery partner is invalid.')
    partner_bank = getattr(partner, 'bank_details', None)
    if payment_mode == 'Bank Transfer' and not partner_bank:
        return _error_response('Bank details are missing for this partner. Ask the partner to add bank details first.')
    if payment_mode == 'UPI':
        if not partner_bank or not partner_bank.upi_id:
            return _error_response('UPI ID is missing for this partner. Ask the partner to update bank details first.')

    try:
        base_salary_raw = request.POST.get('base_salary', '').strip()
        bonus_raw = request.POST.get('bonus', '').strip() or '0'
        deductions_raw = request.POST.get('deductions', '').strip() or '0'

        base_salary = Decimal(base_salary_raw) if base_salary_raw else (partner.delivery_profile.salary or Decimal('0'))
        bonus = Decimal(bonus_raw)
        deductions = Decimal(deductions_raw)
    except (InvalidOperation, TypeError):
        return _error_response('Invalid salary amount values.')

    if base_salary < 0 or bonus < 0 or deductions < 0:
        return _error_response('Salary amounts cannot be negative.')

    net_salary = base_salary + bonus - deductions
    if net_salary < 0:
        return _error_response('Net salary cannot be negative.')

    existing_payment = SalaryPayment.objects.filter(
        delivery_partner=partner,
        month=month,
        year=year,
    ).first()
    if existing_payment:
        return _error_response(
            f'Salary already processed for {existing_payment.get_period_display()}. '
            'You cannot pay or modify the same month again.'
        )

    deliveries_completed = Order.objects.filter(
        assigned_to=partner,
        status='Delivered',
        delivered_at__year=year,
        delivered_at__month=month,
    ).count()
    returns_completed = Return.objects.filter(
        assigned_to=partner,
        status='Completed',
        updated_at__year=year,
        updated_at__month=month,
    ).count()

    transfer_account_holder_name = None
    transfer_account_last4 = None
    transfer_ifsc_code = None
    transfer_bank_name = None
    transfer_upi_id = None
    if payment_mode == 'Bank Transfer' and partner_bank:
        transfer_account_holder_name = partner_bank.account_holder_name
        transfer_account_last4 = (partner_bank.account_number or '')[-4:] or None
        transfer_ifsc_code = partner_bank.ifsc_code
        transfer_bank_name = partner_bank.bank_name
    elif payment_mode == 'UPI' and partner_bank:
        transfer_upi_id = partner_bank.upi_id or None

    payment = SalaryPayment.objects.create(
        delivery_partner=partner,
        month=month,
        year=year,
        base_salary=base_salary,
        bonus=bonus,
        deductions=deductions,
        net_salary=net_salary,
        deliveries_completed=deliveries_completed,
        returns_completed=returns_completed,
        status='Paid',
        payment_mode=payment_mode,
        transaction_reference=None,
        transfer_account_holder_name=transfer_account_holder_name,
        transfer_account_last4=transfer_account_last4,
        transfer_ifsc_code=transfer_ifsc_code,
        transfer_bank_name=transfer_bank_name,
        transfer_upi_id=transfer_upi_id,
        remarks=remarks or None,
        paid_at=timezone.now(),
        paid_by=request.user,
    )

    period_label = payment.get_period_display()
    partner_name = partner.get_full_name() or partner.username
    success_message = f'Salary processed for {partner_name} ({period_label}).'
    if is_ajax:
        return JsonResponse({
            'success': True,
            'message': success_message,
            'salary': {
                'partner_name': partner_name,
                'period': period_label,
                'base_salary': f"{payment.base_salary:.2f}",
                'bonus': f"{payment.bonus:.2f}",
                'deductions': f"{payment.deductions:.2f}",
                'net_salary': f"{payment.net_salary:.2f}",
                'payment_mode': payment.payment_mode or '-',
                'transfer_destination': payment.get_transfer_destination_display(),
                'status': payment.status,
            }
        })
    messages.success(request, success_message)
    return redirect('/admin_dashboard/#salary')


# --- ADMIN: RETURN ACTIONS ---
@login_required
def approve_return(request, return_id):
    if not request.user.is_staff:
        messages.error(request, 'Access denied. You need admin privileges.')
        return redirect('homepage')
    if request.method != 'POST':
        return redirect('/admin_dashboard/#returns')

    return_request = get_object_or_404(Return, id=return_id)
    assigned_to_id = request.POST.get('assigned_to')
    if assigned_to_id:
        assigned_user = get_object_or_404(User, id=assigned_to_id)
        return_request.assigned_to = assigned_user
    return_request.status = 'Approved'
    return_request.save()

    messages.success(request, f'Return #{return_request.id} approved successfully.')
    return redirect('/admin_dashboard/#returns')


@login_required
def reject_return(request, return_id):
    if not request.user.is_staff:
        messages.error(request, 'Access denied. You need admin privileges.')
        return redirect('homepage')
    if request.method != 'POST':
        return redirect('/admin_dashboard/#returns')

    return_request = get_object_or_404(Return, id=return_id)
    return_request.status = 'Rejected'
    return_request.save()

    messages.success(request, f'Return #{return_request.id} rejected.')
    return redirect('/admin_dashboard/#returns')


@login_required
def return_details(request, return_id):
    if not request.user.is_staff:
        messages.error(request, 'Access denied. You need admin privileges.')
        return redirect('homepage')
    # For now, keep details within the dashboard context
    return redirect('/admin_dashboard/#returns')

@login_required
def process_return_refund(request, return_id):
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Access denied.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

    return_request = get_object_or_404(Return, id=return_id)
    try:
        payload = json.loads(request.body or '{}')
        amount_raw = payload.get('amount')
        damage_raw = payload.get('damage_amount', 0)
        amount = Decimal(str(amount_raw))
        damage_amount = Decimal(str(damage_raw))
        if amount < 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid refund amount.'}, status=400)

    Refund.objects.update_or_create(
        return_request=return_request,
        defaults={
            'order': return_request.order,
            'amount': amount,
            'damage_amount': damage_amount,
            'status': 'Processed',
            'processed_by': request.user,
            'processed_at': timezone.now(),
        }
    )

    if return_request.status != 'Completed':
        return_request.status = 'Completed'
        return_request.save()

    # Notify customer that refund is completed
    try:
        recipient = (
            return_request.order.email
            or (return_request.user.email if return_request.user else None)
        )
        if recipient:
            subject = f"Refund Completed - Order #{return_request.order.order_number}"
            customer_name = return_request.user.get_full_name() if return_request.user else 'Customer'
            message = (
                f"Hello {customer_name},\n\n"
                "Your refund has been completed.\n\n"
                f"Order Number: {return_request.order.order_number}\n"
                f"Refund Amount: ₹{amount}\n"
                f"Payment Method: {return_request.order.payment_method or 'COD'}\n\n"
                "Thank you for shopping with SkinCraft."
            )
            EmailMultiAlternatives(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
            ).send(fail_silently=True)
    except Exception:
        pass

    return JsonResponse({'status': 'success', 'message': 'Refund processed.'})


# --- API: GET ORDER DETAILS ---
@login_required
def get_order(request, order_id):
    """API endpoint to get order details as JSON for modal display"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        order = Order.objects.select_related('user', 'assigned_to').prefetch_related('items__product', 'items__variant').get(id=order_id)
        
        # Build timeline based on order status
        timeline = []
        timeline.append({
            'status': 'Order Placed',
            'date': order.created_at.strftime('%b %d, %Y, %I:%M %p'),
            'icon': 'fa-check-circle',
            'color': 'text-green-500'
        })
        
        if order.status in ['Shipped', 'On Way', 'Delivered']:
            timeline.append({
                'status': 'Shipped',
                'date': order.created_at.strftime('%b %d, %Y, %I:%M %p'),
                'icon': 'fa-box',
                'color': 'text-orange-500'
            })
        
        if order.status in ['On Way', 'Delivered']:
            timeline.append({
                'status': 'Out for Delivery',
                'date': order.created_at.strftime('%b %d, %Y, %I:%M %p'),
                'icon': 'fa-truck',
                'color': 'text-blue-500'
            })
        
        if order.status == 'Delivered':
            timeline.append({
                'status': 'Delivered',
                'date': (order.delivered_at or order.created_at).strftime('%b %d, %Y, %I:%M %p'),
                'icon': 'fa-check-circle',
                'color': 'text-green-500'
            })
        else:
            timeline.append({
                'status': 'Delivered',
                'date': 'Pending',
                'icon': 'fa-check-circle',
                'color': 'text-gray-300'
            })
        
        # Build line items
        line_items = []
        for item in order.items.all():
            line_items.append({
                'name': item.product.name if item.product else 'Unknown Product',
                'sku': item.variant.batch_number if item.variant else 'N/A',
                'qty': item.quantity,
                'price': f'₹{item.price_at_purchase:.2f}',
                'size': f'{item.variant.unit_value}{item.variant.unit_type}' if item.variant else 'N/A'
            })
        
        # Calculate totals
        subtotal = float(sum((item.get_subtotal for item in order.items.all()), Decimal('0')))
        shipping = float(order.delivery_fee or 0)
        discount = float(order.discount_amount or 0)
        tax = 0.0
        
        payment_status_display = 'PENDING'
        if order.payment_status == 'Paid':
            payment_status_display = 'PAID'
        elif order.payment_status == 'Failed':
            payment_status_display = 'FAILED'
        
        driver_rating_avg = None
        driver_rating_count = 0
        if order.assigned_to and hasattr(order.assigned_to, 'delivery_profile'):
            rating_summary = DeliveryPartnerReview.objects.filter(
                delivery_partner=order.assigned_to.delivery_profile
            ).aggregate(avg=Avg('rating'), count=Count('id'))
            driver_rating_avg = rating_summary['avg']
            driver_rating_count = rating_summary['count'] or 0

        order_data = {
            'id': order.id,
            'orderNumber': f'#{order.order_number}',
            'items': len(order.items.all()),
            'total': f'₹{order.total_amount:.2f}',
            'amountDue': f'₹{order.total_amount:.2f}',
            'amountPaid': f'₹{order.total_amount if order.payment_status == "Paid" else 0:.2f}',
            'lineItems': line_items,
            'subtotal': f'₹{subtotal:.2f}',
            'shipping': f'₹{shipping:.2f}' if shipping > 0 else 'FREE',
            'discount': f'-₹{discount:.2f}' if discount > 0 else '₹0.00',
            'tax': f'₹{tax:.2f}',
            'customerName': order.full_name or (order.user.get_full_name() if order.user else 'Guest'),
            'customerEmail': order.email or (order.user.email if order.user else ''),
            'customerPhone': order.phone or (order.user.phone if order.user else ''),
            'customerAddress': f'{order.street_address}, {order.city} - {order.zip_code}, {order.state}' if order.street_address else 'N/A',
            'paymentMethod': order.payment_method or 'Cash on Delivery',
            'paymentStatus': payment_status_display,
            'timeline': timeline,
            'status': order.status,
            'assignedDriver': order.assigned_to.get_full_name() if order.assigned_to else 'Not Assigned',
            'assignedDriverId': order.assigned_to.id if order.assigned_to else None,
            'driverRatingAvg': float(driver_rating_avg) if driver_rating_avg is not None else None,
            'driverRatingCount': driver_rating_count,
        }
        
        return JsonResponse(order_data)
    
    except Order.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# --- API: UPDATE ORDER ---
@login_required
def update_order(request, order_id):
    """API endpoint to update order status and assigned driver"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)

    try:
        order = Order.objects.get(id=order_id)
        data = json.loads(request.body)
        previous_status = order.status

        # Update status if provided
        if 'status' in data and data['status']:
            order.status = data['status']

        # Update assigned driver if provided
        if 'assigned_to' in data:
            if data['assigned_to']:
                try:
                    driver = User.objects.get(id=data['assigned_to'], role=User.DELIVERY)
                    order.assigned_to = driver
                except User.DoesNotExist:
                    return JsonResponse({'success': False, 'message': 'Driver not found'}, status=404)
            else:
                order.assigned_to = None

        order.save()

        if previous_status != 'Cancelled' and order.status == 'Cancelled':
            _send_order_cancellation_email(order)

        return JsonResponse({'success': True, 'message': 'Order updated successfully'})

    except Order.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def toggle_delivery_partner(request, partner_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)

    try:
        partner = DeliveryProfile.objects.select_related('user').get(id=partner_id)
        data = json.loads(request.body or '{}')
        is_active = bool(data.get('is_active'))
        partner.is_active = is_active
        partner.save(update_fields=['is_active'])
        partner.user.is_active = is_active
        partner.user.save(update_fields=['is_active'])

        return JsonResponse({'success': True, 'is_active': partner.is_active})
    except DeliveryProfile.DoesNotExist:
        return JsonResponse({'error': 'Delivery partner not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def create_delivery_partner(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    user_id = request.POST.get('user_id')
    license_number = request.POST.get('license_number', '').strip()
    vehicle_type = (request.POST.get('vehicle_type', 'Bike') or 'Bike').strip()
    vehicle_number = request.POST.get('vehicle_number', '').strip()
    salary_raw = request.POST.get('salary', '').strip()
    is_active = request.POST.get('is_active') in ['true', 'on', '1']

    if not user_id or not license_number or not vehicle_number:
        return JsonResponse({'error': 'Missing required fields'}, status=400)

    user = User.objects.filter(id=user_id).first()
    if not user:
        return JsonResponse({'error': 'User not found'}, status=404)
    if user.is_staff:
        return JsonResponse({'error': 'Cannot assign staff users'}, status=400)
    if hasattr(user, 'delivery_profile'):
        return JsonResponse({'error': 'User is already a delivery partner'}, status=400)

    vehicle_choices = {choice[0] for choice in DeliveryProfile.VEHICLE_CHOICES}
    if vehicle_type not in vehicle_choices:
        return JsonResponse({'error': 'Invalid vehicle type'}, status=400)

    try:
        salary = Decimal(salary_raw) if salary_raw else Decimal('0')
        if salary < 0:
            return JsonResponse({'error': 'Invalid salary'}, status=400)
    except InvalidOperation:
        return JsonResponse({'error': 'Invalid salary'}, status=400)

    with transaction.atomic():
        user.role = User.DELIVERY
        user.is_active = is_active
        user.save(update_fields=['role', 'is_active'])

        profile = DeliveryProfile.objects.create(
            user=user,
            license_number=license_number,
            vehicle_type=vehicle_type,
            vehicle_number=vehicle_number,
            salary=salary,
            is_active=is_active
        )

    full_name = user.get_full_name() or user.username
    payload = {
        'id': profile.id,
        'user_id': user.id,
        'name': full_name,
        'email': user.email or '',
        'phone': user.phone or '',
        'vehicle_type': profile.vehicle_type,
        'vehicle_number': profile.vehicle_number,
        'is_active': profile.is_active,
        'avg_rating': 0,
        'review_count': 0,
        'active_deliveries': 0,
        'completed_deliveries': 0,
        'search': f"{full_name} {user.email or ''} {user.phone or ''} {profile.vehicle_type} {profile.vehicle_number}".lower(),
    }

    return JsonResponse({'success': True, 'partner': payload})


@login_required
def toggle_user_active(request, user_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)

    try:
        user_obj = User.objects.get(id=user_id)
        if user_obj.is_staff:
            return JsonResponse({'success': False, 'error': 'Cannot modify staff accounts.'}, status=400)
        if user_obj.id == request.user.id:
            return JsonResponse({'success': False, 'error': 'Cannot modify your own account.'}, status=400)

        data = json.loads(request.body or '{}')
        if 'is_active' in data:
            is_active = bool(data.get('is_active'))
        else:
            is_active = not user_obj.is_active

        user_obj.is_active = is_active
        user_obj.save(update_fields=['is_active'])

        return JsonResponse({'success': True, 'is_active': user_obj.is_active})
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def get_delivery_partner_reviews(request, partner_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    try:
        partner = DeliveryProfile.objects.select_related('user').get(id=partner_id)
    except DeliveryProfile.DoesNotExist:
        return JsonResponse({'error': 'Delivery partner not found'}, status=404)

    reviews_qs = DeliveryPartnerReview.objects.filter(
        delivery_partner=partner
    ).select_related('customer', 'order').order_by('-created_at')

    rating_summary = reviews_qs.aggregate(avg=Avg('rating'), count=Count('id'))
    reviews = []
    for review in reviews_qs[:30]:
        reviews.append({
            'customerName': review.customer.get_full_name() or review.customer.username,
            'orderNumber': review.order.order_number,
            'rating': review.rating,
            'comment': review.comment,
            'date': review.created_at.strftime('%b %d, %Y'),
            'dateIso': review.created_at.strftime('%Y-%m-%d'),
        })

    return JsonResponse({
        'partnerName': partner.user.get_full_name() or partner.user.username,
        'avgRating': float(rating_summary['avg']) if rating_summary['avg'] is not None else None,
        'reviewCount': rating_summary['count'] or 0,
        'reviews': reviews,
    })


@login_required
@require_http_methods(["POST"])
def create_inventory_product(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    try:
        name = request.POST.get('name', '').strip()
        category_id = request.POST.get('category')
        subcategory_id = request.POST.get('subcategory')
        tags_raw = request.POST.get('tags', '')
        description = request.POST.get('description', '').strip()
        is_active = request.POST.get('is_active') == 'true'
        variants_json = request.POST.get('variants')
        thumbnail = request.FILES.get('thumbnail')
        gallery_files = request.FILES.getlist('gallery_images')

        if not name or not category_id or not thumbnail or not variants_json:
            return JsonResponse({'error': 'Missing required fields'}, status=400)

        _validate_inventory_image(thumbnail, 'Thumbnail image')
        for index, image in enumerate(gallery_files, start=1):
            _validate_inventory_image(image, f'Gallery image {index}')

        try:
            variants = json.loads(variants_json)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid variants payload'}, status=400)

        if not isinstance(variants, list) or not variants:
            return JsonResponse({'error': 'At least one variant is required'}, status=400)

        category = get_object_or_404(Category, id=category_id)
        subcategory = None
        if subcategory_id:
            subcategory = SubCategory.objects.filter(id=subcategory_id, category=category).first()

        with transaction.atomic():
            product = Product.objects.create(
                name=name,
                description=description,
                category=category,
                subcategory=subcategory,
                thumbnail=thumbnail,
                is_active=is_active,
            )

            tags = [tag.strip() for tag in tags_raw.split(',') if tag.strip()]
            for tag_name in tags:
                tag, _ = ProductTag.objects.get_or_create(name=tag_name)
                product.tags.add(tag)

            for variant in variants:
                unit_value = int(variant.get('unit_value') or 0)
                unit_type = variant.get('unit_type') or 'ml'
                price = variant.get('price')
                stock = int(variant.get('stock') or 0)
                batch_number = (variant.get('batch_number') or '').strip()
                expiry_date = variant.get('expiry_date')
                manufacturing_date = variant.get('manufacturing_date')

                if not unit_value or not batch_number or price is None or expiry_date is None:
                    raise ValueError('Invalid variant data')

                price_value = _parse_positive_variant_price(price)

                expiry_date_value = date.fromisoformat(expiry_date)
                manufacturing_value = date.fromisoformat(manufacturing_date) if manufacturing_date else None

                ProductVariant.objects.create(
                    product=product,
                    unit_value=unit_value,
                    unit_type=unit_type,
                    price=price_value,
                    stock=stock,
                    batch_number=batch_number,
                    expiry_date=expiry_date_value,
                    manufacturing_date=manufacturing_value,
                )

            for image in gallery_files:
                ProductImage.objects.create(product=product, image=image)

        return JsonResponse({'success': True, 'product': _inventory_product_payload(product)})
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@login_required
@require_http_methods(["POST"])
def update_inventory_product(request, product_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    product = get_object_or_404(Product, id=product_id)

    try:
        name = request.POST.get('name', '').strip()
        category_id = request.POST.get('category')
        subcategory_id = request.POST.get('subcategory')
        tags_raw = request.POST.get('tags', '')
        description = request.POST.get('description', '').strip()
        is_active = request.POST.get('is_active') == 'true'
        variants_json = request.POST.get('variants')
        thumbnail = request.FILES.get('thumbnail')
        gallery_files = request.FILES.getlist('gallery_images')

        if not name or not category_id or not variants_json:
            return JsonResponse({'error': 'Missing required fields'}, status=400)

        if thumbnail:
            _validate_inventory_image(thumbnail, 'Thumbnail image')
        for index, image in enumerate(gallery_files, start=1):
            _validate_inventory_image(image, f'Gallery image {index}')

        try:
            variants = json.loads(variants_json)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid variants payload'}, status=400)

        if not isinstance(variants, list) or not variants:
            return JsonResponse({'error': 'At least one variant is required'}, status=400)

        category = get_object_or_404(Category, id=category_id)
        subcategory = None
        if subcategory_id:
            subcategory = SubCategory.objects.filter(id=subcategory_id, category=category).first()

        with transaction.atomic():
            product.name = name
            product.category = category
            product.subcategory = subcategory
            product.description = description
            product.is_active = is_active
            if thumbnail:
                product.thumbnail = thumbnail
            product.save()

            product.tags.clear()
            tags = [tag.strip() for tag in tags_raw.split(',') if tag.strip()]
            for tag_name in tags:
                tag, _ = ProductTag.objects.get_or_create(name=tag_name)
                product.tags.add(tag)

            existing_ids = set(product.variants.values_list('id', flat=True))
            incoming_ids = set()
            for variant in variants:
                variant_id = variant.get('id')
                unit_value = int(variant.get('unit_value') or 0)
                unit_type = variant.get('unit_type') or 'ml'
                price = variant.get('price')
                stock = int(variant.get('stock') or 0)
                batch_number = (variant.get('batch_number') or '').strip()
                expiry_date = variant.get('expiry_date')
                manufacturing_date = variant.get('manufacturing_date')

                if not unit_value or not batch_number or price is None or expiry_date is None:
                    raise ValueError('Invalid variant data')

                price_value = _parse_positive_variant_price(price)

                expiry_date_value = date.fromisoformat(expiry_date)
                manufacturing_value = date.fromisoformat(manufacturing_date) if manufacturing_date else None

                if variant_id:
                    incoming_ids.add(int(variant_id))
                    ProductVariant.objects.filter(id=variant_id, product=product).update(
                        unit_value=unit_value,
                        unit_type=unit_type,
                        price=price_value,
                        stock=stock,
                        batch_number=batch_number,
                        expiry_date=expiry_date_value,
                        manufacturing_date=manufacturing_value,
                    )
                else:
                    created = ProductVariant.objects.create(
                        product=product,
                        unit_value=unit_value,
                        unit_type=unit_type,
                        price=price_value,
                        stock=stock,
                        batch_number=batch_number,
                        expiry_date=expiry_date_value,
                        manufacturing_date=manufacturing_value,
                    )
                    incoming_ids.add(created.id)

            to_delete = existing_ids - incoming_ids
            if to_delete:
                ProductVariant.objects.filter(id__in=to_delete, product=product).delete()

            for image in gallery_files:
                ProductImage.objects.create(product=product, image=image)

        return JsonResponse({'success': True, 'product': _inventory_product_payload(product)})
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@login_required
@require_http_methods(["POST"])
def delete_inventory_product(request, product_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    product = get_object_or_404(Product, id=product_id)
    product.delete()
    return JsonResponse({'success': True})


def _inventory_product_payload(product):
    variants_data = []
    total_stock = 0
    for variant in product.variants.all():
        total_stock += variant.stock
        variants_data.append({
            'id': variant.id,
            'unit_value': variant.unit_value,
            'unit_type': variant.unit_type,
            'unit_label': f"{variant.unit_value}{variant.unit_type}",
            'price': float(variant.price),
            'stock': variant.stock,
            'batch_number': variant.batch_number,
            'manufacturing_date': variant.manufacturing_date.isoformat() if variant.manufacturing_date else '',
            'expiry_date': variant.expiry_date.isoformat() if variant.expiry_date else '',
        })

    return {
        'id': product.id,
        'name': product.name,
        'category': product.category.name if product.category else 'Uncategorized',
        'subcategory': product.subcategory.name if product.subcategory else '',
        'category_id': product.category.id if product.category else None,
        'subcategory_id': product.subcategory.id if product.subcategory else None,
        'tags': [tag.name for tag in product.tags.all()],
        'description': product.description or '',
        'is_active': product.is_active,
        'thumbnail': product.thumbnail.url if product.thumbnail else '',
        'gallery': [img.image.url for img in product.images.all()],
        'variants': variants_data,
        'variant_count': len(variants_data),
        'total_stock': total_stock,
    }


# --- HOMEPAGE VIEW ---
def homepage(request):
    from django.db.models import Avg
    from django.db.models.functions import Random
    
    # Get 4 random active products that are high rated (>= 4 stars)
    products_with_rating = Product.objects.filter(is_active=True).annotate(avg_rating=Avg('reviews__rating'))
    
    # 1. Try to get 4 random high-rated products
    featured_products = list(products_with_rating.filter(avg_rating__gte=4).order_by(Random()).prefetch_related('variants', 'reviews')[:4])
    
    # 2. If we don't have enough, fill with other random products
    if len(featured_products) < 4:
        needed = 4 - len(featured_products)
        existing_ids = [p.id for p in featured_products]
        others = list(Product.objects.filter(is_active=True).exclude(id__in=existing_ids).order_by(Random()).prefetch_related('variants', 'reviews')[:needed])
        featured_products.extend(others)
    
    # --- WISHLIST CONTEXT RITUAL ---
    wishlisted_product_ids = []
    if request.user.is_authenticated:
        wishlisted_product_ids = Wishlist.objects.filter(
            user=request.user
        ).values_list('product_id', flat=True)
    else:
        session_items = _get_session_wishlist_items(request)
        wishlisted_product_ids = [item.get('product_id') for item in session_items if item.get('product_id')]
    
    # Get herbal oil product for the FAQ section
    herbal_oil_product = Product.objects.filter(
        is_active=True, 
        name__icontains='herbal oil'
    ).first()
    
    context = {
        'featured_products': featured_products,
        'wishlisted_product_ids': wishlisted_product_ids,
        'herbal_oil_product': herbal_oil_product,
    }
    return render(request, 'homepage.html', context)

def ayurveda_view(request):
    categories = Category.objects.all()
    
    context = {
        'categories': categories,
    }
    return render(request, 'ayurveda.html', context)

def faq_view(request):
    return render(request, 'faq.html')

def about_view(request):
    happy_customer_count = User.objects.filter(role=User.CUSTOMER, is_active=True).count()
    product_count = Product.objects.count()
    context = {
        'happy_customer_count': happy_customer_count,
        'product_count': product_count,
    }
    return render(request, 'about.html', context)

def privacy_policy(request):
    return render(request, 'privacy_policy.html')

def shipping_policy(request):
    return render(request, 'shipping_policy.html')

def terms_conditions(request):
    return render(request, 'terms_conditions.html')


@login_required
def delivery_dashboard(request):
    if getattr(request.user, 'role', None) != User.DELIVERY:
        messages.error(request, 'Access denied.')
        return redirect('homepage')

    assigned_orders = Order.objects.filter(assigned_to=request.user)
    active_orders = assigned_orders.filter(status__in=['Pending', 'Shipped', 'On Way']).order_by('-created_at')
    delivered_orders = assigned_orders.filter(status='Delivered').order_by('-created_at')
    
    # Get assigned return pickups (only approved ones)
    assigned_returns = Return.objects.filter(assigned_to=request.user, status='Approved').select_related('order', 'user').order_by('-created_at')
    
    # Get completed return pickups for history
    completed_returns = Return.objects.filter(assigned_to=request.user, status='Completed').select_related('order', 'user').order_by('-picked_up_at')

    profile = DeliveryProfile.objects.filter(user=request.user).first()
    deliveries = Delivery.objects.filter(delivery_personnel=profile) if profile else Delivery.objects.none()
    delivery_reviews = DeliveryPartnerReview.objects.filter(delivery_partner=profile).select_related('customer', 'order') if profile else DeliveryPartnerReview.objects.none()
    avg_delivery_rating = delivery_reviews.aggregate(avg=Avg('rating'))['avg'] or 0
    rating_breakdown = {
        star: delivery_reviews.filter(rating=star).count()
        for star in range(1, 6)
    }

    helpdesk_tickets = DeliveryHelpDeskTicket.objects.filter(user=request.user).order_by('-created_at')

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    delivered_count = deliveries.filter(status='Delivered', delivered_at__gte=month_start).count()
    pending_count = deliveries.filter(status__in=['Pending', 'Picked Up'], assigned_at__gte=month_start).count()

    monthly_salary = profile.salary if profile else Decimal('0')
    salary_payments = SalaryPayment.objects.filter(delivery_partner=request.user).order_by('-year', '-month', '-created_at')
    paid_salary_qs = salary_payments.filter(status='Paid')
    current_salary_payment = paid_salary_qs.filter(month=now.month, year=now.year).first()
    salary_paid = current_salary_payment.net_salary if current_salary_payment else Decimal('0')
    total_salary_received = paid_salary_qs.aggregate(total=Sum('net_salary'))['total'] or Decimal('0')
    last_salary_payment = paid_salary_qs.first()

    bank_details = BankDetails.objects.filter(user=request.user).first()

    context = {
        'stats': {
            'monthly_salary': monthly_salary,
            'salary_paid': salary_paid,
            'total_salary_received': total_salary_received,
            'pending_count': active_orders.count(),
            'total_delivered': delivered_orders.count(),
            'pending_returns': assigned_returns.count(),
            'return_pickups': assigned_returns.count(),
        },
        'tasks': active_orders,
        'pickup_tasks': assigned_returns,
        'history': delivered_orders,
        'completed_pickups': completed_returns,
        'profile': profile,
        'helpdesk_reasons': DeliveryHelpDeskTicket.REASON_CHOICES,
        'helpdesk_tickets': helpdesk_tickets,
        'delivery_reviews': delivery_reviews,
        'avg_delivery_rating': avg_delivery_rating,
        'rating_breakdown': rating_breakdown,
        'salary_payments': salary_payments[:12],
        'current_salary_payment': current_salary_payment,
        'last_salary_payment': last_salary_payment,
        'bank_details': bank_details,
    }
    return render(request, 'delivery_dashboard.html', context)


@login_required
def submit_helpdesk_ticket(request):
    if getattr(request.user, 'role', None) != User.DELIVERY:
        messages.error(request, 'Access denied.')
        return redirect('homepage')

    if request.method != 'POST':
        return redirect('delivery_dashboard')

    reason = request.POST.get('reason')
    remarks = request.POST.get('remarks', '').strip()

    valid_reasons = [choice[0] for choice in DeliveryHelpDeskTicket.REASON_CHOICES]
    if reason not in valid_reasons:
        messages.error(request, 'Please select a valid reason.')
        return redirect('delivery_dashboard')

    DeliveryHelpDeskTicket.objects.create(
        user=request.user,
        reason=reason,
        remarks=remarks
    )

    messages.success(request, 'Your help desk request has been submitted.')
    return redirect('delivery_dashboard')


@login_required
@require_http_methods(["POST"])
def update_delivery_profile(request):
    if getattr(request.user, 'role', None) != User.DELIVERY:
        messages.error(request, 'Access denied.')
        return redirect('homepage')

    profile = DeliveryProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, 'Delivery profile not found.')
        return redirect('delivery_dashboard')

    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    email = request.POST.get('email', '').strip()
    phone = request.POST.get('phone', '').strip()
    license_number = request.POST.get('license_number', '').strip()
    vehicle_type = request.POST.get('vehicle_type', '').strip()
    vehicle_number = request.POST.get('vehicle_number', '').strip()
    street_address = request.POST.get('street_address', '').strip()
    city = request.POST.get('city', '').strip()
    state = request.POST.get('state', '').strip()
    zip_code = request.POST.get('zip_code', '').strip()

    if not license_number or not vehicle_type or not vehicle_number:
        messages.error(request, 'Please fill all required profile fields.')
        return redirect('/delivery/dashboard/?tab=profile')

    vehicle_choices = {choice[0] for choice in DeliveryProfile.VEHICLE_CHOICES}
    if vehicle_type not in vehicle_choices:
        messages.error(request, 'Invalid vehicle type.')
        return redirect('/delivery/dashboard/?tab=profile')

    request.user.first_name = first_name
    request.user.last_name = last_name
    request.user.email = email
    request.user.phone = phone
    request.user.save(update_fields=['first_name', 'last_name', 'email', 'phone'])

    profile.license_number = license_number
    profile.vehicle_type = vehicle_type
    profile.vehicle_number = vehicle_number
    profile.street_address = street_address
    profile.city = city
    profile.state = state
    profile.zip_code = zip_code
    profile.save(update_fields=[
        'license_number', 'vehicle_type', 'vehicle_number',
        'street_address', 'city', 'state', 'zip_code'
    ])

    messages.success(request, 'Profile updated successfully.')
    return redirect('/delivery/dashboard/?tab=profile')


@login_required
@require_http_methods(["POST"])
def update_delivery_bank_details(request):
    if getattr(request.user, 'role', None) != User.DELIVERY:
        messages.error(request, 'Access denied.')
        return redirect('homepage')

    account_holder_name = (request.POST.get('account_holder_name') or '').strip()
    account_number = (request.POST.get('account_number') or '').strip()
    ifsc_code = (request.POST.get('ifsc_code') or '').strip().upper()
    bank_name = (request.POST.get('bank_name') or '').strip()
    upi_id = (request.POST.get('upi_id') or '').strip()

    if not account_holder_name or not account_number or not ifsc_code or not bank_name:
        messages.error(request, 'Account holder, account number, IFSC code, and bank name are required.')
        return redirect('/delivery/dashboard/?tab=bank')

    bank_details, _ = BankDetails.objects.get_or_create(user=request.user)
    bank_details.account_holder_name = account_holder_name
    bank_details.account_number = account_number
    bank_details.ifsc_code = ifsc_code
    bank_details.bank_name = bank_name
    bank_details.upi_id = upi_id or None
    bank_details.save(update_fields=[
        'account_holder_name',
        'account_number',
        'ifsc_code',
        'bank_name',
        'upi_id',
        'updated_at',
    ])

    messages.success(request, 'Bank details saved successfully. Admin can now use these details for salary transfer.')
    return redirect('/delivery/dashboard/?tab=bank')


@login_required
def update_delivery_status(request, order_id):
    if getattr(request.user, 'role', None) != User.DELIVERY:
        return JsonResponse({'status': 'error', 'message': 'Access denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

    order = get_object_or_404(Order, id=order_id, assigned_to=request.user)
    new_status = request.POST.get('new_status')
    allowed = {'Pending': 'Shipped', 'Shipped': 'On Way', 'On Way': 'Delivered'}

    if order.status not in allowed or allowed[order.status] != new_status:
        return JsonResponse({'status': 'error', 'message': 'Invalid status change.'}, status=400)

    order.status = new_status
    if new_status == 'Delivered':
        order.delivered_at = timezone.now()
        if order.payment_method == 'COD' and order.payment_status != 'Paid':
            order.payment_status = 'Paid'
    order.save()
    return JsonResponse({'status': 'success'})


@login_required
def send_delivery_otp(request, order_id):
    if getattr(request.user, 'role', None) != User.DELIVERY:
        return JsonResponse({'status': 'error', 'message': 'Access denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

    order = get_object_or_404(Order, id=order_id, assigned_to=request.user)
    otp = f"{random.randint(100000, 999999)}"
    order.delivery_otp = otp
    order.otp_created_at = timezone.now()
    order.save()

    if order.email:
        subject = f"Your Delivery OTP for Order {order.order_number}"
        body = f"Your delivery OTP is {otp}. Please share it with the delivery partner to complete delivery."
        EmailMultiAlternatives(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[order.email]).send()

    return JsonResponse({'status': 'success'})


@login_required
def complete_delivery(request, order_id):
    if getattr(request.user, 'role', None) != User.DELIVERY:
        return JsonResponse({'status': 'error', 'message': 'Access denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

    order = get_object_or_404(Order, id=order_id, assigned_to=request.user)
    otp = request.POST.get('otp')

    if not order.delivery_otp or otp != order.delivery_otp:
        return JsonResponse({'status': 'error', 'message': 'Invalid OTP.'}, status=400)

    order.status = 'Delivered'
    order.delivered_at = timezone.now()
    order.delivery_otp = None
    order.otp_created_at = None
    if order.payment_method == 'COD' and order.payment_status != 'Paid':
        order.payment_status = 'Paid'
    order.save()

    return JsonResponse({'status': 'success'})


@login_required
def profile_view(request):
    active_tab = request.GET.get('tab', 'edit')
    edit_address_id = request.GET.get('edit', None)
    
    # Forms initialization
    user_form = UserUpdateForm(instance=request.user)
    address_form = AddressForm()
    password_form = PasswordChangeForm(request.user)
    existing_bank_details = BankDetails.objects.filter(user=request.user).first()
    bank_form = BankDetailsForm(instance=existing_bank_details)

    if request.method == 'POST':
        # 1. Update Profile Ritual
        if 'update_profile' in request.POST:
            user_form = UserUpdateForm(request.POST, request.FILES, instance=request.user)
            if user_form.is_valid():
                user_form.save()
                messages.success(request, 'Your profile sanctuary has been updated!')
                return redirect('/profile/?tab=edit')
            active_tab = 'edit'

        # 1.1 Remove Profile Image
        elif 'remove_profile_image' in request.POST:
            current_image = getattr(request.user, 'profile_image', None)
            if current_image and getattr(current_image, 'name', '') and current_image.name != 'default.jpg':
                current_image.delete(save=False)
            request.user.profile_image = 'default.jpg'
            request.user.save(update_fields=['profile_image'])
            messages.success(request, 'Profile picture removed successfully!')
            return redirect('/profile/?tab=edit')

        # 2. Add/Update Address
        elif 'add_address' in request.POST:
            address_id = request.POST.get('address_id', None)
            if address_id:
                # Update existing address
                try:
                    addr = Address.objects.get(id=address_id, user=request.user)
                    address_form = AddressForm(request.POST, instance=addr)
                except Address.DoesNotExist:
                    messages.error(request, 'Address not found!')
                    return redirect('/profile/?tab=address')
            else:
                # Create new address
                address_form = AddressForm(request.POST)
            
            if address_form.is_valid():
                addr = address_form.save(commit=False)
                addr.user = request.user
                
                # Exclusive Default Logic
                if addr.is_default:
                    Address.objects.filter(user=request.user).update(is_default=False)
                
                addr.save()
                msg = 'Delivery address updated successfully!' if address_id else 'New delivery sanctuary added successfully!'
                messages.success(request, msg)
                return redirect('/profile/?tab=address')
            else:
                # If invalid, ensure we stay on the address tab to see errors
                active_tab = 'address'
        
        # 3. Delete Address
        elif 'delete_address' in request.POST:
            address_id = request.POST.get('delete_address')
            try:
                addr = Address.objects.get(id=address_id, user=request.user)
                addr.delete()
                messages.success(request, 'Address removed successfully!')
            except Address.DoesNotExist:
                messages.error(request, 'Address not found!')
            return redirect('/profile/?tab=address')

        # 4. Change Security Ritual
        elif 'change_password' in request.POST:
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your security ritual is complete. Password changed!')
                return redirect('/profile/?tab=security')
            active_tab = 'security'
        
        # 5. Save Bank Details
        elif 'save_bank_details' in request.POST:
            bank_form = BankDetailsForm(request.POST, instance=existing_bank_details)
            if bank_form.is_valid():
                details = bank_form.save(commit=False)
                details.user = request.user
                details.save()
                messages.success(request, 'Bank details saved successfully!')
                return redirect('/profile/?tab=bank')
            active_tab = 'bank'

    # If editing an address, populate the form
    if edit_address_id:
        try:
            edit_address = Address.objects.get(id=edit_address_id, user=request.user)
            address_form = AddressForm(instance=edit_address)
            active_tab = 'address'
        except Address.DoesNotExist:
            messages.error(request, 'Address not found!')

    # Fetch ritual history and saved locations
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    addresses = Address.objects.filter(user=request.user)
    delivery_review_map = {
        review.order_id: review
        for review in DeliveryPartnerReview.objects.filter(order__user=request.user).select_related('order')
    }
    for order in orders:
        order.delivery_partner_review = delivery_review_map.get(order.id)
        try:
            product_total = sum((item.get_subtotal for item in order.items.all()), Decimal('0'))
        except Exception:
            product_total = Decimal('0')
        order.product_total = product_total
        cancelled_refund = (
            order.refunds.filter(return_request__isnull=True)
            .order_by('-created_at')
            .first()
        )
        order.cancelled_refund_record = cancelled_refund
        if cancelled_refund:
            if cancelled_refund.status == 'Processed':
                order.cancelled_refund_status_display = 'Paid'
            elif cancelled_refund.status == 'Pending':
                order.cancelled_refund_status_display = 'Pending'
            else:
                order.cancelled_refund_status_display = 'Failed'
            order.refund_amount = cancelled_refund.amount
        elif getattr(order, 'payment_status', '') == 'Paid':
            order.cancelled_refund_status_display = 'Paid'
            order.refund_amount = order.total_amount
        else:
            order.cancelled_refund_status_display = getattr(order, 'payment_status', 'Pending')
            order.refund_amount = Decimal('0')
    
    context = {
        'orders': orders,
        'addresses': addresses,
        'user_form': user_form,
        'address_form': address_form,
        'password_form': password_form,
        'bank_form': bank_form,
        'active_tab': active_tab,
        'edit_address_id': edit_address_id,
        # Passing model choices for dynamic icon handling
        'address_choices': Address.ADDRESS_TYPES,
        'delivery_review_map': delivery_review_map,
    }
    return render(request, 'profile.html', context)


@login_required
@require_http_methods(["POST"])
def cancel_order(request, order_id):
    try:
        order = Order.objects.select_related('user').prefetch_related('items__variant').get(id=order_id, user=request.user)
    except Order.DoesNotExist:
        messages.error(request, 'Order not found.')
        return redirect('/profile/?tab=orders')

    if order.status not in ['Pending', 'Shipped']:
        messages.error(request, 'This order can no longer be cancelled.')
        return redirect('/profile/?tab=orders')

    with transaction.atomic():
        # Restock variants
        for item in order.items.all():
            if item.variant:
                ProductVariant.objects.filter(id=item.variant.id).update(stock=F('stock') + item.quantity)

        order.status = 'Cancelled'
        order.assigned_to = None
        order.save(update_fields=['status', 'assigned_to'])
        transaction.on_commit(lambda: _send_order_cancellation_email(order))

    messages.success(request, f'Order {order.order_number} has been cancelled.')
    return redirect('/profile/?tab=orders')


@login_required
def submit_delivery_partner_review(request):
    if request.method != 'POST':
        return redirect('/profile/?tab=orders')

    order_id = request.POST.get('order_id')
    rating = request.POST.get('rating')
    comment = request.POST.get('comment', '').strip()

    if not order_id or not rating:
        messages.error(request, 'Please provide a rating before submitting.')
        return redirect('/profile/?tab=orders')

    try:
        order = Order.objects.get(id=order_id, user=request.user, status='Delivered')
    except Order.DoesNotExist:
        messages.error(request, 'Order not found or not eligible for delivery review.')
        return redirect('/profile/?tab=orders')

    if not order.assigned_to or not hasattr(order.assigned_to, 'delivery_profile'):
        messages.error(request, 'No delivery partner found for this order.')
        return redirect('/profile/?tab=orders')

    if DeliveryPartnerReview.objects.filter(order=order).exists():
        messages.warning(request, 'You have already reviewed this delivery partner.')
        return redirect('/profile/?tab=orders')

    DeliveryPartnerReview.objects.create(
        order=order,
        delivery_partner=order.assigned_to.delivery_profile,
        customer=request.user,
        rating=int(rating),
        comment=comment,
    )

    messages.success(request, 'Thanks for rating your delivery partner!')
    return redirect('/profile/?tab=orders')

# --- CONTACT FORM VIEW ---
def contact(request):
    if request.method == 'POST':
        # Create a form instance with the submitted data
        form = ContactForm(request.POST)
        
        if form.is_valid():
            form.save() # Saves to the database
            messages.success(request, "Thank you! Your message has been sent successfully.")
            return redirect('contact') # Reloads the page clear
        else:
            # If there are errors (like invalid email), show them
            messages.error(request, "There was an error sending your message. Please check the form.")
    else:
        form = ContactForm()

    return render(request, 'contact.html', {'form': form})


@login_required
@require_http_methods(["POST"])
def add_address_from_checkout(request):
    data = request.POST.copy()
    address_type = (data.get('address_type') or '').strip()
    if address_type.lower() == 'office':
        data['address_type'] = 'Work'

    form = AddressForm(data)
    if form.is_valid():
        address = form.save(commit=False)
        address.user = request.user
        if address.is_default:
            Address.objects.filter(user=request.user).update(is_default=False)
        address.save()
        messages.success(request, 'New address added successfully.')
    else:
        messages.error(request, 'Unable to add address. Please check the details.')

    return redirect('checkout')

def product_list(request):
    # 1. Base Query
    products = Product.objects.filter(is_active=True).prefetch_related('reviews')
    
    # 2. Categories with Counts (Optimized)
    categories = Category.objects.annotate(
        product_count=Count('product', filter=Q(product__is_active=True))
    ).prefetch_related('subcategories').all()

    # 3. Subcategories for Tags
    all_subcategories = SubCategory.objects.filter(product__is_active=True).distinct()

    # --- FILTERING ---
    query = request.GET.get('q')
    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query))

    category_id = request.GET.get('category')
    if category_id and category_id != 'all':
        products = products.filter(category_id=category_id)

    subcategory_id = request.GET.get('subcategory')
    if subcategory_id:
        products = products.filter(subcategory_id=subcategory_id)

    max_price = request.GET.get('max_price')
    if max_price:
        # distinct() is used here to avoid duplicates due to multiple variants
        products = products.filter(variants__price__lte=max_price).distinct()

    # --- SORTING ---
    sort_by = request.GET.get('sort', 'newest')
    if sort_by == 'price_low':
        products = products.annotate(min_price=Min('variants__price')).order_by('min_price')
    elif sort_by == 'price_high':
        products = products.annotate(min_price=Min('variants__price')).order_by('-min_price')
    else:
        products = products.order_by('-created_at')

    # --- WISHLIST CONTEXT RITUAL ---
    # This is crucial for keeping icons red after filtering
    wishlisted_product_ids = []
    if request.user.is_authenticated:
        wishlisted_product_ids = Wishlist.objects.filter(
            user=request.user
        ).values_list('product_id', flat=True)
    else:
        session_items = _get_session_wishlist_items(request)
        wishlisted_product_ids = [item.get('product_id') for item in session_items if item.get('product_id')]

    # --- PAGINATION ---
    paginator = Paginator(products, 6) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'products': page_obj,
        'categories': categories,
        'all_subcategories': all_subcategories,
        'total_products': products.count(),
        'current_sort': sort_by,
        'wishlisted_product_ids': wishlisted_product_ids, # Added back to context
    }

    # --- AJAX HANDLER ---
    # Case-insensitive header check to avoid double-rendering
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
              request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if is_ajax:
        # Return ONLY the grid snippet, not the full page structure
        html = render_to_string('product_grid.html', context, request=request)
        return HttpResponse(html)

    return render(request, 'product.html', context)


def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.prefetch_related('images', 'variants', 'tags'), 
        pk=pk
    )
    # Logic: Same category, exclude current product, limit to 4 items
    related_products = Product.objects.filter(
        category=product.category, 
        is_active=True
    ).exclude(pk=pk)[:4]
    
    # Get reviews for this product with images
    reviews = Review.objects.filter(product=product).select_related('user').prefetch_related('images').order_by('-created_at')
    
    # Check if user has purchased this product and can review
    can_review = False
    user_review = None
    if request.user.is_authenticated:
        # Check if user has a delivered order with this product
        user_orders = OrderItem.objects.filter(
            order__user=request.user,
            order__status='Delivered',
            product=product
        ).exists()
        
        can_review = user_orders
        
        # Check if user already reviewed this product
        user_review = Review.objects.filter(
            user=request.user,
            product=product
        ).first()

    context = {
        'product': product,
        'related_products': related_products,
        'reviews': reviews,
        'can_review': can_review,
        'user_review': user_review,
    } 
    return render(request, 'product_detail.html', context)


@login_required
def wishlist_view(request):
    if request.user.is_authenticated:
        items = Wishlist.objects.filter(user=request.user).select_related('product', 'variant').order_by('-added_at')
        wishlist_count = items.count()
    else:
        session_items = _get_session_wishlist_items(request)
        items = []
        for entry in session_items:
            product_id = entry.get('product_id')
            if not product_id:
                continue
            product = Product.objects.filter(id=product_id).first()
            if not product:
                continue
            variant_id = entry.get('variant_id')
            variant = ProductVariant.objects.filter(id=variant_id).first() if variant_id else None
            items.append({'product': product, 'variant': variant})
        wishlist_count = len(items)
    
    context = {
        'wishlist_items': items,
        'wishlist_count': wishlist_count,
    }
    return render(request, 'wishlist.html', context)

def toggle_wishlist(request, product_id):
    """
    Handles the AJAX ritual for adding/removing items.
    Ensures that if variant_id is missing, it removes the entire product entry.
    """
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        variant_id = request.POST.get('variant_id')

        if not request.user.is_authenticated:
            items = _get_session_wishlist_items(request)
            entry = {
                'product_id': product.id,
                'variant_id': variant_id if variant_id else None
            }
            if entry in items:
                items = [i for i in items if i != entry]
                _set_session_wishlist_items(request, items)
                return JsonResponse({'status': 'removed', 'wishlist_count': len(items)})
            items.append(entry)
            _set_session_wishlist_items(request, items)
            return JsonResponse({'status': 'added', 'wishlist_count': len(items)})

        if variant_id:
            variant = ProductVariant.objects.filter(id=variant_id).first()
            wish_items = Wishlist.objects.filter(user=request.user, product=product, variant=variant)
        else:
            wish_items = Wishlist.objects.filter(user=request.user, product=product)

        if wish_items.exists():
            wish_items.delete()
            # Recalculate count
            if request.user.is_authenticated:
                count = Wishlist.objects.filter(user=request.user).count()
            else:
                count = len(_get_session_wishlist_items(request))
            return JsonResponse({'status': 'removed', 'wishlist_count': count})
        else:
            variant = ProductVariant.objects.filter(id=variant_id).first() if variant_id else None
            Wishlist.objects.create(user=request.user, product=product, variant=variant)
            # Recalculate count
            if request.user.is_authenticated:
                count = Wishlist.objects.filter(user=request.user).count()
            else:
                count = len(_get_session_wishlist_items(request))
            return JsonResponse({'status': 'added', 'wishlist_count': count})
            
    return JsonResponse({'status': 'error'}, status=400)

def get_or_create_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
    else:
        if not request.session.session_key:
            request.session.create()
        cart, _ = Cart.objects.get_or_create(session_id=request.session.session_key)
    return cart

def add_to_cart(request, product_id):
    if not request.user.is_authenticated:
        login_url = reverse('login')
        redirect_url = f"{login_url}?next={quote(request.get_full_path())}"
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'auth_required', 'redirect_url': redirect_url}, status=401)
        return redirect(redirect_url)

    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        variant_id = request.POST.get('variant_id')
        
        # Validation: Ensure a variant exists
        variant = get_object_or_404(ProductVariant, id=variant_id)

        # Get or create cart
        cart, created = Cart.objects.get_or_create(user=request.user)
        
        # Add item if not already in cart
        item, created = CartItem.objects.get_or_create(
            cart=cart, product=product, variant=variant
        )
        
        # Check stock before adding
        requested_qty = item.quantity + 1 if not created else 1
        if requested_qty > variant.stock:
            messages.error(request, f'Only {variant.stock} units of {product.name} available. Cannot add more.')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': f'Only {variant.stock} units available.'}, status=400)
            return redirect('cart_view')
        
        if not created:
            # Increase quantity for repeated adds
            item.quantity += 1
            item.save()

        # AJAX Response
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            total_items = cart.items.count()
            return JsonResponse({
                'status': 'success',
                'cart_count': total_items
            })
            
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

def cart_view(request):
    # Clear stale "Access denied" flashes that shouldn't show on cart
    storage = messages.get_messages(request)
    preserved = []
    for msg in storage:
        if 'Access denied' not in str(msg):
            preserved.append(msg)
    storage.used = True
    for msg in preserved:
        messages.add_message(request, msg.level, msg.message, extra_tags=msg.tags)

    cart = get_or_create_cart(request)
    return render(request, 'cart.html', {'cart': cart})

def update_cart_quantity(request, item_id, action):
    cart = get_or_create_cart(request)
    item = get_object_or_404(CartItem, id=item_id, cart=cart)
    item_removed = False
    error_message = None

    if action == 'plus':
        # Check stock availability before increasing quantity
        if item.quantity + 1 > item.variant.stock:
            error_message = f'Only {item.variant.stock} units of {item.product.name} available.'
            messages.error(request, error_message)
        else:
            item.quantity += 1
            item.save()
    elif action == 'minus':
        if item.quantity > 1:
            item.quantity -= 1
            item.save()
        else:
            # Delete item if quantity is 1 and user clicks minus
            item.delete()
            item_removed = True

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        cart_total = str(cart.total_price)
        cart_count = cart.items.count()
        payload = {
            'status': 'success' if not error_message else 'error',
            'message': error_message or '',
            'item_id': item_id,
            'item_removed': item_removed,
            'cart_total': cart_total,
            'cart_count': cart_count,
            'cart_empty': cart_count == 0,
        }
        if not item_removed and item.pk:
            payload.update({
                'quantity': item.quantity,
                'item_subtotal': str(item.subtotal),
            })
        return JsonResponse(payload, status=400 if error_message else 200)

    return redirect('cart_view')

def delete_cart_item(request, item_id):
    cart = get_or_create_cart(request)
    item = get_object_or_404(CartItem, id=item_id, cart=cart)
    item.delete()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        cart_total = str(cart.total_price)
        cart_count = cart.items.count()
        return JsonResponse({
            'status': 'success',
            'item_id': item_id,
            'item_removed': True,
            'cart_total': cart_total,
            'cart_count': cart_count,
            'cart_empty': cart_count == 0,
        })
    return redirect('cart_view')

@login_required
def checkout_view(request):
    # Fetch saved data for the sanctuary ritual
    initial_contact = {
        'full_name': f"{request.user.first_name} {request.user.last_name}",
        'email': request.user.email,
        'phone': request.user.phone or ""
    }
    addresses = Address.objects.filter(user=request.user)

    # CHECK FOR BUY NOW MODE
    buy_now_variant_id = request.GET.get('variant_id')
    buy_now_mode = False
    checkout_items = []
    
    cart = None
    if buy_now_variant_id:
        try:
            variant = ProductVariant.objects.get(id=buy_now_variant_id)
            if variant.stock > 0:
                buy_now_mode = True
                # Create a pseudo-item structure for the template
                from collections import namedtuple
                PseudoItem = namedtuple('PseudoItem', ['product', 'variant', 'quantity', 'subtotal'])
                
                item = PseudoItem(
                    product=variant.product,
                    variant=variant,
                    quantity=1,
                    subtotal=variant.price
                )
                checkout_items = [item]
                subtotal = variant.price
            else:
                messages.error(request, 'Selected item is out of stock.')
                return redirect('cart_view')
        except ProductVariant.DoesNotExist:
            messages.error(request, 'Invalid item selected.')
            return redirect('cart_view')
    else:
        # STANDARD CART CHECKOUT
        cart, _ = Cart.objects.get_or_create(user=request.user)
        if not cart.items.exists():
            return redirect('cart_view')
        
        # Validate stock availability for all items
        for item in cart.items.all():
            if item.quantity > item.variant.stock:
                messages.error(request, f'{item.product.name}: Only {item.variant.stock} units available. Please adjust quantity.')
                return redirect('cart_view')
        
        checkout_items = cart.items.all()
        subtotal = Decimal(str(cart.total_price))

    # Delivery fee rules
    delivery_free_threshold = Decimal('999')
    delivery_fee_fixed = Decimal('49')
    delivery_fee = Decimal('0') if subtotal >= delivery_free_threshold else delivery_fee_fixed

    # Coupon handling
    applied_code = request.session.get('coupon_code')
    discount_amount = Decimal('0')
    applied_coupon = None
    if applied_code:
        today = timezone.now().date()
        applied_coupon = Coupon.objects.filter(
            code__iexact=applied_code,
            is_active=True,
            start_date__lte=today,
            end_date__gte=today
        ).first()
        if applied_coupon and subtotal >= applied_coupon.min_order_amount:
            if applied_coupon.code.upper() == 'NEW50' and not _is_first_order_user(request.user):
                applied_coupon = None
                request.session.pop('coupon_code', None)
            else:
                if applied_coupon.discount_type == 'Percent':
                    discount_amount = (subtotal * applied_coupon.value / Decimal('100')).quantize(Decimal('0.01'))
                    if applied_coupon.max_discount:
                        discount_amount = min(discount_amount, applied_coupon.max_discount)
                else:
                    discount_amount = applied_coupon.value
        else:
            applied_coupon = None
            request.session.pop('coupon_code', None)

    total_amount = max(Decimal('0'), subtotal + delivery_fee - discount_amount)

    available_coupons = Coupon.objects.filter(
        is_active=True,
        start_date__lte=timezone.now().date(),
        end_date__gte=timezone.now().date()
    ).order_by('end_date')

    context = {
        'cart': cart, # Can be None in buy_now_mode
        'checkout_items': checkout_items, # Use this for iteration
        'buy_now_mode': buy_now_mode,
        'buy_now_variant_id': buy_now_variant_id,
        'initial_contact': initial_contact,
        'addresses': addresses,
        'address_choices': [('Home', 'Home'), ('Office', 'Office'), ('Other', 'Other')],
        'delivery_fee': delivery_fee,
        'delivery_free_threshold': delivery_free_threshold,
        'discount_amount': discount_amount,
        'total_amount': total_amount,
        'available_coupons': available_coupons,
        'applied_coupon': applied_coupon,
    }
    return render(request, 'checkout.html', context)


@require_http_methods(["POST"])
def apply_coupon(request):
    if request.user.is_authenticated:
        cart = get_object_or_404(Cart, user=request.user)
    else:
        if not request.session.session_key:
            request.session.create()
        cart = get_object_or_404(Cart, session_id=request.session.session_key)

    if not cart.items.exists():
        return JsonResponse({'status': 'error', 'message': 'Cart is empty'}, status=400)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        payload = {}

    code = (payload.get('code') or '').strip()
    if not code:
        request.session.pop('coupon_code', None)
        return JsonResponse({'status': 'success', 'message': 'Coupon removed', 'discount': 0})

    today = timezone.now().date()
    coupon = Coupon.objects.filter(
        code__iexact=code,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today
    ).first()
    if not coupon:
        return JsonResponse({'status': 'error', 'message': 'Invalid or expired coupon.'}, status=400)

    if coupon.code.upper() == 'NEW50' and not _is_first_order_user(request.user):
        return JsonResponse({'status': 'error', 'message': 'NEW50 is only valid for first-time users.'}, status=400)

    subtotal = Decimal(str(cart.total_price))
    if subtotal < coupon.min_order_amount:
        return JsonResponse({'status': 'error', 'message': f'Minimum order ₹{coupon.min_order_amount} required.'}, status=400)

    if coupon.discount_type == 'Percent':
        discount_amount = (subtotal * coupon.value / Decimal('100')).quantize(Decimal('0.01'))
        if coupon.max_discount:
            discount_amount = min(discount_amount, coupon.max_discount)
    else:
        discount_amount = coupon.value

    request.session['coupon_code'] = coupon.code
    request.session.modified = True

    return JsonResponse({
        'status': 'success',
        'message': 'Coupon applied',
        'discount': float(discount_amount),
        'code': coupon.code,
    })


def track_order(request):
    order = None
    if request.method == 'POST':
        order_number = (request.POST.get('order_number') or '').strip()
        if order_number:
            order = Order.objects.select_related('user').prefetch_related(
                'items__product',
                'items__variant'
            ).filter(order_number__iexact=order_number).first()
            if not order:
                messages.error(request, 'Order not found. Please check the order number.')
        else:
            messages.error(request, 'Please enter an order number.')

    return render(request, 'track_order.html', {'order': order})

def get_razorpay_client():
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

def create_razorpay_order(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

    if request.user.is_authenticated:
        cart = get_object_or_404(Cart, user=request.user)
        prefill_name = f"{request.user.first_name} {request.user.last_name}".strip()
        prefill_email = request.user.email
        prefill_contact = request.user.phone or ''
    else:
        if not request.session.session_key:
            request.session.create()
        cart = get_object_or_404(Cart, session_id=request.session.session_key)
        prefill_name = ''
        prefill_email = ''
        prefill_contact = ''

    if not cart.items.exists():
        return JsonResponse({'status': 'error', 'message': 'Cart is empty'}, status=400)

    # Apply delivery fee + coupon discount for online payments
    delivery_free_threshold = Decimal('999')
    delivery_fee_fixed = Decimal('49')
    subtotal = Decimal(str(cart.total_price))
    delivery_fee = Decimal('0') if subtotal >= delivery_free_threshold else delivery_fee_fixed

    discount_amount = Decimal('0')
    applied_code = request.session.get('coupon_code')
    if applied_code:
        today = timezone.now().date()
        coupon = Coupon.objects.filter(
            code__iexact=applied_code,
            is_active=True,
            start_date__lte=today,
            end_date__gte=today
        ).first()
        if coupon and subtotal >= coupon.min_order_amount:
            if coupon.code.upper() == 'NEW50' and not _is_first_order_user(request.user):
                coupon = None
                request.session.pop('coupon_code', None)
            else:
                if coupon.discount_type == 'Percent':
                    discount_amount = (subtotal * coupon.value / Decimal('100')).quantize(Decimal('0.01'))
                    if coupon.max_discount:
                        discount_amount = min(discount_amount, coupon.max_discount)
                else:
                    discount_amount = coupon.value

    total_amount = max(Decimal('0'), subtotal + delivery_fee - discount_amount)
    amount_paise = int(total_amount * 100)
    receipt_id = f"SC-{uuid.uuid4().hex[:10].upper()}"

    client = get_razorpay_client()
    rp_order = client.order.create({
        'amount': amount_paise,
        'currency': 'INR',
        'receipt': receipt_id,
        'payment_capture': 1,
    })

    return JsonResponse({
        'status': 'success',
        'key_id': settings.RAZORPAY_KEY_ID,
        'order_id': rp_order.get('id'),
        'amount': rp_order.get('amount'),
        'currency': rp_order.get('currency'),
        'prefill': {
            'name': prefill_name,
            'email': prefill_email,
            'contact': prefill_contact,
        }
    })

def send_invoice_email(order):
    """Send invoice email to customer"""
    try:
        # Get user email
        recipient_email = order.email if order.email else (order.user.email if order.user else None)
        
        if not recipient_email:
            print(f"No email found for order {order.order_number}")
            return False
        
        # Render invoice HTML using email-specific template
        subtotal = sum((item.get_subtotal for item in order.items.all()), Decimal('0'))
        html_content = render_to_string('invoice_email.html', {'order': order, 'user': order.user, 'subtotal': subtotal})
        
        # Create email
        subject = f'Invoice for Order #{order.order_number} - SkinCraft'
        from_email = settings.DEFAULT_FROM_EMAIL
        to_email = [recipient_email]
        
        # Create message
        email = EmailMultiAlternatives(
            subject=subject,
            body=f'Thank you for your order! Please find your invoice below.\n\nOrder Number: {order.order_number}\nTotal Amount: ₹{order.total_amount}',
            from_email=from_email,
            to=to_email
        )
        
        # Attach HTML content
        email.attach_alternative(html_content, "text/html")
        
        # Send email
        email.send(fail_silently=False)
        print(f"Invoice email sent successfully to {recipient_email} for order {order.order_number}")
        return True
        
    except Exception as e:
        print(f"Error sending invoice email for order {order.order_number}: {str(e)}")
        return False

def get_available_delivery_partner():
    return (
        #assign delivery to delivery person only having active profile and least active orders
        User.objects.filter(role=User.DELIVERY, delivery_profile__is_active=True)
        .annotate(
            active_orders=Count(
                'assigned_orders',
                filter=Q(assigned_orders__status__in=['Pending', 'Shipped', 'On Way'])
            )
        )
        .order_by('active_orders', 'id')
        .first()
    )

def _is_first_order_user(user):
    if not user or not user.is_authenticated:
        return False
    return not Order.objects.filter(user=user).exists()

@transaction.atomic
def process_order(request):
    if request.method == 'POST':
        # CHECK FOR BUY NOW MODE
        buy_now_mode = request.POST.get('action') == 'buy_now'
        buy_now_variant_id = request.POST.get('variant_id')
        
        cart = None
        pseudo_items = []
        
        if buy_now_mode and buy_now_variant_id:
            try:
                variant = ProductVariant.objects.get(id=buy_now_variant_id)
                # Create a pseudo-item structure for processing
                from collections import namedtuple
                PseudoItem = namedtuple('PseudoItem', ['product', 'variant', 'quantity', 'subtotal'])
                
                item = PseudoItem(
                    product=variant.product,
                    variant=variant,
                    quantity=1,
                    subtotal=variant.price
                )
                pseudo_items = [item]
                cart_total_price = variant.price
            except ProductVariant.DoesNotExist:
                messages.error(request, 'Invalid item for Buy Now.')
                return redirect('checkout')
        else:
            # STANDARD CART CHECKOUT
            if request.user.is_authenticated:
                cart = get_object_or_404(Cart, user=request.user)
            else:
                cart = get_object_or_404(Cart, session_id=request.session.session_key)
            
            pseudo_items = cart.items.all()
            cart_total_price = cart.total_price

        # 2. Extract Details from Form
        full_name = request.POST.get('full_name')
        email = request.POST.get('email', '')
        phone = request.POST.get('phone', '')
        payment_method = request.POST.get('payment', 'cod')
        selected_address_id = request.POST.get('selected_address')

        razorpay_order_id = request.POST.get('razorpay_order_id')
        razorpay_payment_id = request.POST.get('razorpay_payment_id')
        razorpay_signature = request.POST.get('razorpay_signature')

        # 3. Get the selected address
        selected_address = None
        if selected_address_id and request.user.is_authenticated:
            selected_address = get_object_or_404(Address, id=selected_address_id, user=request.user)
        
        # If user is authenticated and no email provided, use user's email
        if request.user.is_authenticated and not email:
            email = request.user.email

        # 4. Verify Razorpay payment if needed
        if payment_method == 'online':
            if not (razorpay_order_id and razorpay_payment_id and razorpay_signature):
                messages.error(request, 'Payment verification failed. Please try again.')
                return redirect('checkout')

            client = get_razorpay_client()
            try:
                client.utility.verify_payment_signature({
                    'razorpay_order_id': razorpay_order_id,
                    'razorpay_payment_id': razorpay_payment_id,
                    'razorpay_signature': razorpay_signature,
                })
            except Exception:
                messages.error(request, 'Payment verification failed. Please try again.')
                return redirect('checkout')

        # 5. Create Unique Order
        order_number = f"SC-{uuid.uuid4().hex[:8].upper()}"
        # Set status based on payment method
        order_status = 'Pending' if payment_method == 'cod' else 'Pending'
        payment_status = 'Paid' if payment_method == 'online' else 'Pending'
        
        delivery_partner = get_available_delivery_partner()

        # Recalculate totals for order
        delivery_free_threshold = Decimal('999')
        delivery_fee_fixed = Decimal('49')
        subtotal = Decimal(str(cart_total_price))
        delivery_fee = Decimal('0') if subtotal >= delivery_free_threshold else delivery_fee_fixed

        discount_amount = Decimal('0')
        coupon_code = None
        applied_code = request.session.get('coupon_code')
        if applied_code:
            today = timezone.now().date()
            coupon = Coupon.objects.filter(
                code__iexact=applied_code,
                is_active=True,
                start_date__lte=today,
                end_date__gte=today
            ).first()
            if coupon and subtotal >= coupon.min_order_amount:
                if coupon.code.upper() == 'NEW50' and not _is_first_order_user(request.user):
                    messages.error(request, 'NEW50 is only valid for first-time users.')
                    request.session.pop('coupon_code', None)
                    return redirect('checkout')
                if coupon.discount_type == 'Percent':
                    discount_amount = (subtotal * coupon.value / Decimal('100')).quantize(Decimal('0.01'))
                    if coupon.max_discount:
                        discount_amount = min(discount_amount, coupon.max_discount)
                else:
                    discount_amount = coupon.value
                coupon_code = coupon.code

        total_amount = max(Decimal('0'), subtotal + delivery_fee - discount_amount)

        order = Order.objects.create(
            user=request.user if request.user.is_authenticated else None,
            assigned_to=delivery_partner,
            order_number=order_number,
            total_amount=total_amount,
            delivery_fee=delivery_fee,
            discount_amount=discount_amount,
            coupon_code=coupon_code,
            status=order_status,
            full_name=full_name,
            email=email,
            phone=phone,
            payment_method='Razorpay' if payment_method == 'online' else 'COD',
            payment_status=payment_status,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
            street_address=selected_address.street_address if selected_address else '',
            city=selected_address.city if selected_address else '',
            state=selected_address.state if selected_address else '',
            zip_code=selected_address.zip_code if selected_address else ''
        )

        # 6. Create OrderItems from pseudo items (works for both flows)
        for item in pseudo_items:
            OrderItem.objects.create(
                order=order,
                product=item.product,
                variant=item.variant,
                quantity=item.quantity,
                price_at_purchase=item.variant.price
            )
            # Decrement product variant stock
            item.variant.stock -= item.quantity
            item.variant.save()

        # 7. Send invoice email
        send_invoice_email(order)

        # 8. Clear the cart items and coupon if STANDARD FLOW
        if not buy_now_mode and cart:
            cart.items.all().delete()
        elif buy_now_mode:
            # For Buy Now, remove only the specific item from the cart if it exists
            # This prevents double purchasing if they later go to cart
            if request.user.is_authenticated:
                user_cart = Cart.objects.filter(user=request.user).first()
            else:
                user_cart = Cart.objects.filter(session_id=request.session.session_key).first()
                
            if user_cart:
                try:
                    # Find and remove/decrement the item in the cart
                    cart_item = user_cart.items.filter(variant_id=buy_now_variant_id).first()
                    if cart_item:
                        # Logic: Since we just bought 1 unit (assumed for buy now), 
                        # we should reduce quantity by 1 or delete if qty is 1.
                        # However, for simplicity and typical "Buy Now" expectation, 
                        # we often just remove the item line entirely to be safe/clean.
                        # Let's decrement for correctness.
                        if cart_item.quantity > 1:
                            cart_item.quantity -= 1
                            cart_item.save()
                        else:
                            cart_item.delete()
                except Exception as e:
                    # Log error but don't fail the order process
                    print(f"Error cleaning up cart after buy now: {e}")
        
        # Always remove coupon after use
        request.session.pop('coupon_code', None)
        
        return redirect('order_success', order_number=order_number)
        
    return redirect('checkout')

def order_success(request, order_number):
    return render(request, 'order_success.html', {'order_number': order_number})

def payment_failed(request, order_number=None):
    """Handle failed payment"""
    context = {'order_number': order_number}
    return render(request, 'payment_failed.html', context)

@csrf_exempt
@require_http_methods(["POST"])
def razorpay_webhook(request):
    """
    Handle Razorpay webhook notifications for payment updates.
    Verifies webhook signature and updates order payment status.
    """
    try:
        # Parse webhook payload
        event_data = json.loads(request.body)
        event = event_data.get('event')
        payload = event_data.get('payload', {})
        
        # Get webhook signature
        webhook_signature = request.headers.get('X-Razorpay-Signature')
        
        # Reconstruct message to verify signature
        message = request.body.decode('utf-8')
        expected_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Verify signature
        if webhook_signature != expected_signature:
            return JsonResponse({'status': 'error', 'message': 'Invalid signature'}, status=403)
        
        # Handle payment.authorized event
        if event == 'payment.authorized':
            payment_data = payload.get('payment', {})
            razorpay_payment_id = payment_data.get('entity', {}).get('id')
            razorpay_order_id = payment_data.get('entity', {}).get('order_id')
            
            if razorpay_order_id and razorpay_payment_id:
                # Update order payment status
                try:
                    order = Order.objects.get(razorpay_order_id=razorpay_order_id)
                    order.razorpay_payment_id = razorpay_payment_id
                    order.payment_status = 'Paid'
                    order.save()
                except Order.DoesNotExist:
                    pass
        
        # Handle payment.failed event
        elif event == 'payment.failed':
            razorpay_order_id = payload.get('payment', {}).get('entity', {}).get('order_id')
            
            if razorpay_order_id:
                try:
                    order = Order.objects.get(razorpay_order_id=razorpay_order_id)
                    order.payment_status = 'Failed'
                    order.save()
                except Order.DoesNotExist:
                    pass
        
        return JsonResponse({'status': 'success'})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

def knowledge_hub(request):
    hub_categories = [
        {'title': 'Skin Care Tips', 'slug': 'tips', 'icon': 'fa-face-smile'},
        {'title': 'Daily Life', 'slug': 'daily-life', 'icon': 'fa-sun'},
        {'title': 'Seasonal Rituals', 'slug': 'seasonal', 'icon': 'fa-cloud-sun'},
    ]
    return render(request, 'knowledge_hub.html', {'categories': hub_categories})


@login_required
def get_order_items(request, order_id):
    """Get order items for review modal"""
    try:
        order = Order.objects.get(id=order_id, user=request.user)
        items_data = []
        
        for item in order.items.all():
            # Check if user has already reviewed this product
            review = Review.objects.filter(
                user=request.user,
                product=item.product,
                order=order
            ).first()
            has_review = review is not None
            
            items_data.append({
                'product_id': item.product.id,
                'name': item.product.name,
                'variant': f"{item.variant.unit_value}{item.variant.unit_type}" if item.variant else '',
                'thumbnail': item.product.thumbnail.url if item.product.thumbnail else '/static/images/default-product.png',
                'has_review': has_review,
                'review_rating': review.rating if review else None,
                'review_comment': review.comment if review else ''
            })
        
        return JsonResponse({
            'status': 'success',
            'items': items_data
        })
    except Order.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Order not found'
        }, status=404)


@login_required
def submit_review(request):
    """Submit reviews for products in an order"""
    if request.method == 'POST':
        order_id = request.POST.get('order_id')
        product_ids = request.POST.getlist('product_id[]')
        
        try:
            order = Order.objects.get(id=order_id, user=request.user)
            
            # Create reviews for each product
            reviews_created = 0
            for product_id in product_ids:
                rating = request.POST.get(f'rating_{product_id}')
                comment = request.POST.get(f'comment_{product_id}')
                
                if rating and comment:
                    product = Product.objects.get(id=product_id)
                    
                    # Create or update review
                    review, created = Review.objects.update_or_create(
                        user=request.user,
                        product=product,
                        order=order,
                        defaults={
                            'rating': int(rating),
                            'comment': comment
                        }
                    )
                    reviews_created += 1
            
            if reviews_created > 0:
                messages.success(request, f'Successfully submitted {reviews_created} review(s)!')
            else:
                messages.warning(request, 'No reviews were submitted.')
                
        except Order.DoesNotExist:
            messages.error(request, 'Order not found!')
        except Exception as e:
            messages.error(request, f'Error submitting reviews: {str(e)}')
        
        return redirect('/profile/?tab=orders')
    
    return redirect('profile')

@login_required
def submit_return(request):
    """Submit return request for a delivered order"""
    if request.method == 'POST':
        order_id = request.POST.get('order_id')
        reason = request.POST.get('reason')
        issue = request.POST.get('issue') or request.POST.get('additional_details', '').strip() or reason
        additional_details = request.POST.get('additional_details', '')
        
        try:
            order = Order.objects.get(id=order_id, user=request.user, status='Delivered')
            
            # Check if return already exists
            if hasattr(order, 'return_request'):
                messages.warning(request, 'A return request already exists for this order!')
                return redirect('/profile/?tab=orders')
            
            # Create return request
            return_request = Return.objects.create(
                order=order,
                user=request.user,
                reason=reason,
                issue=issue,
                additional_details=additional_details
            )
            
            messages.success(request, f'Return request submitted successfully! Reference ID: {return_request.id}')
            
        except Order.DoesNotExist:
            messages.error(request, 'Order not found or not eligible for return!')
        except Exception as e:
            messages.error(request, f'Error submitting return request: {str(e)}')
        
        return redirect('/profile/?tab=orders')
    
    return redirect('profile')


@login_required
def confirm_return_pickup(request, return_id):
    """Confirm return pickup by delivery partner"""
    return_request = get_object_or_404(
        Return,
        id=return_id,
        assigned_to=request.user,
        status='Approved'
    )
    
    # Check if order was paid via COD
    is_cod = return_request.order.payment_method and return_request.order.payment_method.upper() == 'COD'
    bank_details = BankDetails.objects.filter(user=return_request.user).first() if return_request.user else None
    bank_details_exists = bank_details is not None
    
    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        # For COD orders, collect bank details first
        if is_cod and not bank_details_exists:
            form = BankDetailsForm(request.POST)
            if form.is_valid():
                # Save bank details for refund processing
                details = form.save(commit=False)
                details.user = return_request.user
                details.save()
                
                # Now complete the return
                return_request.status = 'Completed'
                return_request.picked_up_at = timezone.now()
                return_request.save()
                
                # Send confirmation email to customer
                try:
                    subject = f'Return Pickup Confirmed - Order #{return_request.order.order_number}'
                    message = f'''
Dear {return_request.user.get_full_name()},

Your return pickup has been successfully completed!

Order Number: {return_request.order.order_number}
Pickup Date: {return_request.picked_up_at.strftime('%B %d, %Y at %I:%M %p')}
Picked up by: {request.user.get_full_name()}

Bank Details Collected:
Account Holder: {details.account_holder_name}
Account Number: ****{details.account_number[-4:]}
IFSC Code: {details.ifsc_code}
Bank: {details.bank_name}
{f"UPI ID: {details.upi_id}" if details.upi_id else ""}

Your refund will be processed within 5-7 business days to your provided bank account.

Thank you for shopping with SkinCraft!

Best regards,
SkinCraft Team
                    '''
                    
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [return_request.user.email],
                        fail_silently=True,
                    )
                except Exception as e:
                    print(f"Failed to send email: {e}")
                
                if is_ajax:
                    return JsonResponse({'status': 'success', 'message': 'Return pickup confirmed.'})
                messages.success(request, f'Return pickup confirmed and bank details saved for Order #{return_request.order.order_number}!')
                return redirect('delivery_dashboard')
            else:
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': 'Please provide valid bank details to complete the COD return pickup.'}, status=400)
                messages.error(request, 'Please provide valid bank details to complete the COD return pickup.')
                return redirect('delivery_dashboard')
        else:
            # Non-COD order or bank details already collected
            return_request.status = 'Completed'
            return_request.picked_up_at = timezone.now()
            return_request.save()
            
            # Send confirmation email to customer
            try:
                subject = f'Return Pickup Confirmed - Order #{return_request.order.order_number}'
                message = f'''
Dear {return_request.user.get_full_name()},

Your return pickup has been successfully completed!

Order Number: {return_request.order.order_number}
Pickup Date: {return_request.picked_up_at.strftime('%B %d, %Y at %I:%M %p')}
Picked up by: {request.user.get_full_name()}

The returned item is now being processed. You will receive a refund within 5-7 business days.

Thank you for shopping with SkinCraft!

Best regards,
SkinCraft Team
                '''
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [return_request.user.email],
                    fail_silently=True,
                )
            except Exception as e:
                print(f"Failed to send email: {e}")
            
            if is_ajax:
                return JsonResponse({'status': 'success', 'message': 'Return pickup confirmed.'})
            messages.success(request, f'Return pickup confirmed for Order #{return_request.order.order_number}!')
            return redirect('delivery_dashboard')
    
    # GET request - not supported for pickup confirm
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=400)
    return redirect('delivery_dashboard')

@login_required
def invoice_view(request, order_id):
    """Display invoice page"""
    try:
        if request.user.is_staff:
            order = Order.objects.get(id=order_id)
        else:
            order = Order.objects.get(id=order_id, user=request.user)
        subtotal = sum((item.get_subtotal for item in order.items.all()), Decimal('0'))
        return render(request, 'invoice.html', {'order': order, 'subtotal': subtotal})
    except Order.DoesNotExist:
        messages.error(request, 'Order not found!')
        if request.user.is_staff:
            return redirect('admin_dashboard')
        return redirect('profile')


@login_required
def submit_product_review(request, product_id):
    """Submit review from product detail page with images"""
    if request.method == 'POST':
        try:
            product = Product.objects.get(id=product_id)
            rating = request.POST.get('rating')
            comment = request.POST.get('comment')
            
            # Check if user has purchased this product
            has_purchased = OrderItem.objects.filter(
                order__user=request.user,
                order__status='Delivered',
                product=product
            ).exists()
            
            if not has_purchased:
                messages.error(request, 'You can only review products you have purchased.')
                return redirect('product_detail', pk=product_id)
            
            # Create or update review
            review, created = Review.objects.update_or_create(
                user=request.user,
                product=product,
                defaults={
                    'rating': int(rating),
                    'comment': comment
                }
            )
            
            # Handle image removals
            remove_ids = request.POST.getlist('remove_review_images')
            if remove_ids:
                review.images.filter(id__in=remove_ids).delete()

            # Handle multiple image uploads
            images = request.FILES.getlist('review_images')
            if images:
                existing_count = review.images.count()
                remaining_slots = max(0, 5 - existing_count)
                if remaining_slots <= 0:
                    messages.warning(request, 'You can only upload up to 5 review images.')
                else:
                    for image in images[:remaining_slots]:
                        ReviewImage.objects.create(
                            review=review,
                            image=image
                        )
                    if len(images) > remaining_slots:
                        messages.warning(request, 'Only the first 5 review images were saved.')
            
            if created:
                messages.success(request, 'Thank you for your review!')
            else:
                messages.success(request, 'Your review has been updated!')
                
        except Product.DoesNotExist:
            messages.error(request, 'Product not found!')
        except Exception as e:
            messages.error(request, f'Error submitting review: {str(e)}')
        
        return redirect('product_detail', pk=product_id)
    
    return redirect('product')


# --- FORGOT PASSWORD VIEW ---
FORGOT_PASSWORD_OTP_EXPIRY_SECONDS = 120


def forgot_password(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Step 1: Send OTP
        if action == 'send_otp':
            email = request.POST.get('email', '').strip()
            cache_email = email.lower()

            if not email:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Please enter your email address.'})
                messages.error(request, 'Please enter your email address.')
                return render(request, 'forgot_password.html')
            
            try:
                user = User.objects.get(email__iexact=email)
                email = user.email
                cache_email = email.lower()
                
                # Generate 6-digit OTP
                otp = str(random.randint(100000, 999999))
                otp_expires_at = timezone.now() + timedelta(seconds=FORGOT_PASSWORD_OTP_EXPIRY_SECONDS)
                
                # Store OTP in cache for 2 minutes
                cache.set(
                    f'password_reset_otp_{cache_email}',
                    {
                        'otp': otp,
                        'expires_at': int(otp_expires_at.timestamp()),
                    },
                    FORGOT_PASSWORD_OTP_EXPIRY_SECONDS,
                )
                
                # Send OTP via email
                subject = 'Password Reset OTP - SkinCraft'
                message = f'''
                <html>
                <body style="font-family: Arial, sans-serif; background-color: #f5f7fa; padding: 20px;">
                    <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                        <div style="background: linear-gradient(135deg, #1A3C34 0%, #2d5a4a 100%); padding: 40px; text-align: center;">
                            <h1 style="color: #ffffff; font-size: 28px; margin: 0;">Password Reset</h1>
                        </div>
                        <div style="padding: 40px;">
                            <p style="font-size: 16px; color: #333333; margin-bottom: 20px;">Hello,</p>
                            <p style="font-size: 16px; color: #333333; margin-bottom: 20px;">You requested to reset your password. Use the verification code below:</p>
                            <div style="background-color: #f9fafb; border: 2px dashed #D4AF37; border-radius: 12px; padding: 30px; text-align: center; margin: 30px 0;">
                                <p style="font-size: 14px; color: #666666; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 2px; font-weight: bold;">Your Verification Code</p>
                                <p style="font-size: 36px; color: #1A3C34; font-weight: bold; letter-spacing: 8px; margin: 0;">{otp}</p>
                            </div>
                            <p style="font-size: 14px; color: #666666; margin-bottom: 10px;">This code will expire in <strong>2 minutes</strong>.</p>
                            <p style="font-size: 14px; color: #666666;">If you didn't request this, please ignore this email.</p>
                        </div>
                        <div style="background-color: #f9fafb; padding: 20px; text-align: center; border-top: 1px solid #e5e7eb;">
                            <p style="font-size: 12px; color: #9ca3af; margin: 0;">© 2026 SkinCraft • Ayurvedic Excellence</p>
                        </div>
                    </div>
                </body>
                </html>
                '''
                
                email_obj = EmailMultiAlternatives(
                    subject=subject,
                    body=f'Your OTP is: {otp}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[email]
                )
                email_obj.attach_alternative(message, "text/html")
                email_obj.send()
                
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'message': 'Verification code sent to your email! It expires in 2 minutes.',
                        'expires_at': int(otp_expires_at.timestamp()),
                    })
                else:
                    messages.success(request, 'Verification code sent to your email! It expires in 2 minutes.')
                    
            except User.DoesNotExist:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'No account found with this email address.'})
                else:
                    messages.error(request, 'No account found with this email address.')
            except Exception as e:
                cache.delete(f'password_reset_otp_{cache_email}')
                debug_message = f' ({str(e)})' if settings.DEBUG else ''
                if is_ajax:
                    return JsonResponse({'success': False, 'message': f'Unable to send verification code right now. Please try again.{debug_message}'})
                messages.error(request, f'Unable to send verification code right now. Please try again.{debug_message}')
        
        # Step 2: Verify OTP
        elif action == 'verify_otp':
            email = request.POST.get('email', '').strip()
            cache_email = email.lower()
            entered_otp = request.POST.get('otp')
            
            stored_data = cache.get(f'password_reset_otp_{cache_email}')
            stored_otp = stored_data.get('otp') if isinstance(stored_data, dict) else stored_data
            expires_at = int(stored_data.get('expires_at', 0)) if isinstance(stored_data, dict) else 0
            now_ts = int(timezone.now().timestamp())

            if expires_at and now_ts > expires_at:
                cache.delete(f'password_reset_otp_{cache_email}')
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Verification code expired. Please resend OTP.'})
                else:
                    messages.error(request, 'Verification code expired. Please resend OTP.')
                    return render(request, 'forgot_password.html')

            if stored_otp and stored_otp == entered_otp:
                if is_ajax:
                    return JsonResponse({'success': True, 'message': 'Code verified successfully!'})
                else:
                    messages.success(request, 'Code verified successfully!')
            else:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Invalid or expired verification code.'})
                else:
                    messages.error(request, 'Invalid or expired verification code.')
        
        # Step 3: Reset Password
        elif action == 'reset_password':
            email = request.POST.get('email', '').strip()
            cache_email = email.lower()
            otp = request.POST.get('otp')
            password1 = request.POST.get('password1')
            password2 = request.POST.get('password2')
            
            stored_data = cache.get(f'password_reset_otp_{cache_email}')
            stored_otp = stored_data.get('otp') if isinstance(stored_data, dict) else stored_data
            expires_at = int(stored_data.get('expires_at', 0)) if isinstance(stored_data, dict) else 0
            now_ts = int(timezone.now().timestamp())

            if expires_at and now_ts > expires_at:
                cache.delete(f'password_reset_otp_{cache_email}')
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Verification code expired. Please resend OTP.'})
                else:
                    messages.error(request, 'Verification code expired. Please resend OTP.')
                    return render(request, 'forgot_password.html')
            elif not stored_otp or stored_otp != otp:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Invalid verification code.'})
                else:
                    messages.error(request, 'Invalid verification code.')
            elif password1 != password2:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Passwords do not match.'})
                else:
                    messages.error(request, 'Passwords do not match.')
            else:
                try:
                    user = User.objects.get(email__iexact=email)
                    user.set_password(password1)
                    user.save()
                    
                    # Clear OTP from cache
                    cache.delete(f'password_reset_otp_{cache_email}')
                    
                    if is_ajax:
                        return JsonResponse({'success': True, 'message': 'Password reset successfully! Redirecting to login...'})
                    else:
                        messages.success(request, 'Password reset successfully! Please login with your new password.')
                        return redirect('login')
                        
                except User.DoesNotExist:
                    if is_ajax:
                        return JsonResponse({'success': False, 'message': 'User not found.'})
                    else:
                        messages.error(request, 'User not found.')
    
    return render(request, 'forgot_password.html')

