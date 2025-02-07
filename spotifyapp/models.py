from django.contrib.auth.models import User
from django.db import models

class Song(models.Model):
    track_id = models.CharField(max_length=255, unique=True)
    track_name = models.CharField(max_length=255)
    artist_names = models.TextField()
    album_art = models.URLField(blank=True, null=True)
    genres = models.TextField(blank=True)
    popularity = models.IntegerField(blank=True, null=True)
    danceability = models.FloatField(blank=True, null=True)
    energy = models.FloatField(blank=True, null=True)
    valence = models.FloatField(blank=True, null=True)
    acousticness = models.FloatField(blank=True, null=True)
    instrumentalness = models.FloatField(blank=True, null=True)
    liveness = models.FloatField(blank=True, null=True)
    speechiness = models.FloatField(blank=True, null=True)
    
    # Many-to-Many relationship with users
    users = models.ManyToManyField(User, related_name="songs")

    def __str__(self):
        return self.track_name
