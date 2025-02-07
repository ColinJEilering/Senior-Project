import random
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
import environ
import os
import requests
import logging
import sqlite3
from django.contrib.auth.forms import UserCreationForm
from myspotifyproject.settings import BASE_DIR
from .models import Song
from django.db.models import Avg
import time
from django.conf import settings


#This started as me wanting to create recommendation playlists, but as I started to dive into this, I decided
#that I should start to flesh it out into a website/app that others can use. This has been a learning experience
#more than anything. I have taught myself html, css, and some javascript during this process. I also had to learn
#how to code with spotify API which is a challenge in itself. 

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
        print("❌ No authorization code found in request.")
        return redirect('login')

    token_info = sp_oauth.get_access_token(code)

    print("🔍 DEBUG: token_info received from Spotify:", token_info)

    if token_info and 'access_token' in token_info:
        # Force session to be stored explicitly
        request.session['token_info'] = token_info
        request.session.save()  # 👈 Explicitly save session
        print("✅ token_info successfully stored in session:", request.session['token_info'])
    else:
        print("❌ Failed to retrieve token_info from Spotify.")

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
    logger.info("📢 Checking for Spotify client in session...")

    # Debug: Log session contents
    logger.info(f"📦 Current session contents: {dict(request.session.items())}")

    token_info = request.session.get('token_info', None)
    if not token_info:
        logger.warning("❌ No token info found in session.")
        return None

    # Refresh the token if it's expired
    if token_info['expires_at'] - time.time() < 60:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id= env('SPOTIPY_CLIENT_ID'),
                client_secret=env('SPOTIPY_CLIENT_SECRET'),
                redirect_uri='http://localhost:8888/callback'))
        try:
            logger.info("🔄 Refreshing expired token...")
            token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
            request.session['token_info'] = token_info
            request.session.modified = True
            logger.info("✅ Token refreshed successfully!")
        except SpotifyOauthError as e:
            logger.error(f"❌ Error refreshing token: {e}")
            return redirect('spotify_login')

    logger.info(f"✅ Using access token: {token_info['access_token']}")
    return spotipy.Spotify(auth=token_info['access_token'])

def test_spotify_connection(request):
    logger.info("📢 Testing Spotify connection...")

    sp = get_spotify_client(request)
    if sp is None:
        logger.warning("❌ No Spotify client found, redirecting to login.")
        return redirect('spotify_login')  

    try:
        user_profile = sp.current_user()
        logger.info(f"✅ Successfully retrieved user profile: {user_profile}")
        return JsonResponse(user_profile)
    except spotipy.exceptions.SpotifyException as e:
        logger.error(f"❌ Error connecting to Spotify API: {e}")
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
            # Populate song fields with API data
            song.track_name = track.get('name', 'Unknown')
            song.artist_names = ', '.join([artist.get('name', 'Unknown') for artist in track.get('artists', [])])
            song.album_art = track.get('album', {}).get('images', [{}])[0].get('url', '')

            # Fetch and save the song's audio features
            features = sp.audio_features(track_id)[0]
            if features:
                song.danceability = features.get('danceability')
                song.energy = features.get('energy')
                song.valence = features.get('valence')
                song.popularity = track.get('popularity')
                song.acousticness = features.get('acousticness')
                song.instrumentalness = features.get('instrumentalness')
                song.liveness = features.get('liveness')
                song.speechiness = features.get('speechiness')
            else:
                logger.warning(f"Audio features for track {track_id} are not available.")

            # Fetch and save genres
            genres = []
            for artist in track.get('artists', []):
                artist_info = sp.artist(artist.get('id', ''))
                genres.extend(artist_info.get('genres', []))
            song.genres = ', '.join(genres)

            # Save the song to the database
            song.save()
        
        # Associate the user with this song
        if user not in song.users.all():
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
def view_top_genres(request, time_range='short_term'):
    top_artists = sp.current_user_top_artists(limit=50, time_range=time_range)['items']
    genres = {}
    for artist in top_artists:
        for genre in artist.get('genres', []):
            if genre in genres:
                genres[genre] += 1
            else:
                genres[genre] = 1
    sorted_genres = sorted(genres.items(), key=lambda item: item[1], reverse=True)
    genre_list = [(i+1, genre, count) for i, (genre, count) in enumerate(sorted_genres)]
    return render(request, 'spotifyapp/view_top_genres.html', {'genres': genre_list, 'time_range': time_range})

#Function that will calculate the user's averages for each of the following categories, excluded instrumentalness
#because a large number of songs have an instrumentalness of 0.0
def calculate_user_averages():
    averages = Song.objects.aggregate(
        avg_danceability=Avg('danceability'),
        avg_energy=Avg('energy'),
        avg_valence=Avg('valence'),
        avg_acousticness=Avg('acousticness'),
        avg_instrumentalness=Avg('instrumentalness'),
        avg_liveness=Avg('liveness'),
        avg_speechiness=Avg('speechiness'),
        avg_popularity=Avg('popularity')
    )
    return averages

#Works with calculate_user_averages to display them in a nicer way
def view_user_averages(request):
    averages = calculate_user_averages()

    # Convert to percentages and round to 2 decimal places
    context = {
        'avg_danceability': round(averages['avg_danceability'] * 100, 2),
        'avg_energy': round(averages['avg_energy'] * 100, 2),
        'avg_valence': round(averages['avg_valence'] * 100, 2),
        'avg_acousticness': round(averages['avg_acousticness'] * 100, 2),
        'avg_instrumentalness': round(averages['avg_instrumentalness'] * 100, 2),
        'avg_liveness': round(averages['avg_liveness'] * 100, 2),
        'avg_speechiness': round(averages['avg_speechiness'] * 100, 2),
        'avg_popularity': round(averages['avg_popularity'], 2)
    }

    return render(request, 'spotifyapp/view_user_averages.html', context)

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

#Function that will create a playlist that has songs that have similar attributes to your averages
def create_playlist_with_similar_attributes(request):
    if request.method == 'POST':
        playlist_name = request.POST.get('playlist_name')
        
        averages = calculate_user_averages()

        # Connect to the SQLite database
        conn = sqlite3.connect('C:/Users/nlevi/Documents/myspotifyproject/db.sqlite3')  # Use the correct path to your SQLite database
        cursor = conn.cursor()

        # Query to select a random track_id from spotifyapp_song table
        cursor.execute("SELECT track_id FROM spotifyapp_song ORDER BY RANDOM() LIMIT 1")
        seed_track = cursor.fetchone()

        conn.close()

        if seed_track:
            seed_track_id = seed_track[0]  # Get the track_id
        

        # Retrieve user track IDs from the database
        user_track_ids = get_all_user_tracks()  # Call the function to get track IDs
        num_recommendations = 100
        recommended_tracks = []

        while len(recommended_tracks) < num_recommendations:
            recommendations = sp.recommendations(
                seed_tracks=[seed_track_id],
                limit=100,
                target_danceability=averages['avg_danceability'],
                target_energy=averages['avg_energy'],
                target_valence=averages['avg_valence'],
                target_acousticness=averages['avg_acousticness'],
                target_instrumentalness=averages['avg_instrumentalness'],
                target_liveness=averages['avg_liveness'],
                target_speechiness=averages['avg_speechiness']
            )
            user = request.user
            for rec_track in recommendations['tracks']:
                rec_track_id = rec_track.get('id')
                if rec_track_id and rec_track_id not in user_track_ids and rec_track_id not in [track['id'] for track in recommended_tracks]:
                    recommended_tracks.append(rec_track)
                    get_or_create_song(rec_track, user)  # Adds song to database
                    if len(recommended_tracks) == num_recommendations:
                        break
        
        track_ids = [track['id'] for track in recommended_tracks]  # Corrected to use recommended_tracks
        new_playlist_id = create_playlist(playlist_name)
        add_tracks_to_playlist(new_playlist_id, track_ids)

        return HttpResponse(f"Playlist '{playlist_name}' created successfully with songs matching your averages!")

    return HttpResponse("Invalid request method.")
#Function that allows you to view your top songs
def view_top_songs(request, time_range='short_term'):
    top_tracks = sp.current_user_top_tracks(limit=50, time_range=time_range)['items']

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
                'energy': song.energy,
                'valence': song.valence,
                'danceability': song.danceability,
                'acousticness': song.acousticness,
                'instrumentalness': song.instrumentalness,
                'liveness': song.liveness,
                'speechiness': song.speechiness,
            })

    return render(request, 'spotifyapp/view_top_songs.html', {'songs': songs, 'time_range': time_range})

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

def create_recommendation_playlist(request):
    if request.method == 'POST':
        playlist_link = request.POST.get('playlist_link')
        num_recommendations = int(request.POST.get('num_recommendations'))
        playlist_name = request.POST.get('playlist_name')

        playlist_id = playlist_link.split('/')[-1].split('?')[0]
        user_track_ids = get_all_user_tracks()

        # Fetch tracks from the specified playlist as seed tracks
        tracks = sp.playlist_tracks(playlist_id)['items']
        track_ids = [
            track['track']['id']
            for track in tracks
            if track['track'] and track['track'].get('id') and not track['track'].get('is_local')
        ]

        if not track_ids:
            logger.error("No valid tracks found in the provided playlist.")
            return HttpResponse("No valid tracks found in the provided playlist.")

        rec_track_ids = []
        attempts = 0
        max_attempts = 25

        while len(rec_track_ids) < num_recommendations and attempts < max_attempts:
            remaining_recommendations = num_recommendations - len(rec_track_ids)

            if len(track_ids) >= 5:
                seed_tracks = random.sample(track_ids, min(5, len(track_ids)))
            else:
                seed_tracks = track_ids

            logger.error(f"Attempt {attempts + 1}: Using seed tracks: {seed_tracks}")

            recommendations = get_recommendations(seed_tracks, min(5, remaining_recommendations), user_track_ids)
            if not recommendations:
                logger.error(f"No recommendations found with seed tracks: {seed_tracks}. Attempt {attempts + 1}")
                attempts += 1
                continue

            for rec_track in recommendations:
                if rec_track['id'] not in rec_track_ids:
                    rec_track_ids.append(rec_track['id'])
                if len(rec_track_ids) >= num_recommendations:
                    break

            if len(rec_track_ids) < num_recommendations:
                attempts += 1

        if rec_track_ids:
            new_playlist_id = create_playlist(playlist_name)
            if new_playlist_id:
                add_tracks_to_playlist(new_playlist_id, rec_track_ids)
                return HttpResponse(f"Playlist '{playlist_name}' created successfully with {num_recommendations} recommendations!")
            else:
                logger.error("Error creating new playlist.")
                return HttpResponse("Error creating playlist.")
        else:
            logger.error("Unable to create playlist with the given inputs after multiple attempts.")
            return HttpResponse("Unable to create playlist with the given inputs.")

    return render(request, 'spotifyapp/create_recommendation_playlist.html')

def get_recommendations(seed_tracks, num_recommendations, user_track_ids):
    user = request.user
    try:
        recommended_tracks = []
        attempts = 0
        max_attempts = 10
        number = 0

        while len(recommended_tracks) < num_recommendations and attempts < max_attempts:
            logger.error("Point 1")

            limit = min(50, num_recommendations - len(recommended_tracks))
            logger.error("Point 2")

            if not seed_tracks:
                logger.error("Not Seed Tracks")
                break

            try:
                logger.error("Point 3")
                recommendations = sp.recommendations(seed_tracks = seed_tracks, limit = limit)
                logger.error("Point 4")
            except Exception as e:
                logger.error(f"Error during recommendations API call: {e}")
                break

            logger.error("Point 5")
            tracks = recommendations.get('tracks', [])
            if not tracks:
                logger.error("No tracks returned from recommendations.")
                attempts += 1
                logger.error("Point 6")
                if attempts < max_attempts:
                    if len(seed_tracks) > 1:
                        seed_tracks = random.sample(seed_tracks, min(5, len(seed_tracks)))
                    else:
                        logger.error("Seed tracks < 1")
                        break
                continue

            logger.error("Point 7")
            new_tracks_found = False
            for rec_track in tracks:
                rec_track_id = rec_track.get('id')
                if rec_track_id and not rec_track.get('is_local') and rec_track_id not in user_track_ids and rec_track_id not in [track['id'] for track in recommended_tracks]:
                    logger.error(f"{number + 1} track added")
                    number += 1
                    recommended_tracks.append(rec_track)
                    get_or_create_song(rec_track, user)
                    new_tracks_found = True
                    

                if len(recommended_tracks) >= num_recommendations:
                    break

            if not new_tracks_found:
                attempts += 1
                logger.error("No new tracks found in attempt %d. Adjusting seed tracks.", attempts)
                if len(seed_tracks) > 1:
                    seed_tracks = random.sample(seed_tracks, min(5, len(seed_tracks)))
                else:
                    break

        return recommended_tracks

    except spotipy.SpotifyException as e:
        logger.error(f"Spotify API Error: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Request Error: {e}")
        return []
    except Exception as e:
        logger.error(f"Error Fetching Recommendations: {e}")
        return []
    
def get_recently_played_tracks():
    user = request.user
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
                get_or_create_song(track, user)

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