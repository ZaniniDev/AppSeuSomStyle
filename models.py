from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    spotify_id       = Column(String, nullable=False, unique=True)
    name             = Column(String)
    display_name     = Column(String)
    email            = Column(String)
    access_token     = Column(String, nullable=False)
    refresh_token    = Column(String, nullable=False)
    token_expires_at = Column(DateTime, nullable=False)
    created_at       = Column(DateTime, default=datetime.utcnow)
    last_login_at    = Column(DateTime, default=datetime.utcnow)

    tracks    = relationship("UserTrack", back_populates="user")
    playlists = relationship("Playlist", back_populates="user")


class Track(Base):
    __tablename__ = "tracks"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    spotify_id        = Column(String, nullable=False, unique=True)
    name              = Column(String, nullable=False)
    artist_name       = Column(String, nullable=False)
    artist_spotify_id = Column(String)
    album_name        = Column(String)
    image_url         = Column(String)
    duration_ms       = Column(Integer)
    created_at        = Column(DateTime, default=datetime.utcnow)

    genres     = relationship("TrackGenre", back_populates="track")
    user_links = relationship("UserTrack", back_populates="track")


class UserTrack(Base):
    __tablename__ = "user_tracks"
    __table_args__ = (UniqueConstraint("user_id", "track_id"),)

    id        = Column(Integer, primary_key=True, autoincrement=True)
    user_id   = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    track_id  = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    liked_at  = Column(DateTime)
    synced_at = Column(DateTime, default=datetime.utcnow)

    user  = relationship("User", back_populates="tracks")
    track = relationship("Track", back_populates="user_links")


class TrackGenre(Base):
    __tablename__ = "track_genres"
    __table_args__ = (UniqueConstraint("track_id", "genre"),)

    id         = Column(Integer, primary_key=True, autoincrement=True)
    track_id   = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    genre      = Column(String, nullable=False)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    track = relationship("Track", back_populates="genres")


class Playlist(Base):
    __tablename__ = "playlists"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    user_id             = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name                = Column(String, nullable=False)
    description         = Column(String)
    user_prompt         = Column(String)
    status              = Column(String, nullable=False, default="pending_export")
    spotify_playlist_id = Column(String)
    spotify_url         = Column(String)
    created_at          = Column(DateTime, default=datetime.utcnow)
    exported_at         = Column(DateTime)

    user   = relationship("User", back_populates="playlists")
    tracks = relationship("PlaylistTrack", back_populates="playlist")


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    __table_args__ = (UniqueConstraint("playlist_id", "track_id"),)

    id          = Column(Integer, primary_key=True, autoincrement=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False)
    track_id    = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    position    = Column(Integer, nullable=False)

    playlist = relationship("Playlist", back_populates="tracks")
    track    = relationship("Track")