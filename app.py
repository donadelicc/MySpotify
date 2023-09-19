from flask import Flask, render_template, request, redirect, url_for, session, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import CacheHandler

import os
from dotenv import load_dotenv
import time
import datetime
import json
import openai
import os

# Få den nåværende mappens absolutte sti
current_folder = os.path.dirname(os.path.abspath(__file__))
# Bygg stien til .env-filen
env_path = os.path.join(current_folder, '.env')
# Last inn .env-filen fra den spesifikke stien
load_dotenv(dotenv_path=env_path)

openai.api_key = os.environ.get("OPENAI_API_KEY")


app = Flask(__name__)

app.secret_key = "spotifyApp"
app.config['SESSION_COOKIE_NAME'] = 'Prebens Cookie'
TOKEN_INFO = "token_info"
USER_LIBRARY_READ_SCOPE = "user-library-read"
MODIFY_PLAYLIST_SCOPE = "playlist-modify-private"
USER_LIBRARY_MODIFY_SCOPE = "user-library-modify"

class FlaskSessionCacheHandler(CacheHandler):
    def __init__(self, session):
        self.session = session

    def get_cached_token(self):
        return self.session.get(TOKEN_INFO)

    def save_token_to_cache(self, token_info):
        self.session[TOKEN_INFO] = token_info



def create_spotify_oauth():
    cache_handler = FlaskSessionCacheHandler(session)
    return SpotifyOAuth(
        client_id=os.environ.get("SPOTIFY_CLIENT_ID"),
        client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=url_for("redirectPage", _external=True),
        scope= USER_LIBRARY_READ_SCOPE + " " + MODIFY_PLAYLIST_SCOPE + " " + USER_LIBRARY_MODIFY_SCOPE,
        cache_handler=cache_handler
    )

def get_token():
    token_info = session.get(TOKEN_INFO, None)
    if not token_info:
        raise "exception"
    now = int(time.time())
    is_expired = token_info['expires_at'] - now < 60
    if (is_expired):
        sp_oauth = create_spotify_oauth()
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
    #return token_info['access_token']
    return token_info


                    # Routes        

def get_playlist(prompt, count):
    example_json = """ 
    [
      {"song": "Someone Like You", "artist": "Adele"},
      {"song": "Hurt", "artist": "Johnny Cash"},
      {"song": "Fix You", "artist": "Coldplay"},
      {"song": "Nothing Compares 2 U", "artist": "Sinead O'Connor"},
      {"song": "All By Myself", "artist": "Celine Dion"},
      {"song": "Tears in Heaven", "artist": "Eric Clapton"},
      {"song": "My Immortal", "artist": "Evanescence"},
      {"song": "I Can't Make You Love Me", "artist": "Bonnie Raitt"},
      {"song": "Everybody Hurts", "artist": "R.E.M."},
      {"song": "Mad World", "artist": "Gary Jules"}
    ]
    """

    messages = [
        {"role": "system", "content": """You are a helpfull playlist generating assistant.
        You should generate a list of songs and their artists accordning to a text prompt.
        You should return it as a json array, where each element follows this format: {"song": <song_title>, "artist": <artist_name>}
        """
        },
        {"role": "user", "content": """Generate a playlist of 10 songs based on this prompt: super super sad songs
        """
        },
        {"role": "assistant", "content": example_json
        },
        {"role": "user", "content": f"Generate a playlist of {count} songs based on this prompt: {prompt}"
        },
    ]

    response = openai.ChatCompletion.create(
        messages=messages,
        model="gpt-3.5-turbo",
        max_tokens=2000,
    )
    
    playlist = json.loads(response["choices"][0]["message"]["content"])
    return (playlist)





@app.route('/')
def home():
    return render_template('index.html')


@app.route('/redirect')
def redirectPage():
    sp_oauth = create_spotify_oauth()
    session.clear()
    code = request.args.get('code')
    if not code:
        #auth_url = sp_oauth.get_authorize_url()
        #return redirect(auth_url)
        return "Authorization code not provided in callback."
    token_info = sp_oauth.get_access_token(code)
    session[TOKEN_INFO] = token_info
    session['logged_in'] = True
    return redirect(url_for("home", _external=True))


@app.route('/prompt', methods=['GET', 'POST'])
def getPrompt():
    if request.method == 'GET':
        return render_template('prompt.html')
    else:
        try:
            prompt = request.form.get('prompt')
            count = int(request.form.get('count'))
            
            if not prompt or count <= 0:
                raise Exception("Ugylding prompt eller antall sanger. Prøv på nytt.")
            
            playlist = get_playlist(prompt, count)
            
            # Create playlist in user's Spotify account
            token_info = get_token()
            sp = spotipy.Spotify(auth=token_info['access_token'])
            current_user = sp.current_user()
            track_ids = []
            songs_added = []

            for item in playlist:
                artist, song = item["artist"], item["song"]
                query = f"{song} {artist}"
                search_results = sp.search(q=query, type="track", limit=1)
                if search_results["tracks"]["items"]:
                    track_ids.append(search_results["tracks"]["items"][0]["id"])
                    songs_added.append({"song": song, "artist": artist})
                else:
                    raise ValueError(f"Sangen{song} av {artist} ble ikke funnet på Spotify. Prøv å opprett spilleliste på nytt med en annen prompt.")

            playlist_name = f"AI - {prompt} {datetime.datetime.now().strftime('%c')}"
            created_playlist = sp.user_playlist_create(current_user["id"], public=False, name=playlist_name)
            sp.user_playlist_add_tracks(current_user["id"], created_playlist["id"], track_ids)
            
            return render_template('prompt.html', playlist=songs_added if 'songs_added' in locals() else None, playlist_name=playlist_name if 'playlist_name' in locals() else None)

        except ValueError as e:
            return f"Feil: {e}"
        except Exception as e:
            return f"Feil: {e}"


@app.route('/savedTracks')
def getSavedTracks():
    try:
        token_info = get_token()
    except:
        print("user not logged in")
        return redirect(url_for("login", _external=False))
    
    sp = spotipy.Spotify(auth=token_info['access_token'])
    allTracks = []
    i = 0
    while True:
        tracks_data = sp.current_user_saved_tracks(limit=50, offset=i * 50)["items"]
        if not tracks_data:
            break
        i += 1

        for track_item in tracks_data:
            track = track_item["track"]
            song_name = track["name"]
            artist_name = track["artists"][0]["name"]
            album_name = track["album"]["name"]
            duration_in_minutes = track["duration_ms"]/60000

            track_info = {
                "song_name": song_name,
                "artist_name": artist_name,
                "album_name": album_name,
                "duration_ms": round(duration_in_minutes, 2)
            }
            allTracks.append(track_info)

    return render_template('tracks.html', tracks=allTracks[:10]) # --> returnere bare de første 10


if __name__ == '__main__':
    app.run(debug=True)