import pygame
import requests # BIBLIOTECA DE REDE
import json
import datetime
import math
import os
import io # Para ler bytes da imagem baixada

# ============================================================
#  CONFIGURAÇÕES DE REDE (IOT)
# ============================================================
URL_SERVIDOR = "http://127.0.0.1:5000" # Endereço do Servidor Python
TIMEOUT_REQ = 3 # Segundos para timeout

# ============================================================
#  HARDWARE - Display ST7735 (128x160)
# ============================================================
LARGURA = 128
ALTURA = 160
SCALE = 3
PASTA_CACHE = "cache_pulseira" # Pasta temporária da pulseira

if not os.path.exists(PASTA_CACHE): os.makedirs(PASTA_CACHE)

# ============================================================
#  PALETA DE CORES
# ============================================================
BG_DEEP       = (10, 12, 18)
BG_CARD       = (25, 30, 40)
AZUL_ICE      = (100, 200, 255)
MENTA         = (72, 219, 160)
LARANJA       = (255, 140, 0)
BRANCO        = (255, 255, 255)
CINZA_CLARO   = (200, 200, 200)
CINZA_ESCURO  = (80, 80, 80)
AMARELO_OURO  = (255, 215, 0)
VERMELHO_ERRO = (200, 50, 50)

# ============================================================
#  ESTADOS
# ============================================================
TELA_SETUP      = -1
TELA_RELOGIO    = 0
TELA_ALERTA     = 1
TELA_FOTO_FULL  = 2
TELA_CONFIRMADO = 3
TELA_SYNC       = 4 # Nova tela: Sincronizando

estado_atual = TELA_SETUP 
medicamento_atual = None
img_medicamento_cache = None
soneca_ativa = False
tempo_inicio_soneca = 0
inicio_confirmacao = 0
TEMPO_SONECA_TESTE = 10
erro_conexao = False # Flag para mostrar erro se o servidor cair

pygame.init()
tela_display = pygame.display.set_mode((LARGURA * SCALE, ALTURA * SCALE))
pygame.display.set_caption("Pulseira IoT - Cliente HTTP")
clock = pygame.time.Clock()

# Fontes
fonte_hora      = pygame.font.SysFont("arial", 42, bold=True)
fonte_titulo    = pygame.font.SysFont("arial", 14, bold=True)
fonte_dado      = pygame.font.SysFont("arial", 17, bold=True)
fonte_med_nome  = pygame.font.SysFont("arial", 20, bold=True)
fonte_med_dose  = pygame.font.SysFont("arial", 14, bold=True)
fonte_botao     = pygame.font.SysFont("arial", 16, bold=True)
fonte_mini      = pygame.font.SysFont("arial", 10)

agenda = [] # Começa vazia, será preenchida pela REDE

# ============================================================
#  FUNÇÕES DE REDE (O "CÉREBRO" DA CONEXÃO)
# ============================================================

def sincronizar_dados():
    """Simula o ESP32 conectando no Wi-Fi e baixando JSON"""
    global agenda, erro_conexao
    print("[IOT] Conectando ao servidor...")
    
    try:
        # 1. Baixa o JSON
        resp = requests.get(f"{URL_SERVIDOR}/api/agenda", timeout=TIMEOUT_REQ)
        if resp.status_code == 200:
            dados = resp.json()
            agenda = dados.get('medicamentos', [])
            print(f"[IOT] Agenda atualizada! {len(agenda)} itens.")
            erro_conexao = False
            return True
        else:
            print(f"[ERRO] Servidor respondeu: {resp.status_code}")
            erro_conexao = True
            return False
            
    except Exception as e:
        print(f"[ERRO] Falha na conexão: {e}")
        erro_conexao = True
        return False

def baixar_imagem(nome_arquivo):
    """Baixa a imagem via HTTP e salva no Cache local"""
    if not nome_arquivo: return None
    
    caminho_local = os.path.join(PASTA_CACHE, nome_arquivo)
    
    # Se já temos no cache, não gasta dados baixando de novo
    if os.path.exists(caminho_local):
        print(f"[CACHE] Imagem carregada do disco: {nome_arquivo}")
        return pygame.image.load(caminho_local)
        
    print(f"[IOT] Baixando imagem nova: {nome_arquivo}...")
    try:
        url = f"{URL_SERVIDOR}/api/imagens/{nome_arquivo}"
        resp = requests.get(url, timeout=TIMEOUT_REQ)
        if resp.status_code == 200:
            # Salva no disco (Cache)
            with open(caminho_local, 'wb') as f:
                f.write(resp.content)
            # Carrega para memória
            img_bytes = io.BytesIO(resp.content)
            return pygame.image.load(img_bytes)
    except:
        print("[ERRO] Falha ao baixar imagem.")
    return None

def enviar_confirmacao(medicamento):
    """Envia POST para o servidor avisando que tomou"""
    payload = {
        "usuario": "user_01",
        "medicamento": medicamento['nome'],
        "horario_real": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "TOMADO"
    }
    try:
        requests.post(f"{URL_SERVIDOR}/api/confirmar", json=payload, timeout=1)
        print("[IOT] Confirmação enviada para a nuvem!")
    except:
        print("[IOT] Sem internet. Log salvo localmente (Simulado).")

# ============================================================
#  INTERFACE GRÁFICA
# ============================================================

def rounded_rect(surface, cor, rect, radius=8):
    pygame.draw.rect(surface, cor, rect, border_radius=radius)

def tc(surface, texto, fonte, cor, cx, cy):
    s = fonte.render(texto, True, cor)
    surface.blit(s, s.get_rect(center=(cx, cy)))

def tl(surface, texto, fonte, cor, x, cy):
    s = fonte.render(texto, True, cor)
    surface.blit(s, s.get_rect(midleft=(x, cy)))

def truncar(t, m): return t[:m-2]+".." if len(t)>m else t

# --- TELAS ---

def desenhar_setup(surface):
    surface.fill(BG_DEEP)
    cx = LARGURA // 2
    
    # Ícone e Texto
    pygame.draw.circle(surface, AZUL_ICE, (cx, 30), 4)
    pygame.draw.arc(surface, BRANCO, (cx-15, 15, 30, 30), 0.6, 2.5, 3)
    
    rounded_rect(surface, BG_CARD, (5, 55, 118, 100), radius=10)
    tc(surface, "Rede Wi-Fi:", fonte_mini, CINZA_CLARO, cx, 65)
    tc(surface, "PULSEIRA", fonte_dado, AZUL_ICE, cx, 80)
    tc(surface, "Senha:", fonte_mini, CINZA_CLARO, cx, 100)
    rounded_rect(surface, (40, 40, 10), (20, 108, 88, 20), radius=5)
    tc(surface, "12345678", fonte_dado, AMARELO_OURO, cx, 118)
    
    # Instrução de tecla
    if erro_conexao:
        tc(surface, "ERRO AO CONECTAR!", fonte_titulo, VERMELHO_ERRO, cx, 145)
    else:
        tc(surface, "[W] Conectar", fonte_mini, CINZA_ESCURO, cx, 145)

def desenhar_sync(surface):
    # Tela de carregamento
    surface.fill(BG_DEEP)
    cx = LARGURA // 2
    cy = ALTURA // 2
    
    # Animação de loading
    t = pygame.time.get_ticks()
    pontos = "." * ((t // 500) % 4)
    
    tc(surface, "CONECTANDO", fonte_titulo, AZUL_ICE, cx, cy - 20)
    tc(surface, "AO SERVIDOR", fonte_titulo, AZUL_ICE, cx, cy)
    tc(surface, pontos, fonte_hora, BRANCO, cx, cy + 30)

def desenhar_relogio(surface):
    surface.fill(BG_DEEP)
    agora = datetime.datetime.now()
    
    # Barra Status
    rounded_rect(surface, (30,40,50), (0,0,LARGURA,18), radius=0)
    
    if erro_conexao:
        tc(surface, "OFFLINE", fonte_mini, VERMELHO_ERRO, 25, 9)
    else:
        tc(surface, "ONLINE", fonte_mini, MENTA, 25, 9)
        
    tc(surface, "90%", fonte_mini, BRANCO, LARGURA-15, 9)
    
    hora = agora.strftime("%H:%M")
    tc(surface, hora, fonte_hora, BRANCO, LARGURA//2, 50)
    
    dias = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
    data = f"{dias[agora.weekday()]}, {agora.day:02d}/{agora.month:02d}"
    tc(surface, data, fonte_titulo, CINZA_CLARO, LARGURA//2, 85)
    
    if soneca_ativa:
        rounded_rect(surface, LARANJA, (5, 105, 118, 40), radius=8)
        tc(surface, "PENDENTE!", fonte_titulo, (0,0,0), LARGURA//2, 118)
        tc(surface, "Toque p/ confirmar", fonte_mini, (0,0,0), LARGURA//2, 132)
    elif agenda:
        rounded_rect(surface, (20,30,50), (5, 105, 118, 40), radius=8)
        tl(surface, "Próximo:", fonte_mini, CINZA_CLARO, 12, 115)
        tl(surface, truncar(agenda[0]['nome'],12), fonte_titulo, AZUL_ICE, 12, 130)
        tl(surface, agenda[0]['horario'], fonte_titulo, AMARELO_OURO, 80, 130)
    else:
        # Se a agenda estiver vazia (ainda não baixou ou erro)
        rounded_rect(surface, BG_CARD, (5, 105, 118, 40), radius=8)
        tc(surface, "Sem dados", fonte_titulo, CINZA_ESCURO, LARGURA//2, 125)

def desenhar_alerta(surface):
    piscar = int(datetime.datetime.now().strftime("%S")) % 2 == 0
    bg = (40, 10, 10) if piscar else BG_DEEP
    surface.fill(bg)
    
    pygame.draw.rect(surface, (0,0,0), (0,0,LARGURA,25))
    tc(surface, "HORA DO REMÉDIO", fonte_titulo, LARANJA, LARGURA//2, 12)
    
    if medicamento_atual:
        tc(surface, truncar(medicamento_atual['nome'], 12), fonte_med_nome, BRANCO, LARGURA//2, 45)
        tc(surface, medicamento_atual['dose'], fonte_med_dose, AMARELO_OURO, LARGURA//2, 65)
        
    rounded_rect(surface, MENTA, (5, 90, 118, 30), radius=8)
    tc(surface, "JÁ TOMEI", fonte_botao, (0,0,0), LARGURA//2, 105)
    
    y_b = 125
    rounded_rect(surface, (40,50,70), (5, y_b, 56, 30), radius=8)
    tc(surface, "FOTO", fonte_titulo, BRANCO, 33, y_b+15)
    
    rounded_rect(surface, (80,40,0), (67, y_b, 56, 30), radius=8)
    tc(surface, "PARAR", fonte_titulo, BRANCO, 95, y_b+15)

def desenhar_foto(surface):
    surface.fill((0,0,0))
    if img_medicamento_cache:
        # Redimensiona para caber na tela
        img_scaled = pygame.transform.scale(img_medicamento_cache, (LARGURA, ALTURA))
        surface.blit(img_scaled, (0,0))
    else:
        tc(surface, "Carregando...", fonte_titulo, BRANCO, LARGURA//2, ALTURA//2)

def desenhar_confirma(surface):
    surface.fill(MENTA)
    tc(surface, "REGISTRADO", fonte_med_nome, (0,0,0), LARGURA//2, 80)
    tc(surface, "COM SUCESSO!", fonte_titulo, (0,0,0), LARGURA//2, 100)

# ============================================================
#  LOOP
# ============================================================
rodando = True
while rodando:
    tela = pygame.Surface((LARGURA, ALTURA))
    
    if soneca_ativa and estado_atual == TELA_RELOGIO:
        if (pygame.time.get_ticks()-tempo_inicio_soneca)/1000 > TEMPO_SONECA_TESTE:
            estado_atual = TELA_ALERTA; soneca_ativa = False

    for event in pygame.event.get():
        if event.type == pygame.QUIT: rodando = False
        if event.type == pygame.KEYDOWN:
            
            # --- SETUP (Conecta ao Wi-Fi e Baixa Dados) ---
            if estado_atual == TELA_SETUP:
                if event.key == pygame.K_w:
                    # Muda para tela de carregamento e força renderização
                    estado_atual = TELA_SYNC
            
            # --- RELOGIO ---
            elif estado_atual == TELA_RELOGIO:
                if event.key == pygame.K_SPACE: 
                    if agenda:
                        medicamento_atual = agenda[0]
                        # Tenta baixar a imagem na hora (ou pegar do cache)
                        img_medicamento_cache = baixar_imagem(medicamento_atual['img_arquivo'])
                        estado_atual = TELA_ALERTA
                        soneca_ativa = False
                    else:
                        print("[AVISO] Agenda vazia! Sincronize primeiro.")
                
                elif soneca_ativa and event.key == pygame.K_s:
                     enviar_confirmacao(medicamento_atual) # Envia para Nuvem
                     estado_atual = TELA_CONFIRMADO; inicio_confirmacao = pygame.time.get_ticks()

            # --- ALERTA ---
            elif estado_atual == TELA_ALERTA:
                if event.key == pygame.K_s: 
                    enviar_confirmacao(medicamento_atual) # Envia para Nuvem
                    estado_atual = TELA_CONFIRMADO; inicio_confirmacao = pygame.time.get_ticks()
                elif event.key == pygame.K_a: 
                    estado_atual = TELA_FOTO_FULL
                elif event.key == pygame.K_d: 
                    estado_atual = TELA_RELOGIO; soneca_ativa = True; tempo_inicio_soneca = pygame.time.get_ticks()

            elif estado_atual == TELA_FOTO_FULL: estado_atual = TELA_ALERTA

    # Lógica de Sincronização (Executada fora do loop de eventos para não travar o clique, mas aqui simplificada)
    if estado_atual == TELA_SYNC:
        desenhar_sync(tela)
        # Renderiza o frame de "Conectando..." antes de travar no download
        frame = pygame.transform.scale(tela, (LARGURA*SCALE, ALTURA*SCALE))
        tela_display.blit(frame, (0,0))
        pygame.display.flip()
        
        # Faz o download real
        sucesso = sincronizar_dados()
        pygame.time.wait(1000) # Só para ver a animação
        if sucesso:
            estado_atual = TELA_RELOGIO
        else:
            estado_atual = TELA_SETUP # Volta para tentar de novo

    # Renderização Normal
    elif estado_atual == TELA_SETUP: desenhar_setup(tela)
    elif estado_atual == TELA_RELOGIO: desenhar_relogio(tela)
    elif estado_atual == TELA_ALERTA: desenhar_alerta(tela)
    elif estado_atual == TELA_FOTO_FULL: desenhar_foto(tela)
    elif estado_atual == TELA_CONFIRMADO: 
        desenhar_confirma(tela)
        if pygame.time.get_ticks()-inicio_confirmacao > 2000: estado_atual = TELA_RELOGIO

    if estado_atual != TELA_SYNC: # Já renderizamos o sync acima
        frame = pygame.transform.scale(tela, (LARGURA*SCALE, ALTURA*SCALE))
        tela_display.blit(frame, (0,0))
        pygame.display.flip()
        clock.tick(30)

pygame.quit()