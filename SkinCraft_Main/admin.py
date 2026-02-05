from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *


# Register Custom User model using UserAdmin
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    
    # Customize the list display to show your custom fields
    list_display = ('username', 'email', 'phone', 'role', 'is_staff', 'is_active')
    
    # Add filters for quick sorting
    list_filter = ('role', 'is_staff', 'is_active', 'gender')
    
    # Add search capabilities
    search_fields = ('username', 'email', 'phone', 'first_name', 'last_name')
    
    # Organize fields in the "Edit User" form
    # Note: 'role' is now a direct field on User, so this works perfectly
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {'fields': ('phone', 'role', 'gender')}),
    )
    
    # Organize fields in the "Add User" form
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Additional Info', {'fields': ('phone', 'role', 'gender', 'email', 'first_name', 'last_name')}),
    )
from django.contrib import admin
from .models import ContactMessage

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'subject', 'email', 'formatted_created_at')
    list_filter = ('subject', 'created_at')
    search_fields = ('name', 'email', 'phone', 'message')
    readonly_fields = ('created_at',)
    
    def formatted_created_at(self, obj):
        from django.utils import timezone
        local_time = timezone.localtime(obj.created_at)
        return local_time.strftime('%d %B %Y, %I:%M %p')
    formatted_created_at.short_description = 'Created At'
    formatted_created_at.admin_order_field = 'created_at'

# 1. Inlines (Manage Images & Variants inside the Product page)
class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1

class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ('unit_value', 'unit_type', 'price', 'stock', 'batch_number', 'manufacturing_date', 'expiry_date')

# 2. Product Admin
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_active', 'get_starting_price')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'description')
    # Removed prepopulated_fields because there is no slug
    inlines = [ProductVariantInline, ProductImageInline]

# 3. Register other models
admin.site.register(Category)
admin.site.register(SubCategory)
admin.site.register(ProductTag)
admin.site.register(ProductVariant)
admin.site.register(Wishlist)
admin.site.register(Address)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'user', 'status', 'payment_status', 'assigned_to', 'total_amount', 'created_at')
    list_filter = ('status', 'payment_status', 'created_at')
    search_fields = ('order_number', 'user__username', 'email', 'phone')
    readonly_fields = ('order_number', 'created_at', 'delivered_at')
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order_number', 'user', 'total_amount', 'created_at')
        }),
        ('Status', {
            'fields': ('status', 'payment_status', 'assigned_to')
        }),
        ('Customer Details', {
            'fields': ('full_name', 'email', 'phone')
        }),
        ('Delivery Address', {
            'fields': ('street_address', 'city', 'state', 'zip_code')
        }),
        ('Payment Details', {
            'fields': ('payment_method', 'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature')
        }),
        ('Delivery Info', {
            'fields': ('delivery_otp', 'otp_created_at', 'delivered_at')
        }),
    )

admin.site.register(DeliveryProfile)
admin.site.register(Delivery)
admin.site.register(DeliveryHelpDeskTicket)

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('user__username', 'product__name', 'comment')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ReviewImage)
class ReviewImageAdmin(admin.ModelAdmin):
    list_display = ('review', 'uploaded_at')
    list_filter = ('uploaded_at',)
    readonly_fields = ('uploaded_at',)

@admin.register(Return)
class ReturnAdmin(admin.ModelAdmin):
    list_display = ('order', 'user', 'reason', 'status', 'assigned_to', 'refund_payment_status', 'created_at')
    list_filter = ('status', 'reason', 'created_at')
    search_fields = ('order__order_number', 'user__username', 'issue')
    readonly_fields = ('created_at', 'updated_at', 'assigned_to', 'payment_details_display')
    fieldsets = (
        ('Order Information', {
            'fields': ('order', 'user')
        }),
        ('Return Details', {
            'fields': ('reason', 'issue', 'additional_details', 'status')
        }),
        ('Pickup Assignment', {
            'fields': ('assigned_to',),
            'description': 'Delivery partner will be auto-assigned when status is changed to Approved'
        }),
        ('Refund Payment Details', {
            'fields': ('payment_details_display',),
            'classes': ('collapse',),
            'description': 'Payment details for refund processing'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'picked_up_at'),
            'classes': ('collapse',)
        }),
    )
    
    def refund_payment_status(self, obj):
        """Show refund payment status"""
        try:
            payment = obj.payment
            if payment.status == 'Completed':
                return '✓ Refund Details Collected'
            return f'- {payment.status}'
        except:
            return '- No Payment'
    refund_payment_status.short_description = 'Refund Status'
    
    def payment_details_display(self, obj):
        """Display collected payment details"""
        try:
            payment = obj.payment
            if payment.payment_method == 'COD':
                return f"""
                <div style="background: #f0f0f0; padding: 15px; border-radius: 5px;">
                    <p><strong>Type:</strong> COD Refund</p>
                    <p><strong>Amount:</strong> ₹{payment.amount}</p>
                    <p><strong>Status:</strong> {payment.get_status_display()}</p>
                    <hr style="margin: 10px 0;">
                    <p><strong>Account Holder:</strong> {payment.account_holder_name}</p>
                    <p><strong>Bank:</strong> {payment.bank_name}</p>
                    <p><strong>Account Number:</strong> ****{payment.account_number[-4:]}</p>
                    <p><strong>IFSC Code:</strong> {payment.ifsc_code}</p>
                    {f'<p><strong>UPI ID:</strong> {payment.upi_id}</p>' if payment.upi_id else ''}
                    <p><strong>Collected By:</strong> {payment.collected_by.get_full_name()}</p>
                    <p><strong>Date:</strong> {payment.completed_at.strftime('%d %B %Y, %I:%M %p')}</p>
                </div>
                """
            return '<em>No refund payment details collected yet</em>'
        except:
            return '<em>No refund payment details collected yet</em>'
    payment_details_display.short_description = 'Payment Details'
    payment_details_display.allow_tags = True
    
    def get_readonly_fields(self, request, obj=None):
        """Make assigned_to readonly as it's auto-assigned"""
        if obj and obj.assigned_to:
            return self.readonly_fields
        return ('created_at', 'updated_at', 'picked_up_at', 'payment_details_display')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order', 'payment_type', 'payment_method', 'amount', 'status', 'collected_by', 'created_at')
    list_filter = ('payment_type', 'payment_method', 'status', 'created_at')
    search_fields = ('order__order_number', 'return_request__order__order_number', 'account_holder_name', 'razorpay_payment_id')
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('order', 'return_request', 'payment_type', 'payment_method', 'amount', 'status')
        }),
        ('Online Payment (Razorpay)', {
            'fields': ('razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature'),
            'classes': ('collapse',)
        }),
        ('Bank Details (COD Refunds)', {
            'fields': ('account_holder_name', 'account_number', 'ifsc_code', 'bank_name', 'upi_id'),
            'classes': ('collapse',)
        }),
        ('Collection Information', {
            'fields': ('collected_by',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Payments are only created by system/delivery partners"""
        return False

