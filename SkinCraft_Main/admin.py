from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib import messages
from django.utils import timezone
from .models import *

admin.site.register(Category)
admin.site.register(SubCategory)
admin.site.register(ProductTag)
admin.site.register(ProductVariant)
admin.site.register(Wishlist)
admin.site.register(Address)

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

    def _has_order_history(self, obj):
        return obj.orderitem_set.exists()

    def has_delete_permission(self, request, obj=None):
        has_perm = super().has_delete_permission(request, obj)
        if not has_perm:
            return False
        if obj is None:
            return True
        return not self._has_order_history(obj)

    def delete_model(self, request, obj):
        if self._has_order_history(obj):
            self.message_user(
                request,
                "This product cannot be deleted because customers have already ordered it. Disable it instead.",
                level=messages.ERROR,
            )
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        blocked = queryset.filter(orderitem__isnull=False).distinct()
        allowed = queryset.exclude(id__in=blocked.values('id'))

        if blocked.exists():
            self.message_user(
                request,
                f"{blocked.count()} product(s) were not deleted because customers already ordered them.",
                level=messages.WARNING,
            )
        if allowed.exists():
            super().delete_queryset(request, allowed)

@admin.register(BankDetails)
class BankDetailsAdmin(admin.ModelAdmin):
    list_display = ('user', 'account_holder_name', 'bank_name', 'account_number', 'ifsc_code', 'upi_id', 'updated_at')
    search_fields = ('user__username', 'user__email', 'account_holder_name', 'account_number', 'ifsc_code', 'bank_name', 'upi_id')
    readonly_fields = ('updated_at',)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'user', 'status', 'cancel_reason', 'payment_status', 'assigned_to', 'total_amount', 'created_at')
    list_filter = ('status', 'payment_status', 'created_at')
    search_fields = ('order_number', 'user__username', 'email', 'phone')
    readonly_fields = ('order_number', 'created_at', 'delivered_at')
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order_number', 'user', 'total_amount', 'created_at')
        }),
        ('Status', {
            'fields': ('status', 'cancel_reason', 'payment_status', 'assigned_to')
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
@admin.register(DeliveryHelpDeskTicket)
class DeliveryHelpDeskTicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'reason', 'status', 'created_at', 'replied_at')
    list_filter = ('status', 'reason', 'created_at')
    search_fields = ('user__username', 'user__email', 'remarks', 'admin_reply')
    readonly_fields = ('created_at', 'replied_at', 'replied_by')
    fields = ('user', 'reason', 'remarks', 'status', 'admin_reply', 'replied_at', 'replied_by', 'created_at')

    def save_model(self, request, obj, form, change):
        if obj.admin_reply and not obj.replied_at:
            obj.replied_at = timezone.now()
            obj.replied_by = request.user
            if obj.status == 'Open':
                obj.status = 'Resolved'
        super().save_model(request, obj, form, change)
admin.site.register(Coupon)

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
        refund = getattr(obj, 'refund_record', None)
        if refund:
            return f'- {refund.status}'
        return '- No Refund'
    refund_payment_status.short_description = 'Refund Status'
    
    def payment_details_display(self, obj):
        """Display collected payment details"""
        refund = getattr(obj, 'refund_record', None)
        if refund:
            return f"""
            <div style="background: #f0f0f0; padding: 15px; border-radius: 5px;">
                <p><strong>Status:</strong> {refund.get_status_display()}</p>
                <p><strong>Amount:</strong> &#8377;{refund.amount}</p>
                <p><strong>Processed At:</strong> {refund.processed_at or '-'} </p>
                <p><strong>Notes:</strong> {refund.notes or '-'} </p>
            </div>
            """
        return '<em>No refund record yet</em>'
    payment_details_display.short_description = 'Payment Details'
    payment_details_display.allow_tags = True
    
    def get_readonly_fields(self, request, obj=None):
        """Make assigned_to readonly as it's auto-assigned"""
        if obj and obj.assigned_to:
            return self.readonly_fields
        return ('created_at', 'updated_at', 'picked_up_at', 'payment_details_display')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order', 'payment_method', 'amount', 'status', 'created_at')
    list_filter = ('payment_method', 'status', 'created_at')
    search_fields = ('order__order_number', 'razorpay_payment_id')
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('order', 'payment_method', 'amount', 'status')
        }),
        ('Online Payment (Razorpay)', {
            'fields': ('razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature'),
            'classes': ('collapse',)
        }),
                ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Payments are only created by system/delivery partners"""
        return False

@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'return_request', 'amount', 'damage_amount', 'status', 'processed_by', 'processed_at')
    list_filter = ('status', 'processed_at', 'created_at')
    search_fields = ('order__order_number', 'return_request__order__order_number', 'processed_by__username')
    readonly_fields = ('created_at', 'processed_at')

    fieldsets = (
        ('Refund Information', {
            'fields': ('order', 'return_request', 'amount', 'damage_amount', 'status')
        }),
        ('Processing', {
            'fields': ('processed_by', 'processed_at', 'notes')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

@admin.register(SalaryPayment)
class SalaryPaymentAdmin(admin.ModelAdmin):
    list_display = (
        'delivery_partner',
        'month',
        'year',
        'base_salary',
        'bonus',
        'deductions',
        'net_salary',
        'payment_mode',
        'transfer_destination',
        'status',
        'paid_at',
    )
    list_filter = ('status', 'payment_mode', 'month', 'year')
    search_fields = ('delivery_partner__username', 'delivery_partner__first_name', 'delivery_partner__last_name')
    readonly_fields = (
        'created_at',
        'paid_at',
        'paid_by',
        'transfer_destination',
        'transfer_account_holder_name',
        'transfer_account_last4',
        'transfer_ifsc_code',
        'transfer_bank_name',
        'transfer_upi_id',
    )

    def transfer_destination(self, obj):
        return obj.get_transfer_destination_display()
    transfer_destination.short_description = 'Transfer To'

