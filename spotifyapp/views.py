import random
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import UserCreationForm
from django.views.decorators.csrf import csrf_exempt
import environ
import os
import requests
import logging
from myspotifyproject.settings import BASE_DIR
from .models import Song, ListeningHistory
from django.db.models import Avg, Count
import time
from django.conf import settings
from django.contrib.auth.decorators import login_required
import time



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
            token_info = sp.refresh_access_token(token_info['refresh_token'])
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
            return render(request, "spotifyapp/index.html")
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
            return redirect("login_view")
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
@login_required
def view_top_genres(request):
    user = request.user
    user_songs = Song.objects.filter(users=user)

    # Build a dictionary of genre counts
    genres = {}
    for song in user_songs:
        for genre in song.genres.split(', '):
            genre = genre.strip()
            if genre:
                genres[genre] = genres.get(genre, 0) + 1

    # Sort genres by count (most listened first)
    sorted_genres = sorted(genres.items(), key=lambda item: item[1], reverse=True)

    genre_list = []
    for i, (genre, count) in enumerate(sorted_genres):
        # For each genre, fetch up to 4 distinct album art images as a stand-in for artist images.
        # We're filtering songs that have the genre in their genres field.
        songs_in_genre = user_songs.filter(genres__icontains=genre).exclude(album_art__isnull=True).exclude(album_art__exact='')
        images = list(songs_in_genre.values_list('album_art', flat=True).distinct()[:4])
        genre_list.append((i + 1, genre, count, images))

    # Paginate results (50 genres per page)
    paginator = Paginator(genre_list, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'spotifyapp/view_top_genres.html', {'genres': page_obj})

#Function that will add all songs that are in your library to the database, for easier use later
@login_required
def add_all_songs_to_database(request):
    try:
        # Initialize variables to track pagination
        all_tracks = []
        offset = 0
        limit = 50
        
        # Fetch all tracks from playlists
        while True:
            playlists = sp.current_user_playlists(offset=offset, limit=limit)
            if not playlists.get('items', []):
                return HttpResponse("No playlists found for this user.")
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

@login_required
def view_last_50_listens(request):
    try:
        user = request.user
        # Fetch the last 50 recently played tracks from Spotify
        recent_items = sp.current_user_recently_played(limit=50).get('items', [])
        
        songs = []
        for i, item in enumerate(recent_items):
            # Each item from recently played has a 'track' key.
            track = item.get('track')
            if not track:
                continue

            # Save or update the song in the database
            song = get_or_create_song(track, user)
            
            if song:
                # Record the listening event (if you wish to record every fetch)
                ListeningHistory.objects.create(user=user, song=song)
                
                songs.append({
                    'index': i + 1,
                    'track_name': song.track_name,
                    'artist_names': song.artist_names,
                    'album_art': song.album_art,
                    'popularity': song.popularity,
                })
        
        return render(request, 'spotifyapp/view_last_50_songs.html', {
            'songs': songs,
            'time_range': 'Recent Listens'
        })
    except Exception as e:
        logger.error(f"Error in view_last_50_listens: {e}")
        return render(request, 'spotifyapp/view_last_50_songs.html', {
            'songs': []
        })

@login_required
def view_top_songs(request, time_range='short_term'):
    try:
        # Fetch the current user's top tracks from Spotify
        top_tracks = sp.current_user_top_tracks(limit=50, time_range=time_range).get('items', [])
        if not top_tracks:
            logger.warning("No top tracks found.")
            return render(request, 'spotifyapp/view_top_songs.html', {'songs': [], 'time_range': time_range})

        songs = []
        user = request.user  # This is the currently logged in user
        
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
        # Retrieve and convert the number of songs; default to 50 if conversion fails.
        try:
            num_songs = int(request.POST.get('num_songs', 50))
        except ValueError:
            num_songs = 50

        logger.debug("Debug message: 1")
        user_track_ids = get_all_user_tracks()

        genre_tracks = []
        offset = 0
        logger.debug("Debug message: 2")
        # Use the num_songs value instead of hardcoding 50
        while len(genre_tracks) < num_songs and offset < 1000:  # Limit search to first 1000 tracks
            results = sp.search(q=f'genre:"{genre}"', type='track', limit=50, offset=offset)
            logger.debug("Debug message: 3")
            tracks = results['tracks']['items']
            for track in tracks:
                logger.debug("Debug message: 4")
                if track['id'] not in user_track_ids:
                    genre_tracks.append(track)
                    get_or_create_song(track, user)
                logger.debug("Debug message: 5")
                if len(genre_tracks) >= num_songs:
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
            # Add up to num_songs tracks instead of 50
            add_tracks_to_playlist(new_playlist_id, genre_track_ids[:num_songs])
            return redirect('index')
        else:
            return HttpResponse("Failed to create playlist.")

    return render(request, 'spotifyapp/view_top_genres.html')

#Function that will get the recently played tracks
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

def combine_candidates(candidates):
    """Given a dict mapping track_id to a score, return a sorted list of track_ids."""
    sorted_items = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
    return [track_id for track_id, score in sorted_items]

@login_required
def get_recommendations(request):
    if request.method == "POST":
        try:
            # Retrieve the weights from the form
            weight_genres   = int(request.POST.get("weight_genres", 25))
            weight_artists  = int(request.POST.get("weight_artists", 25))
                        
            # Optional fields
            year_filter = request.POST.get("year_filter", "").strip()  # e.g. "1990" or "1990-2000"
            hipster_mode = request.POST.get("hipster_mode", "off") == "on"
            
            # Prepare a field filter string (for Spotify search queries)
            year_query = f' year:{year_filter}' if year_filter else ''
            
            # Dictionary to accumulate candidate track scores
            candidate_scores = {}

            # 2. Top Genres
            # Use your stored songs to get user’s top genres (similar to view_top_genres)
            user_songs = Song.objects.filter(users=request.user)
            genres = {}
            for song in user_songs:
                for genre in song.genres.split(', '):
                    g = genre.strip()
                    if g:
                        genres[g] = genres.get(g, 0) + 1
            sorted_genres = sorted(genres.items(), key=lambda item: item[1], reverse=True)
            top_genres = [genre for genre, count in sorted_genres[:10]]  # top 10 genres

            for genre in top_genres:
                # Build a search query for the genre
                query = f'genre:"{genre}"{year_query}'
                if hipster_mode:
                    # In hipster mode, search for albums with tag:hipster
                    query = f'tag:hipster album:"{genre}"{year_query}'
                    # Search albums then pull tracks from album
                    albums = sp.search(q=query, type='album', limit=5).get('albums', {}).get('items', [])
                    for album in albums:
                        album_id = album.get('id')
                        album_tracks = sp.album_tracks(album_id).get('items', [])
                        for track in album_tracks:
                            track_id = track.get('id')
                            candidate_scores[track_id] = candidate_scores.get(track_id, 0) + weight_genres
                else:
                    # Normal search: search for tracks based on genre
                    results = sp.search(q=query, type='track', limit=5)
                    for track in results.get('tracks', {}).get('items', []):
                        track_id = track.get('id')
                        candidate_scores[track_id] = candidate_scores.get(track_id, 0) + weight_genres

            # 3. Top Artists
            # Use top artists to search tracks normally (with year filter if provided)
            top_artists = sp.current_user_top_artists(limit=20, time_range='medium_term').get('items', [])
            for artist in top_artists:
                artist_name = artist.get('name')
                # Build a search query: artist and optionally year
                query = f'artist:"{artist_name}"{year_query}'
                # In hipster mode, search for albums with tag:hipster
                if hipster_mode:
                    query = f'tag:hipster album:"{artist_name}"{year_query}'
                    albums = sp.search(q=query, type='album', limit=5).get('albums', {}).get('items', [])
                    for album in albums:
                        album_tracks = sp.album_tracks(album.get('id')).get('items', [])
                        for track in album_tracks:
                            track_id = track.get('id')
                            candidate_scores[track_id] = candidate_scores.get(track_id, 0) + weight_artists
                else:
                    results = sp.search(q=query, type='track', limit=5)
                    for track in results.get('tracks', {}).get('items', []):
                        track_id = track.get('id')
                        candidate_scores[track_id] = candidate_scores.get(track_id, 0) + weight_artists

            # Combine candidates sorted by their weighted scores
            recommended_track_ids = combine_candidates(candidate_scores)

            # Fetch detailed info for top recommendations and store/update in DB
            recommended_tracks = []
            for i, track_id in enumerate(combine_candidates(candidate_scores)):
                # Only consider this track if it isn't already in the user's library.
                if Song.objects.filter(track_id=track_id, users=request.user).exists():
                    continue

                try:
                    track = sp.track(track_id)
                    # Save (or update) the track in the database and associate with the user.
                    song_obj = get_or_create_song(track, request.user)
                    if song_obj:
                        recommended_tracks.append({
                            'index': len(recommended_tracks) + 1,
                            'track_name': song_obj.track_name,
                            'artist_names': song_obj.artist_names,
                            'album_art': song_obj.album_art,
                            'popularity': song_obj.popularity,
                        })
                except Exception as e:
                    logger.error(f"Error fetching details for track {track_id}: {e}")
                    continue

                # Stop once we have 20 recommendations.
                if len(recommended_tracks) >= 20:
                    break

            return render(request, 'spotifyapp/recommendations_result.html', {
                'tracks': recommended_tracks,
            })

        except Exception as e:
            logger.error(f"Error in recommendation algorithm: {e}")
            return render(request, 'spotifyapp/recommendations_result.html', {'tracks': []})
    else:
        return render(request, 'spotifyapp/recommendations.html')
    
@login_required
@csrf_exempt  # if using AJAX and you handle CSRF via JS; otherwise, ensure your request sends CSRF token
def like_track(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            track_id = data.get("track_id")
            if not track_id:
                return JsonResponse({"error": "No track_id provided."}, status=400)

            # Use the Spotipy client (ensure you have a valid access token from session or elsewhere)
            # Here we assume `sp` is a globally available authenticated Spotipy client
            result = sp.current_user_saved_tracks_add([track_id])
            # Optionally, update your database as well. For example, you might want to record that the user "liked" it.
            return JsonResponse({"success": True})
        except Exception as e:
            logger.error(f"Error liking track: {e}")
            return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"error": "Invalid request method."}, status=405)