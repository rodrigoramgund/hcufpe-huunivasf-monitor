import os
import time
import json
import hashlib
import threading
from typing import Dict, List, Optional
from datetime import datetime
import traceback

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from telegram import Bot  # type: ignore

# -------- Config --------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8030537090:AAE_IztkT1YRYCUyDpACbu96KcWNOpVyoYU")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "796275012")

URLS = [
    "https://www.gov.br/ebserh/pt-br/acesso-a-informacao/agentes-publicos/concursos-e-selecoes/concursos/2024/convocacoes/hc-ufpe",
    "https://www.gov.br/ebserh/pt-br/acesso-a-informacao/agentes-publicos/concursos-e-selecoes/concursos/2024/convocacoes/hu-univasf",
]
INTERVALO = int(os.environ.get("INTERVALO", "300"))  # segundos
PERSIST_FILE = "state.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36"
}

bot = Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)

# -------- Status / Diagnóstico --------
last_status: Dict[str, Dict] = {
    "last_check": None,   # "YYYY-MM-DD HH:MM"
    "urls": {}            # url -> {"pdfs": int, "last_change": str}
}
last_error: Optional[str] = None  # guarda última exceção formatada

# -------- Persistência --------
def load_state() -> Dict[str, Dict[str, object]]:
    try:
        with open(PERSIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: Dict[str, Dict[str, object]]) -> None:
    try:
        with open(PERSIST_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[STATE] erro ao salvar: {e}")

# -------- Coleta / fingerprint --------
def extrair_pdfs(soup: BeautifulSoup) -> List[str]:
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/"):
            href = "https://www.gov.br" + href
        if href.lower().endswith(".pdf"):
            links.append(href)
    return sorted(set(links))

def fingerprint_por_pdf(url: str) -> Optional[Dict[str, object]]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        pdfs = extrair_pdfs(soup)
        if pdfs:
            fp = "PDF:" + hashlib.sha256("\n".join(pdfs).encode("utf-8")).hexdigest()
            return {"fp": fp, "pdfs": pdfs}
        texto = soup.get_text(" ", strip=True)
        fp = "TXT:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()
        return {"fp": fp, "pdfs": []}
    except Exception as e:
        print(f"[ERRO] fingerprint {url}: {e}")
        return None

# -------- Bot --------
def enviar_alerta(url: str, novos_pdfs: List[str]):
    msg = f"⚠️ A página foi atualizada!\n👉 {url}"
    if novos_pdfs:
        lista = "\n".join(f"• {x}" for x in novos_pdfs[:20])
        msg += f"\n\nNovos PDFs detectados:\n{lista}"
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)

# -------- Uma rodada de verificação --------
def rodada(state: Dict[str, Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    global last_status, last_error
    for url in URLS:
        snap = fingerprint_por_pdf(url)
        if not snap:
            print(f"[BOT] erro ao obter {url}, pulando…")
            continue

        old = state.get(url)
        if not old:
            state[url] = snap
            save_state(state)
            print(f"[BOT] inicializado {url}")
        else:
            if snap["fp"] != old["fp"]:
                antigos = set(old.get("pdfs", []))
                atuais = set(snap.get("pdfs", []))
                novos = sorted(list(atuais - antigos))
                enviar_alerta(url, novos_pdfs=novos)
                state[url] = snap
                save_state(state)
                print(f"[BOT] mudança detectada em {url} (alerta enviado).")
            else:
                print(f"[BOT] nenhuma mudança em {url}")

        # status da URL
        last_status["urls"][url] = {
            "pdfs": len(snap.get("pdfs", [])),
            "last_change": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

    last_status["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    last_error = None
    return state

# -------- Monitor (thread) --------
def monitorar():
    global last_error
    try:
        state = load_state()

        # snapshot inicial
        if not state:
            print("[INIT] criando snapshots iniciais…")
            for url in URLS:
                snap = fingerprint_por_pdf(url)
                if snap:
                    state[url] = snap
                    print(f"[INIT] snapshot salvo p/ {url}")
            save_state(state)

        print("[BOT] monitoramento iniciado.")
        while True:
            try:
                state = rodada(state)
            except Exception as e:
                # captura erro da rodada, mas mantém a thread viva
                last_error = f"{e}\n{traceback.format_exc()}"
                print(f"[LOOP] erro na rodada: {last_error}")
            time.sleep(INTERVALO)

    except Exception as e:
        # erro fatal ao iniciar a thread
        last_error = f"{e}\n{traceback.format_exc()}"
        print(f"[FATAL] thread caiu ao iniciar: {last_error}")

# -------- Flask --------
@app.route("/")
def home():
    if not last_status["last_check"]:
        base = "🟢 Bot online (Render). Iniciando..."
    else:
        lines = [f"🟢 Bot online (Render). Última checagem: {last_status['last_check']}"]
        for url, info in last_status["urls"].items():
            lines.append(f"- {url} → PDFs: {info['pdfs']} | última atualização local: {info.get('last_change','-')}")
        base = "<br>".join(lines)
    if last_error:
        base += f"<br><br>⚠️ Último erro:<br><pre>{last_error}</pre>"
    return base

@app.route("/ping")
def ping():
    return "pong"

@app.route("/tick")
def tick():
    """Força uma rodada agora e retorna JSON com status/erro."""
    try:
        state = load_state()
        state = rodada(state)
        save_state(state)
        return jsonify({"ok": True, "last_status": last_status})
    except Exception as e:
        err = f"{e}\n{traceback.format_exc()}"
        return jsonify({"ok": False, "error": err}), 500

# Inicia a thread FORA do __main__ (necessário p/ Gunicorn)
threading.Thread(target=monitorar, daemon=True).start()

# Para rodar localmente (no Render usamos Gunicorn)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)