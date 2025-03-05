from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', views.index, name='index'),
    path('test_spotify/', views.test_spotify_connection, name='test_spotify'),
    path('callback/', views.spotify_callback, name='spotify_callback'),
    path('login/', views.spotify_login, name='spotify_login'),  # Add this line for initiating Spotify login

    path("login_view/", views.login_view, name="login_view"),  # Ensure this line is present
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    
    path('add_all_songs_to_database/', views.add_all_songs_to_database, name='add_all_songs_to_database'),
    path('view_top_artists/', views.view_top_artists, name='view_top_artists'),
    path('view_top_artists/<str:time_range>/', views.view_top_artists, name='view_top_artists_time'),
    path('view_top_genres/', views.view_top_genres, name='view_top_genres'),
    path('view_top_genres/<str:time_range>/', views.view_top_genres, name='view_top_genres_time'),
    path('view_top_songs/', views.view_top_songs, name='view_top_songs'),
    path('view_top_songs/<str:time_range>/', views.view_top_songs, name='view_top_songs_time'),
    path('create_genre_playlist/', views.create_genre_playlist, name='create_genre_playlist'),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)