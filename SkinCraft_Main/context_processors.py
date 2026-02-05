from .models import Cart, Category
from django.db.models import Count, Q

def cart_count(request):
    count = 0
    try:
        if request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user).first()
        else:
            session_key = request.session.session_key
            cart = Cart.objects.filter(session_id=session_key).first()
        if cart:
            count = cart.items.count()
    except Exception:
        count = 0
        
    return {'cart_count': count}

def categories(request):
    try:
        categories = Category.objects.annotate(
            product_count=Count('product', filter=Q(product__is_active=True))
        ).all()
    except Exception:
        categories = []
    return {'categories': categories}
