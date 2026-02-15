import pygame
import requests
import sys
import threading
import time
import math
from datetime import datetime

SERVIDOR_URL = "http://127.0.0.1:5000"

ESCALA = 2
REAL_W = 128
REAL_H = 160
LARGURA = REAL_W * ESCALA
ALTURA = REAL_H * ESCALA
FPS = 30
INTERVALO_CHECK = 30
TEMPO_REALARME = 300

# Paleta profissional
COR_FUNDO = (15, 15, 25)
COR_FUNDO_CARD = (28, 28, 45)
COR_AZUL = (70, 150, 255)
COR_AZUL_HOVER = (100, 170, 255)
COR_VERDE = (60, 210, 100)
COR_VERDE_HOVER = (80, 230, 120)
COR_VERMELHO = (255, 80, 80)
COR_AMARELO = (255, 215, 60)
COR_AMARELO_HOVER = (255, 225, 100)
COR_BRANCO = (240, 240, 250)
COR_CINZA = (130, 130, 150)
COR_CINZA_ESCURO = (70, 70, 90)
COR_ALARME_1 = (60, 15, 15)
COR_ALARME_2 = (40, 10, 10)
COR_BARRA = (45, 45, 70)


class Estado:
    def __init__(self):
        self.agenda = []
        self.config = {"horario_sono_inicio": "23:00", "horario_sono_fim": "07:00"}
        self.paciente = ""
        self.conectada = False
        self.tela = "inicio"
        self.alarme_ativo = False
        self.alarme_med = None
        self.alarme_viu = False
        self.alarme_tomou = False
        self.alarme_inicio = None
        self.vibrando = False
        self.ciclo = 0
        self.alertados = set()
        self.sync = None
        self.msg = ""
        self.msg_t = 0
        self.frame = 0


e = Estado()


def hmin(h):
    p = h.split(":")
    return int(p[0]) * 60 + int(p[1])


def nsono(h, c):
    si = hmin(c.get("horario_sono_inicio", "23:00"))
    sf = hmin(c.get("horario_sono_fim", "07:00"))
    v = hmin(h)
    return (v >= si or v < sf) if si > sf else (si <= v < sf)


def buscar():
    try:
        r = requests.get(f"{SERVIDOR_URL}/api/agenda", timeout=5)
        if r.status_code == 200:
            d = r.json()
            e.agenda = d.get("medicamentos", [])
            e.config = d.get("configuracoes", e.config)
            e.paciente = d.get("paciente", {}).get("nome", "")
            e.conectada = True
            e.sync = datetime.now()
            return True
    except:
        e.conectada = False
    return False


def confirmar(med):
    try:
        r = requests.post(f"{SERVIDOR_URL}/api/confirmar", json={
            "medicamento": med["nome"], "horario": med["horario"],
            "horario_real": datetime.now().strftime("%H:%M:%S"),
            "data": datetime.now().strftime("%d/%m/%Y"),
        }, timeout=5)
        if r.status_code == 200:
            buscar()
    except:
        pass


def alarmar(med):
    e.alarme_ativo = True
    e.alarme_med = med
    e.alarme_viu = False
    e.alarme_tomou = False
    e.alarme_inicio = datetime.now()
    e.vibrando = True
    e.ciclo = 0
    e.tela = "alarme"


def t_horarios():
    while True:
        time.sleep(INTERVALO_CHECK)
        if not e.conectada or e.alarme_ativo:
            continue
        buscar()
        agora = datetime.now()
        ha = agora.strftime("%H:%M")
        for med in e.agenda:
            hmed = med.get("horario", "")
            ch = f"{med['nome']}_{hmed}_{agora.strftime('%Y%m%d_%H%M')}"
            if ha == hmed and ch not in e.alertados:
                cat = med.get("categoria", "normal")
                if nsono(ha, e.config) and cat == "normal":
                    e.alertados.add(ch)
                    continue
                e.alertados.add(ch)
                alarmar(med)
                break


def t_realarme():
    while True:
        time.sleep(10)
        if not e.alarme_ativo or e.alarme_tomou:
            continue
        if e.alarme_viu and not e.alarme_tomou:
            if (datetime.now() - e.alarme_inicio).total_seconds() >= TEMPO_REALARME:
                e.vibrando = True
                e.alarme_viu = False
                e.alarme_inicio = datetime.now()
                e.ciclo = 0


def prox():
    if not e.agenda:
        return None
    ha = datetime.now().strftime("%H:%M")
    at = sorted([m for m in e.agenda if m.get("ativo", True)], key=lambda m: m.get("horario", ""))
    for m in at:
        if m.get("horario", "") >= ha:
            return m
    return at[0] if at else None


# =============================================
#  DESENHO
# =============================================

def tx(tela, texto, x, y, tam=12, cor=COR_BRANCO, centro=False, bold=False):
    try:
        f = pygame.font.SysFont("arial", tam * ESCALA, bold=bold)
    except:
        f = pygame.font.Font(None, tam * ESCALA)
    s = f.render(texto, True, cor)
    if centro:
        r = s.get_rect(center=(x * ESCALA, y * ESCALA))
        tela.blit(s, r)
    else:
        tela.blit(s, (x * ESCALA, y * ESCALA))


def retangulo(tela, x, y, w, h, cor, raio=4):
    r = pygame.Rect(x * ESCALA, y * ESCALA, w * ESCALA, h * ESCALA)
    pygame.draw.rect(tela, cor, r, border_radius=raio * ESCALA)
    return r


def bt(tela, texto, x, y, w, h, cor, cor_h, mp, cor_texto=COR_BRANCO):
    r = pygame.Rect(x * ESCALA, y * ESCALA, w * ESCALA, h * ESCALA)
    c = cor_h if r.collidepoint(mp) else cor
    pygame.draw.rect(tela, c, r, border_radius=8 * ESCALA)
    tx(tela, texto, x + w // 2, y + h // 2, 11, cor_texto, centro=True, bold=True)
    return r


def barra_topo(tela):
    retangulo(tela, 0, 0, REAL_W, 14, COR_BARRA)
    agora = datetime.now()
    tx(tela, agora.strftime("%H:%M"), 4, 1, 8, COR_CINZA)

    # Indicador conexao
    cor_c = COR_VERDE if e.conectada else COR_VERMELHO
    pygame.draw.circle(tela, cor_c, ((REAL_W - 10) * ESCALA, 7 * ESCALA), 4 * ESCALA)


# =============================================
#  TELAS
# =============================================

def tela_inicio(tela, mp):
    tela.fill(COR_FUNDO)

    # Logo area
    retangulo(tela, 14, 25, 100, 50, COR_FUNDO_CARD, 8)
    tx(tela, "PINAID", REAL_W // 2, 40, 20, COR_AZUL, centro=True, bold=True)
    tx(tela, "Cuidado Inteligente", REAL_W // 2, 60, 8, COR_CINZA, centro=True)

    # Status
    cor = COR_VERDE if e.conectada else COR_VERMELHO
    tx(tela, "Conectado" if e.conectada else "Desconectado", REAL_W // 2, 90, 9, cor, centro=True)

    # Botao
    b = bt(tela, "CONECTAR", 18, 110, 92, 32, COR_AZUL, COR_AZUL_HOVER, mp)

    return {"conectar": b}


def tela_relogio(tela, mp):
    tela.fill(COR_FUNDO)
    barra_topo(tela)
    agora = datetime.now()

    # Hora principal
    tx(tela, agora.strftime("%H:%M"), REAL_W // 2, 35, 28, COR_BRANCO, centro=True, bold=True)

    # Data
    tx(tela, agora.strftime("%d/%m/%Y"), REAL_W // 2, 52, 8, COR_CINZA, centro=True)

    # Card proximo remedio
    retangulo(tela, 8, 62, 112, 58, COR_FUNDO_CARD, 6)

    p = prox()
    if p:
        tx(tela, "PROXIMO", REAL_W // 2, 70, 7, COR_CINZA, centro=True)

        nome = p["nome"].upper()
        if len(nome) > 14:
            nome = nome[:13] + "."
        tx(tela, nome, REAL_W // 2, 84, 13, COR_AZUL, centro=True, bold=True)

        tx(tela, p["horario"], REAL_W // 2, 100, 14, COR_BRANCO, centro=True, bold=True)

        dose = p.get("dose", "")
        if len(dose) > 18:
            dose = dose[:17] + "."
        tx(tela, dose, REAL_W // 2, 114, 7, COR_CINZA, centro=True)
    else:
        tx(tela, "Sem remedios", REAL_W // 2, 88, 10, COR_CINZA, centro=True)
        tx(tela, "cadastrados", REAL_W // 2, 100, 10, COR_CINZA, centro=True)

    # Nome paciente
    if e.paciente:
        tx(tela, e.paciente, REAL_W // 2, 128, 7, COR_CINZA_ESCURO, centro=True)

    # Botao
    b = bt(tela, "ATUALIZAR", 24, 136, 80, 20, COR_AZUL, COR_AZUL_HOVER, mp)

    return {"sync": b}


def tela_alarme(tela, mp):
    med = e.alarme_med

    if e.vibrando:
        e.ciclo += 1
        # Efeito pulsante
        intensidade = abs(math.sin(e.ciclo * 0.08))
        r = int(40 + intensidade * 40)
        tela.fill((r, 10, 10))
    else:
        tela.fill(COR_FUNDO)

    barra_topo(tela)

    # Header alarme
    if e.vibrando:
        tx(tela, "HORA DO", REAL_W // 2, 24, 10, COR_VERMELHO, centro=True, bold=True)
        tx(tela, "REMEDIO!", REAL_W // 2, 36, 14, COR_VERMELHO, centro=True, bold=True)
    else:
        tx(tela, "REMEDIO", REAL_W // 2, 30, 12, COR_AZUL, centro=True, bold=True)

    # Card info
    retangulo(tela, 8, 48, 112, 48, COR_FUNDO_CARD, 6)

    nome = med["nome"].upper()
    if len(nome) > 14:
        nome = nome[:13] + "."
    tx(tela, nome, REAL_W // 2, 58, 14, COR_BRANCO, centro=True, bold=True)

    tx(tela, med["horario"], REAL_W // 2, 76, 14, COR_AZUL, centro=True, bold=True)

    dose = med.get("dose", "")
    if len(dose) > 20:
        dose = dose[:19] + "."
    tx(tela, dose, REAL_W // 2, 90, 7, COR_CINZA, centro=True)

    botoes = {}

    if e.vibrando:
        botoes["ja_vi"] = bt(tela, "JA VI", 10, 106, 108, 28, COR_AMARELO, COR_AMARELO_HOVER, mp, (20, 20, 20))
        tx(tela, "Toque para parar", REAL_W // 2, 144, 7, COR_CINZA, centro=True)
    else:
        botoes["tomei"] = bt(tela, "JA TOMEI", 10, 106, 108, 28, COR_VERDE, COR_VERDE_HOVER, mp)

        if e.alarme_inicio:
            t = max(0, TEMPO_REALARME - (datetime.now() - e.alarme_inicio).total_seconds())
            m = int(t // 60)
            s = int(t % 60)
            tx(tela, f"Volta em {m}:{s:02d}", REAL_W // 2, 144, 9, COR_VERMELHO, centro=True, bold=True)

    return botoes


def tela_ok(tela, mp):
    tela.fill(COR_FUNDO)
    barra_topo(tela)

    med = e.alarme_med

    # Circulo de confirmacao
    centro_x = REAL_W // 2 * ESCALA
    centro_y = 50 * ESCALA
    pygame.draw.circle(tela, COR_VERDE, (centro_x, centro_y), 20 * ESCALA, 3 * ESCALA)

    # Check mark
    pontos = [
        (centro_x - 10 * ESCALA, centro_y),
        (centro_x - 3 * ESCALA, centro_y + 8 * ESCALA),
        (centro_x + 12 * ESCALA, centro_y - 8 * ESCALA),
    ]
    pygame.draw.lines(tela, COR_VERDE, False, pontos, 3 * ESCALA)

    tx(tela, "TOMADO!", REAL_W // 2, 80, 16, COR_VERDE, centro=True, bold=True)

    if med:
        nome = med["nome"].upper()
        if len(nome) > 14:
            nome = nome[:13] + "."
        tx(tela, nome, REAL_W // 2, 100, 12, COR_BRANCO, centro=True, bold=True)
        tx(tela, datetime.now().strftime("%H:%M"), REAL_W // 2, 116, 12, COR_CINZA, centro=True)

    b = bt(tela, "VOLTAR", 24, 132, 80, 22, COR_AZUL, COR_AZUL_HOVER, mp)

    return {"voltar": b}


# =============================================
#  MAIN
# =============================================

def main():
    pygame.init()
    tela = pygame.display.set_mode((LARGURA, ALTURA))
    pygame.display.set_caption(f"Pinaid {REAL_W}x{REAL_H}")
    clock = pygame.time.Clock()

    threading.Thread(target=t_horarios, daemon=True).start()
    threading.Thread(target=t_realarme, daemon=True).start()

    print(f"PINAID Mock {REAL_W}x{REAL_H} x{ESCALA} | T=teste S=sync")

    rodando = True
    while rodando:
        mp = pygame.mouse.get_pos()
        b = {}
        e.frame += 1

        if e.tela == "inicio":
            b = tela_inicio(tela, mp)
        elif e.tela == "relogio":
            b = tela_relogio(tela, mp)
        elif e.tela == "alarme":
            b = tela_alarme(tela, mp)
        elif e.tela == "ok":
            b = tela_ok(tela, mp)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                rodando = False
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if "conectar" in b and b["conectar"].collidepoint(ev.pos):
                    if buscar():
                        e.tela = "relogio"
                if "sync" in b and b["sync"].collidepoint(ev.pos):
                    buscar()
                if "ja_vi" in b and b["ja_vi"].collidepoint(ev.pos):
                    e.vibrando = False
                    e.alarme_viu = True
                    e.alarme_inicio = datetime.now()
                if "tomei" in b and b["tomei"].collidepoint(ev.pos):
                    e.alarme_tomou = True
                    e.alarme_ativo = False
                    e.vibrando = False
                    confirmar(e.alarme_med)
                    e.tela = "ok"
                if "voltar" in b and b["voltar"].collidepoint(ev.pos):
                    e.tela = "relogio"
                    e.alarme_med = None
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_t and e.agenda and not e.alarme_ativo:
                    alarmar(e.agenda[0])
                if ev.key == pygame.K_s:
                    buscar()

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()