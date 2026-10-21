import re
from urllib.parse import parse_qs, urlparse


YOUTUBE_VIDEO_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{11}$')
YOUTUBE_HOSTS = {
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'youtube-nocookie.com',
    'www.youtube-nocookie.com',
    'youtu.be',
    'www.youtu.be',
}


def youtube_embed_url(value):
    """Return a canonical embed URL for a direct YouTube video URL, or None."""
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in YOUTUBE_HOSTS:
        return None

    video_id = None
    path_parts = [part for part in parsed.path.split('/') if part]
    if parsed.hostname in {'youtu.be', 'www.youtu.be'}:
        video_id = path_parts[0] if path_parts else None
    elif parsed.path == '/watch':
        video_id = parse_qs(parsed.query).get('v', [None])[0]
    elif len(path_parts) == 2 and path_parts[0] in {'embed', 'shorts', 'live', 'v'}:
        video_id = path_parts[1]

    if not video_id or not YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id):
        return None
    return f'https://www.youtube.com/embed/{video_id}'
