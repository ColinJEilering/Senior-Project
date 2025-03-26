from django.contrib.auth.models import User
from django.db import models

class Song(models.Model):
    track_id = models.CharField(max_length=255, unique=True)
    track_name = models.CharField(max_length=255)
    artist_names = models.TextField()
    album_art = models.URLField(blank=True, null=True)
    genres = models.TextField(blank=True)
    popularity = models.IntegerField(blank=True, null=True)
    
    # Many-to-Many relationship with users
    users = models.ManyToManyField(User, related_name="songs")

    def __str__(self):
        return self.track_name

class ListeningHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    played_at = models.DateTimeField(auto_now_add=True)
    # Optional: How long the song was played, or if completed
    duration_listened = models.PositiveIntegerField(null=True, blank=True)  # in seconds
    def __str__(self):
        return f"{self.user.username} listened to {self.song.track_name} on {self.timestamp}"