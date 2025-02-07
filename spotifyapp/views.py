import random
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.contrib.auth import authenticate, login, logout
import environ
import os
import requests
import logging
from myspotifyproject.settings import BASE_DIR
from .models import Song
from django.db.models import Avg
import time
from django.conf import settings


#So I found out that Spotify depreciated a lot of their endpoints, so we will have to figure out new ways
#To recommend songs. They removed all of the audio features and recommendation endpoints, so we are
#starting from scratch here.

logger = logging.getLogger(__name__)

# Set the timeout value (in seconds)
TIMEOUT = 5
MAX_RETRIES = 3

# Load environment variables
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, 'secret.env'))

# Configure the Spotipy client to use a session with a timeout
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=MAX_RETRIES)
session.mount('https://', adapter)
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id= env('SPOTIPY_CLIENT_ID'),
        client_secret=env('SPOTIPY_CLIENT_SECRET'),
        redirect_uri='http://localhost:8888/callback',
        scope='playlist-modify-private playlist-modify-public user-library-read user-top-read user-read-recently-played playlist-read-private'
    ))

def spotify_callback(request):
    sp_oauth = spotipy.Spotify(auth_manager = SpotifyOAuth(
        client_id= env('SPOTIPY_CLIENT_ID'),
        client_secret=env('SPOTIPY_CLIENT_SECRET'),
        redirect_uri=settings.SPOTIPY_REDIRECT_URI,
        scope='playlist-modify-private playlist-modify-public user-library-read user-top-read user-read-recently-played'
    ))

    code = request.GET.get('code')
    if not code:
        print("No authorization code found in request.")
        return redirect('login')

    token_info = sp_oauth.get_access_token(code)

    print("DEBUG: token_info received from Spotify:", token_info)

    if token_info and 'access_token' in token_info:
        # Force session to be stored explicitly
        request.session['token_info'] = token_info
        request.session.save()  # 👈 Explicitly save session
        print("token_info successfully stored in session:", request.session['token_info'])
    else:
        print("Failed to retrieve token_info from Spotify.")

    return redirect('view_top_artists')

def spotify_login(request):
    logger.info("Spotify login requested.")
    sp_oauth = SpotifyOAuth(client_id= env('SPOTIPY_CLIENT_ID'),
                            client_secret=env('SPOTIPY_CLIENT_SECRET'),
                            redirect_uri='http://localhost:8888/callback',
                            scope='playlist-modify-private playlist-modify-public user-library-read user-top-read user-read-recently-played')
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

def get_spotify_client(request):
    logger.info("Checking for Spotify client in session...")

    # Debug: Log session contents
    logger.info(f"Current session contents: {dict(request.session.items())}")

    token_info = request.session.get('token_info', None)
    if not token_info:
        logger.warning("No token info found in session.")
        return None

    # Refresh the token if it's expired
    if token_info['expires_at'] - time.time() < 60:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id= env('SPOTIPY_CLIENT_ID'),
                client_secret=env('SPOTIPY_CLIENT_SECRET'),
                redirect_uri='http://localhost:8888/callback'))
        try:
            logger.info("Refreshing expired token...")
            token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
            request.session['token_info'] = token_info
            request.session.modified = True
            logger.info("Token refreshed successfully!")
        except SpotifyOauthError as e:
            logger.error(f"Error refreshing token: {e}")
            return redirect('spotify_login')

    logger.info(f"Using access token: {token_info['access_token']}")
    return spotipy.Spotify(auth=token_info['access_token'])

def test_spotify_connection(request):
    logger.info("Testing Spotify connection...")

    sp = get_spotify_client(request)
    if sp is None:
        logger.warning("No Spotify client found, redirecting to login.")
        return redirect('spotify_login')  

    try:
        user_profile = sp.current_user()
        logger.info(f"Successfully retrieved user profile: {user_profile}")
        return JsonResponse(user_profile)
    except spotipy.exceptions.SpotifyException as e:
        logger.error(f"Error connecting to Spotify API: {e}")
        return HttpResponse(f"Error connecting to Spotify API: {e}", status=500)

def login_view(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        logger.info(f"Login attempt for user: {username}")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            logger.info(f"User {username} successfully logged in.")
            return render(request, "spotifyapp/dashboard.html")
        else:
            logger.warning("Invalid login attempt.")
            return HttpResponse("Invalid username or password")
    return render(request, "spotifyapp/login.html")

def logout_view(request):
    logger.info("User logged out.")
    logout(request)
    return redirect("login")

def register_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            logger.info(f"New user registered: {user.username}")
            return redirect("login")
        else:
            logger.warning("User registration failed due to invalid form data.")
    else:
        form = UserCreationForm()
    return render(request, "spotifyapp/register.html", {"form": form})

#Function that will get the playlist id from the link
def extract_playlist_id(playlist_link):
    try:
        playlist_id = playlist_link.split('/')[-1].split('?')[0]
        if not playlist_id:
            raise ValueError("Extracted playlist ID is empty.")
        return playlist_id
    except Exception as e:
        logger.error(f"Error extracting playlist ID: {e}")
        return None

#Function that will add a track to my database, so that I don't have to rely as heavily on API calls
def get_or_create_song(track, user):
    try:
        track_id = track.get('id')
        if not track_id:
            logger.warning("Track ID is missing.")
            return None

        # Check if the song already exists
        song, created = Song.objects.get_or_create(track_id=track_id)

        if created:
            # Populate song fields with available track data
            song.track_name = track.get('name', 'Unknown')
            song.artist_names = ', '.join([artist.get('name', 'Unknown') for artist in track.get('artists', [])])
            song.album_art = track.get('album', {}).get('images', [{}])[0].get('url', '')
            song.popularity = track.get('popularity')
            song.release_date = track.get('album', {}).get('release_date', 'Unknown')
            
            logger.info(f"Audio features are deprecated, storing only available metadata for {track_id}.")
            
            # Fetch and save genres
            genres = []
            for artist in track.get('artists', []):
                artist_id = artist.get('id')
                if artist_id:
                    try:
                        artist_info = sp.artist(artist_id)
                        genres.extend(artist_info.get('genres', []))
                    except Exception as e:
                        logger.warning(f"Failed to fetch genres for artist {artist_id}: {e}")
            song.genres = ', '.join(genres)
            
            # Save the song to the database
            song.save()

        # Associate the user with this song if not already associated
        if not song.users.filter(id=user.id).exists():
            song.users.add(user)
            song.save()
            logger.info(f"User {user.username} added song {track_id} to their list.")

        return song
    except Exception as e:
        logger.error(f"Error in get_or_create_song: {e}")
        return None

#Function that will show you your top artists
def view_top_artists(request, time_range='short_term'):
    top_artists = sp.current_user_top_artists(limit=50, time_range=time_range)['items']

    artists = []
    #Adds all desired info to each artist
    for i, artist in enumerate(top_artists):
        artist_name = artist.get('name', 'Unknown')
        artist_photo = artist['images'][0]['url'] if artist.get('images') else ''
        popularity = artist.get('popularity', 0)
        artists.append((i + 1, artist_name, artist_photo, popularity))

    return render(request, 'spotifyapp/view_top_artists.html', {'artists': artists, 'time_range': time_range})

#Function that will show you your top genres, Later I plan to add some artists images into each genre as well
def view_top_genres(request):
    user = request.user
    user_songs = Song.objects.filter(users=user)  # Get saved songs

    genres = {}
    for song in user_songs:
        for genre in song.genres.split(', '):  # Handle multiple genres
            if genre.strip():
                genres[genre] = genres.get(genre, 0) + 1

    sorted_genres = sorted(genres.items(), key=lambda item: item[1], reverse=True)
    genre_list = [(i + 1, genre, count) for i, (genre, count) in enumerate(sorted_genres)]

    # Paginate results (50 genres per page)
    paginator = Paginator(genre_list, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'spotifyapp/view_top_genres.html', {'genres': page_obj})

#Function that will add all songs that are in your library to the database, for easier use later
def add_all_songs_to_database(request):
    try:
        # Initialize variables to track pagination
        all_tracks = []
        offset = 0
        limit = 50
        
        # Fetch all tracks from playlists
        while True:
            playlists = sp.current_user_playlists(offset=offset, limit=limit)
            for playlist in playlists['items']:
                results = sp.playlist_tracks(playlist['id'], limit=100)
                for item in results['items']:
                    track = item.get('track')
                    if track and track.get('id'):
                        all_tracks.append(track)
            if not playlists['next']:
                break
            offset += limit

        # Fetch all liked songs
        offset = 0
        while True:
            liked_tracks = sp.current_user_saved_tracks(offset=offset, limit=limit)
            for item in liked_tracks['items']:
                track = item['track']
                if track and track.get('id'):
                    all_tracks.append(track)
            if not liked_tracks['next']:
                break
            offset += limit

        # Add all tracks to the database
        user = request.user
        for track in all_tracks:
            get_or_create_song(track, user)

        return HttpResponse(f"Added {len(all_tracks)} songs to the database.")
    except Exception as e:
        logger.error(f"Error adding songs to database: {e}")
        return HttpResponse("Failed to add songs to the database.")

#Function that allows you to view your top songs
def view_top_songs(request, time_range='short_term'):
    try:
        top_tracks = sp.current_user_top_tracks(limit=50, time_range=time_range).get('items', [])
        if not top_tracks:
            logger.warning("No top tracks found.")
            return render(request, 'spotifyapp/view_top_songs.html', {'songs': [], 'time_range': time_range})

        songs = []
        user = request.user
        
        for i, track in enumerate(top_tracks):
            song = get_or_create_song(track, user)
            if song:
                songs.append({
                    'index': i + 1,
                    'track_name': song.track_name,
                    'artist_names': song.artist_names,
                    'album_art': song.album_art,
                    'popularity': song.popularity,
                })

        return render(request, 'spotifyapp/view_top_songs.html', {'songs': songs, 'time_range': time_range})
    except Exception as e:
        logger.error(f"Error in view_top_songs: {e}")
        return render(request, 'spotifyapp/view_top_songs.html', {'songs': [], 'time_range': time_range})

#Function that gets all user tracks (Mostly used to make sure that songs added to new playlists don't already
#exist in your library somewhere, goal it to add all new tracks.
def get_all_user_tracks():
    user_tracks = []
    playlists = sp.current_user_playlists()

    for playlist in playlists['items']:
        results = sp.playlist_tracks(playlist['id'])
        for item in results['items']:
            track = item.get('track')
            if track and track.get('id') and not track.get('is_local'):
                user_tracks.append(track['id'])  # Store only the track ID

    # Fetch liked songs and add their IDs to user_tracks
    results = sp.current_user_saved_tracks(limit=50)
    while results:
        for item in results['items']:
            track = item['track']
            if track and track.get('id') and not track.get('is_local'):
                user_tracks.append(track['id'])
        results = sp.next(results) if results['next'] else None

    return user_tracks

def create_playlist(name):
    try:
        playlist = sp.user_playlist_create(sp.current_user()['id'], name, public=False)
        return playlist['id']
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify API Error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating playlist: {e}")
        return None

def add_tracks_to_playlist(playlist_id, track_ids):
    try:
        sp.playlist_add_items(playlist_id, track_ids)
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify API Error: {e}")
    except Exception as e:
        logger.error(f"Error adding tracks to playlist: {e}")

def create_genre_playlist(request):
    user = request.user
    if request.method == 'POST':
        genre = request.POST.get('explore_a_genre')
        logger.debug("Debug message: 1")
        user_track_ids = get_all_user_tracks()

        genre_tracks = []
        offset = 0
        logger.debug("Debug message: 2")
        while len(genre_tracks) < 50 and offset < 1000:  # Limit search to first 1000 tracks
            results = sp.search(q=f'genre:"{genre}"', type='track', limit=50, offset=offset)
            logger.debug("Debug message: 3")
            tracks = results['tracks']['items']
            for track in tracks:
                logger.debug("Debug message: 4")
                if track['id'] not in user_track_ids:
                    genre_tracks.append(track)
                    get_or_create_song(track, user)
                logger.debug("Debug message: 5")
                if len(genre_tracks) >= 50:
                    break
            offset += 50

        if not genre_tracks:
            # Handle case where no tracks were found for the genre
            print(f"No tracks found for genre: {genre}")
            return HttpResponse("No tracks found for the specified genre.")

        logger.debug("Debug message: 6")
        genre_track_ids = [track['id'] for track in genre_tracks]
        random.shuffle(genre_track_ids)
        logger.debug("Debug message: 7")
        playlist_name = f"{genre} Playlist"
        new_playlist_id = create_playlist(playlist_name)
        logger.debug("Debug message: 8")
        if new_playlist_id:
            add_tracks_to_playlist(new_playlist_id, genre_track_ids[:50])  # Add up to 50 tracks
            return redirect('index')
        else:
            return HttpResponse("Failed to create playlist.")

    return render(request, 'spotifyapp/view_top_genres.html')
    
def get_recently_played_tracks():
    try:
        results = sp.current_user_recently_played(limit=50)
        tracks = results['items']
        while results['next']:
            results = sp.next(results)
            tracks.extend(results['items'])

        # Store or update recently played tracks in the database
        for item in tracks:
            track = item['track']
            if track is not None:
                get_or_create_song(track)

        return tracks
    except spotipy.SpotifyException as e:
        print(f"Spotify API Error: {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return []
    except Exception as e:
        print(f"Error fetching recently played tracks: {e}")
        return []

def index(request):
    return render(request, 'spotifyapp/index.html')