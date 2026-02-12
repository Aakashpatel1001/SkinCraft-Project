from django.db import models
from django.db.models import F
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils import timezone
import os
from datetime import date
from django.utils.text import slugify
from .models import *

class User(AbstractUser):
    ADMIN = 'Admin'
    DELIVERY = 'Delivery'
    CUSTOMER = 'Customer'

    ROLE_CHOICES = [
        (ADMIN, 'Admin'),
        (DELIVERY, 'Delivery Staff'),
        (CUSTOMER, 'Customer'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=CUSTOMER)
    phone = models.CharField(max_length=15, blank=True, null=True)
    profile_image = models.ImageField(upload_to='profile_pics/', default='default.jpg', blank=True, null=True)
    gender = models.CharField(max_length=10, choices=[('M', 'Male'), ('F', 'Female'), ('O', 'Other')], blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.username

class Address(models.Model):
    ADDRESS_TYPES = [
        ('Home', 'Home'),
        ('Work', 'Work'),
        ('Other', 'Other'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    address_type = models.CharField(max_length=10, choices=ADDRESS_TYPES, default='Home')
    street_address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=20)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.address_type}: {self.street_address}, {self.city}"


class BankDetails(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bank_details')
    account_holder_name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50)
    ifsc_code = models.CharField(max_length=20)
    bank_name = models.CharField(max_length=200)
    upi_id = models.CharField(max_length=100, blank=True, null=True, help_text='Optional: UPI ID for faster refunds')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Bank Details for {self.user}"


class DeliveryProfile(models.Model):
    VEHICLE_CHOICES = [
        ('Bike', 'Bike'),
        ('Scooter', 'Scooter'),
        ('Car', 'Car'),
        ('Van', 'Van'),
        ('Other', 'Other'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='delivery_profile')
    street_address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    zip_code = models.CharField(max_length=20, blank=True, null=True)
    license_number = models.CharField(max_length=50)
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_CHOICES, default='Bike')
    vehicle_number = models.CharField(max_length=20)
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Monthly Salary for the delivery personnel")
    is_active = models.BooleanField(default=True)
    joined_at = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.vehicle_type} ({self.vehicle_number})"


class Delivery(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Picked Up', 'Picked Up'),
        ('Delivered', 'Delivered'),
        ('Failed', 'Failed'),
        ('Cancelled', 'Cancelled'),
    ]
    
    order = models.OneToOneField('Order', on_delete=models.CASCADE, related_name='delivery')
    delivery_personnel = models.ForeignKey(
        DeliveryProfile, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='deliveries'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    
    # Timestamps
    assigned_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    
    # Delivery Details
    pickup_location = models.CharField(max_length=255, blank=True, null=True)
    delivery_location = models.CharField(max_length=255, blank=True, null=True)
    estimated_delivery_time = models.DateTimeField(blank=True, null=True)
    
    
    # Verification
    otp = models.CharField(max_length=6, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-assigned_at']
    
    def __str__(self):
        return f"Delivery for Order {self.order.order_number} - {self.status}"


class DeliveryPartnerReview(models.Model):
    RATING_CHOICES = [(i, f"{i} Star") for i in range(1, 6)]

    order = models.OneToOneField('Order', on_delete=models.CASCADE, related_name='delivery_review')
    delivery_partner = models.ForeignKey(DeliveryProfile, on_delete=models.CASCADE, related_name='reviews')
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='delivery_reviews')
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.delivery_partner.user.username} - {self.rating}"


class DeliveryHelpDeskTicket(models.Model):
    REASON_CHOICES = [
        ('Customer Not Available', 'Customer Not Available'),
        ('Wrong Address', 'Wrong Address'),
        ('Payment Issue', 'Payment Issue'),
        ('Package Damaged', 'Package Damaged'),
        ('Vehicle Issue', 'Vehicle Issue'),
        ('Other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('Open', 'Open'),
        ('Resolved', 'Resolved'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='helpdesk_tickets')
    reason = models.CharField(max_length=50, choices=REASON_CHOICES)
    remarks = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Open')
    admin_reply = models.TextField(blank=True, null=True)
    replied_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='helpdesk_replies'
    )
    replied_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.reason}"

class Order(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Shipped', 'Shipped'),
        ('On Way', 'On Way'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
    )
    PAYMENT_STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
        ('Failed', 'Failed'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='assigned_orders',
        null=True,
        blank=True
    )
    order_number = models.CharField(max_length=20, unique=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)
    full_name = models.CharField(max_length=200, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='Pending')
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)
    delivery_otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    street_address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    zip_code = models.CharField(max_length=10, blank=True, null=True)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    coupon_code = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.order_number


class Coupon(models.Model):
    DISCOUNT_TYPE_CHOICES = (
        ('Flat', 'Flat'),
        ('Percent', 'Percent'),
    )
 
    code = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    discount_type = models.CharField(max_length=10, choices=DISCOUNT_TYPE_CHOICES, default='Flat')
    value = models.DecimalField(max_digits=10, decimal_places=2)
    min_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_discount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.code

class ContactMessage(models.Model):
    SUBJECT_CHOICES = [
        ('General Inquiry', 'General Inquiry'),
        ('Order Status / Tracking', 'Order Status / Tracking'),
        ('Product Recommendation', 'Product Recommendation'),
        ('Returns & Refunds', 'Returns & Refunds'),
    ]

    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField()
    subject = models.CharField(max_length=100, choices=SUBJECT_CHOICES)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.subject}"

def product_thumbnail_path(instance, filename):
    folder_name = slugify(instance.name)
    return f'products/{folder_name}/thumbnail/{filename}'

def product_gallery_path(instance, filename):
    folder_name = slugify(instance.product.name)
    return f'products/{folder_name}/gallery/{filename}'

# 1. CATEGORY & SUB-CATEGORY
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

class SubCategory(models.Model):
    category = models.ForeignKey(Category, related_name='subcategories', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = "Sub Categories"

    def __str__(self):
        return f"{self.category.name} > {self.name}"

# 2. TAGS MODEL
class ProductTag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

# 3. MAIN PRODUCT MODEL
class Product(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    subcategory = models.ForeignKey(SubCategory, on_delete=models.SET_NULL, null=True, blank=True)
    thumbnail = models.ImageField(upload_to=product_thumbnail_path)
    tags = models.ManyToManyField(ProductTag, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def get_starting_price(self):
        min_variant = self.variants.order_by('price').first()
        if min_variant:
            return min_variant.price
        return 0
    
    def average_rating(self):
        from django.db.models import Avg
        avg = self.reviews.aggregate(Avg('rating'))['rating__avg']
        return round(avg, 1) if avg else 0

    @property
    def first_available_variant(self):
        """Returns the first variant with stock > 0, or the first variant if all OOS"""
        return self.variants.filter(stock__gt=0).first() or self.variants.first()

# 4. PRODUCT IMAGES (GALLERY)
class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to=product_gallery_path)

    def __str__(self):
        return f"Image for {self.product.name}"

# 5. PRODUCT VARIANTS (Stock, Price, Unit, Batch)
class ProductVariant(models.Model):
    UNIT_CHOICES = [
        ('ml', 'Milliliter (ml)'),
        ('g', 'Gram (g)'),
        ('kg', 'Kilogram (kg)'),
        ('l', 'Liter (L)'),
        ('pc', 'Piece'),
    ]
    product = models.ForeignKey(Product, related_name='variants', on_delete=models.CASCADE)
    unit_value = models.PositiveIntegerField(help_text="e.g., 100, 500, 1")
    unit_type = models.CharField(max_length=10, choices=UNIT_CHOICES, default='ml')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    batch_number = models.CharField(max_length=50, help_text="Batch Number for tracking")
    manufacturing_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(help_text="Date when product expires")

    class Meta:
        unique_together = ('product', 'unit_value', 'unit_type', 'batch_number')

    def is_expired(self):
        if self.expiry_date:
            return date.today() > self.expiry_date
        return False

    def __str__(self):
        return f"{self.product.name} - {self.unit_value}{self.unit_type}"

class Wishlist(models.Model):
    wishlist_id = models.AutoField(primary_key=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name="wishlist"
    )
    
    product = models.ForeignKey(
        'Product', 
        on_delete=models.CASCADE, 
        related_name="wishlisted_by"
    )
    
    variant = models.ForeignKey(
        'ProductVariant', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product', 'variant')
        verbose_name = "Wishlist Item"
        verbose_name_plural = "Wishlist Items"

        indexes = [
            models.Index(fields=['user', 'product']),
        ]

    def __str__(self):
        variant_str = f" ({self.variant})" if self.variant else ""
        return f"{self.user.username} - {self.product.name}{variant_str}"

class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    session_id = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart {self.id} for {self.user or self.session_id}"

    @property
    def total_price(self):
        return sum(item.subtotal for item in self.items.all())

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.product.name} ({self.variant.unit_value}{self.variant.unit_type})"

    @property
    def subtotal(self):
        return self.variant.price * self.quantity

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL)
    variant = models.ForeignKey(ProductVariant, null=True, on_delete=models.SET_NULL)
    quantity = models.PositiveIntegerField()
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def get_subtotal(self):
        return self.price_at_purchase * self.quantity

    def __str__(self):
        return f"{self.product.name} - Order {self.order.order_number}"

class Review(models.Model):
    RATING_CHOICES = [
        (1, '1 Star'),
        (2, '2 Stars'),
        (3, '3 Stars'),
        (4, '4 Stars'),
        (5, '5 Stars'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    rating = models.IntegerField(choices=RATING_CHOICES)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.product.name} ({self.rating} stars)"

class ReviewImage(models.Model):
    review = models.ForeignKey(Review, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='reviews/%Y/%m/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Image for review {self.review.id}"

class Return(models.Model):
    RETURN_REASON_CHOICES = (
        ('Damaged', 'Damaged Product'),
        ('Wrong Item', 'Wrong Item Received'),
        ('Not as Described', 'Not as Described'),
        ('Quality Issue', 'Quality Issue'),
        ('Expired', 'Product Expired'),
        ('Missing Items', 'Missing Items'),
        ('Changed Mind', 'Changed Mind'),
        ('Other', 'Other'),
    )
    
    RETURN_STATUS_CHOICES = (
        ('Initiated', 'Initiated'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Completed', 'Completed'),
    )
    
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='return_request')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='returns')
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='assigned_returns',
        null=True,
        blank=True,
        help_text='Delivery partner assigned for return pickup'
    )
    reason = models.CharField(max_length=50, choices=RETURN_REASON_CHOICES)
    issue = models.CharField(max_length=255)
    additional_details = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=RETURN_STATUS_CHOICES, default='Initiated')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    picked_up_at = models.DateTimeField(null=True, blank=True, help_text='When the return item was picked up')
    
    def __str__(self):
        return f"Return Request - {self.order.order_number} ({self.status})"

class Payment(models.Model):
    """Store payment details for orders (COD and Online)"""
    PAYMENT_METHOD_CHOICES = (
        ('COD', 'Cash on Delivery'),
        ('Razorpay', 'Razorpay'),
        ('UPI', 'UPI'),
    )
    
    PAYMENT_STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Completed', 'Completed'),
        ('Failed', 'Failed'),
    )
    
    # Core Fields
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='Pending')
    
    # For Online Payments (Razorpay)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
    
    def __str__(self):
        return f"{self.order.order_number} - {self.get_status_display()}"


class Refund(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Processed', 'Processed'),
        ('Failed', 'Failed'),
    )

    refund_id = models.CharField(max_length=20, unique=True, blank=True, null=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='refunds')
    return_request = models.OneToOneField(Return, on_delete=models.CASCADE, related_name='refund_record', null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    damage_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Processed')
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='refunds_processed')
    processed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        ref = self.refund_id or f"#{self.id}"
        return f"Refund {ref} - {self.order.order_number} ({self.status})"

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.refund_id:
            self.refund_id = f"REF-{self.pk:06d}"
            super().save(update_fields=['refund_id'])


class SalaryPayment(models.Model):
    """Track salary payments for delivery partners"""
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
        ('Hold', 'On Hold'),
        ('Cancelled', 'Cancelled'),
    )
    
    PAYMENT_MODE_CHOICES = (
        ('Bank Transfer', 'Bank Transfer'),
        ('UPI', 'UPI'),
    )
    
    # Employee Information
    delivery_partner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='salary_payments',
        limit_choices_to={'role': 'Delivery'}
    )
    
    # Salary Details
    month = models.IntegerField(help_text='Month (1-12)')
    year = models.IntegerField(help_text='Year (e.g., 2026)')
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, help_text='Base monthly salary')
    bonus = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='Performance bonus')
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='Deductions (if any)')
    net_salary = models.DecimalField(max_digits=10, decimal_places=2, help_text='Final amount to be paid')
    
    # Performance Metrics
    deliveries_completed = models.IntegerField(default=0, help_text='Total deliveries completed in the month')
    returns_completed = models.IntegerField(default=0, help_text='Total returns picked up in the month')
    
    # Payment Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, blank=True, null=True)
    transaction_reference = models.CharField(max_length=100, blank=True, null=True, help_text='Transaction ID or reference number')
    transfer_account_holder_name = models.CharField(max_length=200, blank=True, null=True, help_text='Snapshot of account holder used for this transfer')
    transfer_account_last4 = models.CharField(max_length=4, blank=True, null=True, help_text='Last 4 digits of account number used for this transfer')
    transfer_ifsc_code = models.CharField(max_length=20, blank=True, null=True, help_text='Snapshot of IFSC used for this transfer')
    transfer_bank_name = models.CharField(max_length=200, blank=True, null=True, help_text='Snapshot of bank name used for this transfer')
    transfer_upi_id = models.CharField(max_length=100, blank=True, null=True, help_text='Snapshot of UPI ID used for this transfer')
    remarks = models.TextField(blank=True, null=True, help_text='Additional notes or remarks')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='salaries_processed'
    )
    
    class Meta:
        ordering = ['-year', '-month', '-created_at']
        unique_together = ['delivery_partner', 'month', 'year']
        verbose_name = 'Salary Payment'
        verbose_name_plural = 'Salary Payments'
    
    def __str__(self):
        from datetime import date
        month_name = date(self.year, self.month, 1).strftime('%B')
        return f"{self.delivery_partner.get_full_name()} - {month_name} {self.year} - ₹{self.net_salary}"
    
    def get_period_display(self):
        from datetime import date
        month_name = date(self.year, self.month, 1).strftime('%B')
        return f"{month_name} {self.year}"

    def get_transfer_destination_display(self):
        if self.payment_mode == 'UPI':
            if self.transfer_upi_id:
                return f"UPI: {self.transfer_upi_id}"
            return '-'
        if self.payment_mode == 'Bank Transfer':
            parts = []
            if self.transfer_account_holder_name:
                parts.append(self.transfer_account_holder_name)
            if self.transfer_bank_name:
                parts.append(self.transfer_bank_name)
            if self.transfer_ifsc_code:
                parts.append(f"IFSC {self.transfer_ifsc_code}")
            if self.transfer_account_last4:
                parts.append(f"A/C ****{self.transfer_account_last4}")
            return ' | '.join(parts) if parts else '-'
        return '-'

    def save(self, *args, **kwargs):
        snapshot_empty = not any([
            self.transfer_upi_id,
            self.transfer_account_last4,
            self.transfer_ifsc_code,
            self.transfer_bank_name,
            self.transfer_account_holder_name,
        ])
        if self.delivery_partner_id and self.payment_mode and snapshot_empty:
            partner_bank = getattr(self.delivery_partner, 'bank_details', None)
            if partner_bank:
                if self.payment_mode == 'UPI':
                    self.transfer_upi_id = partner_bank.upi_id or None
                elif self.payment_mode == 'Bank Transfer':
                    self.transfer_account_holder_name = partner_bank.account_holder_name
                    self.transfer_bank_name = partner_bank.bank_name
                    self.transfer_ifsc_code = partner_bank.ifsc_code
                    self.transfer_account_last4 = (partner_bank.account_number or '')[-4:] or None
        super().save(*args, **kwargs)

# Signals for auto-assignment
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.db.models import Count, Q, F
from django.core.mail import send_mail
from django.conf import settings

@receiver(pre_save, sender=Return)
def auto_assign_delivery_for_return(sender, instance, **kwargs):
    """Automatically assign delivery person when return is approved by admin"""
    if instance.pk:  # Only for existing returns
        try:
            old_instance = Return.objects.get(pk=instance.pk)
            # Check if status changed to Approved and no delivery person assigned
            if instance.status == 'Approved' and old_instance.status != 'Approved' and not instance.assigned_to:
                # Find delivery personnel with least active deliveries
                delivery_users = User.objects.filter(
                    role=User.DELIVERY,
                    is_active=True,
                    delivery_profile__is_active=True
                ).annotate(
                    active_deliveries=Count(
                        'assigned_orders',
                        filter=Q(assigned_orders__status__in=['Shipped', 'On Way'])
                    ),
                    active_returns=Count(
                        'assigned_returns',
                        filter=Q(assigned_returns__status='Approved')
                    )
                )
                
                # Find the delivery user with minimum total workload
                delivery_user = None
                min_workload = float('inf')
                
                for user in delivery_users:
                    total_workload = user.active_deliveries + user.active_returns
                    if total_workload < min_workload:
                        min_workload = total_workload
                        delivery_user = user
                
                if delivery_user:
                    instance.assigned_to = delivery_user
                    # Mark that notification needs to be sent
                    instance._notify_delivery_person = True
        except Return.DoesNotExist:
            pass

@receiver(post_save, sender=Return)
def notify_delivery_person_for_return(sender, instance, created, **kwargs):
    """Send notification to delivery person after return pickup assignment"""
    if hasattr(instance, '_notify_delivery_person') and instance._notify_delivery_person:
        if instance.assigned_to and instance.assigned_to.email:
            try:
                # Send email notification
                subject = f'Return Pickup Assignment - Order #{instance.order.order_number}'
                message = f'''
Hello {instance.assigned_to.get_full_name()},

You have been assigned a RETURN PICKUP request!

Order Number: {instance.order.order_number}
Customer: {instance.order.full_name}
Pickup Address: {instance.order.street_address}, {instance.order.city}, {instance.order.state} - {instance.order.zip_code}
Phone: {instance.order.phone}
Return Reason: {instance.get_reason_display()}
Issue: {instance.issue}

Please login to your delivery dashboard to accept and view full details.

Thank you!
SkinCraft Team
                '''
                
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [instance.assigned_to.email],
                    fail_silently=True,
                )
            except Exception as e:
                print(f"Failed to send email: {e}")
        
        # Clear the flag
        del instance._notify_delivery_person
