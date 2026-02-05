from django.contrib import admin
from django.urls import path,include
from SkinCraft_Main import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin_dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('', views.homepage, name='homepage'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('profile/', views.profile_view, name='profile'),
    path('ayurveda/', views.ayurveda_view, name='ayurveda'),
    path('contact/', views.contact, name='contact'),
    path('faq/', views.faq_view, name='faq'),
    path('about/', views.about_view, name='about'),
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('shipping-policy/', views.shipping_policy, name='shipping_policy'),
    path('delivery/dashboard/', views.delivery_dashboard, name='delivery_dashboard'),
    path('delivery/order/<int:order_id>/status/', views.update_delivery_status, name='update_delivery_status'),
    path('delivery/order/<int:order_id>/send-otp/', views.send_delivery_otp, name='send_delivery_otp'),
    path('delivery/order/<int:order_id>/complete/', views.complete_delivery, name='complete_delivery'),
    path('delivery/helpdesk/submit/', views.submit_helpdesk_ticket, name='submit_helpdesk_ticket'),
    path('products/', views.product_list, name='product'),
    path('product/<int:pk>/', views.product_detail, name='product_detail'),
    path('cart/', views.cart_view, name='cart_view'),
    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/update/<int:item_id>/<str:action>/', views.update_cart_quantity, name='update_cart_quantity'),
    path('cart/delete/<int:item_id>/', views.delete_cart_item, name='delete_cart_item'),
    path('wishlist/', views.wishlist_view, name='wishlist_view'),
    path('wishlist/toggle/<int:product_id>/', views.toggle_wishlist, name='toggle_wishlist'),
    path('checkout/', views.checkout_view, name='checkout'),
    path('razorpay/create-order/', views.create_razorpay_order, name='create_razorpay_order'),
    path('process-order/', views.process_order, name='process_order'),
    path('order-success/<str:order_number>/', views.order_success, name='order_success'),
    path('payment-failed/<str:order_number>/', views.payment_failed, name='payment_failed'),
    path('razorpay/webhook/', views.razorpay_webhook, name='razorpay_webhook'),
    path('knowledge-hub/', views.knowledge_hub, name='knowledge_hub'),
    path('get-order-items/<int:order_id>/', views.get_order_items, name='get_order_items'),
    path('submit-review/', views.submit_review, name='submit_review'),
    path('submit-return/', views.submit_return, name='submit_return'),
    path('confirm-return-pickup/<int:return_id>/', views.confirm_return_pickup, name='confirm_return_pickup'),
    path('invoice/<int:order_id>/', views.invoice_view, name='invoice_view'),
    path('product/<int:product_id>/review/', views.submit_product_review, name='submit_product_review'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)