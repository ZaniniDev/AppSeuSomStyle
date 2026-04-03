# pip install spotipy fastapi uvicorn jinja2

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
from uuid import uuid4
import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Configuração de Logs para Produção
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("AppSeuSomStyle")

CLIENT_ID = os.getenv("CLIENT_ID_SPOTIFY")
CLIENT_SECRET = os.getenv("CLIENT_SECRET_SPOTIFY")
URL_CALL_BACK = os.getenv("URL_CALL_BACK_SPOTIFY")  # Ex: "http://127.0.0.1:8000/callback"

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Armazenar tokens em memória
tokens = {}
musicas_por_usuario = {}

# Você cria esses valores no Spotify Developer Dashboard
sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=URL_CALL_BACK,
    scope="user-library-read playlist-modify-public"
    # user-library-read = ler músicas curtidas
    # playlist-modify-public = criar playlists
)

@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})

@app.get("/login")
def login():
    # Gera um identificador único para a sessão do usuário
    state = str(uuid4())
    auth_url = sp_oauth.get_authorize_url(state=state)
    return RedirectResponse(auth_url)

@app.get("/callback")
def callback(code: str, state: str):
    token_info = sp_oauth.get_access_token(code)

    access_token = token_info["access_token"]
    refresh_token = token_info["refresh_token"]

    # Salva os tokens em memória, associados ao state
    tokens[state] = {
        "access_token": access_token,
        "refresh_token": refresh_token
    }

    # Registrar login no log
    try:
        sp_temp = spotipy.Spotify(auth=access_token)
        user_info_temp = sp_temp.current_user()
        nome_usuario = user_info_temp.get("display_name") or user_info_temp.get("id")
        logger.info(f"Novo login (callback) realizado com sucesso. Usuário: '{nome_usuario}'. AcessToken obtido '{access_token}' e armazenado para state '{state}'.")
    except Exception as e:
        logger.warning(f"Novo login realizado, mas houve erro ao buscar nome do usuário: {e}")

    # Redireciona para a tela de carregamento antes de buscar as músicas
    return RedirectResponse(url=f"/loading?state={state}")

@app.get("/loading")
def loading(request: Request, state: str):
    return templates.TemplateResponse(request, "loading.html", {"state": state})

@app.get("/logout")
def logout(state: str):
    tokens.pop(state, None)
    logger.info(f"Usuário com state '{state}' fez logout.")
    return RedirectResponse(url="/")

@app.get("/musicas-usuario-logado")
def musicas_usuario_logado(state: str):
    """Retorna as músicas salvas para o usuário logado."""
    if state not in musicas_por_usuario:
        print("Esse erro")
        raise HTTPException(status_code=404, detail="Nenhuma música encontrada para o usuário logado.")
    return {"musicas": musicas_por_usuario[state]}

@app.get("/buscar-minhas-musicas")
def buscar_musicas_curtidas(request: Request, state: str):
    # Recupera o access_token associado ao state
    if state not in tokens:
        raise HTTPException(status_code=401, detail="Usuário não autenticado.")
    access_token = tokens[state]["access_token"]
    sp = spotipy.Spotify(auth=access_token)

    try:
        user_info = sp.current_user()
        nome_usuario = user_info.get("display_name") or user_info.get("id")
        logger.info(f"Usuário '{nome_usuario}' acessou a listagem de músicas curtidas (/minhas-musicas).")

        musicas = []
        offset = 0
        limit_per_get_music = 20
        limit_max_music = 0

        # Busca todas as músicas curtidas (paginação)
        while True:
            results = sp.current_user_saved_tracks(limit=limit_per_get_music, offset=offset)
            items = results.get("items", [])
            if not items:
                break

            for item in items:
                track = item["track"]
                images = track["album"].get("images", [])
                imagem = images[0]["url"] if images else None

                musicas.append({
                    "id": track["id"],
                    "nome": track["name"],
                    "artista": track["artists"][0]["name"],
                    "imagem": imagem,
                })

            # Se retornou menos que o limite, chegou ao fim
            if limit_max_music > 0 and offset >= limit_max_music:
                break
            offset += limit_per_get_music

        # Salva as músicas na variável global
        musicas_por_usuario[state] = musicas
        return musicas_por_usuario[state]

    # Deixe explícito o erro
    except spotipy.exceptions.SpotifyException as e:
        logger.warning(f"Token expirado ou inválido para state '{state}'. Redirecionando para login.")
        logger.error(f"Erro ao buscar músicas curtidas: {e}")
        tokens.pop(state, None)
        raise HTTPException(status_code=401, detail=f"Erro ao buscar músicas curtidas: {e}")
        # return {"error": f"Erro ao buscar músicas curtidas: {e}"}
        

@app.get("/minhas-musicas")
def musicas_curtidas(request: Request, state: str):
    # Recupera o access_token associado ao state
    if state not in tokens:
        return RedirectResponse(url="/login")

    access_token = tokens[state]["access_token"]
    sp = spotipy.Spotify(auth=access_token)
    user_info = sp.current_user()
    nome_usuario = user_info.get("display_name") or user_info.get("id")
    logger.info(f"Usuário '{nome_usuario}' acessou a listagem de músicas curtidas (/minhas-musicas).")

    if state not in musicas_por_usuario:
        #Busca as musicas por usuario
        buscar_musicas_curtidas(request, state)

    musicas = musicas_por_usuario[state]

    return templates.TemplateResponse(request, "musicas.html", {
        "musicas": musicas,
        "total": len(musicas),
        "state": state,
    })
# --- Modelos para o body das rotas de criação de playlist ---

class Track(BaseModel):
    id: str
    nome: str

class CriarPlaylistRequest(BaseModel):
    nome_playlist: str
    tracks: List[Track]

class CriarPlaylistIARequest(BaseModel):
    tracks: List[Track]


@app.post("/criar-playlist")
def criar_playlist(state: str, body: CriarPlaylistRequest):
    if state not in tokens:
        raise HTTPException(status_code=404, detail="Usuário não encontrado ou não autenticado.")

    access_token = tokens[state]["access_token"]
    sp = spotipy.Spotify(auth=access_token)

    try:
        user = sp.current_user()
        user_id = user["id"]
        nome_usuario = user.get("display_name") or user_id
        
        logger.info(f"Usuário '{nome_usuario}' ({user_id}) iniciou a criação da playlist '{body.nome_playlist}'.")

        # Cria a playlist
        playlist = sp.current_user_playlist_create(
            name=body.nome_playlist,
            public=True,
            description="Criada pelo App SeuSomStyle"
        )
        playlist_id = playlist["id"]
        playlist_url = playlist["external_urls"]["spotify"]

        # Adiciona as tracks (limite de 100 por request)
        track_ids = [f"spotify:track:{t.id}" for t in body.tracks]
        for i in range(0, len(track_ids), 100):
            sp.playlist_add_items(playlist_id, track_ids[i:i+100])

        logger.info(f"Playlist '{body.nome_playlist}' criada com sucesso pelo usuário '{nome_usuario}' (com {len(body.tracks)} músicas).")

        return {
            "mensagem": f"Playlist '{body.nome_playlist}' criada com {len(body.tracks)} música(s).",
            "playlist_id": playlist_id,
            "url": playlist_url,
        }

    except spotipy.exceptions.SpotifyException as e:
        raise HTTPException(status_code=401, detail=f"Erro no Spotify: {str(e)}")


@app.post("/criar-playlist-ia")
def criar_playlist_ia(state: str, body: CriarPlaylistIARequest):
    # Placeholder — integrar com Claude ou outro modelo de IA
    raise HTTPException(status_code=501, detail="Criação de playlist com IA ainda não implementada.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
