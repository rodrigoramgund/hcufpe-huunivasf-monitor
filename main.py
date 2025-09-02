import os
import time
import json
import hashlib
import threading
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from flask import Flask
from telegram import Bot  # type: ignore

from datetime import datetime
last_status = {
    "last_check": None,  # timestamp
    "urls": {}           # {url: {"pdfs": int, "last_change": "YYYY-MM-DD HH:MM"}}
}


# --- CONFIGURAÇÕES ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8030537090:AAE_IztkT1YRYCUyDpACbu96KcWNOpVyoYU")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "796275012")

URLS = [
    "https://www.gov.br/ebserh/pt-br/acesso-a-informacao/agentes-publicos/concursos-e-selecoes/concursos/2024/convocacoes/hc-ufpe",
    "https://www.gov.br/ebserh/pt-br/acesso-a-informacao/agentes-publicos/concursos-e-selecoes/concursos/2024/convocacoes/hu-univasf",
]
INTERVALO = int(os.environ.get("INTERVALO", "300"))  # segundos
PERSIST_FILE = "state.json"  # arquivo local com o último estado

bot = Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)

# ---------- Persistência simples em arquivo ----------
def load_state() -> Dict[str, Dict[str, object]]:
    """Lê o último estado do disco. Exemplo:
    {
      "<url>": {"fp": "PDF:<hash>", "pdfs": ["...pdf1", "...pdf2"]},
      ...
    }
    """
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

# ---------- Coleta / fingerprint ----------
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
    """Retorna dict com 'fp' (hash) e 'pdfs' (lista)."""
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        pdfs = extrair_pdfs(soup)
        if pdfs:
            fp = "PDF:" + hashlib.sha256("\n".join(pdfs).encode("utf-8")).hexdigest()
            return {"fp": fp, "pdfs": pdfs}
        # fallback: hash do texto se não houver PDFs
        texto = soup.get_text(" ", strip=True)
        fp = "TXT:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()
        return {"fp": fp, "pdfs": []}
    except Exception as e:
        print(f"[ERRO] fingerprint {url}: {e}")
        return None

# ---------- Monitor ----------
def enviar_alerta(url: str, novos_pdfs: List[str]):
    msg = f"⚠️ A página foi atualizada!\n👉 {url}"
    if novos_pdfs:
        lista = "\n".join(f"• {x}" for x in novos_pdfs[:20])
        msg += f"\n\nNovos PDFs detectados:\n{lista}"
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)

def monitorar():
    state = load_state()

    # inicializa snapshots se estiver vazio
    for url in URLS:
        if url not in state:
            snap = fingerprint_por_pdf(url)
            if snap:
                state[url] = snap
                print(f"[INIT] snapshot salvo p/ {url}")
    save_state(state)
    print("[BOT] monitoramento iniciado.")

    while True:
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
                continue

            if snap["fp"] != old["fp"]:
                # calcula PDFs novos (se houver listas)
                antigos = set(old.get("pdfs", []))
                atuais = set(snap.get("pdfs", []))
                novos = sorted(list(atuais - antigos))
                enviar_alerta(url, novos_pdfs=novos)
                state[url] = snap
                save_state(state)
                print(f"[BOT] mudança detectada em {url} (alerta enviado).")
            else:
                print(f"[BOT] nenhuma mudança em {url}")

            # depois de obter 'snap' para cada url:
            last_status["urls"][url] = {
                "pdfs": len(snap.get("pdfs", [])),
                "last_change": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            last_status["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        time.sleep(INTERVALO)

# ---------- Flask (healthcheck) ----------
@app.route("/")
def home():
    if not last_status["last_check"]:
        return "🟢 Bot online (Render). Iniciando..."
    lines = [f"🟢 Bot online (Render). Última checagem: {last_status['last_check']}"]
    for url, info in last_status["urls"].items():
        lines.append(f"- {url} → PDFs: {info['pdfs']} | última mudança: {info.get('last_change','-')}")
    return "<br>".join(lines)

# inicia o monitor em background (compatível com gunicorn)
threading.Thread(target=monitorar, daemon=True).start()

# para rodar localmente; no Render usamos gunicorn
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
