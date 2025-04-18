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
        redirect_uri=env('SPOTIPY_REDIRECT_URI'),
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

@csrf_exempt
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
        songs_with_art = user_songs.filter(
            album_art__isnull=False
        ).exclude(album_art__exact='').order_by('-popularity')

        seen_artists = set()
        seen_album_arts = set()
        unique_images = []
        unique_artists = []

        def process_song(song, exact=True):
            song_genres = [g.strip() for g in song.genres.split(',') if g.strip()]
            if not song_genres:
                return False

            first_genre = song_genres[0].lower()
            if exact and first_genre != genre.lower():
                return False
            if not exact and genre.lower() not in [g.lower() for g in song_genres]:
                return False

            if not song.artist_names:
                return False
            if song.artist_names.startswith("Tyler, The Creator"):
                artist = "Tyler, The Creator"
            else:
                artist = song.artist_names.split(',')[0].strip()

            album_art = song.album_art.strip()
            if not album_art or album_art in seen_album_arts or artist in seen_artists:
                return False

            unique_images.append(album_art)
            unique_artists.append(artist)
            seen_artists.add(artist)
            seen_album_arts.add(album_art)
            return True

        # First pass
        for song in songs_with_art:
            if len(unique_images) >= 4:
                break
            process_song(song, exact=True)

        # Second pass
        if len(unique_images) < 4:
            for song in songs_with_art:
                if len(unique_images) >= 4:
                    break
                process_song(song, exact=False)

        # Fallback to Spotify if needed
        if len(unique_images) < 4:
            try:
                results = sp.search(q=f'genre:"{genre}"', type='track', limit=20)
                for item in results['tracks']['items']:
                    track_id = item['id']
                    track_name = item['name']
                    popularity = item['popularity']
                    album_art = item['album']['images'][0]['url'] if item['album']['images'] else None
                    genres_list = [genre]  # You can’t get genre from track in Spotify API directly

                    artist_names_list = [artist['name'] for artist in item['artists']]
                    if artist_names_list[0] == "Tyler, The Creator":
                        display_artist = "Tyler, The Creator"
                    else:
                        display_artist = artist_names_list[0].split(',')[0].strip()

                    if album_art and album_art not in seen_album_arts and display_artist not in seen_artists:
                        unique_images.append(album_art)
                        unique_artists.append(display_artist)
                        seen_artists.add(display_artist)
                        seen_album_arts.add(album_art)

                        # Check if song exists
                        if not Song.objects.filter(track_id=track_id).exists():
                            Song.objects.create(
                                track_id=track_id,
                                track_name=track_name,
                                artist_names=", ".join(artist_names_list),
                                album_art=album_art,
                                genres=", ".join(genres_list),
                                popularity=popularity
                                # users left blank
                            )

                    if len(unique_images) >= 4:
                        break
            except Exception as e:
                print(f"Spotify fallback failed for genre {genre}: {e}")

        while len(unique_images) < 4:
            unique_images.append("https://via.placeholder.com/150?text=No+Image")
            unique_artists.append("Unknown Artist")

        genre_list.append((i + 1, genre, count, unique_images, unique_artists))

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

#        user_track_ids = get_all_user_tracks()

        genre_tracks = []
        offset = 0
        # Use the num_songs value instead of hardcoding 50
        while len(genre_tracks) < num_songs and offset < 500:  # Limit search to first 500 tracks
            results = sp.search(q=f'genre:"{genre}"', type='track', limit=50, offset=offset)
            tracks = results['tracks']['items']
            for track in tracks:
                track_id = track['id']
                if Song.objects.filter(track_id=track_id, users=request.user).exists():
                    continue                    
                genre_tracks.append(track)
                if len(genre_tracks) >= num_songs:
                    break
            offset += 50

        if not genre_tracks:
            # Handle case where no tracks were found for the genre
            print(f"No tracks found for genre: {genre}")
            return HttpResponse("No tracks found for the specified genre.")

        genre_track_ids = [track['id'] for track in genre_tracks]
        random.shuffle(genre_track_ids)
        playlist_name = f"{genre} Playlist"
        new_playlist_id = create_playlist(playlist_name)
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
            weight_genres   = int(request.POST.get("weight_genres", 25))
            weight_artists  = int(request.POST.get("weight_artists", 25))
            num_songs       = int(request.POST.get("num_songs", 20))
            playlist_name   = request.POST.get("playlist_name", "Recommended Playlist")

            year_filter = request.POST.get("year_filter", "").strip()
            hipster_mode = request.POST.get("hipster_mode", "off") == "on"
            year_query = f' year:{year_filter}' if year_filter else ''

            candidate_scores = {}

            # 1. User's Songs and Top Genres
            user_songs = Song.objects.filter(users=request.user)
            genres = {}
            for song in user_songs:
                for genre in song.genres.split(', '):
                    g = genre.strip()
                    if g:
                        genres[g] = genres.get(g, 0) + 1
            sorted_genres = sorted(genres.items(), key=lambda item: item[1], reverse=True)
            top_genres = [genre for genre, count in sorted_genres[:30]]

            for genre in top_genres:
                query = f'genre:"{genre}"{year_query}'
                if hipster_mode:
                    query = f'tag:hipster album:"{genre}"{year_query}'
                    albums = sp.search(q=query, type='album', limit=20).get('albums', {}).get('items', [])
                    for album in albums:
                        tracks = sp.album_tracks(album.get('id')).get('items', [])
                        for track in tracks:
                            track_id = track.get('id')
                            candidate_scores[track_id] = candidate_scores.get(track_id, 0) + weight_genres
                else:
                    results = sp.search(q=query, type='track', limit=20)
                    for track in results.get('tracks', {}).get('items', []):
                        track_id = track.get('id')
                        candidate_scores[track_id] = candidate_scores.get(track_id, 0) + weight_genres

            # 2. Top Artists
            top_artists = sp.current_user_top_artists(limit=30, time_range='medium_term').get('items', [])
            for artist in top_artists:
                artist_name = artist.get('name')
                query = f'artist:"{artist_name}"{year_query}'
                if hipster_mode:
                    query = f'tag:hipster album:"{artist_name}"{year_query}'
                    albums = sp.search(q=query, type='album', limit=10).get('albums', {}).get('items', [])
                    for album in albums:
                        tracks = sp.album_tracks(album.get('id')).get('items', [])
                        for track in tracks:
                            track_id = track.get('id')
                            candidate_scores[track_id] = candidate_scores.get(track_id, 0) + weight_artists
                else:
                    results = sp.search(q=query, type='track', limit=10)
                    for track in results.get('tracks', {}).get('items', []):
                        track_id = track.get('id')
                        candidate_scores[track_id] = candidate_scores.get(track_id, 0) + weight_artists

            # Combine and sort candidates
            recommended_track_ids = combine_candidates(candidate_scores)

            # Filter out tracks already in the user's library
            overfetch = num_songs * 10  # Overfetch to ensure we get enough unique tracks to add to a playlist
            filtered_track_ids = []
            for track_id in recommended_track_ids[:overfetch]:
                if not Song.objects.filter(track_id=track_id, users=request.user).exists():
                    filtered_track_ids.append(track_id)
                if len(filtered_track_ids) >= num_songs:
                    break

            recommended_tracks = []

            for idx, track_id in enumerate(filtered_track_ids):
                try:
                    track = sp.track(track_id)
                    song_obj = get_or_create_song(track, request.user)
                    if song_obj:
                        recommended_tracks.append({
                            'index': idx + 1,
                            'track_name': song_obj.track_name,
                            'artist_names': song_obj.artist_names,
                            'album_art': song_obj.album_art,
                            'popularity': song_obj.popularity,
                        })
                except Exception as e:
                    logger.error(f"Error fetching details for track {track_id}: {e}")
                    continue

                if len(recommended_tracks) >= num_songs:
                    break

            # Create the playlist and add songs only if we have some
            if filtered_track_ids:
                new_playlist_id = create_playlist(playlist_name)
                if new_playlist_id:
                    logger.debug(f"Adding {len(filtered_track_ids[:num_songs])} tracks to playlist {new_playlist_id}")
                    add_tracks_to_playlist(new_playlist_id, filtered_track_ids[:num_songs])
                else:
                    logger.warning("Playlist creation failed.")
                    return HttpResponse("Failed to create playlist.")
            else:
                logger.warning("No valid recommended tracks to add to playlist.")

            # Render results
            return render(request, 'spotifyapp/recommendations_result.html', {
                'tracks': recommended_tracks,
            })

        except Exception as e:
            logger.error(f"Error in recommendation algorithm: {e}")
            return render(request, 'spotifyapp/recommendations_result.html', {'tracks': []})

    return render(request, 'spotifyapp/recommendations.html')
