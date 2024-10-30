import os
import sqlite3
from flask import Flask, render_template, jsonify, request
from functools import lru_cache
from ytmusicapi import YTMusic
import yt_dlp
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# Initialize YTMusic
ytmusic = YTMusic()

executor = ThreadPoolExecutor(max_workers=20)

def get_db_radio():
    db = sqlite3.connect('sangeet_radio.db')
    db.row_factory = sqlite3.Row
    return db

def init_db_radio():
    with app.app_context():
        db = get_db_radio()
        db.execute('''CREATE TABLE IF NOT EXISTS play_history
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       video_id TEXT UNIQUE,
                       title TEXT,
                       artist TEXT,
                       thumbnail TEXT,
                       timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        db.commit()

init_db_radio()

@lru_cache(maxsize=100)
def get_audio_url(video_id):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'config_location': 'yt_dlp.conf',
        'username': 'oauth2',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return info['url']

def get_song_info(video_id):
    ydl_opts = {
        'quiet': True,
        'config_location': 'yt_dlp.conf',
        'username': 'oauth2',
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return {
            'title': info.get('title', 'Unknown Title'),
            'artist': info.get('artist', 'Unknown Artist'),
            'thumbnail': f"https://img.youtube.com/vi/{video_id}/0.jpg"
        }

@app.route('/')
def radio():
    return render_template('radio.html')

@app.route('/radio/search')
def radio_search():
    query = request.args.get('q', '')
    page = int(request.args.get('page', 1))
    per_page = 80

    try:
        results = ytmusic.search(query, filter="songs")
        start = (page - 1) * per_page
        end = start + per_page
        paginated_results = results[start:end]

        songs = []
        for result in paginated_results:
            if result['resultType'] == 'song':
                songs.append({
                    'video_id': result['videoId'],
                    'title': result['title'],
                    'artist': result['artists'][0]['name'] if result['artists'] else 'Unknown Artist',
                    'thumbnail': f"https://img.youtube.com/vi/{result['videoId']}/0.jpg"
                })
        return jsonify(songs)
    except Exception as e:
        app.logger.error(f"Error searching songs: {str(e)}")
        return jsonify({'error': 'Failed to search songs'}), 500

@app.route('/radio/lyrics/<video_id>')
def radio_get_lyrics(video_id):
    ytmusic_local = YTMusic()
    try:
        watch_playlist = ytmusic_local.get_watch_playlist(videoId=video_id)
        lyrics_browse_id = watch_playlist.get('lyrics')
        if lyrics_browse_id:
            lyrics_data = ytmusic_local.get_lyrics(lyrics_browse_id)
            if lyrics_data and 'lyrics' in lyrics_data:
                return jsonify({
                    'status': 'success',
                    'lyrics': lyrics_data['lyrics'],
                    'source': "Sangeet One..."
                })
        return jsonify({
            'status': 'not_found',
            'message': 'No lyrics available for this song.'
        })
    except Exception as e:
        app.logger.error(f"Error getting lyrics: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"Failed to fetch lyrics: {str(e)}"
        }), 500

@app.route('/radio/stream/<video_id>')
def radio_stream(video_id):
    url = get_audio_url(video_id)
    return url

@app.route('/radio/add_to_history', methods=['POST'])
def radio_add_to_history():
    video_id = request.form.get('video_id')
    if not video_id:
        return jsonify({'error': 'No video_id provided'}), 400

    db = get_db_radio()
    song = db.execute('SELECT * FROM play_history WHERE video_id = ?', (video_id,)).fetchone()
    if song:
        db.execute('UPDATE play_history SET timestamp = CURRENT_TIMESTAMP WHERE video_id = ?', (video_id,))
    else:
        try:
            song_info = get_song_info(video_id)
            db.execute('INSERT OR REPLACE INTO play_history (video_id, title, artist, thumbnail) VALUES (?, ?, ?, ?)',
                       (video_id, song_info['title'], song_info['artist'], song_info['thumbnail']))
        except Exception as e:
            app.logger.error(f"Error adding song to history: {str(e)}")
            return jsonify({'error': 'Failed to add song to history'}), 500
    db.commit()
    return jsonify({'success': True})

@app.route('/radio/recent_songs')
def radio_recent_songs():
    db = get_db_radio()
    songs = db.execute('SELECT * FROM play_history ORDER BY timestamp DESC LIMIT 20').fetchall()
    return jsonify([dict(song) for song in songs])

@app.route('/radio/suggest')
def radio_suggest():
    query = request.args.get('q', '')
    suggestions = ytmusic.get_search_suggestions(query)
    return jsonify(suggestions)

@app.route('/radio/next_song')
def radio_next_song():
    current_song_id = request.args.get('current_song_id')
    if not current_song_id:
        return jsonify({'error': 'No current_song_id provided'}), 400

    try:
        watch_playlist = ytmusic.get_watch_playlist(videoId=current_song_id)
        if watch_playlist and 'tracks' in watch_playlist and watch_playlist['tracks']:
            next_song = watch_playlist['tracks'][0]  # Get the first recommended song
            return jsonify({
                'video_id': next_song['videoId'],
                'title': next_song['title'],
                'artist': next_song['artists'][0]['name'] if next_song['artists'] else 'Unknown Artist',
                'thumbnail': f"https://img.youtube.com/vi/{next_song['videoId']}/0.jpg"
            })
        return jsonify({'error': 'No next song found'}), 404
    except Exception as e:
        app.logger.error(f"Error getting next song: {str(e)}")
        return jsonify({'error': 'Failed to get next song'}), 500

@app.route('/radio/song_info/<video_id>')
def radio_song_info(video_id):
    try:
        info = get_song_info(video_id)
        return jsonify(info)
    except Exception as e:
        app.logger.error(f"Error getting song info: {str(e)}")
        return jsonify({'error': 'Failed to get song info'}), 500

@app.route('/radio/previous_song')
def radio_previous_song():
    db = get_db_radio()
    previous_songs = db.execute('SELECT * FROM play_history ORDER BY timestamp DESC LIMIT 2').fetchall()
    if len(previous_songs) > 1:
        return jsonify(dict(previous_songs[1]))
    else:
        return jsonify({'error': 'No previous song found'}), 404

if __name__ == '__main__':
    # Clean up and create the 'temp' directory
    if os.path.exists("temp"):
        try:
            os.rmdir("temp")
        except Exception as e:
            pass
    try:
        os.mkdir("temp")
    except Exception as e:
        pass
    app.run(host="0.0.0.0", port=os.getenv("port", 5000))
