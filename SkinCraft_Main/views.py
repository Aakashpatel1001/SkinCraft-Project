from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from .forms import *
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from .models import *
from django.db.models import Min, Max, Q, Count, Sum
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
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

# --- REGISTRATION VIEW ---
def register_view(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! Please log in.')
            return redirect('login') 
    else:
        form = UserRegistrationForm()
    
    return render(request, 'register.html', {'form': form})

# --- LOGIN VIEW ---
def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            
            if user is not None:
                login(request, user)
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

# --- LOGOUT VIEW ---
def logout_view(request):
    logout(request)
    messages.info(request, "You have successfully logged out.")
    return redirect('homepage')


# --- ADMIN DASHBOARD VIEW ---
@login_required
def admin_dashboard(request):
    """Admin dashboard showing business statistics"""
    if not request.user.is_staff:
        messages.error(request, 'Access denied. You need admin privileges.')
        return redirect('homepage')
    
    # Get statistics
    stats = {
        'total_orders': Order.objects.count(),
        'total_payments': Payment.objects.count(),
        'total_returns': Return.objects.count(),
        'total_users': User.objects.count(),
        'total_products': Product.objects.count(),
        'pending_orders': Order.objects.filter(status='Pending').count(),
        'pending_returns': Return.objects.filter(status='Initiated').count(),
        'delivered_orders': Order.objects.filter(status='Delivered').count(),
        'total_revenue': Payment.objects.filter(payment_type='Order', status='Completed').aggregate(total=Sum('amount'))['total'] or 0,
    }
    
    # Recent data
    recent_orders = Order.objects.select_related('user', 'assigned_to').order_by('-created_at')[:10]
    recent_payments = Payment.objects.select_related('order', 'return_request').order_by('-created_at')[:10]
    recent_returns = Return.objects.select_related('order', 'user', 'assigned_to').order_by('-created_at')[:10]
    
    context = {
        'stats': stats,
        'recent_orders': recent_orders,
        'recent_payments': recent_payments,
        'recent_returns': recent_returns,
    }
    
    return render(request, 'admin_dashboard.html', context)

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
    return render(request, 'about.html')

def privacy_policy(request):
    return render(request, 'privacy_policy.html')

def shipping_policy(request):
    return render(request, 'shipping_policy.html')


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

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    delivered_count = deliveries.filter(status='Delivered', delivered_at__gte=month_start).count()
    pending_count = deliveries.filter(status__in=['Pending', 'Picked Up'], assigned_at__gte=month_start).count()

    monthly_salary = profile.salary if profile else 0

    if monthly_salary and monthly_salary > 0:
        salary_paid = monthly_salary
        salary_due = 0
    else:
        salary_paid = 0
        salary_due = monthly_salary

    context = {
        'stats': {
            'monthly_salary': monthly_salary,
            'salary_paid': salary_paid,
            'salary_due': salary_due,
            'pending_count': active_orders.count(),
            'total_delivered': delivered_orders.count(),
            'return_pickups': assigned_returns.count(),
        },
        'tasks': active_orders,
        'pickup_tasks': assigned_returns,
        'history': delivered_orders,
        'completed_pickups': completed_returns,
        'profile': profile,
        'helpdesk_reasons': DeliveryHelpDeskTicket.REASON_CHOICES,
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

    if request.method == 'POST':
        # 1. Update Profile Ritual
        if 'update_profile' in request.POST:
            user_form = UserUpdateForm(request.POST, request.FILES, instance=request.user)
            if user_form.is_valid():
                user_form.save()
                messages.success(request, 'Your profile sanctuary has been updated!')
                return redirect('/profile/?tab=edit')
            active_tab = 'edit'

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
    
    context = {
        'orders': orders,
        'addresses': addresses,
        'user_form': user_form,
        'address_form': address_form,
        'password_form': password_form,
        'active_tab': active_tab,
        'edit_address_id': edit_address_id,
        # Passing model choices for dynamic icon handling
        'address_choices': Address.ADDRESS_TYPES 
    }
    return render(request, 'profile.html', context)

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
    items = Wishlist.objects.filter(user=request.user).select_related('product').order_by('-added_at')
    
    context = {
        'wishlist_items': items,
    }
    return render(request, 'wishlist.html', context)

@login_required
def toggle_wishlist(request, product_id):
    """
    Handles the AJAX ritual for adding/removing items.
    Ensures that if variant_id is missing, it removes the entire product entry.
    """
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        variant_id = request.POST.get('variant_id')

        if variant_id:
            variant = ProductVariant.objects.filter(id=variant_id).first()
            wish_items = Wishlist.objects.filter(user=request.user, product=product, variant=variant)
        else:
            wish_items = Wishlist.objects.filter(user=request.user, product=product)

        if wish_items.exists():
            wish_items.delete()
            return JsonResponse({'status': 'removed'})
        else:
            variant = ProductVariant.objects.filter(id=variant_id).first() if variant_id else None
            Wishlist.objects.create(user=request.user, product=product, variant=variant)
            return JsonResponse({'status': 'added'})
            
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
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        variant_id = request.POST.get('variant_id')
        
        # Validation: Ensure a variant exists
        variant = get_object_or_404(ProductVariant, id=variant_id)

        # Get or create cart
        cart, created = Cart.objects.get_or_create(
            user=request.user if request.user.is_authenticated else None,
            defaults={'session_id': request.session.session_key if not request.user.is_authenticated else None}
        )
        
        # Add or update item
        item, created = CartItem.objects.get_or_create(
            cart=cart, product=product, variant=variant
        )
        if not created:
            item.quantity += 1
            item.save()

        # AJAX Response
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            total_items = sum(i.quantity for i in cart.items.all())
            return JsonResponse({
                'status': 'success',
                'cart_count': total_items
            })
            
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

def cart_view(request):
    cart = get_or_create_cart(request)
    return render(request, 'cart.html', {'cart': cart})

def update_cart_quantity(request, item_id, action):
    item = get_object_or_404(CartItem, id=item_id)
    if action == 'plus':
        item.quantity += 1
        item.save()
    elif action == 'minus':
        if item.quantity > 1:
            item.quantity -= 1
            item.save()
        else:
            # Delete item if quantity is 1 and user clicks minus
            item.delete()
    return redirect('cart_view')

def delete_cart_item(request, item_id):
    item = get_object_or_404(CartItem, id=item_id)
    item.delete()
    return redirect('cart_view')

def checkout_view(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        # Fetch saved data for the sanctuary ritual
        initial_contact = {
            'full_name': f"{request.user.first_name} {request.user.last_name}",
            'email': request.user.email,
            'phone': request.user.phone or ""
        }
        addresses = Address.objects.filter(user=request.user)
    else:
        # Redirect if no guest session exists
        session_id = request.session.session_key
        if not session_id:
            return redirect('cart_view')
        cart, _ = Cart.objects.get_or_create(session_id=session_id)
        initial_contact = {}
        addresses = []

    if not cart.items.exists():
        return redirect('cart_view')
    
    context = {
        'cart': cart,
        'initial_contact': initial_contact,
        'addresses': addresses,
        'address_choices': [('Home', 'Home'), ('Office', 'Office'), ('Other', 'Other')],
    }
    return render(request, 'checkout.html', context)

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

    amount_paise = int(cart.total_price * 100)
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
        html_content = render_to_string('invoice_email.html', {'order': order, 'user': order.user})
        
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

@transaction.atomic
def process_order(request):
    if request.method == 'POST':
        # 1. Retrieve the bag for Auth or Guest
        if request.user.is_authenticated:
            cart = get_object_or_404(Cart, user=request.user)
        else:
            cart = get_object_or_404(Cart, session_id=request.session.session_key)

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

        order = Order.objects.create(
            user=request.user if request.user.is_authenticated else None,
            assigned_to=delivery_partner,
            order_number=order_number,
            total_amount=cart.total_price,
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

        # 6. Create OrderItems from cart items
        for item in cart.items.all():
            OrderItem.objects.create(
                order=order,
                product=item.product,
                variant=item.variant,
                quantity=item.quantity,
                price_at_purchase=item.variant.price
            )

        # 7. Send invoice email
        send_invoice_email(order)

        # 8. Clear the cart items
        cart.items.all().delete()
        
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
        issue = request.POST.get('issue')
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
    payment_exists = Payment.objects.filter(return_request=return_request, payment_type='Refund').exists()
    
    if request.method == 'POST':
        # For COD orders, collect bank details first
        if is_cod and not payment_exists:
            form = PaymentForm(request.POST)
            if form.is_valid():
                # Create payment record for refund
                payment = form.save(commit=False)
                payment.order = return_request.order
                payment.return_request = return_request
                payment.payment_type = 'Refund'
                payment.payment_method = 'COD'
                payment.amount = return_request.order.total_amount
                payment.status = 'Completed'
                payment.collected_by = request.user
                payment.completed_at = timezone.now()
                payment.save()
                
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
Account Holder: {payment.account_holder_name}
Account Number: ****{payment.account_number[-4:]}
IFSC Code: {payment.ifsc_code}
Bank: {payment.bank_name}
{f"UPI ID: {payment.upi_id}" if payment.upi_id else ""}

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
                
                messages.success(request, f'Return pickup confirmed and bank details saved for Order #{return_request.order.order_number}!')
                return redirect('delivery_dashboard')
            else:
                # Form has errors, re-render with form
                context = {
                    'return_request': return_request,
                    'is_cod': is_cod,
                    'form': form,
                    'needs_bank_details': True,
                }
                return render(request, 'delivery_return_confirm.html', context)
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
            
            messages.success(request, f'Return pickup confirmed for Order #{return_request.order.order_number}!')
            return redirect('delivery_dashboard')
    
    # GET request - show form if bank details needed
    if is_cod and not payment_exists:
        form = PaymentForm()
        context = {
            'return_request': return_request,
            'is_cod': is_cod,
            'form': form,
            'needs_bank_details': True,
        }
        return render(request, 'delivery_return_confirm.html', context)
    else:
        # Get existing payment if available
        payment = Payment.objects.filter(return_request=return_request, payment_type='Refund').first()
        context = {
            'return_request': return_request,
            'is_cod': is_cod,
            'needs_bank_details': False,
            'payment': payment,
        }
        return render(request, 'delivery_return_confirm.html', context)




@login_required
def invoice_view(request, order_id):
    """Display invoice page"""
    try:
        order = Order.objects.get(id=order_id, user=request.user)
        return render(request, 'invoice.html', {'order': order})
    except Order.DoesNotExist:
        messages.error(request, 'Order not found!')
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
            
            # Handle multiple image uploads
            images = request.FILES.getlist('review_images')
            if images:
                # Delete old images if updating
                if not created:
                    review.images.all().delete()
                
                # Add new images (limit to 5)
                for image in images[:5]:
                    ReviewImage.objects.create(
                        review=review,
                        image=image
                    )
            
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
def forgot_password(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # Step 1: Send OTP
        if action == 'send_otp':
            email = request.POST.get('email')
            
            try:
                user = User.objects.get(email=email)
                
                # Generate 6-digit OTP
                otp = str(random.randint(100000, 999999))
                
                # Store OTP in cache for 10 minutes
                cache.set(f'password_reset_otp_{email}', otp, 600)
                
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
                            <p style="font-size: 14px; color: #666666; margin-bottom: 10px;">This code will expire in <strong>10 minutes</strong>.</p>
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
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': 'Verification code sent to your email!'})
                else:
                    messages.success(request, 'Verification code sent to your email!')
                    
            except User.DoesNotExist:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'No account found with this email address.'})
                else:
                    messages.error(request, 'No account found with this email address.')
        
        # Step 2: Verify OTP
        elif action == 'verify_otp':
            email = request.POST.get('email')
            entered_otp = request.POST.get('otp')
            
            stored_otp = cache.get(f'password_reset_otp_{email}')
            
            if stored_otp and stored_otp == entered_otp:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': 'Code verified successfully!'})
                else:
                    messages.success(request, 'Code verified successfully!')
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Invalid or expired verification code.'})
                else:
                    messages.error(request, 'Invalid or expired verification code.')
        
        # Step 3: Reset Password
        elif action == 'reset_password':
            email = request.POST.get('email')
            otp = request.POST.get('otp')
            password1 = request.POST.get('password1')
            password2 = request.POST.get('password2')
            
            stored_otp = cache.get(f'password_reset_otp_{email}')
            
            if not stored_otp or stored_otp != otp:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Invalid verification code.'})
                else:
                    messages.error(request, 'Invalid verification code.')
            elif password1 != password2:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Passwords do not match.'})
                else:
                    messages.error(request, 'Passwords do not match.')
            else:
                try:
                    user = User.objects.get(email=email)
                    user.set_password(password1)
                    user.save()
                    
                    # Clear OTP from cache
                    cache.delete(f'password_reset_otp_{email}')
                    
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': True, 'message': 'Password reset successfully! Redirecting to login...'})
                    else:
                        messages.success(request, 'Password reset successfully! Please login with your new password.')
                        return redirect('login')
                        
                except User.DoesNotExist:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': 'User not found.'})
                    else:
                        messages.error(request, 'User not found.')
    
    return render(request, 'forgot_password.html')
