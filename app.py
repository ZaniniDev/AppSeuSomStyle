# pip install spotipy fastapi uvicorn jinja2 itsdangerous

from datetime import datetime, timezone

from requests import models
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List
from starlette.middleware.sessions import SessionMiddleware
import logging
import os
from dotenv import load_dotenv
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Track, User, UserTrack
from database import engine
import models
from dataclasses import dataclass
from typing import List


load_dotenv()

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("AppSeuSomStyle")

# Configurações do ambiente
CLIENT_ID = os.getenv("CLIENT_ID_SPOTIFY")
CLIENT_SECRET = os.getenv("CLIENT_SECRET_SPOTIFY")
URL_CALL_BACK = os.getenv("URL_CALL_BACK_SPOTIFY")
SECRET_KEY = os.getenv("SECRET_KEY", "chave_mestra_segura_123")

app = FastAPI()
models.Base.metadata.create_all(bind=engine)
# Ativando as Sessões (Cookies)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates = Jinja2Templates(directory="templates")

# Cache de músicas em memória (usando o user_id como chave)
musicas_por_usuario = {}

sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=URL_CALL_BACK,
    scope="user-library-read playlist-modify-public",
    cache_handler=spotipy.MemoryCacheHandler()
)

# --- FUNÇÃO AUXILIAR ---
def get_spotify_client(request: Request):
    """Recupera o cliente Spotify se houver um token válido na sessão."""
    token_info = request.session.get("token_info")
    if not token_info:
        return None
    return spotipy.Spotify(auth=token_info["access_token"])

# --- ROTAS ---

@app.get("/")
def home(request: Request):
    logado = "token_info" in request.session
    return templates.TemplateResponse(request, "index.html", {"logado": logado})

@app.get("/login")
def login(request: Request):
    # Se já tiver os dados na sessão, pula o login do Spotify
    if "token_info" in request.session:
        return RedirectResponse(url="/pages-user")
    
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(auth_url)

@app.get("/callback")
def callback(request: Request, code: str, db: Session = Depends(get_db)):
    # 1. Troca o código pelo token
    token_info = sp_oauth.get_access_token(code)
    request.session["token_info"] = token_info

    # 2. Busca informações do perfil UMA ÚNICA VEZ
    sp = spotipy.Spotify(auth=token_info["access_token"])
    user_info = sp.current_user()
    
    # 3. Salva ID e Nome na sessão para uso futuro
    request.session["user_id"] = user_info["id"]
    request.session["user_name"] = user_info.get("display_name") or user_info["id"]
    user = db.query(User).filter_by(spotify_id=request.session["user_id"]).first()
    if not user:
        user = User(
            spotify_id=request.session["user_id"],
            name=user_info.get("name"),
            display_name=request.session["user_name"],
            email=user_info.get("email"),
            access_token=token_info["access_token"],
            refresh_token=token_info["refresh_token"],
            token_expires_at=datetime.fromtimestamp(token_info["expires_at"], tz=timezone.utc)
        )
        db.add(user)
        db.flush()
        db.commit()
        logger.info(f"Usuário '{request.session['user_name']}' logado e dados salvos na sessão.")
    else:
        user.access_token = token_info["access_token"]
        user.refresh_token = token_info["refresh_token"]
        user.last_login_at = datetime.utcnow()
        user.token_expires_at=datetime.fromtimestamp(token_info["expires_at"], tz=timezone.utc)
        db.commit()
    
    logger.info(f"Usuário '{request.session['user_name']}' logado e dados salvos na sessão.")
    
    return RedirectResponse(url="/pages-user")

@app.get("/loading")
def loading(request: Request):
    if "token_info" not in request.session:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "loading.html", {})

@app.get("/pages-user")
def pages_user(request: Request):
    if "token_info" not in request.session:
        return RedirectResponse(url="/login")
    user_name = request.session.get("user_name", "Usuário")
    return templates.TemplateResponse(request, "pages_user.html", {"nome_usuario": user_name})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/buscar-minhas-musicas")
def buscar_musicas_curtidas(request: Request, db: Session = Depends(get_db)):
    sp = get_spotify_client(request)
    user_id = request.session.get("user_id")

    if not sp or not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    user = db.query(User).filter_by(spotify_id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    musicas = []
    offset = 0
    limit = 20
    limit_musicas = 2000
    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        items = results.get("items", [])
        if not items:
            break
        for item in items:
            track_data = item["track"]
            liked_at = item.get("added_at")
            images = track_data["album"].get("images", [])
            imagem = images[0]["url"] if images else None
            # upsert na tabela tracks (insere só se não existir)
            track = db.query(Track).filter_by(spotify_id=track_data["id"]).first()
            if not track:
                
                track = Track(
                    spotify_id=track_data["id"],
                    name=track_data["name"],
                    artist_name=track_data["artists"][0]["name"],
                    artist_spotify_id=track_data["artists"][0]["id"],
                    album_name=track_data["album"]["name"],
                    duration_ms=track_data["duration_ms"],
                    image_url=imagem
                )
                db.add(track)
                db.flush()  # garante que track.id é gerado antes do próximo insert

            # vincula a música ao usuário se ainda não estiver vinculada
            link = db.query(UserTrack).filter_by(user_id=user.id, track_id=track.id).first()
            if not link:
                db.add(UserTrack(
                    user_id=user.id,
                    track_id=track.id,
                    liked_at=datetime.fromisoformat(liked_at.replace("Z", "+00:00")) if liked_at else None,
                ))            

            musicas.append({
                "id": track_data["id"],
                "nome": track_data["name"],
                "artista": track_data["artists"][0]["name"],
                "imagem": imagem,
            })

        offset += limit
        if len(musicas) >= limit_musicas:
            break

    db.commit()
    musicas_por_usuario[user_id] = musicas
    return musicas

@app.get("/minhas-musicas")
def musicas_curtidas(request: Request, db: Session = Depends(get_db)):
    user_spotify_id = request.session.get("user_id")
    user_name = request.session.get("user_name")

    
    if "token_info" not in request.session:
        logger.info("Usuário não autenticado. Redirecionando para login.")
        return RedirectResponse(url="/login")

    user = db.query(User).filter_by(spotify_id=user_spotify_id).first()
    if not user:
        logger.info(f"Usuário com Spotify ID '{user_spotify_id}' não encontrado no banco de dados. Redirecionando para login.")
        return RedirectResponse(url="/loading")

    tracks = (
        db.query(Track)
        .join(UserTrack, UserTrack.track_id == Track.id)
        .filter(UserTrack.user_id == user.id)
        .order_by(UserTrack.liked_at.desc())
        .all()
    )

    return templates.TemplateResponse(request, "musicas.html", {
        "musicas": tracks,
        "total": len(tracks),
        "nome_usuario": user_name,
    })

# --- Criação de Playlist ---
@dataclass
class TrackRequest:
    id: str
    nome: str

@dataclass
class CriarPlaylistRequest:
    nome_playlist: str
    tracks: List[TrackRequest]

@app.post("/criar-playlist")
def criar_playlist(request: Request, body: CriarPlaylistRequest):
    sp = get_spotify_client(request)
    user_id = request.session.get("user_id")
    user_name = request.session.get("user_name")

    if not sp or not user_id:
        raise HTTPException(status_code=401, detail="Sessão expirada.")

    try:
        logger.info(f"Usuário {user_name} criando playlist '{body.nome_playlist}'")
        
        # Cria a playlist usando o user_id da sessão
        playlist = sp.current_user_playlist_create(
            name=body.nome_playlist,
            public=True,
            description="Criada via App SeuSomStyle"
        )
        
        track_ids = [f"spotify:track:{t.id}" for t in body.tracks]
        for i in range(0, len(track_ids), 100):
            sp.playlist_add_items(playlist["id"], track_ids[i:i+100])

        return {"mensagem": "Sucesso!", "url": playlist["external_urls"]["spotify"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)