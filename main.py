import requests
from bs4 import BeautifulSoup
import hashlib
import time
from flask import Flask
from telegram import Bot  # type: ignore
import threading
import os

# --- CONFIGURAÇÕES DO BOT ---
TELEGRAM_TOKEN = '8030537090:AAE_IztkT1YRYCUyDpACbu96KcWNOpVyoYU'
TELEGRAM_CHAT_ID = '796275012'
URLS = [
    'https://www.gov.br/ebserh/pt-br/acesso-a-informacao/agentes-publicos/concursos-e-selecoes/concursos/2024/convocacoes/hc-ufpe',
    'https://www.gov.br/ebserh/pt-br/acesso-a-informacao/agentes-publicos/concursos-e-selecoes/concursos/2024/convocacoes/hu-univasf'
]
INTERVALO = 300  # 5 minutos

bot = Bot(token=TELEGRAM_TOKEN)

def obter_hash_da_pagina(url):
    for tentativa in range(3):
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            conteudo = soup.get_text()
            return hashlib.sha256(conteudo.encode('utf-8')).hexdigest()
        except Exception as e:
            print(f"[ERRO] Tentativa {tentativa+1}/3 ao acessar {url}: {e}")
            time.sleep(3)
    return None

def monitorar():
    ultimos_hashes = {url: obter_hash_da_pagina(url) for url in URLS}

    if not all(ultimos_hashes.values()):
        print("[BOT] Falha inicial ao capturar o hash de uma ou mais páginas.")
        return

    print("[BOT] Monitoramento iniciado. Hashes iniciais capturados.")

    while True:
        for url in URLS:
            novo_hash = obter_hash_da_pagina(url)

            if novo_hash is None:
                print(f"[BOT] Erro ao acessar a página: {url}")
                continue

            if novo_hash != ultimos_hashes[url]:
                print(f"[BOT] Atualização detectada em: {url}")
                bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f'⚠️ A página foi atualizada!\n👉 {url}')
                ultimos_hashes[url] = novo_hash
            else:
                print(f"[BOT] Nenhuma mudança em: {url}")

        time.sleep(INTERVALO)

# --- SERVIDOR FLASK PARA UPTIMEROBOT ---
app = Flask(__name__)

@app.route('/')
def home():
    return '🟢 Bot está rodando e monitorando as páginas do HC-UFPE e HU-UNIVASF (EBSERH 2024).'

# Iniciar o monitoramento em outra thread (fora do __main__, para rodar no Gunicorn)
threading.Thread(target=monitorar, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))  # usa a porta do Render
    app.run(host='0.0.0.0', port=port)

