"""
URL configuration for quant_site project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from core import views

urlpatterns = [
    path('healthz/', views.healthz),
    path('', views.frontend_index),
    path('account', views.frontend_index),
    path('account/', views.frontend_index),
    path('admin/', admin.site.urls),
    path('api/auth/session/', views.auth_session),
    path('api/auth/register/', views.auth_register),
    path('api/auth/login/', views.auth_login),
    path('api/auth/logout/', views.auth_logout),
    path('api/auth/guest/', views.auth_guest),
    path('api/csrf/', views.csrf_token),
    path('api/account/summary/', views.account_summary),
    path('api/account/change-password/', views.change_password),
    path('api/account/profile/', views.account_profile),
    path('api/account/preferences/', views.account_preferences),
    path('api/account/avatar/', views.account_avatar),
    path('api/watchlist/', views.watchlist),
    path('api/watchlist/<str:code>/', views.watchlist_delete),
    path('api/ai-analysis/', views.ai_analysis),
    path('api/ai-analysis/status/<str:task_id>/', views.ai_analysis_status),
    path('api/quote/<str:code>/', views.quote),
    path('api/kline/<str:code>/', views.kline),
    path('api/realtime/market-stream/<str:code>/', views.realtime_market_stream),
    path('api/markets/', views.markets),
    path('api/market-index-snapshots/', views.market_index_snapshots),
    path('api/market-leaders/<str:market>/', views.market_leaders),
    path('api/symbols/<str:market>/', views.symbols),
    path('api/indicators/', views.indicators),
    path('api/indicator-render/<str:code>/<str:symbol>/', views.indicator_render),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
